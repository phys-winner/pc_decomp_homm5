/* Tribes of the East's DXVK renderers. With the launcher's "DXVK (Vulkan)" or "DXVK (Turnip)"
 * (Renderers.java; GameActivity.nativeRenderer before the engine starts), Direct3DCreate9
 * (d3d9_device.c) hands the game DXVK's IDirect3D9 instead of the GLES one. DXVK runs natively in
 * libdxvk_d3d9.so through libh5dxvk.so (android/dxvk), both from the APK's native library
 * directory (tools/build_dxvk.py). This is the guest side: COM wrappers whose generated stdcall
 * thunks (dxvk_methods.h) forward each call with its stack arguments, the guest memory and window
 * services of android/dxvk/bridge_abi.h, and what the GLES device does around a frame without
 * Direct3D: the creating thread's x87 precision, the touch frame pump and frame count, the frame
 * limit (port_fps_limit), waiting while the activity has no surface. touch_render.c reads the
 * device through a shadow d3d_device (com.guest, window, pp, in_scene and recording only). When
 * DXVK cannot start, the session renders with GLES; ported to no other edition (TECHDEBT-LEGACY.md). */
#include "d3d9_internal.h"
#include "dxvk.h"
#include "input.h"
#include "touch.h"

/* DXVK/Turnip support is commented out (2026-10-29, RendererPolicy.ENABLED): without HOMM5_DXVK the engine
 * keeps the stubs below and never loads libh5dxvk.so; the launcher offers no DXVK mode.
#define HOMM5_DXVK
 */

#ifndef HOMM5_LEGACY_UI
#if defined(VOID_ANDROID_APP) && defined(HOMM5_DXVK)
#include <dlfcn.h>
#include <errno.h>
#include <jni.h>
#include <sys/stat.h>
#include <time.h>
#include "../dxvk/bridge_abi.h"

void *void_android_window_current(uint32_t *serial, int wait);
void void_android_window_ack(uint32_t serial);
void *void_android_window_acquire(uint32_t *serial);

/* Kinds as tools/generate_dxvk_bridge.py numbers them (checked against dxvk_classes on opening). */
enum { KIND_D3D9 = 1, KIND_DEVICE = 2, KIND_TEXTURE = 5, KIND_CUBE = 6, KIND_SURFACE = 9, KIND_QUERY = 16, KIND_SWAPCHAIN = 17 };
enum { SLOT_CREATE_DEVICE = 16, SLOT_RESET = 16, SLOT_PRESENT = 17, SLOT_BEGIN_SCENE = 41, SLOT_END_SCENE = 42,
       SLOT_BEGIN_STATE_BLOCK = 60, SLOT_END_STATE_BLOCK = 61, SLOT_SWAPCHAIN_PRESENT = 3, SLOT_GET_DATA = 7 };
static const char *const mode_names[] = {"OpenGL ES", "DXVK (Vulkan)", "DXVK (Turnip)"};
static int dxvk_mode, dxvk_state;    /* state: 0 not started, 1 DXVK running, -1 GLES for this session */
static char native_dir[512], cache_dir[512];
static const homm5_dxvk_bridge *bridge;
static d3d_device shadow;
static uint64_t frame_deadline_ns, frame_period_ns;

typedef struct dxvk_object { void_com_object com; void *native; unsigned kind; struct dxvk_object *next; } dxvk_object;
#define DXVK_OBJECT_BUCKETS 1024u
static dxvk_object *dxvk_objects[DXVK_OBJECT_BUCKETS];
static unsigned dxvk_bucket(unsigned kind, void *native)
{
    uintptr_t key = (uintptr_t)native >> 4;
    return (unsigned)(key ^ (key >> 11) ^ ((uintptr_t)kind * 0x9E3779B1u)) & (DXVK_OBJECT_BUCKETS - 1u);
}
static uint32_t dxvk_guest_call(uint32_t guest, unsigned kind, unsigned slot, const uint32_t *args);
static void dxvk_return_float(uint32_t bits)
{
    float value;
    memcpy(&value, &bits, 4);
#ifdef RECOMP_X87_WINDOW
    fp_window_push(value);
#else
    fp_push_impl(g_st, &g_fp_top, value);
#endif
}
#include "dxvk_methods.h"
#define DXVK_KINDS (sizeof dxvk_classes / sizeof *dxvk_classes)

static dxvk_object *dxvk_object_of(uint32_t guest)
{
    void_com_object *base = (void_com_object *)void_com_host(guest);
    uintptr_t cls = (uintptr_t)base->cls, first = (uintptr_t)dxvk_classes;
    if (cls < first || cls >= first + sizeof dxvk_classes) return NULL;
    dxvk_object *object = (dxvk_object *)base;
    if (base->cls != &dxvk_classes[object->kind]) void_lift_trap(g_cur_func, "DXVK object kind mismatch");
    return object;
}

/* ----------------------------------------------------------- host services */
static void *host_guest_memory(uint32_t va, uint32_t bytes, int write)
{
    if (!va || !(write ? void_vm_writable(va, bytes) : void_vm_readable(va, bytes)))
        void_lift_trap(g_cur_func, "DXVK invalid guest memory span");
    return GPTR(va);
}

static void *host_unwrap(uint32_t guest)
{
    if (!guest) return NULL;
    dxvk_object *object = dxvk_object_of(guest);
    if (!object) void_lift_trap(g_cur_func, "DXVK object has another COM owner");
    return object->native;
}

static void dxvk_destroy(void_com_object *base)
{
    dxvk_object *object = (dxvk_object *)base, **at = &dxvk_objects[dxvk_bucket(object->kind, object->native)];
    while (*at && *at != object) at = &(*at)->next;
    if (*at) *at = object->next;
    if (object->kind == KIND_DEVICE && g_d3d_device == &shadow && shadow.com.guest == base->guest) {
        g_d3d_device = NULL;
        memset(&shadow, 0, sizeof shadow);
    }
    free(object);
}

/* Each incoming native pointer already owns one reference; one wrapper per native object and kind. */
static uint32_t host_wrap(unsigned kind, void *native)
{
    if (!native) return 0;
    if (kind >= DXVK_KINDS) void_lift_trap(g_cur_func, "DXVK unknown COM interface");
    unsigned bucket = dxvk_bucket(kind, native);
    for (dxvk_object *object = dxvk_objects[bucket]; object; object = object->next)
        if (object->native == native && object->kind == kind) { void_com_addref(&object->com); return object->com.guest; }
    dxvk_object *object = (dxvk_object *)calloc(1, sizeof *object);
    if (!object) void_fatal("DXVK object allocation failed");
    object->native = native;
    object->kind = kind;
    object->com.destroy = dxvk_destroy;
    uint32_t guest = void_com_wrap(&object->com, &dxvk_classes[kind], 0);
    object->next = dxvk_objects[bucket];
    dxvk_objects[bucket] = object;
    return guest;
}

static void host_log(const char *text) { void_log("[dxvk] %s", text); }

static const homm5_dxvk_host host = {
    HOMM5_DXVK_ABI, sizeof(homm5_dxvk_host), DXVK_SLOTS_DIGEST,
    host_guest_memory, void_galloc, void_gfree, host_unwrap, host_wrap, host_log,
    void_android_window_acquire, void_android_window_ack, void_android_display_size, void_input_set_screen_size,
};

/* --------------------------------------------------------- frame and window */
/* Without a surface (Home: GameActivity hands its persistent surface back on onStart) the game
 * waits here, letting the other guest threads run, as the GLES present does (follow_window). */
static void dxvk_wait_window(const char *what)
{
    uint32_t serial;
    if (void_android_window_current(&serial, 0)) return;
    void_android_window_ack(serial);
    void_log("[dxvk] %s: no surface, the game waits for the activity", what);
    void_blocking_begin();
    void_android_window_current(&serial, 1);
    void_blocking_end();
    frame_deadline_ns = 0;
}

/* port_fps_limit as d3d_gl_frame_pace applies it: after the present, without a catch-up burst. */
static void dxvk_frame_pace(void)
{
    float fps = void_port_fps_limit();
    if (fps <= 0.0f) { frame_deadline_ns = 0; return; }
    uint64_t period = (uint64_t)(1000000000.0 / (double)fps), now = void_perf_now_ns();
    if (period != frame_period_ns || !frame_deadline_ns || now >= frame_deadline_ns + period) {
        frame_deadline_ns = now;
        frame_period_ns = period;
    }
    if (now < frame_deadline_ns) {
        struct timespec deadline = { (time_t)(frame_deadline_ns / 1000000000ull), (long)(frame_deadline_ns % 1000000000ull) };
        void_blocking_begin();
        int error;
        do { error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL); } while (error == EINTR);
        void_blocking_end();
        if (error) { frame_deadline_ns = 0; return; }
        now = void_perf_now_ns();
    }
    frame_deadline_ns = now >= frame_deadline_ns + period ? now + period : frame_deadline_ns + period;
}

/* A pending occlusion query polled with D3DGETDATA_FLUSH: after 8 polls let the other guest
 * threads (and DXVK's workers) run before the next one; results pass through unchanged. */
static void dxvk_query_wait(uint32_t result, uint32_t flags)
{
    static _Thread_local unsigned pending;
    if (result != 1u || !(flags & 1u)) { pending = 0; return; }
    if (pending < 8) { ++pending; return; }
    if (recomp_yield_hook) recomp_yield_hook();
}

static uint32_t dxvk_create_device(dxvk_object *object, const uint32_t *args)
{
    dxvk_wait_window("CreateDevice");
    uint32_t hr = bridge->call(KIND_D3D9, object->native, SLOT_CREATE_DEVICE, args);
    if (hr || !args[5] || !MEM32(args[5])) return hr;
    /* Without D3DCREATE_FPU_PRESERVE, Direct3D puts the creating thread's x87 in single precision,
     * round to nearest (as d3d_device_create): the guest's arithmetic, and LAN checksums, follow. */
    if (!(args[3] & 2u)) { g_fpu_cw &= (uint16_t)~0x0F00u; fp_cw_masks(g_fpu_cw); }
    memset(&shadow, 0, sizeof shadow);
    shadow.com.guest = MEM32(args[5]);
    shadow.window = args[2];
    for (uint32_t i = 0; i < 14; ++i) shadow.pp[i] = MEM32(args[4] + 4u * i);
    if (!shadow.pp[7]) shadow.pp[7] = args[2];
    g_d3d_device = &shadow;
    frame_deadline_ns = 0;
    return hr;
}

static uint32_t dxvk_present(dxvk_object *object, unsigned kind, unsigned slot, const uint32_t *args)
{
    dxvk_wait_window("present");
    uint32_t hr = bridge->call(kind, object->native, slot, args);
    ++shadow.frame;
    void_touch_frame_presented();
    dxvk_frame_pace();
    if (recomp_yield_hook) recomp_yield_hook();
    return hr;
}

static uint32_t dxvk_guest_call(uint32_t guest, unsigned kind, unsigned slot, const uint32_t *args)
{
    dxvk_object *object = (dxvk_object *)void_com_host(guest);
    if (object->kind != kind || object->com.cls != &dxvk_classes[kind]) void_lift_trap(g_cur_func, "DXVK vtable/interface mismatch");
    if (slot == 1) { bridge->addref(object->native); return void_com_addref(&object->com); }
    if (slot == 2) { bridge->release(object->native); return void_com_release(&object->com); }
    if (kind == KIND_D3D9 && slot == SLOT_CREATE_DEVICE) return dxvk_create_device(object, args);
    if (kind == KIND_SWAPCHAIN && slot == SLOT_SWAPCHAIN_PRESENT) return dxvk_present(object, kind, slot, args);
    int main_device = kind == KIND_DEVICE && g_d3d_device == &shadow && shadow.com.guest == guest;
    if (kind == KIND_DEVICE) switch (slot) {
    case SLOT_PRESENT:
        return dxvk_present(object, kind, slot, args);
    case SLOT_BEGIN_SCENE:
        /* H5's normal frame has presented and released its old batches here (as dev_BeginScene). */
        if (main_device && g_cur_func == 0x00A3FB70u && !shadow.in_scene && !shadow.recording)
            void_touch_render_frame_pump();
        break;
    default:
        break;
    }
    uint32_t result = bridge->call(kind, object->native, slot, args);
    if (main_device && !result) switch (slot) {
    case SLOT_RESET:
        for (uint32_t i = 0; i < 14; ++i) shadow.pp[i] = MEM32(args[0] + 4u * i);
        frame_deadline_ns = 0;
        break;
    case SLOT_BEGIN_SCENE: shadow.in_scene = 1; break;
    case SLOT_END_SCENE: shadow.in_scene = 0; break;
    case SLOT_BEGIN_STATE_BLOCK: shadow.recording = (d3d_stateblock *)(void *)&shadow; break;
    case SLOT_END_STATE_BLOCK: shadow.recording = NULL; break;
    default: break;
    }
    if (kind == KIND_QUERY && slot == SLOT_GET_DATA) dxvk_query_wait(result, args[2]);
    return result;
}

/* -------------------------------------------------------------- starting */
static int dxvk_open(void)
{
    static const char *const kinds[] = {[KIND_D3D9] = "DXVK::IDirect3D9", [KIND_DEVICE] = "DXVK::IDirect3DDevice9",
        [KIND_TEXTURE] = "DXVK::IDirect3DTexture9", [KIND_CUBE] = "DXVK::IDirect3DCubeTexture9",
        [KIND_SURFACE] = "DXVK::IDirect3DSurface9", [KIND_QUERY] = "DXVK::IDirect3DQuery9", [KIND_SWAPCHAIN] = "DXVK::IDirect3DSwapChain9"};
    for (unsigned kind = 0; kind < sizeof kinds / sizeof *kinds; ++kind)
        if (kinds[kind] && (kind >= DXVK_KINDS || strcmp(dxvk_classes[kind].name, kinds[kind])))
            void_fatal("dxvk_methods.h does not number %s as d3d9_dxvk.c expects", kinds[kind]);
    char path[600];
    snprintf(path, sizeof path, "%s/libh5dxvk.so", native_dir);
    void *library = dlopen(path, RTLD_NOW | RTLD_LOCAL);
    if (!library) { void_log("[dxvk] %s", dlerror()); return 0; }
    homm5_dxvk_open_fn open = (homm5_dxvk_open_fn)dlsym(library, HOMM5_DXVK_OPEN);
    const homm5_dxvk_bridge *opened = open ? open(&host) : NULL;
    if (!opened || opened->abi != HOMM5_DXVK_ABI || opened->size != sizeof *opened || opened->slots_digest != DXVK_SLOTS_DIGEST) {
        void_log("[dxvk] %s does not match this engine (slots %08X)", path, DXVK_SLOTS_DIGEST);
        return 0;
    }
    bridge = opened;
    return 1;
}

/* DXVK's log goes beside homm5.log, its pipeline state cache and configuration into the app
 * cache. The configuration starts with the port's defaults and ends with the player's
 * /sdcard/HeroesV/dxvk.conf, if any (later lines win): the 1 GiB of texture memory the GLES
 * renderer reports (a 32-bit game reads more as negative), vsync as eglSwapInterval(1), and a
 * Reset that keeps default-pool resources, which the GLES renderer never checked either. */
static void dxvk_environment(void)
{
    char folder[600], conf[640], user[600];
    snprintf(folder, sizeof folder, "%s/dxvk", cache_dir);
    mkdir(folder, 0700);
    snprintf(conf, sizeof conf, "%s/dxvk.conf", folder);
    snprintf(user, sizeof user, "%s", void_data_dir());
    char *slash = strrchr(user, '/');
    if (slash) snprintf(slash, sizeof user - (size_t)(slash - user), "/dxvk.conf");
    FILE *out = fopen(conf, "w");
    if (out) {
        fputs("# Heroes V port defaults (android/host/d3d9_dxvk.c)\n"
              "d3d9.maxAvailableMemory = 1024\nd3d9.presentInterval = 1\nd3d9.countLosableResources = False\n", out);
        FILE *in = slash ? fopen(user, "r") : NULL;
        if (in) {
            void_log("[dxvk] configuration %s applies after the port's defaults", user);
            fprintf(out, "# %s\n", user);
            char line[512];
            while (fgets(line, sizeof line, in)) fputs(line, out);
            fclose(in);
        }
        fclose(out);
        setenv("DXVK_CONFIG_FILE", conf, 1);
    }
    setenv("DXVK_STATE_CACHE_PATH", folder, 1);
    setenv("DXVK_LOG_PATH", void_data_dir(), 1);
    setenv("DXVK_LOG_LEVEL", void_verbose ? "info" : "warn", 1);
    setenv("DXVK_WSI_DRIVER", "Android", 1);
    setenv("DXVK_FORCE_WINDOWED", "1", 1);
}

uint32_t void_dxvk_create9(uint32_t sdk)
{
    if (dxvk_mode == HOMM5_RENDERER_GLES || dxvk_state < 0) return 0;
    if (!bridge && !dxvk_open()) {
        dxvk_state = -1;
        void_log("[dxvk] %s: libh5dxvk.so unavailable, OpenGL ES renders this session", mode_names[dxvk_mode]);
        return 0;
    }
    if (!dxvk_state) dxvk_environment();
    char library[600];
    snprintf(library, sizeof library, "%s/libdxvk_d3d9.so", native_dir);
    uint32_t guest = bridge->create9(sdk, library, dxvk_mode == HOMM5_RENDERER_TURNIP ? native_dir : NULL);
    if (!guest) {
        dxvk_state = -1;
        void_log("[dxvk] %s could not start: OpenGL ES renders this session", mode_names[dxvk_mode]);
        return 0;
    }
    dxvk_state = 1;
    void_log("[d3d9] renderer=%s Direct3DCreate9(%u) = %08X", mode_names[dxvk_mode], sdk, guest);
    return guest;
}

/* --------------------------------------------------------- D3DX services */
void *void_dxvk_native(uint32_t guest)
{
    if (!guest || dxvk_state <= 0) return NULL;
    dxvk_object *object = dxvk_object_of(guest);
    return object ? object->native : NULL;
}

int void_dxvk_cube(uint32_t guest)
{
    dxvk_object *object = guest && dxvk_state > 0 ? dxvk_object_of(guest) : NULL;
    return object && object->kind == KIND_CUBE;
}

void void_dxvk_addref(uint32_t guest)
{
    dxvk_object *object = guest && dxvk_state > 0 ? dxvk_object_of(guest) : NULL;
    if (!object) return;
    bridge->addref(object->native);
    void_com_addref(&object->com);
}

uint32_t void_dxvk_texture_create(uint32_t device, int cube, uint32_t width, uint32_t height, uint32_t levels,
                                  uint32_t usage, uint32_t format, uint32_t pool, void **texture)
{
    void *native = void_dxvk_native(device);
    *texture = NULL;
    return native ? (uint32_t)bridge->create_texture(native, cube, width, height, levels, usage, format, pool, texture)
                  : D3DERR_INVALIDCALL;
}

uint32_t void_dxvk_texture_wrap(void *texture, int cube) { return host_wrap(cube ? KIND_CUBE : KIND_TEXTURE, texture); }
uint32_t void_dxvk_texture_levels(void *texture) { return bridge->texture_levels(texture); }
void void_dxvk_texture_generate_mips(void *texture) { bridge->generate_mips(texture); }
void *void_dxvk_texture_surface(void *texture, int cube, uint32_t face, uint32_t level) { return bridge->texture_surface(texture, cube, face, level); }
void void_dxvk_release(void *native) { if (native) bridge->release(native); }
uint32_t void_dxvk_surface_desc(void *surface, uint32_t desc[5]) { return (uint32_t)bridge->surface_desc(surface, desc); }
uint32_t void_dxvk_surface_copy(void *source, const int32_t *source_rect, void *target, const int32_t *target_rect, uint32_t filter)
{
    return (uint32_t)bridge->surface_copy(source, source_rect, target, target_rect, filter);
}

uint32_t void_dxvk_surface_write(void *surface, const int32_t *rect, const uint8_t *data, uint32_t pitch,
                                 uint32_t rows, uint32_t row_bytes)
{
    void *bits = NULL, *target = surface, *staging = NULL;
    int32_t stride = 0, hr = bridge->surface_lock(surface, rect, 0, &bits, &stride);
    if (hr || !bits) {
        staging = bridge->surface_staging(surface, 0);
        if (!staging) return hr ? (uint32_t)hr : D3DERR_INVALIDCALL;
        hr = bridge->surface_lock(staging, rect, 0, &bits, &stride);
        if (hr || !bits) { bridge->release(staging); return hr ? (uint32_t)hr : D3DERR_INVALIDCALL; }
        target = staging;
    }
    if (stride < 0 || (uint32_t)stride < row_bytes) hr = (int32_t)D3DERR_INVALIDCALL;
    else for (uint32_t y = 0; y < rows; ++y) memcpy((uint8_t *)bits + (size_t)y * (uint32_t)stride, data + (size_t)y * pitch, row_bytes);
    bridge->surface_unlock(target);
    if (staging) {
        if (!hr) hr = bridge->surface_upload(staging, surface, rect);
        bridge->release(staging);
    }
    return (uint32_t)hr;
}

typedef struct { void *surface, *staging; } dxvk_mapping;

const uint8_t *void_dxvk_surface_map(void *surface, int32_t *pitch, void **held)
{
    void *bits = NULL, *staging = NULL, *source = surface;
    *held = NULL;
    if (bridge->surface_lock(surface, NULL, 0x10u /* READONLY */, &bits, pitch) || !bits) {
        staging = bridge->surface_staging(surface, 1);
        if (!staging) return NULL;
        if (bridge->surface_lock(staging, NULL, 0x10u, &bits, pitch) || !bits) { bridge->release(staging); return NULL; }
        source = staging;
    }
    dxvk_mapping *mapping = (dxvk_mapping *)malloc(sizeof *mapping);
    if (!mapping) void_fatal("DXVK mapping allocation failed");
    mapping->surface = source;
    mapping->staging = staging;
    *held = mapping;
    return (const uint8_t *)bits;
}

void void_dxvk_surface_unmap(void *held)
{
    dxvk_mapping *mapping = (dxvk_mapping *)held;
    if (!mapping) return;
    bridge->surface_unlock(mapping->surface);
    if (mapping->staging) bridge->release(mapping->staging);
    free(mapping);
}

void void_dxvk_constants(uint32_t device, int pixel, int type, uint32_t start, const void *data, uint32_t count)
{
    void *native = void_dxvk_native(device);
    if (native && count) bridge->constants(native, pixel, type, start, data, count);
}

/* ------------------------------------------------------------------- JNI */
/* GameActivity, before nativeStart: the launcher's mode (HOMM5_RENDERER_*), where the APK's
 * libraries were extracted, the app cache. */
JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeRenderer(JNIEnv *env, jclass type, jint mode,
    jstring library_dir, jstring cache)
{
    (void)type;
    if (mode < HOMM5_RENDERER_GLES || mode > HOMM5_RENDERER_TURNIP || !library_dir || !cache || dxvk_state) return;
    const char *l = (*env)->GetStringUTFChars(env, library_dir, NULL), *c = (*env)->GetStringUTFChars(env, cache, NULL);
    if (l && c) {
        snprintf(native_dir, sizeof native_dir, "%s", l);
        snprintf(cache_dir, sizeof cache_dir, "%s", c);
        dxvk_mode = mode;
    }
    if (l) (*env)->ReleaseStringUTFChars(env, library_dir, l);
    if (c) (*env)->ReleaseStringUTFChars(env, cache, c);
}

/* The mode this session renders with once Direct3DCreate9 ran (-1 before, and with GLES chosen). */
JNIEXPORT jint JNICALL Java_org_homm5_port_GameActivity_nativeRendererActive(JNIEnv *env, jclass type)
{
    (void)env; (void)type;
    return dxvk_state > 0 ? dxvk_mode : dxvk_state < 0 ? HOMM5_RENDERER_GLES : -1;
}

#else
/* The command-line build has no activity, and without HOMM5_DXVK there is no DXVK. */
uint32_t void_dxvk_create9(uint32_t sdk) { (void)sdk; return 0; }
void *void_dxvk_native(uint32_t guest) { (void)guest; return NULL; }
int void_dxvk_cube(uint32_t guest) { (void)guest; return 0; }
void void_dxvk_addref(uint32_t guest) { (void)guest; }
uint32_t void_dxvk_texture_create(uint32_t device, int cube, uint32_t width, uint32_t height, uint32_t levels,
                                  uint32_t usage, uint32_t format, uint32_t pool, void **texture)
{
    (void)device; (void)cube; (void)width; (void)height; (void)levels; (void)usage; (void)format; (void)pool;
    *texture = NULL;
    return D3DERR_INVALIDCALL;
}
uint32_t void_dxvk_texture_wrap(void *texture, int cube) { (void)texture; (void)cube; return 0; }
uint32_t void_dxvk_texture_levels(void *texture) { (void)texture; return 0; }
void void_dxvk_texture_generate_mips(void *texture) { (void)texture; }
void *void_dxvk_texture_surface(void *texture, int cube, uint32_t face, uint32_t level)
{
    (void)texture; (void)cube; (void)face; (void)level;
    return NULL;
}
void void_dxvk_release(void *native) { (void)native; }
uint32_t void_dxvk_surface_desc(void *surface, uint32_t desc[5]) { (void)surface; (void)desc; return D3DERR_INVALIDCALL; }
uint32_t void_dxvk_surface_write(void *surface, const int32_t *rect, const uint8_t *data, uint32_t pitch,
                                 uint32_t rows, uint32_t row_bytes)
{
    (void)surface; (void)rect; (void)data; (void)pitch; (void)rows; (void)row_bytes;
    return D3DERR_INVALIDCALL;
}
const uint8_t *void_dxvk_surface_map(void *surface, int32_t *pitch, void **held)
{
    (void)surface; *pitch = 0; *held = NULL;
    return NULL;
}
void void_dxvk_surface_unmap(void *held) { (void)held; }
uint32_t void_dxvk_surface_copy(void *source, const int32_t *source_rect, void *target, const int32_t *target_rect, uint32_t filter)
{
    (void)source; (void)source_rect; (void)target; (void)target_rect; (void)filter;
    return D3DERR_INVALIDCALL;
}
void void_dxvk_constants(uint32_t device, int pixel, int type, uint32_t start, const void *data, uint32_t count)
{
    (void)device; (void)pixel; (void)type; (void)start; (void)data; (void)count;
}
#endif
#endif
