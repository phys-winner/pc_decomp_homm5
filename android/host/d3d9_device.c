/* IDirect3D9 and IDirect3DDevice9. */
#include "d3d9_internal.h"
#include "dxvk.h"
#include "input.h"
#include "touch.h"
#include <math.h>

d3d_device *g_d3d_device;
/* The APK supplies physical window dimensions; the shell keeps input's size. */
extern int void_android_display_size(int *w, int *h) __attribute__((weak));


/* What Direct3D 9 answered on the Windows PC (NVIDIA GeForce RTX 4060, see
 * build/d3d9-native/caps-dump.txt); a few limits follow the Mali GPU. */
static const char pc_caps_hex[] =
    "010000000000000000000200000002E0A00300000F00008001000000F0BE1B00F2CE2F0091217307FF000000FF3F0000FF3F0000FF000000"
    "08420800C5EC01000007030300030303000303033F0000003F0000001F000000004000000040000000080000002000000040000010000000"
    "F902155020BCBECC20BCBECC20BCBE4C20BCBE4C00000000FF01000008001800FFFFFE0308000000080000003B0100000800000008000000"
    "040000000000000000000046FFFFFF00FFFFFF0010000000FF0000000003FEFF000100000003FFFF00E07F47510000000000000000000000"
    "0000000000000000020000000F0300000400000000030003010000001800000020000000040000001F000000180000002000000004000000"
    "0002000000070303FFFF0000FFFF00000010000000100000";

typedef struct { void_com_object com; } d3d9_t;

/* ============================================================ IDirect3D9 */
static int hex_digit(char c) { return c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10; }

static void fill_caps(uint32_t out)
{
    size_t n = strlen(pc_caps_hex) / 2;
    for (size_t i = 0; i < n && i < 304; ++i)
        MEM8(out + (uint32_t)i) = (uint8_t)(hex_digit(pc_caps_hex[2 * i]) * 16 + hex_digit(pc_caps_hex[2 * i + 1]));
    /* Limits the GPU cannot reach are lowered to what GL reports (d3d_gl_init);
     * everything else stays exactly as the PC answered. */
    uint32_t tex = d3d_gl_limits.max_texture ? d3d_gl_limits.max_texture : 8192;
    uint32_t vol = d3d_gl_limits.max_3d_texture ? d3d_gl_limits.max_3d_texture : 2048;
    uint32_t rts = d3d_gl_limits.max_draw_buffers ? d3d_gl_limits.max_draw_buffers : 4;
    if (MEM32(out + 88) > tex) MEM32(out + 88) = tex;      /* MaxTextureWidth */
    if (MEM32(out + 92) > tex) MEM32(out + 92) = tex;      /* MaxTextureHeight */
    if (MEM32(out + 96) > vol) MEM32(out + 96) = vol;      /* MaxVolumeExtent */
    if (MEM32(out + 104) > tex) MEM32(out + 104) = tex;    /* MaxTextureAspectRatio */
    if (MEM32(out + 260) > rts) MEM32(out + 260) = rts;    /* NumSimultaneousRTs */
}

/* Preserve the PC's familiar modes, then offer the current native display. */
static const uint32_t modes[][2] = {
    {640, 480}, {800, 600}, {1024, 768}, {1152, 864}, {1280, 720}, {1280, 768}, {1280, 800}, {1280, 960},
    {1280, 1024}, {1360, 768}, {1366, 768}, {1440, 900}, {1560, 720}, {1600, 900}, {1600, 1200}, {1680, 1050},
    {1920, 1080}, {2340, 1080},
};
#define MODE_COUNT (sizeof modes / sizeof modes[0])

COM_METHOD(d3d9, QueryInterface, 3)
{
    d3d9_t *d = (d3d9_t *)void_com_host(THIS_);
    if (void_guid_equal(ARG(1), IID_IDirect3D9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&d->com);
        MEM32(ARG(2)) = THIS_;
        return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(d3d9, AddRef, 1) { return void_com_addref((void_com_object *)void_com_host(THIS_)); }
COM_METHOD(d3d9, Release, 1) { return void_com_release((void_com_object *)void_com_host(THIS_)); }
COM_METHOD(d3d9, RegisterSoftwareDevice, 2) { return D3DERR_INVALIDCALL; }
COM_METHOD(d3d9, GetAdapterCount, 1) { return 1; }

COM_METHOD(d3d9, GetAdapterIdentifier, 4)
{
    if (ARG(1)) return D3DERR_INVALIDCALL;
    uint32_t out = ARG(3);
    memset(GPTR(out), 0, 1100);
    void_utf8_to_ga("nvldumd.dll", out, 512);
    void_utf8_to_ga("NVIDIA GeForce RTX 4060", out + 512, 512);
    void_utf8_to_ga("\\\\.\\DISPLAY1", out + 1024, 32);
    MEM32(out + 1056) = 0x0010069Cu;    /* DriverVersion low */
    MEM32(out + 1060) = 0x00200000u;    /* DriverVersion high */
    MEM32(out + 1064) = 0x10DE;         /* VendorId */
    MEM32(out + 1068) = 0x2882;         /* DeviceId */
    MEM32(out + 1072) = 0x51611462u;    /* SubSysId */
    MEM32(out + 1076) = 161;            /* Revision */
    return D3D_OK;
}

static int mode_format_ok(uint32_t format) { return format == 22 || format == 23; }

static int adapter_display_size(uint32_t size[2])
{
    int w = 0, h = 0;
    if (!void_android_display_size || !void_android_display_size(&w, &h))
        void_input_screen_size(&w, &h);
    uint32_t limit = d3d_gl_limits.max_texture ? d3d_gl_limits.max_texture : 8192;
    if (w <= 0 || h <= 0 || (uint32_t)w > limit || (uint32_t)h > limit) return 0;
    size[0] = (uint32_t)w; size[1] = (uint32_t)h;
    return 1;
}

static int extra_display_mode(uint32_t size[2])
{
    if (!adapter_display_size(size)) return 0;
    for (unsigned i = 0; i < MODE_COUNT; ++i)
        if (modes[i][0] == size[0] && modes[i][1] == size[1]) return 0;
    return 1;
}

COM_METHOD(d3d9, GetAdapterModeCount, 3)
{
    uint32_t native[2];
    return !ARG(1) && mode_format_ok(ARG(2)) ? (uint32_t)MODE_COUNT + (uint32_t)extra_display_mode(native) : 0;
}

COM_METHOD(d3d9, EnumAdapterModes, 5)
{
    uint32_t format = ARG(2), index = ARG(3), out = ARG(4);
    if (ARG(1) || !mode_format_ok(format) || index > MODE_COUNT) return D3DERR_INVALIDCALL;
    uint32_t native[2];
    const uint32_t *size = index < MODE_COUNT ? modes[index] : extra_display_mode(native) ? native : NULL;
    if (!size) return D3DERR_INVALIDCALL;
    MEM32(out) = size[0]; MEM32(out + 4) = size[1]; MEM32(out + 8) = 60; MEM32(out + 12) = format;
    return D3D_OK;
}

COM_METHOD(d3d9, GetAdapterDisplayMode, 3)
{
    uint32_t size[2];
    if (ARG(1) || !adapter_display_size(size)) return D3DERR_INVALIDCALL;
    uint32_t out = ARG(2);
    MEM32(out) = size[0]; MEM32(out + 4) = size[1]; MEM32(out + 8) = 60; MEM32(out + 12) = 22;
    return D3D_OK;
}

COM_METHOD(d3d9, CheckDeviceType, 6)
{
    uint32_t adapter_format = ARG(3), back = ARG(4);
    return (adapter_format == 22 || adapter_format == 23) && (back == 21 || back == 22 || back == 23 || back == 0)
        ? D3D_OK : D3DERR_NOTAVAILABLE;
}

/* The PC's CheckDeviceFormat answers, restricted to what GLES can store. */
static int format_supported(uint32_t usage, uint32_t rtype, uint32_t format)
{
    const d3d_format *f = d3d_format_find(format);
    if (!f) return 0;
    uint32_t base = usage & 0xFFFFu;
    if (rtype == D3DRTYPE_VERTEXBUFFER || rtype == D3DRTYPE_INDEXBUFFER) return 0;
    if (base & D3DUSAGE_DEPTHSTENCIL) {
        if (!f->depth) return 0;
        /* Depth formats usable as depth-stencil surfaces; as textures only
         * INTZ/RAWZ/DF16/DF24 (raw depth reads), not NVIDIA's comparing D24S8. */
        if (rtype == D3DRTYPE_SURFACE) return 1;
        if (rtype == D3DRTYPE_TEXTURE)
            return format == FOURCC('I','N','T','Z') || format == FOURCC('D','F','2','4') || format == FOURCC('D','F','1','6');
        return 0;
    }
    if (f->depth) return 0;
    if (base & D3DUSAGE_RENDERTARGET) {
        if (!f->render_target) return 0;
        if (format == FOURCC('N','U','L','L')) return rtype == D3DRTYPE_SURFACE;
        return 1;
    }
    if (rtype == D3DRTYPE_VOLUMETEXTURE && f->block_bytes) return 1;
    if (usage & 0x00100000u) return f->is_float || format == 21;   /* QUERY_VERTEXTEXTURE: like the PC */
    if (usage & 0x00080000u) return !f->depth;                       /* POSTPIXELSHADER_BLENDING */
    if (usage & 0x00020000u) {                                       /* QUERY_FILTER */
        return !(format == 114 || format == 115 || format == 116 || format == 34 || format == 36 || format == 81);
    }
    if (usage & 0x00040000u) return format == 21 || format == 22 || format == FOURCC('D','X','T','1') ||
        format == FOURCC('D','X','T','3') || format == FOURCC('D','X','T','5');  /* QUERY_SRGBREAD */
    if (usage & 0x00010000u) return format == 21 || format == 22;    /* QUERY_SRGBWRITE */
    return format != FOURCC('N','U','L','L');
}

COM_METHOD(d3d9, CheckDeviceFormat, 7)
{
    uint32_t usage = ARG(4), rtype = ARG(5), format = ARG(6);
    int ok = format_supported(usage, rtype, format);
    VLOG("[d3d9] CheckDeviceFormat(usage %08X, rtype %u, format %u/%.4s) = %s", usage, rtype, format,
        format > 0xFFFF ? (const char *)&format : "", ok ? "OK" : "NOTAVAILABLE");
    if (ok && (usage & D3DUSAGE_AUTOGENMIPMAP)) {
        const d3d_format *f = d3d_format_find(format);
        if (f && (f->block_bytes || f->conv != CONV_NONE)) return D3DOK_NOAUTOGEN;
    }
    return ok ? D3D_OK : D3DERR_NOTAVAILABLE;
}

COM_METHOD(d3d9, CheckDeviceMultiSampleType, 7)
{
    uint32_t type = ARG(5), quality = ARG(6);
    if (type == 0) { if (quality) MEM32(quality) = 1; return D3D_OK; }
    if (type == 2 || type == 4) { if (quality) MEM32(quality) = 1; return D3DERR_NOTAVAILABLE; }
    return D3DERR_NOTAVAILABLE;
}

COM_METHOD(d3d9, CheckDepthStencilMatch, 6) { return D3D_OK; }
COM_METHOD(d3d9, CheckDeviceFormatConversion, 5) { return D3D_OK; }

COM_METHOD(d3d9, GetDeviceCaps, 4)
{
    fill_caps(ARG(3));
    return D3D_OK;
}

COM_METHOD(d3d9, GetAdapterMonitor, 2) { return 0x00070001u; }

uint32_t d3d_device_create(uint32_t d3d9, uint32_t window, uint32_t behavior, uint32_t pp, uint32_t *out);
COM_METHOD(d3d9, CreateDevice, 7)
{
    uint32_t out = 0;
    uint32_t hr = d3d_device_create(THIS_, ARG(3), ARG(4), ARG(5), &out);
    MEM32(ARG(6)) = out;
    return hr;
}

static const void_fn d3d9_methods[] = {
    d3d9_QueryInterface, d3d9_AddRef, d3d9_Release, d3d9_RegisterSoftwareDevice, d3d9_GetAdapterCount,
    d3d9_GetAdapterIdentifier, d3d9_GetAdapterModeCount, d3d9_EnumAdapterModes, d3d9_GetAdapterDisplayMode,
    d3d9_CheckDeviceType, d3d9_CheckDeviceFormat, d3d9_CheckDeviceMultiSampleType, d3d9_CheckDepthStencilMatch,
    d3d9_CheckDeviceFormatConversion, d3d9_GetDeviceCaps, d3d9_GetAdapterMonitor, d3d9_CreateDevice,
};
static void_com_class d3d9_class = { "IDirect3D9", 17, d3d9_methods, 0 };

WINAPI_EXPORT("d3d9.dll", Direct3DCreate9, 1)
{
#ifndef HOMM5_LEGACY_UI
    /* The launcher's DXVK renderer (d3d9_dxvk.c); 0 when GLES was chosen or DXVK cannot start. */
    uint32_t dxvk = void_dxvk_create9(ARG(0));
    if (dxvk) return dxvk;
#endif
    d3d9_t *d = (d3d9_t *)calloc(1, sizeof *d);
    uint32_t guest = void_com_wrap(&d->com, &d3d9_class, 0);
    void_log("[d3d9] Direct3DCreate9(%u) = %08X", ARG(0), guest);
    return guest;
}

WINAPI_EXPORT("d3d9.dll", D3DPERF_SetOptions, 1) { return 0; }
WINAPI_EXPORT("d3d9.dll", D3DPERF_BeginEvent, 2) { return 0; }
WINAPI_EXPORT("d3d9.dll", D3DPERF_EndEvent, 0) { return 0; }
WINAPI_EXPORT("d3d9.dll", D3DPERF_GetStatus, 0) { return 0; }

/* ===================================================== device: defaults */
static uint32_t f2u(float f) { uint32_t u; memcpy(&u, &f, 4); return u; }

static void default_state(d3d_device *dev, d3d_state *s)
{
    memset(s, 0, sizeof *s);
    uint32_t *rs = s->rs;
    rs[7] = dev->pp[9] ? 1 : 0;   /* ZENABLE follows EnableAutoDepthStencil */
    rs[8] = 3; rs[9] = 2; rs[14] = 1; rs[16] = 1; rs[19] = 2; rs[20] = 1; rs[22] = 3; rs[23] = 4;
    rs[25] = 8; rs[37] = f2u(1.0f); rs[38] = f2u(1.0f);
    rs[53] = rs[54] = rs[55] = 1; rs[56] = 8; rs[58] = rs[59] = 0xFFFFFFFFu; rs[60] = 0xFFFFFFFFu;
    rs[136] = 1; rs[137] = 1; rs[141] = 1; rs[142] = 1; rs[145] = 1; rs[146] = 2;
    rs[154] = f2u(1.0f); rs[155] = f2u(1.0f); rs[158] = f2u(1.0f); rs[161] = 1; rs[162] = 0xFFFFFFFFu;
    rs[165] = 0xBAADCAFEu; rs[166] = f2u(64.0f); rs[168] = 0xF; rs[171] = 1; rs[172] = 3; rs[173] = 1;
    rs[178] = f2u(1.0f); rs[179] = f2u(1.0f); rs[182] = f2u(1.0f);
    rs[186] = rs[187] = rs[188] = 1; rs[189] = 8; rs[190] = rs[191] = rs[192] = 0xF; rs[193] = 0xFFFFFFFFu;
    rs[207] = 2; rs[208] = 1; rs[209] = 1;
    for (int i = 0; i < 20; ++i) {
        s->ss[i][1] = s->ss[i][2] = s->ss[i][3] = 1;   /* ADDRESS = WRAP */
        s->ss[i][5] = s->ss[i][6] = 1;                 /* MAG/MIN = POINT */
        s->ss[i][10] = 1;                              /* MAXANISOTROPY */
    }
    for (int i = 0; i < 8; ++i) {
        s->tss[i][1] = i ? 1 : 4;     /* COLOROP: MODULATE / DISABLE */
        s->tss[i][2] = 2; s->tss[i][3] = 1;
        s->tss[i][4] = i ? 1 : 2;     /* ALPHAOP: SELECTARG1 / DISABLE */
        s->tss[i][5] = 2; s->tss[i][6] = 1;
        s->tss[i][11] = (uint32_t)i;  /* TEXCOORDINDEX */
        s->tss[i][26] = s->tss[i][27] = s->tss[i][28] = 1;
    }
    for (int t = 0; t < 512; ++t) for (int k = 0; k < 4; ++k) s->transforms[t][k * 5] = 1.0f;
    for (int i = 0; i < 16; ++i) s->stream_freq[i] = 1;
}

static void set_default_viewport(d3d_device *dev, d3d_surface *rt)
{
    dev->st.viewport[0] = dev->st.viewport[1] = 0;
    dev->st.viewport[2] = rt ? rt->width : 1;
    dev->st.viewport[3] = rt ? rt->height : 1;
    dev->st.viewport_z[0] = 0.0f;
    dev->st.viewport_z[1] = 1.0f;
    dev->st.scissor[0] = dev->st.scissor[1] = 0;
    dev->st.scissor[2] = rt ? rt->width : 1;
    dev->st.scissor[3] = rt ? rt->height : 1;
}

/* Reference counts the device holds on bound objects, like D3D. */
void d3d_ref_set(void **slot, void *object)
{
    if (*slot == object) return;
    if (object) void_com_addref((void_com_object *)object);
    if (*slot) void_com_release((void_com_object *)*slot);
    *slot = object;
}
#define bind_ref d3d_ref_set

void d3d_state_release(d3d_state *state)
{
    for (int i = 0; i < 20; ++i) bind_ref(&state->textures[i], NULL);
    for (int i = 0; i < 16; ++i) bind_ref(&state->streams[i], NULL);
    bind_ref(&state->indices, NULL);
    bind_ref(&state->decl, NULL);
    bind_ref(&state->vs, NULL);
    bind_ref(&state->ps, NULL);
}

static void *host_or_null(uint32_t guest) { return guest ? void_com_host(guest) : NULL; }

/* Render target and depth slots hold a reference on the surface's owner: a
 * texture level keeps its texture alive while bound (as in D3D9). */
/* Returns whether the slot changed. */
static int bind_surface(d3d_surface **slot, d3d_surface *s)
{
    if (*slot == s) return 0;
    if (s) void_com_addref(d3d_surface_owner(s));
    if (*slot) void_com_release(d3d_surface_owner(*slot));
    *slot = s;
    return 1;
}

static void make_backbuffer(d3d_device *dev)
{
    uint32_t w = dev->pp[0], h = dev->pp[1];
    if (!w || !h) {
        int ww, hh;
        void_window_client_size(dev->window, &ww, &hh);
        w = ww > 0 ? (uint32_t)ww : 1280;
        h = hh > 0 ? (uint32_t)hh : 720;
        dev->pp[0] = w; dev->pp[1] = h;
    }
    uint32_t format = dev->pp[2] ? dev->pp[2] : 22;
    if (format == 0) format = 22;
    if (dev->backbuffer) void_com_release(&dev->backbuffer->com);
    dev->backbuffer = d3d_surface_new(dev, w, h, format, D3DUSAGE_RENDERTARGET, D3DPOOL_DEFAULT, 0);
    if (dev->auto_depth) { void_com_release(&dev->auto_depth->com); dev->auto_depth = NULL; }
    if (dev->pp[9]) dev->auto_depth = d3d_surface_new(dev, w, h, dev->pp[10], D3DUSAGE_DEPTHSTENCIL, D3DPOOL_DEFAULT, 0);
    for (int i = 0; i < 4; ++i) bind_surface(&dev->rt[i], NULL);
    bind_surface(&dev->ds, NULL);
    bind_surface(&dev->rt[0], dev->backbuffer);
    if (dev->auto_depth) bind_surface(&dev->ds, dev->auto_depth);
    dev->fbo_dirty = 1;
    /* Touch coordinates must use the same size as the image being presented. */
    void_input_set_screen_size((int)dev->backbuffer->width, (int)dev->backbuffer->height);
}

/* ======================================================= device methods */
#define DEV ((d3d_device *)void_com_host(THIS_))

COM_METHOD(dev, QueryInterface, 3)
{
    d3d_device *d = DEV;
    if (void_guid_equal(ARG(1), IID_IDirect3DDevice9) || void_guid_equal(ARG(1), IID_IUnknown)) {
        void_com_addref(&d->com);
        MEM32(ARG(2)) = THIS_;
        return 0;
    }
    MEM32(ARG(2)) = 0;
    return E_NOINTERFACE_;
}
COM_METHOD(dev, AddRef, 1) { return void_com_addref(&DEV->com); }
COM_METHOD(dev, Release, 1) { return void_com_release(&DEV->com); }
COM_METHOD(dev, TestCooperativeLevel, 1) { return D3D_OK; }
COM_METHOD(dev, GetAvailableTextureMem, 1) { return 1024u << 20; }
COM_METHOD(dev, EvictManagedResources, 1) { return D3D_OK; }
COM_METHOD(dev, GetDirect3D, 2)
{
    d3d_device *d = DEV;
    void_com_addref((void_com_object *)void_com_host(d->d3d9));
    MEM32(ARG(1)) = d->d3d9;
    return D3D_OK;
}
COM_METHOD(dev, GetDeviceCaps, 2) { fill_caps(ARG(1)); return D3D_OK; }
COM_METHOD(dev, GetDisplayMode, 3)
{
    int w, h;
    void_input_screen_size(&w, &h);
    uint32_t out = ARG(2);
    MEM32(out) = (uint32_t)w; MEM32(out + 4) = (uint32_t)h; MEM32(out + 8) = 60; MEM32(out + 12) = 22;
    return D3D_OK;
}
COM_METHOD(dev, GetCreationParameters, 2)
{
    d3d_device *d = DEV;
    uint32_t out = ARG(1);
    MEM32(out) = 0; MEM32(out + 4) = 1; MEM32(out + 8) = d->window; MEM32(out + 12) = d->behavior;
    return D3D_OK;
}
COM_METHOD(dev, SetCursorProperties, 4) { return D3D_OK; }
COM_METHOD(dev, SetCursorPosition, 4) { return 0; }
COM_METHOD(dev, ShowCursor, 2) { return 0; }
COM_METHOD(dev, CreateAdditionalSwapChain, 3) { void_log("[d3d9] CreateAdditionalSwapChain unsupported"); return D3DERR_INVALIDCALL; }
COM_METHOD(dev, GetSwapChain, 3)
{
    d3d_device *d = DEV;
    if (ARG(1)) return D3DERR_INVALIDCALL;
    void_com_addref((void_com_object *)void_com_host(d->swapchain));
    MEM32(ARG(2)) = d->swapchain;
    return D3D_OK;
}
COM_METHOD(dev, GetNumberOfSwapChains, 1) { return 1; }

COM_METHOD(dev, Reset, 2)
{
    d3d_device *d = DEV;
    uint32_t pp = ARG(1);
    for (int i = 0; i < 14; ++i) d->pp[i] = MEM32(pp + 4u * (uint32_t)i);
    if (!d->pp[2]) d->pp[2] = 22;
    make_backbuffer(d);
    for (int i = 0; i < 14; ++i) MEM32(pp + 4u * (uint32_t)i) = d->pp[i];
    d3d_state_release(&d->st);
    default_state(d, &d->st);
    set_default_viewport(d, d->backbuffer);
    void_log("[d3d9] Reset %ux%u format %u depth %u/%u", d->pp[0], d->pp[1], d->pp[2], d->pp[9], d->pp[10]);
    return D3D_OK;
}

COM_METHOD(dev, Present, 5)
{
    d3d_device *d = DEV;
    d3d_gl_present(d);
    ++d->frame;
    void_touch_frame_presented();
    d3d_gl_frame_pace();
    if (recomp_yield_hook) recomp_yield_hook();
    return D3D_OK;
}

COM_METHOD(dev, GetBackBuffer, 5)
{
    d3d_device *d = DEV;
    if (ARG(1) || ARG(2)) return D3DERR_INVALIDCALL;
    void_com_addref(&d->backbuffer->com);
    MEM32(ARG(4)) = d->backbuffer->com.guest;
    return D3D_OK;
}

COM_METHOD(dev, GetRasterStatus, 3) { MEM32(ARG(2)) = 0; MEM32(ARG(2) + 4) = 0; return D3D_OK; }
COM_METHOD(dev, SetDialogBoxMode, 2) { return D3D_OK; }
COM_METHOD(dev, SetGammaRamp, 4) { return 0; }
COM_METHOD(dev, GetGammaRamp, 3)
{
    uint32_t ramp = ARG(2);
    for (uint32_t i = 0; i < 256; ++i) MEM16(ramp + 2 * i) = MEM16(ramp + 512 + 2 * i) = MEM16(ramp + 1024 + 2 * i) = (uint16_t)(i * 257);
    return 0;
}

COM_METHOD(dev, CreateTexture, 9)
{
    d3d_device *d = DEV;
    uint32_t w = ARG(1), h = ARG(2), levels = ARG(3), usage = ARG(4), format = ARG(5), pool = ARG(6);
    if (!d3d_format_find(format)) { void_log("[d3d9] CreateTexture: unsupported format %u", format); return D3DERR_INVALIDCALL; }
    d3d_texture *t = d3d_texture_new(d, D3DRTYPE_TEXTURE, w, h, 1, levels, usage, format, pool);
    if (!t) return D3DERR_INVALIDCALL;
    MEM32(ARG(7)) = d3d_wrap_texture(t);
    if (d3d_trace_active()) void_log("[trace] CreateTexture %ux%u levels %u usage %X format %u pool %u = %08X", w, h, t->levels,
        usage, format, pool, MEM32(ARG(7)));
    VLOG("[d3d9] CreateTexture %ux%u levels %u usage %X format %u pool %u = %08X caller %08X", w, h, t->levels, usage, format, pool,
         MEM32(ARG(7)), MEM32(g_esp));
    return D3D_OK;
}

COM_METHOD(dev, CreateVolumeTexture, 10)
{
    d3d_device *d = DEV;
    uint32_t w = ARG(1), h = ARG(2), depth = ARG(3), levels = ARG(4), usage = ARG(5), format = ARG(6), pool = ARG(7);
    if (!d3d_format_find(format)) return D3DERR_INVALIDCALL;
    d3d_texture *t = d3d_texture_new(d, D3DRTYPE_VOLUMETEXTURE, w, h, depth, levels, usage, format, pool);
    if (!t) return D3DERR_INVALIDCALL;
    MEM32(ARG(8)) = d3d_wrap_texture(t);
    return D3D_OK;
}

COM_METHOD(dev, CreateCubeTexture, 8)
{
    d3d_device *d = DEV;
    uint32_t edge = ARG(1), levels = ARG(2), usage = ARG(3), format = ARG(4), pool = ARG(5);
    if (!d3d_format_find(format)) { void_log("[d3d9] CreateCubeTexture: unsupported format %u", format); return D3DERR_INVALIDCALL; }
    d3d_texture *t = d3d_texture_new(d, D3DRTYPE_CUBETEXTURE, edge, edge, 1, levels, usage, format, pool);
    if (!t) return D3DERR_INVALIDCALL;
    MEM32(ARG(6)) = d3d_wrap_texture(t);
    return D3D_OK;
}

uint32_t d3d_buffer_create(d3d_device *dev, int index, uint32_t length, uint32_t usage, uint32_t format, uint32_t pool);

COM_METHOD(dev, CreateVertexBuffer, 7)
{
    uint32_t b = d3d_buffer_create(DEV, 0, ARG(1), ARG(2), ARG(3), ARG(4));
    MEM32(ARG(5)) = b;
    return b ? D3D_OK : D3DERR_OUTOFVIDEOMEMORY;
}

COM_METHOD(dev, CreateIndexBuffer, 7)
{
    uint32_t b = d3d_buffer_create(DEV, 1, ARG(1), ARG(2), ARG(3), ARG(4));
    MEM32(ARG(5)) = b;
    return b ? D3D_OK : D3DERR_OUTOFVIDEOMEMORY;
}

COM_METHOD(dev, CreateRenderTarget, 9)
{
    d3d_device *d = DEV;
    if (!d3d_format_find(ARG(3))) return D3DERR_INVALIDCALL;
    d3d_surface *s = d3d_surface_new(d, ARG(1), ARG(2), ARG(3), D3DUSAGE_RENDERTARGET, D3DPOOL_DEFAULT, ARG(4));
    MEM32(ARG(7)) = s->com.guest;
    VLOG("[d3d9] CreateRenderTarget %ux%u format %u = %08X", ARG(1), ARG(2), ARG(3), s->com.guest);
    return D3D_OK;
}

COM_METHOD(dev, CreateDepthStencilSurface, 9)
{
    d3d_device *d = DEV;
    if (!d3d_format_find(ARG(3))) return D3DERR_INVALIDCALL;
    d3d_surface *s = d3d_surface_new(d, ARG(1), ARG(2), ARG(3), D3DUSAGE_DEPTHSTENCIL, D3DPOOL_DEFAULT, ARG(4));
    MEM32(ARG(7)) = s->com.guest;
    return D3D_OK;
}

void d3d_update_surface(d3d_surface *src, uint32_t src_rect, d3d_surface *dst, uint32_t dst_point);
COM_METHOD(dev, UpdateSurface, 5)
{
    d3d_update_surface((d3d_surface *)void_com_host(ARG(1)), ARG(2), (d3d_surface *)void_com_host(ARG(3)), ARG(4));
    return D3D_OK;
}

void d3d_update_texture(d3d_texture *src, d3d_texture *dst);
COM_METHOD(dev, UpdateTexture, 3)
{
    d3d_update_texture((d3d_texture *)void_com_host(ARG(1)), (d3d_texture *)void_com_host(ARG(2)));
    return D3D_OK;
}

COM_METHOD(dev, GetRenderTargetData, 3)
{
    d3d_surface *src = (d3d_surface *)void_com_host(ARG(1)), *dst = (d3d_surface *)void_com_host(ARG(2));
    if (!dst->sysmem || src->width != dst->width || src->height != dst->height) return D3DERR_INVALIDCALL;
    d3d_gl_read_surface(src, dst->sysmem, dst->pitch);
    return D3D_OK;
}

COM_METHOD(dev, GetFrontBufferData, 3)
{
    d3d_device *d = DEV;
    d3d_surface *dst = (d3d_surface *)void_com_host(ARG(2));
    if (!dst->sysmem) return D3DERR_INVALIDCALL;
    d3d_gl_read_surface(d->backbuffer, dst->sysmem, dst->pitch);
    return D3D_OK;
}

static int read_rect(uint32_t va, d3d_surface *s, uint32_t r[4])
{
    if (!va) { r[0] = r[1] = 0; r[2] = s->width; r[3] = s->height; return 1; }
    for (int i = 0; i < 4; ++i) r[i] = MEM32(va + 4u * (uint32_t)i);
    return 1;
}

COM_METHOD(dev, StretchRect, 6)
{
    d3d_surface *src = (d3d_surface *)void_com_host(ARG(1)), *dst = (d3d_surface *)void_com_host(ARG(3));
    uint32_t sr[4], dr[4];
    read_rect(ARG(2), src, sr);
    read_rect(ARG(4), dst, dr);
    d3d_gl_blit(src, sr, dst, dr, ARG(5));
    return D3D_OK;
}

COM_METHOD(dev, ColorFill, 4)
{
    d3d_surface *s = (d3d_surface *)void_com_host(ARG(1));
    uint32_t r[4];
    read_rect(ARG(2), s, r);
    d3d_gl_fill(s, r, ARG(3));
    return D3D_OK;
}

COM_METHOD(dev, CreateOffscreenPlainSurface, 7)
{
    d3d_device *d = DEV;
    if (!d3d_format_find(ARG(3))) return D3DERR_INVALIDCALL;
    d3d_surface *s = d3d_surface_new(d, ARG(1), ARG(2), ARG(3), 0, ARG(4), 0);
    MEM32(ARG(5)) = s->com.guest;
    return D3D_OK;
}

COM_METHOD(dev, SetRenderTarget, 3)
{
    d3d_device *d = DEV;
    uint32_t index = ARG(1);
    if (index > 3 || (index == 0 && !ARG(2))) return D3DERR_INVALIDCALL;
    d3d_surface *s = (d3d_surface *)host_or_null(ARG(2));
    if (bind_surface(&d->rt[index], s)) d->fbo_dirty = 1;
    if (index == 0) set_default_viewport(d, s);
    return D3D_OK;
}

COM_METHOD(dev, GetRenderTarget, 3)
{
    d3d_device *d = DEV;
    uint32_t index = ARG(1);
    if (index > 3) return D3DERR_INVALIDCALL;
    if (!d->rt[index]) { MEM32(ARG(2)) = 0; return D3DERR_NOTFOUND; }
    void_com_addref(d3d_surface_owner(d->rt[index]));
    MEM32(ARG(2)) = d->rt[index]->com.guest;
    return D3D_OK;
}

COM_METHOD(dev, SetDepthStencilSurface, 2)
{
    d3d_device *d = DEV;
    if (bind_surface(&d->ds, (d3d_surface *)host_or_null(ARG(1)))) d->fbo_dirty = 1;
    return D3D_OK;
}

COM_METHOD(dev, GetDepthStencilSurface, 2)
{
    d3d_device *d = DEV;
    if (!d->ds) { MEM32(ARG(1)) = 0; return D3DERR_NOTFOUND; }
    void_com_addref(d3d_surface_owner(d->ds));
    MEM32(ARG(1)) = d->ds->com.guest;
    return D3D_OK;
}

COM_METHOD(dev, BeginScene, 1)
{
    d3d_device *d = DEV;
    /* H5's normal frame has presented and released its old batches at this call. */
    if (g_cur_func == 0x00A3FB70u && !d->in_scene && !d->recording)
        void_touch_render_frame_pump();
    if (g_d3d_device != d) return D3DERR_INVALIDCALL;
    d->in_scene = 1;
    return D3D_OK;
}
COM_METHOD(dev, EndScene, 1) { DEV->in_scene = 0; return D3D_OK; }

COM_METHOD(dev, Clear, 7)
{
    float z;
    uint32_t zbits = ARG(5);
    memcpy(&z, &zbits, 4);
    d3d_gl_clear(DEV, ARG(1), ARG(2), ARG(3), ARG(4), z, ARG(6));
    return D3D_OK;
}

/* ---------------------------------------------------------- recording */
#define REC(field) (d->recording ? (d->recording->field = 1) : 0)

static d3d_state *target_state(d3d_device *d) { return d->recording ? &d->recording->state : &d->st; }

static uint32_t transform_slot(uint32_t state)
{
    if (state < 256) return state & 511;
    return 256u + ((state - 256u) & 255u);
}

COM_METHOD(dev, SetTransform, 3)
{
    d3d_device *d = DEV;
    uint32_t slot = transform_slot(ARG(1));
    memcpy(target_state(d)->transforms[slot], GPTR(ARG(2)), 64);
    if (d->recording) d->recording->rec_transform[slot] = 1;
    return D3D_OK;
}

COM_METHOD(dev, GetTransform, 3)
{
    memcpy(GPTR(ARG(2)), DEV->st.transforms[transform_slot(ARG(1))], 64);
    return D3D_OK;
}

COM_METHOD(dev, MultiplyTransform, 3)
{
    d3d_device *d = DEV;
    uint32_t slot = transform_slot(ARG(1));
    float a[16], b[16], r[16];
    memcpy(a, d->st.transforms[slot], 64);
    memcpy(b, GPTR(ARG(2)), 64);
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) {
        float s = 0;
        for (int k = 0; k < 4; ++k) s += a[i * 4 + k] * b[k * 4 + j];
        r[i * 4 + j] = s;
    }
    memcpy(target_state(d)->transforms[slot], r, 64);
    return D3D_OK;
}

COM_METHOD(dev, SetViewport, 2)
{
    d3d_device *d = DEV;
    d3d_state *s = target_state(d);
    uint32_t vp = ARG(1);
    for (int i = 0; i < 4; ++i) s->viewport[i] = MEM32(vp + 4u * (uint32_t)i);
    memcpy(s->viewport_z, GPTR(vp + 16), 8);
    if (d->recording) d->recording->rec_viewport = 1;
    return D3D_OK;
}

COM_METHOD(dev, GetViewport, 2)
{
    d3d_device *d = DEV;
    uint32_t vp = ARG(1);
    for (int i = 0; i < 4; ++i) MEM32(vp + 4u * (uint32_t)i) = d->st.viewport[i];
    memcpy(GPTR(vp + 16), d->st.viewport_z, 8);
    return D3D_OK;
}

COM_METHOD(dev, SetMaterial, 2)
{
    d3d_device *d = DEV;
    memcpy(target_state(d)->material, GPTR(ARG(1)), 68);
    if (d->recording) d->recording->rec_material = 1;
    return D3D_OK;
}
COM_METHOD(dev, GetMaterial, 2) { memcpy(GPTR(ARG(1)), DEV->st.material, 68); return D3D_OK; }

COM_METHOD(dev, SetLight, 3)
{
    d3d_device *d = DEV;
    if (ARG(1) >= 8) return D3D_OK;
    memcpy(target_state(d)->lights[ARG(1)], GPTR(ARG(2)), 104);
    if (d->recording) d->recording->rec_light[ARG(1)] = 1;
    return D3D_OK;
}
COM_METHOD(dev, GetLight, 3)
{
    if (ARG(1) >= 8) return D3DERR_INVALIDCALL;
    memcpy(GPTR(ARG(2)), DEV->st.lights[ARG(1)], 104);
    return D3D_OK;
}
COM_METHOD(dev, LightEnable, 3)
{
    d3d_device *d = DEV;
    if (ARG(1) >= 8) return D3D_OK;
    target_state(d)->light_enable[ARG(1)] = ARG(2) != 0;
    if (d->recording) d->recording->rec_light[ARG(1)] = 1;
    return D3D_OK;
}
COM_METHOD(dev, GetLightEnable, 3)
{
    if (ARG(1) >= 8) return D3DERR_INVALIDCALL;
    MEM32(ARG(2)) = DEV->st.light_enable[ARG(1)] ? 128u : 0u;
    return D3D_OK;
}
COM_METHOD(dev, SetClipPlane, 3)
{
    d3d_device *d = DEV;
    if (ARG(1) >= 6) return D3DERR_INVALIDCALL;
    memcpy(target_state(d)->clip_planes[ARG(1)], GPTR(ARG(2)), 16);
    if (d->recording) d->recording->rec_clip[ARG(1)] = 1;
    return D3D_OK;
}
COM_METHOD(dev, GetClipPlane, 3)
{
    if (ARG(1) >= 6) return D3DERR_INVALIDCALL;
    memcpy(GPTR(ARG(2)), DEV->st.clip_planes[ARG(1)], 16);
    return D3D_OK;
}

COM_METHOD(dev, SetRenderState, 3)
{
    d3d_device *d = DEV;
    uint32_t state = ARG(1);
    if (state >= 256) return D3D_OK;
    target_state(d)->rs[state] = ARG(2);
    if (d->recording) d->recording->rec_rs[state] = 1;
    return D3D_OK;
}

COM_METHOD(dev, GetRenderState, 3)
{
    uint32_t state = ARG(1);
    MEM32(ARG(2)) = state < 256 ? DEV->st.rs[state] : 0;
    return D3D_OK;
}

/* ---------------------------------------------------------- state blocks */
uint32_t d3d_stateblock_create(d3d_device *dev, uint32_t type);
void d3d_stateblock_capture(d3d_stateblock *sb);

COM_METHOD(dev, CreateStateBlock, 3)
{
    uint32_t sb = d3d_stateblock_create(DEV, ARG(1));
    MEM32(ARG(2)) = sb;
    return sb ? D3D_OK : D3DERR_INVALIDCALL;
}

COM_METHOD(dev, BeginStateBlock, 1)
{
    d3d_device *d = DEV;
    if (d->recording) return D3DERR_INVALIDCALL;
    uint32_t guest = d3d_stateblock_create(d, 0);   /* empty: records nothing yet */
    d->recording = (d3d_stateblock *)void_com_host(guest);
    /* Values start from the device's (only recorded items are applied);
     * object slots start empty: the block holds references only on the
     * objects recorded into it. */
    d->recording->state = d->st;
    d3d_state *s = &d->recording->state;
    memset(s->textures, 0, sizeof s->textures);
    memset(s->streams, 0, sizeof s->streams);
    s->indices = s->decl = s->vs = s->ps = NULL;
    return D3D_OK;
}

COM_METHOD(dev, EndStateBlock, 2)
{
    d3d_device *d = DEV;
    if (!d->recording) return D3DERR_INVALIDCALL;
    MEM32(ARG(1)) = d->recording->com.guest;
    d->recording = NULL;
    return D3D_OK;
}

COM_METHOD(dev, SetClipStatus, 2) { return D3D_OK; }
COM_METHOD(dev, GetClipStatus, 2) { MEM32(ARG(1)) = 0; MEM32(ARG(1) + 4) = 0; return D3D_OK; }

static int sampler_slot(uint32_t sampler)
{
    if (sampler < 16) return (int)sampler;
    if (sampler >= 256 && sampler <= 260) return 16 + (int)(sampler - 257 < 4 ? sampler - 257 : 0);
    return -1;
}

COM_METHOD(dev, GetTexture, 3)
{
    d3d_device *d = DEV;
    int slot = sampler_slot(ARG(1));
    void_com_object *t = slot >= 0 ? (void_com_object *)d->st.textures[slot] : NULL;
    if (t) void_com_addref(t);
    MEM32(ARG(2)) = t ? t->guest : 0;
    return D3D_OK;
}

COM_METHOD(dev, SetTexture, 3)
{
    d3d_device *d = DEV;
    int slot = sampler_slot(ARG(1));
    if (d3d_trace_active()) {
        d3d_texture *t = (d3d_texture *)host_or_null(ARG(2));
        void_log("[trace] SetTexture(%u -> slot %d, %08X: %ux%u fmt %u)%s", ARG(1), slot, ARG(2), t ? t->width : 0,
            t ? t->height : 0, t ? t->format : 0, d->recording ? " recording" : "");
    }
    if (slot < 0) return D3DERR_INVALIDCALL;
    if (d->recording) {
        d3d_ref_set(&d->recording->state.textures[slot], host_or_null(ARG(2)));
        d->recording->rec_tex[slot] = 1;
        return D3D_OK;
    }
    bind_ref(&d->st.textures[slot], host_or_null(ARG(2)));
    return D3D_OK;
}

COM_METHOD(dev, GetTextureStageState, 4)
{
    MEM32(ARG(3)) = (ARG(1) < 8 && ARG(2) < 33) ? DEV->st.tss[ARG(1)][ARG(2)] : 0;
    return D3D_OK;
}

COM_METHOD(dev, SetTextureStageState, 4)
{
    d3d_device *d = DEV;
    if (ARG(1) >= 8 || ARG(2) >= 33) return D3D_OK;
    target_state(d)->tss[ARG(1)][ARG(2)] = ARG(3);
    if (d->recording) d->recording->rec_tss[ARG(1)][ARG(2)] = 1;
    return D3D_OK;
}

COM_METHOD(dev, GetSamplerState, 4)
{
    int slot = sampler_slot(ARG(1));
    MEM32(ARG(3)) = (slot >= 0 && ARG(2) < 14) ? DEV->st.ss[slot][ARG(2)] : 0;
    return D3D_OK;
}

COM_METHOD(dev, SetSamplerState, 4)
{
    d3d_device *d = DEV;
    int slot = sampler_slot(ARG(1));
    if (slot < 0 || ARG(2) >= 14) return D3D_OK;
    target_state(d)->ss[slot][ARG(2)] = ARG(3);
    if (d->recording) d->recording->rec_ss[slot][ARG(2)] = 1;
    return D3D_OK;
}

COM_METHOD(dev, ValidateDevice, 2) { if (ARG(1)) MEM32(ARG(1)) = 1; return D3D_OK; }
COM_METHOD(dev, SetPaletteEntries, 3) { return D3D_OK; }
COM_METHOD(dev, GetPaletteEntries, 3) { return D3DERR_INVALIDCALL; }
COM_METHOD(dev, SetCurrentTexturePalette, 2) { return D3D_OK; }
COM_METHOD(dev, GetCurrentTexturePalette, 2) { MEM32(ARG(1)) = 0; return D3D_OK; }

COM_METHOD(dev, SetScissorRect, 2)
{
    d3d_device *d = DEV;
    d3d_state *s = target_state(d);
    uint32_t r = ARG(1);
    s->scissor[0] = MEM32(r); s->scissor[1] = MEM32(r + 4);
    s->scissor[2] = MEM32(r + 8) - MEM32(r); s->scissor[3] = MEM32(r + 12) - MEM32(r + 4);
    if (d->recording) d->recording->rec_scissor = 1;
    return D3D_OK;
}

COM_METHOD(dev, GetScissorRect, 2)
{
    d3d_device *d = DEV;
    uint32_t r = ARG(1);
    MEM32(r) = d->st.scissor[0]; MEM32(r + 4) = d->st.scissor[1];
    MEM32(r + 8) = d->st.scissor[0] + d->st.scissor[2]; MEM32(r + 12) = d->st.scissor[1] + d->st.scissor[3];
    return D3D_OK;
}

COM_METHOD(dev, SetSoftwareVertexProcessing, 2) { return D3D_OK; }
COM_METHOD(dev, GetSoftwareVertexProcessing, 1) { return 0; }
COM_METHOD(dev, SetNPatchMode, 2) { return D3D_OK; }
/* float return value: ST0. */
static void dev_GetNPatchMode(void) { g_st[0] = 0.0; fp_push_impl(g_st, &g_fp_top, 0.0); g_esp += 8; }

/* ----------------------------------------------------------------- draws */
static uint32_t vertex_count_for(uint32_t primitive, uint32_t count)
{
    switch (primitive) {
    case 1: return count;              /* POINTLIST */
    case 2: return count * 2;          /* LINELIST */
    case 3: return count + 1;          /* LINESTRIP */
    case 4: return count * 3;          /* TRIANGLELIST */
    case 5: return count + 2;          /* TRIANGLESTRIP */
    case 6: return count + 2;          /* TRIANGLEFAN */
    default: return 0;
    }
}

COM_METHOD(dev, DrawPrimitive, 4)
{
    d3d_device *d = DEV;
    uint32_t primitive = ARG(1), start = ARG(2), count = ARG(3);
    if (!count) return D3D_OK;
    d3d_gl_draw(d, primitive, start, vertex_count_for(primitive, count), count, 0, 0, 0, 0, NULL, 0, NULL, 0);
    return D3D_OK;
}

COM_METHOD(dev, DrawIndexedPrimitive, 7)
{
    d3d_device *d = DEV;
    uint32_t primitive = ARG(1), base = ARG(2), min_index = ARG(3), vertices = ARG(4), start_index = ARG(5), count = ARG(6);
    if (!count) return D3D_OK;
    (void)vertices;
    d3d_gl_draw(d, primitive, 0, vertex_count_for(primitive, count), count, 1, base, start_index, min_index, NULL, 0, NULL, 0);
    return D3D_OK;
}

COM_METHOD(dev, DrawPrimitiveUP, 5)
{
    d3d_device *d = DEV;
    uint32_t primitive = ARG(1), count = ARG(2), data = ARG(3), stride = ARG(4);
    if (!count) return D3D_OK;
    d3d_gl_draw(d, primitive, 0, vertex_count_for(primitive, count), count, 0, 0, 0, 0, GPTR(data), stride, NULL, 0);
    /* D3D unbinds stream 0 and the index buffer after a UP draw. */
    bind_ref(&d->st.streams[0], NULL);
    d->st.stream_offset[0] = d->st.stream_stride[0] = 0;
    return D3D_OK;
}

COM_METHOD(dev, DrawIndexedPrimitiveUP, 9)
{
    d3d_device *d = DEV;
    uint32_t primitive = ARG(1), min_index = ARG(2), vertices = ARG(3), count = ARG(4), indices = ARG(5);
    uint32_t index_format = ARG(6), data = ARG(7), stride = ARG(8);
    if (!count) return D3D_OK;
    (void)vertices;
    d3d_gl_draw(d, primitive, 0, vertex_count_for(primitive, count), count, 1, 0, 0, min_index, GPTR(data), stride,
        GPTR(indices), index_format == 102);
    bind_ref(&d->st.streams[0], NULL);
    bind_ref(&d->st.indices, NULL);
    d->st.stream_offset[0] = d->st.stream_stride[0] = 0;
    return D3D_OK;
}

COM_METHOD(dev, ProcessVertices, 7) { void_log("[d3d9] ProcessVertices unsupported"); return D3DERR_INVALIDCALL; }

uint32_t d3d_decl_create(d3d_device *dev, uint32_t elements, uint32_t fvf);
COM_METHOD(dev, CreateVertexDeclaration, 3)
{
    uint32_t decl = d3d_decl_create(DEV, ARG(1), 0);
    MEM32(ARG(2)) = decl;
    return decl ? D3D_OK : D3DERR_INVALIDCALL;
}

COM_METHOD(dev, SetVertexDeclaration, 2)
{
    d3d_device *d = DEV;
    if (d->recording) { d3d_ref_set(&d->recording->state.decl, host_or_null(ARG(1))); d->recording->rec_decl = 1; return D3D_OK; }
    bind_ref(&d->st.decl, host_or_null(ARG(1)));
    d->st.fvf = 0;
    return D3D_OK;
}

COM_METHOD(dev, GetVertexDeclaration, 2)
{
    d3d_device *d = DEV;
    void_com_object *o = (void_com_object *)d->st.decl;
    if (o) void_com_addref(o);
    MEM32(ARG(1)) = o ? o->guest : 0;
    return D3D_OK;
}

/* SetFVF selects an implicit declaration built from the FVF code. */
static struct { uint32_t fvf; uint32_t guest; } fvf_decls[64];
static int fvf_decl_count;

/* The implicit declaration of an FVF code (cached; the cache owns the
 * creation reference). */
static void *fvf_declaration(d3d_device *d, uint32_t fvf)
{
    uint32_t guest = 0;
    for (int i = 0; i < fvf_decl_count; ++i) if (fvf_decls[i].fvf == fvf) guest = fvf_decls[i].guest;
    if (!guest) {
        guest = d3d_decl_create(d, 0, fvf);
        int slot = fvf_decl_count < 64 ? fvf_decl_count++ : 0;
        if (fvf_decls[slot].guest) void_com_release((void_com_object *)void_com_host(fvf_decls[slot].guest));
        fvf_decls[slot].fvf = fvf;
        fvf_decls[slot].guest = guest;
    }
    return void_com_host(guest);
}

COM_METHOD(dev, SetFVF, 2)
{
    d3d_device *d = DEV;
    uint32_t fvf = ARG(1);
    if (d->recording) {
        /* SetFVF replaces the vertex declaration: a block records both. */
        d->recording->state.fvf = fvf;
        d->recording->rec_fvf = 1;
        if (fvf) {
            d3d_ref_set(&d->recording->state.decl, fvf_declaration(d, fvf));
            d->recording->rec_decl = 1;
        }
        return D3D_OK;
    }
    d->st.fvf = fvf;
    if (!fvf) return D3D_OK;
    bind_ref(&d->st.decl, fvf_declaration(d, fvf));
    return D3D_OK;
}

COM_METHOD(dev, GetFVF, 2) { MEM32(ARG(1)) = DEV->st.fvf; return D3D_OK; }

COM_METHOD(dev, CreateVertexShader, 3)
{
    d3d_shader *s = d3d_shader_create(DEV, 0, ARG(1));
    if (!s) { MEM32(ARG(2)) = 0; return D3DERR_INVALIDCALL; }
    MEM32(ARG(2)) = d3d_wrap_shader(s);
    return D3D_OK;
}

COM_METHOD(dev, SetVertexShader, 2)
{
    d3d_device *d = DEV;
    if (d->recording) { d3d_ref_set(&d->recording->state.vs, host_or_null(ARG(1))); d->recording->rec_vs = 1; return D3D_OK; }
    bind_ref(&d->st.vs, host_or_null(ARG(1)));
    return D3D_OK;
}

COM_METHOD(dev, GetVertexShader, 2)
{
    void_com_object *o = (void_com_object *)DEV->st.vs;
    if (o) void_com_addref(o);
    MEM32(ARG(1)) = o ? o->guest : 0;
    return D3D_OK;
}

extern uint32_t d3d_constant_generation;
#define CONST_SET(field, rec, limit, width) do { \
    d3d_device *d = DEV; d3d_state *s = target_state(d); \
    uint32_t start = ARG(1), data = ARG(2), count = ARG(3); \
    if (start + count > (limit)) return D3DERR_INVALIDCALL; \
    memcpy(&s->field[start], GPTR(data), (size_t)count * (width)); \
    if (d->recording) for (uint32_t i = 0; i < count; ++i) d->recording->rec[start + i] = 1; \
    d->constants_dirty = 1; ++d3d_constant_generation; return D3D_OK; } while (0)
#define CONST_GET(field, limit, width) do { \
    d3d_device *d = DEV; uint32_t start = ARG(1), data = ARG(2), count = ARG(3); \
    if (start + count > (limit)) return D3DERR_INVALIDCALL; \
    memcpy(GPTR(data), &d->st.field[start], (size_t)count * (width)); return D3D_OK; } while (0)

COM_METHOD(dev, SetVertexShaderConstantF, 4) { CONST_SET(vs_f, rec_vs_f, 256, 16); }
COM_METHOD(dev, GetVertexShaderConstantF, 4) { CONST_GET(vs_f, 256, 16); }
COM_METHOD(dev, SetVertexShaderConstantI, 4) { CONST_SET(vs_i, rec_vs_i, 16, 16); }
COM_METHOD(dev, GetVertexShaderConstantI, 4) { CONST_GET(vs_i, 16, 16); }
COM_METHOD(dev, SetVertexShaderConstantB, 4) { CONST_SET(vs_b, rec_vs_b, 16, 4); }
COM_METHOD(dev, GetVertexShaderConstantB, 4) { CONST_GET(vs_b, 16, 4); }

COM_METHOD(dev, SetStreamSource, 5)
{
    d3d_device *d = DEV;
    uint32_t n = ARG(1);
    if (n >= 16) return D3DERR_INVALIDCALL;
    if (d->recording) {
        d3d_ref_set(&d->recording->state.streams[n], host_or_null(ARG(2)));
        d->recording->state.stream_offset[n] = ARG(3);
        d->recording->state.stream_stride[n] = ARG(4);
        d->recording->rec_stream[n] = 1;
        return D3D_OK;
    }
    bind_ref(&d->st.streams[n], host_or_null(ARG(2)));
    d->st.stream_offset[n] = ARG(3);
    d->st.stream_stride[n] = ARG(4);
    return D3D_OK;
}

COM_METHOD(dev, GetStreamSource, 5)
{
    d3d_device *d = DEV;
    uint32_t n = ARG(1);
    if (n >= 16) return D3DERR_INVALIDCALL;
    void_com_object *o = (void_com_object *)d->st.streams[n];
    if (o) void_com_addref(o);
    MEM32(ARG(2)) = o ? o->guest : 0;
    MEM32(ARG(3)) = d->st.stream_offset[n];
    MEM32(ARG(4)) = d->st.stream_stride[n];
    return D3D_OK;
}

COM_METHOD(dev, SetStreamSourceFreq, 3)
{
    d3d_device *d = DEV;
    if (ARG(1) >= 16) return D3DERR_INVALIDCALL;
    target_state(d)->stream_freq[ARG(1)] = ARG(2);
    return D3D_OK;
}
COM_METHOD(dev, GetStreamSourceFreq, 3) { MEM32(ARG(2)) = ARG(1) < 16 ? DEV->st.stream_freq[ARG(1)] : 1; return D3D_OK; }

COM_METHOD(dev, SetIndices, 2)
{
    d3d_device *d = DEV;
    if (d->recording) { d3d_ref_set(&d->recording->state.indices, host_or_null(ARG(1))); d->recording->rec_indices = 1; return D3D_OK; }
    bind_ref(&d->st.indices, host_or_null(ARG(1)));
    return D3D_OK;
}

COM_METHOD(dev, GetIndices, 2)
{
    void_com_object *o = (void_com_object *)DEV->st.indices;
    if (o) void_com_addref(o);
    MEM32(ARG(1)) = o ? o->guest : 0;
    return D3D_OK;
}

COM_METHOD(dev, CreatePixelShader, 3)
{
    if (getenv("VOID_TRACE_PSDB")) {
        /* RendererD3D's shader database loader (16255330): database, key at [ebp + 8], [ebp + 0xC]. */
        uint32_t k = (g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1);
        if (g_icall_from[k] == 0x16255330u)
            void_log("[psdb] db %08X key %08X code %08X first %08X", MEM32(g_ebp + 8), MEM32(g_ebp + 0xC), ARG(1), MEM32(ARG(1)));
    }
    d3d_shader *s = d3d_shader_create(DEV, 1, ARG(1));
    if (!s) { MEM32(ARG(2)) = 0; return D3DERR_INVALIDCALL; }
    MEM32(ARG(2)) = d3d_wrap_shader(s);
    return D3D_OK;
}

COM_METHOD(dev, SetPixelShader, 2)
{
    d3d_device *d = DEV;
    if (d->recording) { d3d_ref_set(&d->recording->state.ps, host_or_null(ARG(1))); d->recording->rec_ps = 1; return D3D_OK; }
    bind_ref(&d->st.ps, host_or_null(ARG(1)));
    return D3D_OK;
}

COM_METHOD(dev, GetPixelShader, 2)
{
    void_com_object *o = (void_com_object *)DEV->st.ps;
    if (o) void_com_addref(o);
    MEM32(ARG(1)) = o ? o->guest : 0;
    return D3D_OK;
}

COM_METHOD(dev, SetPixelShaderConstantF, 4)
{
    if (d3d_trace_active()) {
        uint32_t k = (g_icall_trace_idx - 1) & (ICALL_TRACE_SIZE - 1);
        const float *f = (const float *)GPTR(ARG(2));
        void_log("[trace] SetPixelShaderConstantF(c%u x%u) = (%g %g %g %g) from %08X", ARG(1), ARG(3),
            f[0], f[1], f[2], f[3], g_icall_from[k]);
    }
    CONST_SET(ps_f, rec_ps_f, 224, 16);
}
COM_METHOD(dev, GetPixelShaderConstantF, 4) { CONST_GET(ps_f, 224, 16); }
COM_METHOD(dev, SetPixelShaderConstantI, 4) { CONST_SET(ps_i, rec_ps_i, 16, 16); }
COM_METHOD(dev, GetPixelShaderConstantI, 4) { CONST_GET(ps_i, 16, 16); }
COM_METHOD(dev, SetPixelShaderConstantB, 4) { CONST_SET(ps_b, rec_ps_b, 16, 4); }
COM_METHOD(dev, GetPixelShaderConstantB, 4) { CONST_GET(ps_b, 16, 4); }

COM_METHOD(dev, DrawRectPatch, 4) { return D3DERR_INVALIDCALL; }
COM_METHOD(dev, DrawTriPatch, 4) { return D3DERR_INVALIDCALL; }
COM_METHOD(dev, DeletePatch, 2) { return D3D_OK; }

uint32_t d3d_query_create(d3d_device *dev, uint32_t type);
COM_METHOD(dev, CreateQuery, 3)
{
    uint32_t type = ARG(1);
    if (type != 8 && type != 9 && type != 4) {           /* EVENT, OCCLUSION, VCACHE */
        VLOG("[d3d9] CreateQuery(%u): unsupported", type);
        return D3DERR_NOTAVAILABLE;
    }
    if (!ARG(2)) return D3D_OK;                           /* support check */
    MEM32(ARG(2)) = d3d_query_create(DEV, type);
    return D3D_OK;
}

static const void_fn device_methods[119] = {
    dev_QueryInterface, dev_AddRef, dev_Release, dev_TestCooperativeLevel, dev_GetAvailableTextureMem,
    dev_EvictManagedResources, dev_GetDirect3D, dev_GetDeviceCaps, dev_GetDisplayMode, dev_GetCreationParameters,
    dev_SetCursorProperties, dev_SetCursorPosition, dev_ShowCursor, dev_CreateAdditionalSwapChain, dev_GetSwapChain,
    dev_GetNumberOfSwapChains, dev_Reset, dev_Present, dev_GetBackBuffer, dev_GetRasterStatus, dev_SetDialogBoxMode,
    dev_SetGammaRamp, dev_GetGammaRamp, dev_CreateTexture, dev_CreateVolumeTexture, dev_CreateCubeTexture,
    dev_CreateVertexBuffer, dev_CreateIndexBuffer, dev_CreateRenderTarget, dev_CreateDepthStencilSurface,
    dev_UpdateSurface, dev_UpdateTexture, dev_GetRenderTargetData, dev_GetFrontBufferData, dev_StretchRect,
    dev_ColorFill, dev_CreateOffscreenPlainSurface, dev_SetRenderTarget, dev_GetRenderTarget,
    dev_SetDepthStencilSurface, dev_GetDepthStencilSurface, dev_BeginScene, dev_EndScene, dev_Clear,
    dev_SetTransform, dev_GetTransform, dev_MultiplyTransform, dev_SetViewport, dev_GetViewport, dev_SetMaterial,
    dev_GetMaterial, dev_SetLight, dev_GetLight, dev_LightEnable, dev_GetLightEnable, dev_SetClipPlane,
    dev_GetClipPlane, dev_SetRenderState, dev_GetRenderState, dev_CreateStateBlock, dev_BeginStateBlock,
    dev_EndStateBlock, dev_SetClipStatus, dev_GetClipStatus, dev_GetTexture, dev_SetTexture,
    dev_GetTextureStageState, dev_SetTextureStageState, dev_GetSamplerState, dev_SetSamplerState,
    dev_ValidateDevice, dev_SetPaletteEntries, dev_GetPaletteEntries, dev_SetCurrentTexturePalette,
    dev_GetCurrentTexturePalette, dev_SetScissorRect, dev_GetScissorRect, dev_SetSoftwareVertexProcessing,
    dev_GetSoftwareVertexProcessing, dev_SetNPatchMode, dev_GetNPatchMode, dev_DrawPrimitive,
    dev_DrawIndexedPrimitive, dev_DrawPrimitiveUP, dev_DrawIndexedPrimitiveUP, dev_ProcessVertices,
    dev_CreateVertexDeclaration, dev_SetVertexDeclaration, dev_GetVertexDeclaration, dev_SetFVF, dev_GetFVF,
    dev_CreateVertexShader, dev_SetVertexShader, dev_GetVertexShader, dev_SetVertexShaderConstantF,
    dev_GetVertexShaderConstantF, dev_SetVertexShaderConstantI, dev_GetVertexShaderConstantI,
    dev_SetVertexShaderConstantB, dev_GetVertexShaderConstantB, dev_SetStreamSource, dev_GetStreamSource,
    dev_SetStreamSourceFreq, dev_GetStreamSourceFreq, dev_SetIndices, dev_GetIndices, dev_CreatePixelShader,
    dev_SetPixelShader, dev_GetPixelShader, dev_SetPixelShaderConstantF, dev_GetPixelShaderConstantF,
    dev_SetPixelShaderConstantI, dev_GetPixelShaderConstantI, dev_SetPixelShaderConstantB,
    dev_GetPixelShaderConstantB, dev_DrawRectPatch, dev_DrawTriPatch, dev_DeletePatch, dev_CreateQuery,
};
static void_com_class device_class = { "IDirect3DDevice9", 119, device_methods, 0 };

uint32_t d3d_swapchain_create(d3d_device *dev);

static void device_destroy(void_com_object *o)
{
    /* shortcut: external resources must be released first, add child-to-device lifetime references when needed. */
    d3d_device *d = (d3d_device *)o;
    d3d_gl_device_destroy();
    if (d->recording) void_com_release(&d->recording->com);
    d3d_state_release(&d->st);
    for (int i = 0; i < 4; ++i) bind_surface(&d->rt[i], NULL);
    bind_surface(&d->ds, NULL);
    if (d->backbuffer) void_com_release(&d->backbuffer->com);
    if (d->auto_depth) void_com_release(&d->auto_depth->com);
    if (d->swapchain) void_com_release((void_com_object *)void_com_host(d->swapchain));
    for (int i = 0; i < fvf_decl_count; ++i)
        void_com_release((void_com_object *)void_com_host(fvf_decls[i].guest));
    memset(fvf_decls, 0, sizeof fvf_decls);
    fvf_decl_count = 0;
    void_com_release((void_com_object *)void_com_host(d->d3d9));
    if (g_d3d_device == d) g_d3d_device = NULL;
    free(d->gl);
    free(d);
    void_log("[d3d9] device released");
}

uint32_t d3d_device_create(uint32_t d3d9, uint32_t window, uint32_t behavior, uint32_t pp, uint32_t *out)
{
    *out = 0;
    if (g_d3d_device) { void_log("[d3d9] a second device is not supported"); return D3DERR_NOTAVAILABLE; }
    if (!d3d_gl_init()) return D3DERR_NOTAVAILABLE;
    d3d_device *dev = (d3d_device *)calloc(1, sizeof *dev);
    if (!dev) return D3DERR_OUTOFVIDEOMEMORY;
    dev->d3d9 = d3d9;
    dev->window = window;
    dev->behavior = behavior;
    for (int i = 0; i < 14; ++i) dev->pp[i] = MEM32(pp + 4u * (uint32_t)i);
    if (!dev->pp[2]) dev->pp[2] = 22;
    if (!dev->pp[7]) dev->pp[7] = window;
    void_log("[d3d9] CreateDevice window=%08X behavior=%08X backbuffer=%ux%u format=%u count=%u ms=%u swap=%u "
        "windowed=%u autodepth=%u/%u flags=%08X refresh=%u interval=%08X",
        window, behavior, dev->pp[0], dev->pp[1], dev->pp[2], dev->pp[3], dev->pp[4], dev->pp[6], dev->pp[8],
        dev->pp[9], dev->pp[10], dev->pp[11], dev->pp[12], dev->pp[13]);
    /* Without D3DCREATE_FPU_PRESERVE, Direct3D puts the creating thread's x87
       in single precision, round to nearest; the guest's arithmetic follows
       (fp_pc in recomp_types.h) so its results keep the original's bits. */
    if (!(behavior & 2u)) { g_fpu_cw &= (uint16_t)~0x0F00u; fp_cw_masks(g_fpu_cw); }
    g_d3d_device = dev;
    *out = void_com_wrap(&dev->com, &device_class, 0);
    dev->com.destroy = device_destroy;
    void_com_addref((void_com_object *)void_com_host(d3d9));
    make_backbuffer(dev);
    for (int i = 0; i < 14; ++i) MEM32(pp + 4u * (uint32_t)i) = dev->pp[i];
    default_state(dev, &dev->st);
    set_default_viewport(dev, dev->backbuffer);
    dev->swapchain = d3d_swapchain_create(dev);
    return D3D_OK;
}

/* Run through guest COM entries so the on-device check covers their stack ABI. */
void d3d_device_lifecycle_selftest(void)
{
    uint32_t module = void_module_load("d3d9.dll"), name = void_gstrdup("Direct3DCreate9");
    uint32_t create = void_module_proc(module, name), sdk = 32;
    void_gfree(name);
    uint32_t parent = create ? void_call_guest(create, 1, &sdk, 1) : 0;
    if (!parent) void_fatal("Direct3DCreate9 lifecycle selftest failed");
    uint32_t pp = void_galloc(56), out = void_galloc(4);
    for (uint32_t pass = 0; pass < 2; ++pass) {
        memset(GPTR(pp), 0, 56);
        MEM32(pp) = pass ? 1280 : 640; MEM32(pp + 4) = pass ? 800 : 480;
        MEM32(pp + 8) = 22; MEM32(pp + 12) = 1; MEM32(pp + 24) = 1;
        MEM32(pp + 32) = 1; MEM32(pp + 36) = 1; MEM32(pp + 40) = 75;
        MEM32(pp + 52) = 0x80000000u;
        uint32_t args[7] = {parent, 0, 1, 0, 0x50, pp, out};
        uint32_t method = MEM32(MEM32(parent) + 16 * 4);
        if (void_call_guest(method, 7, args, 1) != D3D_OK || !MEM32(out))
            void_fatal("CreateDevice lifecycle selftest pass %u failed", pass);
        uint32_t device = MEM32(out);
        int input_w, input_h;
        void_input_screen_size(&input_w, &input_h);
        if (input_w != (pass ? 1280 : 640) || input_h != (pass ? 800 : 480))
            void_fatal("CreateDevice input dimensions mismatch");
        if (void_call_guest(method, 7, args, 1) != D3DERR_NOTAVAILABLE || MEM32(out))
            void_fatal("concurrent CreateDevice lifecycle guard failed");
        uint32_t fvf[2] = {device, 0x144};
        if (void_call_guest(MEM32(MEM32(device) + 89 * 4), 2, fvf, 1)) void_fatal("SetFVF lifecycle selftest failed");
        uint32_t clear[7] = {device, 0, 0, 3, 0xFF123456, 0x3F800000, 0};
        if (void_call_guest(MEM32(MEM32(device) + 43 * 4), 7, clear, 1) || glGetError())
            void_fatal("Clear lifecycle selftest failed");
        uint32_t back[5] = {device, 0, 0, 0, out};
        if (void_call_guest(MEM32(MEM32(device) + 18 * 4), 5, back, 1) || !MEM32(out))
            void_fatal("GetBackBuffer lifecycle selftest failed");
        uint32_t surface = MEM32(out);
        void_call_guest(MEM32(MEM32(surface) + 8), 1, &surface, 1);
        if (!pass) {
            MEM32(pp) = 800; MEM32(pp + 4) = 600;
            uint32_t reset[2] = {device, pp};
            if (void_call_guest(MEM32(MEM32(device) + 16 * 4), 2, reset, 1)) void_fatal("Reset lifecycle selftest failed");
            void_input_screen_size(&input_w, &input_h);
            if (input_w != 800 || input_h != 600) void_fatal("Reset input dimensions mismatch");
        }
        if (void_call_guest(MEM32(MEM32(device) + 8), 1, &device, 1) || g_d3d_device)
            void_fatal("device Release lifecycle selftest failed");
    }
    if (void_call_guest(MEM32(MEM32(parent) + 8), 1, &parent, 1)) void_fatal("IDirect3D9 lifecycle reference leak");
    void_gfree(pp); void_gfree(out);
    void_log("[selftest] D3D9 create, FVF, clear, reset, release, recreate, input sizes and parent references PASS");
}

/* Index of the next set flag at or after i (n if none), skipping eight clear
 * flags a step: a block records a handful of the ~1,900 states it could. */
static inline int next_flag(const uint8_t *f, int i, int n)
{
    for (; i < n && (i & 7); ++i) if (f[i]) return i;
    for (; i + 8 <= n; i += 8) {
        uint64_t w;
        memcpy(&w, f + i, 8);
        if (w) return i + (__builtin_ctzll(w) >> 3);
    }
    for (; i < n; ++i) if (f[i]) return i;
    return n;
}
#define FOR_FLAGS(i, flags, n) for (int i = next_flag((flags), 0, (n)); i < (n); i = next_flag((flags), i + 1, (n)))

/* State block application (d3d9_resource.c builds and captures them). */
void d3d_stateblock_apply(d3d_stateblock *sb)
{
    d3d_device *d = sb->dev;
    d3d_state *s = &sb->state;
    FOR_FLAGS(i, sb->rec_rs, 256) d->st.rs[i] = s->rs[i];
    FOR_FLAGS(i, &sb->rec_ss[0][0], 20 * 14) d->st.ss[i / 14][i % 14] = s->ss[i / 14][i % 14];
    FOR_FLAGS(i, &sb->rec_tss[0][0], 8 * 33) d->st.tss[i / 33][i % 33] = s->tss[i / 33][i % 33];
    FOR_FLAGS(i, sb->rec_tex, 20) bind_ref(&d->st.textures[i], s->textures[i]);
    FOR_FLAGS(i, sb->rec_stream, 16) {
        bind_ref(&d->st.streams[i], s->streams[i]);
        d->st.stream_offset[i] = s->stream_offset[i];
        d->st.stream_stride[i] = s->stream_stride[i];
        d->st.stream_freq[i] = s->stream_freq[i];
    }
    int constants = 0;   /* shader constants recorded: programs must upload again */
    FOR_FLAGS(i, sb->rec_vs_f, 256) { memcpy(d->st.vs_f[i], s->vs_f[i], 16); constants = 1; }
    FOR_FLAGS(i, sb->rec_ps_f, 224) { memcpy(d->st.ps_f[i], s->ps_f[i], 16); constants = 1; }
    for (int i = 0; i < 16; ++i) {
        if (sb->rec_vs_i[i]) { memcpy(d->st.vs_i[i], s->vs_i[i], 16); constants = 1; }
        if (sb->rec_ps_i[i]) { memcpy(d->st.ps_i[i], s->ps_i[i], 16); constants = 1; }
        if (sb->rec_vs_b[i]) { d->st.vs_b[i] = s->vs_b[i]; constants = 1; }
        if (sb->rec_ps_b[i]) { d->st.ps_b[i] = s->ps_b[i]; constants = 1; }
    }
    FOR_FLAGS(i, sb->rec_transform, 512) memcpy(d->st.transforms[i], s->transforms[i], 64);
    if (sb->rec_viewport) { memcpy(d->st.viewport, s->viewport, 16); memcpy(d->st.viewport_z, s->viewport_z, 8); }
    if (sb->rec_scissor) memcpy(d->st.scissor, s->scissor, 16);
    if (sb->rec_indices) bind_ref(&d->st.indices, s->indices);
    if (sb->rec_decl) { bind_ref(&d->st.decl, s->decl); }
    if (sb->rec_fvf) d->st.fvf = s->fvf;
    if (sb->rec_vs) bind_ref(&d->st.vs, s->vs);
    if (sb->rec_ps) bind_ref(&d->st.ps, s->ps);
    if (sb->rec_material) memcpy(d->st.material, s->material, 68);
    for (int i = 0; i < 8; ++i) if (sb->rec_light[i]) { memcpy(d->st.lights[i], s->lights[i], 104); d->st.light_enable[i] = s->light_enable[i]; }
    for (int i = 0; i < 6; ++i) if (sb->rec_clip[i]) memcpy(d->st.clip_planes[i], s->clip_planes[i], 16);
    if (constants) {
        d->constants_dirty = 1;
        ++d3d_constant_generation;
    }
}
