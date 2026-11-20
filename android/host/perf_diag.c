/* The frame monitor (all three editions).
 *
 * 1. Diagnostics for long frames on HyperOS (or any device with the perf-diag flag file):
 *    machine-readable "[hyperos] ..." lines in homm5.log, specified in research/hyperos-diag.md.
 *    The game's thread only takes counters at the end of each frame and pushes one record into a
 *    single-producer ring (atomics only, no allocation, no lock it shares); a sampler thread
 *    (nice +10, any CPU, outside the machine) reads cpufreq/thermal/proc files, joins the records
 *    with its samples and the GPU timestamps, classifies long frames and writes every line.
 * 2. The ADPF hint session (APerformanceHint, API 33+, through dlsym): the game's thread, the
 *    render thread and FMOD's threads, the effective frame period as the target and each frame's
 *    work without the limiter's sleep and the vsync wait. On by default on HyperOS (MediaTek's
 *    PowerHAL hands the hints to FPSGO whatever the package name), elsewhere with the adpf flag.
 * Java (PerfMonitor.java) configures both before the engine starts. Without diagnostics no
 * line, thread or descriptor of part 1 exists. */
#define _GNU_SOURCE
#include "host.h"
#include "perf_diag.h"
#include <ctype.h>
#include <dirent.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <sched.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/system_properties.h>
#include <time.h>
#include <unistd.h>

/* The edition this engine was built for (tools/build_android.py's edition.h), for the start line. */
#ifdef HOMM5_EDITION
#define DIAG_EDITION HOMM5_EDITION
#else
#define DIAG_EDITION "toe"
#endif
#ifdef VOID_ANDROID_APP
#include <jni.h>
#endif

#include <link.h>
#include <elf.h>

int d3d_rt_render_tid(void);
void void_port_scales(float *ui, float *render);

/* This library's GNU build ID for the start line (core.c logs it at startup too). */
static int find_own_build_id(struct dl_phdr_info *module, size_t size, void *data)
{
    (void)size;
    char *out = (char *)data;
    uintptr_t self = (uintptr_t)find_own_build_id;
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
            if (header->n_type == NT_GNU_BUILD_ID && header->n_namesz == 4 && !memcmp(name, "GNU", 4) && desc + header->n_descsz <= end) {
                for (uint32_t b = 0; b < header->n_descsz && b < 32; ++b) sprintf(out + 2 * b, "%02x", desc[b]);
                return 1;
            }
            note = desc + ((header->n_descsz + 3) & ~3u);
        }
    }
    return 1;
}

const char *void_build_id(void)
{
    static char build_id[65];
    if (!build_id[0]) dl_iterate_phdr(find_own_build_id, build_id);
    return build_id[0] ? build_id : "?";
}

int void_diag_on, void_frame_monitor_on;
static unsigned perf_options;
static int hyperos_native, hyperos_any;
static char java_info[1024], inject_file[1024];
unsigned void_perf_options(void) { return perf_options; }

static uint64_t mono_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static int gettid_(void) { return (int)syscall(SYS_gettid); }

/* ------------------------------------------------------------------ lines */
#define DIAG_CAP_BYTES (2u << 20)
static _Atomic uint64_t diag_bytes;
static _Atomic int cap_reached;

static void diag_vline(int essential, uint64_t at_ns, const char *type, const char *fmt, va_list ap)
{
    char body[1800];
    int wanted = vsnprintf(body, sizeof body, fmt, ap);
    if (wanted >= (int)sizeof body) {
        /* Cut at the last whole token and say so. */
        char *space = strrchr(body, ' ');
        if (space) snprintf(space, sizeof body - (size_t)(space - body), " truncated=1");
    }
    char line[2000];
    int n = snprintf(line, sizeof line, "[hyperos] %s t=%.3f diag=1%s%s", type, (double)(at_ns ? at_ns : mono_ns()) / 1e6,
                     *body ? " " : "", body);
    if (n <= 0) return;
    uint64_t total = atomic_fetch_add(&diag_bytes, (uint64_t)n + 1u) + (uint64_t)n + 1u;
    if (total > DIAG_CAP_BYTES && !essential) {
        if (!atomic_exchange(&cap_reached, 1))
            void_log("[hyperos] event t=%.3f diag=1 kind=cap_reached bytes=%llu", (double)mono_ns() / 1e6,
                     (unsigned long long)total);
        return;
    }
    void_log("%s", line);
}

static void diag_line(const char *type, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    diag_vline(!strcmp(type, "win") || !strcmp(type, "end"), 0, type, fmt, ap);
    va_end(ap);
}

/* A line about a moment in the past: t is that moment (a long frame's end), not the write. */
static void diag_line_at(uint64_t at_ns, const char *type, const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    diag_vline(0, at_ns, type, fmt, ap);
    va_end(ap);
}

/* Free text as one value: space, percent and control characters percent-encoded. */
static const char *word(const char *in, char *out, size_t cap)
{
    size_t n = 0;
    for (const unsigned char *p = (const unsigned char *)(in ? in : ""); *p && n + 4 < cap; ++p) {
        if (*p <= ' ' || *p == '%' || *p == 0x7F) n += (size_t)snprintf(out + n, cap - n, "%%%02X", *p);
        else out[n++] = (char)*p;
    }
    out[n] = 0;
    return out;
}

/* A small text file (sysfs/procfs); -errno when unreadable. */
static int read_text(const char *path, char *out, size_t cap)
{
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) { out[0] = 0; return -errno; }
    ssize_t got = read(fd, out, cap - 1);
    int e = errno;
    close(fd);
    if (got < 0) { out[0] = 0; return -e; }
    out[got] = 0;
    while (got > 0 && (out[got - 1] == '\n' || out[got - 1] == ' ')) out[--got] = 0;
    return (int)got;
}

static long read_long_fd(int fd)
{
    char text[64];
    ssize_t got = pread(fd, text, sizeof text - 1, 0);
    if (got <= 0) return -1;
    text[got] = 0;
    return strtol(text, NULL, 10);
}

/* "value" or "!errnoN" for one file, one word. */
static const char *file_value(const char *path, char *out, size_t cap)
{
    char text[256], enc[512];
    int r = read_text(path, text, sizeof text);
    if (r < 0) snprintf(out, cap, "!errno%d", -r);
    else snprintf(out, cap, "%s", word(text, enc, sizeof enc));
    return out;
}

/* ------------------------------------------------------- state from Java */
static _Atomic uint32_t st_vsync50, st_vsync95, st_batt_temp, st_mismatch_choreo;
static _Atomic int st_plugged = -1, st_thermal = -1, st_power_save = -1;
static _Atomic uint64_t lifecycle_ns[16];
static _Atomic uint32_t lifecycle_head;
static _Atomic int pause_end_request;

static float fbits(uint32_t bits) { float f; memcpy(&f, &bits, sizeof f); return f; }
static uint32_t bitsf(float f) { uint32_t bits; memcpy(&bits, &f, sizeof bits); return bits; }

static int near_lifecycle(uint64_t from, uint64_t to)
{
    for (int i = 0; i < 16; ++i) {
        uint64_t at = atomic_load_explicit(&lifecycle_ns[i], memory_order_relaxed);
        if (at && at + 1000000000ull >= from && at <= to + 1000000000ull) return 1;
    }
    return 0;
}

/* ----------------------------------------------- frame records (game -> sampler) */
enum { C_CPU, C_RUNQ, C_LOCK, C_PACE, C_SWAP, C_IO, C_GPU, C_OTHER, C_COUNT };
static const char *const cause_names[C_COUNT] = { "cpu", "runq", "lock", "pace", "swap", "io", "gpu", "other" };

typedef struct {
    uint64_t t_end, wall, cpu, runq, lock, lock_max, pace, swap, frame_wait, sync, ring_wait, render_busy;
    uint64_t io, io_bytes, diag_ns;
    uint32_t frame, majflt, vcsw, ivcsw;
    int holder, cpu_id;
    uint8_t migrated, runq_valid, threaded;
    float cap, eff_cap;
} frame_rec;

#define FRAME_RING 1024u
static frame_rec frame_ring[FRAME_RING];
static _Atomic uint32_t ring_head, ring_tail;
static _Atomic uint32_t frames_dropped;

/* The largest component; gpu only when it exceeds 0.6 of the frame and every other one. */
static int classify(const double c[C_COUNT], double wall)
{
    int best = C_CPU;
    double value = -1;
    for (int i = 0; i < C_COUNT; ++i) {
        if (i == C_GPU) continue;
        if (c[i] > value) { value = c[i]; best = i; }
    }
    if (c[C_GPU] > 0.6 * wall && c[C_GPU] > value) best = C_GPU;
    return best;
}

/* ------------------------------------------------- GPU timestamps (render thread) */
#define GPU_RING 64u
typedef struct { _Atomic uint32_t frame; _Atomic int64_t gpu_ns, present_ns; } gpu_rec;
static gpu_rec gpu_ring[GPU_RING];

void void_diag_gpu_frame(uint32_t frame, int64_t gpu_ns, int64_t present_ns)
{
    if (!void_diag_on) return;
    gpu_rec *r = &gpu_ring[frame % GPU_RING];
    atomic_store_explicit(&r->frame, 0, memory_order_relaxed);
    atomic_store_explicit(&r->gpu_ns, gpu_ns, memory_order_relaxed);
    atomic_store_explicit(&r->present_ns, present_ns, memory_order_relaxed);
    atomic_store_explicit(&r->frame, frame + 1u, memory_order_release);
}

static int gpu_lookup(uint32_t frame, int64_t *gpu_ns, int64_t *present_ns)
{
    gpu_rec *r = &gpu_ring[frame % GPU_RING];
    if (atomic_load_explicit(&r->frame, memory_order_acquire) != frame + 1u) return 0;
    *gpu_ns = atomic_load_explicit(&r->gpu_ns, memory_order_relaxed);
    *present_ns = atomic_load_explicit(&r->present_ns, memory_order_relaxed);
    return atomic_load_explicit(&r->frame, memory_order_acquire) == frame + 1u;
}

/* ------------------------------------------------------------ EGL identity */
static struct {
    char egl_vendor[96], egl_version[96], gl_renderer[128], gl_version[128];
    int frame_timestamps, presentation_time, fence_sync, swap_ok, ww, wh, rw, rh;
} egl_info;
static _Atomic uint64_t egl_ready_ns;

void void_diag_egl(const char *egl_vendor, const char *egl_version, const char *gl_renderer, const char *gl_version,
                   int frame_timestamps, int presentation_time, int fence_sync, int swap_interval_ok,
                   int window_w, int window_h, int render_w, int render_h)
{
    if (!void_diag_on) return;
    snprintf(egl_info.egl_vendor, sizeof egl_info.egl_vendor, "%s", egl_vendor ? egl_vendor : "");
    snprintf(egl_info.egl_version, sizeof egl_info.egl_version, "%s", egl_version ? egl_version : "");
    snprintf(egl_info.gl_renderer, sizeof egl_info.gl_renderer, "%s", gl_renderer ? gl_renderer : "");
    snprintf(egl_info.gl_version, sizeof egl_info.gl_version, "%s", gl_version ? gl_version : "");
    egl_info.frame_timestamps = frame_timestamps;
    egl_info.presentation_time = presentation_time;
    egl_info.fence_sync = fence_sync;
    egl_info.swap_ok = swap_interval_ok;
    egl_info.ww = window_w; egl_info.wh = window_h; egl_info.rw = render_w; egl_info.rh = render_h;
    atomic_store(&egl_ready_ns, mono_ns());
}

/* -------------------------------------------------------------------- ADPF */
typedef void *(*hint_manager_fn)(void);
typedef void *(*hint_create_fn)(void *, const int32_t *, size_t, int64_t);
typedef int64_t (*hint_rate_fn)(void *);
typedef int (*hint_update_fn)(void *, int64_t);
typedef int (*hint_report_fn)(void *, int64_t);
typedef void (*hint_close_fn)(void *);
typedef int (*hint_threads_fn)(void *, const int32_t *, size_t);
typedef void *(*thermal_acquire_fn)(void);
typedef float (*thermal_headroom_fn)(void *, int);
typedef int (*thermal_status_fn)(void *);

static struct {
    int wanted, loaded;
    hint_manager_fn get_manager;
    hint_create_fn create;
    hint_rate_fn rate;
    hint_update_fn update;
    hint_report_fn report;
    hint_close_fn close;
    hint_threads_fn set_threads;
    void *manager, *session;
    int64_t target_ns, rate_ns;
    int32_t tids[16];
    int ntids, failures;
    uint64_t next_threads_ns, retry_ns;
} adpf;
/* For the sampler's win line: 0 off, 1 on, 2 unavailable, 3 error, 4 idle (no surface). */
static _Atomic int adpf_state;
static _Atomic uint32_t adpf_reports, adpf_errors;
static _Atomic int64_t adpf_target;

static void *libandroid(void)
{
    static void *lib;
    if (!lib) lib = dlopen("libandroid.so", RTLD_NOW | RTLD_LOCAL);
    return lib;
}

static void adpf_load(void)
{
    if (adpf.loaded) return;
    adpf.loaded = 1;
    void *lib = libandroid();
    if (!lib) { atomic_store(&adpf_state, 2); return; }
    adpf.get_manager = (hint_manager_fn)dlsym(lib, "APerformanceHint_getManager");
    adpf.create = (hint_create_fn)dlsym(lib, "APerformanceHint_createSession");
    adpf.rate = (hint_rate_fn)dlsym(lib, "APerformanceHint_getPreferredUpdateRateNanos");
    adpf.update = (hint_update_fn)dlsym(lib, "APerformanceHint_updateTargetWorkDuration");
    adpf.report = (hint_report_fn)dlsym(lib, "APerformanceHint_reportActualWorkDuration");
    adpf.close = (hint_close_fn)dlsym(lib, "APerformanceHint_closeSession");
    adpf.set_threads = (hint_threads_fn)dlsym(lib, "APerformanceHint_setThreads");
    adpf.manager = adpf.get_manager ? adpf.get_manager() : NULL;
    if (!adpf.manager || !adpf.create || !adpf.update || !adpf.report || !adpf.close) {
        atomic_store(&adpf_state, 2);
        void_log("[adpf] unavailable on this system (APerformanceHint needs Android 13)");
        return;
    }
    adpf.rate_ns = adpf.rate ? adpf.rate(adpf.manager) : 0;
}

/* The session's threads: this one, the render thread, FMOD's guest threads. */
static int adpf_collect(int32_t *tids, int max)
{
    int n = 0;
    tids[n++] = gettid_();
    int render = d3d_rt_render_tid();
    if (render > 0 && n < max) tids[n++] = render;
    void_guest_info guests[48];
    int count = void_guest_threads(guests, 48, 0);
    for (int i = 0; i < count && n < max; ++i)
        if (!strncmp(guests[i].name, "h5-fmod", 7) && guests[i].tid != tids[0]) tids[n++] = guests[i].tid;
    return n;
}

static void adpf_close(int state)
{
    if (adpf.session) adpf.close(adpf.session);
    adpf.session = NULL;
    atomic_store(&adpf_state, state);
}

static void adpf_open(uint64_t now, int64_t target)
{
    if (now < adpf.retry_ns || adpf.failures >= 3) return;
    adpf.ntids = adpf_collect(adpf.tids, 16);
    adpf.target_ns = target;
    adpf.session = adpf.create(adpf.manager, adpf.tids, (size_t)adpf.ntids, target);
    adpf.next_threads_ns = now + 2000000000ull;
    if (!adpf.session) {
        ++adpf.failures;
        adpf.retry_ns = now + 10000000000ull;
        atomic_store(&adpf_state, 3);
        atomic_fetch_add(&adpf_errors, 1);
        void_log("[adpf] createSession failed (%d of 3)", adpf.failures);
        if (void_diag_on) diag_line("event", "kind=adpf op=create rc=-1 threads=%d target=%.2f", adpf.ntids, target / 1e6);
        return;
    }
    atomic_store(&adpf_state, 1);
    atomic_store(&adpf_target, target);
    char list[160] = "";
    for (int i = 0, n = 0; i < adpf.ntids && n < (int)sizeof list - 12; ++i)
        n += snprintf(list + n, sizeof list - (size_t)n, "%s%d", i ? "," : "", adpf.tids[i]);
    void_log("[adpf] session: threads %s, target %.2f ms, update rate %.2f ms", list, target / 1e6, adpf.rate_ns / 1e6);
    if (void_diag_on) diag_line("event", "kind=adpf op=create rc=0 threads=%s target=%.2f", list, target / 1e6);
}

static void adpf_frame(const void_frame_in *in, uint64_t now, uint64_t actual)
{
    if (!adpf.wanted) return;
    adpf_load();
    if (atomic_load(&adpf_state) == 2) return;
    float fps = in->eff_cap > 0 ? in->eff_cap : in->cap > 0 ? in->cap : 60.0f;
    int64_t target = (int64_t)(1e9 / fps);
    if (!in->surface_live) { if (adpf.session) adpf_close(4); return; }
    if (!adpf.session) { adpf_open(now, target); if (!adpf.session) return; }
    if (target != adpf.target_ns) {
        int rc = adpf.update(adpf.session, target);
        adpf.target_ns = target;
        atomic_store(&adpf_target, target);
        if (rc) atomic_fetch_add(&adpf_errors, 1);
        if (void_diag_on) diag_line("event", "kind=adpf op=target rc=%d target=%.2f", rc, target / 1e6);
    }
    if (now >= adpf.next_threads_ns) {
        adpf.next_threads_ns = now + 2000000000ull;
        int32_t tids[16];
        int n = adpf_collect(tids, 16);
        if (n != adpf.ntids || memcmp(tids, adpf.tids, sizeof *tids * (size_t)n)) {
            int rc = -1;
            if (adpf.set_threads) rc = adpf.set_threads(adpf.session, tids, (size_t)n);
            if (rc) { adpf_close(0); adpf_open(now, target); }
            else { memcpy(adpf.tids, tids, sizeof *tids * (size_t)n); adpf.ntids = n; }
            if (void_diag_on) diag_line("event", "kind=adpf op=threads rc=%d threads=%d", rc, n);
            if (!adpf.session) return;
        }
    }
    int rc = adpf.report(adpf.session, (int64_t)(actual > 1000 ? actual : 1000));
    if (rc) {
        uint32_t errors = atomic_fetch_add(&adpf_errors, 1) + 1u;
        if (errors <= 5 && void_diag_on) diag_line("event", "kind=adpf op=report rc=%d", rc);
        if (rc == EPIPE || rc == -EPIPE) adpf_close(3);
    } else {
        atomic_fetch_add_explicit(&adpf_reports, 1, memory_order_relaxed);
    }
}

/* ------------------------------------------------------------ diag-inject */
enum { INJECT_CPU, INJECT_LOCK, INJECT_PACE, INJECT_IO };
/* 60 ms: the prompt's 30 ms only dominates a 60 FPS frame; a CPU-bound 30 FPS scene spends ~33 ms
 * of CPU per frame, and the injected component must be the largest to test the classifier. */
#define INJECT_NS 60000000ull
static const char *const inject_names[] = { "cpu", "lock", "pace", "io" };
static _Atomic uint64_t inject_pace_ns;
static _Atomic int inject_lock_request;
static pthread_mutex_t inject_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t inject_cond = PTHREAD_COND_INITIALIZER;
static uint64_t inject_io_offset;
static _Atomic int inject_tid;

uint64_t void_diag_inject_pace(void) { return atomic_exchange(&inject_pace_ns, 0); }

static void spin_until(uint64_t until) { while (mono_ns() < until) {} }

/* Another guest thread that takes the machine and sleeps INJECT_NS with it (cause_lock, holder). */
static void *inject_main(void *unused)
{
    (void)unused;
    prctl(PR_SET_NAME, "h5-diag-inject", 0, 0, 0);
    atomic_store(&inject_tid, gettid_());
    for (;;) {
        pthread_mutex_lock(&inject_lock);
        while (!atomic_load(&inject_lock_request)) pthread_cond_wait(&inject_cond, &inject_lock);
        atomic_store(&inject_lock_request, 0);
        pthread_mutex_unlock(&inject_lock);
        void_machine_enter();
        struct timespec nap = { 0, (long)INJECT_NS };
        while (nanosleep(&nap, &nap) && errno == EINTR) {}
        void_machine_leave();
    }
    return NULL;
}

/* INJECT_NS of reads from a large game file with its cache dropped (off-CPU waits: cause_io). */
static void inject_io(void)
{
    if (!inject_file[0]) return;
    int fd = open(inject_file, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return;
    struct stat st;
    static uint8_t buffer[256 * 1024];
    uint64_t start = mono_ns(), bytes = 0;
    if (!fstat(fd, &st) && st.st_size > (off_t)sizeof buffer) {
        posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);
        while (mono_ns() - start < INJECT_NS) {
            if (inject_io_offset + sizeof buffer > (uint64_t)st.st_size) inject_io_offset = 0;
            ssize_t got = pread(fd, buffer, sizeof buffer, (off_t)inject_io_offset);
            if (got <= 0) break;
            inject_io_offset += (uint64_t)got + 7u * sizeof buffer;   /* skip ahead: no read-ahead hits */
            bytes += (uint64_t)got;
        }
    }
    close(fd);
    void_perf_add(VOID_PERF_FILE_READ, mono_ns() - start, bytes);
}

/* ---------------------------------------------------- the game's thread */
static struct {
    int init, tid, sched_fd, last_cpu_id, runq_sparse, runq_reads;
    uint64_t last_end, last_cpu, last_runq, last_lock, last_pace, last_swap, last_fw, last_sync, last_ring, last_busy;
    uint64_t runq_cost_ns, first_ns, next_inject_ns;
    long last_majflt, last_nvcsw, last_nivcsw;
    unsigned inject_turn;
} game;
static _Atomic int game_tid_seen, last_threaded;
static _Atomic uint32_t frame_cap_bits, frame_eff_bits;
static _Atomic uint64_t first_frame_ns;

static uint64_t thread_cpu_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_THREAD_CPUTIME_ID, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

static int read_runq(uint64_t *wait)
{
    char text[96];
    if (game.sched_fd < 0) return 0;
    ssize_t got = pread(game.sched_fd, text, sizeof text - 1, 0);
    if (got <= 0) return 0;
    text[got] = 0;
    char *end = NULL;
    strtoull(text, &end, 10);
    *wait = strtoull(end, NULL, 10);
    return 1;
}

void void_frame_monitor(const void_frame_in *in)
{
    if (!adpf.wanted && !void_diag_on) return;
    uint64_t now = mono_ns();
    uint64_t cpu = thread_cpu_ns(), lock = void_lock_wait_ns();
    if (!game.init) {
        game.init = 1;
        game.tid = gettid_();
        atomic_store(&game_tid_seen, game.tid);
        game.sched_fd = void_diag_on ? open("/proc/thread-self/schedstat", O_RDONLY | O_CLOEXEC) : -1;
        game.last_end = now; game.last_cpu = cpu; game.last_lock = lock;
        game.last_pace = in->pace_ns; game.last_swap = in->swap_ns; game.last_fw = in->frame_wait_ns;
        game.last_sync = in->sync_ns; game.last_ring = in->ring_wait_ns; game.last_busy = in->render_busy_ns;
        game.last_cpu_id = sched_getcpu();
        game.first_ns = now;
        game.next_inject_ns = now + 10000000000ull;
        if (void_diag_on) {
            read_runq(&game.last_runq);
            struct rusage ru;
            if (!getrusage(RUSAGE_THREAD, &ru)) {
                game.last_majflt = ru.ru_majflt; game.last_nvcsw = ru.ru_nvcsw; game.last_nivcsw = ru.ru_nivcsw;
            }
            uint64_t io_ns, io_bytes;
            void_perf_io_take(&io_ns, &io_bytes);
            uint64_t wait_max; int holder;
            void_lock_take_frame(&wait_max, &holder);
            atomic_store(&first_frame_ns, now);
        }
        return;
    }
    uint64_t wall = now - game.last_end, pace = in->pace_ns - game.last_pace, swap_total = in->swap_ns - game.last_swap;
    uint64_t fw = in->frame_wait_ns - game.last_fw, sync = in->sync_ns - game.last_sync;
    uint64_t ring = in->ring_wait_ns - game.last_ring, busy = in->render_busy_ns - game.last_busy;
    game.last_end = now; game.last_pace = in->pace_ns; game.last_swap = in->swap_ns; game.last_fw = in->frame_wait_ns;
    game.last_sync = in->sync_ns; game.last_ring = in->ring_wait_ns; game.last_busy = in->render_busy_ns;
    /* The work of the frame: no limiter sleep, no wait for the display (the swap, or the game's
     * wait for the render thread that swaps); the render thread's own work without its swap. */
    if (adpf.wanted) {
        uint64_t waits = pace + (in->threaded ? fw : swap_total);
        uint64_t game_work = wall > waits ? wall - waits : 0;
        uint64_t render_work = in->threaded && busy > swap_total ? busy - swap_total : 0;
        adpf_frame(in, now, game_work > render_work ? game_work : render_work);
    }
    if (!void_diag_on) return;
    frame_rec r;
    memset(&r, 0, sizeof r);
    r.t_end = now; r.wall = wall; r.frame = in->frame;
    r.cpu = cpu - game.last_cpu; game.last_cpu = cpu;
    r.lock = lock - game.last_lock; game.last_lock = lock;
    void_lock_take_frame(&r.lock_max, &r.holder);
    r.pace = pace; r.frame_wait = fw; r.sync = sync; r.ring_wait = ring; r.render_busy = busy;
    r.swap = in->threaded ? fw + sync + ring : swap_total;
    r.threaded = (uint8_t)(in->threaded != 0);
    r.cap = in->cap; r.eff_cap = in->eff_cap;
    float period_ms = 1000.0f / (in->eff_cap > 0 ? in->eff_cap : in->cap > 0 ? in->cap : 60.0f);
    if (!game.runq_sparse || (double)wall > 1.5e6 * period_ms || (in->frame % 300u) == 0) {
        uint64_t before = mono_ns(), runq;
        if (read_runq(&runq)) {
            r.runq = runq - game.last_runq;
            game.last_runq = runq;
            r.runq_valid = 1;
        }
        if (game.runq_reads < 64) {
            game.runq_cost_ns += mono_ns() - before;
            if (++game.runq_reads == 64 && game.runq_cost_ns / 64 > 20000) game.runq_sparse = 1;
        }
    }
    void_perf_io_take(&r.io, &r.io_bytes);
    struct rusage ru;
    if (!getrusage(RUSAGE_THREAD, &ru)) {
        r.majflt = (uint32_t)(ru.ru_majflt - game.last_majflt);
        r.vcsw = (uint32_t)(ru.ru_nvcsw - game.last_nvcsw);
        r.ivcsw = (uint32_t)(ru.ru_nivcsw - game.last_nivcsw);
        game.last_majflt = ru.ru_majflt; game.last_nvcsw = ru.ru_nvcsw; game.last_nivcsw = ru.ru_nivcsw;
    }
    r.cpu_id = sched_getcpu();
    r.migrated = (uint8_t)(r.cpu_id != game.last_cpu_id);
    game.last_cpu_id = r.cpu_id;
    atomic_store_explicit(&last_threaded, in->threaded, memory_order_relaxed);
    atomic_store_explicit(&frame_cap_bits, bitsf(in->cap), memory_order_relaxed);
    atomic_store_explicit(&frame_eff_bits, bitsf(in->eff_cap), memory_order_relaxed);
    r.diag_ns = mono_ns() - now;
    uint32_t head = atomic_load_explicit(&ring_head, memory_order_relaxed);
    if (head - atomic_load_explicit(&ring_tail, memory_order_acquire) < FRAME_RING) {
        frame_ring[head % FRAME_RING] = r;
        atomic_store_explicit(&ring_head, head + 1u, memory_order_release);
    } else {
        atomic_fetch_add_explicit(&frames_dropped, 1, memory_order_relaxed);
    }
    if ((perf_options & PERF_OPT_INJECT) && now >= game.next_inject_ns) {
        game.next_inject_ns = now + 10000000000ull;
        int what = (int)(game.inject_turn++ % 4u);
        if (what == INJECT_LOCK)
            diag_line("event", "kind=inject what=%s frame=%u tid=%d comm=h5-diag-inject", inject_names[what], in->frame + 1u,
                      atomic_load(&inject_tid));
        else
            diag_line("event", "kind=inject what=%s frame=%u", inject_names[what], in->frame + 1u);
        if (what == INJECT_CPU) spin_until(mono_ns() + INJECT_NS);
        else if (what == INJECT_PACE) atomic_store(&inject_pace_ns, INJECT_NS);
        else if (what == INJECT_IO) inject_io();
        else {
            pthread_mutex_lock(&inject_lock);
            atomic_store(&inject_lock_request, 1);
            pthread_cond_signal(&inject_cond);
            pthread_mutex_unlock(&inject_lock);
        }
    }
}

/* ================================================================ sampler */
#define MAX_POLICIES 8
#define SAMPLE_RING 128u
typedef struct {
    int first_cpu, fd_cur, fd_min, fd_max;
    char related[32];
    long min_khz, max_khz, cur_khz, window_max_low;    /* window_max_low: scaling_max's minimum in the window */
} policy_t;
static policy_t policies[MAX_POLICIES];
static int policy_count, big_policy = -1, cpu_policy[64], cpu_count;
static long cpu_capacity_value[64];

typedef struct { uint64_t t; long khz[MAX_POLICIES]; long gpu_mhz, gpu_load; } sample_t;
static sample_t samples[SAMPLE_RING];
static uint32_t sample_count;

static int gpu_freq_fd = -1, gpu_load_fd = -1;
static char gpu_freq_path[128], gpu_load_path[128];
static int online_fd = -1;
static char online_last[64];
static void *thermal_manager;
static thermal_headroom_fn thermal_headroom;
static thermal_status_fn thermal_status_get;
static float headroom_now = NAN, headroom_10 = NAN;
static char psi_text[48] = "";
static float zone_max = NAN;

static long cpu_file(int cpu, const char *name)
{
    char path[128], text[64];
    snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/%s", cpu, name);
    return read_text(path, text, sizeof text) > 0 ? strtol(text, NULL, 10) : -1;
}

static int open_policy_file(int first_cpu, const char *name)
{
    char path[128];
    snprintf(path, sizeof path, "/sys/devices/system/cpu/cpufreq/policy%d/%s", first_cpu, name);
    return open(path, O_RDONLY | O_CLOEXEC);
}

static void policies_init(void)
{
    for (cpu_count = 0; cpu_count < 64; ++cpu_count) {
        char path[96];
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d", cpu_count);
        if (access(path, F_OK)) break;
        cpu_capacity_value[cpu_count] = cpu_file(cpu_count, "cpu_capacity");
        cpu_policy[cpu_count] = -1;
    }
    for (int cpu = 0; cpu < cpu_count && policy_count < MAX_POLICIES; ++cpu) {
        char path[96], text[64];
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpufreq/policy%d/related_cpus", cpu);
        if (read_text(path, text, sizeof text) <= 0) continue;
        policy_t *p = &policies[policy_count];
        p->first_cpu = cpu;
        snprintf(p->related, sizeof p->related, "%s", text);
        for (char *s = text; *s;) {
            char *end;
            long c = strtol(s, &end, 10);
            if (end == s) { ++s; continue; }
            if (c >= 0 && c < 64) cpu_policy[c] = policy_count;
            s = end;
        }
        p->fd_cur = open_policy_file(cpu, "scaling_cur_freq");
        p->fd_min = open_policy_file(cpu, "scaling_min_freq");
        p->fd_max = open_policy_file(cpu, "scaling_max_freq");
        ++policy_count;
    }
    long best = -1;
    for (int cpu = 0; cpu < cpu_count; ++cpu)
        if (cpu_policy[cpu] >= 0 && (cpu_capacity_value[cpu] > best || (cpu_capacity_value[cpu] == best && best < 0))) {
            best = cpu_capacity_value[cpu];
            big_policy = cpu_policy[cpu];
        }
    if (big_policy < 0 && policy_count) big_policy = policy_count - 1;
}

/* MediaTek GED (root-only on most phones), Adreno kgsl, generic gpu nodes: the first readable. */
static void gpu_nodes_init(void)
{
    static const char *const freq[] = { "/sys/kernel/ged/hal/current_freqency", "/sys/class/kgsl/kgsl-3d0/gpuclk",
                                        "/sys/kernel/gpu/gpu_clock", NULL };
    static const char *const load[] = { "/sys/kernel/ged/hal/gpu_utilization", "/sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
                                        "/sys/kernel/gpu/gpu_busy", NULL };
    for (int i = 0; freq[i] && gpu_freq_fd < 0; ++i) {
        int fd = open(freq[i], O_RDONLY | O_CLOEXEC);
        char text[64];
        if (fd >= 0 && pread(fd, text, sizeof text, 0) > 0) { gpu_freq_fd = fd; snprintf(gpu_freq_path, sizeof gpu_freq_path, "%s", freq[i]); }
        else if (fd >= 0) close(fd);
    }
    for (int i = 0; load[i] && gpu_load_fd < 0; ++i) {
        int fd = open(load[i], O_RDONLY | O_CLOEXEC);
        char text[64];
        if (fd >= 0 && pread(fd, text, sizeof text, 0) > 0) { gpu_load_fd = fd; snprintf(gpu_load_path, sizeof gpu_load_path, "%s", load[i]); }
        else if (fd >= 0) close(fd);
    }
}

/* The last integer of a GPU node in MHz (kHz/Hz values scaled down). */
static long gpu_value(int fd, int frequency)
{
    char text[128];
    ssize_t got = fd >= 0 ? pread(fd, text, sizeof text - 1, 0) : -1;
    if (got <= 0) return -1;
    text[got] = 0;
    long value = -1;
    for (char *s = text; *s;) {
        if (isdigit((unsigned char)*s)) { value = strtol(s, &s, 10); continue; }
        ++s;
    }
    if (frequency) { while (value > 5000) value /= 1000; }
    return value;
}

static void sample_now(uint64_t now)
{
    sample_t *s = &samples[sample_count % SAMPLE_RING];
    s->t = now;
    for (int i = 0; i < policy_count; ++i) {
        long khz = read_long_fd(policies[i].fd_cur);
        s->khz[i] = khz;
        policies[i].cur_khz = khz;
    }
    s->gpu_mhz = gpu_value(gpu_freq_fd, 1);
    s->gpu_load = gpu_value(gpu_load_fd, 0);
    ++sample_count;
}

/* Frequency of policy p over [from, to]: min and average of the samples (else the nearest). */
static void freq_over(int p, uint64_t from, uint64_t to, long *min_mhz, long *avg_mhz)
{
    long low = -1, sum = 0, n = 0, nearest = -1;
    uint64_t nearest_d = UINT64_MAX;
    uint32_t count = sample_count < SAMPLE_RING ? sample_count : SAMPLE_RING;
    for (uint32_t i = 0; i < count; ++i) {
        const sample_t *s = &samples[(sample_count - 1u - i) % SAMPLE_RING];
        if (p < 0 || s->khz[p] < 0) continue;
        uint64_t d = s->t > to ? s->t - to : from > s->t ? from - s->t : 0;
        if (d < nearest_d) { nearest_d = d; nearest = s->khz[p]; }
        if (s->t < from || s->t > to) continue;
        if (low < 0 || s->khz[p] < low) low = s->khz[p];
        sum += s->khz[p];
        ++n;
    }
    if (!n) { low = nearest; sum = nearest; n = 1; }
    *min_mhz = low >= 0 ? low / 1000 : -1;
    *avg_mhz = low >= 0 ? sum / n / 1000 : -1;
}

/* ---------------------------------------------------------------- windows */
#define WIN_MAX 2400
typedef struct {
    uint64_t start, end;
    int frames, lc_frames, over15, over2, over50, long_total, long_logged, runq_sparse;
    float walls[WIN_MAX];
    float onscreen[WIN_MAX];
    int non;
    double sum[C_COUNT], sum_long[C_COUNT];
    int nlong, cause[C_COUNT];
    double core_ms[64];
    uint64_t vcsw, ivcsw, diag_sum, diag_max;
    float cap, eff_cap;
} window_t;
static window_t win;
static struct {
    uint64_t start, frames, long_total, cause[C_COUNT];
    double maxfreq_s[24]; long maxfreq_level[24];
    int levels;
    double mismatch_s, seconds;
    uint64_t last_end_ns;
} session;
static _Atomic uint32_t long_frames_total;
static int64_t last_present_ns;
static uint32_t last_present_frame;

static int cmp_float(const void *a, const void *b)
{
    float x = *(const float *)a, y = *(const float *)b;
    return (x > y) - (x < y);
}

static float percentile(float *values, int n, double q)
{
    if (n <= 0) return NAN;
    int index = (int)(q * (n - 1) + 0.5);
    return values[index < 0 ? 0 : index >= n ? n - 1 : index];
}

static void window_reset(uint64_t start)
{
    memset(&win, 0, sizeof win);
    win.start = start;
}

static float mismatch_now(float cap)
{
    float hz = void_port_display_rate();
    return (hz > 0 && cap > hz + 0.5f) || fbits(atomic_load(&st_mismatch_choreo)) > 0.5f;
}

static void hold_text(char *out, size_t cap)
{
    void_guest_info guests[48];
    int n = void_guest_threads(guests, 48, 1);
    out[0] = 0;
    for (int k = 0; k < 3; ++k) {
        int best = -1;
        for (int i = 0; i < n; ++i)
            if (guests[i].hold_max_ns && (best < 0 || guests[i].hold_max_ns > guests[best].hold_max_ns)) best = i;
        if (best < 0) break;
        size_t used = strlen(out);
        snprintf(out + used, cap - used, "%s%d:%s:%.2f", used ? "," : "", guests[best].tid, guests[best].name,
                 guests[best].hold_max_ns / 1e6);
        guests[best].hold_max_ns = 0;
    }
    if (!out[0]) snprintf(out, cap, "-");
}

static void window_close(void)
{
    if (!win.frames) return;
    qsort(win.walls, (size_t)(win.frames < WIN_MAX ? win.frames : WIN_MAX), sizeof *win.walls, cmp_float);
    int nw = win.frames < WIN_MAX ? win.frames : WIN_MAX;
    double seconds = (double)(win.end - win.start) / 1e9;
    char avg[160], avg_long[160], causes[200], freq[900], cores[200], on[96], hold[200], gpu[48];
    int n = 0;
    for (int i = 0; i < C_COUNT; ++i) n += snprintf(avg + n, sizeof avg - (size_t)n, "%s%.2f", i ? ":" : "", win.sum[i] / win.frames);
    n = 0;
    for (int i = 0; i < C_COUNT; ++i)
        n += snprintf(avg_long + n, sizeof avg_long - (size_t)n, "%s%.2f", i ? ":" : "", win.nlong ? win.sum_long[i] / win.nlong : 0.0);
    n = 0;
    for (int i = 0; i < C_COUNT; ++i) n += snprintf(causes + n, sizeof causes - (size_t)n, "%scause_%s=%d", i ? " " : "", cause_names[i], win.cause[i]);
    n = 0;
    long gpu_min = -1, gpu_sum = 0, gpu_n = 0, load_sum = 0, load_n = 0;
    for (int p = 0; p < policy_count; ++p) {
        long low = -1, high = -1, sum = 0, count = 0;
        uint32_t total = sample_count < SAMPLE_RING ? sample_count : SAMPLE_RING;
        for (uint32_t i = 0; i < total; ++i) {
            const sample_t *s = &samples[(sample_count - 1u - i) % SAMPLE_RING];
            if (s->t < win.start || s->t > win.end) continue;
            if (p == 0) {
                if (s->gpu_mhz >= 0) { if (gpu_min < 0 || s->gpu_mhz < gpu_min) gpu_min = s->gpu_mhz; gpu_sum += s->gpu_mhz; ++gpu_n; }
                if (s->gpu_load >= 0) { load_sum += s->gpu_load; ++load_n; }
            }
            if (s->khz[p] < 0) continue;
            if (low < 0 || s->khz[p] < low) low = s->khz[p];
            if (s->khz[p] > high) high = s->khz[p];
            sum += s->khz[p];
            ++count;
        }
        long max_low = policies[p].window_max_low > 0 ? policies[p].window_max_low : policies[p].max_khz;
        n += snprintf(freq + n, sizeof freq - (size_t)n, " p%d_cur=%ld/%ld/%ld p%d_min=%ld p%d_max=%ld/%ld",
                      policies[p].first_cpu, low / 1000, count ? sum / count / 1000 : -1, high / 1000,
                      policies[p].first_cpu, policies[p].min_khz / 1000,
                      policies[p].first_cpu, policies[p].max_khz / 1000, max_low / 1000);
        policies[p].window_max_low = policies[p].max_khz;
    }
    if (gpu_n) snprintf(gpu, sizeof gpu, "%ld/%ld", gpu_min, gpu_sum / gpu_n);
    else snprintf(gpu, sizeof gpu, "%s", gpu_freq_fd < 0 ? "!unreadable" : "-");
    n = 0;
    double total_ms = 0;
    for (int c = 0; c < 64; ++c) total_ms += win.core_ms[c];
    for (int c = 0; c < 64 && n < (int)sizeof cores - 16; ++c)
        if (win.core_ms[c] > 0) n += snprintf(cores + n, sizeof cores - (size_t)n, "%s%d:%.1f", n ? "," : "", c, 100.0 * win.core_ms[c] / total_ms);
    if (!n) snprintf(cores, sizeof cores, "-");
    if (win.non > 1) {
        qsort(win.onscreen, (size_t)win.non, sizeof *win.onscreen, cmp_float);
        snprintf(on, sizeof on, "on_p50=%.2f on_p95=%.2f on_p99=%.2f on_max=%.2f", percentile(win.onscreen, win.non, .5),
                 percentile(win.onscreen, win.non, .95), percentile(win.onscreen, win.non, .99), win.onscreen[win.non - 1]);
    } else {
        snprintf(on, sizeof on, "on_p50=- on_p95=- on_p99=- on_max=-");
    }
    hold_text(hold, sizeof hold);
    static const char *const adpf_names[] = { "off", "on", "unavailable", "error", "idle" };
    int as = atomic_load(&adpf_state);
    diag_line("win", "frames=%d fps=%.1f p50=%.2f p95=%.2f p99=%.2f max=%.2f over15=%d over2=%d over50=%d %s "
              "avg=%s avg_long=%s %s long_logged=%d lc_frames=%d%s gpu_freq=%s gpu_load=%ld headroom=%.2f headroom10=%.2f "
              "thermal=%d batt_temp=%.1f plugged=%d power_save=%d vsync=%.2f/%.2f display_hz=%.1f cap=%.1f eff_cap=%.1f mismatch=%d "
              "cores=%s vcsw=%llu ivcsw=%llu psi=%s zmax=%.1f hold_max=%s adpf=%s adpf_target=%.2f adpf_reports=%u adpf_errors=%u "
              "diag_us=%.1f/%.1f runq_mode=%s dropped=%u",
              win.frames, seconds > 0 ? win.frames / seconds : 0.0, percentile(win.walls, nw, .5), percentile(win.walls, nw, .95),
              percentile(win.walls, nw, .99), win.walls[nw - 1], win.over15, win.over2, win.over50, on, avg, avg_long, causes,
              win.long_logged, win.lc_frames, freq, gpu, load_n ? load_sum / load_n : -1L, headroom_now, headroom_10,
              atomic_load(&st_thermal), fbits(atomic_load(&st_batt_temp)), atomic_load(&st_plugged), atomic_load(&st_power_save),
              fbits(atomic_load(&st_vsync50)), fbits(atomic_load(&st_vsync95)), void_port_display_rate(), win.cap, win.eff_cap,
              (int)mismatch_now(win.cap), cores, (unsigned long long)win.vcsw, (unsigned long long)win.ivcsw,
              psi_text[0] ? psi_text : "!unreadable", zone_max, hold, adpf_names[as >= 0 && as <= 4 ? as : 0],
              atomic_load(&adpf_target) / 1e6, atomic_load(&adpf_reports), atomic_load(&adpf_errors),
              win.diag_sum / 1e3 / win.frames, win.diag_max / 1e3, win.runq_sparse ? "sparse" : "frame",
              atomic_exchange(&frames_dropped, 0));
}

static void long_line(const frame_rec *r, const double c[C_COUNT], int cause, int64_t gpu_ns, double onscreen, int lc)
{
    int p = r->cpu_id >= 0 && r->cpu_id < 64 ? cpu_policy[r->cpu_id] : -1;
    long fmin = -1, favg = -1;
    freq_over(p, r->t_end - r->wall, r->t_end, &fmin, &favg);
    const sample_t *last = sample_count ? &samples[(sample_count - 1u) % SAMPLE_RING] : NULL;
    char holder[24] = "-", gpu[24] = "-", on[24] = "-", runq[24] = "-";
    void_guest_info guests[48];
    if (r->holder > 0) {
        int n = void_guest_threads(guests, 48, 0);
        snprintf(holder, sizeof holder, "%d", r->holder);
        for (int i = 0; i < n; ++i) if (guests[i].tid == r->holder) snprintf(holder, sizeof holder, "%s", guests[i].name);
    }
    if (gpu_ns >= 0) snprintf(gpu, sizeof gpu, "%.2f", gpu_ns / 1e6);
    if (onscreen >= 0) snprintf(on, sizeof on, "%.2f", onscreen);
    if (r->runq_valid) snprintf(runq, sizeof runq, "%.2f", r->runq / 1e6);
    diag_line_at(r->t_end, "long", "frame=%u wall=%.2f cpu=%.2f runq=%s lock=%.2f lock_max=%.2f holder=%d holder_comm=%s pace=%.2f swap=%.2f "
              "frame_wait=%.2f sync=%.2f ring_wait=%.2f render_busy=%.2f io=%.2f gpu=%s other=%.2f cause=%s cpu_id=%d migrated=%d "
              "freq_min=%ld freq_avg=%ld freq_max_policy=%ld gpu_freq=%ld gpu_load=%ld headroom=%.2f cap=%.1f eff_cap=%.1f "
              "vsync=%.2f onscreen=%s io_bytes=%llu majflt=%u lc=%d",
              r->frame, r->wall / 1e6, r->cpu / 1e6, runq, r->lock / 1e6, r->lock_max / 1e6, r->holder, holder, r->pace / 1e6,
              r->swap / 1e6, r->frame_wait / 1e6, r->sync / 1e6, r->ring_wait / 1e6, r->render_busy / 1e6, r->io / 1e6, gpu,
              c[C_OTHER], cause_names[cause], r->cpu_id, r->migrated, fmin, favg, p >= 0 ? policies[p].max_khz / 1000 : -1,
              last ? last->gpu_mhz : -1, last ? last->gpu_load : -1, headroom_now, r->cap, r->eff_cap,
              fbits(atomic_load(&st_vsync50)), on, (unsigned long long)r->io_bytes, r->majflt, lc);
}

static void process_frame(const frame_rec *r)
{
    if (!win.start) window_reset(r->t_end - r->wall);
    if (r->t_end >= win.start + 5000000000ull) {
        window_close();
        window_reset(r->t_end - r->wall);
    }
    if (!session.start) session.start = r->t_end - r->wall;
    session.last_end_ns = r->t_end;
    win.end = r->t_end;
    win.cap = r->cap;
    win.eff_cap = r->eff_cap;
    double c[C_COUNT];
    c[C_CPU] = r->cpu / 1e6; c[C_RUNQ] = r->runq_valid ? r->runq / 1e6 : 0; c[C_LOCK] = r->lock / 1e6;
    c[C_PACE] = r->pace / 1e6; c[C_SWAP] = r->swap / 1e6; c[C_IO] = r->io / 1e6; c[C_GPU] = 0;
    double wall = r->wall / 1e6;
    double known = c[C_CPU] + c[C_RUNQ] + c[C_LOCK] + c[C_PACE] + c[C_SWAP] + c[C_IO];
    c[C_OTHER] = wall > known ? wall - known : 0;
    int64_t gpu_ns = -1, present_ns = -1;
    double onscreen = -1;
    if (gpu_lookup(r->frame, &gpu_ns, &present_ns)) {
        if (gpu_ns >= 0) c[C_GPU] = gpu_ns / 1e6;
        if (present_ns > 0 && last_present_ns > 0 && r->frame == last_present_frame + 1u && present_ns > last_present_ns) {
            onscreen = (present_ns - last_present_ns) / 1e6;
            if (win.non < WIN_MAX) win.onscreen[win.non++] = (float)onscreen;
        }
        if (present_ns > 0) { last_present_ns = present_ns; last_present_frame = r->frame; }
    } else {
        gpu_ns = -1;
    }
    if (win.frames < WIN_MAX) win.walls[win.frames] = (float)wall;
    ++win.frames;
    ++session.frames;
    for (int i = 0; i < C_COUNT; ++i) win.sum[i] += c[i];
    float fps = r->eff_cap > 0 ? r->eff_cap : r->cap > 0 ? r->cap : 60.0f;
    double period = 1000.0 / fps;
    if (wall > 1.5 * period) ++win.over15;
    if (wall > 2.0 * period) ++win.over2;
    if (wall > 50.0) ++win.over50;
    if (r->cpu_id >= 0 && r->cpu_id < 64) win.core_ms[r->cpu_id] += wall;
    win.vcsw += r->vcsw; win.ivcsw += r->ivcsw;
    win.diag_sum += r->diag_ns;
    if (r->diag_ns > win.diag_max) win.diag_max = r->diag_ns;
    if (!r->runq_valid) win.runq_sparse = 1;
    int lc = near_lifecycle(r->t_end - r->wall, r->t_end);
    if (lc) ++win.lc_frames;
    if (wall > 2.0 * period || wall > 50.0) {
        int cause = classify(c, wall);
        ++win.long_total;
        ++session.long_total;
        atomic_fetch_add(&long_frames_total, 1);
        if (!lc) { ++win.cause[cause]; ++session.cause[cause]; }
        ++win.nlong;
        for (int i = 0; i < C_COUNT; ++i) win.sum_long[i] += c[i];
        if (win.long_logged < 20) { ++win.long_logged; long_line(r, c, cause, gpu_ns, onscreen, lc); }
    }
}

/* ---------------------------------------------------------- start lines */
static void prop(const char *name, char *out)
{
    out[0] = 0;
    __system_property_get(name, out);
}

static void env_props_line(void)
{
    static const char *const keys[][2] = {
        {"mi_os_name", "ro.mi.os.version.name"}, {"mi_os_code", "ro.mi.os.version.code"},
        {"incremental", "ro.build.version.incremental"}, {"fingerprint", "ro.build.fingerprint"},
        {"egl", "ro.hardware.egl"}, {"sf_game_default_override", "ro.surface_flinger.game_default_frame_rate_override"},
        {"sf_frame_rate_override", "ro.surface_flinger.enable_frame_rate_override"},
        {"game_default_disabled", "debug.graphics.game_default_frame_rate.disabled"},
        {"fps_switch_thermal", "ro.vendor.fps.switch.thermal"}, {"fps_switch_default", "ro.vendor.fps.switch.default"},
        {"idle_fps", "ro.vendor.idle_fps"}, {"tp_idle_fps", "ro.vendor.display.tp_idle_fps"},
        {"sf_touch_timer_ms", "ro.surface_flinger.set_touch_timer_ms"}, {"sf_idle_timer_ms", "debug.sf.set_idle_timer_ms"},
        {"disable_idle_fps_threshold", "ro.vendor.disable_idle_fps.threshold"},
    };
    char line[1700] = "part=props";
    size_t n = strlen(line);
    for (size_t i = 0; i < sizeof keys / sizeof *keys; ++i) {
        char value[PROP_VALUE_MAX], enc[300];
        prop(keys[i][1], value);
        n += (size_t)snprintf(line + n, sizeof line - n, " %s=%s", keys[i][0], word(value, enc, sizeof enc));
    }
    diag_line("env", "%s", line);
}

static void env_libs_line(void)
{
    static const char *const names[] = { "libGLES_meow", "libmigl", "libmigui", "libmivk", "libboost", "libperfctl",
                                         "libGLES_mali", "vulkan.", "libged" };
    int found[9] = {0};
    FILE *maps = fopen("/proc/self/maps", "re");
    if (!maps) { diag_line("env", "part=libs libs=!errno%d", errno); return; }
    char row[512];
    while (fgets(row, sizeof row, maps)) {
        const char *slash = strrchr(row, '/');
        if (!slash) continue;
        for (int i = 0; i < 9; ++i) if (strstr(slash, names[i])) found[i] = 1;
    }
    fclose(maps);
    char list[200] = "";
    for (int i = 0, n = 0; i < 9; ++i)
        if (found[i]) n += snprintf(list + n, sizeof list - (size_t)n, "%s%s", n ? "," : "", names[i]);
    diag_line("env", "part=libs libs=%s", list);
}

static void env_egl_line(void)
{
    char a[300], b[300], c[300], d[300];
    diag_line("env", "part=egl egl_vendor=%s egl_version=%s gl_renderer=%s gl_version=%s frame_timestamps=%d "
              "presentation_time=%d fence_sync=%d swap_interval=%d window=%dx%d render=%dx%d",
              word(egl_info.egl_vendor, a, sizeof a), word(egl_info.egl_version, b, sizeof b),
              word(egl_info.gl_renderer, c, sizeof c), word(egl_info.gl_version, d, sizeof d),
              egl_info.frame_timestamps, egl_info.presentation_time, egl_info.fence_sync, egl_info.swap_ok,
              egl_info.ww, egl_info.wh, egl_info.rw, egl_info.rh);
}

static unsigned long long mask_of(int tid, int *rc, int *err)
{
    cpu_set_t set;
    CPU_ZERO(&set);
    *rc = sched_getaffinity(tid, sizeof set, &set);
    *err = *rc ? errno : 0;
    unsigned long long mask = 0;
    for (int i = 0; i < 64 && i < CPU_SETSIZE; ++i) if (CPU_ISSET(i, &set)) mask |= 1ull << i;
    return mask;
}

static void cpu_lines(void)
{
    for (int cpu = 0; cpu < cpu_count; ++cpu)
        diag_line("cpu", "part=core cpu=%d cap=%ld min=%ld max=%ld policy=%d", cpu, cpu_capacity_value[cpu],
                  cpu_file(cpu, "cpufreq/cpuinfo_min_freq") / 1000, cpu_file(cpu, "cpufreq/cpuinfo_max_freq") / 1000,
                  cpu_policy[cpu] >= 0 ? policies[cpu_policy[cpu]].first_cpu : -1);
    for (int p = 0; p < policy_count; ++p) {
        char path[128], governor[64], enc[128];
        snprintf(path, sizeof path, "/sys/devices/system/cpu/cpufreq/policy%d/scaling_governor", policies[p].first_cpu);
        file_value(path, governor, sizeof governor);
        diag_line("cpu", "part=policy policy=%d related=%s governor=%s min=%ld max=%ld cur=%ld", policies[p].first_cpu,
                  word(policies[p].related, enc, sizeof enc), governor, read_long_fd(policies[p].fd_min) / 1000,
                  read_long_fd(policies[p].fd_max) / 1000, read_long_fd(policies[p].fd_cur) / 1000);
    }
    char online[64], isolated[64];
    file_value("/sys/devices/system/cpu/online", online, sizeof online);
    file_value("/sys/devices/system/cpu/isolated", isolated, sizeof isolated);
    const char *policy = "big";
    unsigned long long big = void_big_cores_mask(&policy);
    int game_tid = atomic_load(&game_tid_seen), grc = 0, gerr = 0;
    unsigned long long game_mask = game_tid ? mask_of(game_tid, &grc, &gerr) : 0;
    void_guest_info guests[48];
    int n = void_guest_threads(guests, 48, 0), set_rc = 0, set_err = 0;
    for (int i = 0; i < n; ++i) if (guests[i].tid == game_tid) { set_rc = guests[i].rc; set_err = guests[i].err; }
    int rrc = 0, rerr = 0, early = 0, rtid = 0, mrc = 0, merr = 0;
    const char *rpolicy = "-";
    d3d_rt_affinity(&rrc, &rerr, &rpolicy, &early, &rtid);
    unsigned long long render_mask = rtid > 0 ? mask_of(rtid, &mrc, &merr) : 0;
    diag_line("cpu", "part=mask online=%s isolated=%s cores=%s big_cores=%llx game_tid=%d game_rc=%d game_errno=%d game_mask=%llx "
              "render_tid=%d render_rc=%d render_errno=%d render_mask=%llx render_policy=%s render_when=%s",
              online, isolated, policy, big, game_tid, set_rc, set_err, game_mask, rtid, rrc, rerr, render_mask, rpolicy,
              early ? "early" : "late");
}

static void threads_lines(const char *when)
{
    DIR *dir = opendir("/proc/self/task");
    if (!dir) { diag_line("threads", "when=%s tasks=!errno%d", when, errno); return; }
    struct dirent *entry;
    while ((entry = readdir(dir))) {
        int tid = atoi(entry->d_name);
        if (tid <= 0) continue;
        char path[96], comm[64], status[2048], stat[1024], enc[128], cpus[128] = "?";
        snprintf(path, sizeof path, "/proc/self/task/%d/comm", tid);
        read_text(path, comm, sizeof comm);
        snprintf(path, sizeof path, "/proc/self/task/%d/status", tid);
        if (read_text(path, status, sizeof status) > 0) {
            const char *at = strstr(status, "Cpus_allowed_list:");
            if (at) { sscanf(at + 18, " %127s", cpus); }
        }
        long nice = 0;
        snprintf(path, sizeof path, "/proc/self/task/%d/stat", tid);
        if (read_text(path, stat, sizeof stat) > 0) {
            const char *close_paren = strrchr(stat, ')');
            if (close_paren) {
                /* Fields after ")": state(3) ... priority(18) nice(19). */
                const char *s = close_paren + 2;
                for (int field = 3; field < 19 && s; ++field) { s = strchr(s, ' '); if (s) ++s; }
                if (s) nice = strtol(s, NULL, 10);
            }
        }
        int policy = sched_getscheduler(tid);
        /* uclamp from /proc (CONFIG_SCHED_DEBUG kernels with uclamp): sched_getattr may be outside
         * the app seccomp filter, and a filtered call kills the process. */
        char uclamp[64] = "uclamp_min=!absent uclamp_max=!absent", sched[4096];
        snprintf(path, sizeof path, "/proc/self/task/%d/sched", tid);
        int got = read_text(path, sched, sizeof sched);
        if (got < 0) {
            snprintf(uclamp, sizeof uclamp, "uclamp_min=!errno%d uclamp_max=!errno%d", -got, -got);
        } else {
            const char *min = strstr(sched, "\nuclamp.min"), *max = strstr(sched, "\nuclamp.max");
            const char *min_value = min ? strchr(min, ':') : NULL, *max_value = max ? strchr(max, ':') : NULL;
            if (min_value && max_value)
                snprintf(uclamp, sizeof uclamp, "uclamp_min=%ld uclamp_max=%ld", strtol(min_value + 1, NULL, 10),
                         strtol(max_value + 1, NULL, 10));
        }
        diag_line("threads", "when=%s tid=%d comm=%s cpus=%s nice=%ld policy=%d %s", when, tid, word(comm, enc, sizeof enc), cpus,
                  nice, policy, uclamp);
    }
    closedir(dir);
    char cgroup[1024];
    int r = read_text("/proc/self/cgroup", cgroup, sizeof cgroup);
    for (char *s = cgroup; *s; ++s) if (*s == '\n') *s = ',';
    char enc[1500];
    if (r < 0) diag_line("threads", "when=%s part=cgroup cgroup=!errno%d", when, -r);
    else diag_line("threads", "when=%s part=cgroup cgroup=%s", when, word(cgroup, enc, sizeof enc));
}

static void probe_lines(void)
{
    char sconfig[96], temp_state[96], board[96], psi[3][32], sched_value[32], scratch[256];
    file_value("/sys/class/thermal/thermal_message/sconfig", sconfig, sizeof sconfig);
    file_value("/sys/class/thermal/thermal_message/temp_state", temp_state, sizeof temp_state);
    file_value("/sys/class/thermal/thermal_message/board_sensor_temp", board, sizeof board);
    static const char *const psi_paths[3] = { "/proc/pressure/cpu", "/proc/pressure/io", "/proc/pressure/memory" };
    for (int i = 0; i < 3; ++i) {
        int r = read_text(psi_paths[i], scratch, sizeof scratch);
        if (r < 0) snprintf(psi[i], sizeof psi[i], "!errno%d", -r);
        else snprintf(psi[i], sizeof psi[i], "1");
    }
    int r = read_text("/proc/thread-self/schedstat", scratch, sizeof scratch);
    if (r < 0) snprintf(sched_value, sizeof sched_value, "!errno%d", -r); else snprintf(sched_value, sizeof sched_value, "1");
    uint64_t cost = game.runq_reads ? game.runq_cost_ns / (uint64_t)game.runq_reads : 0;
    void *lib = libandroid();
    int has_adpf = lib && dlsym(lib, "APerformanceHint_getManager");
    int has_thermal = lib && dlsym(lib, "AThermal_getThermalHeadroom");
    char gfreq[160], gload[160];
    if (gpu_freq_fd >= 0) snprintf(gfreq, sizeof gfreq, "%s", gpu_freq_path);
    else { int fd = open("/sys/kernel/ged/hal/current_freqency", O_RDONLY | O_CLOEXEC); snprintf(gfreq, sizeof gfreq, "!errno%d", fd < 0 ? errno : 0); if (fd >= 0) close(fd); }
    if (gpu_load_fd >= 0) snprintf(gload, sizeof gload, "%s", gpu_load_path);
    else { int fd = open("/sys/kernel/ged/hal/gpu_utilization", O_RDONLY | O_CLOEXEC); snprintf(gload, sizeof gload, "!errno%d", fd < 0 ? errno : 0); if (fd >= 0) close(fd); }
    diag_line("probe", "part=nodes sconfig=%s temp_state=%s board_sensor_temp=%s psi_cpu=%s psi_io=%s psi_memory=%s schedstat=%s "
              "schedstat_us=%.1f adpf=%d adpf_rate_ns=%lld thermal_api=%d ged_freq=%s ged_load=%s",
              sconfig, temp_state, board, psi[0], psi[1], psi[2], sched_value, cost / 1e3, has_adpf,
              (long long)adpf.rate_ns, has_thermal, gfreq, gload);
    char zones[1600] = "";
    int n = 0;
    for (int i = 0; i < 40 && n < (int)sizeof zones - 80; ++i) {
        char path[96], type[64], temp[32], enc[96];
        snprintf(path, sizeof path, "/sys/class/thermal/thermal_zone%d/temp", i);
        if (read_text(path, temp, sizeof temp) <= 0) continue;
        snprintf(path, sizeof path, "/sys/class/thermal/thermal_zone%d/type", i);
        read_text(path, type, sizeof type);
        n += snprintf(zones + n, sizeof zones - (size_t)n, "%s%d:%s:%.1f", n ? "," : "", i, word(type, enc, sizeof enc),
                      strtol(temp, NULL, 10) / 1000.0);
    }
    diag_line("probe", "part=zones zones=%s", n ? zones : "-");
}

static void start_line(void)
{
    char local[40] = "?";
    time_t now_wall = time(NULL);
    struct tm tm_local;
    if (localtime_r(&now_wall, &tm_local)) strftime(local, sizeof local, "%Y-%m-%dT%H:%M:%S%z", &tm_local);
    struct timespec boot, mono;
    clock_gettime(CLOCK_BOOTTIME, &boot);
    clock_gettime(CLOCK_MONOTONIC, &mono);
    double offset = (double)(boot.tv_sec - mono.tv_sec) * 1e3 + (double)(boot.tv_nsec - mono.tv_nsec) / 1e6;
    const char *policy = "big";
    unsigned long long big = void_big_cores_mask(&policy);
    float ui = 1, render = 1;
    void_port_scales(&ui, &render);
    char flags[256] = "";
    int n = 0;
    static const struct { unsigned bit; const char *name; } bits[] = {
        {PERF_OPT_DIAG, "perf-diag"}, {PERF_OPT_INJECT, "diag-inject"}, {PERF_OPT_NO_REFRESH_FOLLOW, "no-refresh-follow"},
        {PERF_OPT_ADPF, "adpf"}, {PERF_OPT_NO_ADPF, "no-adpf"}, {PERF_OPT_PACE_TIMER, "pace-timer"},
        {PERF_OPT_PACE_VSYNC, "pace-vsync"}, {PERF_OPT_VERBOSE, "verbose"} };
    for (size_t i = 0; i < sizeof bits / sizeof *bits; ++i)
        if (perf_options & bits[i].bit) n += snprintf(flags + n, sizeof flags - (size_t)n, "%s%s", n ? "," : "", bits[i].name);
    static const char *const env[] = { "VOID_BIG_CORES", "VOID_RT_CORES", "VOID_RT_EARLY", "VOID_RENDER_THREAD" };
    for (size_t i = 0; i < sizeof env / sizeof *env; ++i) {
        const char *value = getenv(env[i]);
        if (value && *value) n += snprintf(flags + n, sizeof flags - (size_t)n, "%s%s=%s", n ? "," : "", env[i], value);
    }
    diag_line("start", "reason=%s %s build=%s edition=%s rt=%d flags=%s cores=%s big_cores=%llx fps_choice=%.1f eff_cap=%.1f "
              "display_hz=%.1f render_scale=%.2f ui_scale=%.2f res=%dx%d window=%dx%d adpf_wanted=%d boot_offset_ms=%.3f "
              "local=%s cap_bytes=%u",
              hyperos_any ? "hyperos" : "perf-diag", java_info, void_build_id(), DIAG_EDITION, atomic_load(&last_threaded), n ? flags : "-",
              policy, big, fbits(atomic_load(&frame_cap_bits)), fbits(atomic_load(&frame_eff_bits)), void_port_display_rate(),
              render, ui, egl_info.rw, egl_info.rh, egl_info.ww, egl_info.wh, adpf.wanted, offset, local, DIAG_CAP_BYTES);
}

static void end_line(const char *why)
{
    char hist[400] = "";
    int n = 0;
    for (int i = 0; i < session.levels && n < (int)sizeof hist - 24; ++i)
        n += snprintf(hist + n, sizeof hist - (size_t)n, "%s%ld:%.0f", n ? "," : "", session.maxfreq_level[i], session.maxfreq_s[i]);
    char causes[200];
    int m = 0;
    for (int i = 0; i < C_COUNT; ++i)
        m += snprintf(causes + m, sizeof causes - (size_t)m, "%scause_%s=%llu", i ? " " : "", cause_names[i],
                      (unsigned long long)session.cause[i]);
    diag_line("end", "why=%s dur_s=%.1f frames=%llu long_total=%llu %s maxfreq_s=%s mismatch_s=%.0f mismatch_pct=%.1f", why,
              session.start ? (session.last_end_ns - session.start) / 1e9 : 0.0, (unsigned long long)session.frames,
              (unsigned long long)session.long_total, causes, n ? hist : "-", session.mismatch_s,
              session.seconds > 0 ? 100.0 * session.mismatch_s / session.seconds : 0.0);
}

/* ------------------------------------------------------------- 1 Hz work */
static unsigned long long guest_masks_tid[48], guest_masks[48];
static int guest_mask_count;

static void one_hz(uint64_t now, unsigned second)
{
    for (int p = 0; p < policy_count; ++p) {
        policies[p].min_khz = read_long_fd(policies[p].fd_min);
        policies[p].max_khz = read_long_fd(policies[p].fd_max);
        if (policies[p].max_khz > 0 && (policies[p].window_max_low <= 0 || policies[p].max_khz < policies[p].window_max_low))
            policies[p].window_max_low = policies[p].max_khz;
    }
    int foreground = session.last_end_ns && now < session.last_end_ns + 2000000000ull + 1100000000ull;
    if (foreground && big_policy >= 0) {
        long level = policies[big_policy].max_khz / 1000;
        int i = 0;
        while (i < session.levels && session.maxfreq_level[i] != level) ++i;
        if (i == session.levels && i < 24) { session.maxfreq_level[i] = level; session.maxfreq_s[i] = 0; ++session.levels; }
        if (i < 24) session.maxfreq_s[i] += 1.0;
        session.seconds += 1.0;
        if (mismatch_now(fbits(atomic_load(&frame_cap_bits)))) session.mismatch_s += 1.0;
    }
    if (online_fd >= 0) {
        char text[64];
        ssize_t got = pread(online_fd, text, sizeof text - 1, 0);
        if (got > 0) {
            text[got] = 0;
            while (got > 0 && text[got - 1] == '\n') text[--got] = 0;
            if (online_last[0] && strcmp(text, online_last)) diag_line("event", "kind=cpu_online from=%s to=%s", online_last, text);
            snprintf(online_last, sizeof online_last, "%s", text);
        }
    }
    char text[256];
    psi_text[0] = 0;
    const char *names[3] = { "/proc/pressure/cpu", "/proc/pressure/io", "/proc/pressure/memory" };
    for (int i = 0; i < 3; ++i) {
        if (read_text(names[i], text, sizeof text) <= 0) { psi_text[0] = 0; break; }
        const char *avg = strstr(text, "avg10=");
        size_t used = strlen(psi_text);
        snprintf(psi_text + used, sizeof psi_text - used, "%s%.2f", i ? "/" : "", avg ? strtod(avg + 6, NULL) : -1.0);
    }
    float zmax = NAN;
    for (int i = 0; i < 40; ++i) {
        char path[96], temp[32];
        snprintf(path, sizeof path, "/sys/class/thermal/thermal_zone%d/temp", i);
        if (read_text(path, temp, sizeof temp) <= 0) continue;
        float value = strtol(temp, NULL, 10) / 1000.0f;
        if (value > -50 && value < 150 && (isnan(zmax) || value > zmax)) zmax = value;
    }
    zone_max = zmax;
    void_guest_info guests[48];
    int n = void_guest_threads(guests, 48, 0);
    for (int i = 0; i < n; ++i) {
        int rc, err;
        unsigned long long mask = mask_of(guests[i].tid, &rc, &err);
        if (rc) continue;
        int k = 0;
        while (k < guest_mask_count && guest_masks_tid[k] != (unsigned long long)guests[i].tid) ++k;
        if (k < guest_mask_count && guest_masks[k] != mask)
            diag_line("event", "kind=affinity tid=%d comm=%s old=%llx new=%llx", guests[i].tid, guests[i].name, guest_masks[k], mask);
        if (k == guest_mask_count && k < 48) { guest_masks_tid[k] = (unsigned long long)guests[i].tid; ++guest_mask_count; }
        if (k < 48) guest_masks[k] = mask;
    }
    if (thermal_manager && thermal_headroom) {
        if (second & 1u) headroom_10 = thermal_headroom(thermal_manager, 10);
        else headroom_now = thermal_headroom(thermal_manager, 0);
    }
    if (thermal_manager && thermal_status_get && atomic_load(&st_thermal) < 0)
        atomic_store(&st_thermal, thermal_status_get(thermal_manager));
}

static void *sampler_main(void *unused)
{
    (void)unused;
    prctl(PR_SET_NAME, "h5-perf-diag", 0, 0, 0);
    setpriority(PRIO_PROCESS, 0, 10);
    cpu_set_t all;
    CPU_ZERO(&all);
    long configured = sysconf(_SC_NPROCESSORS_CONF);
    for (long i = 0; i < configured && i < CPU_SETSIZE; ++i) CPU_SET((int)i, &all);
    sched_setaffinity(0, sizeof all, &all);
    policies_init();
    gpu_nodes_init();
    online_fd = open("/sys/devices/system/cpu/online", O_RDONLY | O_CLOEXEC);
    void *lib = libandroid();
    if (lib) {
        thermal_acquire_fn acquire = (thermal_acquire_fn)dlsym(lib, "AThermal_acquireManager");
        thermal_headroom = (thermal_headroom_fn)dlsym(lib, "AThermal_getThermalHeadroom");
        thermal_status_get = (thermal_status_fn)dlsym(lib, "AThermal_getCurrentThermalStatus");
        thermal_manager = acquire ? acquire() : NULL;
    }
    int started = 0, egl_done = 0, threads_egl = 0, threads_30 = 0;
    unsigned tick = 0, second = 0;
    uint64_t next = mono_ns(), next_end = 0, next_threads = 0;
    for (;;) {
        next += 100000000ull;
        struct timespec until = { (time_t)(next / 1000000000ull), (long)(next % 1000000000ull) };
        while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &until, NULL) == EINTR) {}
        uint64_t now = mono_ns();
        if (now > next + 1000000000ull) next = now;          /* suspended: no catch-up burst */
        sample_now(now);
        if (++tick % 10u == 0) one_hz(now, ++second);
        uint64_t first = atomic_load(&first_frame_ns), egl = atomic_load(&egl_ready_ns);
        if (!started && first && now > first + 500000000ull) {
            started = 1;
            start_line();
            env_props_line();
            cpu_lines();
            probe_lines();
            next_end = now + 600000000000ull;
            next_threads = now + 60000000000ull;
        }
        if (!egl_done && egl && started) { egl_done = 1; env_egl_line(); }
        if (!threads_egl && egl && started && now > egl + 1000000000ull) { threads_egl = 1; env_libs_line(); threads_lines("egl"); }
        if (!threads_30 && first && now > first + 30000000000ull) { threads_30 = 1; threads_lines("30s"); cpu_lines(); }
        if ((perf_options & PERF_OPT_VERBOSE) && started && now > next_threads) { next_threads = now + 60000000000ull; threads_lines("minute"); }
        uint32_t tail = atomic_load_explicit(&ring_tail, memory_order_relaxed);
        uint32_t head = atomic_load_explicit(&ring_head, memory_order_acquire);
        while (tail != head) {
            const frame_rec *r = &frame_ring[tail % FRAME_RING];
            if (r->t_end + 1100000000ull > now) break;      /* lifecycle ±1 s, GPU timestamps come later */
            frame_rec copy = *r;
            atomic_store_explicit(&ring_tail, ++tail, memory_order_release);
            process_frame(&copy);
        }
        if (atomic_exchange(&pause_end_request, 0) && started) { window_close(); window_reset(0); end_line("pause"); }
        if (started && next_end && now > next_end) { next_end = now + 600000000000ull; end_line("periodic"); }
    }
    return NULL;
}

/* android_main.c at process exit. */
void void_diag_exit(void);
void void_diag_exit(void)
{
    if (void_diag_on && session.start) end_line("exit");
}

/* --------------------------------------------------------------- configure */
/* Java configures before the engine opens homm5.log: the summary waits for the first frame. */
static char perf_summary[400];
void void_perf_log_summary(void)
{
    if (perf_summary[0]) void_log("%s", perf_summary);
}

static void configure(unsigned options, const char *info, float display_hz, const char *inject)
{
    static int configured;
    void_port_set_display_rate(display_hz);
    if (configured++) return;            /* a recreated activity: the engine and its threads stay */
    perf_options = options;
    snprintf(java_info, sizeof java_info, "%s", info ? info : "");
    snprintf(inject_file, sizeof inject_file, "%s", inject ? inject : "");
    char name[PROP_VALUE_MAX] = "", code_text[PROP_VALUE_MAX] = "";
    __system_property_get("ro.mi.os.version.name", name);
    __system_property_get("ro.mi.os.version.code", code_text);
    hyperos_native = atoi(code_text) >= 1 || !strncmp(name, "OS", 2);
    hyperos_any = hyperos_native || (options & PERF_OPT_HYPEROS);
    void_diag_on = (hyperos_any || (options & PERF_OPT_DIAG)) && !(options & PERF_OPT_NO_DIAG);
    adpf.wanted = !(options & PERF_OPT_NO_ADPF) && (hyperos_any || (options & PERF_OPT_ADPF));
    void_frame_monitor_on = void_diag_on || adpf.wanted;
    snprintf(perf_summary, sizeof perf_summary,
             "[perf] HyperOS %s (native %s/%s, Java %s); diagnostics %s; ADPF %s; refresh follow %s; pacer %s",
             hyperos_any ? "yes" : "no", name[0] ? name : "-", code_text[0] ? code_text : "-",
             (options & PERF_OPT_HYPEROS) ? "yes" : "no", void_diag_on ? "on" : "off", adpf.wanted ? "wanted" : "off",
             (options & PERF_OPT_NO_REFRESH_FOLLOW) ? "off" : "on",
             (options & PERF_OPT_PACE_TIMER) ? "timer" : (options & PERF_OPT_PACE_VSYNC) ? "vsync" : "auto");
    if (!void_diag_on) return;
    pthread_t thread;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_attr_setstacksize(&attr, 256u << 10);
    if (pthread_create(&thread, &attr, sampler_main, NULL)) void_log("[hyperos] sampler thread not started");
    if (options & PERF_OPT_INJECT) pthread_create(&thread, &attr, inject_main, NULL);
    pthread_attr_destroy(&attr);
}

#ifdef VOID_ANDROID_APP
/* PerfMonitor.java (every edition's engine). */
JNIEXPORT void JNICALL Java_org_homm5_port_PerfMonitor_nativeConfigure(JNIEnv *env, jclass type, jint options, jstring info,
    jfloat display_hz, jstring inject)
{
    (void)type;
    const char *text = info ? (*env)->GetStringUTFChars(env, info, NULL) : NULL;
    const char *file = inject ? (*env)->GetStringUTFChars(env, inject, NULL) : NULL;
    configure((unsigned)options, text, display_hz, file);
    if (text) (*env)->ReleaseStringUTFChars(env, info, text);
    if (file) (*env)->ReleaseStringUTFChars(env, inject, file);
}

JNIEXPORT jboolean JNICALL Java_org_homm5_port_PerfMonitor_nativeDiagOn(JNIEnv *env, jclass type)
{
    (void)env; (void)type;
    return void_diag_on ? JNI_TRUE : JNI_FALSE;
}

JNIEXPORT void JNICALL Java_org_homm5_port_PerfMonitor_nativeDisplayRate(JNIEnv *env, jclass type, jfloat hz)
{
    (void)env; (void)type;
    void_port_set_display_rate(hz);
}

enum { STATE_VSYNC50 = 1, STATE_VSYNC95, STATE_BATT_TEMP, STATE_PLUGGED, STATE_THERMAL, STATE_POWER_SAVE, STATE_LIFECYCLE,
       STATE_MISMATCH, STATE_PAUSE };

JNIEXPORT void JNICALL Java_org_homm5_port_PerfMonitor_nativeState(JNIEnv *env, jclass type, jint key, jfloat value)
{
    (void)env; (void)type;
    switch (key) {
    case STATE_VSYNC50: atomic_store(&st_vsync50, bitsf(value)); break;
    case STATE_VSYNC95: atomic_store(&st_vsync95, bitsf(value)); break;
    case STATE_BATT_TEMP: atomic_store(&st_batt_temp, bitsf(value)); break;
    case STATE_PLUGGED: atomic_store(&st_plugged, (int)value); break;
    case STATE_THERMAL: atomic_store(&st_thermal, (int)value); break;
    case STATE_POWER_SAVE: atomic_store(&st_power_save, (int)value); break;
    case STATE_MISMATCH: atomic_store(&st_mismatch_choreo, bitsf(value)); break;
    case STATE_PAUSE: atomic_store(&pause_end_request, 1); /* fall through: a lifecycle event too */
    case STATE_LIFECYCLE: {
        uint32_t at = atomic_fetch_add(&lifecycle_head, 1) % 16u;
        atomic_store(&lifecycle_ns[at], mono_ns());
        break;
    }
    default: break;
    }
}

JNIEXPORT void JNICALL Java_org_homm5_port_PerfMonitor_nativeLine(JNIEnv *env, jclass type, jstring line)
{
    (void)type;
    if (!void_diag_on || !line) return;
    const char *text = (*env)->GetStringUTFChars(env, line, NULL);
    if (!text) return;
    size_t length = strlen(text);
    uint64_t total = atomic_fetch_add(&diag_bytes, length + 1u) + length + 1u;
    if (total <= DIAG_CAP_BYTES) void_log("%s", text);
    else if (!atomic_exchange(&cap_reached, 1))
        void_log("[hyperos] event t=%.3f diag=1 kind=cap_reached bytes=%llu", (double)mono_ns() / 1e6, (unsigned long long)total);
    (*env)->ReleaseStringUTFChars(env, line, text);
}

JNIEXPORT jint JNICALL Java_org_homm5_port_PerfMonitor_nativeLongFrames(JNIEnv *env, jclass type)
{
    (void)env; (void)type;
    return (jint)atomic_load(&long_frames_total);
}
#endif
