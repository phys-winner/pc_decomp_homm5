/* The render thread of the GLES path of Direct3D 9. The game's thread records
 * what the GL side has to do as calls (a function and a copy of its arguments)
 * in a ring; one host thread that owns the EGL context runs them in order, at
 * most a frame behind. On a draw the game's thread pays for the state that
 * changed since the last one (d3d_rt_sync_state) and a few words; the GL
 * driver and our translation run beside it. Resource data travels by copy,
 * made on the game's thread when D3D hands it over (an Unlock, a draw's UP
 * data); buffers the render thread reads in guest memory are never written
 * under it (d3d9_resource.c). Whatever has to answer the game at once (a
 * read-back) waits for the thread to get there; query results are published
 * by it and polled, never waited for.
 *
 * Switch: VOID_RENDER_THREAD=0/1, else <data dir>/render-thread holding 0 or 1;
 * on by default. Off, every record runs at once on the game's thread through
 * the same code, in the same order.
 *
 * Shared by the D3D9 -> GLES bridges of this family: it knows d3d_state and
 * d3d_device of d3d9_internal.h and the host runtime (log, machine, data dir)
 * and nothing of the game. After The Sims 2 (the_sims_2/android/host). */
#define _GNU_SOURCE
#include "d3d9_internal.h"
#include "d3d9_thread.inc"
#include <pthread.h>
#include <sched.h>
#include <time.h>
#include <errno.h>
#include <unistd.h>
#include <sys/syscall.h>

int void_machine_is_owned(void) __attribute__((weak));

#define RING_BYTES (32u << 20)
#define BIG_BYTES (RING_BYTES / 8)      /* larger payloads go on the heap */

typedef struct {
    uint32_t size;                      /* the whole record, 16-aligned */
    uint32_t wrap;                      /* skip to the end of the ring */
    d3d_rt_fn fn;
} rec_t;

/* The two threads' positions sit on cache lines of their own: sharing one,
 * every record either side finished moved the line between the cores. The
 * game's thread publishes in batches and before any wait, and reads the
 * render thread's position only when the ring looks full. */
#define LINE __attribute__((aligned(128)))
#define PUBLISH_BYTES (64u << 10)
#define PUBLISH_RECORDS 48u
static uint8_t *ring;
static _Atomic uint64_t head LINE;      /* bytes published (game) */
static _Atomic uint64_t tail LINE;      /* bytes run (render) */
static _Atomic int render_sleeping LINE;
static _Atomic int game_sleeping LINE;
static _Atomic uint64_t game_wait_until;
static _Atomic int game_wait_frames;
static uint64_t written LINE;           /* game: bytes recorded */
static uint64_t tail_seen;              /* game: its last look at tail */
static uint32_t unpublished;            /* game: records since the last publish */
static uint64_t open_at;                /* game: the record d3d_rt_begin handed out */
static uint32_t open_size;
static void *open_big;
static d3d_rt_fn open_fn;
static int threaded = -1;
static pthread_t render_thread;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t to_render = PTHREAD_COND_INITIALIZER, to_game = PTHREAD_COND_INITIALIZER;
static _Atomic uint32_t frames_queued LINE;
static __thread int on_render;
static __thread int executing;          /* inline mode: inside a record */
static int (*_Atomic idle_poll)(int idle);
/* Inline mode: each open call's arguments, a level per nested call. */
#define INLINE_DEPTH 8
static __thread uint8_t *inline_payload[INLINE_DEPTH];
static __thread size_t inline_cap[INLINE_DEPTH];
static __thread int inline_depth;
static __thread d3d_rt_fn inline_fn[INLINE_DEPTH];
static d3d_rt_stats_t stats;            /* the game's fields */
static _Atomic uint64_t render_busy_ns;

int d3d_rt_threaded(void) { return threaded > 0; }
int d3d_rt_on_render(void) { return on_render || threaded <= 0; }
int d3d_rt_executing(void) { return on_render || executing; }
void d3d_rt_set_idle(int (*poll)(int idle)) { idle_poll = poll; }

static inline void cpu_relax(void)
{
#if defined(__aarch64__)
    __asm__ volatile("yield" ::: "memory");
#endif
}

static void wake(_Atomic int *sleeping, pthread_cond_t *cond)
{
    if (atomic_load(sleeping)) {
        pthread_mutex_lock(&lock);
        if (atomic_exchange(sleeping, 0)) pthread_cond_broadcast(cond);
        pthread_mutex_unlock(&lock);
    }
}

static int game_waiting_done(uint64_t until, int frames)
{
    return frames >= 0 ? atomic_load(&frames_queued) <= (uint32_t)frames : atomic_load(&tail) >= until;
}

/* What the game's thread recorded becomes the render thread's to run. */
static void publish(void)
{
    unpublished = 0;
    if (atomic_load_explicit(&head, memory_order_relaxed) == written) return;
    atomic_store_explicit(&head, written, memory_order_release);
    wake(&render_sleeping, &to_render);
}

/* The game's thread waits for the render thread to run up to `until` bytes
 * (or, with frames >= 0, until at most that many presents are queued). After
 * a short spin it lets other guest threads have the machine: the render
 * thread never needs it, and no other guest thread makes D3D9 calls (the GL
 * context was only ever current on this one). Returns the time waited. */
static uint64_t game_wait(uint64_t until, int frames)
{
    publish();
    if (game_waiting_done(until, frames)) return 0;
    uint64_t start = void_monotonic_ns();
    for (int spin = 0; spin < 2000; ++spin) {
        if (game_waiting_done(until, frames)) return void_monotonic_ns() - start;
        cpu_relax();
    }
    int release = void_machine_is_owned && void_machine_is_owned();
    if (release) void_blocking_begin();
    pthread_mutex_lock(&lock);
    atomic_store(&game_wait_until, until);
    atomic_store(&game_wait_frames, frames);
    for (;;) {
        atomic_store(&game_sleeping, 1);
        if (game_waiting_done(until, frames)) break;
        pthread_cond_wait(&to_game, &lock);
    }
    atomic_store(&game_sleeping, 0);
    pthread_mutex_unlock(&lock);
    if (release) void_blocking_end();
    return void_monotonic_ns() - start;
}

/* ---------------------------------------------------------- the thread */
enum { RT_CORES_AUTO, RT_CORES_BIG, RT_CORES_NEXT, RT_CORES_ANY };

static long render_core_mask(const long *capacity, int cpus, int policy, cpu_set_t *mask)
{
    CPU_ZERO(mask);
    if (!capacity || cpus < 1 || cpus > CPU_SETSIZE || policy == RT_CORES_ANY) return 0;
    long best = 0, next = 0;
    int big_count = 0, third_tier = 0;
    for (int i = 0; i < cpus; ++i) {
        if (capacity[i] <= 0) return 0;
        if (capacity[i] > best) best = capacity[i];
    }
    for (int i = 0; i < cpus; ++i) {
        if (capacity[i] == best) ++big_count;
        else if (capacity[i] > next) next = capacity[i];
    }
    if (!next) return 0;
    for (int i = 0; i < cpus; ++i) if (capacity[i] < next) third_tier = 1;
    /* A two-tier SoC can share several big cores: the machine runs one guest at a time. */
    long chosen = policy == RT_CORES_BIG ? best : policy == RT_CORES_NEXT ? next :
                  (third_tier || big_count == 1) ? next : best;
    for (int i = 0; i < cpus; ++i) if (capacity[i] == chosen) CPU_SET(i, mask);
    return chosen;
}

static long cpu_capacity(int cpu)
{
    char path[96];
    snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/cpu_capacity", cpu);
    FILE *f = fopen(path, "r");
    if (!f) return -1;
    long value = -1;
    if (fscanf(f, "%ld", &value) != 1) value = -1;
    fclose(f);
    return value;
}

static void leave_game_cores(void)
{
    static const char *const policies[] = { "auto", "big", "next", "any" };
    const char *requested = getenv("VOID_RT_CORES");
    int policy = RT_CORES_AUTO;
    if (requested && *requested) {
        for (policy = 0; policy <= RT_CORES_ANY; ++policy) if (!strcmp(requested, policies[policy])) break;
        if (policy > RT_CORES_ANY) {
            void_log("[rt] unknown VOID_RT_CORES policy '%s'; using auto", requested);
            policy = RT_CORES_AUTO;
        }
    }
    static long value[CPU_SETSIZE];
    long configured = sysconf(_SC_NPROCESSORS_CONF);
    int cpus = configured > 0 && configured <= CPU_SETSIZE ? (int)configured : 0;
    for (int i = 0; i < cpus; ++i) value[i] = cpu_capacity(i);
    cpu_set_t mine;
    long chosen = render_core_mask(value, cpus, policy, &mine);
    if (!chosen) {
        void_log("[rt] render thread on scheduler-selected cores (policy %s)", policies[policy]);
    } else if (sched_setaffinity(0, sizeof mine, &mine) == 0) {
        void_log("[rt] render thread on %d cores of capacity %ld (policy %s)", CPU_COUNT(&mine), chosen, policies[policy]);
    } else {
        void_log("[rt] render thread on scheduler-selected cores (policy %s; affinity rejected: %s)",
                 policies[policy], strerror(errno));
    }
}

static _Atomic int render_tid;
int d3d_rt_render_tid(void) { return atomic_load(&render_tid); }

/* The render thread moves to its cores once the GL context exists: the
 * driver's own threads, born during EGL setup, keep the creator's mask. */
static void run_leave_game_cores(void *unused) { (void)unused; leave_game_cores(); }

static void *render_main(void *unused)
{
    (void)unused;
    on_render = 1;
    atomic_store(&render_tid, (int)syscall(SYS_gettid));
    pthread_setname_np(pthread_self(), "d3d9-render");
    uint64_t at = 0;
    for (;;) {
        if (atomic_load_explicit(&head, memory_order_acquire) == at) {
            /* Out of records: first the GL work it does unasked (query results the game polls). */
            int (*poll)(int) = idle_poll;
            for (int idle = 1; poll && atomic_load_explicit(&head, memory_order_acquire) == at && poll(idle); idle = 2) {
                for (int spin = 0; spin < 200 && atomic_load_explicit(&head, memory_order_acquire) == at; ++spin)
                    cpu_relax();
                if (atomic_load_explicit(&head, memory_order_acquire) != at) break;
                struct timespec nap = { 0, 50000 };
                nanosleep(&nap, NULL);
            }
            int spin = 0;
            while (atomic_load_explicit(&head, memory_order_acquire) == at && spin < 4000) { cpu_relax(); ++spin; }
            if (atomic_load_explicit(&head, memory_order_acquire) == at) {
                pthread_mutex_lock(&lock);
                for (;;) {
                    atomic_store(&render_sleeping, 1);
                    if (atomic_load_explicit(&head, memory_order_acquire) != at) break;
                    pthread_cond_wait(&to_render, &lock);
                }
                atomic_store(&render_sleeping, 0);
                pthread_mutex_unlock(&lock);
            }
        }
        uint64_t published = atomic_load_explicit(&head, memory_order_acquire);
        uint64_t start = void_monotonic_ns();
        while (at != published) {
            rec_t *r = (rec_t *)(ring + (at % RING_BYTES));
            if (r->wrap) at += RING_BYTES - (at % RING_BYTES);
            else { r->fn((uint8_t *)r + sizeof *r); at += r->size; }
            atomic_store_explicit(&tail, at, memory_order_release);
            /* Byte waits finish at their target; frame waits need a completed present. */
            if (atomic_load(&game_sleeping) && game_waiting_done(atomic_load(&game_wait_until),
                atomic_load(&game_wait_frames))) wake(&game_sleeping, &to_game);
        }
        /* Between batches too: a busy render thread still answers polls. */
        int (*poll)(int) = idle_poll;
        if (poll) poll(0);
        atomic_fetch_add_explicit(&render_busy_ns, void_monotonic_ns() - start, memory_order_relaxed);
    }
    return NULL;
}

static int switched_on(void)
{
    const char *env = getenv("VOID_RENDER_THREAD");
    if (env && *env) return *env != '0';
    char path[1100];
    snprintf(path, sizeof path, "%s/render-thread", void_data_dir());
    FILE *f = fopen(path, "rb");
    if (!f) return 1;
    int c = fgetc(f);
    fclose(f);
    return c != '0';
}

void d3d_rt_start(void)
{
    if (threaded >= 0) return;
    threaded = switched_on();
    if (!threaded) { void_log("[rt] render thread off: GL calls run inline"); return; }
    if (posix_memalign((void **)&ring, 64, RING_BYTES) != 0) ring = NULL;
    if (!ring || pthread_create(&render_thread, NULL, render_main, NULL) != 0) {
        void_log("[rt] no render thread: GL calls run inline");
        free(ring);
        ring = NULL;
        threaded = 0;
        return;
    }
    void_log("[rt] render thread started (%u MiB ring)", RING_BYTES >> 20);
}

/* The GL context exists now (d3d_gl_init): the render thread takes its cores. */
void d3d_rt_settle(void);
void d3d_rt_settle(void) { if (threaded > 0) d3d_rt_call(run_leave_game_cores, NULL, 0); }

void d3d_rt_wait_begin(void) { if (!on_render) void_blocking_begin(); }
void d3d_rt_wait_end(void) { if (!on_render) void_blocking_end(); }

/* --------------------------------------------------------------- records */
void *d3d_rt_begin(d3d_rt_fn fn, uint32_t size)
{
    if (threaded <= 0 || on_render) {
        int d = inline_depth++;
        if (d >= INLINE_DEPTH) void_fatal("render calls nested %d deep", d);
        if (size > inline_cap[d]) {
            free(inline_payload[d]);
            inline_cap[d] = size > 4096 ? size : 4096;
            inline_payload[d] = (uint8_t *)malloc(inline_cap[d]);
            if (!inline_payload[d]) void_fatal("render call of %u bytes", size);
        }
        inline_fn[d] = fn;
        return inline_payload[d];
    }
    open_fn = fn;
    open_big = NULL;
    uint32_t payload = size;
    if (size > BIG_BYTES) {
        open_big = malloc(size);
        if (!open_big) void_fatal("render call of %u bytes", size);
        payload = sizeof(void *) + sizeof(d3d_rt_fn);
    }
    uint32_t need = (uint32_t)((sizeof(rec_t) + payload + 15u) & ~15u);
    uint64_t at = written;
    uint32_t room_to_end = RING_BYTES - (uint32_t)(at % RING_BYTES);
    if (room_to_end < need) {
        /* No record straddles the end: mark the rest skipped. */
        if (at + room_to_end - tail_seen > RING_BYTES) {
            tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
            if (at + room_to_end - tail_seen > RING_BYTES) {
                ++stats.ring_waits;
                stats.ring_wait_ns += game_wait(at + room_to_end - RING_BYTES, -1);
                tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
            }
        }
        ((rec_t *)(ring + at % RING_BYTES))->wrap = 1;
        at += room_to_end;
        written = at;
        publish();
    }
    if (at + need - tail_seen > RING_BYTES) {
        tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
        if (at + need - tail_seen > RING_BYTES) {
            ++stats.ring_waits;
            stats.ring_wait_ns += game_wait(at + need - RING_BYTES, -1);
            tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
        }
    }
    rec_t *r = (rec_t *)(ring + at % RING_BYTES);
    r->wrap = 0;
    r->size = need;
    r->fn = fn;
    open_at = at;
    open_size = need;
    return open_big ? open_big : (uint8_t *)r + sizeof *r;
}

static void run_big(void *payload)
{
    void *p;
    d3d_rt_fn fn;
    memcpy(&p, payload, sizeof p);
    memcpy(&fn, (uint8_t *)payload + sizeof p, sizeof fn);
    fn(p);
    free(p);
}

void d3d_rt_commit(void)
{
    if (threaded <= 0 || on_render) {
        int d = inline_depth - 1;
        ++executing;
        inline_fn[d](inline_payload[d]);
        --executing;
        --inline_depth;
        return;
    }
    rec_t *r = (rec_t *)(ring + open_at % RING_BYTES);
    if (open_big) {
        r->fn = run_big;
        uint8_t *p = (uint8_t *)r + sizeof *r;
        memcpy(p, &open_big, sizeof open_big);
        memcpy(p + sizeof open_big, &open_fn, sizeof open_fn);
        open_big = NULL;
    }
    written = open_at + open_size;
    ++stats.records;
    stats.bytes += open_size;
    if (++unpublished >= PUBLISH_RECORDS || written - atomic_load_explicit(&head, memory_order_relaxed) >= PUBLISH_BYTES)
        publish();
}

void d3d_rt_commit_size(uint32_t used)
{
    if (threaded > 0 && !on_render && !open_big) {
        uint32_t need = (uint32_t)((sizeof(rec_t) + used + 15u) & ~15u);
        if (need < open_size) {
            ((rec_t *)(ring + open_at % RING_BYTES))->size = need;
            open_size = need;
        }
    }
    d3d_rt_commit();
}

void d3d_rt_flush(void)
{
    if (threaded > 0 && !on_render) publish();
}

void d3d_rt_call(d3d_rt_fn fn, const void *args, uint32_t size)
{
    void *p = d3d_rt_begin(fn, size);
    if (size) memcpy(p, args, size);
    d3d_rt_commit();
}

uint64_t d3d_rt_position(void) { return threaded > 0 && !on_render ? written : 0; }

int d3d_rt_reached(uint64_t position)
{
    if (threaded <= 0 || on_render || !position) return 1;
    if (tail_seen >= position) return 1;
    tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
    return tail_seen >= position;
}

void d3d_rt_wait_for(uint64_t position)
{
    if (d3d_rt_reached(position)) return;
    ++stats.ring_waits;
    stats.ring_wait_ns += game_wait(position, -1);
    tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
}

void d3d_rt_finish(void)
{
    if (threaded <= 0 || on_render) return;
    game_wait(written, -1);
    tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
}

typedef struct { d3d_rt_fn fn; void *arg; } sync_call;
static void run_sync(void *payload) { sync_call *c = (sync_call *)payload; c->fn(c->arg); }

void d3d_rt_sync(d3d_rt_fn fn, void *arg)
{
    if (threaded <= 0 || on_render) {
        ++executing;
        fn(arg);
        --executing;
        return;
    }
    sync_call c = { fn, arg };
    d3d_rt_call(run_sync, &c, sizeof c);
    ++stats.syncs;
    stats.sync_ns += game_wait(written, -1);
    tail_seen = atomic_load_explicit(&tail, memory_order_acquire);
}

void d3d_rt_frame_queued(void)
{
    if (threaded > 0) atomic_fetch_add(&frames_queued, 1);
}

void d3d_rt_frame_wait(int ahead)
{
    if (threaded <= 0) return;
    uint64_t waited = game_wait(0, ahead);
    if (waited) { ++stats.frame_waits; stats.frame_wait_ns += waited; }
}

void d3d_rt_frame_done(void)
{
    if (threaded > 0) atomic_fetch_sub(&frames_queued, 1);
}

void d3d_rt_stats(d3d_rt_stats_t *out)
{
    *out = stats;
    out->render_busy_ns = atomic_load_explicit(&render_busy_ns, memory_order_relaxed);
}

#ifdef VOID_RT_CHECK
void d3d_rt_gl_check(const char *name)
{
    static _Atomic int reported;
    if (threaded > 0 && !on_render && atomic_fetch_add(&reported, 1) < 20)
        void_log("[rt] CHECK FAILED: %s called on the game's thread", name);
}
#endif

/* ------------------------------------------------------------- the mirror
 * The render thread draws through a device of its own whose state follows the
 * game's: before each call that reads it the game's thread sends what changed
 * since the last one, as (offset, bytes) patches of whole 64-byte pieces that
 * setters touched and that differ from what was sent. Object pointers travel
 * as they are: the game's state holds a reference on each, and an object's
 * destruction is recorded after the state change that let it go. The render
 * targets travel after the state, at TARGETS_AT. */
uint32_t d3d_rt_dirty_bits[D3D_RT_DIRTY_WORDS];
static d3d_device mirror;
static d3d_state sent;
typedef struct { d3d_surface *rt[4], *ds, *backbuffer; } targets_t;
static targets_t sent_targets;
#define TARGETS_AT ((uint32_t)((sizeof(d3d_state) + 63u) & ~63u))
_Static_assert(TARGETS_AT + sizeof(targets_t) <= UINT16_MAX * 4u,
    "render-state patch offsets and lengths must fit 16-bit word counts");
_Static_assert(sizeof(d3d_state) % 4u == 0, "state patches move whole words");
#define CONSTANTS_LO ((uint32_t)offsetof(d3d_state, vs_f))
#define CONSTANTS_HI ((uint32_t)offsetof(d3d_state, viewport))
extern uint32_t d3d_constant_generation;

d3d_device *d3d_rt_device(void) { return &mirror; }

typedef struct { uint8_t *at, *last; uint32_t last_end; } patcher;

static void patch(patcher *w, uint32_t off, const void *data, uint32_t len)
{
    if (w->last && w->last_end == off) {          /* extends the previous patch */
        uint16_t h[2];
        memcpy(h, w->last, 4);
        h[1] = (uint16_t)(h[1] + len / 4);
        memcpy(w->last, h, 4);
    } else {
        uint16_t h[2] = { (uint16_t)(off / 4), (uint16_t)(len / 4) };
        w->last = w->at;
        memcpy(w->at, h, 4);
        w->at += 4;
    }
    memcpy(w->at, data, len);
    w->at += len;
    w->last_end = off + len;
}

/* Whether 64 bytes differ: inline, the compiler's vector compare. */
static inline int piece_differs(const uint8_t *a, const uint8_t *b)
{
    uint64_t x = 0;
    for (int i = 0; i < 8; ++i) {
        uint64_t u, v;
        memcpy(&u, a + 8 * i, 8);
        memcpy(&v, b + 8 * i, 8);
        x |= u ^ v;
    }
    return x != 0;
}

static void apply_state(void *args)
{
    const uint8_t *p = (const uint8_t *)args;
    for (;;) {
        uint16_t h[2];
        memcpy(h, p, 4);
        p += 4;
        if (!h[1]) break;
        uint32_t off = h[0] * 4u, len = h[1] * 4u;
        if (off >= TARGETS_AT) {
            targets_t t;
            memcpy(&t, p, sizeof t);
            memcpy(mirror.rt, t.rt, sizeof t.rt);
            mirror.ds = t.ds;
            mirror.backbuffer = t.backbuffer;
            mirror.fbo_dirty = 1;
        } else {
            memcpy((uint8_t *)&mirror.st + off, p, len);
            if (off < CONSTANTS_HI && off + len > CONSTANTS_LO) ++d3d_constant_generation;
        }
        p += len;
    }
}

void d3d_rt_sync_state(d3d_device *d)
{
    /* Worst case: every piece in its own patch, the targets, the end mark. */
    uint32_t reserve = (uint32_t)sizeof(d3d_state) + 4u * D3D_RT_STATE_PIECES + 8u + (uint32_t)sizeof(targets_t);
    const uint8_t *now = (const uint8_t *)&d->st;
    uint8_t *was = (uint8_t *)&sent;
    targets_t t;
    memcpy(t.rt, d->rt, sizeof t.rt);
    t.ds = d->ds;
    t.backbuffer = d->backbuffer;
    int targets = memcmp(&t, &sent_targets, sizeof t) != 0;
    int any = targets;
    for (uint32_t word = 0; word < D3D_RT_DIRTY_WORDS && !any; ++word) any = d3d_rt_dirty_bits[word] != 0;
    if (!any) return;
    uint8_t *start = (uint8_t *)d3d_rt_begin(apply_state, reserve);
    patcher w = { start, NULL, 0 };
    for (uint32_t word = 0; word < D3D_RT_DIRTY_WORDS; ++word) {
        uint32_t b = d3d_rt_dirty_bits[word];
        d3d_rt_dirty_bits[word] = 0;
        while (b) {
            uint32_t off = (word * 32u + (uint32_t)__builtin_ctz(b)) * 64u;
            b &= b - 1;
            if (off >= sizeof(d3d_state)) continue;
            uint32_t len = sizeof(d3d_state) - off < 64 ? (uint32_t)sizeof(d3d_state) - off : 64;
            if (len == 64 ? !piece_differs(now + off, was + off) : !memcmp(now + off, was + off, len)) continue;
            memcpy(was + off, now + off, len);
            patch(&w, off, now + off, len);
        }
    }
    if (targets) {
        sent_targets = t;
        w.last = NULL;
        patch(&w, TARGETS_AT, &t, sizeof t);
    }
    uint16_t end[2] = { 0, 0 };
    memcpy(w.at, end, 4);
    w.at += 4;
    d3d_rt_commit_size((uint32_t)(w.at - start));
}

/* The mirror starts as the device does (CreateDevice, Reset): its present
 * parameters and frame count; its state follows with the next sync, all of it. */
typedef struct { uint32_t pp[14]; uint32_t frame; } mirror_init_args;
static void mirror_init(void *args)
{
    const mirror_init_args *a = (const mirror_init_args *)args;
    memcpy(mirror.pp, a->pp, sizeof mirror.pp);
    mirror.frame = a->frame;
    mirror.fbo_dirty = 1;
}

void d3d_rt_device_reset(d3d_device *d)
{
    mirror_init_args a;
    memcpy(a.pp, d->pp, sizeof a.pp);
    a.frame = d->frame;
    /* Everything again: what was sent belongs to the state before. */
    memset(d3d_rt_dirty_bits, 0xFF, sizeof d3d_rt_dirty_bits);
    memset(&sent, 0xA5, sizeof sent);
    memset(&sent_targets, 0, sizeof sent_targets);
    sent_targets.backbuffer = (d3d_surface *)(uintptr_t)1;    /* never a real one: targets are sent too */
    d3d_rt_call(mirror_init, &a, sizeof a);
}

/* The frame number the render thread's records belong to (present). */
void d3d_rt_mirror_frame(uint32_t frame);
void d3d_rt_mirror_frame(uint32_t frame) { mirror.frame = frame; }
