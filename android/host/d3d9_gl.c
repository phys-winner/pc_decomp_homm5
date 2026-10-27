/* The GL side of Direct3D 9: EGL, render targets, state, draws, blits, present. */
#define _GNU_SOURCE
#include "d3d9_internal.h"
#include <time.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <math.h>
#include <sys/stat.h>
#include <errno.h>

static EGLDisplay egl_display = EGL_NO_DISPLAY;
static EGLContext egl_context = EGL_NO_CONTEXT;
static EGLSurface egl_surface = EGL_NO_SURFACE;
static int window_mode;
static int dump_every;
d3d_gl_limits_t d3d_gl_limits;
static uint32_t trace_frame;   /* defined with the tracing helpers */
static GLuint vao;
static GLuint upload_unit = 31;   /* texture uploads bind here, away from the sampler units */
#define FB_UNKNOWN 0xFFFFFFFFu
/* Binding caches (see bind_texture and d3d_gl_bind_targets). */
static GLuint unit_tex[32], unit_sampler[32];
static GLenum unit_target[32];
static int active_unit = -1;
static uint64_t draw_calls;   /* for the per-frame statistics */
static uint64_t vb_upload_calls, vb_upload_bytes, vb_upload_frame_bytes, vb_upload_peak_bytes, vb_sparse_calls, vb_sparse_saved;
typedef struct { GLuint buffer; GLint size; GLenum type; GLboolean norm; GLsizei stride; uintptr_t offset; GLuint divisor; } attr_state;
static attr_state attr_cache[16];
static GLuint elem_buffer = FB_UNKNOWN;
static int attr_cache_ready;
static int raster_state_valid;
static uint64_t frame_deadline_ns, frame_period_ns;
extern uint32_t d3d_constant_generation;

/* The Android activity provides the window; the shell build has none. */
__attribute__((weak)) void *void_android_window(void) { return NULL; }
__attribute__((weak)) void void_android_frame_presented(void) {}
__attribute__((weak)) void *void_android_window_current(uint32_t *serial, int wait) { (void)wait; *serial = 0; return NULL; }
__attribute__((weak)) void void_android_window_ack(uint32_t serial) { (void)serial; }

/* The window surface follows the activity's (android_main.c): the context
 * stays current on a 1x1 pbuffer while there is none. */
static EGLConfig egl_config;
static EGLSurface egl_pbuffer = EGL_NO_SURFACE;
static uint32_t egl_window_serial;

/* Take up the activity's current window if it changed since the last frame.
 * Without one (the app in the background) the game waits here, letting the
 * other guest threads run, until the activity has a surface again. */
static void follow_window(void)
{
    uint32_t serial;
    void *window = void_android_window_current(&serial, 0);
    if (serial == egl_window_serial) return;
    frame_deadline_ns = 0;
    raster_state_valid = 0;
    eglMakeCurrent(egl_display, egl_pbuffer, egl_pbuffer, egl_context);
    if (egl_surface != EGL_NO_SURFACE) eglDestroySurface(egl_display, egl_surface);
    egl_surface = EGL_NO_SURFACE;
    egl_window_serial = serial;
    void_android_window_ack(serial);
    if (!window) {
        void_log("[gl] surface gone: the game waits for the activity");
        void_blocking_begin();
        window = void_android_window_current(&serial, 1);
        void_blocking_end();
        egl_window_serial = serial;
    }
    egl_surface = eglCreateWindowSurface(egl_display, egl_config, (EGLNativeWindowType)window, NULL);
    if (egl_surface == EGL_NO_SURFACE || !eglMakeCurrent(egl_display, egl_surface, egl_surface, egl_context)) {
        void_log("[gl] new window surface failed %04X", eglGetError());
        eglMakeCurrent(egl_display, egl_pbuffer, egl_pbuffer, egl_context);
        egl_surface = EGL_NO_SURFACE;
    } else {
        eglSwapInterval(egl_display, 1);
        void_log("[gl] presenting into a new window surface");
    }
    void_android_window_ack(serial);
}

int d3d_gl_init(void)
{
    raster_state_valid = 0;
    frame_deadline_ns = 0;
    if (egl_context != EGL_NO_CONTEXT) {
        if (!vao) { glGenVertexArrays(1, &vao); glBindVertexArray(vao); }
        return 1;
    }
    egl_display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    if (!eglInitialize(egl_display, NULL, NULL)) { void_log("[gl] eglInitialize failed %04X", eglGetError()); return 0; }
    void *window = void_android_window_current(&egl_window_serial, 1);   /* NULL in the shell build */
    window_mode = window != NULL;
    const EGLint attrs[] = {
        EGL_SURFACE_TYPE, window_mode ? EGL_WINDOW_BIT | EGL_PBUFFER_BIT : EGL_PBUFFER_BIT,
        EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT_KHR,
        EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8,
        EGL_DEPTH_SIZE, 0, EGL_STENCIL_SIZE, 0, EGL_NONE };
    EGLConfig config;
    EGLint n = 0;
    if (!eglChooseConfig(egl_display, attrs, &config, 1, &n) || !n) { void_log("[gl] no EGL config"); return 0; }
    egl_config = config;
    const EGLint ctx_attrs[] = { EGL_CONTEXT_CLIENT_VERSION, 3, EGL_CONTEXT_MINOR_VERSION_KHR, 2, EGL_NONE };
    egl_context = eglCreateContext(egl_display, config, EGL_NO_CONTEXT, ctx_attrs);
    if (egl_context == EGL_NO_CONTEXT) { void_log("[gl] eglCreateContext failed %04X", eglGetError()); return 0; }
    const EGLint pb[] = { EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE };
    if (window_mode) {
        egl_surface = eglCreateWindowSurface(egl_display, config, (EGLNativeWindowType)window, NULL);
        egl_pbuffer = eglCreatePbufferSurface(egl_display, config, pb);
    } else {
        egl_surface = eglCreatePbufferSurface(egl_display, config, pb);
    }
    if (egl_surface == EGL_NO_SURFACE || !eglMakeCurrent(egl_display, egl_surface, egl_surface, egl_context)) {
        void_log("[gl] EGL surface/current failed %04X", eglGetError());
        return 0;
    }
    if (window_mode) eglSwapInterval(egl_display, 1);
    void_log("[gl] %s / %s / %s (%s)", glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION),
        window_mode ? "window" : "pbuffer");
    GLint value = 0;
    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &value); d3d_gl_limits.max_texture = (uint32_t)value;
    glGetIntegerv(GL_MAX_3D_TEXTURE_SIZE, &value); d3d_gl_limits.max_3d_texture = (uint32_t)value;
    glGetIntegerv(GL_MAX_DRAW_BUFFERS, &value); d3d_gl_limits.max_draw_buffers = (uint32_t)value;
    const char *extensions = (const char *)glGetString(GL_EXTENSIONS);
    d3d_gl_limits.astc_ldr = extensions && strstr(extensions, "GL_KHR_texture_compression_astc_ldr") != NULL;
    void_log("[gl] limits: texture %u, 3D texture %u, draw buffers %u, ASTC %s", d3d_gl_limits.max_texture,
        d3d_gl_limits.max_3d_texture, d3d_gl_limits.max_draw_buffers, d3d_gl_limits.astc_ldr ? "yes" : "no");
    const char *dump = getenv("VOID_DUMP_FRAMES");
    dump_every = dump ? atoi(dump) : 0;
    const char *trace = getenv("VOID_TRACE_FRAME");
    if (trace) trace_frame = (uint32_t)strtoul(trace, NULL, 10);
    glGetIntegerv(GL_MAX_COMBINED_TEXTURE_IMAGE_UNITS, &value);
    upload_unit = value > 32 ? 31u : (GLuint)(value > 21 ? value - 1 : 21);
    glGenVertexArrays(1, &vao);
    glBindVertexArray(vao);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    return 1;
}

/* ------------------------------------------------------------- targets */
static GLuint fbo, read_fbo, draw_fbo;

static void attach(GLenum fb_target, GLenum attachment, d3d_surface *s)
{
    /* Scratch FBOs must not retain smaller attachments from an earlier blit. */
    glFramebufferTexture2D(fb_target, GL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, 0, 0);
    GLenum buffer = attachment == GL_COLOR_ATTACHMENT0 ? GL_COLOR_ATTACHMENT0 : GL_NONE;
    if (buffer == GL_NONE) glFramebufferTexture2D(fb_target, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 0, 0);
    if (fb_target != GL_READ_FRAMEBUFFER) glDrawBuffers(1, &buffer);
    if (fb_target != GL_DRAW_FRAMEBUFFER) glReadBuffer(buffer);
    if (!s) { glFramebufferTexture2D(fb_target, attachment, GL_TEXTURE_2D, 0, 0); return; }
    GLenum target;
    GLint level, layer;
    GLuint tex = d3d_surface_gl_texture(s, &target, &level, &layer);
    if (target == GL_TEXTURE_3D) glFramebufferTextureLayer(fb_target, attachment, tex, level, layer);
    else glFramebufferTexture2D(fb_target, attachment, target, tex, level);
}

static GLenum depth_attachment(const d3d_surface *s)
{
    return s && s->fmt && s->fmt->stencil ? GL_DEPTH_STENCIL_ATTACHMENT : GL_DEPTH_ATTACHMENT;
}

/* ------------------------------------------------------------- tracing
 * VOID_TRACE_FRAME=N logs every target change, clear, draw and blit of frame
 * N and dumps each render target when the frame leaves it (and the back
 * buffer at present) to <data>/frames/trace_N_SEQ.bmp, clamped to [0, 1]. */
static uint32_t trace_frame = 0xFFFFFFFFu;
static unsigned trace_seq;
static d3d_surface *trace_rt;

static int tracing(d3d_device *d) { return d->frame == trace_frame; }
void d3d_shader_trace(void);

/* VOID_TRACE_DIFF: render target 0 before each traced draw, to report what
 * the draw changed. */
static uint8_t *trace_before;
static uint32_t trace_before_w, trace_before_h;

static int trace_read_rt0(d3d_device *d, uint8_t **out, uint32_t *w, uint32_t *h)
{
    d3d_surface *s = d->rt[0];
    if (!s || !s->fmt || s->fmt->is_float || s->fmt->depth) return 0;
    *w = s->width; *h = s->height;
    *out = (uint8_t *)malloc((size_t)s->width * s->height * 4);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    glReadPixels(0, 0, (GLsizei)s->width, (GLsizei)s->height, GL_RGBA, GL_UNSIGNED_BYTE, *out);
    return glGetError() == GL_NO_ERROR;
}

/* Whether the current frame is being traced (for the other D3D9 files). */
int d3d_trace_active(void) { return g_d3d_device && tracing(g_d3d_device); }

/* Trace the next frame (scripted "trace"). */
void d3d_request_trace(void) { if (g_d3d_device) trace_frame = g_d3d_device->frame + 1; }

static uint32_t shader_tag(const void *shader)
{
    if (!shader) return 0;
    const d3d_shader *sh = (const d3d_shader *)shader;
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < sh->size; ++i) h = (h ^ sh->bytecode[i]) * 16777619u;
    return h;
}

static void trace_dump(d3d_device *d, d3d_surface *s, const char *why)
{
    if (!s || !s->fmt || s->fmt->depth) return;
    uint32_t w = s->width, h = s->height, rect[4] = { 0, 0, w, h };
    float *px = (float *)malloc((size_t)w * h * 16);
    if (!d3d_gl_read_rgba(s, rect, px)) {
        void_log("[trace] %s: surface %ux%u fmt %u unreadable", why, w, h, s->format);
        free(px);
        return;
    }
    float lo[4] = { 1e30f, 1e30f, 1e30f, 1e30f }, hi[4] = { -1e30f, -1e30f, -1e30f, -1e30f };
    for (size_t i = 0; i < (size_t)w * h; ++i)
        for (int k = 0; k < 4; ++k) {
            float v = px[4 * i + k];
            if (v < lo[k]) lo[k] = v;
            if (v > hi[k]) hi[k] = v;
        }
    char path[1100];
    snprintf(path, sizeof path, "%s/frames", void_data_dir());
    mkdir(path, 0775);
    snprintf(path, sizeof path, "%s/frames/trace_%u_%03u.bmp", void_data_dir(), d->frame, trace_seq++);
    FILE *f = fopen(path, "wb");
    if (f) {
        uint32_t row = w * 3, pad = (4 - row % 4) % 4, size = 54 + (row + pad) * h;
        uint8_t header[54] = { 'B', 'M' };
        memcpy(header + 2, &size, 4);
        uint32_t v = 54; memcpy(header + 10, &v, 4);
        v = 40; memcpy(header + 14, &v, 4);
        memcpy(header + 18, &w, 4); memcpy(header + 22, &h, 4);
        header[26] = 1; header[28] = 24;
        fwrite(header, 1, 54, f);
        uint8_t zero[4] = {0};
        for (uint32_t y = h; y-- > 0;) {
            for (uint32_t x = 0; x < w; ++x) {
                const float *c = px + 4 * ((size_t)y * w + x);
                uint8_t bgr[3];
                for (int k = 0; k < 3; ++k) {
                    float t = c[2 - k];
                    bgr[k] = (uint8_t)(t <= 0.0f ? 0 : t >= 1.0f ? 255 : t * 255.0f + 0.5f);
                }
                fwrite(bgr, 1, 3, f);
            }
            fwrite(zero, 1, pad, f);
        }
        fclose(f);
    }
    void_log("[trace] %s: %ux%u fmt %u -> %s  r[%g,%g] g[%g,%g] b[%g,%g] a[%g,%g]", why, w, h, s->format, path,
        lo[0], hi[0], lo[1], hi[1], lo[2], hi[2], lo[3], hi[3]);
    free(px);
}

/* What the render framebuffer object has attached. Re-attaching the very same
 * texture still ends a tiler's render pass (Mali stores and reloads every
 * tile), and the map set its depth surface ~290 times a frame: only real
 * changes reach GL. A deleted texture's name can come back, so deletion
 * forgets it (d3d_gl_forget_texture). */
typedef struct { GLuint tex; GLenum target; GLint level, layer; } fb_attachment;
static fb_attachment fb_color[4] = { { FB_UNKNOWN, 0, 0, 0 }, { FB_UNKNOWN, 0, 0, 0 }, { FB_UNKNOWN, 0, 0, 0 },
                                     { FB_UNKNOWN, 0, 0, 0 } };
static fb_attachment fb_depth = { FB_UNKNOWN, 0, 0, 0 };
static GLenum fb_depth_point = FB_UNKNOWN, fb_bufs[4];
static uint32_t fb_depth_w, fb_depth_h;
static GLsizei fb_buf_count = -1;

static fb_attachment attachment_of(d3d_surface *s)
{
    fb_attachment a = { 0, GL_TEXTURE_2D, 0, 0 };
    if (s) a.tex = d3d_surface_gl_texture(s, &a.target, &a.level, &a.layer);
    return a;
}

static int same_attachment(fb_attachment a, fb_attachment b)
{
    return a.tex == b.tex && a.target == b.target && a.level == b.level && a.layer == b.layer;
}

static void put_attachment(GLenum point, fb_attachment a)
{
    if (!a.tex) glFramebufferTexture2D(GL_FRAMEBUFFER, point, GL_TEXTURE_2D, 0, 0);
    else if (a.target == GL_TEXTURE_3D) glFramebufferTextureLayer(GL_FRAMEBUFFER, point, a.tex, a.level, a.layer);
    else glFramebufferTexture2D(GL_FRAMEBUFFER, point, a.target, a.tex, a.level);
}

void d3d_gl_forget_texture(GLuint tex)
{
    for (int i = 0; i < 32; ++i) if (unit_tex[i] == tex) unit_tex[i] = 0;   /* deletion unbinds it everywhere */
    for (int i = 0; i < 4; ++i) if (fb_color[i].tex == tex) fb_color[i].tex = FB_UNKNOWN;
    if (fb_depth.tex == tex) { fb_depth.tex = FB_UNKNOWN; fb_depth_point = FB_UNKNOWN; }
}

/* The native quad renderer is shared by text, buttons and UI panels. */
static unsigned ui_quad_depth;
static int ui_active;
static d3d_device *ui_owner;
static d3d_surface *ui_backbuffer, *ui_color, *ui_depth, *ui_depth_source;

void sub_00A46BC0_lifted(void);
void sub_00A46BC0(void)
{
    ++ui_quad_depth;
    sub_00A46BC0_lifted();
    --ui_quad_depth;
}

static void ui_release(d3d_surface **surface)
{
    if (*surface) void_com_release(&(*surface)->com);
    *surface = NULL;
}

static int ui_allocate(d3d_device *d, d3d_surface **surface, d3d_surface *source, uint32_t w, uint32_t h)
{
    if (*surface && ((*surface)->dev != d || (*surface)->width != w || (*surface)->height != h ||
                     (*surface)->format != source->format)) ui_release(surface);
    if (!*surface) {
        *surface = d3d_surface_new(d, w, h, source->format, source->usage, D3DPOOL_DEFAULT, 0);
        GLint allocated = 0;
        if (*surface && (*surface)->gl) glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &allocated);
        if (allocated != (GLint)w) { ui_release(surface); return 0; }
    }
    return *surface && (*surface)->gl;
}

static d3d_surface *ui_surface(d3d_device *d, d3d_surface *surface)
{
    if (!ui_active || ui_owner != d || d->backbuffer != ui_backbuffer) return surface;
    if (surface == ui_backbuffer) return ui_color;
    if (surface && surface == ui_depth_source && d->rt[0] == ui_backbuffer) return ui_depth;
    return surface;
}

static void ui_copy(d3d_surface *source, d3d_surface *target)
{
    uint32_t from[] = {0, 0, source->width, source->height};
    uint32_t to[] = {0, 0, target->width, target->height};
    int active = ui_active;
    d3d_surface *depth_source = ui_depth_source;
    ui_active = 0;
    source->dev->fbo_dirty = 1;
    d3d_gl_blit(source, from, target, to, source->fmt->depth ? 1 : 2);
    ui_active = active;
    ui_depth_source = depth_source;
    source->dev->fbo_dirty = 1;
}

static void ui_prepare_depth(d3d_device *d)
{
    if (!ui_active || ui_owner != d || d->backbuffer != ui_backbuffer || d->rt[0] != ui_backbuffer) {
        ui_depth_source = NULL;
        return;
    }
    if (d->ds == ui_depth_source) return;
    ui_depth_source = NULL;
    if (d->ds) {
        if (!ui_allocate(d, &ui_depth, d->ds, ui_color->width, ui_color->height)) {
            ui_copy(ui_color, ui_backbuffer);
            ui_active = 0;
        } else {
            ui_copy(d->ds, ui_depth);
            ui_depth_source = d->ds;
        }
    }
    d->fbo_dirty = 1;
}

static void ui_promote(d3d_device *d)
{
    if (ui_active || !window_mode || !d->backbuffer || d->rt[0] != d->backbuffer ||
        d->rt[1] || d->rt[2] || d->rt[3] || egl_surface == EGL_NO_SURFACE) return;
    EGLint w = 0, h = 0;
    if (!eglQuerySurface(egl_display, egl_surface, EGL_WIDTH, &w) ||
        !eglQuerySurface(egl_display, egl_surface, EGL_HEIGHT, &h) || w <= 0 || h <= 0) return;
    d3d_surface *bb = d->backbuffer;
    float scale = fminf((float)w / bb->width, (float)h / bb->height);
    uint32_t width = (uint32_t)lroundf(bb->width * scale), height = (uint32_t)lroundf(bb->height * scale);
    if (width <= bb->width && height <= bb->height) return;
    if (width > d3d_gl_limits.max_texture || height > d3d_gl_limits.max_texture) return;
    int changed = !ui_color || ui_color->width != width || ui_color->height != height;
    if (!ui_allocate(d, &ui_color, bb, width, height)) return;
    ui_copy(bb, ui_color);
    ui_owner = d;
    ui_backbuffer = bb;
    ui_depth_source = NULL;
    ui_active = 1;
    d->fbo_dirty = 1;
    raster_state_valid = 0;
    if (changed) void_log("[gl] UI %ux%u over scene %ux%u", width, height, bb->width, bb->height);
}

/* Scale rectangle edges together, so neighbouring clips have no cracks. */
static void ui_rect(d3d_device *d, const uint32_t in[4], uint32_t out[4])
{
    memcpy(out, in, 4 * sizeof *out);
    if (!d || d->rt[0] != d->backbuffer || ui_surface(d, d->backbuffer) == d->backbuffer) return;
    double x = (double)ui_color->width / d->backbuffer->width;
    double y = (double)ui_color->height / d->backbuffer->height;
    int32_t left = (int32_t)lround((int32_t)in[0] * x), top = (int32_t)lround((int32_t)in[1] * y);
    out[0] = (uint32_t)left; out[1] = (uint32_t)top;
    out[2] = (uint32_t)((int32_t)lround(((int32_t)in[2] + (double)(int32_t)in[0]) * x) - left);
    out[3] = (uint32_t)((int32_t)lround(((int32_t)in[3] + (double)(int32_t)in[1]) * y) - top);
}

static void ui_scissor(d3d_device *d, int x, int y, int w, int h)
{
    uint32_t in[] = {(uint32_t)x, (uint32_t)y, (uint32_t)w, (uint32_t)h}, out[4];
    ui_rect(d, in, out);
    glScissor((GLint)out[0], (GLint)out[1], (GLsizei)out[2], (GLsizei)out[3]);
}

void d3d_gl_bind_targets(d3d_device *dev)
{
    ui_prepare_depth(dev);
    if (!fbo) glGenFramebuffers(1, &fbo);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (!dev->fbo_dirty) return;
    if (tracing(dev) && trace_rt != dev->rt[0]) {
        if (trace_rt) trace_dump(dev, trace_rt, "target done");
        trace_rt = dev->rt[0];
        void_log("[trace] target rt0 %p %ux%u fmt %u%s, rt1 %p, ds %p %ux%u fmt %u", (void *)dev->rt[0],
            dev->rt[0] ? dev->rt[0]->width : 0, dev->rt[0] ? dev->rt[0]->height : 0, dev->rt[0] ? dev->rt[0]->format : 0,
            dev->rt[0] == dev->backbuffer ? " (back buffer)" : "", (void *)dev->rt[1], (void *)dev->ds,
            dev->ds ? dev->ds->width : 0, dev->ds ? dev->ds->height : 0, dev->ds ? dev->ds->format : 0);
    }
    GLenum bufs[4];
    int last = 0, changed = 0;
    for (int i = 0; i < 4; ++i) {
        d3d_surface *s = ui_surface(dev, dev->rt[i]);
        int usable = s && s->fmt && s->fmt->internal;
        fb_attachment a = attachment_of(usable ? s : NULL);
        if (!same_attachment(a, fb_color[i])) {
            put_attachment(GL_COLOR_ATTACHMENT0 + (GLenum)i, a);
            fb_color[i] = a;
            changed = 1;
        }
        bufs[i] = usable ? GL_COLOR_ATTACHMENT0 + (GLenum)i : GL_NONE;
        if (usable) last = i + 1;
    }
    GLsizei count = last ? last : 1;
    if (count != fb_buf_count || memcmp(bufs, fb_bufs, sizeof(GLenum) * (size_t)count)) {
        glDrawBuffers(count, bufs);
        memcpy(fb_bufs, bufs, sizeof bufs);
        fb_buf_count = count;
    }
    d3d_surface *depth = ui_surface(dev, dev->ds);
    fb_attachment z = attachment_of(depth);
    GLenum point = depth ? depth_attachment(depth) : 0;
    d3d_surface *rt0 = ui_surface(dev, dev->rt[0]);
    if (!dev->ds && fb_depth_point != FB_UNKNOWN && fb_depth_point && fb_depth.tex != FB_UNKNOWN && rt0 &&
        fb_depth_w >= rt0->width && fb_depth_h >= rt0->height) {
        /* No depth surface: keep the last one attached while it covers the
         * colour target. Depth and stencil tests and clears all check d->ds,
         * so it is neither read nor written; detaching it would end the
         * render pass at every NULL <-> surface toggle (the map toggles
         * between passes ~10 times a frame). */
        z = fb_depth;
        point = fb_depth_point;
    }
    if (point != fb_depth_point || !same_attachment(z, fb_depth)) {
        if (fb_depth_point == FB_UNKNOWN) {
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT, GL_TEXTURE_2D, 0, 0);
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D, 0, 0);
        } else if (fb_depth_point && fb_depth_point != point) {
            glFramebufferTexture2D(GL_FRAMEBUFFER, fb_depth_point, GL_TEXTURE_2D, 0, 0);
        }
        if (point) put_attachment(point, z);
        if (tracing(dev)) void_log("[trace] depth attachment %u -> %u (ds %p)", fb_depth.tex, z.tex, (void *)dev->ds);
        fb_depth = z;
        fb_depth_point = point;
        if (depth) { fb_depth_w = depth->width; fb_depth_h = depth->height; }
        changed = 1;
    }
    GLenum status = changed ? glCheckFramebufferStatus(GL_FRAMEBUFFER) : GL_FRAMEBUFFER_COMPLETE;
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        static int warned;
        if (warned++ < 20)
            void_log("[gl] framebuffer incomplete %04X: rt0 %ux%u fmt %u, ds %ux%u fmt %u", status,
                dev->rt[0] ? dev->rt[0]->width : 0, dev->rt[0] ? dev->rt[0]->height : 0, dev->rt[0] ? dev->rt[0]->format : 0,
                dev->ds ? dev->ds->width : 0, dev->ds ? dev->ds->height : 0, dev->ds ? dev->ds->format : 0);
    }
    dev->fbo_dirty = 0;
}

/* --------------------------------------------------------------- state */
static GLenum compare(uint32_t f)
{
    static const GLenum map[] = { GL_ALWAYS, GL_NEVER, GL_LESS, GL_EQUAL, GL_LEQUAL, GL_GREATER, GL_NOTEQUAL, GL_GEQUAL, GL_ALWAYS };
    return f < 9 ? map[f] : GL_ALWAYS;
}

static GLenum blend_factor(uint32_t b, int alpha)
{
    switch (b) {
    case 1: return GL_ZERO;
    case 2: return GL_ONE;
    case 3: return alpha ? GL_SRC_ALPHA : GL_SRC_COLOR;
    case 4: return alpha ? GL_ONE_MINUS_SRC_ALPHA : GL_ONE_MINUS_SRC_COLOR;
    case 5: return GL_SRC_ALPHA;
    case 6: return GL_ONE_MINUS_SRC_ALPHA;
    case 7: return GL_DST_ALPHA;
    case 8: return GL_ONE_MINUS_DST_ALPHA;
    case 9: return alpha ? GL_DST_ALPHA : GL_DST_COLOR;
    case 10: return alpha ? GL_ONE_MINUS_DST_ALPHA : GL_ONE_MINUS_DST_COLOR;
    case 11: return GL_SRC_ALPHA_SATURATE;
    case 14: return alpha ? GL_CONSTANT_ALPHA : GL_CONSTANT_COLOR;
    case 15: return alpha ? GL_ONE_MINUS_CONSTANT_ALPHA : GL_ONE_MINUS_CONSTANT_COLOR;
    default: return GL_ONE;
    }
}

static GLenum blend_op(uint32_t op)
{
    switch (op) {
    case 2: return GL_FUNC_SUBTRACT;
    case 3: return GL_FUNC_REVERSE_SUBTRACT;
    case 4: return GL_MIN;
    case 5: return GL_MAX;
    default: return GL_FUNC_ADD;
    }
}

static GLenum stencil_op(uint32_t op)
{
    static const GLenum map[] = { GL_KEEP, GL_KEEP, GL_ZERO, GL_REPLACE, GL_INCR, GL_DECR, GL_INVERT, GL_INCR_WRAP, GL_DECR_WRAP };
    return op < 9 ? map[op] : GL_KEEP;
}

static float u2f(uint32_t u) { float f; memcpy(&f, &u, 4); return f; }

typedef struct {
    uint32_t rs[33], viewport[4], scissor[4];
    float range[2];
    uint32_t depth[3];
} raster_state_key;
static raster_state_key raster_state_held;

void d3d_gl_apply_state(d3d_device *d)
{
    const uint32_t *rs = d->st.rs;
    raster_state_key key = {
        { rs[7], rs[23], rs[14], rs[27], rs[19], rs[20], rs[171], rs[206], rs[207], rs[208], rs[209], rs[193],
          rs[22], rs[52], rs[56], rs[57], rs[58], rs[53], rs[54], rs[55], rs[185], rs[189], rs[186], rs[187],
          rs[188], rs[59], rs[168], rs[190], rs[191], rs[192], rs[174], rs[195], rs[175] },
        {0}, {0}, {0},
        { d->ds != NULL, d->ds && d->ds->fmt && d->ds->fmt->stencil,
          d->ds && d->ds->fmt && d->ds->fmt->bits == 16 }
    };
    ui_rect(d, d->st.viewport, key.viewport);
    ui_rect(d, d->st.scissor, key.scissor);
    memcpy(key.range, d->st.viewport_z, sizeof key.range);
    if (raster_state_valid && !memcmp(&key, &raster_state_held, sizeof key)) return;
    raster_state_held = key;
    raster_state_valid = 1;
    /* Depth */
    if (rs[7] && d->ds) glEnable(GL_DEPTH_TEST); else glDisable(GL_DEPTH_TEST);
    glDepthFunc(compare(rs[23]));
    glDepthMask(rs[14] ? GL_TRUE : GL_FALSE);
    /* Blend */
    if (rs[27]) {
        glEnable(GL_BLEND);
        uint32_t src = rs[19], dst = rs[20];
        if (src == 12) { src = 5; dst = 6; } else if (src == 13) { src = 6; dst = 5; }
        uint32_t asrc = src, adst = dst, aop = rs[171];
        if (rs[206]) {
            asrc = rs[207]; adst = rs[208]; aop = rs[209];
            if (asrc == 12) { asrc = 5; adst = 6; } else if (asrc == 13) { asrc = 6; adst = 5; }
        }
        glBlendFuncSeparate(blend_factor(src, 0), blend_factor(dst, 0), blend_factor(asrc, 1), blend_factor(adst, 1));
        glBlendEquationSeparate(blend_op(rs[171]), blend_op(aop));
        uint32_t bf = rs[193];
        glBlendColor(((bf >> 16) & 255) / 255.0f, ((bf >> 8) & 255) / 255.0f, (bf & 255) / 255.0f, (bf >> 24) / 255.0f);
    } else {
        glDisable(GL_BLEND);
    }
    /* Cull: D3D clockwise is GL counter-clockwise in the flipped targets. */
    glFrontFace(GL_CCW);
    if (rs[22] == 1) glDisable(GL_CULL_FACE);
    else { glEnable(GL_CULL_FACE); glCullFace(rs[22] == 2 ? GL_FRONT : GL_BACK); }
    /* Stencil */
    if (rs[52] && d->ds && d->ds->fmt && d->ds->fmt->stencil) {
        glEnable(GL_STENCIL_TEST);
        glStencilFuncSeparate(GL_FRONT, compare(rs[56]), (GLint)rs[57], rs[58]);
        glStencilOpSeparate(GL_FRONT, stencil_op(rs[53]), stencil_op(rs[54]), stencil_op(rs[55]));
        if (rs[185]) {
            glStencilFuncSeparate(GL_BACK, compare(rs[189]), (GLint)rs[57], rs[58]);
            glStencilOpSeparate(GL_BACK, stencil_op(rs[186]), stencil_op(rs[187]), stencil_op(rs[188]));
        } else {
            glStencilFuncSeparate(GL_BACK, compare(rs[56]), (GLint)rs[57], rs[58]);
            glStencilOpSeparate(GL_BACK, stencil_op(rs[53]), stencil_op(rs[54]), stencil_op(rs[55]));
        }
        glStencilMask(rs[59]);
    } else {
        glDisable(GL_STENCIL_TEST);
    }
    /* Colour write masks */
    static const int mask_state[4] = { 168, 190, 191, 192 };
    for (int i = 0; i < 4; ++i) {
        uint32_t m = rs[mask_state[i]];
        glColorMaski((GLuint)i, (m & 1) != 0, (m & 2) != 0, (m & 4) != 0, (m & 8) != 0);
    }
    /* Scissor */
    if (rs[174]) {
        glEnable(GL_SCISSOR_TEST);
        ui_scissor(d, (int)d->st.scissor[0], (int)d->st.scissor[1], (int)d->st.scissor[2], (int)d->st.scissor[3]);
    } else {
        glDisable(GL_SCISSOR_TEST);
    }
    /* Depth bias */
    float bias = u2f(rs[195]), slope = u2f(rs[175]);
    if (bias != 0.0f || slope != 0.0f) {
        glEnable(GL_POLYGON_OFFSET_FILL);
        float scale = (d->ds && d->ds->fmt && d->ds->fmt->bits == 16) ? 65535.0f : 16777215.0f;
        glPolygonOffset(slope, bias * scale);
    } else {
        glDisable(GL_POLYGON_OFFSET_FILL);
    }
    /* Viewport */
    uint32_t viewport[4];
    ui_rect(d, d->st.viewport, viewport);
    glViewport((GLint)viewport[0], (GLint)viewport[1], (GLsizei)viewport[2], (GLsizei)viewport[3]);
    glDepthRangef(d->st.viewport_z[0], d->st.viewport_z[1]);
}

/* ------------------------------------------------------------- samplers */
typedef struct { uint32_t key[9]; GLuint sampler; } sampler_entry;
static sampler_entry sampler_cache[512];
static int sampler_count;

static GLenum address(uint32_t a)
{
    switch (a) {
    case 2: return GL_MIRRORED_REPEAT;
    case 3: return GL_CLAMP_TO_EDGE;
    case 4: return GL_CLAMP_TO_BORDER_EXT;
    case 5: return GL_MIRRORED_REPEAT;          /* MIRRORONCE: closest available */
    default: return GL_REPEAT;
    }
}

static GLuint sampler_for(const uint32_t *ss, int no_filter, uint32_t levels, uint32_t lod)
{
    uint32_t key[9] = { ss[1], ss[2], ss[3], ss[4], no_filter ? 1 : ss[5], no_filter ? 1 : ss[6],
        no_filter ? (ss[7] ? 1u : 0u) : ss[7], ss[10], ss[9] > lod ? ss[9] : lod };
    (void)levels;
    for (int i = 0; i < sampler_count; ++i) if (!memcmp(sampler_cache[i].key, key, sizeof key)) return sampler_cache[i].sampler;
    GLuint s;
    glGenSamplers(1, &s);
    glSamplerParameteri(s, GL_TEXTURE_WRAP_S, (GLint)address(key[0]));
    glSamplerParameteri(s, GL_TEXTURE_WRAP_T, (GLint)address(key[1]));
    glSamplerParameteri(s, GL_TEXTURE_WRAP_R, (GLint)address(key[2]));
    uint32_t bc = key[3];
    GLfloat border[4] = { ((bc >> 16) & 255) / 255.0f, ((bc >> 8) & 255) / 255.0f, (bc & 255) / 255.0f, (bc >> 24) / 255.0f };
    glSamplerParameterfv(s, GL_TEXTURE_BORDER_COLOR_EXT, border);
    uint32_t mag = key[4], min = key[5], mip = key[6];
    glSamplerParameteri(s, GL_TEXTURE_MAG_FILTER, mag >= 2 ? GL_LINEAR : GL_NEAREST);
    GLenum minf;
    int linear = min >= 2;
    if (mip == 0) minf = linear ? GL_LINEAR : GL_NEAREST;
    else if (mip == 1) minf = linear ? GL_LINEAR_MIPMAP_NEAREST : GL_NEAREST_MIPMAP_NEAREST;
    else minf = linear ? GL_LINEAR_MIPMAP_LINEAR : GL_NEAREST_MIPMAP_LINEAR;
    glSamplerParameteri(s, GL_TEXTURE_MIN_FILTER, (GLint)minf);
    float aniso = (min == 3 || mag == 3) ? (float)(key[7] ? key[7] : 1) : 1.0f;
    if (aniso > 16.0f) aniso = 16.0f;
    glSamplerParameterf(s, GL_TEXTURE_MAX_ANISOTROPY_EXT, aniso);
    glSamplerParameterf(s, GL_TEXTURE_MIN_LOD, (float)key[8]);
    if (sampler_count < 512) {
        memcpy(sampler_cache[sampler_count].key, key, sizeof key);
        sampler_cache[sampler_count++].sampler = s;
    }
    return s;
}

/* What each texture unit and vertex attribute holds, so a draw only sends GL
 * the bindings that changed: Mali revalidates at the draw for every binding
 * call, changed or not. Texture uploads bind on a unit of their own
 * (d3d_gl_upload_unit); deleted textures and buffers are forgotten. */

static void activate_unit(GLuint unit)
{
    if ((int)unit == active_unit) return;
    glActiveTexture(GL_TEXTURE0 + unit);
    active_unit = (int)unit;
}

void d3d_gl_upload_unit(void) { activate_unit(upload_unit); }

void d3d_gl_forget_buffer(GLuint buffer)
{
    for (int i = 0; i < 16; ++i) if (attr_cache[i].buffer == buffer) attr_cache[i].buffer = FB_UNKNOWN;
    if (elem_buffer == buffer) elem_buffer = FB_UNKNOWN;
}

static void bind_texture(d3d_device *d, int slot, GLuint unit)
{
    d3d_texture *t = (d3d_texture *)d->st.textures[slot];
    if (!t || !t->gl) {
        if (unit_tex[unit]) {
            activate_unit(unit);
            glBindTexture(GL_TEXTURE_2D, 0);
            glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
            unit_tex[unit] = 0;
        }
        return;
    }
    if (t->mips_dirty) d3d_generate_mips(t);
    if (unit_tex[unit] != t->gl || unit_target[unit] != t->target) {
        activate_unit(unit);
        glBindTexture(t->target, t->gl);
        unit_tex[unit] = t->gl;
        unit_target[unit] = t->target;
    }
    int no_filter = t->fmt->depth || (t->fmt->is_float && t->fmt->gl_bits / (t->fmt->format == GL_RED ? 1 : t->fmt->format == GL_RG ? 2 : 4) >= 32);
    if (t->levels < 2) {
        /* No mip chain: D3D samples level 0 whatever MIPFILTER says. */
        uint32_t ss[14];
        memcpy(ss, d->st.ss[slot], sizeof ss);
        ss[7] = 0;
        GLuint sampler = sampler_for(ss, no_filter, t->levels, t->lod);
        if (unit_sampler[unit] != sampler) { glBindSampler(unit, sampler); unit_sampler[unit] = sampler; }
    } else {
        GLuint sampler = sampler_for(d->st.ss[slot], no_filter, t->levels, t->lod);
        if (unit_sampler[unit] != sampler) { glBindSampler(unit, sampler); unit_sampler[unit] = sampler; }
    }
}

/* Dedicated CPU-only capture; the general render trace performs readbacks. */
static unsigned depth_trace_requested;
static unsigned depth_trace_remaining, depth_trace_samples, depth_trace_hits;
static uint64_t depth_trace_draws, depth_trace_null, depth_trace_retained, depth_trace_aliases;

void d3d_request_depth_trace(void)
{
    __atomic_store_n(&depth_trace_requested, 1u, __ATOMIC_RELAXED);
}

static uint32_t retained_depth_sampler_mask(d3d_device *d, uint32_t ps, uint32_t vs)
{
    if (d->ds || !fb_depth_point || fb_depth_point == FB_UNKNOWN || !fb_depth.tex || fb_depth.tex == FB_UNKNOWN) return 0;
    uint32_t hits = 0;
    for (unsigned slot = 0; slot < 20; ++slot) {
        if (slot < 16 ? !(ps & (1u << slot)) : !(vs & (1u << (slot - 16)))) continue;
        d3d_texture *t = (d3d_texture *)d->st.textures[slot];
        if (t && t->gl && t->gl == fb_depth.tex) hits |= 1u << slot;
    }
    return hits;
}

static void depth_trace_draw(d3d_device *d, uint32_t ps, uint32_t vs, uint32_t vertex, uint32_t pixel)
{
    if (!depth_trace_remaining) return;
    ++depth_trace_draws;
    if (d->ds) return;
    ++depth_trace_null;
    if (!fb_depth_point || fb_depth_point == FB_UNKNOWN || !fb_depth.tex || fb_depth.tex == FB_UNKNOWN) return;
    ++depth_trace_retained;
    uint32_t hits = retained_depth_sampler_mask(d, ps, vs);
    if (hits) ++depth_trace_aliases;
    if (hits ? depth_trace_hits >= 12 : depth_trace_samples >= 4) return;
    if (hits) ++depth_trace_hits; else ++depth_trace_samples;
    char textures[1024] = {0};
    size_t used = 0;
    for (unsigned slot = 0; slot < 20; ++slot) {
        if (slot < 16 ? !(ps & (1u << slot)) : !(vs & (1u << (slot - 16)))) continue;
        d3d_texture *t = (d3d_texture *)d->st.textures[slot];
        int n = snprintf(textures + used, sizeof textures - used,
            " %c%u=%u/%X(t=%u,levels=%u,lod=%u,mip=%u)", slot < 16 ? 'p' : 'v', slot < 16 ? slot : slot - 16,
            unit_tex[slot], unit_target[slot], t ? t->gl : 0, t ? t->levels : 0, t ? t->lod : 0, d->st.ss[slot][7]);
        if (n < 0 || (size_t)n >= sizeof textures - used) break;
        used += (size_t)n;
    }
    void_log("[depth-trace] %s frame=%u draw=%llu rt=%u/%ux%u depth=%u point=%X level=%d layer=%d size=%ux%u ps=%X vs=%X hit=%X shaders=%08X/%08X%s",
        hits ? "alias" : "sample", d->frame, (unsigned long long)draw_calls, fb_color[0].tex,
        d->rt[0] ? d->rt[0]->width : 0, d->rt[0] ? d->rt[0]->height : 0, fb_depth.tex, fb_depth_point,
        fb_depth.level, fb_depth.layer, fb_depth_w, fb_depth_h, ps, vs, hits, vertex, pixel, textures);
}

static void depth_trace_present(d3d_device *d)
{
    if (depth_trace_remaining && !--depth_trace_remaining) {
        void_log("[depth-trace] end frame=%u draws=%llu nullDS=%llu retainedDS=%llu aliasDraws=%llu records=%u",
            d->frame, (unsigned long long)depth_trace_draws, (unsigned long long)depth_trace_null,
            (unsigned long long)depth_trace_retained, (unsigned long long)depth_trace_aliases,
            depth_trace_samples + depth_trace_hits);
    }
    if (!__atomic_exchange_n(&depth_trace_requested, 0u, __ATOMIC_RELAXED)) return;
    depth_trace_remaining = 120;
    depth_trace_samples = depth_trace_hits = 0;
    depth_trace_draws = depth_trace_null = depth_trace_retained = depth_trace_aliases = 0;
    void_log("[depth-trace] begin after frame=%u frames=120 maxRecords=16", d->frame);
}


/* ------------------------------------------------------------ attributes */
typedef struct { GLint size; GLenum type; GLboolean norm; } attr_format;
static const attr_format attr_formats[] = {
    {1, GL_FLOAT, GL_FALSE}, {2, GL_FLOAT, GL_FALSE}, {3, GL_FLOAT, GL_FALSE}, {4, GL_FLOAT, GL_FALSE},
    {4, GL_UNSIGNED_BYTE, GL_TRUE}, {4, GL_UNSIGNED_BYTE, GL_FALSE}, {2, GL_SHORT, GL_FALSE}, {4, GL_SHORT, GL_FALSE},
    {4, GL_UNSIGNED_BYTE, GL_TRUE}, {2, GL_SHORT, GL_TRUE}, {4, GL_SHORT, GL_TRUE}, {2, GL_UNSIGNED_SHORT, GL_TRUE},
    {4, GL_UNSIGNED_SHORT, GL_TRUE}, {4, GL_UNSIGNED_INT_2_10_10_10_REV, GL_FALSE}, {4, GL_INT_2_10_10_10_REV, GL_TRUE},
    {2, GL_HALF_FLOAT, GL_FALSE}, {4, GL_HALF_FLOAT, GL_FALSE},
};
static const uint8_t attr_bytes[] = {4, 8, 12, 16, 4, 4, 4, 8, 4, 4, 8, 4, 8, 4, 4, 4, 8};

static const d3d_vertex_element *find_element(d3d_device *d, int usage, int index)
{
    d3d_decl *decl = (d3d_decl *)d->st.decl;
    if (!decl) return NULL;
    for (int i = 0; i < decl->count; ++i)
        if (decl->elements[i].usage == usage && decl->elements[i].usage_index == index && decl->elements[i].type < 17)
            return &decl->elements[i];
    /* POSITIONT feeds a POSITION input, as for pre-transformed vertices. */
    if (usage == 0) for (int i = 0; i < decl->count; ++i)
        if (decl->elements[i].usage == 9 && decl->elements[i].usage_index == index) return &decl->elements[i];
    return NULL;
}

static int bgra_of(d3d_device *d, int usage, int index)
{
    const d3d_vertex_element *e = find_element(d, usage, index);
    return e && e->type == 4;
}

void d3d_buffer_flush(d3d_buffer *b);
void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi);

/* Bound the bytes the GPU actually fetches, not the pooled allocator's whole
 * Lock(0, 0). Reuse a scanned index range until its next writable lock. */
static int draw_vertex_bounds(d3d_buffer *ib, const void *up_indices, int up_i32,
    uint32_t start, uint32_t count, int indexed, uint32_t base, uint32_t start_index,
    uint32_t *first, uint32_t *last)
{
    if (!count) return 0;
    if (!indexed) {
        uint64_t end = (uint64_t)start + count - 1u;
        if (end > UINT32_MAX) return 0;
        *first = start; *last = (uint32_t)end; return 1;
    }
    int i32 = up_indices ? up_i32 : ib && ib->format == 102;
    const uint8_t *indices = (const uint8_t *)up_indices;
    uint32_t lo = UINT32_MAX, hi = 0;
    int cached = 0;
    if (!indices) {
        uint64_t offset = (uint64_t)start_index * (i32 ? 4u : 2u);
        uint64_t end = offset + (uint64_t)count * (i32 ? 4u : 2u);
        if (!ib || end > ib->size) return 0;
        cached = !ib->locks && ib->bounds_count == count && ib->bounds_start == start_index && ib->bounds_format == ib->format;
        if (cached) { lo = ib->bounds_lo; hi = ib->bounds_hi; }
        else indices = (const uint8_t *)GPTR(ib->shadow) + offset;
    }
    if (!cached && i32) {
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t v; memcpy(&v, indices + (size_t)i * 4u, 4);
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
    } else if (!cached) {
        for (uint32_t i = 0; i < count; ++i) {
            uint16_t v; memcpy(&v, indices + (size_t)i * 2u, 2);
            if (v < lo) lo = v;
            if (v > hi) hi = v;
        }
    }
    if (!up_indices && !ib->locks && !cached) {
        ib->bounds_start = start_index; ib->bounds_count = count; ib->bounds_format = ib->format;
        ib->bounds_lo = lo; ib->bounds_hi = hi;
    }
    int64_t low = (int64_t)lo + (int32_t)base, high = (int64_t)hi + (int32_t)base;
    if (low < 0 || high > UINT32_MAX) return 0;
    *first = (uint32_t)low; *last = (uint32_t)high; return 1;
}

static void buffer_flush_vertices(d3d_buffer *b, uint64_t offset, uint32_t stride,
    uint32_t bytes, uint32_t first, uint32_t last, int bounded)
{
    if (!bounded || offset >= b->size) { d3d_buffer_flush(b); return; }
    /* GL interprets zero stride as tightly packed attributes. */
    if (!stride) stride = bytes;
    uint64_t lo = offset + (uint64_t)first * stride;
    uint64_t hi = offset + (uint64_t)last * stride + bytes;
    if (hi > b->size || lo >= hi) d3d_buffer_flush(b);
    else d3d_buffer_flush_range(b, (uint32_t)lo, (uint32_t)hi);
}

static int draw_stream_range(uint32_t buffer_size, uint32_t stream_offset, uint32_t stride,
    uint32_t attr_end, uint32_t first, uint32_t last, uint32_t *out_lo, uint32_t *out_bytes)
{
    if (!stride || !attr_end || first > last) return 0;
    uint64_t lo = (uint64_t)stream_offset + (uint64_t)first * stride;
    uint64_t hi = (uint64_t)stream_offset + (uint64_t)last * stride + attr_end;
    if (hi > buffer_size || lo >= hi) return 0;
    *out_lo = (uint32_t)lo; *out_bytes = (uint32_t)(hi - lo); return 1;
}

static int draw_rebase(uint32_t base, uint32_t first, int indexed, int32_t *out_base)
{
    int64_t value = indexed ? (int64_t)(int32_t)base - first : 0;
    if (value < INT32_MIN || value > INT32_MAX) return 0;
    *out_base = (int32_t)value; return 1;
}
int d3d_shader_bind2(d3d_device *dev, d3d_shader *vs, d3d_shader *ps, int (*bgra)(d3d_device *, int, int),
    int *attr_count, const int **attr_usage, const int **attr_index, uint32_t *ps_samplers, uint32_t *vs_samplers,
    const int **ps_types, const int **vs_types);
void d3d_shader_upload(d3d_device *dev, float half_x, float half_y, int alpha_func, float alpha_ref);

static GLuint up_vbo, up_ibo;
static GLuint stream_vbos[16];

/* Per-draw uploads go to one persistently mapped buffer (GL_EXT_buffer_storage):
 * RING_SEGMENTS segments, one per frame in flight, each reused only after the
 * fence of the frame that last wrote it. A fresh glBufferData store per draw
 * cost an allocation and the driver's own copy ~430 times a frame. A frame
 * that outgrows its segment uploads the rest the old way. */
#define RING_SEGMENTS 3u
#define RING_SEGMENT_BYTES (16u << 20)
static GLuint ring_buffer;
static uint8_t *ring_map;
static uint32_t ring_segment, ring_used;
static GLsync ring_fence[RING_SEGMENTS];
static int ring_state;                   /* 0 untried, 1 mapped, -1 unavailable */
static uint32_t stream_ring[16];         /* this draw's ring offset per stream, or UINT32_MAX */
static uint32_t sparse_ring_at;          /* ring offset of this draw's sparse gather, or UINT32_MAX */

static int ring_ready(void)
{
    if (ring_state) return ring_state > 0;
    ring_state = -1;
    const char *extensions = (const char *)glGetString(GL_EXTENSIONS);
    if (!extensions || !strstr(extensions, "GL_EXT_buffer_storage") || getenv("VOID_NO_RING")) return 0;
    PFNGLBUFFERSTORAGEEXTPROC storage = (PFNGLBUFFERSTORAGEEXTPROC)eglGetProcAddress("glBufferStorageEXT");
    if (!storage) return 0;
    GLbitfield flags = GL_MAP_WRITE_BIT | GL_MAP_PERSISTENT_BIT_EXT | GL_MAP_COHERENT_BIT_EXT;
    GLsizeiptr bytes = (GLsizeiptr)RING_SEGMENTS * RING_SEGMENT_BYTES;
    glGenBuffers(1, &ring_buffer);
    glBindBuffer(GL_COPY_WRITE_BUFFER, ring_buffer);
    storage(GL_COPY_WRITE_BUFFER, bytes, NULL, flags);
    ring_map = (uint8_t *)glMapBufferRange(GL_COPY_WRITE_BUFFER, 0, bytes, flags);
    if (!ring_map) {
        void_log("[gl] streaming ring unavailable (%04X)", glGetError());
        glDeleteBuffers(1, &ring_buffer);
        ring_buffer = 0;
        return 0;
    }
    ring_segment = ring_used = 0;
    ring_state = 1;
    void_log("[gl] streaming ring: %u x %u MiB", RING_SEGMENTS, RING_SEGMENT_BYTES >> 20);
    return 1;
}

/* Room for `bytes` in this frame's segment, 16-byte aligned, or NULL. */
static uint8_t *ring_alloc(uint32_t bytes, uint32_t *offset)
{
    if (!bytes || !ring_ready()) return NULL;
    uint32_t at = (ring_used + 15u) & ~15u;
    if ((uint64_t)at + bytes > RING_SEGMENT_BYTES) return NULL;
    ring_used = at + bytes;
    *offset = ring_segment * RING_SEGMENT_BYTES + at;
    return ring_map + *offset;
}

/* After a frame's last draw: fence its segment, move to the next one and wait
 * for the GPU to finish the frame that used it RING_SEGMENTS frames ago. */
static void ring_frame_end(void)
{
    if (ring_state <= 0) return;
    if (ring_fence[ring_segment]) glDeleteSync(ring_fence[ring_segment]);
    ring_fence[ring_segment] = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
    ring_segment = (ring_segment + 1u) % RING_SEGMENTS;
    ring_used = 0;
    GLsync fence = ring_fence[ring_segment];
    if (!fence) return;
    for (int waits = 0;; ++waits) {
        GLenum result = glClientWaitSync(fence, GL_SYNC_FLUSH_COMMANDS_BIT, 1000000000ull);
        if (result == GL_ALREADY_SIGNALED || result == GL_CONDITION_SATISFIED) break;
        if (result == GL_WAIT_FAILED) { void_log("[gl] streaming ring fence wait failed %04X", glGetError()); break; }
        if (waits < 3) void_log("[gl] streaming ring: GPU still on segment %u after %d s", ring_segment, waits + 1);
    }
    glDeleteSync(fence);
    ring_fence[ring_segment] = 0;
}

static void ring_release(void)
{
    for (unsigned i = 0; i < RING_SEGMENTS; ++i)
        if (ring_fence[i]) { glDeleteSync(ring_fence[i]); ring_fence[i] = 0; }
    if (ring_buffer) {
        glBindBuffer(GL_COPY_WRITE_BUFFER, ring_buffer);
        glUnmapBuffer(GL_COPY_WRITE_BUFFER);
        glDeleteBuffers(1, &ring_buffer);
    }
    ring_buffer = 0;
    ring_map = NULL;
    ring_state = 0;
    ring_segment = ring_used = 0;
}

/* One draw's stream data: into the ring when it has room, else a fresh store. */
static void draw_stream_upload(unsigned stream, uint32_t size, const void *data)
{
    uint32_t at;
    uint8_t *dst = ring_alloc(size, &at);
    if (dst) {
        memcpy(dst, data, size);
        stream_ring[stream] = at;
    } else {
        stream_ring[stream] = UINT32_MAX;
        if (!stream_vbos[stream]) glGenBuffers(1, &stream_vbos[stream]);
        glBindBuffer(GL_COPY_WRITE_BUFFER, stream_vbos[stream]);
        glBufferData(GL_COPY_WRITE_BUFFER, size, data, GL_STREAM_DRAW);
    }
}
static uint32_t enabled_attribs;

/* Sparse pooled meshes need only their referenced vertices. Scratch is bounded
 * independently of the source envelope; every unsupported case keeps the old path. */
#define SPARSE_MAX_INDICES 262144u
#define SPARSE_MAX_BYTES (8u * 1024u * 1024u)
typedef struct { uint32_t raw, dense_plus_one; } sparse_index_entry;
static uint32_t *sparse_indices, *sparse_vertices;
static sparse_index_entry *sparse_hash;
static uint8_t *sparse_data;
static uint32_t sparse_capacity, sparse_hash_capacity, sparse_data_capacity;
/* Spans up to this many vertices use a direct map instead of the hash. */
#define SPARSE_MAX_SPAN (1u << 20)
#define SPARSE_DENSE_BITS 18u
#define SPARSE_DENSE_MASK ((1u << SPARSE_DENSE_BITS) - 1u)
#define SPARSE_GENERATION_MAX (UINT32_MAX >> SPARSE_DENSE_BITS)
_Static_assert(SPARSE_MAX_INDICES <= SPARSE_DENSE_MASK + 1u, "sparse dense index must fit its packed entry");
typedef uint32_t sparse_map_entry;
static sparse_map_entry *sparse_map;
static uint32_t sparse_map_capacity, sparse_map_generation;

/* One entry per vertex of the draw's referenced span, valid when stamped with
 * this draw's generation: nothing is cleared per draw, and neighbouring
 * indices stay neighbours in memory (hashing scattered every lookup into a
 * cache miss). Packing the dense index and stamp halves this hot map's cache
 * footprint. Dense numbers follow first use, exactly as with the hash. */
static int draw_sparse_map(const uint8_t *source, uint32_t unit, uint32_t count, uint32_t base,
    uint32_t first, uint32_t last, uint32_t *unique_count)
{
    uint32_t span = last - first + 1u;
    if (sparse_map_capacity < span) {
        uint32_t capacity = 4096;
        while (capacity < span) capacity *= 2;
        sparse_map_entry *map = calloc(capacity, sizeof *map);
        if (!map) return 0;
        free(sparse_map);
        sparse_map = map; sparse_map_capacity = capacity; sparse_map_generation = 0;
    }
    if (++sparse_map_generation > SPARSE_GENERATION_MAX) {
        memset(sparse_map, 0, (size_t)sparse_map_capacity * sizeof *sparse_map);
        sparse_map_generation = 1;
    }
    uint32_t generation = sparse_map_generation << SPARSE_DENSE_BITS, unique = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t raw;
        if (unit == 4) memcpy(&raw, source + (size_t)i * 4u, 4);
        else { uint16_t value; memcpy(&value, source + (size_t)i * 2u, 2); raw = value; }
        int64_t vertex = (int64_t)raw + (int32_t)base;
        if (vertex < first || vertex > last) return 0;
        sparse_map_entry *e = &sparse_map[(uint32_t)vertex - first];
        /* Subtraction extracts the dense index only when this draw's stamp matches. */
        uint32_t dense = *e - generation;
        if (dense > SPARSE_DENSE_MASK) {
            dense = unique;
            *e = generation | unique;
            sparse_vertices[unique++] = (uint32_t)vertex;
        }
        sparse_indices[i] = dense;
    }
    *unique_count = unique;
    return 1;
}

static int draw_sparse_indices(d3d_buffer *ib, uint32_t start_index, uint32_t count,
    uint32_t base, uint32_t first, uint32_t last, uint32_t *unique_count)
{
    if (!ib || !count || count > SPARSE_MAX_INDICES || first > last) return 0;
    uint32_t unit = ib->format == 102 ? 4u : 2u;
    uint64_t begin = (uint64_t)start_index * unit, end = begin + (uint64_t)count * unit;
    if (end > ib->size) return 0;
    uint32_t capacity = 256;
    while (capacity < count) capacity *= 2;
    if (sparse_capacity < capacity) {
        uint32_t *work = realloc(sparse_indices, (size_t)capacity * 2u * sizeof *work);
        if (!work) return 0;
        sparse_indices = work; sparse_capacity = capacity; sparse_vertices = work + capacity;
    }
    if ((uint64_t)last - first < SPARSE_MAX_SPAN)
        return draw_sparse_map((const uint8_t *)GPTR(ib->shadow) + begin, unit, count, base, first, last, unique_count);
    uint32_t slots = capacity * 2u;
    if (sparse_hash_capacity < slots) {
        sparse_index_entry *hash = realloc(sparse_hash, (size_t)slots * sizeof *hash);
        if (!hash) return 0;
        sparse_hash = hash; sparse_hash_capacity = slots;
    }
    memset(sparse_hash, 0, (size_t)slots * sizeof *sparse_hash);
    const uint8_t *source = (const uint8_t *)GPTR(ib->shadow) + begin;
    uint32_t unique = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t raw;
        if (unit == 4) memcpy(&raw, source + (size_t)i * 4u, 4);
        else { uint16_t value; memcpy(&value, source + (size_t)i * 2u, 2); raw = value; }
        int64_t vertex = (int64_t)raw + (int32_t)base;
        if (vertex < first || vertex > last) return 0;
        uint32_t hash = raw ^ (raw >> 16);
        hash *= 0x7FEB352Du; hash ^= hash >> 15; hash *= 0x846CA68Bu; hash ^= hash >> 16;
        uint32_t at = hash & (slots - 1u), probes = 0;
        while (sparse_hash[at].dense_plus_one && sparse_hash[at].raw != raw) {
            if (++probes > 64) return 0;
            at = (at + 1u) & (slots - 1u);
        }
        if (!sparse_hash[at].dense_plus_one) {
            sparse_hash[at] = (sparse_index_entry){raw, unique + 1u};
            sparse_vertices[unique++] = (uint32_t)vertex;
        }
        sparse_indices[i] = sparse_hash[at].dense_plus_one - 1u;
    }
    *unique_count = unique;
    return 1;
}

static int draw_sparse_gather(d3d_buffer *b, uint32_t offset, uint32_t stride, uint32_t attr_end,
    uint32_t unique, uint8_t *out, uint32_t out_bytes)
{
    if (!b || !out || !unique || !sparse_vertices || unique > sparse_capacity || !stride || !attr_end || attr_end > stride ||
        (uint64_t)(unique - 1u) * stride + attr_end != out_bytes) return 0;
    const uint8_t *shadow = (const uint8_t *)GPTR(b->shadow);
    /* Fixed-size pieces inline; a memcpy call per small vertex dominated. */
    uint32_t wide = attr_end & ~15u, words = attr_end & 12u, tail = attr_end & 3u;
    for (uint32_t i = 0; i < unique; ++i) {
        uint64_t source = (uint64_t)offset + (uint64_t)sparse_vertices[i] * stride;
        if (source + attr_end > b->size) return 0;
        const uint8_t *from = shadow + source;
        uint8_t *to = out + (size_t)i * stride;
        uint32_t k = 0;
        for (; k < wide; k += 16) memcpy(to + k, from + k, 16);
        for (uint32_t w = 0; w < words; w += 4, k += 4) memcpy(to + k, from + k, 4);
        for (uint32_t t = 0; t < tail; ++t, ++k) to[k] = from[k];
    }
    return 1;
}

static uint32_t draw_sparse_prepare(d3d_device *d, uint32_t start_index, uint32_t count, uint32_t base,
    uint32_t first, uint32_t last, uint32_t instances, const uint32_t ends[16], const uint32_t ranges[16],
    uint32_t bytes[16], uint32_t offsets[16])
{
    if (!count || count > SPARSE_MAX_INDICES || (uint64_t)last - first + 1u <= (uint64_t)count * 2u) return 0;
    uint64_t old_bytes = 0, estimate = (uint64_t)count * 4u;
    for (unsigned stream = 0; stream < 16; ++stream) if (ends[stream]) {
        if (instances && (d->st.stream_freq[stream] & 0x80000000u)) continue;
        d3d_buffer *b = (d3d_buffer *)d->st.streams[stream];
        uint32_t stride = d->st.stream_stride[stream];
        if (!b || !stride || stride > INT32_MAX || ends[stream] > stride) return 0;
        estimate += (uint64_t)(count - 1u) * stride + ends[stream];
        if (b->dirty_pages) old_bytes += ranges[stream];
    }
    if (old_bytes <= estimate * 2u || estimate > SPARSE_MAX_BYTES) return 0;
    uint32_t unique;
    if (!draw_sparse_indices((d3d_buffer *)d->st.indices, start_index, count, base, first, last, &unique)) return 0;
    uint64_t total = 0;
    for (unsigned stream = 0; stream < 16; ++stream) if (ends[stream]) {
        if (instances && (d->st.stream_freq[stream] & 0x80000000u)) continue;
        uint64_t length = (uint64_t)(unique - 1u) * d->st.stream_stride[stream] + ends[stream];
        total = (total + 15u) & ~(uint64_t)15u;      /* each stream's attributes stay aligned in the ring */
        if (total + length > SPARSE_MAX_BYTES) return 0;
        offsets[stream] = (uint32_t)total; bytes[stream] = (uint32_t)length; total += length;
    }
    if (!total) return 0;
    /* Gather straight into this frame's ring segment when it has room; a
     * failed gather only leaves unused ring bytes behind. */
    uint32_t ring_at;
    uint8_t *dest = ring_alloc((uint32_t)total, &ring_at);
    sparse_ring_at = dest ? ring_at : UINT32_MAX;
    if (!dest) {
        if (sparse_data_capacity < total) {
            uint32_t capacity = 256;
            while (capacity < total) capacity *= 2;
            uint8_t *data = realloc(sparse_data, capacity);
            if (!data) return 0;
            sparse_data = data; sparse_data_capacity = capacity;
        }
        dest = sparse_data;
    }
    /* Finish every gather before GL changes, so allocation/range failure is a clean fallback. */
    for (unsigned stream = 0; stream < 16; ++stream) if (bytes[stream])
        if (!draw_sparse_gather((d3d_buffer *)d->st.streams[stream], d->st.stream_offset[stream],
                d->st.stream_stride[stream], ends[stream], unique, dest + offsets[stream], bytes[stream])) return 0;
    ++vb_sparse_calls; vb_sparse_saved += old_bytes - total;
    return unique;
}

/* A compact immutable data store per draw avoids both full pooled-buffer
 * copies and writes into storage still consumed by queued draws. Each stream
 * has its own object, so orphaning one cannot erase another in the same draw. */
static void draw_buffer_upload(GLuint *buffer, uint32_t size, const void *data)
{
    if (!*buffer) glGenBuffers(1, buffer);
    glBindBuffer(GL_COPY_WRITE_BUFFER, *buffer);
    glBufferData(GL_COPY_WRITE_BUFFER, size, data, GL_STREAM_DRAW);
}

static GLenum gl_mode(uint32_t p)
{
    switch (p) {
    case 1: return GL_POINTS;
    case 2: return GL_LINES;
    case 3: return GL_LINE_STRIP;
    case 5: return GL_TRIANGLE_STRIP;
    case 6: return GL_TRIANGLE_FAN;
    default: return GL_TRIANGLES;
    }
}

static uint64_t swap_ns;      /* time in eglSwapBuffers: vsync and the GPU catching up */

int d3d_gl_draw(d3d_device *d, uint32_t primitive, uint32_t start_vertex, uint32_t vertex_count,
    uint32_t prim_count, int indexed, uint32_t base_vertex, uint32_t start_index, uint32_t min_index,
    const void *up_vertices, uint32_t up_stride, const void *up_indices, int up_index32)
{
    (void)prim_count; (void)min_index;
    ++draw_calls;
    d3d_shader *vs = (d3d_shader *)d->st.vs, *ps = (d3d_shader *)d->st.ps;
    /* POSITIONT vertices are already transformed: D3D9 runs no vertex shader
     * for them (Wine: use_vs() is false for a position_transformed
     * declaration), only the fixed-function pass-through. */
    if (vs) {
        d3d_decl *decl = (d3d_decl *)d->st.decl;
        for (int i = 0; decl && i < decl->count; ++i)
            if (decl->elements[i].usage == 9 && decl->elements[i].usage_index == 0 && decl->elements[i].type < 17) {
                vs = NULL;
                break;
            }
    }
    if (ui_quad_depth) ui_promote(d);
    d3d_gl_bind_targets(d);
    d3d_gl_apply_state(d);
    int attr_count;
    const int *attr_usage, *attr_index, *ps_types, *vs_types;
    uint32_t ps_samplers, vs_samplers;
    /* No shaders: the generated fixed-function pipeline. One shader: the
     * other half is generated inside d3d_shader_bind2. */
    if (!vs && !ps) {
        static int ff_usage[16], ff_index[16];
        if (!d3d_ff_bind(d, &attr_count, ff_usage, ff_index, &ps_samplers)) return 0;
        attr_usage = ff_usage;
        attr_index = ff_index;
        vs_samplers = 0;
    } else {
        if (!d3d_shader_bind2(d, vs, ps, bgra_of, &attr_count, &attr_usage, &attr_index, &ps_samplers, &vs_samplers,
                              &ps_types, &vs_types))
            return 0;
        float hx = d->st.viewport[2] ? 1.0f / (float)d->st.viewport[2] : 0.0f;
        float hy = d->st.viewport[3] ? 1.0f / (float)d->st.viewport[3] : 0.0f;
        int alpha_func = d->st.rs[15] ? (int)d->st.rs[25] : 8;
        d3d_shader_upload(d, hx, hy, alpha_func, (float)(d->st.rs[24] & 0xFF));
    }
    for (int s = 0; s < 16; ++s) if (ps_samplers & (1u << s)) bind_texture(d, s, (GLuint)s);
    for (int s = 0; s < 4; ++s) if (vs_samplers & (1u << s)) bind_texture(d, 16 + s, (GLuint)(16 + s));
    if (depth_trace_remaining) depth_trace_draw(d, ps_samplers, vs_samplers, shader_tag(vs), shader_tag(ps));
    /* UP data */
    uint32_t up_bytes = 0;
    if (up_vertices) {
        uint32_t vertices = vertex_count;
        if (indexed && up_indices) {
            uint32_t max = 0;
            for (uint32_t i = 0; i < vertex_count; ++i) {
                uint32_t v = up_index32 ? ((const uint32_t *)up_indices)[i] : ((const uint16_t *)up_indices)[i];
                if (v > max) max = v;
            }
            vertices = max + 1;
        }
        up_bytes = vertices * up_stride;
        if (!up_vbo) glGenBuffers(1, &up_vbo);
        glBindBuffer(GL_ARRAY_BUFFER, up_vbo);
        glBufferData(GL_ARRAY_BUFFER, up_bytes, up_vertices, GL_STREAM_DRAW);
    }
    uint32_t instances = (d->st.stream_freq[0] & 0x40000000u) ? (d->st.stream_freq[0] & 0x3FFFFFFFu) : 0;
    uint32_t first_vertex = 0, last_vertex = 0;
    int vertex_bounds = draw_vertex_bounds((d3d_buffer *)d->st.indices, up_indices, up_index32,
        start_vertex, vertex_count, indexed, base_vertex, start_index, &first_vertex, &last_vertex);
    uint32_t stream_end[16] = {0}, stream_lo[16] = {0}, stream_bytes[16] = {0};
    int local_streams = 0;
    for (int i = 0; i < attr_count; ++i) {
        const d3d_vertex_element *e = find_element(d, attr_usage[i], attr_index[i]);
        if (!e || e->stream >= 16) continue;
        d3d_buffer *b = (d3d_buffer *)d->st.streams[e->stream];
        if (!b) continue;
        uint32_t end = e->offset + attr_bytes[e->type];
        if (end > stream_end[e->stream]) stream_end[e->stream] = end;
        if (b->dirty_pages) local_streams = 1;
    }
    int32_t draw_base = (int32_t)base_vertex;
    local_streams = local_streams && !up_vertices && !up_indices && vertex_bounds &&
        draw_rebase(base_vertex, first_vertex, indexed, &draw_base);
    if (local_streams) for (unsigned stream = 0; stream < 16; ++stream) if (stream_end[stream]) {
        d3d_buffer *b = (d3d_buffer *)d->st.streams[stream];
        int instanced = instances && (d->st.stream_freq[stream] & 0x80000000u);
        if (!draw_stream_range(b->size, d->st.stream_offset[stream], d->st.stream_stride[stream], stream_end[stream],
            instanced ? 0 : first_vertex, instanced ? instances - 1u : last_vertex,
            &stream_lo[stream], &stream_bytes[stream])) { local_streams = 0; break; }
    }
    uint32_t sparse_bytes[16] = {0}, sparse_offsets[16] = {0};
    uint32_t sparse_count = local_streams && indexed ?
        draw_sparse_prepare(d, start_index, vertex_count, base_vertex, first_vertex, last_vertex,
                            instances, stream_end, stream_bytes, sparse_bytes, sparse_offsets) : 0;
    if (sparse_count) draw_base = 0;
    if (local_streams) memset(stream_ring, 0xFF, sizeof stream_ring);
    if (!local_streams) draw_base = (int32_t)base_vertex;
    else for (unsigned stream = 0; stream < 16; ++stream) if (stream_end[stream]) {
        d3d_buffer *b = (d3d_buffer *)d->st.streams[stream];
        if (sparse_count && sparse_bytes[stream]) {
            if (sparse_ring_at != UINT32_MAX) stream_ring[stream] = sparse_ring_at + sparse_offsets[stream];
            else draw_stream_upload(stream, sparse_bytes[stream], sparse_data + sparse_offsets[stream]);
            ++vb_upload_calls;
            vb_upload_bytes += sparse_bytes[stream];
            vb_upload_frame_bytes += sparse_bytes[stream];
        } else if (b->dirty_pages) {
            draw_stream_upload(stream, stream_bytes[stream], (const uint8_t *)GPTR(b->shadow) + stream_lo[stream]);
            ++vb_upload_calls;
            vb_upload_bytes += stream_bytes[stream];
            vb_upload_frame_bytes += stream_bytes[stream];

        }
    }
    uint32_t want = 0;
    if (!attr_cache_ready) {
        for (int i = 0; i < 16; ++i) attr_cache[i].buffer = FB_UNKNOWN;
        attr_cache_ready = 1;
    }
    for (int i = 0; i < attr_count; ++i) {
        const d3d_vertex_element *e = find_element(d, attr_usage[i], attr_index[i]);
        if (!e) {
            if (attr_usage[i] == 10) glVertexAttrib4f((GLuint)i, 1, 1, 1, 1);
            else glVertexAttrib4f((GLuint)i, 0, 0, 0, 1);
            continue;
        }
        const attr_format *f = &attr_formats[e->type];
        uintptr_t offset;
        GLsizei stride;
        GLuint buffer;
        if (up_vertices && e->stream == 0) {
            buffer = up_vbo;
            offset = e->offset;
            stride = (GLsizei)up_stride;
        } else {
            d3d_buffer *b = (d3d_buffer *)d->st.streams[e->stream];
            if (!b) { glVertexAttrib4f((GLuint)i, 0, 0, 0, 1); continue; }
            int instanced = instances && (d->st.stream_freq[e->stream] & 0x80000000u);
            if (local_streams && (b->dirty_pages || (sparse_count && !instanced))) {
                if (stream_ring[e->stream] != UINT32_MAX) {
                    buffer = ring_buffer; offset = (uintptr_t)stream_ring[e->stream] + e->offset;
                } else {
                    buffer = stream_vbos[e->stream]; offset = e->offset;
                }
            } else {
                buffer_flush_vertices(b, (uint64_t)d->st.stream_offset[e->stream] + e->offset,
                    d->st.stream_stride[e->stream], attr_bytes[e->type],
                    instanced ? 0 : first_vertex, instanced ? instances - 1u : last_vertex,
                    instanced || vertex_bounds);
                buffer = b->gl;
                offset = (uintptr_t)d->st.stream_offset[e->stream] + e->offset;
                if (local_streams && !instanced) offset += (uintptr_t)first_vertex * d->st.stream_stride[e->stream];
            }
            stride = (GLsizei)d->st.stream_stride[e->stream];
        }
        attr_state *c = &attr_cache[i];
        if (c->buffer != buffer || c->size != f->size || c->type != f->type || c->norm != f->norm || c->stride != stride ||
            c->offset != offset) {
            glBindBuffer(GL_ARRAY_BUFFER, buffer);
            glVertexAttribPointer((GLuint)i, f->size, f->type, f->norm, stride, (const void *)offset);
            c->buffer = buffer; c->size = f->size; c->type = f->type; c->norm = f->norm; c->stride = stride; c->offset = offset;
        }
        GLuint divisor = (instances && (d->st.stream_freq[e->stream] & 0x80000000u)) ? 1u : 0u;
        if (c->divisor != divisor) { glVertexAttribDivisor((GLuint)i, divisor); c->divisor = divisor; }
        want |= 1u << i;
    }
    for (int i = 0; i < 16; ++i) {
        uint32_t bit = 1u << i;
        if ((want & bit) && !(enabled_attribs & bit)) glEnableVertexAttribArray((GLuint)i);
        if (!(want & bit) && (enabled_attribs & bit)) glDisableVertexAttribArray((GLuint)i);
    }
    enabled_attribs = want;
    GLuint trace_query = 0;
    if (tracing(d)) {
        /* The first vertex as the draw reads it, and the transform constants. */
        const d3d_vertex_element *pe = find_element(d, 0, 0);
        uint32_t index = start_vertex;
        if (indexed && !up_indices && d->st.indices) {
            d3d_buffer *ib = (d3d_buffer *)d->st.indices;
            index = ib->format == 102 ? MEM32(ib->shadow + start_index * 4u) : MEM16(ib->shadow + start_index * 2u);
            index += base_vertex;
        }
        float pos[4] = { 0, 0, 0, 0 };
        if (pe && pe->type <= 3) {
            const uint8_t *vb = NULL;
            uint32_t stride = 0;
            if (up_vertices && pe->stream == 0) { vb = (const uint8_t *)up_vertices; stride = up_stride; }
            else if (d->st.streams[pe->stream]) {
                d3d_buffer *b = (d3d_buffer *)d->st.streams[pe->stream];
                vb = (const uint8_t *)GPTR(b->shadow + d->st.stream_offset[pe->stream]);
                stride = d->st.stream_stride[pe->stream];
            }
            if (vb) memcpy(pos, vb + (size_t)index * stride + pe->offset, 4u * (pe->type + 1u));
        }
        const float *c = &d->st.vs_f[0][0];
        void_log("[trace]   v%u pos (%g %g %g %g) usage %u type %d; c0 (%g %g %g %g) c1 (%g %g %g %g) c2 (%g %g %g %g) c3 (%g %g %g %g)",
            index, pos[0], pos[1], pos[2], pos[3], pe ? pe->usage : 99, pe ? pe->type : -1, c[0], c[1], c[2], c[3], c[4], c[5],
            c[6], c[7], c[8], c[9], c[10], c[11], c[12], c[13], c[14], c[15]);
        char tex[256];
        size_t tn = 0;
        tex[0] = 0;
        for (int s2 = 0; s2 < 8; ++s2) {
            d3d_texture *t = (d3d_texture *)d->st.textures[s2];
            if (t && (ps_samplers & (1u << s2)))
                tn += (size_t)snprintf(tex + tn, sizeof tex - tn, " s%d=%ux%u/%u", s2, t->width, t->height, t->format);
        }
        uint32_t ck = (g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1);
        {
            d3d_decl *dd = (d3d_decl *)d->st.decl;
            char dl[256];
            size_t dn = 0;
            dl[0] = 0;
            for (int i = 0; dd && i < dd->count && dn < sizeof dl - 24; ++i)
                dn += (size_t)snprintf(dl + dn, sizeof dl - dn, " %u.%u:t%u@%u", dd->elements[i].usage, dd->elements[i].usage_index,
                    dd->elements[i].type, dd->elements[i].offset);
            void_log("[trace]   decl%s (fvf %X, set vs %08X)", dl, d->st.fvf, shader_tag(d->st.vs));
        }
        void_log("[trace] draw from %08X prim %u count %u%s vs %08X ps %08X%s blend %u(%u,%u) z %u/%u/%u cull %u cw %X vp %u,%u %ux%u%s",
            g_icall_from[ck], primitive, vertex_count, indexed ? " indexed" : "", shader_tag(vs), shader_tag(ps), (!vs && !ps) ? " (ff)" : "",
            d->st.rs[27], d->st.rs[19], d->st.rs[20], d->st.rs[7], d->st.rs[14], d->st.rs[23], d->st.rs[22], d->st.rs[168],
            d->st.viewport[0], d->st.viewport[1], d->st.viewport[2], d->st.viewport[3], tex);
    }
    if (tracing(d)) {
        static int textures_traced;
        if (getenv("VOID_TRACE_TEXTURES") && textures_traced < 24) {
            d3d_texture *tt = (d3d_texture *)d->st.textures[0];
            if (tt && tt->rtype == D3DRTYPE_TEXTURE) {
                ++textures_traced;
                trace_dump(d, (d3d_surface *)void_com_host(d3d_texture_surface(tt, 0, 0)), "stage 0 texture");
            }
        }
        if (vs || ps) d3d_shader_trace();
        if (!vs && !ps) {
            /* Fixed function: the declaration, stage 0 and the first vertices. */
            d3d_decl *decl = (d3d_decl *)d->st.decl;
            char line[512];
            size_t n = 0;
            for (int i = 0; decl && i < decl->count && n < sizeof line - 40; ++i)
                n += (size_t)snprintf(line + n, sizeof line - n, " [s%u+%u t%u u%u.%u]", decl->elements[i].stream,
                    decl->elements[i].offset, decl->elements[i].type, decl->elements[i].usage, decl->elements[i].usage_index);
            const uint32_t *t0 = d->st.tss[0], *t1 = d->st.tss[1];
            void_log("[trace]   ff decl%s fvf %X; ts0 op %u(%X,%X) a %u(%X,%X) tci %X ttf %X; ts1 op %u; lighting %u tf %08X",
                line, d->st.fvf, t0[1], t0[2], t0[3], t0[4], t0[5], t0[6], t0[11], t0[24], t1[1], d->st.rs[137], d->st.rs[60]);
            const uint8_t *vb = NULL;
            uint32_t stride = 0;
            if (up_vertices) { vb = (const uint8_t *)up_vertices; stride = up_stride; }
            else if (d->st.streams[0]) {
                d3d_buffer *b = (d3d_buffer *)d->st.streams[0];
                vb = (const uint8_t *)GPTR(b->shadow + d->st.stream_offset[0]);
                stride = d->st.stream_stride[0];
            }
            static int textures_dumped;
            d3d_texture *t0tex = (d3d_texture *)d->st.textures[0];
            if (t0tex && textures_dumped++ < 2 && t0tex->rtype == D3DRTYPE_TEXTURE)
                trace_dump(d, (d3d_surface *)void_com_host(d3d_texture_surface(t0tex, 0, 0)), "ff stage 0 texture");
            for (uint32_t v = 0; vb && v < 4 && v < vertex_count; ++v) {
                const uint32_t *w = (const uint32_t *)(vb + (size_t)(start_vertex + v) * stride);
                float f[8];
                memcpy(f, w, sizeof f);
                void_log("[trace]   v%u: %g %g %g %g | %08X %08X | %g %g", v, f[0], f[1], f[2], f[3], w[4], w[5], f[6], f[7]);
            }
        }
        GLint view[4], scissor[4], fb = 0, status = 0;
        GLfloat range[2];
        glGetIntegerv(GL_VIEWPORT, view);
        glGetIntegerv(GL_SCISSOR_BOX, scissor);
        glGetFloatv(GL_DEPTH_RANGE, range);
        glGetIntegerv(GL_DRAW_FRAMEBUFFER_BINDING, &fb);
        status = (GLint)glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
        void_log("[trace]   gl viewport %d,%d %dx%d depth %g..%g scissor %s %d,%d %dx%d cull %d depth %d stencil %d blend %d fb %d status %04X",
            view[0], view[1], view[2], view[3], range[0], range[1], glIsEnabled(GL_SCISSOR_TEST) ? "on" : "off", scissor[0],
            scissor[1], scissor[2], scissor[3], glIsEnabled(GL_CULL_FACE), glIsEnabled(GL_DEPTH_TEST), glIsEnabled(GL_STENCIL_TEST),
            glIsEnabled(GL_BLEND), fb, status);
        GLint program = 0;
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        GLint af = glGetUniformLocation((GLuint)program, "vpAlphaFunc"), ar = glGetUniformLocation((GLuint)program, "vpAlphaRef");
        GLint afv = -1;
        GLfloat arv = -1;
        if (af >= 0) glGetUniformiv((GLuint)program, af, &afv);
        if (ar >= 0) glGetUniformfv((GLuint)program, ar, &arv);
        void_log("[trace]   alpha test rs %u func %u ref %u; program vpAlphaFunc %d vpAlphaRef %g", d->st.rs[15], d->st.rs[25],
            d->st.rs[24], afv, arv);
        if (getenv("VOID_DEBUG_NOALPHA") && af >= 0) glUniform1i(af, 8);
        raster_state_valid = 0;   /* Tracing can override the D3D raster state. */
        if (getenv("VOID_DEBUG_NODEPTH")) glDisable(GL_DEPTH_TEST);
        if (getenv("VOID_DEBUG_NOCULL")) glDisable(GL_CULL_FACE);
        if (getenv("VOID_TRACE_DIFF")) {
            free(trace_before);
            trace_before = NULL;
            if (!trace_read_rt0(d, &trace_before, &trace_before_w, &trace_before_h)) { free(trace_before); trace_before = NULL; }
        }
        glGenQueries(1, &trace_query);
        glBeginQuery(GL_ANY_SAMPLES_PASSED, trace_query);
    }
    GLenum mode = gl_mode(primitive);
    if (indexed) {
        if (up_indices) {
            if (!up_ibo) glGenBuffers(1, &up_ibo);
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, up_ibo);
            elem_buffer = up_ibo;
            glBufferData(GL_ELEMENT_ARRAY_BUFFER, vertex_count * (up_index32 ? 4u : 2u), up_indices, GL_STREAM_DRAW);
            glDrawElements(mode, (GLsizei)vertex_count, up_index32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, NULL);
        } else {
            d3d_buffer *ib = (d3d_buffer *)d->st.indices;
            if (!ib) { void_log("[gl] indexed draw without an index buffer"); return 0; }
            uint64_t index_lo = (uint64_t)start_index * (ib->format == 102 ? 4u : 2u);
            uint64_t index_hi = index_lo + (uint64_t)vertex_count * (ib->format == 102 ? 4u : 2u);
            GLuint element = ib->gl;
            int compact = sparse_count || (ib->dirty_pages && index_hi <= ib->size);
            uint32_t compact_at = 0;
            if (compact) {
                const void *data = sparse_count ? (const void *)sparse_indices : (const uint8_t *)GPTR(ib->shadow) + index_lo;
                uint32_t size = sparse_count ? vertex_count * 4u : (uint32_t)(index_hi - index_lo);
                uint8_t *dst = ring_alloc(size, &compact_at);
                if (dst) {
                    memcpy(dst, data, size);
                    element = ring_buffer;
                } else {
                    compact_at = 0;
                    draw_buffer_upload(&up_ibo, size, data);
                    element = up_ibo;
                }
            } else if (index_hi <= ib->size) d3d_buffer_flush_range(ib, (uint32_t)index_lo, (uint32_t)index_hi);
            else d3d_buffer_flush(ib);
            if (elem_buffer != element) { glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, element); elem_buffer = element; }
            int i32 = sparse_count || ib->format == 102;
            const void *ptr = (const void *)(uintptr_t)(compact ? compact_at : start_index * (i32 ? 4u : 2u));
            if (instances)
                glDrawElementsInstancedBaseVertex(mode, (GLsizei)vertex_count, i32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, ptr,
                    (GLsizei)instances, draw_base);
            else if (vertex_bounds) {
                /* GL ranges describe raw indices, before base-vertex rebasing. */
                GLuint lo = sparse_count ? 0 : first_vertex - base_vertex;
                GLuint hi = sparse_count ? sparse_count - 1u : last_vertex - base_vertex;
                glDrawRangeElementsBaseVertex(mode, lo, hi, (GLsizei)vertex_count,
                    i32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, ptr, draw_base);
            }
            else
                glDrawElementsBaseVertex(mode, (GLsizei)vertex_count, i32 ? GL_UNSIGNED_INT : GL_UNSIGNED_SHORT, ptr, draw_base);
        }
    } else {
        GLint draw_start = local_streams ? 0 : (GLint)start_vertex;
        if (instances) glDrawArraysInstanced(mode, draw_start, (GLsizei)vertex_count, (GLsizei)instances);
        else glDrawArrays(mode, draw_start, (GLsizei)vertex_count);
    }
    /* GL errors stay set until read: present checks once per frame, a traced
     * draw at once (a per-draw glGetError is a driver entry ~430 times a frame). */
    GLenum e = trace_query ? glGetError() : GL_NO_ERROR;
    if (e) {
        static int warned;
        if (warned++ < 20) void_log("[gl] draw error %04X (prim %u count %u indexed %d)", e, primitive, vertex_count, indexed);
    }
    if (trace_query) {
        glEndQuery(GL_ANY_SAMPLES_PASSED);
        GLuint passed = 0;
        glGetQueryObjectuiv(trace_query, GL_QUERY_RESULT, &passed);
        glDeleteQueries(1, &trace_query);
        GLint program = 0;
        glGetIntegerv(GL_CURRENT_PROGRAM, &program);
        void_log("[trace]   samples passed: %s (program %d, error %04X)", passed ? "yes" : "NONE", program, e);
        uint8_t *after = NULL;
        uint32_t w = 0, h = 0;
        if (trace_before && trace_read_rt0(d, &after, &w, &h) && w == trace_before_w && h == trace_before_h) {
            uint32_t changed = 0, x0 = w, y0 = h, x1 = 0, y1 = 0;
            double sum_before = 0, sum_after = 0;
            for (uint32_t y = 0; y < h; ++y)
                for (uint32_t x = 0; x < w; ++x) {
                    const uint8_t *a = trace_before + 4 * ((size_t)y * w + x), *b = after + 4 * ((size_t)y * w + x);
                    if (a[0] != b[0] || a[1] != b[1] || a[2] != b[2]) {
                        ++changed;
                        sum_before += a[0] + a[1] + a[2];
                        sum_after += b[0] + b[1] + b[2];
                        if (x < x0) x0 = x;
                        if (y < y0) y0 = y;
                        if (x > x1) x1 = x;
                        if (y > y1) y1 = y;
                    }
                }
            if (changed)
                void_log("[trace]   changed %u px in (%u,%u)-(%u,%u), mean rgb %.1f -> %.1f", changed, x0, y0, x1, y1,
                    sum_before / (3.0 * changed), sum_after / (3.0 * changed));
            else
                void_log("[trace]   changed nothing");
        }
        free(after);
    }
    return 1;
}

/* ---------------------------------------------------------------- clear */
void d3d_gl_clear(d3d_device *d, uint32_t count, uint32_t rects, uint32_t flags, uint32_t color, float z, uint32_t stencil)
{
    raster_state_valid = 0;
    d3d_gl_bind_targets(d);
    if (tracing(d)) void_log("[trace] clear flags %X color %08X z %g stencil %u rects %u", flags, color, z, stencil, count);
    GLbitfield mask = 0;
    if ((flags & 1u) && d->rt[0]) {
        mask |= GL_COLOR_BUFFER_BIT;
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        for (int i = 1; i < 4; ++i) glColorMaski((GLuint)i, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glClearColor(((color >> 16) & 255) / 255.0f, ((color >> 8) & 255) / 255.0f, (color & 255) / 255.0f, (color >> 24) / 255.0f);
    }
    if ((flags & 2u) && d->ds) { mask |= GL_DEPTH_BUFFER_BIT; glDepthMask(GL_TRUE); glClearDepthf(z); }
    if ((flags & 4u) && d->ds && d->ds->fmt && d->ds->fmt->stencil) { mask |= GL_STENCIL_BUFFER_BIT; glStencilMask(0xFF); glClearStencil((GLint)stencil); }
    if (!mask) return;
    /* The cleared area is the viewport, narrowed by the scissor and rects. */
    int vx = (int)d->st.viewport[0], vy = (int)d->st.viewport[1];
    int vx2 = vx + (int)d->st.viewport[2], vy2 = vy + (int)d->st.viewport[3];
    if (d->st.rs[174]) {
        int sx = (int)d->st.scissor[0], sy = (int)d->st.scissor[1];
        int sx2 = sx + (int)d->st.scissor[2], sy2 = sy + (int)d->st.scissor[3];
        if (sx > vx) vx = sx;
        if (sy > vy) vy = sy;
        if (sx2 < vx2) vx2 = sx2;
        if (sy2 < vy2) vy2 = sy2;
    }
    glEnable(GL_SCISSOR_TEST);
    if (!count || !rects) {
        if (vx2 > vx && vy2 > vy) {
            ui_scissor(d, vx, vy, vx2 - vx, vy2 - vy);
            glClear(mask);
        }
    } else {
        for (uint32_t i = 0; i < count; ++i) {
            int x1 = (int)MEM32(rects + 16 * i), y1 = (int)MEM32(rects + 16 * i + 4);
            int x2 = (int)MEM32(rects + 16 * i + 8), y2 = (int)MEM32(rects + 16 * i + 12);
            if (x1 < vx) x1 = vx;
            if (y1 < vy) y1 = vy;
            if (x2 > vx2) x2 = vx2;
            if (y2 > vy2) y2 = vy2;
            if (x2 <= x1 || y2 <= y1) continue;
            ui_scissor(d, x1, y1, x2 - x1, y2 - y1);
            glClear(mask);
        }
    }
    glDisable(GL_SCISSOR_TEST);
}

/* -------------------------------------------------------- blits and reads */
void d3d_gl_blit(d3d_surface *src, const uint32_t *sr, d3d_surface *dst, const uint32_t *dr, uint32_t filter)
{
    raster_state_valid = 0;
    if (g_d3d_device && tracing(g_d3d_device)) {
        GLboolean cm[4];
        glGetBooleanv(GL_COLOR_WRITEMASK, cm);
        void_log("[trace] blit %ux%u fmt %u (%u,%u,%u,%u) -> %ux%u fmt %u (%u,%u,%u,%u) colour mask was %d%d%d%d", src->width,
            src->height, src->format, sr[0], sr[1], sr[2], sr[3], dst->width, dst->height, dst->format, dr[0], dr[1], dr[2], dr[3],
            cm[0], cm[1], cm[2], cm[3]);
        trace_dump(g_d3d_device, src, "blit source");
    }
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    int depth = src->fmt && src->fmt->depth;
    GLenum attachment = depth ? depth_attachment(src) : GL_COLOR_ATTACHMENT0;
    /* A destination the main framebuffer holds is written through it: Mali
     * keeps a clear of that framebuffer pending as the load operation of
     * its render pass and resolves it when the pass ends, after - and over -
     * writes made through other framebuffers (Mali-G76 r26p0). */
    d3d_device *dev = g_d3d_device;
    int slot = -1;
    if (dev) {
        if (depth) slot = dev->ds == dst ? 4 : -1;
        else for (int i = 0; i < 4; ++i) if (dev->rt[i] == dst) slot = i;
    }
    uint32_t source_rect[4], target_rect[4];
    d3d_surface *source = dev ? ui_surface(dev, src) : src, *target = dev ? ui_surface(dev, dst) : dst;
    if (source != src) {
        for (int i = 0; i < 4; ++i) source_rect[i] = (uint32_t)lround((double)(int32_t)sr[i] *
            (i & 1 ? (double)source->height / src->height : (double)source->width / src->width));
        sr = source_rect;
    }
    if (target != dst) {
        for (int i = 0; i < 4; ++i) target_rect[i] = (uint32_t)lround((double)(int32_t)dr[i] *
            (i & 1 ? (double)target->height / dst->height : (double)target->width / dst->width));
        dr = target_rect;
    }
    src = source; dst = target;
    if (slot >= 0) {
        d3d_gl_bind_targets(dev);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, fbo);
        if (slot < 4) {
            GLenum bufs[4] = { GL_NONE, GL_NONE, GL_NONE, GL_NONE };
            bufs[slot] = GL_COLOR_ATTACHMENT0 + (GLenum)slot;
            glDrawBuffers(slot + 1, bufs);
            fb_buf_count = -1;
        }
    } else {
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, draw_fbo);
        attach(GL_DRAW_FRAMEBUFFER, depth ? depth_attachment(dst) : GL_COLOR_ATTACHMENT0, dst);
    }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    attach(GL_READ_FRAMEBUFFER, attachment, src);
    glDisable(GL_SCISSOR_TEST);
    /* StretchRect ignores the write masks; some GL drivers apply them to
     * blits. The next draw re-applies the D3D masks. */
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glDepthMask(GL_TRUE);
    glStencilMask(0xFF);
    GLbitfield mask = depth ? (GL_DEPTH_BUFFER_BIT | (src->fmt->stencil ? GL_STENCIL_BUFFER_BIT : 0)) : GL_COLOR_BUFFER_BIT;
    glBlitFramebuffer((GLint)sr[0], (GLint)sr[1], (GLint)sr[2], (GLint)sr[3], (GLint)dr[0], (GLint)dr[1], (GLint)dr[2], (GLint)dr[3],
        mask, (!depth && filter >= 2) ? GL_LINEAR : GL_NEAREST);
    GLenum e = glGetError();
    if (e) void_log("[gl] StretchRect %ux%u fmt %u -> %ux%u fmt %u error %04X", src->width, src->height, src->format,
        dst->width, dst->height, dst->format, e);
    if (g_d3d_device && tracing(g_d3d_device)) {
        GLenum rs = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER), ds = glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER);
        GLint rb = 0, db = 0;
        glGetIntegerv(GL_READ_BUFFER, &rb);
        glGetIntegerv(GL_DRAW_BUFFER0, &db);
        void_log("[trace]   blit read fb %04X buffer %04X, draw fb %04X buffer %04X", rs, rb, ds, db);
        trace_dump(g_d3d_device, dst, "blit result");
    }
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (g_d3d_device) g_d3d_device->fbo_dirty = 1;
}

/* Logical RGBA of rect (x0, y0, x1, y1) of a GPU surface: storage rows are
 * D3D rows, so the rect reads unchanged. Returns 0 if GL cannot read it. */
int d3d_gl_read_rgba(d3d_surface *s, const uint32_t *r, float *out)
{
    if (!s->fmt || s->fmt->depth || !s->fmt->internal) return 0;
    d3d_surface *shown = g_d3d_device ? ui_surface(g_d3d_device, s) : s;
    if (shown != s) ui_copy(shown, s);
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    attach(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, s);
    glReadBuffer(GL_COLOR_ATTACHMENT0);
    GLsizei w = (GLsizei)(r[2] - r[0]), h = (GLsizei)(r[3] - r[1]);
    int ok = glCheckFramebufferStatus(GL_READ_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE;
    if (ok) {
        while (glGetError()) {}
        if (s->fmt->is_float) {
            glReadPixels((GLint)r[0], (GLint)r[1], w, h, GL_RGBA, GL_FLOAT, out);
        } else {
            uint8_t *tmp = (uint8_t *)malloc((size_t)w * (size_t)h * 4);
            glReadPixels((GLint)r[0], (GLint)r[1], w, h, GL_RGBA, GL_UNSIGNED_BYTE, tmp);
            d3d_gl_layout_to_rgba(GL_RGBA, GL_UNSIGNED_BYTE, tmp, (uint32_t)(w * h), out);
            free(tmp);
        }
        ok = glGetError() == GL_NO_ERROR;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (g_d3d_device) g_d3d_device->fbo_dirty = 1;
    if (!ok) return 0;
    /* Standalone GPU surfaces are stored like render targets (d3d_surface_new). */
    uint32_t usage = s->container ? s->container->usage : (s->usage | D3DUSAGE_RENDERTARGET);
    GLint sw[4];
    d3d_storage_swizzle(s->fmt, usage, sw);
    d3d_swizzle_rgba(sw, out, (uint32_t)(w * h));
    return 1;
}

/* A whole GPU surface into guest memory in its own format (LockRect). */
void d3d_gl_read_surface(d3d_surface *src, uint32_t dst_mem, uint32_t dst_pitch)
{
    uint32_t w = src->width, h = src->height, rect[4] = { 0, 0, w, h };
    float *px = (float *)malloc((size_t)w * h * 16);
    if (!d3d_gl_read_rgba(src, rect, px)) {
        void_log("[gl] surface %ux%u format %u cannot be read back", w, h, src->format);
        for (uint32_t y = 0; y < h; ++y) memset(GPTR(dst_mem + y * dst_pitch), 0, dst_pitch);
    } else {
        for (uint32_t y = 0; y < h; ++y)
            if (!d3d_format_encode(src->format, px + (size_t)y * w * 4, w, (uint8_t *)GPTR(dst_mem + y * dst_pitch))) {
                void_log("[gl] read back of format %u unsupported", src->format);
                break;
            }
    }
    free(px);
}

void d3d_gl_fill(d3d_surface *dst, const uint32_t *r, uint32_t color)
{
    raster_state_valid = 0;
    uint32_t scaled[4];
    d3d_surface *target = g_d3d_device ? ui_surface(g_d3d_device, dst) : dst;
    if (target != dst) {
        for (int i = 0; i < 4; ++i) scaled[i] = (uint32_t)lround((double)(int32_t)r[i] *
            (i & 1 ? (double)target->height / dst->height : (double)target->width / dst->width));
        r = scaled; dst = target;
    }
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    glBindFramebuffer(GL_FRAMEBUFFER, draw_fbo);
    attach(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, dst);
    glEnable(GL_SCISSOR_TEST);
    glScissor((GLint)r[0], (GLint)r[1], (GLsizei)(r[2] - r[0]), (GLsizei)(r[3] - r[1]));
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glClearColor(((color >> 16) & 255) / 255.0f, ((color >> 8) & 255) / 255.0f, (color & 255) / 255.0f, (color >> 24) / 255.0f);
    glClear(GL_COLOR_BUFFER_BIT);
    glDisable(GL_SCISSOR_TEST);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    if (g_d3d_device) g_d3d_device->fbo_dirty = 1;
}

/* --------------------------------------------------------------- present */
void d3d_gl_dump_frame(d3d_device *dev, const char *path)
{
    d3d_surface *bb = dev->backbuffer;
    uint32_t w = bb->width, h = bb->height;
    uint8_t *px = (uint8_t *)malloc((size_t)w * h * 4);
    if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
    glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
    attach(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, bb);
    glReadPixels(0, 0, (GLsizei)w, (GLsizei)h, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    dev->fbo_dirty = 1;
    FILE *f = fopen(path, "wb");
    if (f) {
        uint32_t row = w * 3, pad = (4 - row % 4) % 4, size = 54 + (row + pad) * h;
        uint8_t header[54] = { 'B', 'M' };
        memcpy(header + 2, &size, 4);
        uint32_t v = 54; memcpy(header + 10, &v, 4);
        v = 40; memcpy(header + 14, &v, 4);
        memcpy(header + 18, &w, 4); memcpy(header + 22, &h, 4);
        header[26] = 1; header[28] = 24;
        fwrite(header, 1, 54, f);
        uint8_t zero[4] = {0};
        /* BMP rows run bottom-up; the backbuffer's row 0 is the top. */
        for (uint32_t y = h; y-- > 0;) {
            for (uint32_t x = 0; x < w; ++x) {
                uint8_t *p = px + ((size_t)y * w + x) * 4;
                uint8_t bgr[3] = { p[2], p[1], p[0] };
                fwrite(bgr, 1, 3, f);
            }
            fwrite(zero, 1, pad, f);
        }
        fclose(f);
        void_log("[gl] frame %u written to %s", dev->frame, path);
    }
    free(px);
}

static volatile int dump_requested;

/* Dump the next presented frame (scripted "shot"). */
void d3d_request_frame_dump(void) { dump_requested = 1; }

/* The EGL context/window belongs to the activity; device-owned GL state does not. */
void d3d_gl_device_destroy(void)
{
    frame_deadline_ns = 0;
    raster_state_valid = 0;
    ui_active = 0;
    ui_owner = NULL; ui_backbuffer = ui_depth_source = NULL;
    ui_release(&ui_color); ui_release(&ui_depth);
    glUseProgram(0);
    d3d_shader_reset();
    d3d_ff_reset();
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (fbo) glDeleteFramebuffers(1, &fbo);
    if (read_fbo) glDeleteFramebuffers(1, &read_fbo);
    if (draw_fbo) glDeleteFramebuffers(1, &draw_fbo);
    fbo = read_fbo = draw_fbo = 0;
    for (int i = 0; i < 4; ++i) fb_color[i] = (fb_attachment){FB_UNKNOWN, 0, 0, 0};
    fb_depth = (fb_attachment){FB_UNKNOWN, 0, 0, 0};
    fb_depth_point = FB_UNKNOWN;
    fb_depth_w = fb_depth_h = 0;
    memset(fb_bufs, 0, sizeof fb_bufs);
    fb_buf_count = -1;
    for (GLuint i = 0; i < 32; ++i) {
        glActiveTexture(GL_TEXTURE0 + i);
        glBindTexture(GL_TEXTURE_2D, 0);
        glBindTexture(GL_TEXTURE_3D, 0);
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0);
        glBindSampler(i, 0);
    }
    for (int i = 0; i < sampler_count; ++i) glDeleteSamplers(1, &sampler_cache[i].sampler);
    memset(sampler_cache, 0, sizeof sampler_cache);
    sampler_count = 0;
    memset(unit_tex, 0, sizeof unit_tex);
    memset(unit_sampler, 0, sizeof unit_sampler);
    memset(unit_target, 0, sizeof unit_target);
    active_unit = -1;
    if (vao) glDeleteVertexArrays(1, &vao);
    if (up_vbo) glDeleteBuffers(1, &up_vbo);
    if (up_ibo) glDeleteBuffers(1, &up_ibo);
    for (unsigned stream = 0; stream < 16; ++stream)
        if (stream_vbos[stream]) glDeleteBuffers(1, &stream_vbos[stream]);
    memset(stream_vbos, 0, sizeof stream_vbos);
    ring_release();
    free(sparse_indices); free(sparse_hash); free(sparse_data); free(sparse_map);
    sparse_indices = sparse_vertices = NULL; sparse_hash = NULL; sparse_data = NULL;
    sparse_capacity = sparse_hash_capacity = sparse_data_capacity = 0;
    sparse_map = NULL; sparse_map_capacity = sparse_map_generation = 0;
    vao = up_vbo = up_ibo = 0;
    memset(attr_cache, 0, sizeof attr_cache);
    attr_cache_ready = 0;
    enabled_attribs = 0;
    elem_buffer = FB_UNKNOWN;
    trace_rt = NULL;
    free(trace_before);
    trace_before = NULL;
    trace_before_w = trace_before_h = trace_seq = 0;
    dump_requested = 0;
    draw_calls = swap_ns = 0;
    vb_upload_calls = vb_upload_bytes = vb_upload_frame_bytes = vb_upload_peak_bytes = vb_sparse_calls = vb_sparse_saved = 0;
    depth_trace_remaining = 0;
    __atomic_store_n(&depth_trace_requested, 0u, __ATOMIC_RELAXED);
}

/* Present commits its GL/frame state first; audio and other guest threads may
 * run during the deadline wait without changing the simulation clock. */
void d3d_gl_frame_pace(void)
{
    float fps = void_port_fps_limit();
    if (!window_mode || egl_surface == EGL_NO_SURFACE || fps <= 0.0f) {
        frame_deadline_ns = 0;
        return;
    }
    uint64_t period = (uint64_t)(1000000000.0 / (double)fps);
    uint64_t now = void_perf_now_ns();
    if (period != frame_period_ns || !frame_deadline_ns || now >= frame_deadline_ns + period) {
        frame_deadline_ns = now;
        frame_period_ns = period;
    }
    if (now < frame_deadline_ns) {
        struct timespec deadline = { (time_t)(frame_deadline_ns / 1000000000ull),
                                     (long)(frame_deadline_ns % 1000000000ull) };
        void_blocking_begin();
        int error;
        do { error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL); } while (error == EINTR);
        void_blocking_end();
        if (error) {
            void_log("[gl] frame deadline wait failed %d", error);
            frame_deadline_ns = 0;
            return;
        }
        now = void_perf_now_ns();
    }
    /* A slow frame or background/resume never creates a catch-up burst. */
    frame_deadline_ns = now >= frame_deadline_ns + period ? now + period : frame_deadline_ns + period;
}

void d3d_gl_present(d3d_device *dev)
{
    ring_frame_end();
    GLenum error = glGetError();
    if (error) {
        static int warned;
        if (warned++ < 20) void_log("[gl] error %04X during frame %u", error, dev->frame);
    }
    depth_trace_present(dev);
    raster_state_valid = 0;
    if (vb_upload_frame_bytes > vb_upload_peak_bytes) vb_upload_peak_bytes = vb_upload_frame_bytes;
    vb_upload_frame_bytes = 0;
    static struct timespec fps_start, cpu_start;
    static uint64_t wait_start, draws_start, swap_start_ns;
    static uint32_t fps_frame;
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    /* Every 600 frames, or every 5 s when frames are slow. */
    if (dev->frame - fps_frame >= 600 || !fps_start.tv_sec || now.tv_sec - fps_start.tv_sec >= 5) {
        struct timespec cpu;
        clock_gettime(CLOCK_THREAD_CPUTIME_ID, &cpu);
        uint64_t wait = void_lock_wait_ns();
        double dt = (double)(now.tv_sec - fps_start.tv_sec) + (double)(now.tv_nsec - fps_start.tv_nsec) / 1e9;
        double dcpu = (double)(cpu.tv_sec - cpu_start.tv_sec) + (double)(cpu.tv_nsec - cpu_start.tv_nsec) / 1e9;
        uint32_t frames = dev->frame - fps_frame;
        if (fps_start.tv_sec && frames)
            void_log("[gl] frame %u: %.1f fps; per frame %.1f ms wall, %.1f ms cpu, %.1f ms machine wait, %.0f draws, "
                "%.1f ms swap; compact VB %.1f KiB/frame, %.1f calls/frame, %.1f KiB peak; sparse %llu draws %.1f MiB/frame saved",
                dev->frame, frames / dt, 1000.0 * dt / frames, 1000.0 * dcpu / frames,
                (double)(wait - wait_start) / 1e6 / frames, (double)(draw_calls - draws_start) / frames,
                (double)(swap_ns - swap_start_ns) / 1e6 / frames,
                (double)vb_upload_bytes / 1024.0 / frames, (double)vb_upload_calls / frames,
                (double)vb_upload_peak_bytes / 1024.0,
                (unsigned long long)vb_sparse_calls, (double)vb_sparse_saved / (1024.0 * 1024.0) / frames);
        if (fps_start.tv_sec && frames) void_thunk_stats(frames);
        vb_upload_calls = vb_upload_bytes = vb_upload_peak_bytes = vb_sparse_calls = vb_sparse_saved = 0;
        draws_start = draw_calls;
        swap_start_ns = swap_ns;
        fps_start = now;
        cpu_start = cpu;
        wait_start = wait;
        fps_frame = dev->frame;
    }
    if (tracing(dev)) {
        if (trace_rt && trace_rt != dev->backbuffer) trace_dump(dev, trace_rt, "target done");
        trace_dump(dev, dev->backbuffer, "present");
        trace_rt = NULL;
        void_log("[trace] frame %u presented", dev->frame);
    }
    if (dump_requested) {
        dump_requested = 0;
        char path[1100];
        snprintf(path, sizeof path, "%s/frames", void_data_dir());
        mkdir(path, 0775);
        snprintf(path, sizeof path, "%s/frames/shot_%05u.bmp", void_data_dir(), dev->frame);
        d3d_gl_dump_frame(dev, path);
    }
    if (dump_every && dev->frame % (uint32_t)dump_every == 0) {
        char path[1100];
        snprintf(path, sizeof path, "%s/frames", void_data_dir());
        mkdir(path, 0775);
        snprintf(path, sizeof path, "%s/frames/frame_%05u.bmp", void_data_dir(), dev->frame);
        d3d_gl_dump_frame(dev, path);
    }
    if (window_mode) follow_window();
    if (window_mode && egl_surface != EGL_NO_SURFACE) {
        EGLint sw = 0, sh = 0;
        eglQuerySurface(egl_display, egl_surface, EGL_WIDTH, &sw);
        eglQuerySurface(egl_display, egl_surface, EGL_HEIGHT, &sh);
        d3d_surface *bb = ui_surface(dev, dev->backbuffer);
        if (!read_fbo) { glGenFramebuffers(1, &read_fbo); glGenFramebuffers(1, &draw_fbo); }
        glBindFramebuffer(GL_READ_FRAMEBUFFER, read_fbo);
        attach(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, bb);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glDisable(GL_SCISSOR_TEST);
        glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
        glClearColor(0, 0, 0, 1);
        glClear(GL_COLOR_BUFFER_BIT);
        /* Fit with the original aspect ratio; flip rows to the window's. */
        float scale = fminf((float)sw / (float)bb->width, (float)sh / (float)bb->height);
        int dw = (int)((float)bb->width * scale), dh = (int)((float)bb->height * scale);
        int dx = (sw - dw) / 2, dy = (sh - dh) / 2;
        glBlitFramebuffer(0, 0, (GLint)bb->width, (GLint)bb->height, dx, dy + dh, dx + dw, dy, GL_COLOR_BUFFER_BIT, GL_LINEAR);
        /* Present hands off after the swap and frame state are committed. */
        struct timespec swap_start, swap_end;
        clock_gettime(CLOCK_MONOTONIC, &swap_start);
        eglSwapBuffers(egl_display, egl_surface);
        clock_gettime(CLOCK_MONOTONIC, &swap_end);
        swap_ns += (uint64_t)(swap_end.tv_sec - swap_start.tv_sec) * 1000000000ull + (uint64_t)swap_end.tv_nsec -
                   (uint64_t)swap_start.tv_nsec;
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        dev->fbo_dirty = 1;
    } else {
        glFlush();
    }
    ui_active = 0;
    ui_depth_source = NULL;
    dev->fbo_dirty = 1;
    raster_state_valid = 0;
    void_android_frame_presented();
    void_perf_frame_end(dev->frame);
}
