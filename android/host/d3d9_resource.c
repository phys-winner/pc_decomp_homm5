/* Direct3D 9 resources: surfaces, textures, buffers, vertex declarations,
 * queries, state blocks and the implicit swap chain. */
#include "d3d9_internal.h"
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

static void surface_destroy(void_com_object *o)
{
    d3d_surface *s = (d3d_surface *)o;
    if (s->gl) { d3d_gl_forget_texture(s->gl); glDeleteTextures(1, &s->gl); }
    if (s->sysmem) void_gfree(s->sysmem);
    free(s);
}

d3d_surface *d3d_surface_new(d3d_device *dev, uint32_t w, uint32_t h, uint32_t format, uint32_t usage,
    uint32_t pool, uint32_t multisample)
{
    d3d_surface *s = (d3d_surface *)calloc(1, sizeof *s);
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
        glGenTextures(1, &s->gl);
        d3d_gl_upload_unit();
        glBindTexture(GL_TEXTURE_2D, s->gl);
        glTexStorage2D(GL_TEXTURE_2D, 1, s->fmt->internal, (GLsizei)s->width, (GLsizei)s->height);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        apply_swizzle(GL_TEXTURE_2D, s->fmt, usage | (s->fmt->depth ? 0 : D3DUSAGE_RENDERTARGET));
        GLenum e = glGetError();
        if (e) void_log("[d3d9] surface %ux%u format %u: GL error %04X", s->width, s->height, format, e);
    }
    return s;
}

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
static void texture_set_storage(d3d_texture *t, const d3d_native_format *native)
{
    if (t->native == native) return;
    if (!t->gl) { t->native = native; return; }     /* a system copy only remembers it */
    if (t->target != GL_TEXTURE_2D) return;          /* never converted */
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
        (s->gl || (s->container && s->container->gl)))
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
    } else if (s->gl && s->fmt->internal && !s->fmt->depth) {
        /* Standalone GPU surfaces are stored like render targets (d3d_surface_new). */
        void *owned;
        size_t size;
        const void *gl_data = d3d_format_convert(s->fmt, data, x1 - x0, y1 - y0, s->pitch, &owned, &size, 1);
        d3d_gl_upload_unit();
        glBindTexture(GL_TEXTURE_2D, s->gl);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        glTexSubImage2D(GL_TEXTURE_2D, 0, (GLint)x0, (GLint)y0, (GLsizei)(x1 - x0), (GLsizei)(y1 - y0), s->fmt->format,
            s->fmt->type, gl_data);
        free(owned);
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

static void texture_destroy(void_com_object *o)
{
    d3d_texture *t = (d3d_texture *)o;
    if (t->gl) { d3d_gl_forget_texture(t->gl); glDeleteTextures(1, &t->gl); }
    int n = t->faces * (int)t->levels;
    for (int i = 0; i < n; ++i) {
        if (t->surfaces && t->surfaces[i]) {
            d3d_surface *s = t->surfaces[i];
            s->container = NULL;
            s->com.refs = 1;
            void_com_release(&s->com);
        }
        if (t->sysmem && t->sysmem[i]) void_gfree(t->sysmem[i]);
    }
    free(t->surfaces);
    free(t->sysmem);
    free(t);
}

void d3d_texture_level_size(d3d_texture *t, uint32_t level, uint32_t *w, uint32_t *h)
{
    level_dims(t->width, t->height, level, w, h);
}

d3d_texture *d3d_texture_new(d3d_device *dev, uint32_t rtype, uint32_t w, uint32_t h, uint32_t d,
    uint32_t levels, uint32_t usage, uint32_t format, uint32_t pool)
{
    const d3d_format *f = d3d_format_find(format);
    if (!f || !w || !h) return NULL;
    uint32_t full = mip_levels(w, h, rtype == D3DRTYPE_VOLUMETEXTURE ? d : 1);
    if (usage & D3DUSAGE_AUTOGENMIPMAP) levels = (levels == 0 || levels > 1) ? full : 1;
    if (!levels || levels > full) levels = full;
    d3d_texture *t = (d3d_texture *)calloc(1, sizeof *t);
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
        glGenTextures(1, &t->gl);
        d3d_gl_upload_unit();
        glBindTexture(t->target, t->gl);
        if (t->target == GL_TEXTURE_3D)
            glTexStorage3D(GL_TEXTURE_3D, (GLsizei)levels, f->internal, (GLsizei)w, (GLsizei)h, (GLsizei)t->depth);
        else
            glTexStorage2D(t->target, (GLsizei)levels, f->internal, (GLsizei)w, (GLsizei)h);
        glTexParameteri(t->target, GL_TEXTURE_MAX_LEVEL, (GLint)levels - 1);
        apply_swizzle(t->target, f, usage);
        GLenum e = glGetError();
        if (e) void_log("[d3d9] texture %ux%u levels %u format %u: GL error %04X", w, h, levels, format, e);
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
    d3d_texture *t = (d3d_texture *)calloc(1, sizeof *t);
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
    glGenTextures(1, &t->gl);
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glTexStorage2D(t->target, (GLsizei)levels, native->internal, (GLsizei)w, (GLsizei)h);
    glTexParameteri(t->target, GL_TEXTURE_MAX_LEVEL, (GLint)levels - 1);
    apply_swizzle(t->target, f, usage);
    GLenum e = glGetError();
    if (e) void_log("[d3d9] converted texture %ux%u levels %u format %.4s: GL error %04X", w, h, levels,
                    (const char *)&native->fourcc, e);
    return t;
}

/* One whole level of a converted texture, as its blocks are stored. */
void d3d_texture_upload_native(d3d_texture *t, uint32_t face, uint32_t level, const uint8_t *data, uint32_t size)
{
    if (!t->gl || !t->native || level >= t->levels) return;
    uint32_t w, h;
    level_dims(t->width, t->height, level, &w, &h);
    if (size != d3d_native_size(t->native, w, h)) {
        void_log("[d3d9] converted level %u of %ux%u: %u bytes, %u expected", level, t->width, t->height, size,
                 d3d_native_size(t->native, w, h));
        return;
    }
    uint64_t start = void_perf_now_ns();
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glCompressedTexSubImage2D(face_target(t, face), (GLint)level, 0, 0, (GLsizei)w, (GLsizei)h, t->native->internal,
        (GLsizei)size, data);
    GLenum e = glGetError();
    if (e) void_log("[d3d9] converted upload %ux%u level %u: GL error %04X", w, h, level, e);
    void_perf_add(VOID_PERF_TEXTURE, void_perf_now_ns() - start, size);
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
        d3d_surface *s = (d3d_surface *)calloc(1, sizeof *s);
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
void d3d_texture_upload_rect(d3d_texture *t, uint32_t face, uint32_t level, uint32_t x, uint32_t y, uint32_t w, uint32_t h,
    const uint8_t *data, uint32_t pitch)
{
    if (!t->gl || !w || !h) return;
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
        uint64_t started = void_perf_now_ns();
        d3d_gl_upload_unit();
        glBindTexture(t->target, t->gl);
        glCompressedTexSubImage2D(face_target(t, face), (GLint)level, 0, 0, (GLsizei)lw, (GLsizei)lh, t->native->internal,
                                  (GLsizei)size, data);
        GLenum e = glGetError();
        if (e) void_log("[d3d9] converted upload %ux%u level %u %.4s: GL error %04X", lw, lh, level,
                        (const char *)&t->native->fourcc, e);
        void_perf_add(VOID_PERF_TEXTURE, void_perf_now_ns() - started, size);
        (void)pitch;
        return;
    }
    void *owned;
    size_t size;
    uint64_t start = void_perf_now_ns();
    const void *gl_data = d3d_format_convert(t->fmt, data, w, h, pitch, &owned, &size, (t->usage & D3DUSAGE_RENDERTARGET) != 0);
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    if (t->target == GL_TEXTURE_3D) {
        uint32_t d = t->depth >> level;
        if (!d) d = 1;
        glTexSubImage3D(GL_TEXTURE_3D, (GLint)level, (GLint)x, (GLint)y, 0, (GLsizei)w, (GLsizei)h, (GLsizei)d, t->fmt->format,
            t->fmt->type, gl_data);
    } else {
        glTexSubImage2D(face_target(t, face), (GLint)level, (GLint)x, (GLint)y, (GLsizei)w, (GLsizei)h, t->fmt->format,
            t->fmt->type, gl_data);
    }
    GLenum e = glGetError();
    if (e) void_log("[d3d9] upload %ux%u at %u,%u level %u format %u: GL error %04X", w, h, x, y, level, t->format, e);
    free(owned);
    void_perf_add(VOID_PERF_TEXTURE, void_perf_now_ns() - start, size);
    if (level == 0 && (t->usage & D3DUSAGE_AUTOGENMIPMAP)) t->mips_dirty = 1;
}

void d3d_texture_upload_level(d3d_texture *t, uint32_t face, uint32_t level, const uint8_t *data, uint32_t pitch)
{
    uint32_t w, h;
    level_dims(t->width, t->height, level, &w, &h);
    d3d_texture_upload_rect(t, face, level, 0, 0, w, h, data, pitch);
}

void d3d_generate_mips(d3d_texture *t)
{
    if (!t->gl || t->levels < 2 || t->native) return;   /* converted textures store every level */
    d3d_gl_upload_unit();
    glBindTexture(t->target, t->gl);
    glGenerateMipmap(t->target);
    t->mips_dirty = 0;
}

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
COM_METHOD(tex, SetLOD, 2) { d3d_texture *t = TEX; uint32_t old = t->lod; t->lod = ARG(1) < t->levels ? ARG(1) : t->levels - 1; return old; }
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

static void buffer_destroy(void_com_object *o)
{
    d3d_buffer *b = (d3d_buffer *)o;
    if (b->gl) { d3d_gl_forget_buffer(b->gl); glDeleteBuffers(1, &b->gl); }
    if (b->shadow) void_gfree(b->shadow);
    free(b->dirty_pages);
    free(b);
}

uint32_t d3d_buffer_create(d3d_device *dev, int index, uint32_t length, uint32_t usage, uint32_t format, uint32_t pool)
{
    if (!length) return 0;
    d3d_buffer *b = (d3d_buffer *)calloc(1, sizeof *b);
    b->dev = dev; b->index = index; b->size = length; b->usage = usage; b->format = format; b->pool = pool;
    b->shadow = void_galloc(length);
    if (!b->shadow) { free(b); return 0; }
    glGenBuffers(1, &b->gl);
    /* Created through the copy target, which no vertex array object records. */
    glBindBuffer(GL_COPY_WRITE_BUFFER, b->gl);
    glBufferData(GL_COPY_WRITE_BUFFER, length, NULL, (usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
    b->dirty_lo = 0xFFFFFFFFu;
    uint32_t guest = void_com_wrap(&b->com, index ? &ibuffer_class : &vbuffer_class, 0);
    b->com.destroy = buffer_destroy;
    return guest;
}

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
    const uint8_t *src = (const uint8_t *)GPTR(b->shadow) + b->dirty_lo;
    uint32_t length = b->dirty_hi - b->dirty_lo;
    if (b->discard_pending) {
        /* DISCARD invalidates the whole buffer, even for a partial lock. */
        glBufferData(target, b->size, NULL, (b->usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
        glBufferSubData(target, b->dirty_lo, length, src);
    } else if (b->dirty_lo == 0 && b->dirty_hi >= b->size) {
        glBufferData(target, b->size, GPTR(b->shadow), (b->usage & D3DUSAGE_DYNAMIC) ? GL_DYNAMIC_DRAW : GL_STATIC_DRAW);
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
            (const uint8_t *)GPTR(b->shadow) + start);
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

COM_METHOD(buf, Lock, 5)
{
    d3d_buffer *b = BUF;
    uint32_t offset = ARG(1), size = ARG(2), out = ARG(3), flags = ARG(4);
    if (offset > b->size) return D3DERR_INVALIDCALL;
    if (!size || size > b->size - offset) size = b->size - offset;
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
    ++b->locks;
    MEM32(out) = b->shadow + offset;
    return D3D_OK;
}

COM_METHOD(buf, Unlock, 1)
{
    d3d_buffer *b = BUF;
    if (!b->locks) return D3DERR_INVALIDCALL;
    if (--b->locks == 0 && !b->dirty_pages) d3d_buffer_flush(b);
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

static void query_destroy(void_com_object *o)
{
    d3d_query *q = (d3d_query *)o;
    if (q->gl) glDeleteQueries(1, &q->gl);
    if (q->fence) glDeleteSync(q->fence);
    free(q);
}

uint32_t d3d_query_create(d3d_device *dev, uint32_t type)
{
    d3d_query *q = (d3d_query *)calloc(1, sizeof *q);
    q->dev = dev;
    q->type = type;
    if (type == 9) glGenQueries(1, &q->gl);
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

COM_METHOD(qry, Issue, 2)
{
    d3d_query *q = QRY;
    uint32_t flags = ARG(1);
    if (q->type == 9) {
        if (flags & 2u) { glBeginQuery(GL_ANY_SAMPLES_PASSED_CONSERVATIVE, q->gl); q->issued = 1; q->ended = 0; }
        if ((flags & 1u) && q->issued) { glEndQuery(GL_ANY_SAMPLES_PASSED_CONSERVATIVE); q->ended = 1; q->issued = 0; }
    } else if (q->type == 8 && (flags & 1u)) {
        if (q->fence) glDeleteSync(q->fence);
        q->fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
        q->ended = 1;
    }
    return D3D_OK;
}

COM_METHOD(qry, GetData, 4)
{
    d3d_query *q = QRY;
    uint32_t out = ARG(1), size = ARG(2), flags = ARG(3);
    if (q->type == 4) {
        if (out && size >= 16) { MEM32(out) = FOURCC('C','A','C','H'); MEM32(out + 4) = 1; MEM32(out + 8) = 16; MEM32(out + 12) = 7; }
        return D3D_OK;
    }
    if (q->type == 8) {
        if (q->fence) {
            GLenum r = glClientWaitSync(q->fence, flags & 1u ? GL_SYNC_FLUSH_COMMANDS_BIT : 0, 0);
            if (r == GL_TIMEOUT_EXPIRED) return S_FALSE_D3D;
        }
        if (out && size >= 4) MEM32(out) = 1;
        return D3D_OK;
    }
    if (!q->ended) { if (out && size >= 4) MEM32(out) = 0; return D3D_OK; }
    /* D3DGETDATA_FLUSH submits queued work; GetData remains a status poll. */
    if (flags & 1u) glFlush();
    GLuint available = 0;
    glGetQueryObjectuiv(q->gl, GL_QUERY_RESULT_AVAILABLE, &available);
    if (!available) return S_FALSE_D3D;
    GLuint any = 0;
    glGetQueryObjectuiv(q->gl, GL_QUERY_RESULT, &any);
    /* GLES reports only "any samples": answer with the viewport's pixel count. */
    if (out && size >= 4) MEM32(out) = any ? q->dev->st.viewport[2] * q->dev->st.viewport[3] : 0;
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
