/* Register file, dispatch, CPUID, x87 helpers and fatal diagnostics. */
#define _GNU_SOURCE
#include "host.h"
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <ucontext.h>
#include <stdatomic.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#ifdef __ANDROID__
#include <android/log.h>
#endif

/* ------------------------------------------------------------ register file */
VOID_HIDDEN uint32_t g_eax, g_ecx, g_edx, g_esp, g_ebx, g_esi, g_edi, g_ebp;
#ifdef RECOMP_X87_WINDOW
VOID_HIDDEN double g_st_win[RECOMP_X87_SLOTS];
VOID_HIDDEN int64_t g_st_i64_win[RECOMP_X87_SLOTS];
VOID_HIDDEN int g_fp_sp = RECOMP_X87_SLOTS / 2;
#else
VOID_HIDDEN double g_st[8];
#endif
VOID_HIDDEN int g_fp_top;
VOID_HIDDEN uint16_t g_fpu_cw = 0x027F;
VOID_HIDDEN uint64_t g_fp_round_mask = ~0ull, g_fp_store_mask = ~0ull;   /* of 0x027F (fp_cw_masks) */
VOID_HIDDEN uint16_t g_seg_cs, g_seg_ds, g_seg_es, g_seg_fs, g_seg_gs, g_seg_ss;
VOID_HIDDEN uint64_t g_mm[8];
VOID_HIDDEN xmm_t g_xmm[8];
VOID_HIDDEN uint32_t g_mxcsr = 0x1F80;
VOID_HIDDEN uint32_t g_fs_base, g_gs_base, g_es_base;
VOID_HIDDEN ptrdiff_t g_mem_base = (ptrdiff_t)VOID_GUEST_BASE;
VOID_HIDDEN uint32_t g_cur_func;
VOID_HIDDEN uint32_t g_icall_trace[ICALL_TRACE_SIZE], g_icall_from[ICALL_TRACE_SIZE];
VOID_HIDDEN uint32_t g_icall_trace_idx, g_icall_count;
VOID_HIDDEN uint32_t g_flag_k, g_flag_a, g_flag_b, g_flag_cf;
VOID_HIDDEN int void_fpu_cmp = 1;
#ifndef RECOMP_X87_WINDOW
VOID_HIDDEN int64_t g_st_i64[8];
#endif
VOID_HIDDEN void (*recomp_yield_hook)(void);
VOID_HIDDEN uint32_t g_backedges;
#define VOID_ENTER_RING 1024
VOID_HIDDEN uint32_t g_enter_trace[VOID_ENTER_RING];
VOID_HIDDEN uint32_t g_enter_idx;

int void_verbose;

void void_regs_save(void_regs *r)
{
    r->eax = g_eax; r->ecx = g_ecx; r->edx = g_edx; r->ebx = g_ebx;
    r->esp = g_esp; r->ebp = g_ebp; r->esi = g_esi; r->edi = g_edi;
    r->fs = g_fs_base; r->cur = g_cur_func;
    r->flag_k = g_flag_k; r->flag_a = g_flag_a; r->flag_b = g_flag_b; r->flag_cf = g_flag_cf;
    memcpy(r->st, g_st, sizeof g_st);
    memcpy(r->st_i64, g_st_i64, sizeof g_st_i64);
    r->fp_top = g_fp_top; r->fpu_cmp = void_fpu_cmp; r->fpu_cw = g_fpu_cw;
    r->fp_round_mask = g_fp_round_mask; r->fp_store_mask = g_fp_store_mask;
    memcpy(r->mm, g_mm, sizeof g_mm);
    memcpy(r->xmm, g_xmm, sizeof g_xmm);
    r->mxcsr = g_mxcsr;
    r->eh_frames = g_eh_frames; r->eh_obj = g_eh_obj; r->eh_info = g_eh_info;
    r->backedges = g_backedges;
}

void void_regs_load(const void_regs *r)
{
    g_eax = r->eax; g_ecx = r->ecx; g_edx = r->edx; g_ebx = r->ebx;
    g_esp = r->esp; g_ebp = r->ebp; g_esi = r->esi; g_edi = r->edi;
    g_fs_base = r->fs; g_cur_func = r->cur;
    g_flag_k = r->flag_k; g_flag_a = r->flag_a; g_flag_b = r->flag_b; g_flag_cf = r->flag_cf;
    memcpy(g_st, r->st, sizeof g_st);
    memcpy(g_st_i64, r->st_i64, sizeof g_st_i64);
    g_fp_top = r->fp_top; void_fpu_cmp = r->fpu_cmp; g_fpu_cw = r->fpu_cw;
    g_fp_round_mask = r->fp_round_mask; g_fp_store_mask = r->fp_store_mask;
    memcpy(g_mm, r->mm, sizeof g_mm);
    memcpy(g_xmm, r->xmm, sizeof g_xmm);
    g_mxcsr = r->mxcsr;
    g_eh_frames = (recomp_ehframe_t *)r->eh_frames; g_eh_obj = r->eh_obj; g_eh_info = r->eh_info;
    g_backedges = r->backedges;
}

/* --------------------------------------------------------------- logging */
static pthread_mutex_t log_lock = PTHREAD_MUTEX_INITIALIZER;
static FILE *log_file;
/* Set while a fatal signal is being reported: the faulting thread may hold log_lock. */
static atomic_int log_in_signal;

void void_log_open(const char *path)
{
    pthread_mutex_lock(&log_lock);
    if (log_file) fclose(log_file);
#ifdef VOID_ANDROID_APP
    /* GameActivity (SessionLog.java) has moved the previous sessions' logs aside and begun
     * this one; appending also keeps the lines Java adds itself (an uncaught exception). */
    log_file = path ? fopen(path, "a") : NULL;
#else
    log_file = path ? fopen(path, "w") : NULL;
#endif
    if (log_file) setvbuf(log_file, NULL, _IOLBF, 0);
    pthread_mutex_unlock(&log_lock);
}

static void log_va(const char *fmt, va_list ap)
{
    char line[2048];
    vsnprintf(line, sizeof line, fmt, ap);
    if (atomic_load_explicit(&log_in_signal, memory_order_relaxed)) {
        /* A crash report must not wait for a lock its own thread may hold: wait briefly,
         * then write the line past the lock (line-buffered stdio holds no partial lines). */
        int locked = 0;
        for (int i = 0; i < 100 && !(locked = !pthread_mutex_trylock(&log_lock)); ++i) usleep(1000);
        size_t length = strlen(line);
        line[length] = '\n';
        if (log_file) {
            if (locked) fflush(log_file);
            ssize_t written = write(fileno(log_file), line, length + 1);
            (void)written;
        }
        line[length] = 0;
#ifdef __ANDROID__
        __android_log_write(ANDROID_LOG_ERROR, "HeroesV", line);
#endif
        if (locked) pthread_mutex_unlock(&log_lock);
        return;
    }
    pthread_mutex_lock(&log_lock);
    fprintf(stderr, "%s\n", line);
    if (log_file) fprintf(log_file, "%s\n", line);
#ifdef __ANDROID__
    __android_log_write(ANDROID_LOG_INFO, "HeroesV", line);
#endif
    pthread_mutex_unlock(&log_lock);
}

void void_log(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    log_va(fmt, ap);
    va_end(ap);
}

void void_log_flush(void)
{
    pthread_mutex_lock(&log_lock);
    fflush(stderr);
    if (log_file) fflush(log_file);
    pthread_mutex_unlock(&log_lock);
}

/* ------------------------------------------------------------- dispatch */
typedef struct { uint32_t va; void_fn fn; } slot_t;
static slot_t *table;
static uint32_t table_mask, table_used;
static uint32_t image_lo[64], image_hi[64];
static int image_count;

static inline uint32_t hash_va(uint32_t va) { return (va * 0x9E3779B1u) >> 7; }

static void table_grow(void)
{
    uint32_t capacity = table ? (table_mask + 1) * 2 : 1u << 18;
    slot_t *old = table;
    uint32_t old_capacity = table ? table_mask + 1 : 0;
    table = (slot_t *)calloc(capacity, sizeof *table);
    if (!table) void_fatal("dispatch table allocation failed");
    table_mask = capacity - 1;
    table_used = 0;
    for (uint32_t i = 0; i < old_capacity; ++i)
        if (old[i].va) void_dispatch_add(old[i].va, old[i].fn);
    free(old);
}

/* A direct-mapped cache in front of the table for void_resolve. Indirect
 * calls (C++ virtual calls above all) hit the same few thousand targets over
 * and over, and the table (megabytes) misses the data cache on nearly every
 * probe. Only the thread holding the machine resolves, so plain stores do. */
#define RESOLVE_CACHE_BITS 12
static struct { uint32_t va; void_fn fn; } resolve_cache[1u << RESOLVE_CACHE_BITS];
static inline uint32_t resolve_slot(uint32_t va) { return (va * 0x9E3779B1u) >> (32 - RESOLVE_CACHE_BITS); }

void void_dispatch_add(uint32_t va, void_fn fn)
{
    if (!va) void_fatal("dispatch: VA 0 cannot be registered");
    resolve_cache[resolve_slot(va)].va = 0;   /* a re-registered VA must not keep its old target */
    if (!table || (table_used + 1) * 2 > table_mask + 1) table_grow();
    for (uint32_t i = hash_va(va) & table_mask;; i = (i + 1) & table_mask) {
        if (table[i].va == va) { table[i].fn = fn; return; }
        if (!table[i].va) { table[i].va = va; table[i].fn = fn; ++table_used; return; }
    }
}

void_fn void_dispatch_find(uint32_t va)
{
    if (!va || !table) return NULL;
    for (uint32_t i = hash_va(va) & table_mask;; i = (i + 1) & table_mask) {
        if (table[i].va == va) return table[i].fn;
        if (!table[i].va) return NULL;
    }
}

void void_dispatch_image(uint32_t lo, uint32_t hi)
{
    if (image_count < 64) { image_lo[image_count] = lo; image_hi[image_count] = hi; ++image_count; }
}

static int in_image(uint32_t va)
{
    for (int i = 0; i < image_count; ++i) if (va >= image_lo[i] && va < image_hi[i]) return 1;
    return 0;
}

void void_dispatch_init(void)
{
    for (uint32_t i = 0; i < recomp_dispatch_count; ++i) {
        if (i && recomp_dispatch_table[i].address <= recomp_dispatch_table[i - 1].address)
            void_fatal("dispatch table not strictly sorted at %u", i);
        void_dispatch_add(recomp_dispatch_table[i].address, recomp_dispatch_table[i].func);
    }
    void_log("[void] dispatch: %u lifted entries", recomp_dispatch_count);
    void_zlib_init();
}

/* Synthetic VAs. Each thunk owns 16 bytes of a reserved, inaccessible range,
 * so a stray data access through one faults instead of reading garbage. */
#define MAX_THUNKS ((GUEST_THUNK_LIMIT - GUEST_THUNK_BASE) / 16u)
static const char **thunk_names;
static uint32_t thunk_count;

uint32_t void_thunk(void_fn fn, const char *name)
{
    if (!thunk_names) thunk_names = (const char **)calloc(MAX_THUNKS, sizeof *thunk_names);
    if (thunk_count >= MAX_THUNKS) void_fatal("thunk space exhausted");
    uint32_t va = GUEST_THUNK_BASE + 16u * thunk_count;
    thunk_names[thunk_count++] = name;
    void_dispatch_add(va, fn);
    return va;
}

const char *void_thunk_name(uint32_t va)
{
    if (va < GUEST_THUNK_BASE || va >= GUEST_THUNK_BASE + 16u * thunk_count || (va & 15u)) return NULL;
    return thunk_names[(va - GUEST_THUNK_BASE) / 16u];
}

/* x86 recomp_lookup*: the host code ported from Windows asks by kind. */
recomp_func_t recomp_lookup(uint32_t va)
{
    return in_image(va) ? (recomp_func_t)void_dispatch_find(va) : NULL;
}

recomp_func_t recomp_lookup_import(uint32_t va)
{
    return void_thunk_name(va) ? (recomp_func_t)void_dispatch_find(va) : NULL;
}

recomp_func_t recomp_lookup_manual(uint32_t va)
{
    (void)va;
    return NULL;
}

/* VOID_COUNT_THUNKS=1: count guest calls into each host thunk (Win32 and COM
 * methods all go through void_resolve) and log the busiest per frame. */
static int count_thunks = -1;
static uint32_t *thunk_calls;

void void_thunk_stats(uint32_t frames)
{
    if (count_thunks <= 0 || !thunk_calls || !frames) return;
    for (int rank = 0; rank < 12; ++rank) {
        uint32_t best = 0, best_i = 0;
        for (uint32_t i = 0; i < thunk_count; ++i) if (thunk_calls[i] > best) { best = thunk_calls[i]; best_i = i; }
        if (!best) break;
        void_log("[thunks] %8.1f/frame %s", (double)best / frames, thunk_names[best_i]);
        thunk_calls[best_i] = 0;
    }
    memset(thunk_calls, 0, thunk_count * sizeof *thunk_calls);
}

/* VOID_TRACE_CALLS=va[,va...] (hex, up to 8): indirect calls to these guest
 * functions log the object (ECX), the calling function and the EAX returned,
 * whenever the result for that object changes. Only the machine holder runs
 * guest code, so the bookkeeping needs no lock. */
#define TRACE_MAX 8
#define TRACE_OBJECTS 32
static int trace_n = -1;
static uint32_t trace_va[TRACE_MAX];
static void_fn trace_real[TRACE_MAX];
static struct { uint32_t ecx, eax, calls; } trace_obj[TRACE_MAX][TRACE_OBJECTS];

static void trace_call(int k)
{
    uint32_t ecx = g_ecx, caller = g_cur_func;
    if (trace_va[k] == 0x11102B30u) {
        /* Engine CGestures::recognize(callback, count, CVector2<float> *points, float threshold). */
        uint32_t count = MEM32(g_esp + 8), points = MEM32(g_esp + 12), threshold = MEM32(g_esp + 16);
        float t;
        memcpy(&t, &threshold, 4);
        uint32_t callback = MEM32(g_esp + 4);
        void_log("[trace] recognize: %u points at %08X, threshold %g, callback %08X (vtbl[2] %08X)", count, points,
            (double)t, callback, callback ? MEM32(MEM32(callback) + 8) : 0);
        char line[2048];
        size_t n = 0;
        for (uint32_t i = 0; i < count && n < sizeof line - 32; i += count > 48 ? count / 48 : 1) {
            float x, y;
            uint32_t ux = MEM32(points + 8 * i), uy = MEM32(points + 8 * i + 4);
            memcpy(&x, &ux, 4);
            memcpy(&y, &uy, 4);
            n += (size_t)snprintf(line + n, sizeof line - n, " %.0f,%.0f", (double)x, (double)y);
        }
        void_log("[trace] recognize points:%s", line);
        /* Templates: [this+8] count, [this+0xC] array of 0x1C-byte entries, points count +0x14, data +0x18. */
        uint32_t templates = MEM32(ecx + 8), base = MEM32(ecx + 0xC);
        for (uint32_t t = 0; t < templates && t < 3; ++t) {
            uint32_t entry = base + 0x1C * t, pc = MEM32(entry + 0x14), pd = MEM32(entry + 0x18);
            float lo_x = 1e30f, lo_y = 1e30f, hi_x = -1e30f, hi_y = -1e30f;
            for (uint32_t i = 0; i < pc && i < 4096; ++i) {
                float x, y;
                uint32_t ux = MEM32(pd + 8 * i), uy = MEM32(pd + 8 * i + 4);
                memcpy(&x, &ux, 4);
                memcpy(&y, &uy, 4);
                if (x < lo_x) lo_x = x;
                if (x > hi_x) hi_x = x;
                if (y < lo_y) lo_y = y;
                if (y > hi_y) hi_y = y;
            }
            void_log("[trace] template %u of %u: %u points, x %g..%g, y %g..%g, words %08X %08X %08X %08X %08X",
                t, templates, pc, (double)lo_x, (double)hi_x, (double)lo_y, (double)hi_y,
                MEM32(entry), MEM32(entry + 4), MEM32(entry + 8), MEM32(entry + 0xC), MEM32(entry + 0x10));
        }
    }
    uint32_t arg0 = MEM32(g_esp + 4);
    trace_real[k]();
    uint32_t eax = g_eax;
    if (trace_va[k] == 0x11102B30u && arg0) {
        /* The callback keeps the first matching template in [+8] (-1: none); recognize returns true only
         * when a template of another gesture matched too. The gesture class is word 2 of the template. */
        uint32_t first = MEM32(arg0 + 8);
        uint32_t cls = first != 0xFFFFFFFFu ? MEM32(MEM32(ecx + 0xC) + 0x1C * first + 8) : 0xFFFFFFFFu;
        void_log("[trace] recognize -> %u (ambiguous if 1), first template %d, gesture class %d", eax & 0xFF,
            (int)first, (int)cls);
    }
    int i = 0;
    while (i < TRACE_OBJECTS - 1 && trace_obj[k][i].ecx && trace_obj[k][i].ecx != ecx) ++i;
    if (trace_obj[k][i].ecx != ecx || trace_obj[k][i].eax != eax || !trace_obj[k][i].calls) {
        char peek[80] = "";
        if (eax >= 0x10000u && void_vm_readable(eax, 32)) {
            /* What the result points at: printable bytes, '.' for the rest (UTF-16 shows as "n.a.m.e."). */
            size_t n = (size_t)snprintf(peek, sizeof peek, " [");
            for (uint32_t b = 0; b < 32 && n < sizeof peek - 2; ++b) {
                uint8_t c = MEM8(eax + b);
                peek[n++] = (char)(c >= 32 && c < 127 ? c : '.');
            }
            peek[n++] = ']';
            peek[n] = 0;
        }
        void_log("[trace] %08X(ecx=%08X) from %08X -> %08X after %u calls%s", trace_va[k], ecx, caller, eax,
            trace_obj[k][i].calls, peek);
        trace_obj[k][i].ecx = ecx;
        trace_obj[k][i].eax = eax;
        trace_obj[k][i].calls = 0;
    }
    ++trace_obj[k][i].calls;
}

#define TRACE_TRAMPOLINE(k) static void trace_trampoline##k(void) { trace_call(k); }
TRACE_TRAMPOLINE(0) TRACE_TRAMPOLINE(1) TRACE_TRAMPOLINE(2) TRACE_TRAMPOLINE(3)
TRACE_TRAMPOLINE(4) TRACE_TRAMPOLINE(5) TRACE_TRAMPOLINE(6) TRACE_TRAMPOLINE(7)
static const void_fn trace_trampolines[TRACE_MAX] = {
    trace_trampoline0, trace_trampoline1, trace_trampoline2, trace_trampoline3,
    trace_trampoline4, trace_trampoline5, trace_trampoline6, trace_trampoline7,
};

static void_fn trace_wrap(uint32_t va, void_fn fn)
{
    if (trace_n < 0) {
        trace_n = 0;
        const char *env = getenv("VOID_TRACE_CALLS");
        for (char *end; env && *env && trace_n < TRACE_MAX; env = *end ? end + 1 : end) {
            uint32_t v = (uint32_t)strtoul(env, &end, 16);
            if (end == env) break;
            trace_va[trace_n++] = v;
        }
    }
    for (int k = 0; k < trace_n; ++k) {
        if (trace_va[k] != va) continue;
        trace_real[k] = fn;
        return trace_trampolines[k];
    }
    return fn;
}

static __attribute__((noinline)) recomp_func_t resolve_slow(uint32_t va)
{
    if (__builtin_expect(count_thunks != 0, 0)) {
        if (count_thunks < 0) {
            const char *env = getenv("VOID_COUNT_THUNKS");
            count_thunks = env && *env == '1';
            if (count_thunks) thunk_calls = (uint32_t *)calloc(MAX_THUNKS, sizeof *thunk_calls);
        }
        if (count_thunks && va >= GUEST_THUNK_BASE && va < GUEST_THUNK_BASE + 16u * thunk_count)
            ++thunk_calls[(va - GUEST_THUNK_BASE) >> 4];
    }
    uint32_t slot = resolve_slot(va);
    if (__builtin_expect(resolve_cache[slot].va == va && va, 1)) return (recomp_func_t)resolve_cache[slot].fn;
    void_fn fn = void_dispatch_find(va);
    if (__builtin_expect(fn != NULL, 1)) {
        if (__builtin_expect(trace_n != 0, 0)) fn = trace_wrap(va, fn);
        resolve_cache[slot].fn = fn;
        resolve_cache[slot].va = va;
        return (recomp_func_t)fn;
    }
    if (va == RECOMP_RETADDR) void_lift_trap(va, "return-address marker used as a call target");
    if (va < 0x10000u) void_lift_trap(va, "null or low guest control-flow target");
    if (in_image(va)) void_lift_trap(va, "unresolved guest control-flow target (not lifted)");
    void_lift_trap(va, "control-flow target outside every lifted image and thunk");
    return NULL;
}

/* Keep the common cache hit free of the diagnostic/miss path's saved registers. */
recomp_func_t void_resolve(uint32_t va)
{
    if (__builtin_expect(count_thunks == 0, 1)) {
        uint32_t slot = resolve_slot(va);
        if (__builtin_expect(va && resolve_cache[slot].va == va, 1))
            return (recomp_func_t)resolve_cache[slot].fn;
    }
    return resolve_slow(va);
}

/* ---------------------------------------------------------------- traps */
static atomic_int dumping;

/* The lifted function whose entry is the closest at or below va (the merged dispatch table
 * is sorted), or 0. */
static uint32_t lifted_owner(uint32_t va)
{
    uint32_t lo = 0, hi = recomp_dispatch_count;
    while (lo < hi) {
        uint32_t mid = lo + (hi - lo) / 2;
        if (recomp_dispatch_table[mid].address <= va) lo = mid + 1; else hi = mid;
    }
    return lo ? recomp_dispatch_table[lo - 1].address : 0;
}

/* A word on the guest stack that follows a call instruction in a lifted image. */
static int return_address(uint32_t va)
{
    if (!in_image(va) || !void_vm_readable(va - 7, 7)) return 0;
    if (MEM8(va - 5) == 0xE8) {                                   /* call rel32 */
        uint32_t target = va + MEM32(va - 4);
        return in_image(target) || void_thunk_name(target);
    }
    uint8_t m2 = MEM8(va - 1), m3 = MEM8(va - 2), m6 = MEM8(va - 5), m7 = MEM8(va - 6);
    return (MEM8(va - 2) == 0xFF && ((m2 >= 0xD0 && m2 <= 0xD7) ||                  /* call reg */
                                     (m2 >= 0x10 && m2 <= 0x17 && m2 != 0x14 && m2 != 0x15))) ||   /* [reg] */
           (MEM8(va - 3) == 0xFF && ((m3 >= 0x50 && m3 <= 0x57 && m3 != 0x54) || m3 == 0x14)) ||  /* [reg+d8] */
           (MEM8(va - 4) == 0xFF && MEM8(va - 3) == 0x54) ||                                     /* [sib+d8] */
           (MEM8(va - 6) == 0xFF && (m6 == 0x15 || (m6 >= 0x90 && m6 <= 0x97 && m6 != 0x94))) ||  /* [d32] */
           (MEM8(va - 7) == 0xFF && m7 == 0x94);                                                /* [sib+d32] */
}

/* Production builds keep no guest call trace (g_cur_func is 0): the return addresses on the
 * guest stack name the lifted callers instead. Words that only look like return addresses can
 * appear, so this is a hint, newest first. */
static void log_guest_stack(void)
{
    uint32_t esp = g_esp & ~3u, shown = 0;
    for (uint32_t offset = 0; offset < 0x8000u && shown < 24; offset += 4) {
        uint32_t at = esp + offset;
        if (!(at & (GUEST_PAGE - 1)) || !offset) {
            if (!void_vm_readable(at, 4)) break;
        }
        uint32_t va = MEM32(at);
        if (!return_address(va)) continue;
        uint32_t owner = lifted_owner(va);
        void_log("[void] guest stack +%04X: %08X in sub_%08X+0x%X", offset, va, owner, va - owner);
        ++shown;
    }
    if (!shown) void_log("[void] guest stack: no return addresses found above ESP %08X", g_esp);
}

void void_dump_state(const char *why)
{
    void_log("[void] ===== state dump: %s =====", why ? why : "");
    void_log("[void] cur=%08X EAX=%08X ECX=%08X EDX=%08X EBX=%08X ESP=%08X EBP=%08X ESI=%08X EDI=%08X FS=%08X",
        g_cur_func, g_eax, g_ecx, g_edx, g_ebx, g_esp, g_ebp, g_esi, g_edi, g_fs_base);
    void_log("[void] x87 top=%d cw=%04X st0=%g st1=%g flags k=%u a=%08X b=%08X cf=%u",
        g_fp_top, g_fpu_cw, g_st[0], g_st[1], g_flag_k, g_flag_a, g_flag_b, g_flag_cf);
    if (void_vm_readable(g_esp, 64)) {
        void_log("[void] stack %08X: %08X %08X %08X %08X %08X %08X %08X %08X", g_esp,
            MEM32(g_esp), MEM32(g_esp + 4), MEM32(g_esp + 8), MEM32(g_esp + 12),
            MEM32(g_esp + 16), MEM32(g_esp + 20), MEM32(g_esp + 24), MEM32(g_esp + 28));
    }
    char line[1024];
    size_t used = 0;
    uint32_t end = g_enter_idx, count = end < 48 ? end : 48;
    used += (size_t)snprintf(line + used, sizeof line - used, "[void] last entries:");
    for (uint32_t i = end - count; i != end; ++i) {
        used += (size_t)snprintf(line + used, sizeof line - used, " %08X", g_enter_trace[i & (VOID_ENTER_RING - 1)]);
        if (used > sizeof line - 16) { void_log("%s", line); used = 0; line[0] = 0; }
    }
    if (used) void_log("%s", line);
    end = g_icall_trace_idx; count = end < 24 ? end : 24;
    used = 0;
    used += (size_t)snprintf(line + used, sizeof line - used, "[void] last icalls (from->to):");
    for (uint32_t i = end - count; i != end; ++i) {
        uint32_t k = i & (ICALL_TRACE_SIZE - 1);
        const char *name = void_thunk_name(g_icall_trace[k]);
        used += (size_t)snprintf(line + used, sizeof line - used, " %08X->%08X%s%s",
            g_icall_from[k], g_icall_trace[k], name ? ":" : "", name ? name : "");
        if (used > sizeof line - 80) { void_log("%s", line); used = 0; line[0] = 0; }
    }
    if (used) void_log("%s", line);
    log_guest_stack();
    void_log_flush();
}

static void log_code_address(const char *what, uintptr_t pc);

/* The lifted callers of a host trap: generated functions keep frame records. */
static void log_caller_backtrace(void)
{
#if defined(__aarch64__)
    uintptr_t fp = (uintptr_t)__builtin_frame_address(0), low = fp;
    for (int depth = 0; depth < 48 && fp >= low && fp - low < (96u << 20) && !(fp & 15); ++depth) {
        const uintptr_t *record = (const uintptr_t *)fp;
        uintptr_t next = record[0], ret = record[1];
        log_code_address("caller", ret);
        if (next <= fp) break;
        fp = next;
    }
#endif
}

_Noreturn void void_fatal(const char *fmt, ...)
{
    va_list ap;
    char message[1024];
    va_start(ap, fmt);
    vsnprintf(message, sizeof message, fmt, ap);
    va_end(ap);
    void_log("[void] FATAL: %s", message);
    if (!atomic_exchange(&dumping, 1)) {
        log_caller_backtrace();
        void_dump_state(message);
    }
    void_log_flush();
    _exit(70);
}

void void_lift_trap(uint32_t address, const char *instruction)
{
    const char *name = void_thunk_name(address);
    void_fatal("guest trap at %08X%s%s: %s (caller %08X)", address, name ? " " : "", name ? name : "",
        instruction, g_cur_func);
}

/* Validation builds (build_android.py --protocol-check) report each call site
 * whose callee changed a register its summary keeps, and each x87-rewritten
 * body that left the global stack window at the wrong depth; once each. */
static int seen_once(uint32_t key)
{
    static uint32_t seen[4096];
    static unsigned count;
    static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
    int fresh = 1;
    pthread_mutex_lock(&lock);
    for (unsigned i = 0; i < count; ++i)
        if (seen[i] == key) { fresh = 0; break; }
    if (fresh && count < sizeof seen / sizeof seen[0]) seen[count++] = key;
    pthread_mutex_unlock(&lock);
    return fresh;
}

void recomp_protocol_violation(uint32_t site, uint32_t target, uint32_t regs)
{
    if (seen_once(site ^ (regs << 24)))
        void_log("[protocol] site %08X target %08X regs %02X", site, target, regs);
}

void recomp_x87_violation(uint32_t va, int found, int expected)
{
    if (seen_once(va ^ 0x80000000u))
        void_log("[x87] %08X net %d expected %d", va, found, expected);
}

/* A host code address as module+offset (llvm-symbolizer resolves it against
 * the unstripped libhomm5.so); production builds keep no guest call trace. */
static void log_code_address(const char *what, uintptr_t pc)
{
    Dl_info info;
    if (pc && dladdr((void *)pc, &info) && info.dli_fbase) {
        const char *slash = info.dli_fname ? strrchr(info.dli_fname, '/') : NULL;
        const char *module = slash ? slash + 1 : info.dli_fname ? info.dli_fname : "?";
        void_log("[void] %s %p = %s+0x%lx%s%s", what, (void *)pc, module,
                 (unsigned long)(pc - (uintptr_t)info.dli_fbase), info.dli_sname ? " " : "",
                 info.dli_sname ? info.dli_sname : "");
    } else {
        void_log("[void] %s %p", what, (void *)pc);
    }
}

static void log_host_backtrace(const void *context)
{
#if defined(__aarch64__)
    const ucontext_t *uc = (const ucontext_t *)context;
    if (!uc) return;
    uintptr_t sp = (uintptr_t)uc->uc_mcontext.sp, fp = (uintptr_t)uc->uc_mcontext.regs[29];
    log_code_address("pc", (uintptr_t)uc->uc_mcontext.pc);
    log_code_address("lr", (uintptr_t)uc->uc_mcontext.regs[30]);
    /* Frame records live on the faulting thread's stack, above its SP. */
    for (int depth = 0; depth < 48 && fp >= sp && fp - sp < (96u << 20) && !(fp & 15); ++depth) {
        const uintptr_t *record = (const uintptr_t *)fp;
        uintptr_t next = record[0], ret = record[1];
        log_code_address("frame", ret);
        if (next <= fp) break;
        fp = next;
    }
#else
    (void)context;
#endif
}

/* The handlers before ours (debuggerd's in an app): they still get the signal afterwards. */
static struct sigaction previous_actions[SIGSYS + 1];

static void on_signal(int signo, siginfo_t *info, void *context)
{
    uintptr_t fault = (uintptr_t)info->si_addr;
    char where[96] = "";
    if (fault >= VOID_GUEST_BASE && fault < VOID_GUEST_BASE + VOID_GUEST_SPAN)
        snprintf(where, sizeof where, " (guest VA %08X)", (uint32_t)(fault - VOID_GUEST_BASE));
    atomic_store(&log_in_signal, 1);
    char thread[17] = "?";
    prctl(PR_GET_NAME, thread, 0, 0, 0);
    void_log("[void] host signal %d (%s) code %d at %p%s on thread %d \"%s\"", signo, strsignal(signo),
             info->si_code, info->si_addr, where, (int)gettid(), thread);
    if (!atomic_exchange(&dumping, 1)) {
        log_host_backtrace(context);
        void_dump_state("host signal");
    }
    void_log_flush();
    /* The previous handler takes over: in an app debuggerd writes the tombstone and Android
     * records the native crash (shown in the next session's homm5.1.log). A fault happens
     * again when the handler returns; a sent signal (abort, kill) is sent again. */
    const struct sigaction *previous = signo > 0 && signo <= SIGSYS ? &previous_actions[signo] : NULL;
    if (previous && previous->sa_handler != SIG_IGN &&
        !((previous->sa_flags & SA_SIGINFO) && previous->sa_sigaction == on_signal)) {
        sigaction(signo, previous, NULL);
        if (info->si_code <= 0) raise(signo);
        return;
    }
    signal(signo, SIG_DFL);
    raise(signo);
}

void void_install_fault_handlers(void)
{
    static char alt[256 * 1024];
    stack_t ss = { .ss_sp = alt, .ss_size = sizeof alt, .ss_flags = 0 };
    sigaltstack(&ss, NULL);
    struct sigaction sa;
    memset(&sa, 0, sizeof sa);
    sa.sa_sigaction = on_signal;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sigemptyset(&sa.sa_mask);
    int signals[] = { SIGSEGV, SIGBUS, SIGILL, SIGFPE, SIGABRT };
    for (size_t i = 0; i < sizeof signals / sizeof signals[0]; ++i)
        sigaction(signals[i], &sa, &previous_actions[signals[i]]);
}

#ifdef __ANDROID__
#include <link.h>
#include <sys/sysinfo.h>
#include <sys/system_properties.h>

void void_log_system_info(void);

/* This library's GNU build ID: llvm-symbolizer needs the unstripped build it names. */
static int find_build_id(struct dl_phdr_info *module, size_t size, void *data)
{
    (void)size;
    char *out = (char *)data;
    uintptr_t self = (uintptr_t)void_log_system_info;
    int ours = 0;
    for (int i = 0; i < module->dlpi_phnum; ++i) {
        const ElfW(Phdr) *p = &module->dlpi_phdr[i];
        uintptr_t start = module->dlpi_addr + p->p_vaddr;
        if (p->p_type == PT_LOAD && self >= start && self < start + p->p_memsz) ours = 1;
    }
    if (!ours) return 0;
    for (int i = 0; i < module->dlpi_phnum; ++i) {
        const ElfW(Phdr) *p = &module->dlpi_phdr[i];
        if (p->p_type != PT_NOTE) continue;
        const uint8_t *note = (const uint8_t *)(module->dlpi_addr + p->p_vaddr), *end = note + p->p_memsz;
        while (note + sizeof(ElfW(Nhdr)) <= end) {
            const ElfW(Nhdr) *header = (const ElfW(Nhdr) *)note;
            const uint8_t *name = note + sizeof *header, *desc = name + ((header->n_namesz + 3) & ~3u);
            if (header->n_type == NT_GNU_BUILD_ID && header->n_namesz == 4 && !memcmp(name, "GNU", 4) &&
                desc + header->n_descsz <= end) {
                for (uint32_t b = 0; b < header->n_descsz && b < 32; ++b) sprintf(out + 2 * b, "%02x", desc[b]);
                return 1;
            }
            note = desc + ((header->n_descsz + 3) & ~3u);
        }
    }
    return 1;
}

/* The device and the engine build, for a log a player sends in. */
void void_log_system_info(void)
{
    static const char *const names[] = { "ro.product.manufacturer", "ro.product.model", "ro.build.version.release",
        "ro.build.version.sdk", "ro.soc.manufacturer", "ro.soc.model", "ro.board.platform" };
    char value[7][PROP_VALUE_MAX];
    for (int i = 0; i < 7; ++i) {
        value[i][0] = 0;
        __system_property_get(names[i], value[i]);
    }
    struct sysinfo memory;
    unsigned long mib = sysinfo(&memory) ? 0 :
        (unsigned long)((unsigned long long)memory.totalram * memory.mem_unit / (1024 * 1024));
    void_log("[void] device: %s %s, Android %s (SDK %s), SoC %s %s (%s), %ld CPUs, %lu MiB", value[0], value[1],
             value[2], value[3], value[4], value[5], value[6], sysconf(_SC_NPROCESSORS_CONF), mib);
    char build_id[65] = "";
    dl_iterate_phdr(find_build_id, build_id);
    Dl_info self;
    const char *file = dladdr((void *)void_log_system_info, &self) && self.dli_fname ? self.dli_fname : "?";
    const char *slash = strrchr(file, '/');
    void_log("[void] engine %s build-id %s", slash ? slash + 1 : file, build_id[0] ? build_id : "?");
}
#endif

/* ---------------------------------------------------------------- CPUID */
/* Captured on the Windows PC the x86 build was validated on (Ryzen 7 5700X),
 * so the guest picks the same MMX/SSE/SSE2 library paths it ran there. */
static const uint32_t cpuid_table[][5] = {
    {0x00000000u, 0x00000010u, 0x68747541u, 0x444D4163u, 0x69746E65u},
    {0x00000001u, 0x00A20F12u, 0x08100800u, 0x7EF8320Bu, 0x178BFBFFu},
    {0x00000007u, 0x00000000u, 0x219C97A9u, 0x0040068Cu, 0x00000010u},
    {0x80000000u, 0x80000023u, 0x68747541u, 0x444D4163u, 0x69746E65u},
    {0x80000001u, 0x00A20F12u, 0x20000000u, 0x75C237FFu, 0x2FC3FBFFu},
    {0x80000002u, 0x20444D41u, 0x657A7952u, 0x2037206Eu, 0x30303735u},
    {0x80000003u, 0x2D382058u, 0x65726F43u, 0x6F725020u, 0x73736563u},
    {0x80000004u, 0x2020726Fu, 0x20202020u, 0x20202020u, 0x00202020u},
    {0x80000005u, 0xFF40FF40u, 0xFF40FF40u, 0x20080140u, 0x20080140u},
    {0x80000006u, 0x48002200u, 0x68004200u, 0x02006140u, 0x01009140u},
};

void void_cpuid(uint32_t leaf, uint32_t subleaf)
{
    (void)subleaf;
    for (size_t i = 0; i < sizeof cpuid_table / sizeof cpuid_table[0]; ++i) {
        if (cpuid_table[i][0] == leaf) {
            g_eax = cpuid_table[i][1]; g_ebx = cpuid_table[i][2];
            g_ecx = cpuid_table[i][3]; g_edx = cpuid_table[i][4];
            return;
        }
    }
    g_eax = g_ebx = g_ecx = g_edx = 0;
}

/* ----------------------------------------------------------- FPREM/FPREM1 */
/* The x86 host executed the real instruction on the two doubles; here the
 * same double-model operation is computed exactly: the IEEE remainder of two
 * doubles is exact, and so is the partial-remainder step for exponent gaps
 * below 64, which is every case the Windows host accepted. */
void void_fpu_remainder(uint32_t address, int nearest)
{
    if (g_fp_top < 2 || g_fp_top > 8 || (nearest != 0 && nearest != 1))
        void_lift_trap(address, "unsupported FPREM stack/control word");
    double x = g_st[0], y = g_st[1];
    uint16_t status = 0;
    if (isnan(x) || isnan(y) || isinf(x) || y == 0.0) {
        /* Masked invalid operation: the x87 "real indefinite" QNaN. */
        uint64_t indefinite = 0xFFF8000000000000ull;
        memcpy(&g_st[0], &indefinite, sizeof indefinite);
        g_st_i64[0] = 0;
        void_fpu_cmp = (int)0x10000u;
        return;
    }
    if (isinf(y) || x == 0.0) {
        g_st_i64[0] = 0;          /* x unchanged, quotient 0 */
        void_fpu_cmp = (int)0x10000u;
        return;
    }
    int ex, ey;
    frexp(x, &ex); frexp(y, &ey);
    if (ex - ey < 64) {
        /* fmod and remainder are exact in IEEE arithmetic. The quotient's
         * low three bits (C0 C3 C1 = Q2 Q1 Q0) come from the exact truncated
         * remainder modulo 8|y|: r8 - rt = q8 * y with q8 in 0..7, so the
         * rounded division is within an ulp of a small integer. */
        double rt = fmod(x, y);
        double r8 = fmod(x, 8.0 * y);
        if (isinf(8.0 * y)) r8 = x;   /* |y| near DBL_MAX: |q| < 8 already */
        uint32_t q = (uint32_t)nearbyint(fabs((r8 - rt) / y)) & 7u;
        double r = rt;
        if (nearest) {
            double rn = remainder(x, y);
            if (rn != rt) q = (q + 1u) & 7u;  /* quotient rounded away from zero */
            r = rn;
        }
        if (q & 1u) status |= 0x0200u;   /* C1 = Q0 */
        if (q & 2u) status |= 0x4000u;   /* C3 = Q1 */
        if (q & 4u) status |= 0x0100u;   /* C0 = Q2 */
        g_st[0] = r;
    } else {
        /* Partial reduction (C2 = 1): reduce by y * 2^(D - N), N in 32..63,
         * exactly; callers loop until C2 clears, and the remainder they reach
         * is the same exact fmod/remainder whichever N the hardware used. */
        int n = 32 + ((ex - ey) & 31);
        g_st[0] = fmod(x, ldexp(y, ex - ey - n));
        status |= 0x0400u;
    }
    g_st_i64[0] = 0;
    void_fpu_cmp = (int)(0x10000u | status);
}
