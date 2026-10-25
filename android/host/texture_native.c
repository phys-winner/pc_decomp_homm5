/* Converted textures (android/texconv) through the engine's own DDS loader.
 *
 * NGScene::CFileTexture (0x00A9DF80) reads a DDS and asks 0x00A9CDC0 for the
 * engine format code of its header: DXT1..5 are 1..5, anything else 6
 * (A8R8G8B8). It then creates (or takes from its LRU set) a D3D texture of
 * that format and copies the levels into it block row by block row. A
 * converted DDS keeps its original DXT layout (each level in the original
 * format's block slots) with GPU-native blocks at the start of every slot, a
 * port FourCC and a marker. For it the code is the original DXT's, and the
 * D3D texture the loader locks next stores the native blocks instead
 * (d3d9_resource.c: texture_set_storage via d3d_native_take).
 *
 * NGScene::CSWTextureData (0x00CC5F50) decodes DXT on the CPU; converted data
 * cannot serve it, which is logged. Both bodies are NATIVE_OVERRIDES of
 * tools/build_android.py, so direct calls reach them too. */
#include "host.h"
#include "d3d9_internal.h"

void sub_00A9CDC0_lifted(void);
void sub_00CC5F50_lifted(void);

static struct {
    const d3d_native_format *native;
    uint32_t width, height, fourcc;
} pending;

static int dxt_code(uint32_t fourcc)
{
    switch (fourcc) {
    case FOURCC('D', 'X', 'T', '1'): return 1;
    case FOURCC('D', 'X', 'T', '2'): return 2;
    case FOURCC('D', 'X', 'T', '3'): return 3;
    case FOURCC('D', 'X', 'T', '4'): return 4;
    case FOURCC('D', 'X', 'T', '5'): return 5;
    default: return 0;
    }
}

/* thiscall(DDSURFACEDESC2 *desc), RET: the engine format code. The desc is the
 * DDS header after its magic (texconv.h offsets minus 4). */
void sub_00A9CDC0(void)
{
    uint32_t desc = g_ecx;
    if (void_vm_readable(desc, 124) && (MEM32(desc + 76) & 4u) && MEM32(desc + 32) == FOURCC('H', '5', 'T', 'C')) {
        const d3d_native_format *native = d3d_native_find(MEM32(desc + 80));
        uint32_t original = MEM32(desc + 40);
        int code = dxt_code(original);
        if (native && code) {
            static int unsupported_logged;
            if (!d3d_native_supported(native) && !unsupported_logged++)
                void_log("[texture] converted %.4s textures are not supported by this GPU", (const char *)&native->fourcc);
            pending.native = native;
            pending.width = MEM32(desc + 12);
            pending.height = MEM32(desc + 8);
            pending.fourcc = original;
            g_eax = (uint32_t)code;
            g_esp += 4;
            return;
        }
    }
    sub_00A9CDC0_lifted();
}

/* thiscall(CSWTextureData loader), RET. */
void sub_00CC5F50(void)
{
    pending.native = NULL;
    sub_00CC5F50_lifted();
    if (pending.native) {
        static int logged;
        if (logged++ < 20)
            void_log("[texture] software texture %ux%u read from converted data: its CPU image is wrong",
                     pending.width, pending.height);
    }
    pending.native = NULL;
}

/* The pending converted image belongs to a texture of its original format and
 * of its size, or of a power-of-two smaller one (the loader's skipped levels). */
int d3d_native_take(uint32_t width, uint32_t height, uint32_t format, const d3d_native_format **out)
{
    if (!pending.native || format != pending.fourcc) return 0;
    for (uint32_t k = 0; k < 16; ++k) {
        uint32_t w = pending.width >> k ? pending.width >> k : 1, h = pending.height >> k ? pending.height >> k : 1;
        if (w == width && h == height) {
            *out = d3d_native_supported(pending.native) ? pending.native : NULL;
            pending.native = NULL;
            return *out != NULL;
        }
        if (w == 1 && h == 1) break;
    }
    return 0;
}
