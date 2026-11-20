/* Frame monitor (HyperOS / performance diagnostics, research/hyperos-diag.md), the display-rate
 * follower and the ADPF hint session (perf_diag.c), for all three editions. */
#ifndef PERF_DIAG_H
#define PERF_DIAG_H
#include <stdint.h>

/* Switches from Java (PerfMonitor.java: flag files in /sdcard/HeroesV and the HyperOS check). */
enum {
    PERF_OPT_DIAG = 1u << 0,             /* perf-diag */
    PERF_OPT_NO_DIAG = 1u << 1,          /* no-perf-diag */
    PERF_OPT_HYPEROS = 1u << 2,          /* Java saw HyperOS (Build.VERSION.INCREMENTAL, MANUFACTURER) */
    PERF_OPT_INJECT = 1u << 3,           /* diag-inject: classifier self-test */
    PERF_OPT_NO_REFRESH_FOLLOW = 1u << 4,
    PERF_OPT_ADPF = 1u << 5,             /* ADPF on any device (default: HyperOS only) */
    PERF_OPT_NO_ADPF = 1u << 6,
    PERF_OPT_PACE_TIMER = 1u << 7,       /* always the timer pacer */
    PERF_OPT_PACE_VSYNC = 1u << 8,       /* never the timer when the cap equals the refresh */
    PERF_OPT_VERBOSE = 1u << 9,
};

/* Nonzero while the diagnostics run (only then the hooks below record anything). */
extern int void_diag_on;
/* Nonzero when the frame monitor has work: diagnostics or the ADPF session. */
extern int void_frame_monitor_on;
/* The PERF_OPT_* bits of this start. */
unsigned void_perf_options(void);
/* The "[perf]" line of this start's switches, once the log is open. */
void void_perf_log_summary(void);

/* d3d9_gl.c / d3d9_dxvk.c, the game's thread at the end of each frame (after the limiter). */
typedef struct {
    uint32_t frame;
    int threaded;                /* GL commands run on the render thread */
    int surface_live;            /* a window surface to present into */
    uint64_t pace_ns;            /* this thread's total sleep in the frame limiter */
    uint64_t swap_ns;            /* total time in eglSwapBuffers (render thread or inline) */
    uint64_t frame_wait_ns, sync_ns, ring_wait_ns, render_busy_ns;   /* d3d_rt_stats totals */
    float cap, eff_cap;          /* the player's FPS choice and the effective cap (0: none) */
} void_frame_in;
void void_frame_monitor(const void_frame_in *in);
/* diag-inject: extra nanoseconds the limiter sleeps this frame (counted as pace). */
uint64_t void_diag_inject_pace(void);

/* Render thread (d3d9_gl.c): EGL/GL identity after the context exists, and frame timestamps. */
void void_diag_egl(const char *egl_vendor, const char *egl_version, const char *gl_renderer, const char *gl_version,
                   int frame_timestamps, int presentation_time, int fence_sync, int swap_interval_ok,
                   int window_w, int window_h, int render_w, int render_h);
void void_diag_gpu_frame(uint32_t frame, int64_t gpu_ns, int64_t present_ns);

/* port_settings.c: the display's actual refresh rate (Java) and the effective cap. */
void void_port_set_display_rate(float hz);
float void_port_display_rate(void);
float void_port_effective_fps(void);
/* Nonzero when the limiter's timer can be skipped: the cap equals the refresh (vsync paces). */
int void_port_vsync_paced(void);

/* threads.c */
typedef struct { int tid; char name[16]; uint64_t hold_max_ns; int rc, err; } void_guest_info;
int void_guest_threads(void_guest_info *out, int max, int reset_hold);
void void_lock_take_frame(uint64_t *wait_max_ns, int *holder_tid);
uint64_t void_lock_last_wait(uint64_t *end_ns);
uint64_t void_big_cores_mask(const char **policy);
/* perf.c: the calling thread's file I/O since its last call (machine-lock waits inside excluded). */
void void_perf_io_take(uint64_t *ns, uint64_t *bytes);
/* d3d9_thread.c: where the render thread went (rc/errno of sched_setaffinity, policy, early/late). */
void d3d_rt_affinity(int *rc, int *err, const char **policy, int *early, int *tid);
/* This library's build ID (perf_diag.c). */
const char *void_build_id(void);
#endif
