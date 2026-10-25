/* Logical texel access for D3DXLoadSurface*, surface readback and format
 * conversion between surfaces: texels as the RGBA floats a shader sampling
 * them would see. */
#include "d3d9_internal.h"

float d3d_half_to_float(uint16_t h)
{
    uint32_t sign = (uint32_t)(h >> 15) << 31, exp = (h >> 10) & 0x1F, man = h & 0x3FF, bits;
    if (exp == 0) {
        if (!man) {
            bits = sign;
        } else {                                       /* subnormal: renormalize */
            exp = 127 - 15 + 1;
            while (!(man & 0x400)) { man <<= 1; --exp; }
            bits = sign | (exp << 23) | ((man & 0x3FF) << 13);
        }
    } else if (exp == 31) {
        bits = sign | 0x7F800000u | (man << 13);
    } else {
        bits = sign | ((exp + 127 - 15) << 23) | (man << 13);
    }
    float f;
    memcpy(&f, &bits, 4);
    return f;
}

uint16_t d3d_float_to_half(float f)
{
    uint32_t x;
    memcpy(&x, &f, 4);
    uint32_t sign = (x >> 16) & 0x8000u;
    int32_t exp = (int32_t)((x >> 23) & 0xFF) - 127 + 15;
    uint32_t man = x & 0x7FFFFFu;
    if (((x >> 23) & 0xFF) == 0xFF) return (uint16_t)(sign | 0x7C00u | (man ? 0x200u : 0));
    if (exp >= 31) return (uint16_t)(sign | 0x7C00u);
    if (exp <= 0) {
        if (exp < -10) return (uint16_t)sign;
        man |= 0x800000u;
        uint32_t shift = (uint32_t)(14 - exp);
        uint32_t half = man >> shift;
        uint32_t rest = man & ((1u << shift) - 1), mid = 1u << (shift - 1);
        if (rest > mid || (rest == mid && (half & 1))) ++half;
        return (uint16_t)(sign | half);
    }
    uint32_t half = sign | ((uint32_t)exp << 10) | (man >> 13);
    uint32_t rest = man & 0x1FFFu;
    if (rest > 0x1000u || (rest == 0x1000u && (half & 1))) ++half;   /* round to nearest even */
    return (uint16_t)half;
}

/* `count` texels in GL layout (format, type) to RGBA floats in GL channel
 * order; absent channels read as GL reads them (0, 0, 0, 1). */
void d3d_gl_layout_to_rgba(GLenum format, GLenum type, const void *data, uint32_t count, float *out)
{
    int n = format == GL_RED ? 1 : format == GL_RG ? 2 : format == GL_RGB ? 3 : 4;
    const uint8_t *b = (const uint8_t *)data;
    for (uint32_t i = 0; i < count; ++i) {
        float c[4] = { 0, 0, 0, 1 };
        switch (type) {
        case GL_UNSIGNED_BYTE:
            for (int k = 0; k < n; ++k) c[k] = b[(size_t)i * n + k] / 255.0f;
            break;
        case GL_BYTE:
            for (int k = 0; k < n; ++k) {
                float v = (float)(int8_t)b[(size_t)i * n + k] / 127.0f;
                c[k] = v < -1.0f ? -1.0f : v;
            }
            break;
        case GL_FLOAT:
            for (int k = 0; k < n; ++k) c[k] = ((const float *)data)[(size_t)i * n + k];
            break;
        case GL_HALF_FLOAT:
            for (int k = 0; k < n; ++k) c[k] = d3d_half_to_float(((const uint16_t *)data)[(size_t)i * n + k]);
            break;
        case GL_UNSIGNED_SHORT_5_6_5: {
            uint16_t v = ((const uint16_t *)data)[i];
            c[0] = (v >> 11) / 31.0f; c[1] = ((v >> 5) & 63) / 63.0f; c[2] = (v & 31) / 31.0f;
            break;
        }
        case GL_UNSIGNED_SHORT_5_5_5_1: {
            uint16_t v = ((const uint16_t *)data)[i];
            c[0] = (v >> 11) / 31.0f; c[1] = ((v >> 6) & 31) / 31.0f; c[2] = ((v >> 1) & 31) / 31.0f; c[3] = (float)(v & 1);
            break;
        }
        case GL_UNSIGNED_SHORT_4_4_4_4: {
            uint16_t v = ((const uint16_t *)data)[i];
            c[0] = (v >> 12) / 15.0f; c[1] = ((v >> 8) & 15) / 15.0f; c[2] = ((v >> 4) & 15) / 15.0f; c[3] = (v & 15) / 15.0f;
            break;
        }
        case GL_UNSIGNED_INT_2_10_10_10_REV: {
            uint32_t v = ((const uint32_t *)data)[i];
            c[0] = (v & 1023) / 1023.0f; c[1] = ((v >> 10) & 1023) / 1023.0f; c[2] = ((v >> 20) & 1023) / 1023.0f;
            c[3] = (v >> 30) / 3.0f;
            break;
        }
        default:
            break;
        }
        memcpy(out + 4 * (size_t)i, c, sizeof c);
    }
}

/* Map GL channels to logical ones through a sampling swizzle. */
void d3d_swizzle_rgba(const GLint sw[4], float *rgba, uint32_t count)
{
    for (uint32_t i = 0; i < count; ++i) {
        float *p = rgba + 4 * (size_t)i, c[4];
        for (int k = 0; k < 4; ++k) {
            switch (sw[k]) {
            case GL_RED: c[k] = p[0]; break;
            case GL_GREEN: c[k] = p[1]; break;
            case GL_BLUE: c[k] = p[2]; break;
            case GL_ALPHA: c[k] = p[3]; break;
            case GL_ZERO: c[k] = 0.0f; break;
            default: c[k] = 1.0f; break;
            }
        }
        memcpy(p, c, sizeof c);
    }
}

/* The swizzle from GL storage to logical channels of a texture or surface:
 * GPU-written BGRA formats are stored as RGBA (see d3d_format_convert). */
void d3d_storage_swizzle(const d3d_format *f, uint32_t usage, GLint sw[4])
{
    for (int k = 0; k < 4; ++k) sw[k] = f->swizzle[k];
    if ((usage & D3DUSAGE_RENDERTARGET) && (f->d3d == 21 || f->d3d == 22 || f->d3d == 35)) {
        sw[0] = GL_RED; sw[1] = GL_GREEN; sw[2] = GL_BLUE;
        sw[3] = f->d3d == 22 ? GL_ONE : GL_ALPHA;
    }
}

/* Guest texels (D3D layout, `pitch` bytes per row or block row) to logical RGBA. */
void d3d_format_decode(const d3d_format *f, const uint8_t *src, uint32_t width, uint32_t height, uint32_t pitch, float *rgba)
{
    void *owned;
    size_t size;
    const void *gl = d3d_format_convert(f, src, width, height, pitch, &owned, &size, 0);
    d3d_gl_layout_to_rgba(f->format, f->type, gl, width * height, rgba);
    d3d_swizzle_rgba(f->swizzle, rgba, width * height);
    free(owned);
}

static uint32_t unorm(float v, uint32_t max)
{
    if (!(v > 0.0f)) return 0;
    if (v >= 1.0f) return max;
    return (uint32_t)(v * (float)max + 0.5f);
}

static uint8_t snorm8(float v)
{
    if (!(v > -1.0f)) v = -1.0f;
    if (v > 1.0f) v = 1.0f;
    return (uint8_t)(int8_t)(v * 127.0f + (v < 0 ? -0.5f : 0.5f));
}

/* Logical RGBA to `count` guest texels of format `d3d`. Returns 0 for a
 * format without an encoder (block-compressed, depth). */
int d3d_format_encode(uint32_t d3d, const float *rgba, uint32_t count, uint8_t *out)
{
    for (uint32_t i = 0; i < count; ++i) {
        const float *c = rgba + 4 * (size_t)i;
        float l = (c[0] == c[1] && c[1] == c[2]) ? c[0] : 0.2125f * c[0] + 0.7154f * c[1] + 0.0721f * c[2];
        switch (d3d) {
        case 20:                                               /* R8G8B8 */
            out[3*i] = (uint8_t)unorm(c[2], 255); out[3*i+1] = (uint8_t)unorm(c[1], 255); out[3*i+2] = (uint8_t)unorm(c[0], 255);
            break;
        case 21: case 22:                                      /* A8R8G8B8, X8R8G8B8 */
            out[4*i] = (uint8_t)unorm(c[2], 255); out[4*i+1] = (uint8_t)unorm(c[1], 255); out[4*i+2] = (uint8_t)unorm(c[0], 255);
            out[4*i+3] = d3d == 22 ? 255 : (uint8_t)unorm(c[3], 255);
            break;
        case 32: case 33:                                      /* A8B8G8R8, X8B8G8R8 */
            out[4*i] = (uint8_t)unorm(c[0], 255); out[4*i+1] = (uint8_t)unorm(c[1], 255); out[4*i+2] = (uint8_t)unorm(c[2], 255);
            out[4*i+3] = d3d == 33 ? 255 : (uint8_t)unorm(c[3], 255);
            break;
        case 23:                                               /* R5G6B5 */
            ((uint16_t *)out)[i] = (uint16_t)(unorm(c[0], 31) << 11 | unorm(c[1], 63) << 5 | unorm(c[2], 31));
            break;
        case 24: case 25:                                      /* X1R5G5B5, A1R5G5B5 */
            ((uint16_t *)out)[i] = (uint16_t)((d3d == 24 ? 1u : unorm(c[3], 1)) << 15 | unorm(c[0], 31) << 10 |
                unorm(c[1], 31) << 5 | unorm(c[2], 31));
            break;
        case 26:                                               /* A4R4G4B4 */
            ((uint16_t *)out)[i] = (uint16_t)(unorm(c[3], 15) << 12 | unorm(c[0], 15) << 8 | unorm(c[1], 15) << 4 | unorm(c[2], 15));
            break;
        case 28: out[i] = (uint8_t)unorm(c[3], 255); break;                       /* A8 */
        case 50: out[i] = (uint8_t)unorm(l, 255); break;                          /* L8 */
        case 51: out[2*i] = (uint8_t)unorm(l, 255); out[2*i+1] = (uint8_t)unorm(c[3], 255); break;   /* A8L8 */
        case 81: ((uint16_t *)out)[i] = (uint16_t)unorm(l, 65535); break;        /* L16 */
        case 34:                                               /* G16R16 */
            ((uint16_t *)out)[2*i] = (uint16_t)unorm(c[0], 65535); ((uint16_t *)out)[2*i+1] = (uint16_t)unorm(c[1], 65535);
            break;
        case 36: for (int k = 0; k < 4; ++k) ((uint16_t *)out)[4*i+k] = (uint16_t)unorm(c[k], 65535); break;   /* A16B16G16R16 */
        case 31:                                               /* A2B10G10R10 */
            ((uint32_t *)out)[i] = unorm(c[0], 1023) | unorm(c[1], 1023) << 10 | unorm(c[2], 1023) << 20 | unorm(c[3], 3) << 30;
            break;
        case 35:                                               /* A2R10G10B10 */
            ((uint32_t *)out)[i] = unorm(c[2], 1023) | unorm(c[1], 1023) << 10 | unorm(c[0], 1023) << 20 | unorm(c[3], 3) << 30;
            break;
        case 60: out[2*i] = snorm8(c[0]); out[2*i+1] = snorm8(c[1]); break;      /* V8U8 */
        case 63: for (int k = 0; k < 4; ++k) out[4*i+k] = snorm8(c[k]); break;   /* Q8W8V8U8 */
        case 111: ((uint16_t *)out)[i] = d3d_float_to_half(c[0]); break;          /* R16F */
        case 112: for (int k = 0; k < 2; ++k) ((uint16_t *)out)[2*i+k] = d3d_float_to_half(c[k]); break;
        case 113: for (int k = 0; k < 4; ++k) ((uint16_t *)out)[4*i+k] = d3d_float_to_half(c[k]); break;
        case 114: ((float *)out)[i] = c[0]; break;                                /* R32F */
        case 115: memcpy(out + 8 * (size_t)i, c, 8); break;
        case 116: memcpy(out + 16 * (size_t)i, c, 16); break;
        default: return 0;
        }
    }
    return 1;
}

/* Resample a w x h RGBA image to dw x dh: a box average over each target
 * texel's footprint when shrinking, nearest texel when growing. */
void d3d_rgba_resample(const float *src, uint32_t w, uint32_t h, float *dst, uint32_t dw, uint32_t dh)
{
    for (uint32_t y = 0; y < dh; ++y) {
        uint32_t y0 = (uint32_t)((uint64_t)y * h / dh), y1 = (uint32_t)((uint64_t)(y + 1) * h / dh);
        if (y1 <= y0) y1 = y0 + 1;
        for (uint32_t x = 0; x < dw; ++x) {
            uint32_t x0 = (uint32_t)((uint64_t)x * w / dw), x1 = (uint32_t)((uint64_t)(x + 1) * w / dw);
            if (x1 <= x0) x1 = x0 + 1;
            float sum[4] = { 0, 0, 0, 0 };
            for (uint32_t sy = y0; sy < y1; ++sy)
                for (uint32_t sx = x0; sx < x1; ++sx)
                    for (int k = 0; k < 4; ++k) sum[k] += src[4 * ((size_t)sy * w + sx) + k];
            float n = (float)((x1 - x0) * (y1 - y0));
            for (int k = 0; k < 4; ++k) dst[4 * ((size_t)y * dw + x) + k] = sum[k] / n;
        }
    }
}
