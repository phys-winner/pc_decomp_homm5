/* The render thread of the GLES path of Direct3D 9 (d3d9_thread.c): what the
 * D3D9 files share with it. Included after d3d9_internal.h; build_android.py
 * hashes included .inc files into the host objects that use them.
 *
 * Two threads. The game's thread (the one making D3D9 calls) owns the D3D9
 * state, the COM objects and guest memory; it records what the GL side has to
 * do as calls (a function and a copy of its arguments). The render thread owns
 * the EGL context and every GL object and runs those calls in order, at most a
 * frame behind. With the thread switched off (VOID_RENDER_THREAD=0 or
 * userdata/render-thread containing 0) the very same records run at once on
 * the game's thread. */
#ifndef VOID_D3D9_THREAD_INC
#define VOID_D3D9_THREAD_INC

#include <stdint.h>
#include <stddef.h>
#include <stdatomic.h>

typedef void (*d3d_rt_fn)(void *args);

void d3d_rt_start(void);
int d3d_rt_threaded(void);
/* GL may be called here: the render thread, or any thread with the thread off. */
int d3d_rt_on_render(void);
/* Inside a recorded call (either mode): bridge entry points then do the GL work
 * directly instead of recording it again. */
int d3d_rt_executing(void);
void *d3d_rt_begin(d3d_rt_fn fn, uint32_t size);   /* where to write `size` bytes of arguments */
void d3d_rt_commit(void);
void d3d_rt_commit_size(uint32_t used);            /* publish with fewer bytes than begun */
void d3d_rt_call(d3d_rt_fn fn, const void *args, uint32_t size);
void d3d_rt_sync(d3d_rt_fn fn, void *arg);         /* run fn(arg) there, after everything before it, and wait */
void d3d_rt_finish(void);                          /* everything recorded so far has run */
void d3d_rt_flush(void);                           /* hand over what is recorded now */
/* Record positions: what the game's thread recorded so far, whether the render
 * thread has run up to a position, and a wait for it. Without the thread every
 * position is reached. */
uint64_t d3d_rt_position(void);
int d3d_rt_reached(uint64_t position);
void d3d_rt_wait_for(uint64_t position);
/* Frames: a present about to be recorded, the game's wait after it (at most
 * `ahead` presents not yet run), the render thread's present done. */
void d3d_rt_frame_queued(void);
void d3d_rt_frame_wait(int ahead);
void d3d_rt_frame_done(void);
/* Around GL work that sleeps (compiler, window wait): on the game's thread it
 * lets other guest threads have the machine meanwhile; the render thread holds
 * none to let go. */
void d3d_rt_wait_begin(void);
void d3d_rt_wait_end(void);
/* The render thread calls poll(0) between batches of records and poll(1) when
 * it runs out of them; while that returns nonzero it naps briefly and asks
 * again with poll(2) (query results). */
void d3d_rt_set_idle(int (*poll)(int idle));
int d3d_rt_render_tid(void);
typedef struct {
    uint64_t records, bytes;              /* recorded by the game's thread */
    uint64_t syncs, sync_ns;              /* game waits for an answer (read-backs, d3d_rt_sync) */
    uint64_t frame_waits, frame_wait_ns;  /* game waits for the render thread to catch up a frame */
    uint64_t ring_waits, ring_wait_ns;    /* game waits for room in the ring, or for a position */
    uint64_t render_busy_ns;              /* render thread time running records */
} d3d_rt_stats_t;
void d3d_rt_stats(d3d_rt_stats_t *out);

/* ------------------------------------------------------------- the mirror
 * The render thread draws through a device of its own whose state follows the
 * game's (d3d_rt_device): before each recorded call that reads state, the
 * game's thread sends the 64-byte pieces of d3d_state touched since the last
 * one (d3d_rt_sync_state) and the render targets. Setters mark what they touch
 * with d3d_rt_dirty; a write elsewhere than the device's own state (a state
 * block being recorded) is ignored. */
#define D3D_RT_STATE_PIECES ((uint32_t)((sizeof(d3d_state) + 63u) / 64u))
#define D3D_RT_DIRTY_WORDS ((D3D_RT_STATE_PIECES + 31u) / 32u)
extern uint32_t d3d_rt_dirty_bits[D3D_RT_DIRTY_WORDS];

static inline void d3d_rt_dirty(d3d_device *d, const void *p, size_t n)
{
    uintptr_t off = (uintptr_t)p - (uintptr_t)&d->st;
    if (!n || off >= sizeof(d3d_state)) return;
    if (n > sizeof(d3d_state) - off) n = sizeof(d3d_state) - off;
    uint32_t first = (uint32_t)(off / 64u), last = (uint32_t)((off + n - 1u) / 64u);
    for (uint32_t word = first >> 5; word <= (last >> 5); ++word) {
        uint32_t lo = word == (first >> 5) ? first & 31u : 0;
        uint32_t hi = word == (last >> 5) ? last & 31u : 31;
        d3d_rt_dirty_bits[word] |= (UINT32_MAX << lo) & (UINT32_MAX >> (31u - hi));
    }
}
#define D3D_RT_DIRTY(d, lvalue) d3d_rt_dirty((d), &(lvalue), sizeof(lvalue))

d3d_device *d3d_rt_device(void);
void d3d_rt_sync_state(d3d_device *d);
/* The mirror starts over as the device does (CreateDevice, Reset): every piece
 * is sent again with the next sync. */
void d3d_rt_device_reset(d3d_device *d);

/* ---------------------------------------------- render-thread object views
 * Objects the two threads share keep, after the D3D9 structure, what only the
 * render thread reads (rt_*) or what only the game's thread keeps for it;
 * d3d9_resource.c allocates them this size. */
typedef struct {
    d3d_texture t;
    int has_gl;                           /* game: GL storage was asked for */
    const d3d_native_format *rt_native;   /* render: the blocks the GL storage holds */
    uint32_t rt_lod;                      /* render: SetLOD as applied */
} d3d_texture_rt;
typedef struct {
    d3d_surface s;
    int has_gl;                           /* game: a standalone GL texture was asked for */
} d3d_surface_rt;
typedef struct {
    d3d_buffer b;
    uint32_t rt_shadow;                   /* render: the guest copy its records read */
    int rt_locks;                         /* render: locks open as recorded */
    uint64_t read_at;                     /* game: record position after the last that reads the copy */
} d3d_buffer_rt;
typedef struct {
    d3d_query q;
    uint32_t serial;                      /* game: ends issued */
    int game_state;                       /* game: 0 never issued, 1 begun, 2 ended */
    _Atomic uint32_t answer;              /* render: serial << 2 | QUERY_* result, published */
    _Atomic int polling;                  /* game asked, the render thread has not looked yet */
    uint32_t rt_serial;                   /* render: serial of the end it ran last */
} d3d_query_rt;
#define TEX_RT(t) ((d3d_texture_rt *)(t))
#define SURF_RT(s) ((d3d_surface_rt *)(s))
#define BUF_RT(b) ((d3d_buffer_rt *)(b))
#define QRY_RT(q) ((d3d_query_rt *)(q))

/* d3d9_resource.c: the game's thread marks the buffers a recorded call reads. */
void d3d_buffer_read_by(d3d_buffer *b, uint64_t position);
/* d3d9_resource.c: query results the render thread still waits on (its idle poll). */
int d3d_query_watch(int idle);
/* d3d9_gl.c: the GL error state, read where the context lives. */
GLenum d3d_gl_error(void);
/* d3d9_gl.c: a clear with host rects (count x {x1, y1, x2, y2}). */
void d3d_gl_clear_rects(d3d_device *d, uint32_t count, const int32_t *rects, uint32_t flags, uint32_t color, float z,
    uint32_t stencil);

/* Private render targets of the full-resolution UI and spatial filters (GL only). */
d3d_surface *d3d_gl_scratch_new(d3d_device *dev, uint32_t w, uint32_t h, uint32_t format, uint32_t usage);
void d3d_gl_scratch_free(d3d_surface *s);
int d3d_gl_ui_filter(void);

/* ------------------------------------------------- debug: GL off the thread
 * Built with -DVOID_RT_CHECK (build_android.py --rt-check), every GL and EGL
 * call of the D3D9 files first checks that it runs where the context lives. */
#ifdef VOID_RT_CHECK
#include <EGL/egl.h>          /* declared before the wrappers below */
#include <EGL/eglext.h>
void d3d_rt_gl_check(const char *name);
#include "d3d9_thread_check.inc"
#endif

#endif
