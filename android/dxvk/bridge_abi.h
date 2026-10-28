/* The C boundary between the ToE engine (android/host/d3d9_dxvk.c, inside libhomm5.so) and
 * libh5dxvk.so (android/dxvk/bridge.cpp), which the engine opens with dlopen only in a
 * DXVK renderer mode. The engine's symbols are hidden, so it hands the bridge a table of host
 * services; the bridge answers with its operations. Native pointers never enter guest memory:
 * guest objects are host wrappers (DXVK_SLOTS_DIGEST names their kind/slot table). */
#ifndef HOMM5_DXVK_BRIDGE_ABI_H
#define HOMM5_DXVK_BRIDGE_ABI_H
#include <stdint.h>

#define HOMM5_DXVK_ABI 1u
#define HOMM5_DXVK_OPEN "homm5_dxvk_bridge_open"

/* The renderer modes, as the launcher stores them (Renderers.java) and JNI passes them. */
enum { HOMM5_RENDERER_GLES = 0, HOMM5_RENDERER_DXVK = 1, HOMM5_RENDERER_TURNIP = 2 };

typedef struct homm5_dxvk_host {
    uint32_t abi, size, slots_digest;
    /* A checked guest span as a host pointer; traps on an invalid one (never returns NULL for va != 0). */
    void *(*guest_memory)(uint32_t va, uint32_t bytes, int write);
    uint32_t (*guest_alloc)(uint32_t bytes);
    void (*guest_free)(uint32_t va);
    /* The native object behind a DXVK guest wrapper (traps on any other object); NULL for 0. */
    void *(*unwrap_guest)(uint32_t guest);
    /* The guest wrapper of a native object, which hands over one native reference. */
    uint32_t (*wrap_native)(unsigned kind, void *native);
    void (*log)(const char *text);
    /* The activity's current ANativeWindow with a reference of its own (NULL without one) and the
     * window serial it belongs to; ack tells android_main.c the serial has been taken up. */
    void *(*window_acquire)(uint32_t *serial);
    void (*window_ack)(uint32_t serial);
    /* The physical display (0 without one) and the size touch input maps onto (the backbuffer). */
    int (*display_size)(int *width, int *height);
    void (*input_screen_size)(int width, int height);
} homm5_dxvk_host;

typedef struct homm5_dxvk_bridge {
    uint32_t abi, size, slots_digest;
    /* Direct3DCreate9 on the system Vulkan driver, or with turnip_dir on the app-local Turnip driver
     * loaded through adrenotools from that directory. 0 (logged) when DXVK cannot start. */
    uint32_t (*create9)(uint32_t sdk, const char *dxvk_library, const char *turnip_dir);
    /* A guest COM call: the arguments as the guest pushed them, the result as EAX. */
    uint32_t (*call)(unsigned kind, void *native, unsigned slot, const uint32_t *args);
    uint32_t (*addref)(void *native);
    uint32_t (*release)(void *native);
    /* D3DX services on native objects (d3dx9.c under DXVK): HRESULTs, references counted as D3D's. */
    int32_t (*create_texture)(void *device, int cube, uint32_t width, uint32_t height, uint32_t levels,
                              uint32_t usage, uint32_t format, uint32_t pool, void **texture);
    uint32_t (*texture_levels)(void *texture);
    void (*generate_mips)(void *texture);
    /* The surface of a texture level / cube face, with a reference. */
    void *(*texture_surface)(void *texture, int cube, uint32_t face, uint32_t level);
    /* width, height, format, usage, pool of a surface. */
    int32_t (*surface_desc)(void *surface, uint32_t desc[5]);
    int32_t (*surface_lock)(void *surface, const int32_t *rect, uint32_t flags, void **bits, int32_t *pitch);
    int32_t (*surface_unlock)(void *surface);
    /* StretchRect on the surfaces' device; rects may be NULL. */
    int32_t (*surface_copy)(void *source, const int32_t *source_rect, void *target, const int32_t *target_rect,
                            uint32_t filter);
    /* A lockable system-memory surface shaped like `like`, holding its pixels when `read`
     * (GetRenderTargetData for render targets), and the upload of its rect (NULL: all) into the
     * same place of a target (UpdateSurface). */
    void *(*surface_staging)(void *like, int read);
    int32_t (*surface_upload)(void *staging, void *target, const int32_t *rect);
    /* Set*ShaderConstantF/I/B (type 0/1/2) on the device; count in registers (B: booleans). */
    int32_t (*constants)(void *device, int pixel, int type, uint32_t start, const void *data, uint32_t count);
} homm5_dxvk_bridge;

typedef const homm5_dxvk_bridge *(*homm5_dxvk_open_fn)(const homm5_dxvk_host *host);

#endif
