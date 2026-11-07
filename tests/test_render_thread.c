/* The render thread module (android/host/d3d9_thread.c) on its own: the same
 * records run in the same order inline and on the thread; the ring wraps and
 * fills; big payloads; nested records; answers mid-stream; positions; frame
 * lag; the state mirror follows the device piece by piece.
 * Build: tools/build_host_test.py tests/test_render_thread.c --objects build/<task>/obj */
#include "../android/host/d3d9_thread.c"
#include <assert.h>

/* ------------------------------------------------------------- a trace */
#define TRACE_MAX (1u << 20)
static uint32_t trace[TRACE_MAX];
static _Atomic uint32_t trace_count;
static int nested_ok = 1;

static void put(uint32_t value) { uint32_t n = atomic_load(&trace_count); assert(n < TRACE_MAX); trace[n] = value; atomic_store(&trace_count, n + 1); }

typedef struct { uint32_t id, size, seed; } rec_args;

/* Checks its payload (a pattern of its seed) and logs its id. */
static void run_rec(void *p)
{
    const rec_args *a = (const rec_args *)p;
    const uint8_t *data = (const uint8_t *)(a + 1);
    for (uint32_t i = 0; i < a->size; i += 997) assert(data[i] == (uint8_t)(a->seed + i));
    if (a->size) assert(data[a->size - 1] == (uint8_t)(a->seed + a->size - 1));
    put(a->id);
}

static void run_nested_inner(void *p) { put(0x80000000u | *(uint32_t *)p); }
/* A record that records: inside a recorded call the inner one runs at once. */
static void run_nested_outer(void *p)
{
    uint32_t id = *(uint32_t *)p;
    put(id);
    if (!d3d_rt_executing()) nested_ok = 0;
    uint32_t inner = id;
    d3d_rt_call(run_nested_inner, &inner, sizeof inner);
    put(id | 0x40000000u);
}

static void record(uint32_t id, uint32_t size)
{
    rec_args *a = (rec_args *)d3d_rt_begin(run_rec, (uint32_t)sizeof *a + size);
    a->id = id; a->size = size; a->seed = id * 2654435761u;
    uint8_t *data = (uint8_t *)(a + 1);
    for (uint32_t i = 0; i < size; ++i) data[i] = (uint8_t)(a->seed + i);
    d3d_rt_commit();
}

static uint32_t rng = 12345;
static uint32_t next(void) { rng = rng * 1103515245u + 12345u; return rng >> 8; }

/* The script both modes run: small, medium, a few big (heap) records, nested ones and syncs. */
static void read_trace_count(void *out) { *(uint32_t *)out = atomic_load(&trace_count); }
static void script(uint32_t records)
{
    rng = 12345;
    for (uint32_t i = 1; i <= records; ++i) {
        uint32_t kind = next() % 100, size;
        if (kind < 70) size = next() % 256;
        else if (kind < 97) size = next() % (256u << 10);
        else size = BIG_BYTES + next() % (1u << 20);
        if (kind == 50) {
            uint32_t id = i;
            d3d_rt_call(run_nested_outer, &id, sizeof id);
        } else if (kind == 51) {
            /* A read-back mid-stream: everything recorded before it has run. */
            uint32_t seen = 0;
            d3d_rt_sync(read_trace_count, &seen);
            assert(seen == atomic_load(&trace_count));
            put(0x20000000u | i);
        } else {
            record(i, size);
        }
    }
}

/* ---------------------------------------------------------- the mirror */
static d3d_device dev;
uint32_t d3d_constant_generation;

static void mutate(void)
{
    uint32_t what = next() % 6;
    if (what == 0) { uint32_t i = next() % 256; dev.st.rs[i] = next(); D3D_RT_DIRTY(&dev, dev.st.rs[i]); }
    else if (what == 1) {
        uint32_t start = next() % 250, count = 1 + next() % 6;
        for (uint32_t r = start; r < start + count; ++r) for (int k = 0; k < 4; ++k) dev.st.vs_f[r][k] = (float)next();
        d3d_rt_dirty(&dev, dev.st.vs_f[start], 16u * count);
    } else if (what == 2) { uint32_t t = next() % 512; dev.st.transforms[t][next() % 16] = 1.5f; D3D_RT_DIRTY(&dev, dev.st.transforms[t]); }
    else if (what == 3) { dev.st.textures[next() % 20] = (void *)(uintptr_t)(next() | 1); d3d_rt_dirty(&dev, dev.st.textures, sizeof dev.st.textures); }
    else if (what == 4) { dev.rt[next() % 4] = (d3d_surface *)(uintptr_t)(next() << 4); }
    else { dev.st.clip_planes[5][3] = (float)next(); D3D_RT_DIRTY(&dev, dev.st.clip_planes[5][3]); }
    /* A write the game makes into a state block being recorded is not the device's. */
    static d3d_state elsewhere;
    elsewhere.rs[3] = next();
    D3D_RT_DIRTY(&dev, elsewhere.rs[3]);
}

static void compare_mirror(void *unused)
{
    (void)unused;
    d3d_device *m = d3d_rt_device();
    assert(!memcmp(&m->st, &dev.st, sizeof dev.st));
    assert(!memcmp(m->rt, dev.rt, sizeof dev.rt) && m->ds == dev.ds && m->backbuffer == dev.backbuffer);
}

static void mirror_script(void)
{
    rng = 777;
    memset(&dev, 0, sizeof dev);
    dev.pp[0] = 640; dev.frame = 9;
    d3d_rt_device_reset(&dev);
    uint32_t generation = d3d_constant_generation;
    for (int i = 0; i < 20000; ++i) {
        for (int k = next() % 5; k >= 0; --k) mutate();
        d3d_rt_sync_state(&dev);
        if (i % 997 == 0) d3d_rt_sync(compare_mirror, NULL);
    }
    d3d_rt_sync(compare_mirror, NULL);
    assert(d3d_rt_device()->pp[0] == 640 && d3d_rt_device()->frame == 9);
    assert(d3d_constant_generation != generation);   /* constant pieces counted on arrival */
}

/* ------------------------------------------------------------ runtime */
void void_log(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
void void_fatal(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); abort(); }
uint64_t void_monotonic_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec; }
const char *void_data_dir(void) { return "/nonexistent"; }
void void_blocking_begin(void) { assert(!"no machine here"); }
void void_blocking_end(void) { assert(!"no machine here"); }

static void slow(void *ms) { struct timespec t = { 0, *(int *)ms * 1000000L }; nanosleep(&t, NULL); put(0x10000000u); }
static void frame_done(void *unused) { (void)unused; d3d_rt_frame_done(); }

int main(void)
{
    enum { RECORDS = 6000 };
    /* Inline: the reference order. */
    threaded = 0;
    script(RECORDS);
    uint32_t inline_count = atomic_load(&trace_count);
    static uint32_t reference[TRACE_MAX];
    memcpy(reference, trace, inline_count * sizeof *trace);
    assert(nested_ok);
    mirror_script();
    puts("PASS inline: records, nested calls, syncs and state mirror run at once");

    /* The same script on the render thread. */
    atomic_store(&trace_count, 0);
    threaded = -1;
    setenv("VOID_RENDER_THREAD", "1", 1);
    d3d_rt_start();
    assert(d3d_rt_threaded());
    script(RECORDS);
    d3d_rt_finish();
    assert(atomic_load(&trace_count) == inline_count);
    assert(!memcmp(reference, trace, inline_count * sizeof *trace));
    assert(nested_ok);
    d3d_rt_stats_t s;
    d3d_rt_stats(&s);
    assert(s.bytes > 3ull * RING_BYTES);                /* the ring wrapped several times */
    printf("PASS threaded: %u records in the inline order, %.0f MiB through the %u MiB ring\n",
           inline_count, (double)s.bytes / 1048576.0, RING_BYTES >> 20);

    /* A full ring: the render thread held up, the game records more than the ring holds. */
    int hold = 400;
    uint32_t before = atomic_load(&trace_count);
    d3d_rt_call(slow, &hold, sizeof hold);
    for (uint32_t i = 0; i < 400; ++i) record(0x01000000u + i, 200u << 10);    /* ~78 MiB */
    d3d_rt_finish();
    d3d_rt_stats(&s);
    assert(s.ring_waits > 0 && atomic_load(&trace_count) == before + 401);
    for (uint32_t i = 0; i < 400; ++i) assert(trace[before + 1 + i] == 0x01000000u + i);
    printf("PASS full ring: %llu waits for room, every record intact and in order\n", (unsigned long long)s.ring_waits);

    /* Positions: a slow record not yet run, then reached. */
    int ms = 120;
    d3d_rt_call(slow, &ms, sizeof ms);
    uint64_t at = d3d_rt_position();
    d3d_rt_flush();
    assert(!d3d_rt_reached(at));
    uint64_t t0 = void_monotonic_ns();
    d3d_rt_wait_for(at);
    assert(d3d_rt_reached(at) && void_monotonic_ns() - t0 > 50000000ull);
    puts("PASS positions: not reached while the render thread is behind, wait_for returns once it ran");

    /* Frames: the game runs at most one present ahead. */
    for (int f = 0; f < 3; ++f) {
        d3d_rt_call(slow, &ms, sizeof ms);
        d3d_rt_frame_queued();
        d3d_rt_call(frame_done, NULL, 0);
        d3d_rt_flush();
        t0 = void_monotonic_ns();
        d3d_rt_frame_wait(1);
        assert(atomic_load(&frames_queued) <= 1);
        if (f) assert(void_monotonic_ns() - t0 > 50000000ull);    /* waited for the frame before */
    }
    d3d_rt_frame_wait(0);
    assert(!atomic_load(&frames_queued));
    puts("PASS frames: one present queued at most, the game waits for the one before");

    mirror_script();
    d3d_rt_finish();
    puts("PASS mirror: 20000 syncs of random setters (dirty pieces, targets, ignored foreign writes) equal the device");
    return 0;
}
