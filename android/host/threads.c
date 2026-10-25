/* Guest threads, the machine lock, handles and Win32 synchronization.
 *
 * One host pthread per guest thread. Only the thread holding the machine runs
 * lifted code or touches the global register file; a host call that blocks
 * releases the machine around the wait (void_blocking_begin/end), and lifted
 * loops hand it over periodically (recomp_yield_hook), as native32 did on
 * Windows. The lock is a FIFO ticket lock so a yield really passes the
 * machine to a waiting thread instead of re-acquiring it immediately. */
#define _GNU_SOURCE
#include "host.h"
#include <errno.h>
#include <sched.h>
#include <setjmp.h>
#include <time.h>
#include <unistd.h>

#define TLS_SLOTS 1088
#define STATIC_TLS_MODULES 64
#define GUEST_STACK_DEFAULT (1u << 20)
#define HOST_STACK_SIZE (32u << 20)

struct void_thread {
    void_regs regs;
    int depth;
    uint32_t id;
    uint32_t tib, peb;
    uint32_t stack_lo, stack_hi;
    uint32_t last_error;
    uint32_t tls[TLS_SLOTS];
    uint32_t static_tls;
    void_object *object;
    uint32_t start, param;
    uint32_t exit_code;
    int suspended;
    int guest_owned;                 /* created by CreateThread */
    jmp_buf exit_jb;
    int exit_armed;
    pthread_t pt;
    struct void_thread *next_thread;   /* every guest thread, for TLS slot resets */
};

static struct void_thread *all_threads;
static pthread_mutex_t threads_lock = PTHREAD_MUTEX_INITIALIZER;

static __thread void_thread *t_self;
static pthread_mutex_t mlock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t mcond = PTHREAD_COND_INITIALIZER;
static uint64_t ticket_next, ticket_serving;
static uint32_t next_thread_id = 0x104;
static uint32_t peb_va;
static uint8_t tls_used[TLS_SLOTS];
static pthread_mutex_t tls_lock = PTHREAD_MUTEX_INITIALIZER;

/* PE static TLS uses fs:2C; TlsAlloc uses the independent TEB+E10 slots. */
typedef struct {
    uint32_t base, raw, raw_size, total_size, alignment, callbacks;
    int attached;
} static_tls_module;
static static_tls_module static_tls_modules[STATIC_TLS_MODULES];
static uint32_t static_tls_count;
/* shortcut: mapped modules and thread storage stay resident, matching this host; add reclamation with module unloading. */

static void tls_thread_slot(void_thread *t, uint32_t index)
{
    const static_tls_module *m = &static_tls_modules[index];
    uint32_t allocation = void_galloc(m->total_size + m->alignment - 1);
    if (!allocation) void_fatal("static TLS allocation failed");
    uint32_t block = (allocation + m->alignment - 1) & ~(m->alignment - 1);
    memset(GPTR(block), 0, m->total_size);
    if (m->raw_size) memcpy(GPTR(block), GPTR(m->raw), m->raw_size);
    MEM32(t->static_tls + 4 * index) = block;
}

static void tls_thread_init(void_thread *t)
{
    t->static_tls = void_galloc(4 * STATIC_TLS_MODULES);
    if (!t->static_tls) void_fatal("static TLS vector allocation failed");
    MEM32(t->tib + 0x2C) = t->static_tls;
    for (uint32_t i = 0; i < static_tls_count; ++i) tls_thread_slot(t, i);
}

int void_tls_register(uint32_t base, uint32_t directory)
{
    if (!directory) return 1;
    if (!void_vm_readable(directory, 24)) return 0;
    uint32_t raw = MEM32(directory), end = MEM32(directory + 4);
    uint32_t index = MEM32(directory + 8), callbacks = MEM32(directory + 12);
    uint32_t zero_fill = MEM32(directory + 16), align_code = (MEM32(directory + 20) >> 20) & 15;
    uint64_t total = (uint64_t)end - raw + zero_fill;
    if (end < raw || total > UINT32_MAX - 8191u || align_code > 14 ||
        (end != raw && !void_vm_readable(raw, end - raw)) || !void_vm_writable(index, 4)) return 0;
    if (callbacks) {
        uint32_t n;
        for (n = 0; n < 1024; ++n) {
            uint64_t slot = (uint64_t)callbacks + 4 * n;
            if (slot + 4 > 0x100000000ull || !void_vm_readable((uint32_t)slot, 4)) return 0;
            if (!MEM32((uint32_t)slot)) break;
        }
        if (n == 1024) return 0;
    }
    pthread_mutex_lock(&threads_lock);
    for (uint32_t i = 0; i < static_tls_count; ++i) {
        if (static_tls_modules[i].base == base) { MEM32(index) = i; pthread_mutex_unlock(&threads_lock); return 1; }
    }
    if (static_tls_count == STATIC_TLS_MODULES) { pthread_mutex_unlock(&threads_lock); return 0; }
    uint32_t slot = static_tls_count++;
    static_tls_modules[slot] = (static_tls_module){ base, raw, end - raw,
        total ? (uint32_t)total : 1, align_code ? 1u << (align_code - 1) : 16, callbacks, 0 };
    MEM32(index) = slot;
    for (void_thread *t = all_threads; t; t = t->next_thread) tls_thread_slot(t, slot);
    pthread_mutex_unlock(&threads_lock);
    return 1;
}

void void_tls_callbacks(uint32_t base, uint32_t reason)
{
    for (uint32_t i = 0; i < static_tls_count; ++i) {
        static_tls_module *m = &static_tls_modules[i];
        if (m->base != base) continue;
        if (reason == 1) m->attached = 1;
        else if (reason == 0) m->attached = 0;
        uint32_t args[3] = { base, reason, 0 };
        if (m->callbacks) {
            for (uint32_t n = 0; n < 1024; ++n) {
                uint64_t slot = (uint64_t)m->callbacks + 4 * n;
                if (slot + 4 > 0x100000000ull || !void_vm_readable((uint32_t)slot, 4))
                    void_fatal("invalid static TLS callback list for %08X", base);
                uint32_t callback = MEM32((uint32_t)slot);
                if (!callback) return;
                void_call_guest(callback, 3, args, 1);
            }
            void_fatal("unterminated static TLS callback list for %08X", base);
        }
        return;
    }
}

static void tls_thread_callbacks(uint32_t reason)
{
    for (uint32_t n = 0; n < static_tls_count; ++n) {
        uint32_t i = reason == 3 ? static_tls_count - 1 - n : n;
        if (static_tls_modules[i].attached) void_tls_callbacks(static_tls_modules[i].base, reason);
    }
}

/* ---------------------------------------------------------- machine lock */
/* Time this thread spent waiting for the machine (frame statistics). */
static __thread uint64_t t_lock_wait_ns;
uint64_t void_lock_wait_ns(void) { return t_lock_wait_ns; }

static uint64_t now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static void pin_guest_thread(void);

static void machine_acquire(void)
{
    pthread_mutex_lock(&mlock);
    uint64_t ticket = ticket_next++;
    if (ticket != ticket_serving) {
        uint64_t start = now_ns();
        while (ticket != ticket_serving) pthread_cond_wait(&mcond, &mlock);
        t_lock_wait_ns += now_ns() - start;
    }
    pthread_mutex_unlock(&mlock);
    /* Android may reset affinity when the app changes lifecycle state. */
    pin_guest_thread();
}

static void machine_release(void)
{
    pthread_mutex_lock(&mlock);
    ++ticket_serving;
    pthread_cond_broadcast(&mcond);
    pthread_mutex_unlock(&mlock);
}

static int machine_contended(void)
{
    /* Racy read is fine: a missed waiter is picked up at the next edge. */
    return __atomic_load_n(&ticket_next, __ATOMIC_RELAXED) - __atomic_load_n(&ticket_serving, __ATOMIC_RELAXED) > 1;
}

static uint32_t make_peb(void)
{
    if (peb_va) return peb_va;
    peb_va = void_galloc(0x1000);
    MEM8(peb_va + 2) = 0;                          /* BeingDebugged */
    MEM32(peb_va + 8) = void_module_exe_base();    /* ImageBaseAddress */
    MEM32(peb_va + 0x18) = void_process_heap();    /* ProcessHeap */
    MEM32(peb_va + 0x64) = 8;                      /* NumberOfProcessors */
    MEM32(peb_va + 0xA4) = 6;                      /* OSMajorVersion */
    MEM32(peb_va + 0xA8) = 2;                      /* OSMinorVersion */
    MEM16(peb_va + 0xAC) = 9200;                   /* OSBuildNumber */
    MEM32(peb_va + 0xB0) = 2;                      /* OSPlatformId: VER_PLATFORM_WIN32_NT */
    return peb_va;
}

static void_thread *thread_new(uint32_t guest_stack)
{
    void_thread *t = (void_thread *)calloc(1, sizeof *t);
    if (!t) void_fatal("thread allocation failed");
    if (!guest_stack) guest_stack = GUEST_STACK_DEFAULT;
    guest_stack = (guest_stack + 0xFFFFu) & ~0xFFFFu;
    uint32_t lo = void_vm_alloc(0, guest_stack, 0x3000u, 0x04u);
    uint32_t tib = void_vm_alloc(0, 0x1000, 0x3000u, 0x04u);
    if (!lo || !tib) void_fatal("guest stack/TIB allocation failed");
    pthread_mutex_lock(&mlock);
    t->id = next_thread_id;
    next_thread_id += 4;
    pthread_mutex_unlock(&mlock);
    t->stack_lo = lo;
    t->stack_hi = lo + guest_stack;
    t->tib = tib;
    MEM32(tib + 0x00) = 0xFFFFFFFFu;        /* ExceptionList: end of chain */
    MEM32(tib + 0x04) = t->stack_hi;        /* StackBase */
    MEM32(tib + 0x08) = t->stack_lo;        /* StackLimit */
    MEM32(tib + 0x18) = tib;                /* Self */
    MEM32(tib + 0x20) = 0x100;              /* ClientId.UniqueProcess */
    MEM32(tib + 0x24) = t->id;              /* ClientId.UniqueThread */
    MEM32(tib + 0x30) = make_peb();         /* ProcessEnvironmentBlock */
    /* The bridge-style headroom native32 kept above the first frame. */
    t->regs.esp = t->stack_hi - 0x100;
    t->regs.fs = tib;
    t->regs.fpu_cw = 0x027F;
    t->regs.fp_round_mask = t->regs.fp_store_mask = ~0ull;   /* fp_cw_masks(0x027F) */
    t->regs.fpu_cmp = 1;
    t->regs.mxcsr = 0x1F80;
    pthread_mutex_lock(&threads_lock);
    tls_thread_init(t);
    t->next_thread = all_threads;
    all_threads = t;
    pthread_mutex_unlock(&threads_lock);
    return t;
}

/* TlsAlloc and TlsFree zero the slot in every thread, as Windows does: a
 * module that frees its index and one that allocates it next must not see a
 * stale value (the MSVC CRT keeps a function pointer in its slot). */
static void tls_clear_everywhere(uint32_t index)
{
    pthread_mutex_lock(&threads_lock);
    for (void_thread *t = all_threads; t; t = t->next_thread) {
        t->tls[index] = 0;
        if (index < 64) MEM32(t->tib + 0xE10 + 4 * index) = 0;
    }
    pthread_mutex_unlock(&threads_lock);
}

void_thread *void_thread_self(void)
{
    if (!t_self) {
        /* A host thread entering the guest for the first time (the launcher
         * thread, a timer or audio callback) becomes a guest thread. */
        t_self = thread_new(GUEST_STACK_DEFAULT);
        t_self->object = void_object_new(VOID_OBJ_THREAD, 0);
        t_self->pt = pthread_self();
        pin_guest_thread();
    }
    return t_self;
}

void void_machine_enter(void)
{
    void_thread *t = void_thread_self();
    if (t->depth++ == 0) {
        machine_acquire();
        void_regs_load(&t->regs);
    }
}

void void_machine_leave(void)
{
    void_thread *t = t_self;
    if (!t || t->depth <= 0) void_fatal("machine leave without a claim");
    if (--t->depth == 0) {
        void_regs_save(&t->regs);
        machine_release();
    }
}

void void_blocking_begin(void)
{
    void_thread *t = t_self;
    if (!t || t->depth <= 0) void_fatal("blocking call outside the guest machine");
    void_regs_save(&t->regs);
    machine_release();
}

void void_blocking_end(void)
{
    void_thread *t = t_self;
    machine_acquire();
    void_regs_load(&t->regs);
}

static void yield_hook(void)
{
    if (!machine_contended()) return;
    void_thread *t = t_self;
    if (!t || t->depth <= 0) void_fatal("yield outside the guest machine");
    void_regs_save(&t->regs);
    pthread_mutex_lock(&mlock);
    /* Reserve our return before another thread can run. Releasing first lets
     * the next owner mistake a preempted yielding thread for no contender. */
    uint64_t ticket = ticket_next++;
    uint64_t start = now_ns();
    ++ticket_serving;
    pthread_cond_broadcast(&mcond);
    while (ticket != ticket_serving) pthread_cond_wait(&mcond, &mlock);
    t_lock_wait_ns += now_ns() - start;
    pthread_mutex_unlock(&mlock);
    pin_guest_thread();
    void_regs_load(&t->regs);
}

uint32_t void_thread_id(void) { return void_thread_self()->id; }
uint32_t void_get_last_error(void) { return void_thread_self()->last_error; }
void void_set_last_error(uint32_t e) { void_thread_self()->last_error = e; MEM32(void_thread_self()->tib + 0x34) = e; }

/* ---------------------------------------------------- guest call helpers */
uint32_t void_call_guest(uint32_t va, int nargs, const uint32_t *args, int stdcall_pops)
{
    recomp_func_t fn = void_resolve(va);
    uint32_t entry_esp = g_esp, caller = g_cur_func;
    uint32_t ebx = g_ebx, esi = g_esi, edi = g_edi, ebp = g_ebp;
    for (int i = nargs; i > 0; --i) PUSH32(g_esp, args[i - 1]);
    PUSH32(g_esp, RECOMP_RETADDR);
    fn();
    uint32_t expected = stdcall_pops ? entry_esp : entry_esp - 4u * (uint32_t)nargs;
    /* A thread root has no guest caller; old FMOD workers return with plain RET. */
    int thread_cdecl = stdcall_pops == 2 && nargs == 1 && g_esp == entry_esp - 4u;
    if (g_esp != expected && !thread_cdecl) {
        void_log("[void] guest call %08X: ESP %08X, expected %08X (args %d, %s)", va, g_esp, expected, nargs,
            stdcall_pops ? "stdcall" : "cdecl");
        void_lift_trap(va, "guest callback stack imbalance");
    }
    g_esp = entry_esp;
    g_ebx = ebx; g_esi = esi; g_edi = edi; g_ebp = ebp;
    g_cur_func = caller;
    return g_eax;
}

uint32_t void_call_guest_this(uint32_t va, uint32_t this_ptr, int nargs, const uint32_t *args)
{
    g_ecx = this_ptr;
    return void_call_guest(va, nargs, args, 1);
}

/* --------------------------------------------------------------- handles */
#define MAX_HANDLES 65536
static void_object *handles[MAX_HANDLES];
static pthread_mutex_t handle_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t wait_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wait_cond = PTHREAD_COND_INITIALIZER;
static uint32_t handle_hint;

void_object *void_object_new(int kind, size_t extra)
{
    void_object *o = (void_object *)calloc(1, sizeof *o + extra);
    if (!o) void_fatal("object allocation failed");
    o->kind = kind;
    o->refs = 1;
    if (extra) o->data = (void *)(o + 1);
    return o;
}

void void_object_release(void_object *o)
{
    if (!o) return;
    pthread_mutex_lock(&handle_lock);
    int last = --o->refs == 0;
    pthread_mutex_unlock(&handle_lock);
    if (last) {
        if (o->destroy) o->destroy(o);
        free(o);
    }
}

uint32_t void_handle_new(void_object *o)
{
    pthread_mutex_lock(&handle_lock);
    for (uint32_t n = 0; n < MAX_HANDLES; ++n) {
        uint32_t i = (handle_hint + n) % MAX_HANDLES;
        if (!i) continue;
        if (!handles[i]) {
            handles[i] = o;
            handle_hint = i + 1;
            pthread_mutex_unlock(&handle_lock);
            return 0x1000u + 4u * i;
        }
    }
    pthread_mutex_unlock(&handle_lock);
    void_fatal("handle table full");
}

static uint32_t handle_index(uint32_t h)
{
    if (h < 0x1000u || (h & 3u)) return 0;
    uint32_t i = (h - 0x1000u) / 4u;
    return i < MAX_HANDLES ? i : 0;
}

void_object *void_handle_get(uint32_t h, int kind)
{
    if (h == 0xFFFFFFFEu) {           /* GetCurrentThread pseudo-handle */
        void_object *o = void_thread_self()->object;
        return (kind == VOID_OBJ_NONE || kind == VOID_OBJ_THREAD) ? o : NULL;
    }
    uint32_t i = handle_index(h);
    pthread_mutex_lock(&handle_lock);
    void_object *o = i ? handles[i] : NULL;
    pthread_mutex_unlock(&handle_lock);
    if (o && kind != VOID_OBJ_NONE && o->kind != kind) return NULL;
    return o;
}

int void_handle_close(uint32_t h)
{
    uint32_t i = handle_index(h);
    pthread_mutex_lock(&handle_lock);
    void_object *o = i ? handles[i] : NULL;
    if (o) handles[i] = NULL;
    pthread_mutex_unlock(&handle_lock);
    if (!o) return 0;
    void_object_release(o);
    return 1;
}

uint32_t void_handle_dup(uint32_t h)
{
    void_object *o = void_handle_get(h, VOID_OBJ_NONE);
    if (!o) return 0;
    pthread_mutex_lock(&handle_lock);
    ++o->refs;
    pthread_mutex_unlock(&handle_lock);
    return void_handle_new(o);
}

/* ---------------------------------------------------------------- waiting */
static int object_ready(void_object *o, uint32_t tid)
{
    switch (o->kind) {
    case VOID_OBJ_EVENT: case VOID_OBJ_THREAD: case VOID_OBJ_PROCESS: case VOID_OBJ_TIMER:
        return o->signaled;
    case VOID_OBJ_SEMAPHORE:
        return o->count > 0;
    case VOID_OBJ_MUTEX:
        return o->owner == 0 || o->owner == tid;
    default:
        return 1;                     /* files and others: always signaled */
    }
}

static void object_consume(void_object *o, uint32_t tid)
{
    switch (o->kind) {
    case VOID_OBJ_EVENT: case VOID_OBJ_TIMER:
        if (!o->manual_reset) o->signaled = 0;
        break;
    case VOID_OBJ_SEMAPHORE:
        --o->count;
        break;
    case VOID_OBJ_MUTEX:
        o->owner = tid;
        ++o->recursion;
        break;
    default:
        break;
    }
}

void void_object_signal(void_object *o)
{
    pthread_mutex_lock(&wait_lock);
    o->signaled = 1;
    pthread_cond_broadcast(&wait_cond);
    pthread_mutex_unlock(&wait_lock);
}

void void_wait_broadcast(void)
{
    pthread_mutex_lock(&wait_lock);
    pthread_cond_broadcast(&wait_cond);
    pthread_mutex_unlock(&wait_lock);
}

/* Optional extra wake condition (MsgWaitForMultipleObjects: queued input). */
typedef int (*void_wait_extra)(void *);

static uint32_t wait_core(int count, void_object **objects, int wait_all, uint32_t timeout,
    void_wait_extra extra, void *extra_arg)
{
    uint32_t tid = void_thread_self()->id;
    struct timespec deadline;
    if (timeout != INFINITE_) {
        clock_gettime(CLOCK_REALTIME, &deadline);
        deadline.tv_sec += timeout / 1000u;
        deadline.tv_nsec += (long)(timeout % 1000u) * 1000000L;
        if (deadline.tv_nsec >= 1000000000L) { deadline.tv_sec++; deadline.tv_nsec -= 1000000000L; }
    }
    int blocking = timeout != 0;
    if (blocking) void_blocking_begin();
    pthread_mutex_lock(&wait_lock);
    uint32_t result = WAIT_TIMEOUT_;
    for (;;) {
        if (wait_all) {
            int all = 1;
            for (int i = 0; i < count; ++i) if (!object_ready(objects[i], tid)) { all = 0; break; }
            if (all) {
                for (int i = 0; i < count; ++i) object_consume(objects[i], tid);
                result = WAIT_OBJECT_0_;
                break;
            }
        } else {
            int hit = -1;
            for (int i = 0; i < count; ++i) if (object_ready(objects[i], tid)) { hit = i; break; }
            if (hit >= 0) {
                object_consume(objects[hit], tid);
                result = WAIT_OBJECT_0_ + (uint32_t)hit;
                break;
            }
        }
        if (extra && extra(extra_arg)) { result = WAIT_OBJECT_0_ + (uint32_t)count; break; }
        if (!timeout) break;
        int rc = timeout == INFINITE_ ? pthread_cond_wait(&wait_cond, &wait_lock)
                                      : pthread_cond_timedwait(&wait_cond, &wait_lock, &deadline);
        if (rc == ETIMEDOUT) {
            result = WAIT_TIMEOUT_;
            /* One last check: a signal may have raced the timeout. */
            timeout = 0;
        }
    }
    pthread_mutex_unlock(&wait_lock);
    if (blocking) void_blocking_end();
    return result;
}

uint32_t void_wait(int count, const uint32_t *hs, int wait_all, uint32_t timeout)
{
    void_object *objects[64];
    if (count <= 0 || count > 64) { void_set_last_error(ERROR_INVALID_PARAMETER_); return WAIT_FAILED_; }
    for (int i = 0; i < count; ++i) {
        objects[i] = void_handle_get(hs[i], VOID_OBJ_NONE);
        if (!objects[i]) {
            void_log("[void] wait on invalid handle %08X (caller %08X)", hs[i], g_cur_func);
            void_set_last_error(ERROR_INVALID_HANDLE_);
            return WAIT_FAILED_;
        }
    }
    return wait_core(count, objects, wait_all, timeout, NULL, NULL);
}

uint32_t void_wait_extra_cond(int count, const uint32_t *hs, uint32_t timeout, int (*extra)(void *), void *arg)
{
    void_object *objects[64];
    if (count < 0 || count > 63) { void_set_last_error(ERROR_INVALID_PARAMETER_); return WAIT_FAILED_; }
    for (int i = 0; i < count; ++i) {
        objects[i] = void_handle_get(hs[i], VOID_OBJ_NONE);
        if (!objects[i]) { void_set_last_error(ERROR_INVALID_HANDLE_); return WAIT_FAILED_; }
    }
    return wait_core(count, objects, 0, timeout, extra, arg);
}

/* ------------------------------------------------------------- kernel32 */
#define K32 "kernel32.dll"

WINAPI_EXPORT(K32, GetLastError, 0) { return void_get_last_error(); }
WINAPI_EXPORT(K32, SetLastError, 1) { void_set_last_error(ARG(0)); return 0; }
WINAPI_EXPORT(K32, GetCurrentThreadId, 0) { return void_thread_id(); }
WINAPI_EXPORT(K32, GetCurrentThread, 0) { return 0xFFFFFFFEu; }
WINAPI_EXPORT(K32, GetCurrentProcess, 0) { return 0xFFFFFFFFu; }
WINAPI_EXPORT(K32, GetCurrentProcessId, 0) { return 0x100u; }

WINAPI_EXPORT(K32, TlsAlloc, 0)
{
    pthread_mutex_lock(&tls_lock);
    for (uint32_t i = 0; i < TLS_SLOTS; ++i) {
        if (!tls_used[i]) {
            tls_used[i] = 1;
            pthread_mutex_unlock(&tls_lock);
            tls_clear_everywhere(i);
            return i;
        }
    }
    pthread_mutex_unlock(&tls_lock);
    return 0xFFFFFFFFu;              /* TLS_OUT_OF_INDEXES */
}

WINAPI_EXPORT(K32, TlsFree, 1)
{
    uint32_t i = ARG(0);
    if (i >= TLS_SLOTS || !tls_used[i]) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    tls_clear_everywhere(i);
    tls_used[i] = 0;
    return 1;
}

WINAPI_EXPORT(K32, TlsGetValue, 1)
{
    uint32_t i = ARG(0);
    if (i >= TLS_SLOTS) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    void_set_last_error(0);
    return void_thread_self()->tls[i];
}

WINAPI_EXPORT(K32, TlsSetValue, 2)
{
    uint32_t i = ARG(0);
    if (i >= TLS_SLOTS) { void_set_last_error(ERROR_INVALID_PARAMETER_); return 0; }
    void_thread *t = void_thread_self();
    t->tls[i] = ARG(1);
    if (i < 64) MEM32(t->tib + 0xE10 + 4 * i) = ARG(1);
    return 1;
}

/* Critical sections live in guest memory; contention waits on a generation
 * counter so an unlock between the owner check and the wait is never lost.
 * cs_waiters counts threads parked on it: a waiter registers while it still
 * holds the machine and only then lets it go, and a release runs on the
 * machine too, so a release that sees no waiters skips the wake-up (the
 * game's CRT takes a few thousand uncontended sections a frame). */
static pthread_mutex_t cs_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cs_cond = PTHREAD_COND_INITIALIZER;
static uint64_t cs_generation;
static uint32_t cs_waiters;

static void cs_init(uint32_t cs, uint32_t spin)
{
    MEM32(cs + 0) = 0xFFFFFFFFu;     /* DebugInfo: none, as Windows 8+ leaves it */
    MEM32(cs + 4) = 0xFFFFFFFFu;     /* LockCount: free */
    MEM32(cs + 8) = 0;               /* RecursionCount */
    MEM32(cs + 12) = 0;              /* OwningThread */
    MEM32(cs + 16) = 0;              /* LockSemaphore */
    MEM32(cs + 20) = spin;           /* SpinCount */
}

WINAPI_EXPORT(K32, InitializeCriticalSection, 1) { cs_init(ARG(0), 0); return 0; }
WINAPI_EXPORT(K32, InitializeCriticalSectionAndSpinCount, 2) { cs_init(ARG(0), ARG(1)); return 1; }
WINAPI_EXPORT(K32, DeleteCriticalSection, 1) { MEM32(ARG(0) + 12) = 0; MEM32(ARG(0) + 8) = 0; return 0; }

static void cs_enter(uint32_t cs)
{
    uint32_t tid = void_thread_id();
    for (;;) {
        uint32_t owner = MEM32(cs + 12);
        if (!owner) {
            MEM32(cs + 12) = tid;
            MEM32(cs + 8) = 1;
            MEM32(cs + 4) = 0;
            return;
        }
        if (owner == tid) {
            MEM32(cs + 8) += 1;
            MEM32(cs + 4) += 1;
            return;
        }
        pthread_mutex_lock(&cs_lock);
        uint64_t seen = cs_generation;
        __atomic_add_fetch(&cs_waiters, 1, __ATOMIC_RELEASE);
        pthread_mutex_unlock(&cs_lock);
        void_blocking_begin();
        pthread_mutex_lock(&cs_lock);
        while (cs_generation == seen) pthread_cond_wait(&cs_cond, &cs_lock);
        __atomic_sub_fetch(&cs_waiters, 1, __ATOMIC_RELEASE);
        pthread_mutex_unlock(&cs_lock);
        void_blocking_end();
    }
}

static void cs_leave(uint32_t cs)
{
    uint32_t tid = void_thread_id();
    if (MEM32(cs + 12) != tid) {
        void_log("[void] LeaveCriticalSection(%08X) by non-owner %u (owner %u, caller %08X)",
            cs, tid, MEM32(cs + 12), g_cur_func);
        return;
    }
    if (--MEM32(cs + 8) == 0) {
        MEM32(cs + 12) = 0;
        MEM32(cs + 4) = 0xFFFFFFFFu;
        if (__atomic_load_n(&cs_waiters, __ATOMIC_ACQUIRE)) {
            pthread_mutex_lock(&cs_lock);
            ++cs_generation;
            pthread_cond_broadcast(&cs_cond);
            pthread_mutex_unlock(&cs_lock);
        }
    } else {
        MEM32(cs + 4) -= 1;
    }
}

WINAPI_EXPORT(K32, EnterCriticalSection, 1) { cs_enter(ARG(0)); return 0; }
WINAPI_EXPORT(K32, LeaveCriticalSection, 1) { cs_leave(ARG(0)); return 0; }
WINAPI_EXPORT(K32, TryEnterCriticalSection, 1)
{
    uint32_t cs = ARG(0), tid = void_thread_id(), owner = MEM32(cs + 12);
    if (owner && owner != tid) return 0;
    cs_enter(cs);
    return 1;
}

/* Interlocked operations run under the machine lock: plain arithmetic is
 * already atomic with respect to every other guest thread. */
WINAPI_EXPORT(K32, InterlockedIncrement, 1) { return ++MEM32(ARG(0)); }
WINAPI_EXPORT(K32, InterlockedDecrement, 1) { return --MEM32(ARG(0)); }
WINAPI_EXPORT(K32, InterlockedExchange, 2) { uint32_t old = MEM32(ARG(0)); MEM32(ARG(0)) = ARG(1); return old; }
WINAPI_EXPORT(K32, InterlockedExchangeAdd, 2) { uint32_t old = MEM32(ARG(0)); MEM32(ARG(0)) = old + ARG(1); return old; }
WINAPI_EXPORT(K32, InterlockedCompareExchange, 3)
{
    uint32_t old = MEM32(ARG(0));
    if (old == ARG(2)) MEM32(ARG(0)) = ARG(1);
    return old;
}

/* Events, mutexes, semaphores. Names are accepted and ignored except for
 * the single-instance mutex the launcher creates, which is process-local. */
static uint32_t create_event(int manual, int initial)
{
    void_object *o = void_object_new(VOID_OBJ_EVENT, 0);
    o->manual_reset = manual;
    o->signaled = initial;
    return void_handle_new(o);
}

WINAPI_EXPORT(K32, CreateEventA, 4) { return create_event(ARG(1) != 0, ARG(2) != 0); }
WINAPI_EXPORT(K32, CreateEventW, 4) { return create_event(ARG(1) != 0, ARG(2) != 0); }

static uint32_t event_op(uint32_t h, int op)
{
    void_object *o = void_handle_get(h, VOID_OBJ_EVENT);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    pthread_mutex_lock(&wait_lock);
    if (op == 1) { o->signaled = 1; pthread_cond_broadcast(&wait_cond); }
    else if (op == 0) o->signaled = 0;
    else { o->signaled = 1; pthread_cond_broadcast(&wait_cond); }
    pthread_mutex_unlock(&wait_lock);
    if (op == 2) {
        /* PulseEvent: release current waiters, then reset. */
        void_blocking_begin();
        sched_yield();
        void_blocking_end();
        pthread_mutex_lock(&wait_lock);
        o->signaled = 0;
        pthread_mutex_unlock(&wait_lock);
    }
    return 1;
}

WINAPI_EXPORT(K32, SetEvent, 1) { return event_op(ARG(0), 1); }
WINAPI_EXPORT(K32, ResetEvent, 1) { return event_op(ARG(0), 0); }
WINAPI_EXPORT(K32, PulseEvent, 1) { return event_op(ARG(0), 2); }

static uint32_t create_mutex(int initial_owner)
{
    void_object *o = void_object_new(VOID_OBJ_MUTEX, 0);
    if (initial_owner) { o->owner = void_thread_id(); o->recursion = 1; }
    void_set_last_error(0);
    return void_handle_new(o);
}

WINAPI_EXPORT(K32, CreateMutexA, 3) { return create_mutex(ARG(1) != 0); }
WINAPI_EXPORT(K32, CreateMutexW, 3) { return create_mutex(ARG(1) != 0); }
WINAPI_EXPORT(K32, ReleaseMutex, 1)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_MUTEX);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    pthread_mutex_lock(&wait_lock);
    if (o->owner != void_thread_id()) { pthread_mutex_unlock(&wait_lock); void_set_last_error(ERROR_NOT_OWNER_); return 0; }
    if (--o->recursion == 0) { o->owner = 0; pthread_cond_broadcast(&wait_cond); }
    pthread_mutex_unlock(&wait_lock);
    return 1;
}

static uint32_t create_semaphore(int initial, int maximum)
{
    void_object *o = void_object_new(VOID_OBJ_SEMAPHORE, 0);
    o->count = initial;
    o->max_count = maximum;
    return void_handle_new(o);
}

WINAPI_EXPORT(K32, CreateSemaphoreA, 4) { return create_semaphore((int)ARG(1), (int)ARG(2)); }
WINAPI_EXPORT(K32, CreateSemaphoreW, 4) { return create_semaphore((int)ARG(1), (int)ARG(2)); }
WINAPI_EXPORT(K32, ReleaseSemaphore, 3)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_SEMAPHORE);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    pthread_mutex_lock(&wait_lock);
    int previous = o->count;
    if ((int)ARG(1) <= 0 || previous + (int)ARG(1) > o->max_count) {
        pthread_mutex_unlock(&wait_lock);
        void_set_last_error(0x12Au);  /* ERROR_TOO_MANY_POSTS */
        return 0;
    }
    o->count += (int)ARG(1);
    pthread_cond_broadcast(&wait_cond);
    pthread_mutex_unlock(&wait_lock);
    if (ARG(2)) MEM32(ARG(2)) = (uint32_t)previous;
    return 1;
}

WINAPI_EXPORT(K32, WaitForSingleObject, 2)
{
    uint32_t h = ARG(0);
    return void_wait(1, &h, 0, ARG(1));
}

WINAPI_EXPORT(K32, WaitForSingleObjectEx, 3)
{
    uint32_t h = ARG(0);
    return void_wait(1, &h, 0, ARG(1));
}

WINAPI_EXPORT(K32, WaitForMultipleObjects, 4)
{
    uint32_t count = ARG(0), list[64];
    if (!count || count > 64) { void_set_last_error(ERROR_INVALID_PARAMETER_); return WAIT_FAILED_; }
    for (uint32_t i = 0; i < count; ++i) list[i] = MEM32(ARG(1) + 4 * i);
    return void_wait((int)count, list, ARG(2) != 0, ARG(3));
}

static void sleep_ms(uint32_t ms)
{
    if (!ms) {
        if (machine_contended()) yield_hook();
        else sched_yield();
        return;
    }
    void_blocking_begin();
    struct timespec ts = { (time_t)(ms / 1000u), (long)(ms % 1000u) * 1000000L };
    while (nanosleep(&ts, &ts) && errno == EINTR) {}
    void_blocking_end();
}

WINAPI_EXPORT(K32, Sleep, 1) { sleep_ms(ARG(0)); return 0; }
WINAPI_EXPORT(K32, SleepEx, 2) { sleep_ms(ARG(0)); return 0; }
WINAPI_EXPORT(K32, SwitchToThread, 0) { sleep_ms(0); return 1; }

/* ---------------------------------------------------------------- threads */
static void thread_object_destroy(void_object *o) { (void)o; }

/* Every guest thread waits while another holds the machine, so a holder on a
 * little core stretches everyone's time: on the Helio G90T the Sound.dll
 * stream thread decoded Vorbis on an A55 (cpu_capacity 435 against the A76's
 * 1024) while the main thread waited for the machine. Guest threads run on
 * the biggest cores (cpu_capacity, else the highest maximum frequency).
 * Host threads may inherit their creator's mask; this code does not restore
 * a default mask for the mixer or workers created inside a driver.
 * VOID_BIG_CORES=0 turns this off. */
static cpu_set_t big_cores;
static int big_cores_count;
static pthread_once_t big_cores_once = PTHREAD_ONCE_INIT;

static long cpu_value(int cpu, const char *name)
{
    char path[96];
    snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/%s", cpu, name);
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    long value = -1;
    if (fscanf(f, "%ld", &value) != 1) value = -1;
    fclose(f);
    return value;
}

static void big_cores_init(void)
{
    const char *env = getenv("VOID_BIG_CORES");
    if (env && *env == '0') return;
    long value[CPU_SETSIZE];
    int cpus = 0, use_capacity = cpu_value(0, "cpu_capacity") > 0;
    for (; cpus < CPU_SETSIZE; ++cpus) {
        value[cpus] = use_capacity ? cpu_value(cpus, "cpu_capacity") : cpu_value(cpus, "cpufreq/cpuinfo_max_freq");
        if (value[cpus] <= 0) break;
    }
    long best = 0, worst = 0;
    for (int i = 0; i < cpus; ++i) {
        if (value[i] > best) best = value[i];
        if (!worst || value[i] < worst) worst = value[i];
    }
    if (cpus < 2 || best == worst) return;       /* homogeneous or unknown: leave the scheduler alone */
    CPU_ZERO(&big_cores);
    for (int i = 0; i < cpus; ++i) if (value[i] == best) { CPU_SET(i, &big_cores); ++big_cores_count; }
    char list[64] = "";
    for (int i = 0, n = 0; i < cpus && n < 56; ++i)
        if (CPU_ISSET(i, &big_cores)) n += snprintf(list + n, sizeof list - (size_t)n, "%s%d", n ? "," : "", i);
    void_log("[void] guest threads run on cpus %s (%s %ld; others %ld)", list,
        use_capacity ? "capacity" : "max frequency", best, worst);
}

static void pin_guest_thread(void)
{
    pthread_once(&big_cores_once, big_cores_init);
    if (big_cores_count) sched_setaffinity(0, sizeof big_cores, &big_cores);
}

static void *thread_main(void *arg)
{
    void_thread *t = (void_thread *)arg;
    t_self = t;
    pin_guest_thread();
    if (t->suspended) {
        pthread_mutex_lock(&wait_lock);
        while (t->suspended) pthread_cond_wait(&wait_cond, &wait_lock);
        pthread_mutex_unlock(&wait_lock);
    }
    void_machine_enter();
    if (!setjmp(t->exit_jb)) {
        t->exit_armed = 1;
        uint32_t args[1] = { t->param };
        g_esp = t->stack_hi - 0x100;
        g_fs_base = t->tib;
        tls_thread_callbacks(2);            /* DLL_THREAD_ATTACH */
        t->exit_code = void_call_guest(t->start, 1, args, 2);
    }
    t->exit_armed = 0;
    g_esp = t->stack_hi - 0x100;
    g_fs_base = t->tib;
    tls_thread_callbacks(3);                /* DLL_THREAD_DETACH, including ExitThread */
    VLOG("[void] guest thread %u exits with %u", t->id, t->exit_code);
    void_machine_leave();
    pthread_mutex_lock(&wait_lock);
    t->object->signaled = 1;
    t->object->count = (int)t->exit_code;
    pthread_cond_broadcast(&wait_cond);
    pthread_mutex_unlock(&wait_lock);
    void_object_release(t->object);
    return NULL;
}

WINAPI_EXPORT(K32, CreateThread, 6)
{
    uint32_t stack = ARG(1), start = ARG(2), param = ARG(3), flags = ARG(4), tid_out = ARG(5);
    void_thread *t = thread_new((flags & 0x10000u) ? stack : (stack > GUEST_STACK_DEFAULT ? stack : 0));
    t->start = start;
    t->param = param;
    t->guest_owned = 1;
    t->suspended = (flags & 4u) != 0;     /* CREATE_SUSPENDED */
    t->object = void_object_new(VOID_OBJ_THREAD, 0);
    t->object->data = t;
    t->object->destroy = thread_object_destroy;
    t->object->refs = 2;                  /* the handle and the running thread */
    uint32_t handle = void_handle_new(t->object);
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, HOST_STACK_SIZE);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    if (pthread_create(&t->pt, &attr, thread_main, t)) {
        pthread_attr_destroy(&attr);
        void_handle_close(handle);
        void_set_last_error(ERROR_NOT_ENOUGH_MEMORY_);
        return 0;
    }
    pthread_attr_destroy(&attr);
    if (tid_out) MEM32(tid_out) = t->id;
    VLOG("[void] CreateThread start=%08X param=%08X id=%u handle=%08X%s", start, param, t->id, handle,
        t->suspended ? " suspended" : "");
    return handle;
}

WINAPI_EXPORT(K32, ResumeThread, 1)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_THREAD);
    if (!o || !o->data) return 0xFFFFFFFFu;
    void_thread *t = (void_thread *)o->data;
    pthread_mutex_lock(&wait_lock);
    uint32_t previous = (uint32_t)t->suspended;
    t->suspended = 0;
    pthread_cond_broadcast(&wait_cond);
    pthread_mutex_unlock(&wait_lock);
    return previous;
}

RAW_EXPORT(K32, ExitThread)
{
    void_thread *t = void_thread_self();
    t->exit_code = ARG(0);
    if (!t->exit_armed) void_fatal("ExitThread on a thread without a guest root frame");
    void_eh_reset_thread();
    longjmp(t->exit_jb, 1);
}

WINAPI_EXPORT(K32, GetExitCodeThread, 2)
{
    void_object *o = void_handle_get(ARG(0), VOID_OBJ_THREAD);
    if (!o) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    MEM32(ARG(1)) = o->signaled ? (uint32_t)o->count : 259u;   /* STILL_ACTIVE */
    return 1;
}

WINAPI_EXPORT(K32, TerminateThread, 2)
{
    void_log("[void] TerminateThread(%08X, %u) requested by %08X: unsupported, ignored", ARG(0), ARG(1), g_cur_func);
    return 0;
}

WINAPI_EXPORT(K32, GetThreadPriority, 1) { return 0; }
WINAPI_EXPORT(K32, SetThreadPriority, 2) { return 1; }
WINAPI_EXPORT(K32, SetThreadAffinityMask, 2) { return 1; }
WINAPI_EXPORT(K32, SetThreadIdealProcessor, 2) { return 0; }

WINAPI_EXPORT(K32, DuplicateHandle, 7)
{
    uint32_t source = ARG(1), target_out = ARG(3), options = ARG(6);
    uint32_t h;
    if (source == 0xFFFFFFFEu) {
        void_object *o = void_thread_self()->object;
        pthread_mutex_lock(&handle_lock);
        ++o->refs;
        pthread_mutex_unlock(&handle_lock);
        h = void_handle_new(o);
    } else if (source == 0xFFFFFFFFu) {
        void_object *o = void_object_new(VOID_OBJ_PROCESS, 0);
        h = void_handle_new(o);
    } else {
        h = void_handle_dup(source);
    }
    if (!h) { void_set_last_error(ERROR_INVALID_HANDLE_); return 0; }
    if (options & 1u) void_handle_close(source);   /* DUPLICATE_CLOSE_SOURCE */
    if (target_out) MEM32(target_out) = h;
    return 1;
}

WINAPI_EXPORT(K32, CloseHandle, 1)
{
    uint32_t h = ARG(0);
    if (h == 0xFFFFFFFEu || h == 0xFFFFFFFFu) return 1;
    if (!void_handle_close(h)) {
        void_set_last_error(ERROR_INVALID_HANDLE_);
        return 0;
    }
    return 1;
}

void void_threads_init(void)
{
    recomp_yield_hook = yield_hook;
}

/* The thread that runs the game's entry point. */
void void_thread_bind_main(void)
{
    void_thread *t = void_thread_self();
    (void)t;
}

void void_thread_exit_current_for_process(void) {}
