/* Direct3D 9 resources: surfaces, textures, buffers, vertex declarations,
 * queries, state blocks and the implicit swap chain. */
#include "d3d9_internal.h"
#include "d3d9_thread.inc"
#include <errno.h>
#include <time.h>
#include "touch.h"


/* ------------------------------------------------------------------ util */
static uint32_t mip_levels(uint32_t w, uint32_t h, uint32_t d)
{
    uint32_t n = 1, m = w > h ? w : h;
    if (d > m) m = d;
    while (m > 1) { m >>= 1; ++n; }
    return n;
}

static void level_dims(uint32_t w, uint32_t h, uint32_t level, uint32_t *lw, uint32_t *lh)
{
    *lw = w >> level; *lh = h >> level;
    if (!*lw) *lw = 1;
    if (!*lh) *lh = 1;
}

static GLenum face_target(d3d_texture *t, uint32_t face)
{
    return t->rtype == D3DRTYPE_CUBETEXTURE ? GL_TEXTURE_CUBE_MAP_POSITIVE_X + face : t->target;
}

static int is_render_target_usage(uint32_t usage) { return (usage & (D3DUSAGE_RENDERTARGET | D3DUSAGE_DEPTHSTENCIL)) != 0; }

static void apply_swizzle(GLenum target, const d3d_format *f, uint32_t usage)
{
    GLint sw[4] = { f->swizzle[0], f->swizzle[1], f->swizzle[2], f->swizzle[3] };
    if ((usage & D3DUSAGE_RENDERTARGET) && (f->d3d == 21 || f->d3d == 22 || f->d3d == 35)) {
        /* GPU-written BGRA formats are stored as RGBA. */
        sw[0] = GL_RED; sw[1] = GL_GREEN; sw[2] = GL_BLUE;
        sw[3] = f->d3d == 22 ? GL_ONE : GL_ALPHA;
    }
    glTexParameteri(target, GL_TEXTURE_SWIZZLE_R, sw[0]);
    glTexParameteri(target, GL_TEXTURE_SWIZZLE_G, sw[1]);
    glTexParameteri(target, GL_TEXTURE_SWIZZLE_B, sw[2]);
    glTexParameteri(target, GL_TEXTURE_SWIZZLE_A, sw[3]);
}

/* ================================================================ surfaces */
static void_com_class surface_class;

uint32_t d3d_wrap_surface(d3d_surface *s) { return s->com.guest; }

/* Objects the render thread may still reach through recorded calls (its
 * device's state, a draw not run yet) are freed there, after those calls; the
 * game's thread keeps guest memory and COM to itself. */
static void run_surface_free(void *args)
{
    d3d_surface *s = *(d3d_surface **)args;
    if (s->gl) { d3d_gl_forget_texture(s->gl); glDeleteTextures(1, &s->gl); }
    free(s);
}

static void surface_destroy(void_com_object *o)
{
    d3d_surface *s = (d3d_surface *)o;
    if (s->sysmem) void_gfree(s->sysmem);
    d3d_rt_call(run_surface_free, &s, sizeof s);
}

static void run_surface_create(void *args)
{
    d3d_surface *s = *(d3d_surface **)args;
    glGenTextures(1, &s->gl);
    d3d_gl_upload_unit();
    glBindTexture(GL_TEXTURE_2D, s->gl);
    glTexStorage2D(GL_TEXTURE_2D, 1, s->fmt->internal, (GLsizei)s->width, (GLsizei)s->height);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    apply_swizzle(GL_TEXTURE_2D, s->fmt, s->usage | (s->fmt->depth ? 0 : D3DUSAGE_RENDERTARGET));
    GLenum e = glGetError();
    if (e) void_log("[d3d9] surface %ux%u format %u: GL error %04X", s->width, s->height, s->format, e);
}

d3d_surface *d3d_surface_new(d3d_device *dev, uint32_t w, uint32_t h, uint32_t format, uint32_t usage,
    uint32_t pool, uint32_t multisample)
{
    d3d_surface *s = (d3d_surface *)calloc(1, sizeof(d3d_surface_rt));
    s->dev = dev;
    s->width = w ? w : 1; s->height = h ? h : 1;
    s->format = format; s->usage = usage; s->pool = pool; s->multisample = multisample;
    s->fmt = d3d_format_find(format);
    s->pitch = s->fmt ? d3d_format_pitch(s->fmt, s->width) : s->width * 4;
    void_com_wrap(&s->com, &surface_class, 0);
    s->com.destroy = surface_destroy;
    if (pool == D3DPOOL_SYSTEMMEM || pool == D3DPOOL_SCRATCH) {
        s->sysmem = void_galloc(s->pitch * (s->fmt ? d3d_format_rows(s->fmt, s->height) : s->height));
    } else if (s->fmt && s->fmt->internal) {
        SURF_RT(s)->has_gl = 1;
        d3d_rt_call(run_surface_create, &s, sizeof s);
    }
    return s;
}

/* Private UI/filter targets: no COM or guest allocator on the render thread. */
d3d_surface *d3d_gl_scratch_new(d3d_device *dev, uint32_t w, uint32_t h, uint32_t format, uint32_t usage)
{
    d3d_surface *s = (d3d_surface *)calloc(1, sizeof *s);
    if (!s) return NULL;
    s->dev = dev; s->width = w; s->height = h; s->format = format; s->usage = usage;
    s->fmt = d3d_format_find(format);
    if (!s->fmt || !s->fmt->internal) { free(s); return NULL; }
    run_surface_create(&s);
    return s;
}

void d3d_gl_scratch_free(d3d_surface *s) { run_surface_free(&s); }

GLuint d3d_surface_gl_texture(d3d_surface *s, GLenum *target, GLint *level, GLint *layer)
{
    if (s->container) {
        *target = face_target(s->container, s->face);
        *level = (GLint)s->level;
        *layer = (GLint)s->face;
        return s->container->gl;
    }
    *target = GL_TEXTURE_2D;
    *level = 0;
    *layer = 0;
    return s->gl;
}

/* Surfaces of a texture share the texture's reference count. */
static void_com_object *refcount_owner(d3d_surface *s) { return s->container ? &s->container->com : &s->com; }
void_com_object *d3d_surface_owner(d3d_surface *s) { return refcount_owner(s); }

COM_METHOD(surf, QueryInterface, 3)
{
    d3d_surface *s = (d3d_surface *)void_com_host(THIS_);
    if (void_guid_equal(ARG(1), IID_IDirect3DSurface9) || void_guid_equal(ARG(1), IID_IDirect3DResource9) ||
        void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(refcount_owner(s));
        MEM32(ARG(2)) = THIS_;
        return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(surf, AddRef, 1) { return void_com_addref(refcount_owner((d3d_surface *)void_com_host(THIS_))); }
COM_METHOD(surf, Release, 1) { return void_com_release(refcount_owner((d3d_surface *)void_com_host(THIS_))); }
COM_METHOD(surf, GetDevice, 2)
{
    d3d_surface *s = (d3d_surface *)void_com_host(THIS_);
    void_com_addref(&s->dev->com);
    MEM32(ARG(1)) = s->dev->com.guest;
    return D3D_OK;
}
COM_METHOD(surf, SetPrivateData, 5) { return D3D_OK; }
COM_METHOD(surf, GetPrivateData, 4) { return D3DERR_NOTFOUND; }
COM_METHOD(surf, FreePrivateData, 2) { return D3D_OK; }
COM_METHOD(surf, SetPriority, 2) { return 0; }
COM_METHOD(surf, GetPriority, 1) { return 0; }
COM_METHOD(surf, PreLoad, 1) { return 0; }
COM_METHOD(surf, GetType, 1) { return D3DRTYPE_SURFACE; }
COM_METHOD(surf, GetContainer, 3)
{
    d3d_surface *s = (d3d_surface *)void_com_host(THIS_);
    if (s->container) {
        void_com_addref(&s->container->com);
        MEM32(ARG(2)) = s->container->com.guest;
    } else {
        void_com_addref(&s->dev->com);
        MEM32(ARG(2)) = s->dev->com.guest;
    }
    return D3D_OK;
}
COM_METHOD(surf, GetDesc, 2)
{
    d3d_surface *s = (d3d_surface *)void_com_host(THIS_);
    uint32_t d = ARG(1);
    MEM32(d) = s->format; MEM32(d + 4) = D3DRTYPE_SURFACE; MEM32(d + 8) = s->usage; MEM32(d + 12) = s->pool;
    MEM32(d + 16) = s->multisample; MEM32(d + 20) = 0; MEM32(d + 24) = s->width; MEM32(d + 28) = s->height;
    return D3D_OK;
}

/* Guest storage that backs a lock: persistent for SYSTEMMEM/SCRATCH and
 * MANAGED textures (D3D keeps their system copy too), temporary otherwise. */
static uint32_t surface_storage(d3d_surface *s, int *persistent)
{
    *persistent = 1;
    if (s->sysmem) return s->sysmem;
    if (s->container) {
        d3d_texture *t = s->container;
        uint32_t index = s->face * t->levels + s->level;
        if (t->sysmem) {
            if (!t->sysmem[index]) t->sysmem[index] = void_galloc(s->pitch * d3d_format_rows(s->fmt, s->height));
            return t->sysmem[index];
        }
    }
    *persistent = 0;
    return void_galloc(s->pitch * d3d_format_rows(s->fmt, s->height));
}

/* Recreate a texture's GL storage for converted blocks (`native`) or for its
 * D3D format's own upload layout (NULL). Its levels' contents are refilled by
 * the caller; samplers are separate objects, so only the name changes. */
typedef struct { d3d_texture *t; const d3d_native_format *native; } storage_args;

static void run_set_storage(void *args)
{
    const storage_args *a = (const storage_args *)args;
    d3d_texture *t = a->t;
    const d3d_native_format *native = a->native;
    GLuint old = t->gl;
    glGenTextures(1, &t->gl);
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glTexStorage2D(t->target, (GLsizei)t->levels, native ? native->internal : t->fmt->internal, (GLsizei)t->width,
                   (GLsizei)t->height);
    glTexParameteri(t->target, GL_TEXTURE_MAX_LEVEL, (GLint)t->levels - 1);
    apply_swizzle(t->target, t->fmt, t->usage);
    d3d_gl_forget_texture(old);
    glDeleteTextures(1, &old);
    GLenum e = glGetError();
    if (e) void_log("[d3d9] texture %ux%u storage %.4s: GL error %04X", t->width, t->height,
                    native ? (const char *)&native->fourcc : "dxt", e);
    TEX_RT(t)->rt_native = native;
}

static void texture_set_storage(d3d_texture *t, const d3d_native_format *native)
{
    if (t->native == native) return;
    if (!TEX_RT(t)->has_gl) { t->native = native; return; }     /* a system copy only remembers it */
    if (t->target != GL_TEXTURE_2D) return;
    storage_args a = { t, native };
    d3d_rt_call(run_set_storage, &a, sizeof a);
    t->native = native;
    t->native_lock_logged = 0;
}

COM_METHOD(surf, LockRect, 4)
{
    d3d_surface *s = (d3d_surface *)void_com_host(THIS_);
    uint32_t out = ARG(1), rect = ARG(2), flags = ARG(3);
    if (s->locked) return D3DERR_INVALIDCALL;
    if (!s->fmt) return D3DERR_INVALIDCALL;
    int persistent;
    uint32_t mem = surface_storage(s, &persistent);
    s->lock_mem = mem;
    s->lock_flags = flags;
    s->locked = persistent ? 1 : 2;
    uint32_t x = 0, y = 0;
    s->lock_whole = !rect;
    if (rect) {
        x = MEM32(rect); y = MEM32(rect + 4);
        for (int i = 0; i < 4; ++i) s->lock_rect[i] = MEM32(rect + 4u * (uint32_t)i);
    } else {
        s->lock_rect[0] = s->lock_rect[1] = 0; s->lock_rect[2] = s->width; s->lock_rect[3] = s->height;
    }
    if (!persistent && !(flags & D3DLOCK_DISCARD) && !s->fmt->block_bytes && !s->fmt->depth &&
        (SURF_RT(s)->has_gl || (s->container && TEX_RT(s->container)->has_gl)))
        d3d_gl_read_surface(s, mem, s->pitch);      /* reading a GPU-only surface */
    if (s->container && s->fmt->block_bytes && !(flags & D3DLOCK_READONLY)) {
        /* The engine's loader fills DXT textures level by level, reusing them
         * (an LRU set): each fill decides what the blocks are. */
        d3d_texture *t = s->container;
        const d3d_native_format *native = NULL;
        if (d3d_native_take(t->width, t->height, t->format, &native)) texture_set_storage(t, native);
        else if (s->level == 0 && t->native) texture_set_storage(t, NULL);
    }
    uint32_t offset = s->fmt->block_bytes ? (y / 4) * s->pitch + (x / 4) * s->fmt->block_bytes
                                          : y * s->pitch + x * (s->fmt->bits / 8);
    MEM32(out) = s->pitch;
    MEM32(out + 4) = mem + offset;
    return D3D_OK;
}

typedef struct { d3d_surface *s; uint32_t x, y, w, h; } surface_upload_args;

static void run_surface_upload(void *args)
{
    const surface_upload_args *a = (const surface_upload_args *)args;
    d3d_surface *s = a->s;
    void *owned;
    size_t size;
    const void *gl_data = d3d_format_convert(s->fmt, (const uint8_t *)(a + 1), a->w, a->h, s->pitch, &owned, &size, 1);
    d3d_gl_upload_unit();
    glBindTexture(GL_TEXTURE_2D, s->gl);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexSubImage2D(GL_TEXTURE_2D, 0, (GLint)a->x, (GLint)a->y, (GLsizei)a->w, (GLsizei)a->h, s->fmt->format,
        s->fmt->type, gl_data);
    free(owned);
}

/* Upload rect (x0, y0, x1, y1) of guest-layout data `mem` laid out like the
 * whole surface (s->pitch). Block formats widen the rect to whole blocks. */
static void surface_upload_rect(d3d_surface *s, uint32_t mem, const uint32_t *rect)
{
    uint32_t x0 = rect[0], y0 = rect[1], x1 = rect[2], y1 = rect[3];
    if (s->fmt->block_bytes) {
        x0 &= ~3u; y0 &= ~3u;
        x1 = (x1 + 3) & ~3u; y1 = (y1 + 3) & ~3u;
    }
    if (x1 > s->width) x1 = s->width;
    if (y1 > s->height) y1 = s->height;
    if (x1 <= x0 || y1 <= y0) return;
    uint32_t offset = s->fmt->block_bytes ? (y0 / 4) * s->pitch + (x0 / 4) * s->fmt->block_bytes
                                          : y0 * s->pitch + x0 * (s->fmt->bits / 8);
    const uint8_t *data = (const uint8_t *)GPTR(mem + offset);
    if (s->container) {
        d3d_texture_upload_rect(s->container, s->face, s->level, x0, y0, x1 - x0, y1 - y0, data, s->pitch);
    } else if (SURF_RT(s)->has_gl && s->fmt->internal && !s->fmt->depth) {
        /* Standalone GPU surfaces are stored like render targets (d3d_surface_new). */
        uint32_t bytes = s->pitch * (d3d_format_rows(s->fmt, y1 - y0) - 1u) + d3d_format_pitch(s->fmt, x1 - x0);
        surface_upload_args *a = (surface_upload_args *)d3d_rt_begin(run_surface_upload, (uint32_t)sizeof *a + bytes);
        *a = (surface_upload_args){ s, x0, y0, x1 - x0, y1 - y0 };
        memcpy(a + 1, data, bytes);
        d3d_rt_commit();
    }
}

void d3d_surface_upload(d3d_surface *s)
{
    if (!s->lock_mem || !s->fmt) return;
    uint32_t whole[4] = { 0, 0, s->width, s->height };
    surface_upload_rect(s, s->lock_mem, s->lock_whole ? whole : s->lock_rect);
}

/* Rect (x0, y0, x1, y1) of a surface as logical RGBA, from its guest copy when
 * it has one, otherwise from the GPU. */
int d3d_surface_read_rgba(d3d_surface *s, const uint32_t *rect, float *out)
{
    if (!s->fmt) return 0;
    uint32_t w = rect[2] - rect[0], h = rect[3] - rect[1];
    uint32_t mem = s->sysmem;
    if (!mem && s->container && s->container->sysmem)
        mem = s->container->sysmem[s->face * s->container->levels + s->level];
    if (!mem) return d3d_gl_read_rgba(s, rect, out);
    if (s->fmt->block_bytes) {
        /* Decode the whole blocks covering the rect, then crop. */
        uint32_t bx = rect[0] & ~3u, by = rect[1] & ~3u;
        uint32_t bw = ((rect[2] + 3) & ~3u) - bx, bh = ((rect[3] + 3) & ~3u) - by;
        float *tmp = (float *)malloc((size_t)bw * bh * 16);
        d3d_format_decode(s->fmt, (const uint8_t *)GPTR(mem + (by / 4) * s->pitch + (bx / 4) * s->fmt->block_bytes),
            bw, bh, s->pitch, tmp);
        for (uint32_t y = 0; y < h; ++y)
            memcpy(out + (size_t)y * w * 4, tmp + ((size_t)(rect[1] - by + y) * bw + (rect[0] - bx)) * 4, (size_t)w * 16);
        free(tmp);
        return 1;
    }
    d3d_format_decode(s->fmt, (const uint8_t *)GPTR(mem + rect[1] * s->pitch + rect[0] * (s->fmt->bits / 8)), w, h,
        s->pitch, out);
    return 1;
}

/* Store logical RGBA into rect (x0, y0, x1, y1) of a surface: into its guest
 * copy when it has one, and into its GPU copy when it has one. */
int d3d_surface_write_rgba(d3d_surface *s, const uint32_t *rect, const float *rgba)
{
    if (!s->fmt || s->fmt->block_bytes || s->fmt->depth) return 0;
    uint32_t w = rect[2] - rect[0], h = rect[3] - rect[1], bpp = s->fmt->bits / 8;
    uint32_t mem = s->sysmem;
    if (!mem && s->container && s->container->sysmem) {
        uint32_t index = s->face * s->container->levels + s->level;
        if (!s->container->sysmem[index])
            s->container->sysmem[index] = void_galloc(s->pitch * d3d_format_rows(s->fmt, s->height));
        mem = s->container->sysmem[index];
    }
    int temporary = !mem;
    if (temporary) mem = void_galloc(s->pitch * d3d_format_rows(s->fmt, s->height));
    for (uint32_t y = 0; y < h; ++y) {
        uint8_t *row = (uint8_t *)GPTR(mem + (rect[1] + y) * s->pitch + rect[0] * bpp);
        if (!d3d_format_encode(s->format, rgba + (size_t)y * w * 4, w, row)) {
            if (temporary) void_gfree(mem);
            return 0;
        }
    }
    if (!s->sysmem) surface_upload_rect(s, mem, rect);
    if (temporary) void_gfree(mem);
    return 1;
}

COM_METHOD(surf, UnlockRect, 1)
{
    d3d_surface *s = (d3d_surface *)void_com_host(THIS_);
    if (!s->locked) return D3DERR_INVALIDCALL;
    if (!(s->lock_flags & D3DLOCK_READONLY) && !s->sysmem) d3d_surface_upload(s);
    if (s->locked == 2) void_gfree(s->lock_mem);
    s->locked = 0;
    s->lock_mem = 0;
    return D3D_OK;
}

COM_METHOD(surf, GetDC, 2) { void_log("[d3d9] IDirect3DSurface9::GetDC unsupported"); return D3DERR_INVALIDCALL; }
COM_METHOD(surf, ReleaseDC, 2) { return D3D_OK; }

static const void_fn surface_methods[] = {
    surf_QueryInterface, surf_AddRef, surf_Release, surf_GetDevice, surf_SetPrivateData, surf_GetPrivateData,
    surf_FreePrivateData, surf_SetPriority, surf_GetPriority, surf_PreLoad, surf_GetType, surf_GetContainer,
    surf_GetDesc, surf_LockRect, surf_UnlockRect, surf_GetDC, surf_ReleaseDC,
};
static void_com_class surface_class = { "IDirect3DSurface9", 17, surface_methods, 0 };

/* ================================================================ textures */
static void_com_class texture_class, cube_class, volume_class;

static void run_texture_free(void *args)
{
    d3d_texture *t = *(d3d_texture **)args;
    if (t->gl) { d3d_gl_forget_texture(t->gl); glDeleteTextures(1, &t->gl); }
    free(t->surfaces);
    free(t);
}

static void texture_destroy(void_com_object *o)
{
    d3d_texture *t = (d3d_texture *)o;
    int n = t->faces * (int)t->levels;
    for (int i = 0; i < n; ++i) {
        if (t->surfaces && t->surfaces[i]) {
            /* Its surfaces go with it (their structures on the render thread, before the texture's). */
            d3d_surface *s = t->surfaces[i];
            s->com.refs = 1;
            void_com_release(&s->com);
        }
        if (t->sysmem && t->sysmem[i]) void_gfree(t->sysmem[i]);
    }
    free(t->sysmem);
    t->sysmem = NULL;
    d3d_rt_call(run_texture_free, &t, sizeof t);
}

void d3d_texture_level_size(d3d_texture *t, uint32_t level, uint32_t *w, uint32_t *h)
{
    level_dims(t->width, t->height, level, w, h);
}

/* GL storage of a texture: in its D3D format's upload layout, or in the
 * converted blocks rt_native when set before. */
static void run_texture_create(void *args)
{
    d3d_texture *t = *(d3d_texture **)args;
    const d3d_native_format *native = TEX_RT(t)->rt_native;
    GLenum internal = native ? native->internal : t->fmt->internal;
    glGenTextures(1, &t->gl);
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    if (t->target == GL_TEXTURE_3D)
        glTexStorage3D(GL_TEXTURE_3D, (GLsizei)t->levels, internal, (GLsizei)t->width, (GLsizei)t->height, (GLsizei)t->depth);
    else
        glTexStorage2D(t->target, (GLsizei)t->levels, internal, (GLsizei)t->width, (GLsizei)t->height);
    glTexParameteri(t->target, GL_TEXTURE_MAX_LEVEL, (GLint)t->levels - 1);
    apply_swizzle(t->target, t->fmt, t->usage);
    GLenum e = glGetError();
    if (e && native) void_log("[d3d9] converted texture %ux%u levels %u format %.4s: GL error %04X", t->width, t->height,
                              t->levels, (const char *)&native->fourcc, e);
    else if (e) void_log("[d3d9] texture %ux%u levels %u format %u: GL error %04X", t->width, t->height, t->levels,
                         t->format, e);
}

d3d_texture *d3d_texture_new(d3d_device *dev, uint32_t rtype, uint32_t w, uint32_t h, uint32_t d,
    uint32_t levels, uint32_t usage, uint32_t format, uint32_t pool)
{
    const d3d_format *f = d3d_format_find(format);
    if (!f || !w || !h) return NULL;
    uint32_t full = mip_levels(w, h, rtype == D3DRTYPE_VOLUMETEXTURE ? d : 1);
    if (usage & D3DUSAGE_AUTOGENMIPMAP) levels = (levels == 0 || levels > 1) ? full : 1;
    if (!levels || levels > full) levels = full;
    d3d_texture *t = (d3d_texture *)calloc(1, sizeof(d3d_texture_rt));
    t->dev = dev;
    t->rtype = rtype;
    t->width = w; t->height = h; t->depth = d ? d : 1;
    t->levels = levels; t->usage = usage; t->format = format; t->pool = pool;
    t->fmt = f;
    t->faces = rtype == D3DRTYPE_CUBETEXTURE ? 6 : 1;
    t->target = rtype == D3DRTYPE_CUBETEXTURE ? GL_TEXTURE_CUBE_MAP : rtype == D3DRTYPE_VOLUMETEXTURE ? GL_TEXTURE_3D : GL_TEXTURE_2D;
    t->autogen_filter = 2;
    t->surfaces = (d3d_surface **)calloc((size_t)t->faces * levels, sizeof *t->surfaces);
    if (pool == D3DPOOL_MANAGED || pool == D3DPOOL_SYSTEMMEM || pool == D3DPOOL_SCRATCH)
        t->sysmem = (uint32_t *)calloc((size_t)t->faces * levels, sizeof *t->sysmem);
    if (pool != D3DPOOL_SYSTEMMEM && pool != D3DPOOL_SCRATCH && f->internal) {
        TEX_RT(t)->has_gl = 1;
        d3d_rt_call(run_texture_create, &t, sizeof t);
    }
    return t;
}

d3d_texture *d3d_texture_new_native(d3d_device *dev, uint32_t rtype, uint32_t w, uint32_t h, uint32_t levels,
    uint32_t usage, uint32_t format, uint32_t pool, const d3d_native_format *native)
{
    const d3d_format *f = d3d_format_find(format);
    if (!f || !native || !w || !h || (rtype != D3DRTYPE_TEXTURE && rtype != D3DRTYPE_CUBETEXTURE) ||
        (usage & (D3DUSAGE_RENDERTARGET | D3DUSAGE_DEPTHSTENCIL | D3DUSAGE_AUTOGENMIPMAP))) return NULL;
    uint32_t full = mip_levels(w, h, 1);
    if (!levels || levels > full) levels = full;
    d3d_texture *t = (d3d_texture *)calloc(1, sizeof(d3d_texture_rt));
    t->dev = dev;
    t->rtype = rtype;
    t->width = w; t->height = h; t->depth = 1;
    t->levels = levels; t->usage = usage; t->format = format; t->pool = pool;
    t->fmt = f;
    t->native = native;
    t->faces = rtype == D3DRTYPE_CUBETEXTURE ? 6 : 1;
    t->target = rtype == D3DRTYPE_CUBETEXTURE ? GL_TEXTURE_CUBE_MAP : GL_TEXTURE_2D;
    t->autogen_filter = 2;
    t->surfaces = (d3d_surface **)calloc((size_t)t->faces * levels, sizeof *t->surfaces);
    /* No system copy: the game never gets these blocks back (they are not DXT). */
    TEX_RT(t)->has_gl = 1;
    TEX_RT(t)->rt_native = native;      /* before the record: the render thread reads it there */
    d3d_rt_call(run_texture_create, &t, sizeof t);
    return t;
}

/* Converted blocks of a whole level, copied after the arguments. */
typedef struct { d3d_texture *t; uint32_t face, level, w, h, size; GLenum internal; } native_upload_args;

static void run_native_upload(void *args)
{
    const native_upload_args *a = (const native_upload_args *)args;
    d3d_texture *t = a->t;
    uint64_t start = void_perf_now_ns();
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glCompressedTexSubImage2D(face_target(t, a->face), (GLint)a->level, 0, 0, (GLsizei)a->w, (GLsizei)a->h, a->internal,
        (GLsizei)a->size, a + 1);
    GLenum e = glGetError();
    if (e) void_log("[d3d9] converted upload %ux%u level %u internal %04X: GL error %04X", a->w, a->h, a->level,
                    a->internal, e);
    void_perf_add(VOID_PERF_TEXTURE, void_perf_now_ns() - start, a->size);
}

static void record_native_upload(d3d_texture *t, uint32_t face, uint32_t level, uint32_t w, uint32_t h,
    const uint8_t *data, uint32_t size)
{
    native_upload_args *a = (native_upload_args *)d3d_rt_begin(run_native_upload, (uint32_t)sizeof *a + size);
    *a = (native_upload_args){ t, face, level, w, h, size, t->native->internal };
    memcpy(a + 1, data, size);
    d3d_rt_commit();
}

/* One whole level of a converted texture, as its blocks are stored. */
void d3d_texture_upload_native(d3d_texture *t, uint32_t face, uint32_t level, const uint8_t *data, uint32_t size)
{
    if (!TEX_RT(t)->has_gl || !t->native || level >= t->levels) return;
    uint32_t w, h;
    level_dims(t->width, t->height, level, &w, &h);
    if (size != d3d_native_size(t->native, w, h)) {
        void_log("[d3d9] converted level %u of %ux%u: %u bytes, %u expected", level, t->width, t->height, size,
                 d3d_native_size(t->native, w, h));
        return;
    }
    record_native_upload(t, face, level, w, h, data, size);
}

uint32_t d3d_wrap_texture(d3d_texture *t)
{
    void_com_class *cls = t->rtype == D3DRTYPE_CUBETEXTURE ? &cube_class : t->rtype == D3DRTYPE_VOLUMETEXTURE ? &volume_class : &texture_class;
    uint32_t guest = void_com_wrap(&t->com, cls, 0);
    t->com.destroy = texture_destroy;
    return guest;
}

uint32_t d3d_texture_surface(d3d_texture *t, uint32_t face, uint32_t level)
{
    if (level >= t->levels || face >= (uint32_t)t->faces) return 0;
    uint32_t index = face * t->levels + level;
    if (!t->surfaces[index]) {
        d3d_surface *s = (d3d_surface *)calloc(1, sizeof(d3d_surface_rt));
        s->dev = t->dev;
        level_dims(t->width, t->height, level, &s->width, &s->height);
        s->format = t->format; s->usage = t->usage; s->pool = t->pool;
        s->fmt = t->fmt;
        s->pitch = d3d_format_pitch(t->fmt, s->width);
        s->container = t;
        s->face = face;
        s->level = level;
        void_com_wrap(&s->com, &surface_class, 0);
        s->com.destroy = surface_destroy;
        t->surfaces[index] = s;
    }
    return t->surfaces[index]->com.guest;
}

/* Upload a w x h rect at (x, y) of a level from guest-layout data whose first
 * row (or block row) is at `data`. */
/* Guest-layout rows of a rect, copied after the arguments; converted there. */
typedef struct { d3d_texture *t; uint32_t face, level, x, y, w, h, pitch; } texture_upload_args;

static void run_texture_upload(void *args)
{
    const texture_upload_args *a = (const texture_upload_args *)args;
    d3d_texture *t = a->t;
    uint32_t face = a->face, level = a->level;
    void *owned;
    size_t size;
    uint64_t start = void_perf_now_ns();
    const void *gl_data = d3d_format_convert(t->fmt, (const uint8_t *)(a + 1), a->w, a->h, a->pitch, &owned, &size,
                                             (t->usage & D3DUSAGE_RENDERTARGET) != 0);
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    if (t->target == GL_TEXTURE_3D) {
        uint32_t d = t->depth >> level;
        if (!d) d = 1;
        glTexSubImage3D(GL_TEXTURE_3D, (GLint)level, (GLint)a->x, (GLint)a->y, 0, (GLsizei)a->w, (GLsizei)a->h, (GLsizei)d,
            t->fmt->format, t->fmt->type, gl_data);
    } else {
        glTexSubImage2D(face_target(t, face), (GLint)level, (GLint)a->x, (GLint)a->y, (GLsizei)a->w, (GLsizei)a->h,
            t->fmt->format, t->fmt->type, gl_data);
    }
    GLenum e = glGetError();
    if (e) void_log("[d3d9] upload %ux%u at %u,%u level %u format %u: GL error %04X", a->w, a->h, a->x, a->y, level,
                    t->format, e);
    free(owned);
    void_perf_add(VOID_PERF_TEXTURE, void_perf_now_ns() - start, size);
    if (level == 0 && (t->usage & D3DUSAGE_AUTOGENMIPMAP)) t->mips_dirty = 1;
}

void d3d_texture_upload_rect(d3d_texture *t, uint32_t face, uint32_t level, uint32_t x, uint32_t y, uint32_t w, uint32_t h,
    const uint8_t *data, uint32_t pitch)
{
    if (!TEX_RT(t)->has_gl || !w || !h) return;
    if (t->native) {
        uint32_t lw, lh;
        level_dims(t->width, t->height, level, &lw, &lh);
        uint32_t size = d3d_native_size(t->native, lw, lh);
        if (x || y || w != lw || h != lh || size > d3d_format_pitch(t->fmt, lw) * d3d_format_rows(t->fmt, lh)) {
            if (!t->native_lock_logged++)
                void_log("[d3d9] converted %ux%u texture: write %ux%u at %u,%u of level %u ignored", t->width, t->height,
                         w, h, x, y, level);
            return;
        }
        record_native_upload(t, face, level, lw, lh, data, size);
        (void)pitch;
        return;
    }
    /* What d3d_format_convert reads of the source: its rows, for volumes each slice. */
    uint32_t slices = 1;
    if (t->target == GL_TEXTURE_3D) { slices = t->depth >> level; if (!slices) slices = 1; }
    uint32_t bytes = slices > 1 ? pitch * d3d_format_rows(t->fmt, h) * slices
                                : pitch * (d3d_format_rows(t->fmt, h) - 1u) + d3d_format_pitch(t->fmt, w);
    texture_upload_args *a = (texture_upload_args *)d3d_rt_begin(run_texture_upload, (uint32_t)sizeof *a + bytes);
    *a = (texture_upload_args){ t, face, level, x, y, w, h, pitch };
    memcpy(a + 1, data, bytes);
    d3d_rt_commit();
}

void d3d_texture_upload_level(d3d_texture *t, uint32_t face, uint32_t level, const uint8_t *data, uint32_t pitch)
{
    uint32_t w, h;
    level_dims(t->width, t->height, level, &w, &h);
    d3d_texture_upload_rect(t, face, level, 0, 0, w, h, data, pitch);
}

static void gl_generate_mips(d3d_texture *t)
{
    if (!t->gl || t->levels < 2 || TEX_RT(t)->rt_native) return;   /* converted textures store every level */
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glGenerateMipmap(t->target);
    t->mips_dirty = 0;
}

static void run_generate_mips(void *args) { gl_generate_mips(*(d3d_texture **)args); }

/* Draws (render thread) and GenerateMipSubLevels (the game's). */
void d3d_generate_mips(d3d_texture *t)
{
    if (d3d_rt_executing()) gl_generate_mips(t);
    else d3d_rt_call(run_generate_mips, &t, sizeof t);
}

typedef struct { d3d_texture *t; uint32_t lod; } lod_args;
static void run_set_lod(void *args) { const lod_args *a = (const lod_args *)args; TEX_RT(a->t)->rt_lod = a->lod; }

#define TEX ((d3d_texture *)void_com_host(THIS_))

COM_METHOD(tex, QueryInterface, 3)
{
    d3d_texture *t = TEX;
    /* Each texture kind answers its own interface only: the renderer tells
     * 2D, cube and volume textures apart with these queries. */
    const uint8_t *own = t->rtype == D3DRTYPE_CUBETEXTURE ? IID_IDirect3DCubeTexture9
                       : t->rtype == D3DRTYPE_VOLUMETEXTURE ? IID_IDirect3DVolumeTexture9 : IID_IDirect3DTexture9;
    if (void_guid_equal(ARG(1), own) ||
        void_guid_equal(ARG(1), IID_IDirect3DBaseTexture9) || void_guid_equal(ARG(1), IID_IDirect3DResource9) ||
        void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&t->com);
        MEM32(ARG(2)) = THIS_;
        return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(tex, AddRef, 1) { return void_com_addref(&TEX->com); }
COM_METHOD(tex, Release, 1) { return void_com_release(&TEX->com); }
COM_METHOD(tex, GetDevice, 2) { d3d_texture *t = TEX; void_com_addref(&t->dev->com); MEM32(ARG(1)) = t->dev->com.guest; return D3D_OK; }
COM_METHOD(tex, SetPrivateData, 5) { return D3D_OK; }
COM_METHOD(tex, GetPrivateData, 4) { return D3DERR_NOTFOUND; }
COM_METHOD(tex, FreePrivateData, 2) { return D3D_OK; }
COM_METHOD(tex, SetPriority, 2) { return 0; }
COM_METHOD(tex, GetPriority, 1) { return 0; }
COM_METHOD(tex, PreLoad, 1) { return 0; }
COM_METHOD(tex, GetType, 1) { return TEX->rtype; }
COM_METHOD(tex, SetLOD, 2)
{
    d3d_texture *t = TEX;
    uint32_t old = t->lod;
    t->lod = ARG(1) < t->levels ? ARG(1) : t->levels - 1;
    if (t->lod != old) { lod_args a = { t, t->lod }; d3d_rt_call(run_set_lod, &a, sizeof a); }
    return old;
}
COM_METHOD(tex, GetLOD, 1) { return TEX->lod; }
COM_METHOD(tex, GetLevelCount, 1) { d3d_texture *t = TEX; return (t->usage & D3DUSAGE_AUTOGENMIPMAP) ? 1 : t->levels; }
COM_METHOD(tex, SetAutoGenFilterType, 2) { TEX->autogen_filter = ARG(1); return D3D_OK; }
COM_METHOD(tex, GetAutoGenFilterType, 1) { return TEX->autogen_filter; }
COM_METHOD(tex, GenerateMipSubLevels, 1) { d3d_generate_mips(TEX); return 0; }

static uint32_t level_desc(d3d_texture *t, uint32_t level, uint32_t out)
{
    if (level >= t->levels) return D3DERR_INVALIDCALL;
    uint32_t w, h;
    level_dims(t->width, t->height, level, &w, &h);
    MEM32(out) = t->format; MEM32(out + 4) = D3DRTYPE_SURFACE; MEM32(out + 8) = t->usage; MEM32(out + 12) = t->pool;
    MEM32(out + 16) = 0; MEM32(out + 20) = 0; MEM32(out + 24) = w; MEM32(out + 28) = h;
    return D3D_OK;
}

COM_METHOD(tex, GetLevelDesc, 3) { return level_desc(TEX, ARG(1), ARG(2)); }
COM_METHOD(tex, GetSurfaceLevel, 3)
{
    d3d_texture *t = TEX;
    uint32_t s = d3d_texture_surface(t, 0, ARG(1));
    if (!s) return D3DERR_INVALIDCALL;
    void_com_addref(&t->com);
    MEM32(ARG(2)) = s;
    return D3D_OK;
}

/* LockRect on the texture is LockRect on its level surface. */
static uint32_t surface_call(uint32_t surface_guest, int method, int nargs, const uint32_t *args)
{
    uint32_t call_args[4];
    call_args[0] = surface_guest;
    for (int i = 0; i < nargs; ++i) call_args[i + 1] = args[i];
    uint32_t vt = MEM32(surface_guest);
    return void_call_guest(MEM32(vt + 4u * (uint32_t)method), nargs + 1, call_args, 1);
}

COM_METHOD(tex, LockRect, 5)
{
    uint32_t s = d3d_texture_surface(TEX, 0, ARG(1));
    if (!s) return D3DERR_INVALIDCALL;
    uint32_t args[3] = { ARG(2), ARG(3), ARG(4) };
    return surface_call(s, 13, 3, args);
}
COM_METHOD(tex, UnlockRect, 2)
{
    uint32_t s = d3d_texture_surface(TEX, 0, ARG(1));
    if (!s) return D3DERR_INVALIDCALL;
    return surface_call(s, 14, 0, NULL);
}
COM_METHOD(tex, AddDirtyRect, 2) { return D3D_OK; }

static const void_fn texture_methods[] = {
    tex_QueryInterface, tex_AddRef, tex_Release, tex_GetDevice, tex_SetPrivateData, tex_GetPrivateData,
    tex_FreePrivateData, tex_SetPriority, tex_GetPriority, tex_PreLoad, tex_GetType, tex_SetLOD, tex_GetLOD,
    tex_GetLevelCount, tex_SetAutoGenFilterType, tex_GetAutoGenFilterType, tex_GenerateMipSubLevels,
    tex_GetLevelDesc, tex_GetSurfaceLevel, tex_LockRect, tex_UnlockRect, tex_AddDirtyRect,
};
static void_com_class texture_class = { "IDirect3DTexture9", 22, texture_methods, 0 };

COM_METHOD(cube, GetCubeMapSurface, 4)
{
    d3d_texture *t = TEX;
    uint32_t s = d3d_texture_surface(t, ARG(1), ARG(2));
    if (!s) return D3DERR_INVALIDCALL;
    void_com_addref(&t->com);
    MEM32(ARG(3)) = s;
    return D3D_OK;
}
COM_METHOD(cube, LockRect, 6)
{
    uint32_t s = d3d_texture_surface(TEX, ARG(1), ARG(2));
    if (!s) return D3DERR_INVALIDCALL;
    uint32_t args[3] = { ARG(3), ARG(4), ARG(5) };
    return surface_call(s, 13, 3, args);
}
COM_METHOD(cube, UnlockRect, 3)
{
    uint32_t s = d3d_texture_surface(TEX, ARG(1), ARG(2));
    if (!s) return D3DERR_INVALIDCALL;
    return surface_call(s, 14, 0, NULL);
}
COM_METHOD(cube, AddDirtyRect, 3) { return D3D_OK; }

static const void_fn cube_methods[] = {
    tex_QueryInterface, tex_AddRef, tex_Release, tex_GetDevice, tex_SetPrivateData, tex_GetPrivateData,
    tex_FreePrivateData, tex_SetPriority, tex_GetPriority, tex_PreLoad, tex_GetType, tex_SetLOD, tex_GetLOD,
    tex_GetLevelCount, tex_SetAutoGenFilterType, tex_GetAutoGenFilterType, tex_GenerateMipSubLevels,
    tex_GetLevelDesc, cube_GetCubeMapSurface, cube_LockRect, cube_UnlockRect, cube_AddDirtyRect,
};
static void_com_class cube_class = { "IDirect3DCubeTexture9", 22, cube_methods, 0 };

COM_TODO(vol, GetVolumeLevel)
COM_TODO(vol, LockBox)
COM_TODO(vol, UnlockBox)
COM_METHOD(vol, AddDirtyBox, 2) { return D3D_OK; }
static const void_fn volume_methods[] = {
    tex_QueryInterface, tex_AddRef, tex_Release, tex_GetDevice, tex_SetPrivateData, tex_GetPrivateData,
    tex_FreePrivateData, tex_SetPriority, tex_GetPriority, tex_PreLoad, tex_GetType, tex_SetLOD, tex_GetLOD,
    tex_GetLevelCount, tex_SetAutoGenFilterType, tex_GetAutoGenFilterType, tex_GenerateMipSubLevels,
    tex_GetLevelDesc, vol_GetVolumeLevel, vol_LockBox, vol_UnlockBox, vol_AddDirtyBox,
};
static void_com_class volume_class = { "IDirect3DVolumeTexture9", 22, volume_methods, 0 };

/* UpdateSurface / UpdateTexture: system memory -> default pool. */
void d3d_update_surface(d3d_surface *src, uint32_t src_rect, d3d_surface *dst, uint32_t dst_point)
{
    if (!src->sysmem) { void_log("[d3d9] UpdateSurface from a non-system surface"); return; }
    if (src_rect || dst_point) void_log("[d3d9] UpdateSurface with rectangles: whole surface copied");
    dst->lock_mem = src->sysmem;
    d3d_surface_upload(dst);
    dst->lock_mem = 0;
}

void d3d_update_texture(d3d_texture *src, d3d_texture *dst)
{
    if (!src->sysmem) { void_log("[d3d9] UpdateTexture from a non-system texture"); return; }
    if (src->fmt->block_bytes && dst->fmt == src->fmt) texture_set_storage(dst, src->native);
    for (int f = 0; f < src->faces; ++f) {
        for (uint32_t l = 0; l < src->levels && l < dst->levels; ++l) {
            uint32_t mem = src->sysmem[f * (int)src->levels + (int)l];
            if (!mem) continue;
            uint32_t w, h;
            level_dims(src->width, src->height, l, &w, &h);
            d3d_texture_upload_level(dst, (uint32_t)f, l, (const uint8_t *)GPTR(mem), d3d_format_pitch(src->fmt, w));
        }
    }
}

/* ================================================================= buffers */
static void_com_class vbuffer_class, ibuffer_class;

/* The guest copy (shadow) is what Lock returns and what the render thread
 * uploads from, at the draws that need it. It is never written under the
 * render thread: a DISCARD lock while records not yet run read the copy gets
 * a fresh one (D3D's renaming), a lock without NOOVERWRITE waits until they
 * have run, and NOOVERWRITE promises not to touch what they read. Copies the
 * render thread may still read are retired, then freed (or reused) once it is
 * past them. */
typedef struct { uint32_t shadow, size; uint64_t at; } retired_shadow;
static retired_shadow *retired;
static uint32_t retired_count, retired_cap;
static uint64_t shadow_renames, shadow_waits;

static void shadow_retire(uint32_t shadow, uint32_t size, uint64_t at)
{
    if (d3d_rt_reached(at)) { void_gfree(shadow); return; }
    if (retired_count == retired_cap) {
        uint32_t cap = retired_cap ? retired_cap * 2 : 64;
        retired_shadow *grown = (retired_shadow *)realloc(retired, cap * sizeof *grown);
        if (!grown) { d3d_rt_wait_for(at); void_gfree(shadow); return; }
        retired = grown; retired_cap = cap;
    }
    retired[retired_count++] = (retired_shadow){ shadow, size, at };
}

/* Frees the retired copies the render thread is past; returns one of `size` for reuse, if asked. */
static uint32_t shadow_collect(uint32_t size)
{
    uint32_t reuse = 0;
    for (uint32_t i = 0; i < retired_count;) {
        if (!d3d_rt_reached(retired[i].at)) { ++i; continue; }
        if (!reuse && size && retired[i].size == size) reuse = retired[i].shadow;
        else void_gfree(retired[i].shadow);
        retired[i] = retired[--retired_count];
    }
    return reuse;
}

static void run_buffer_free(void *args)
{
    d3d_buffer *b = *(d3d_buffer **)args;
    if (b->gl) { d3d_gl_forget_buffer(b->gl); glDeleteBuffers(1, &b->gl); }
    free(b->dirty_pages);
    free(b);
}

static void buffer_destroy(void_com_object *o)
{
    d3d_buffer *b = (d3d_buffer *)o;
    uint32_t shadow = b->shadow, size = b->size;
    d3d_rt_call(run_buffer_free, &b, sizeof b);
    if (shadow) shadow_retire(shadow, size, d3d_rt_position());
    shadow_collect(0);
}

static void run_buffer_create(void *args)
{
    d3d_buffer *b = *(d3d_buffer **)args;
    glGenBuffers(1, &b->gl);
    /* Created through the copy target, which no vertex array object records. */
    glBindBuffer(GL_COPY_WRITE_BUFFER, b->gl);
    glBufferData(GL_COPY_WRITE_BUFFER, b->size, NULL, (b->usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
}

uint32_t d3d_buffer_create(d3d_device *dev, int index, uint32_t length, uint32_t usage, uint32_t format, uint32_t pool)
{
    if (!length) return 0;
    d3d_buffer *b = (d3d_buffer *)calloc(1, sizeof(d3d_buffer_rt));
    b->dev = dev; b->index = index; b->size = length; b->usage = usage; b->format = format; b->pool = pool;
    b->shadow = void_galloc(length);
    if (!b->shadow) { free(b); return 0; }
    BUF_RT(b)->rt_shadow = b->shadow;
    b->dirty_lo = 0xFFFFFFFFu;
    d3d_rt_call(run_buffer_create, &b, sizeof b);
    uint32_t guest = void_com_wrap(&b->com, index ? &ibuffer_class : &vbuffer_class, 0);
    b->com.destroy = buffer_destroy;
    return guest;
}

void d3d_buffer_read_by(d3d_buffer *b, uint64_t position) { BUF_RT(b)->read_at = position; }

/* A pooled allocator may Lock(0, 0, NOOVERWRITE), modify a few suballocations,
 * then unlock before drawing just one of them. Keep the unconsumed pages dirty;
 * the declared lock extent is not the number of bytes a draw needs. */
#define BUFFER_PAGE_SIZE 4096u
static void buffer_dirty_pages(d3d_buffer *b, uint32_t lo, uint32_t hi)
{
    if (!b->dirty_pages || lo >= hi) return;
    if (!lo && hi == b->size) {
        memset(b->dirty_pages, 1, b->page_count); b->dirty_page_count = b->page_count; return;
    }
    uint32_t first = lo / BUFFER_PAGE_SIZE, last = (hi - 1u) / BUFFER_PAGE_SIZE;
    for (uint32_t page = first; page <= last; ++page)
        if (!b->dirty_pages[page]) { b->dirty_pages[page] = 1; ++b->dirty_page_count; }
}

void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi);

/* Flush every pending byte when no narrower draw extent is available. */
void d3d_buffer_flush(d3d_buffer *b)
{
    if (b->dirty_pages) { d3d_buffer_flush_range(b, 0, b->size); return; }
    if (b->dirty_lo >= b->dirty_hi) return;
    /* Upload through the copy target: it belongs to no vertex array object,
     * so neither the bound VAO's element buffer nor its attributes change. */
    GLenum target = GL_COPY_WRITE_BUFFER;
    glBindBuffer(target, b->gl);
    const uint8_t *src = (const uint8_t *)GPTR(BUF_RT(b)->rt_shadow) + b->dirty_lo;
    uint32_t length = b->dirty_hi - b->dirty_lo;
    if (b->discard_pending) {
        /* DISCARD invalidates the whole buffer, even for a partial lock. */
        glBufferData(target, b->size, NULL, (b->usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
        glBufferSubData(target, b->dirty_lo, length, src);
    } else if (b->dirty_lo == 0 && b->dirty_hi >= b->size) {
        glBufferData(target, b->size, GPTR(BUF_RT(b)->rt_shadow), (b->usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
    } else if (!b->overwrite_pending) {
        /* Only D3DLOCK_NOOVERWRITE locks: the game promises not to touch what
         * queued draws read, so write without waiting for the GPU. A plain
         * glBufferSubData into a buffer in flight makes Mali copy the whole
         * buffer or stall (map: CPU-skinned segments appended draw by draw). */
        void *dst = glMapBufferRange(target, b->dirty_lo, length,
            GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT | GL_MAP_INVALIDATE_RANGE_BIT);
        if (dst) {
            memcpy(dst, src, length);
            glUnmapBuffer(target);
        } else {
            glBufferSubData(target, b->dirty_lo, length, src);
        }
    } else {
        glBufferSubData(target, b->dirty_lo, length, src);
    }
    b->dirty_lo = 0xFFFFFFFFu;
    b->dirty_hi = 0;
    b->discard_pending = 0;
    b->overwrite_pending = 0;
}

void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi)
{
    if (!b->dirty_pages) { d3d_buffer_flush(b); return; }
    if (hi > b->size) hi = b->size;
    if (lo >= hi || !b->dirty_page_count) return;
    glBindBuffer(GL_COPY_WRITE_BUFFER, b->gl);
    if (b->discard_pending) {
        glBufferData(GL_COPY_WRITE_BUFFER, b->size, NULL,
            (b->usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
        b->discard_pending = 0;
    }
    uint32_t page = lo / BUFFER_PAGE_SIZE, end = (hi - 1u) / BUFFER_PAGE_SIZE + 1u;
    while (page < end) {
        if (!b->dirty_pages[page]) { ++page; continue; }
        uint32_t first = page;
        do { b->dirty_pages[page++] = 0; --b->dirty_page_count; }
        while (page < end && b->dirty_pages[page]);
        uint32_t start = first * BUFFER_PAGE_SIZE;
        uint32_t stop = page == b->page_count ? b->size : page * BUFFER_PAGE_SIZE;
        /* Page expansion can include unchanged bytes still used by earlier
         * draws. Synchronized SubData, never an unsynchronized map, is required. */
        glBufferSubData(GL_COPY_WRITE_BUFFER, start, stop - start,
            (const uint8_t *)GPTR(BUF_RT(b)->rt_shadow) + start);
    }
    if (!b->dirty_page_count) {
        b->dirty_lo = 0xFFFFFFFFu; b->dirty_hi = 0; b->overwrite_pending = 0;
    }
}

#define BUF ((d3d_buffer *)void_com_host(THIS_))
COM_METHOD(buf, QueryInterface, 3)
{
    d3d_buffer *b = BUF;
    if (void_guid_equal(ARG(1), b->index ? IID_IDirect3DIndexBuffer9 : IID_IDirect3DVertexBuffer9) ||
        void_guid_equal(ARG(1), IID_IDirect3DResource9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&b->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(buf, AddRef, 1) { return void_com_addref(&BUF->com); }
COM_METHOD(buf, Release, 1) { return void_com_release(&BUF->com); }
COM_METHOD(buf, GetDevice, 2) { d3d_buffer *b = BUF; void_com_addref(&b->dev->com); MEM32(ARG(1)) = b->dev->com.guest; return D3D_OK; }
COM_METHOD(buf, SetPrivateData, 5) { return D3D_OK; }
COM_METHOD(buf, GetPrivateData, 4) { return D3DERR_NOTFOUND; }
COM_METHOD(buf, FreePrivateData, 2) { return D3D_OK; }
COM_METHOD(buf, SetPriority, 2) { return 0; }
COM_METHOD(buf, GetPriority, 1) { return 0; }
COM_METHOD(buf, PreLoad, 1) { return 0; }
COM_METHOD(buf, GetType, 1) { return BUF->index ? D3DRTYPE_INDEXBUFFER : D3DRTYPE_VERTEXBUFFER; }

/* The lock's bookkeeping, on the render thread, in order with the draws: what
 * becomes dirty, and (fresh) the copy its records read from here on. */
typedef struct { d3d_buffer *b; uint32_t offset, size, flags, fresh; } lock_args;

static void run_buffer_lock(void *args)
{
    const lock_args *a = (const lock_args *)args;
    d3d_buffer *b = a->b;
    uint32_t offset = a->offset, size = a->size, flags = a->flags;
    if (a->fresh) BUF_RT(b)->rt_shadow = a->fresh;
    ++BUF_RT(b)->rt_locks;
    if (!(flags & D3DLOCK_READONLY)) {
        b->bounds_count = 0;
        if (!b->dirty_pages && !offset && size == b->size && (flags & D3DLOCK_NOOVERWRITE)) {
            uint32_t pages = b->size / BUFFER_PAGE_SIZE + (b->size % BUFFER_PAGE_SIZE != 0);
            b->dirty_pages = (uint8_t *)calloc(pages, 1);
            if (b->dirty_pages) {
                b->page_count = pages;
                buffer_dirty_pages(b, b->dirty_lo, b->dirty_hi);
            }
        }
        if (offset < b->dirty_lo) b->dirty_lo = offset;
        if (offset + size > b->dirty_hi) b->dirty_hi = offset + size;
        if (flags & D3DLOCK_DISCARD) {
            b->discard_pending = 1;
            /* Bytes outside a DISCARD lock are undefined. Restoring the CPU
             * shadow on a later draw is one valid choice for those bytes. */
            buffer_dirty_pages(b, 0, b->size);
        }
        else if (!(flags & D3DLOCK_NOOVERWRITE)) b->overwrite_pending = 1;
        buffer_dirty_pages(b, offset, offset + size);
    }
}

COM_METHOD(buf, Lock, 5)
{
    d3d_buffer *b = BUF;
    uint32_t offset = ARG(1), size = ARG(2), out = ARG(3), flags = ARG(4);
    if (offset > b->size) return D3DERR_INVALIDCALL;
    if (!size || size > b->size - offset) size = b->size - offset;
    uint32_t fresh = 0, old = 0;
    if (!(flags & D3DLOCK_READONLY) && !d3d_rt_reached(BUF_RT(b)->read_at)) {
        if (flags & D3DLOCK_DISCARD) {
            fresh = shadow_collect(b->size);
            if (!fresh) fresh = void_galloc(b->size);
            if (fresh) { old = b->shadow; b->shadow = fresh; ++shadow_renames; }
        }
        if (!fresh && !(flags & D3DLOCK_NOOVERWRITE)) {
            ++shadow_waits;
            d3d_rt_wait_for(BUF_RT(b)->read_at);
        }
    }
    lock_args a = { b, offset, size, flags, fresh };
    d3d_rt_call(run_buffer_lock, &a, sizeof a);
    if (old) shadow_retire(old, b->size, d3d_rt_position());
    ++b->locks;
    MEM32(out) = b->shadow + offset;
    return D3D_OK;
}

static void run_buffer_unlock(void *args)
{
    d3d_buffer *b = *(d3d_buffer **)args;
    if (--BUF_RT(b)->rt_locks == 0 && !b->dirty_pages) d3d_buffer_flush(b);
}

COM_METHOD(buf, Unlock, 1)
{
    d3d_buffer *b = BUF;
    if (!b->locks) return D3DERR_INVALIDCALL;
    --b->locks;
    d3d_rt_call(run_buffer_unlock, &b, sizeof b);
    BUF_RT(b)->read_at = d3d_rt_position();     /* the flush reads the copy */
    return D3D_OK;
}

COM_METHOD(buf, GetDesc, 2)
{
    d3d_buffer *b = BUF;
    uint32_t d = ARG(1);
    MEM32(d) = b->index ? b->format : 100u;          /* D3DFMT_VERTEXDATA */
    MEM32(d + 4) = b->index ? D3DRTYPE_INDEXBUFFER : D3DRTYPE_VERTEXBUFFER;
    MEM32(d + 8) = b->usage; MEM32(d + 12) = b->pool; MEM32(d + 16) = b->size;
    if (!b->index) MEM32(d + 20) = b->format;          /* FVF */
    return D3D_OK;
}

static const void_fn buffer_methods[] = {
    buf_QueryInterface, buf_AddRef, buf_Release, buf_GetDevice, buf_SetPrivateData, buf_GetPrivateData,
    buf_FreePrivateData, buf_SetPriority, buf_GetPriority, buf_PreLoad, buf_GetType, buf_Lock, buf_Unlock, buf_GetDesc,
};
static void_com_class vbuffer_class = { "IDirect3DVertexBuffer9", 14, buffer_methods, 0 };
static void_com_class ibuffer_class = { "IDirect3DIndexBuffer9", 14, buffer_methods, 0 };

/* ===================================================== vertex declarations */
static void_com_class decl_class;

static void run_decl_free(void *args) { free(*(d3d_decl **)args); }
static void decl_destroy(void_com_object *o)
{
    d3d_decl *d = (d3d_decl *)o;
    d3d_rt_call(run_decl_free, &d, sizeof d);
}

static void decl_add(d3d_decl *d, uint16_t stream, uint16_t offset, uint8_t type, uint8_t usage, uint8_t index)
{
    if (d->count >= 64) return;
    d3d_vertex_element *e = &d->elements[d->count++];
    e->stream = stream; e->offset = offset; e->type = type; e->method = 0; e->usage = usage; e->usage_index = index;
}

static const uint8_t type_sizes[] = {4, 8, 12, 16, 4, 4, 4, 8, 4, 4, 8, 4, 8, 4, 4, 4, 8, 0};

uint32_t d3d_decl_create(d3d_device *dev, uint32_t elements, uint32_t fvf)
{
    d3d_decl *d = (d3d_decl *)calloc(1, sizeof *d);
    d->dev = dev;
    d->fvf = fvf;
    if (elements) {
        for (uint32_t e = elements; MEM16(e) != 0xFF && d->count < 64; e += 8)
            decl_add(d, MEM16(e), MEM16(e + 2), MEM8(e + 4), MEM8(e + 6), MEM8(e + 7));
    } else {
        uint16_t off = 0;
        uint32_t pos = fvf & 0x400E;
        if (pos == 0x002) { decl_add(d, 0, off, 2, 0, 0); off += 12; }
        else if (pos == 0x004) { decl_add(d, 0, off, 3, 9, 0); off += 16; }
        else if (pos == 0x4002) { decl_add(d, 0, off, 3, 0, 0); off += 16; }
        else if (pos >= 0x006 && pos <= 0x00E) {
            int betas = (int)((pos - 0x004) / 2);    /* XYZB1 = 0x006 ... XYZB5 = 0x00E */
            decl_add(d, 0, off, 2, 0, 0); off += 12;
            int indexed = (fvf & 0x1000u) || (fvf & 0x8000u);
            int weights = betas - (indexed ? 1 : 0);
            if (weights > 0) { decl_add(d, 0, off, (uint8_t)(weights - 1), 1, 0); off += (uint16_t)(4 * weights); }
            if (indexed) { decl_add(d, 0, off, (fvf & 0x8000u) ? 4 : 5, 2, 0); off += 4; }
        }
        if (fvf & 0x010) { decl_add(d, 0, off, 2, 3, 0); off += 12; }
        if (fvf & 0x020) { decl_add(d, 0, off, 0, 4, 0); off += 4; }
        if (fvf & 0x040) { decl_add(d, 0, off, 4, 10, 0); off += 4; }
        if (fvf & 0x080) { decl_add(d, 0, off, 4, 10, 1); off += 4; }
        uint32_t texcount = (fvf >> 8) & 15;
        for (uint32_t i = 0; i < texcount; ++i) {
            uint32_t fmt = (fvf >> (16 + 2 * i)) & 3;
            static const uint8_t types[4] = {1, 2, 3, 0};
            static const uint8_t sizes[4] = {8, 12, 16, 4};
            decl_add(d, 0, off, types[fmt], 5, (uint8_t)i);
            off += sizes[fmt];
        }
    }
    uint32_t guest = void_com_wrap(&d->com, &decl_class, 0);
    d->com.destroy = decl_destroy;
    return guest;
}

#define DECL ((d3d_decl *)void_com_host(THIS_))
COM_METHOD(decl, QueryInterface, 3)
{
    if (void_guid_equal(ARG(1), IID_IDirect3DVertexDeclaration9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&DECL->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(decl, AddRef, 1) { return void_com_addref(&DECL->com); }
COM_METHOD(decl, Release, 1) { return void_com_release(&DECL->com); }
COM_METHOD(decl, GetDevice, 2) { d3d_decl *d = DECL; void_com_addref(&d->dev->com); MEM32(ARG(1)) = d->dev->com.guest; return D3D_OK; }
COM_METHOD(decl, GetDeclaration, 3)
{
    d3d_decl *d = DECL;
    uint32_t out = ARG(1), count = ARG(2);
    if (out) {
        for (int i = 0; i < d->count; ++i) {
            uint32_t e = out + 8u * (uint32_t)i;
            MEM16(e) = d->elements[i].stream; MEM16(e + 2) = d->elements[i].offset;
            MEM8(e + 4) = d->elements[i].type; MEM8(e + 5) = d->elements[i].method;
            MEM8(e + 6) = d->elements[i].usage; MEM8(e + 7) = d->elements[i].usage_index;
        }
        uint32_t end = out + 8u * (uint32_t)d->count;
        MEM16(end) = 0xFF; MEM16(end + 2) = 0; MEM8(end + 4) = 17; MEM8(end + 5) = 0; MEM8(end + 6) = 0; MEM8(end + 7) = 0;
    }
    MEM32(count) = (uint32_t)d->count + 1;
    return D3D_OK;
}
static const void_fn decl_methods[] = { decl_QueryInterface, decl_AddRef, decl_Release, decl_GetDevice, decl_GetDeclaration };
static void_com_class decl_class = { "IDirect3DVertexDeclaration9", 5, decl_methods, 0 };

/* ================================================================= queries */
static void_com_class query_class;
#define QRY ((d3d_query *)void_com_host(THIS_))

/* Occlusion queries borrow a GL query object from a pool of at most QUERY_POOL for one BEGIN..result
 * span: `gl` is 1 + the borrowed entry (0: none), `ended` the result state. PowerVR's GLES driver
 * (DXT-48-1536, build 26.1) answers ANY_SAMPLES_PASSED with false zeros once more than 1024 query
 * objects take turns (device probe: 1536 objects in random order, ~5% of the results; 1024 objects,
 * random or LIFO, none), and UE3 keeps a D3D9 query per tested primitive, so meshes blinked on WAR-Torlan. */
#define QUERY_POOL 1024
enum { QUERY_NONE, QUERY_PENDING, QUERY_HIDDEN, QUERY_VISIBLE };
static GLuint query_names[QUERY_POOL];
static d3d_query *query_owners[QUERY_POOL];
static uint16_t query_free[QUERY_POOL];
static uint32_t query_free_count, query_count, query_live, query_unbacked, query_collected_frame = ~0u;

static void query_release(d3d_query *q)
{
    if (!q->gl) return;
    query_owners[q->gl - 1] = NULL;
    query_free[query_free_count++] = (uint16_t)(q->gl - 1);
    q->gl = 0;
}

/* The render thread publishes a result for the game's thread: the serial of
 * the end it belongs to and the state (release: the game reads it as is). */
static void query_publish(d3d_query *q, uint32_t state)
{
    atomic_store_explicit(&QRY_RT(q)->answer, QRY_RT(q)->rt_serial << 2 | state, memory_order_release);
}

/* Keeps a finished result in the query and gives the GL object back; 0 while the GPU is not done. */
static int query_collect(d3d_query *q)
{
    GLuint available = 0, any = 0;
    glGetQueryObjectuiv(query_names[q->gl - 1], GL_QUERY_RESULT_AVAILABLE, &available);
    if (!available) return 0;
    glGetQueryObjectuiv(query_names[q->gl - 1], GL_QUERY_RESULT, &any);
    q->ended = any ? QUERY_VISIBLE : QUERY_HIDDEN;
    query_release(q);
    query_publish(q, (uint32_t)q->ended);
    return 1;
}

static uint32_t query_take(d3d_query *q)
{
    if (!query_free_count && query_count < QUERY_POOL) {
        glGenQueries(1, &query_names[query_count]);
        query_free[query_free_count++] = (uint16_t)query_count++;
        if (query_count == 256 || query_count == 512 || query_count == QUERY_POOL)
            void_log("[gl] occlusion query pool %u (%u D3D9 queries)", query_count, query_live);
    }
    /* Pool used up: once a frame, collect the finished results nobody read (UE3 pools queries it
     * stopped asking about). A query without a GL object then measures nothing and counts as visible. */
    if (!query_free_count && query_collected_frame != d3d_rt_device()->frame) {
        query_collected_frame = d3d_rt_device()->frame;
        for (uint32_t i = 0; i < query_count; ++i)
            if (query_owners[i] && query_owners[i]->ended == QUERY_PENDING) query_collect(query_owners[i]);
    }
    if (!query_free_count) {
        if (query_unbacked++ % 4096 == 0)
            void_log("[gl] occlusion query pool full: %u queries counted as visible (%u D3D9 queries)", query_unbacked, query_live);
        return 0;
    }
    uint32_t slot = query_free[--query_free_count];
    query_owners[slot] = q;
    return slot + 1;
}

/* Results the render thread looks for unasked: every end it runs joins a
 * queue in submission order, and between batches of records and while idle
 * (d3d_rt_set_idle) it publishes what the GPU has finished from the front, so
 * the game's first poll usually finds the answer. The GPU finishes in order:
 * the first unfinished entry ends a look. Entries of a query begun again or
 * destroyed since are skipped (serial) or removed. */
typedef struct { d3d_query *q; uint32_t serial; } watched;
static watched *watch;
static uint32_t watch_head, watch_count, watch_cap;     /* a ring of watch_cap entries */
static _Atomic uint64_t poll_answered_idle;
static int watch_flushed = 1;                           /* GL work flushed since the last end */

static void watch_push(d3d_query *q)
{
    if (!d3d_rt_threaded()) return;                    /* inline, every poll of the game's looks */
    if (watch_count == watch_cap) {
        uint32_t cap = watch_cap ? watch_cap * 2 : 1024;
        watched *grown = (watched *)malloc(cap * sizeof *grown);
        if (!grown) return;                             /* the game's own polls still ask */
        for (uint32_t i = 0; i < watch_count; ++i) grown[i] = watch[(watch_head + i) % watch_cap];
        free(watch);
        watch = grown; watch_cap = cap; watch_head = 0;
    }
    watch[(watch_head + watch_count++) % watch_cap] = (watched){ q, QRY_RT(q)->rt_serial };
    watch_flushed = 0;
}

static void watch_remove(d3d_query *q)
{
    for (uint32_t i = 0; i < watch_count; ++i)
        if (watch[(watch_head + i) % watch_cap].q == q) watch[(watch_head + i) % watch_cap].q = NULL;
}

/* Whether the result of q's last end is known now; publishes it if so. */
static int query_answer(d3d_query *q)
{
    if (q->type == 8) {
        if (q->fence) {
            GLenum r = glClientWaitSync(q->fence, 0, 0);
            if (r == GL_TIMEOUT_EXPIRED) return 0;
        }
        query_publish(q, 1);
        return 1;
    }
    if (q->ended == QUERY_PENDING && (!q->gl || !query_collect(q))) return 0;
    query_publish(q, q->ended == QUERY_HIDDEN ? QUERY_HIDDEN : QUERY_VISIBLE);
    return 1;
}

static int answered(d3d_query *q)
{
    uint32_t a = atomic_load_explicit(&QRY_RT(q)->answer, memory_order_relaxed);
    return a >> 2 == (QRY_RT(q)->rt_serial & 0x3FFFFFFFu) && (a & 3u);
}

int d3d_query_watch(int idle)
{
    while (watch_count) {
        watched *e = &watch[watch_head];
        d3d_query *q = e->q;
        if (q && QRY_RT(q)->rt_serial == e->serial && !answered(q)) {
            if (!query_answer(q)) break;
            atomic_fetch_add_explicit(&poll_answered_idle, 1, memory_order_relaxed);
        }
        watch_head = (watch_head + 1) % watch_cap;
        --watch_count;
    }
    /* Out of records with results outstanding: hand the GPU what it has. */
    if (idle && watch_count && !watch_flushed) { glFlush(); watch_flushed = 1; }
    return watch_count != 0;
}

typedef struct { d3d_query *q; uint32_t flush; } poll_args;

/* The game asked and found no answer: look now (after submitting queued work
 * when it said D3DGETDATA_FLUSH); the queue answers later otherwise. */
static void run_query_poll(void *args)
{
    const poll_args *a = (const poll_args *)args;
    d3d_query *q = a->q;
    if (a->flush) { glFlush(); watch_flushed = 1; }
    if (!answered(q)) query_answer(q);
    atomic_store_explicit(&QRY_RT(q)->polling, 0, memory_order_release);
}

static void run_query_destroy(void *args)
{
    d3d_query *q = *(d3d_query **)args;
    watch_remove(q);
    if (q->type == 9) {
        if (q->issued && q->gl) glEndQuery(GL_ANY_SAMPLES_PASSED_CONSERVATIVE);
        query_release(q);
        --query_live;
    }
    if (q->fence) glDeleteSync(q->fence);
    free(q);
}

static void query_destroy(void_com_object *o)
{
    d3d_query *q = (d3d_query *)o;
    d3d_rt_call(run_query_destroy, &q, sizeof q);
}

static void run_query_create(void *args)
{
    d3d_query *q = *(d3d_query **)args;
    if (q->type == 9) ++query_live;
}

uint32_t d3d_query_create(d3d_device *dev, uint32_t type)
{
    static int idle_set;
    if (!idle_set) { idle_set = 1; d3d_rt_set_idle(d3d_query_watch); }
    d3d_query *q = (d3d_query *)calloc(1, sizeof(d3d_query_rt));
    q->dev = dev;
    q->type = type;
    d3d_rt_call(run_query_create, &q, sizeof q);
    uint32_t guest = void_com_wrap(&q->com, &query_class, 0);
    q->com.destroy = query_destroy;
    return guest;
}

COM_METHOD(qry, QueryInterface, 3)
{
    if (void_guid_equal(ARG(1), IID_IDirect3DQuery9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&QRY->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(qry, AddRef, 1) { return void_com_addref(&QRY->com); }
COM_METHOD(qry, Release, 1) { return void_com_release(&QRY->com); }
COM_METHOD(qry, GetDevice, 2) { d3d_query *q = QRY; void_com_addref(&q->dev->com); MEM32(ARG(1)) = q->dev->com.guest; return D3D_OK; }
COM_METHOD(qry, GetType, 1) { return QRY->type; }
COM_METHOD(qry, GetDataSize, 1) { d3d_query *q = QRY; return q->type == 4 ? 16u : 4u; }

static _Thread_local unsigned query_pending_spins;
/* The game's polls, for the frame statistics: GetData calls of occlusion and
 * event queries, those still pending (with FLUSH), polls handed over, sleeps. */
static uint64_t poll_calls[2], poll_pending[2], poll_pending_flush[2], poll_recorded, poll_sleep_ns;
static uint32_t query_pending_result(uint32_t flags)
{
    if (!(flags & 1u)) { query_pending_spins = 0; return S_FALSE_D3D; }
    if (query_pending_spins < 8) { ++query_pending_spins; return S_FALSE_D3D; }
    /* UE3 spins until its deadline; pending FLUSH probes let GPU workers and guest threads run. */
    struct timespec delay = { 0, 50000 };
    uint64_t start = void_monotonic_ns();
    void_blocking_begin();
    while (nanosleep(&delay, &delay) && errno == EINTR) {}
    void_blocking_end();
    poll_sleep_ns += void_monotonic_ns() - start;
    return S_FALSE_D3D;
}

void d3d_query_log(uint32_t frames);
void d3d_query_log(uint32_t frames)
{
    static uint64_t last[9];
    uint64_t now[9] = { poll_calls[0], poll_pending[0], poll_pending_flush[0], poll_calls[1], poll_pending[1],
                        poll_pending_flush[1], poll_recorded, poll_sleep_ns, atomic_load(&poll_answered_idle) };
    if (frames)
        void_log("[rt] queries per frame: occlusion %.0f polls, %.0f pending (%.0f flush); event %.0f polls, %.0f pending "
                 "(%.0f flush); %.0f handed over, %.0f answered unasked; %.2f ms asleep",
                 (double)(now[0] - last[0]) / frames, (double)(now[1] - last[1]) / frames, (double)(now[2] - last[2]) / frames,
                 (double)(now[3] - last[3]) / frames, (double)(now[4] - last[4]) / frames, (double)(now[5] - last[5]) / frames,
                 (double)(now[6] - last[6]) / frames, (double)(now[8] - last[8]) / frames,
                 (double)(now[7] - last[7]) / 1e6 / frames);
    memcpy(last, now, sizeof last);
}

typedef struct { d3d_query *q; uint32_t flags, serial; } issue_args;

static void run_query_issue(void *args)
{
    const issue_args *a = (const issue_args *)args;
    d3d_query *q = a->q;
    uint32_t flags = a->flags;
    QRY_RT(q)->rt_serial = a->serial;
    if (q->type == 9) {
        if (flags & 2u) {
            if (q->issued && q->gl) glEndQuery(GL_ANY_SAMPLES_PASSED_CONSERVATIVE);
            if (!q->gl) q->gl = query_take(q);
            if (q->gl) glBeginQuery(GL_ANY_SAMPLES_PASSED_CONSERVATIVE, query_names[q->gl - 1]);
            q->issued = 1;
            q->ended = QUERY_NONE;
        }
        if ((flags & 1u) && q->issued) {
            if (q->gl) glEndQuery(GL_ANY_SAMPLES_PASSED_CONSERVATIVE);
            q->ended = q->gl ? QUERY_PENDING : QUERY_VISIBLE;
            q->issued = 0;
            if (q->gl) watch_push(q);
            else query_publish(q, QUERY_VISIBLE);
        }
    } else if (q->type == 8 && (flags & 1u)) {
        if (q->fence) glDeleteSync(q->fence);
        q->fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
        q->ended = 1;
        watch_push(q);
    }
}

/* The game's thread keeps the issue state it answers from (game_state: 0 not
 * ended since its last begin, 1 begun, 2 ended); the render thread runs the
 * GL side and publishes the result of each end by its serial. */
COM_METHOD(qry, Issue, 2)
{
    d3d_query *q = QRY;
    d3d_query_rt *x = QRY_RT(q);
    uint32_t flags = ARG(1);
    if (q->type == 9) {
        if (flags & 2u) x->game_state = 1;
        if ((flags & 1u) && x->game_state == 1) { ++x->serial; x->game_state = 2; }
    } else if (q->type == 8 && (flags & 1u)) {
        ++x->serial;
        x->game_state = 2;
    } else {
        return D3D_OK;
    }
    issue_args a = { q, flags, x->serial };
    d3d_rt_call(run_query_issue, &a, sizeof a);
    return D3D_OK;
}

/* The answer to the game's last end, if the render thread has published it:
 * the state, or -1. Otherwise asks it to look (once per end), and to submit
 * queued work first when the game says D3DGETDATA_FLUSH. */
static int query_result(d3d_query *q, uint32_t flags)
{
    d3d_query_rt *x = QRY_RT(q);
    uint32_t a = atomic_load_explicit(&x->answer, memory_order_acquire);
    if (a >> 2 == (x->serial & 0x3FFFFFFFu) && (a & 3u)) return (int)(a & 3u);
    /* Without the thread nobody looks unasked: every poll looks. */
    if (!d3d_rt_threaded() || !atomic_exchange_explicit(&x->polling, 1, memory_order_acq_rel)) {
        poll_args p = { q, flags & 1u };
        ++poll_recorded;
        d3d_rt_call(run_query_poll, &p, sizeof p);
        d3d_rt_flush();
        a = atomic_load_explicit(&x->answer, memory_order_acquire);   /* without the thread: answered already */
        if (a >> 2 == (x->serial & 0x3FFFFFFFu) && (a & 3u)) return (int)(a & 3u);
    }
    return -1;
}

COM_METHOD(qry, GetData, 4)
{
    d3d_query *q = QRY;
    uint32_t out = ARG(1), size = ARG(2), flags = ARG(3);
    if (q->type == 4) {
        query_pending_spins = 0;
        if (out && size >= 16) { MEM32(out) = FOURCC('C','A','C','H'); MEM32(out + 4) = 1; MEM32(out + 8) = 16; MEM32(out + 12) = 7; }
        return D3D_OK;
    }
    d3d_query_rt *x = QRY_RT(q);
    int kind = q->type == 8;
    ++poll_calls[kind];
    if (q->type == 8) {
        if (x->game_state == 2 && query_result(q, flags) < 0) {
            ++poll_pending[kind]; poll_pending_flush[kind] += flags & 1u;
            return query_pending_result(flags);
        }
        query_pending_spins = 0;
        if (out && size >= 4) MEM32(out) = 1;
        return D3D_OK;
    }
    if (x->game_state != 2) { if (out && size >= 4) MEM32(out) = 0; return D3D_OK; }
    int state = QUERY_NONE;
    if (x->game_state == 2 && (state = query_result(q, flags)) < 0) {
        ++poll_pending[kind]; poll_pending_flush[kind] += flags & 1u;
        return query_pending_result(flags);
    }
    query_pending_spins = 0;
    /* Only a measured zero hides: a query never ended counts as visible, as UE3's own timeout does.
     * GLES reports only "any samples": answer with the viewport's pixel count. */
    if (out && size >= 4) MEM32(out) = state == QUERY_HIDDEN ? 0 : q->dev->st.viewport[2] * q->dev->st.viewport[3];
    return D3D_OK;
}

static const void_fn query_methods[] = { qry_QueryInterface, qry_AddRef, qry_Release, qry_GetDevice, qry_GetType,
    qry_GetDataSize, qry_Issue, qry_GetData };
static void_com_class query_class = { "IDirect3DQuery9", 8, query_methods, 0 };

/* ============================================================= state blocks */
static void_com_class stateblock_class;
#define SB ((d3d_stateblock *)void_com_host(THIS_))

void d3d_stateblock_apply(d3d_stateblock *sb);

/* Pixel and vertex state membership, from the D3D9 documentation. */
static const uint8_t pixel_rs[] = {7,9,14,15,16,19,20,23,24,25,26,27,34,35,36,37,38,48,52,53,54,55,56,57,58,59,60,
    128,129,130,131,132,133,134,135,168,170,171,174,175,176,185,186,187,188,189,190,191,192,193,194,195,198,199,200,201,
    202,203,204,205,206,207,208,209};
static const uint8_t vertex_rs[] = {9,28,29,35,36,37,38,48,136,137,139,140,141,142,143,145,146,147,148,151,152,154,155,
    156,157,158,159,160,161,162,163,166,167,170,172,173,178,179,180,181,182,183,184,185,186,187,188,189};

static void stateblock_destroy(void_com_object *o)
{
    d3d_stateblock *sb = (d3d_stateblock *)o;
    d3d_state_release(&sb->state);
    free(sb);
}

uint32_t d3d_stateblock_create(d3d_device *dev, uint32_t type)
{
    d3d_stateblock *sb = (d3d_stateblock *)calloc(1, sizeof *sb);
    sb->dev = dev;
    if (type == 1 || type == 2) {                  /* ALL, PIXELSTATE */
        if (type == 1) memset(sb->rec_rs, 1, sizeof sb->rec_rs);
        else for (size_t i = 0; i < sizeof pixel_rs; ++i) sb->rec_rs[pixel_rs[i]] = 1;
        for (int i = 0; i < 20; ++i) for (int k = 0; k < 14; ++k) sb->rec_ss[i][k] = 1;
        for (int i = 0; i < 8; ++i) for (int k = 0; k < 33; ++k) sb->rec_tss[i][k] = 1;
        memset(sb->rec_ps_f, 1, sizeof sb->rec_ps_f);
        memset(sb->rec_ps_i, 1, sizeof sb->rec_ps_i);
        memset(sb->rec_ps_b, 1, sizeof sb->rec_ps_b);
        sb->rec_ps = 1;
    }
    if (type == 1 || type == 3) {                  /* ALL, VERTEXSTATE */
        if (type == 3) for (size_t i = 0; i < sizeof vertex_rs; ++i) sb->rec_rs[vertex_rs[i]] = 1;
        memset(sb->rec_vs_f, 1, sizeof sb->rec_vs_f);
        memset(sb->rec_vs_i, 1, sizeof sb->rec_vs_i);
        memset(sb->rec_vs_b, 1, sizeof sb->rec_vs_b);
        memset(sb->rec_light, 1, sizeof sb->rec_light);
        sb->rec_vs = 1; sb->rec_decl = 1; sb->rec_fvf = 1;
        for (int i = 16; i < 20; ++i) for (int k = 0; k < 14; ++k) sb->rec_ss[i][k] = 1;
    }
    if (type == 1) {
        memset(sb->rec_tex, 1, sizeof sb->rec_tex);
        memset(sb->rec_stream, 1, sizeof sb->rec_stream);
        memset(sb->rec_transform, 1, sizeof sb->rec_transform);
        memset(sb->rec_clip, 1, sizeof sb->rec_clip);
        sb->rec_viewport = sb->rec_scissor = sb->rec_indices = sb->rec_material = 1;
    }
    uint32_t guest = void_com_wrap(&sb->com, &stateblock_class, 0);
    sb->com.destroy = stateblock_destroy;
    if (type) d3d_stateblock_capture(sb);
    return guest;
}

void d3d_stateblock_capture(d3d_stateblock *sb)
{
    /* Capture copies the recorded categories. The block holds references on
     * the objects it names, as D3D9 state blocks do (Wine increments them in
     * wined3d_stateblock_capture): a texture released after capture stays
     * valid for Apply. */
    d3d_state *src = &sb->dev->st, *s = &sb->state;
    for (int i = 0; i < 256; ++i) if (sb->rec_rs[i]) s->rs[i] = src->rs[i];
    for (int i = 0; i < 20; ++i) for (int k = 0; k < 14; ++k) if (sb->rec_ss[i][k]) s->ss[i][k] = src->ss[i][k];
    for (int i = 0; i < 8; ++i) for (int k = 0; k < 33; ++k) if (sb->rec_tss[i][k]) s->tss[i][k] = src->tss[i][k];
    for (int i = 0; i < 20; ++i) if (sb->rec_tex[i]) d3d_ref_set(&s->textures[i], src->textures[i]);
    for (int i = 0; i < 16; ++i) if (sb->rec_stream[i]) {
        d3d_ref_set(&s->streams[i], src->streams[i]); s->stream_offset[i] = src->stream_offset[i];
        s->stream_stride[i] = src->stream_stride[i]; s->stream_freq[i] = src->stream_freq[i];
    }
    for (int i = 0; i < 256; ++i) if (sb->rec_vs_f[i]) memcpy(s->vs_f[i], src->vs_f[i], 16);
    for (int i = 0; i < 224; ++i) if (sb->rec_ps_f[i]) memcpy(s->ps_f[i], src->ps_f[i], 16);
    for (int i = 0; i < 16; ++i) {
        if (sb->rec_vs_i[i]) memcpy(s->vs_i[i], src->vs_i[i], 16);
        if (sb->rec_ps_i[i]) memcpy(s->ps_i[i], src->ps_i[i], 16);
        if (sb->rec_vs_b[i]) s->vs_b[i] = src->vs_b[i];
        if (sb->rec_ps_b[i]) s->ps_b[i] = src->ps_b[i];
    }
    for (int i = 0; i < 512; ++i) if (sb->rec_transform[i]) memcpy(s->transforms[i], src->transforms[i], 64);
    if (sb->rec_viewport) { memcpy(s->viewport, src->viewport, 16); memcpy(s->viewport_z, src->viewport_z, 8); }
    if (sb->rec_scissor) memcpy(s->scissor, src->scissor, 16);
    if (sb->rec_indices) d3d_ref_set(&s->indices, src->indices);
    if (sb->rec_decl) d3d_ref_set(&s->decl, src->decl);
    if (sb->rec_fvf) s->fvf = src->fvf;
    if (sb->rec_vs) d3d_ref_set(&s->vs, src->vs);
    if (sb->rec_ps) d3d_ref_set(&s->ps, src->ps);
    if (sb->rec_material) memcpy(s->material, src->material, 68);
    for (int i = 0; i < 8; ++i) if (sb->rec_light[i]) { memcpy(s->lights[i], src->lights[i], 104); s->light_enable[i] = src->light_enable[i]; }
    for (int i = 0; i < 6; ++i) if (sb->rec_clip[i]) memcpy(s->clip_planes[i], src->clip_planes[i], 16);
}

COM_METHOD(sb, QueryInterface, 3)
{
    if (void_guid_equal(ARG(1), IID_IDirect3DStateBlock9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&SB->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(sb, AddRef, 1) { return void_com_addref(&SB->com); }
COM_METHOD(sb, Release, 1) { return void_com_release(&SB->com); }
COM_METHOD(sb, GetDevice, 2) { d3d_stateblock *s = SB; void_com_addref(&s->dev->com); MEM32(ARG(1)) = s->dev->com.guest; return D3D_OK; }
COM_METHOD(sb, Capture, 1) { d3d_stateblock_capture(SB); return D3D_OK; }
COM_METHOD(sb, Apply, 1) { d3d_stateblock_apply(SB); return D3D_OK; }
static const void_fn stateblock_methods[] = { sb_QueryInterface, sb_AddRef, sb_Release, sb_GetDevice, sb_Capture, sb_Apply };
static void_com_class stateblock_class = { "IDirect3DStateBlock9", 6, stateblock_methods, 0 };

/* ============================================================== swap chain */
typedef struct { void_com_object com; d3d_device *dev; } swapchain_t;
#define SC ((swapchain_t *)void_com_host(THIS_))
COM_METHOD(sc, QueryInterface, 3)
{
    if (void_guid_equal(ARG(1), IID_IDirect3DSwapChain9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&SC->com); MEM32(ARG(2)) = THIS_; return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(sc, AddRef, 1) { return void_com_addref(&SC->com); }
COM_METHOD(sc, Release, 1) { return void_com_release(&SC->com); }
COM_METHOD(sc, Present, 6)
{
    swapchain_t *s = SC;
    d3d_gl_present(s->dev);
    ++s->dev->frame;
    void_touch_frame_presented();
    d3d_gl_frame_pace();
    if (recomp_yield_hook) recomp_yield_hook();
    return D3D_OK;
}
COM_METHOD(sc, GetFrontBufferData, 2) { return D3DERR_INVALIDCALL; }
COM_METHOD(sc, GetBackBuffer, 4)
{
    swapchain_t *s = SC;
    void_com_addref(&s->dev->backbuffer->com);
    MEM32(ARG(3)) = s->dev->backbuffer->com.guest;
    return D3D_OK;
}
COM_METHOD(sc, GetRasterStatus, 2) { MEM32(ARG(1)) = 0; MEM32(ARG(1) + 4) = 0; return D3D_OK; }
COM_METHOD(sc, GetDisplayMode, 2)
{
    swapchain_t *s = SC;
    uint32_t out = ARG(1);
    MEM32(out) = s->dev->pp[0]; MEM32(out + 4) = s->dev->pp[1]; MEM32(out + 8) = 60; MEM32(out + 12) = 22;
    return D3D_OK;
}
COM_METHOD(sc, GetDevice, 2) { swapchain_t *s = SC; void_com_addref(&s->dev->com); MEM32(ARG(1)) = s->dev->com.guest; return D3D_OK; }
COM_METHOD(sc, GetPresentParameters, 2)
{
    swapchain_t *s = SC;
    for (int i = 0; i < 14; ++i) MEM32(ARG(1) + 4u * (uint32_t)i) = s->dev->pp[i];
    return D3D_OK;
}
static const void_fn swapchain_methods[] = { sc_QueryInterface, sc_AddRef, sc_Release, sc_Present, sc_GetFrontBufferData,
    sc_GetBackBuffer, sc_GetRasterStatus, sc_GetDisplayMode, sc_GetDevice, sc_GetPresentParameters };
static void_com_class swapchain_class = { "IDirect3DSwapChain9", 10, swapchain_methods, 0 };

uint32_t d3d_swapchain_create(d3d_device *dev)
{
    swapchain_t *s = (swapchain_t *)calloc(1, sizeof *s);
    s->dev = dev;
    return void_com_wrap(&s->com, &swapchain_class, 0);
}
