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
 * NGScene::CSWTextureData (0x00CC5F50) needs CPU pixels for the spellbook.
 * Decode converted DDSs with the existing converter, then let its original
 * uncompressed loader build the CPU image. Both bodies are NATIVE_OVERRIDES
 * of tools/build_android.py, so direct calls reach them too. */
#include "host.h"
#include "d3d9_internal.h"
#if defined(__ANDROID__) && !defined(HOMM5_LEGACY_UI)
#include <dlfcn.h>
#endif

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

#if defined(__ANDROID__) && !defined(HOMM5_LEGACY_UI)
/* A temporary BGRA DDS keeps the original loader's mip allocation and ownership. */
static uint32_t software_dds(uint32_t source, uint32_t size, uint32_t *bytes, uint32_t *consumed)
{
    if (size < 128 || !void_vm_readable(source, size) || MEM32(source) != FOURCC('D', 'D', 'S', ' ') ||
        MEM32(source + 4) != 124 || MEM32(source + 36) != FOURCC('H', '5', 'T', 'C') ||
        MEM32(source + 40) != 2 || !(MEM32(source + 80) & 4u) ||
        !d3d_native_find(MEM32(source + 84)) || !dxt_code(MEM32(source + 44)) ||
        (MEM32(source + 112) & (0x200000u | 0x200u))) return 0;
    uint32_t width = MEM32(source + 16), height = MEM32(source + 12);
    uint32_t levels = MEM32(source + 28) ? MEM32(source + 28) : 1;
    if (!width || !height || width > 16384 || height > 16384 || levels > 15 ||
        levels != MEM32(source + 48)) return 0;
    uint64_t decoded = 128, packed = 128;
    uint32_t w = width, h = height;
    for (uint32_t l = 0; l < levels; ++l) {
        decoded += (uint64_t)w * h * 4;
        packed += (uint64_t)((w + 3) / 4) * ((h + 3) / 4) * (MEM32(source + 44) == FOURCC('D', 'X', 'T', '1') ? 8u : 16u);
        if (w == 1 && h == 1 && l + 1 < levels) return 0;
        w = w > 1 ? w / 2 : 1; h = h > 1 ? h / 2 : 1;
    }
    if (packed > size || decoded > UINT32_MAX) return 0;
    typedef int (*decode_fn)(const uint8_t *, uint64_t, uint32_t, uint8_t *);
    static decode_fn decode;
    if (!decode) {
        void *library = dlopen("libtexconv.so", RTLD_NOW | RTLD_LOCAL);
        if (library) decode = (decode_fn)dlsym(library, "texconv_decode_converted");
        if (!decode) { void_log("[texture] cannot load converted CPU texture decoder"); return 0; }
    }
    uint32_t data = void_galloc((uint32_t)decoded);
    if (!data) return 0;
    memcpy(GPTR(data), GPTR(source), 128);
    memset((uint8_t *)GPTR(data) + 32, 0, 44);
    MEM32(data + 8) = (MEM32(data + 8) & ~0x80000u) | 8u;
    MEM32(data + 20) = width * 4;
    MEM32(data + 80) = 0x41; MEM32(data + 84) = 0; MEM32(data + 88) = 32;
    MEM32(data + 92) = 0x00FF0000; MEM32(data + 96) = 0x0000FF00;
    MEM32(data + 100) = 0x000000FF; MEM32(data + 104) = 0xFF000000;
    uint32_t at = 128;
    w = width; h = height;
    for (uint32_t l = 0; l < levels; ++l) {
        uint8_t *pixels = (uint8_t *)GPTR(data + at);
        if (decode((const uint8_t *)GPTR(source), size, l, pixels)) { void_gfree(data); return 0; }
        for (uint32_t i = 0; i < w * h; ++i) {
            uint8_t red = pixels[i * 4]; pixels[i * 4] = pixels[i * 4 + 2]; pixels[i * 4 + 2] = red;
        }
        at += w * h * 4;
        w = w > 1 ? w / 2 : 1; h = h > 1 ? h / 2 : 1;
    }
    *bytes = (uint32_t)decoded; *consumed = (uint32_t)packed;
    return data;
}
#endif

/* thiscall(CSWTextureData loader), RET. */
void sub_00CC5F50(void)
{
    pending.native = NULL;
#if defined(__ANDROID__) && !defined(HOMM5_LEGACY_UI)
    uint32_t loader = g_ecx, io = 0, data = 0, bytes = 0, consumed = 0, saved[4];
    if (void_vm_readable(loader, 0x40)) {
        uint32_t stream = MEM32(loader + 0x3C);
        if (stream && void_vm_readable(stream, 0x30)) {
            io = stream + 0x1C;
            memcpy(saved, GPTR(io + 4), sizeof saved);
            if (saved[2] >= saved[0]) data = software_dds(saved[0], saved[2] - saved[0], &bytes, &consumed);
            if (data) {
                MEM32(io + 4) = MEM32(io + 16) = data;
                MEM32(io + 8) = MEM32(io + 12) = data + bytes;
            }
        }
    }
#endif
    sub_00CC5F50_lifted();
#if defined(__ANDROID__) && !defined(HOMM5_LEGACY_UI)
    if (data) {
        memcpy(GPTR(io + 4), saved, sizeof saved);
        MEM32(io + 16) = saved[0] + consumed;
        void_gfree(data);
    }
#endif
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
