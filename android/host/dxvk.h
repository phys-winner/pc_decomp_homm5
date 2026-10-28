/* Tribes of the East's DXVK renderer (android/host/d3d9_dxvk.c) as the rest of the host sees
 * it. Only ToE code (#ifndef HOMM5_LEGACY_UI) uses these; without a DXVK mode, and in the
 * command-line build, void_dxvk_create9 returns 0 and nothing else is reached. */
#ifndef VOID_DXVK_H
#define VOID_DXVK_H
#include <stdint.h>

/* Direct3DCreate9 through DXVK when the launcher chose a DXVK mode; 0: use the GLES renderer. */
uint32_t void_dxvk_create9(uint32_t sdk);
/* The native object behind a DXVK guest object; NULL for any other object (or 0). */
void *void_dxvk_native(uint32_t guest);
/* Whether a DXVK guest object is a cube texture. */
int void_dxvk_cube(uint32_t guest);
/* AddRef of a DXVK guest object, as its guest AddRef would (native and wrapper). */
void void_dxvk_addref(uint32_t guest);

/* D3DX services for d3dx9.c on DXVK objects. HRESULTs as uint32_t; native references as D3D's. */
uint32_t void_dxvk_texture_create(uint32_t device, int cube, uint32_t width, uint32_t height, uint32_t levels,
                                  uint32_t usage, uint32_t format, uint32_t pool, void **texture);
/* The guest object of a texture, which takes over the caller's native reference. */
uint32_t void_dxvk_texture_wrap(void *texture, int cube);
uint32_t void_dxvk_texture_levels(void *texture);
void void_dxvk_texture_generate_mips(void *texture);
/* The native surface of a level (with a reference); NULL if it has none. */
void *void_dxvk_texture_surface(void *texture, int cube, uint32_t face, uint32_t level);
void void_dxvk_release(void *native);
/* width, height, format, usage, pool. */
uint32_t void_dxvk_surface_desc(void *surface, uint32_t desc[5]);
/* rows of row_bytes into a surface (rect NULL: all of it), locked directly or, for an unlockable
 * default-pool surface, through a system-memory copy and UpdateSurface. */
uint32_t void_dxvk_surface_write(void *surface, const int32_t *rect, const uint8_t *data, uint32_t pitch,
                                 uint32_t rows, uint32_t row_bytes);
/* A surface's pixels for reading (render targets through GetRenderTargetData); *held ends it. */
const uint8_t *void_dxvk_surface_map(void *surface, int32_t *pitch, void **held);
void void_dxvk_surface_unmap(void *held);
uint32_t void_dxvk_surface_copy(void *source, const int32_t *source_rect, void *target, const int32_t *target_rect,
                                uint32_t filter);
/* Set{Vertex,Pixel}ShaderConstant{F,I,B} (type 0/1/2) on a DXVK device. */
void void_dxvk_constants(uint32_t device, int pixel, int type, uint32_t start, const void *data, uint32_t count);

#endif
