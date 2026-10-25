/* D3DFORMAT -> GLES 3.2 storage, sampling swizzles and upload conversions.
 * Mali-G76 exposes no S3TC/RGTC, so DXTn and ATIn blocks are decoded. */
#include "d3d9_internal.h"

#define R GL_RED
#define G GL_GREEN
#define B GL_BLUE
#define A GL_ALPHA
#define Z GL_ZERO
#define O GL_ONE

static const d3d_format formats[] = {
    /* d3d  bits block internal                 format              type                              conv            swizzle        d s rt f glbits */
    {20,  24, 0, GL_RGB8,                 GL_RGB,             GL_UNSIGNED_BYTE,                 CONV_NONE,      {B, G, R, O}, 0, 0, 0, 0, 24},
    {21,  32, 0, GL_RGBA8,                GL_RGBA,            GL_UNSIGNED_BYTE,                 CONV_NONE,      {B, G, R, A}, 0, 0, 1, 0, 32},
    {22,  32, 0, GL_RGBA8,                GL_RGBA,            GL_UNSIGNED_BYTE,                 CONV_NONE,      {B, G, R, O}, 0, 0, 1, 0, 32},
    {23,  16, 0, GL_RGB565,               GL_RGB,             GL_UNSIGNED_SHORT_5_6_5,          CONV_NONE,      {R, G, B, O}, 0, 0, 1, 0, 16},
    {24,  16, 0, GL_RGB5_A1,              GL_RGBA,            GL_UNSIGNED_SHORT_5_5_5_1,        CONV_X1R5G5B5,  {R, G, B, O}, 0, 0, 0, 0, 16},
    {25,  16, 0, GL_RGB5_A1,              GL_RGBA,            GL_UNSIGNED_SHORT_5_5_5_1,        CONV_A1R5G5B5,  {R, G, B, A}, 0, 0, 0, 0, 16},
    {26,  16, 0, GL_RGBA4,                GL_RGBA,            GL_UNSIGNED_SHORT_4_4_4_4,        CONV_A4R4G4B4,  {R, G, B, A}, 0, 0, 0, 0, 16},
    {28,   8, 0, GL_R8,                   GL_RED,             GL_UNSIGNED_BYTE,                 CONV_NONE,      {Z, Z, Z, R}, 0, 0, 0, 0, 8},
    {31,  32, 0, GL_RGB10_A2,             GL_RGBA,            GL_UNSIGNED_INT_2_10_10_10_REV,   CONV_NONE,      {R, G, B, A}, 0, 0, 1, 0, 32},
    {34,  32, 0, GL_RG32F,                GL_RG,              GL_FLOAT,                         CONV_G16R16,    {R, G, O, O}, 0, 0, 0, 1, 64},
    {35,  32, 0, GL_RGB10_A2,             GL_RGBA,            GL_UNSIGNED_INT_2_10_10_10_REV,   CONV_NONE,      {B, G, R, A}, 0, 0, 1, 0, 32},
    {36,  64, 0, GL_RGBA32F,              GL_RGBA,            GL_FLOAT,                         CONV_A16B16G16R16, {R, G, B, A}, 0, 0, 0, 1, 128},
    {50,   8, 0, GL_R8,                   GL_RED,             GL_UNSIGNED_BYTE,                 CONV_NONE,      {R, R, R, O}, 0, 0, 0, 0, 8},
    {51,  16, 0, GL_RG8,                  GL_RG,              GL_UNSIGNED_BYTE,                 CONV_NONE,      {R, R, R, G}, 0, 0, 0, 0, 16},
    {60,  16, 0, GL_RG8_SNORM,            GL_RG,              GL_BYTE,                          CONV_NONE,      {R, G, O, O}, 0, 0, 0, 0, 16},
    {63,  32, 0, GL_RGBA8_SNORM,          GL_RGBA,            GL_BYTE,                          CONV_NONE,      {R, G, B, A}, 0, 0, 0, 0, 32},
    {81,  16, 0, GL_R32F,                 GL_RED,             GL_FLOAT,                         CONV_L16,       {R, R, R, O}, 0, 0, 0, 1, 32},
    {111, 16, 0, GL_R16F,                 GL_RED,             GL_HALF_FLOAT,                    CONV_NONE,      {R, O, O, O}, 0, 0, 1, 1, 16},
    {112, 32, 0, GL_RG16F,                GL_RG,              GL_HALF_FLOAT,                    CONV_NONE,      {R, G, O, O}, 0, 0, 1, 1, 32},
    {113, 64, 0, GL_RGBA16F,              GL_RGBA,            GL_HALF_FLOAT,                    CONV_NONE,      {R, G, B, A}, 0, 0, 1, 1, 64},
    {114, 32, 0, GL_R32F,                 GL_RED,             GL_FLOAT,                         CONV_NONE,      {R, O, O, O}, 0, 0, 1, 1, 32},
    {115, 64, 0, GL_RG32F,                GL_RG,              GL_FLOAT,                         CONV_NONE,      {R, G, O, O}, 0, 0, 1, 1, 64},
    {116,128, 0, GL_RGBA32F,              GL_RGBA,            GL_FLOAT,                         CONV_NONE,      {R, G, B, A}, 0, 0, 1, 1, 128},
    /* Depth/stencil */
    {70,  16, 0, GL_DEPTH_COMPONENT16,    GL_DEPTH_COMPONENT, GL_UNSIGNED_SHORT,                CONV_NONE,      {R, R, R, R}, 1, 0, 0, 0, 16},
    {71,  32, 0, GL_DEPTH_COMPONENT32F,   GL_DEPTH_COMPONENT, GL_FLOAT,                         CONV_NONE,      {R, R, R, R}, 1, 0, 0, 0, 32},
    {75,  32, 0, GL_DEPTH24_STENCIL8,     GL_DEPTH_STENCIL,   GL_UNSIGNED_INT_24_8,             CONV_NONE,      {R, R, R, R}, 1, 1, 0, 0, 32},
    {77,  32, 0, GL_DEPTH24_STENCIL8,     GL_DEPTH_STENCIL,   GL_UNSIGNED_INT_24_8,             CONV_NONE,      {R, R, R, R}, 1, 1, 0, 0, 32},
    {79,  32, 0, GL_DEPTH24_STENCIL8,     GL_DEPTH_STENCIL,   GL_UNSIGNED_INT_24_8,             CONV_NONE,      {R, R, R, R}, 1, 1, 0, 0, 32},
    {80,  16, 0, GL_DEPTH_COMPONENT16,    GL_DEPTH_COMPONENT, GL_UNSIGNED_SHORT,                CONV_NONE,      {R, R, R, R}, 1, 0, 0, 0, 16},
    {82,  32, 0, GL_DEPTH_COMPONENT32F,   GL_DEPTH_COMPONENT, GL_FLOAT,                         CONV_NONE,      {R, R, R, R}, 1, 0, 0, 0, 32},
    {83,  32, 0, GL_DEPTH24_STENCIL8,     GL_DEPTH_STENCIL,   GL_UNSIGNED_INT_24_8,             CONV_NONE,      {R, R, R, R}, 1, 1, 0, 0, 32},
    {FOURCC('I','N','T','Z'), 32, 0, GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8, CONV_NONE, {R, R, R, R}, 1, 1, 0, 0, 32},
    {FOURCC('R','A','W','Z'), 32, 0, GL_DEPTH24_STENCIL8, GL_DEPTH_STENCIL, GL_UNSIGNED_INT_24_8, CONV_NONE, {R, R, R, R}, 1, 1, 0, 0, 32},
    {FOURCC('D','F','2','4'), 32, 0, GL_DEPTH_COMPONENT24, GL_DEPTH_COMPONENT, GL_UNSIGNED_INT, CONV_NONE, {R, R, R, R}, 1, 0, 0, 0, 32},
    {FOURCC('D','F','1','6'), 16, 0, GL_DEPTH_COMPONENT16, GL_DEPTH_COMPONENT, GL_UNSIGNED_SHORT, CONV_NONE, {R, R, R, R}, 1, 0, 0, 0, 16},
    /* Block-compressed formats, decoded on upload */
    {FOURCC('D','X','T','1'), 4, 8,  GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, CONV_DXT1, {R, G, B, A}, 0, 0, 0, 0, 32},
    {FOURCC('D','X','T','2'), 8, 16, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, CONV_DXT3, {R, G, B, A}, 0, 0, 0, 0, 32},
    {FOURCC('D','X','T','3'), 8, 16, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, CONV_DXT3, {R, G, B, A}, 0, 0, 0, 0, 32},
    {FOURCC('D','X','T','4'), 8, 16, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, CONV_DXT5, {R, G, B, A}, 0, 0, 0, 0, 32},
    {FOURCC('D','X','T','5'), 8, 16, GL_RGBA8, GL_RGBA, GL_UNSIGNED_BYTE, CONV_DXT5, {R, G, B, A}, 0, 0, 0, 0, 32},
    {FOURCC('A','T','I','1'), 4, 8,  GL_R8,    GL_RED,  GL_UNSIGNED_BYTE, CONV_ATI1, {R, R, R, R}, 0, 0, 0, 0, 8},
    {FOURCC('A','T','I','2'), 8, 16, GL_RG8,   GL_RG,   GL_UNSIGNED_BYTE, CONV_ATI2, {R, G, O, O}, 0, 0, 0, 0, 16},
    /* NULL render target: no storage, colour writes discarded. */
    {FOURCC('N','U','L','L'), 0, 0, 0, 0, 0, CONV_NONE, {R, G, B, A}, 0, 0, 1, 0, 0},
};

#undef R
#undef G
#undef B
#undef A
#undef Z
#undef O

const d3d_format *d3d_format_find(uint32_t d3d)
{
    for (size_t i = 0; i < sizeof formats / sizeof formats[0]; ++i) if (formats[i].d3d == d3d) return &formats[i];
    return NULL;
}

/* android/texconv/texconv.h: TEXCONV_ETC2_RGB .. TEXCONV_ASTC_6x6. */
static const d3d_native_format natives[] = {
    {FOURCC('H','5','E','1'), GL_COMPRESSED_RGB8_ETC2,        4, 4, 8,  0},
    {FOURCC('H','5','E','2'), GL_COMPRESSED_RGBA8_ETC2_EAC,   4, 4, 16, 0},
    {FOURCC('H','5','A','4'), GL_COMPRESSED_RGBA_ASTC_4x4_KHR, 4, 4, 16, 1},
    {FOURCC('H','5','A','5'), GL_COMPRESSED_RGBA_ASTC_5x5_KHR, 5, 5, 16, 1},
    {FOURCC('H','5','A','6'), GL_COMPRESSED_RGBA_ASTC_6x6_KHR, 6, 6, 16, 1},
};

const d3d_native_format *d3d_native_find(uint32_t fourcc)
{
    for (size_t i = 0; i < sizeof natives / sizeof natives[0]; ++i) if (natives[i].fourcc == fourcc) return &natives[i];
    return NULL;
}

/* ETC2 is core in GLES 3; ASTC needs the extension (d3d_gl_init). */
int d3d_native_supported(const d3d_native_format *n)
{
    return n && (!n->astc || d3d_gl_limits.astc_ldr);
}

uint32_t d3d_native_size(const d3d_native_format *n, uint32_t width, uint32_t height)
{
    return ((width + n->block_w - 1) / n->block_w) * ((height + n->block_h - 1) / n->block_h) * n->block_bytes;
}

uint32_t d3d_format_pitch(const d3d_format *f, uint32_t width)
{
    if (f->block_bytes) return ((width + 3) / 4) * f->block_bytes;
    return (width * f->bits + 7) / 8;
}

uint32_t d3d_format_rows(const d3d_format *f, uint32_t height)
{
    return f->block_bytes ? (height + 3) / 4 : height;
}

/* -------------------------------------------------------------- blocks */
static void rgb565(uint16_t c, uint8_t out[3])
{
    uint32_t r = (c >> 11) & 31, g = (c >> 5) & 63, b = c & 31;
    out[0] = (uint8_t)((r << 3) | (r >> 2));
    out[1] = (uint8_t)((g << 2) | (g >> 4));
    out[2] = (uint8_t)((b << 3) | (b >> 2));
}

static void decode_color_block(const uint8_t *block, uint8_t out[16][4], int force_four)
{
    uint16_t c0 = (uint16_t)(block[0] | (block[1] << 8)), c1 = (uint16_t)(block[2] | (block[3] << 8));
    uint32_t bits = (uint32_t)block[4] | ((uint32_t)block[5] << 8) | ((uint32_t)block[6] << 16) | ((uint32_t)block[7] << 24);
    uint8_t pal[4][4];
    rgb565(c0, pal[0]); rgb565(c1, pal[1]);
    pal[0][3] = pal[1][3] = 255;
    if (c0 > c1 || force_four) {
        for (int k = 0; k < 3; ++k) {
            pal[2][k] = (uint8_t)((2 * pal[0][k] + pal[1][k] + 1) / 3);
            pal[3][k] = (uint8_t)((pal[0][k] + 2 * pal[1][k] + 1) / 3);
        }
        pal[2][3] = pal[3][3] = 255;
    } else {
        for (int k = 0; k < 3; ++k) pal[2][k] = (uint8_t)((pal[0][k] + pal[1][k]) / 2);
        pal[2][3] = 255;
        pal[3][0] = pal[3][1] = pal[3][2] = pal[3][3] = 0;
    }
    for (int i = 0; i < 16; ++i) memcpy(out[i], pal[(bits >> (2 * i)) & 3], 4);
}

static void decode_alpha_block(const uint8_t *block, uint8_t out[16])
{
    uint8_t a0 = block[0], a1 = block[1];
    uint64_t bits = 0;
    for (int i = 0; i < 6; ++i) bits |= (uint64_t)block[2 + i] << (8 * i);
    uint8_t pal[8];
    pal[0] = a0; pal[1] = a1;
    if (a0 > a1) {
        for (int i = 1; i < 7; ++i) pal[1 + i] = (uint8_t)(((7 - i) * a0 + i * a1 + 3) / 7);
    } else {
        for (int i = 1; i < 5; ++i) pal[1 + i] = (uint8_t)(((5 - i) * a0 + i * a1 + 2) / 5);
        pal[6] = 0; pal[7] = 255;
    }
    for (int i = 0; i < 16; ++i) out[i] = pal[(bits >> (3 * i)) & 7];
}

static void decode_blocks(int conv, const uint8_t *src, uint32_t width, uint32_t height, uint32_t pitch,
    uint8_t *dst, uint32_t channels)
{
    uint32_t bw = (width + 3) / 4, bh = (height + 3) / 4;
    uint32_t block_bytes = (conv == CONV_DXT1 || conv == CONV_ATI1) ? 8 : 16;
    for (uint32_t by = 0; by < bh; ++by) {
        const uint8_t *row = src + (size_t)by * pitch;
        for (uint32_t bx = 0; bx < bw; ++bx) {
            const uint8_t *block = row + (size_t)bx * block_bytes;
            uint8_t texels[16][4];
            uint8_t alpha[16], second[16];
            switch (conv) {
            case CONV_DXT1:
                decode_color_block(block, texels, 0);
                break;
            case CONV_DXT3:
                decode_color_block(block + 8, texels, 1);
                for (int i = 0; i < 16; ++i) {
                    uint8_t nib = (uint8_t)((block[i / 2] >> (4 * (i & 1))) & 15);
                    texels[i][3] = (uint8_t)(nib * 17);
                }
                break;
            case CONV_DXT5:
                decode_color_block(block + 8, texels, 1);
                decode_alpha_block(block, alpha);
                for (int i = 0; i < 16; ++i) texels[i][3] = alpha[i];
                break;
            case CONV_ATI1:
                decode_alpha_block(block, alpha);
                for (int i = 0; i < 16; ++i) texels[i][0] = alpha[i];
                break;
            case CONV_ATI2:
                /* D3D9 ATI2: the first block holds the second (green) channel. */
                decode_alpha_block(block, second);
                decode_alpha_block(block + 8, alpha);
                for (int i = 0; i < 16; ++i) { texels[i][0] = alpha[i]; texels[i][1] = second[i]; }
                break;
            }
            for (uint32_t y = 0; y < 4; ++y) {
                uint32_t py = by * 4 + y;
                if (py >= height) break;
                for (uint32_t x = 0; x < 4; ++x) {
                    uint32_t px = bx * 4 + x;
                    if (px >= width) break;
                    uint8_t *d = dst + ((size_t)py * width + px) * channels;
                    for (uint32_t c = 0; c < channels; ++c) d[c] = texels[y * 4 + x][c];
                }
            }
        }
    }
}

static uint16_t to_rgb5a1(uint16_t v, int force_alpha)
{
    uint16_t a = force_alpha ? 1 : (uint16_t)(v >> 15);
    return (uint16_t)(((v & 0x7FFF) << 1) | a);
}

const void *d3d_format_convert(const d3d_format *f, const uint8_t *src, uint32_t width, uint32_t height,
    uint32_t pitch, void **owned, size_t *gl_size, int render_target)
{
    *owned = NULL;
    uint32_t out_bpp = f->gl_bits / 8;
    size_t size = (size_t)width * height * (out_bpp ? out_bpp : 1);
    int conv = f->conv;
    if (render_target && (f->d3d == 21 || f->d3d == 22)) conv = CONV_BGRA_TO_RGBA;
    if (conv == CONV_NONE) {
        /* Tightly packed rows can upload in place; otherwise repack. */
        uint32_t row = d3d_format_pitch(f, width);
        *gl_size = (size_t)row * d3d_format_rows(f, height);
        if (row == pitch) return src;
        uint8_t *out = (uint8_t *)malloc(*gl_size);
        for (uint32_t y = 0; y < d3d_format_rows(f, height); ++y) memcpy(out + (size_t)y * row, src + (size_t)y * pitch, row);
        *owned = out;
        return out;
    }
    uint8_t *out = (uint8_t *)malloc(size ? size : 1);
    *owned = out;
    *gl_size = size;
    switch (conv) {
    case CONV_DXT1: case CONV_DXT3: case CONV_DXT5:
        decode_blocks(conv, src, width, height, pitch, out, 4);
        break;
    case CONV_ATI1:
        decode_blocks(conv, src, width, height, pitch, out, 1);
        break;
    case CONV_ATI2:
        decode_blocks(conv, src, width, height, pitch, out, 2);
        break;
    case CONV_X1R5G5B5: case CONV_A1R5G5B5:
        for (uint32_t y = 0; y < height; ++y) {
            const uint16_t *s = (const uint16_t *)(src + (size_t)y * pitch);
            uint16_t *d = (uint16_t *)out + (size_t)y * width;
            for (uint32_t x = 0; x < width; ++x) d[x] = to_rgb5a1(s[x], conv == CONV_X1R5G5B5);
        }
        break;
    case CONV_A4R4G4B4:
        for (uint32_t y = 0; y < height; ++y) {
            const uint16_t *s = (const uint16_t *)(src + (size_t)y * pitch);
            uint16_t *d = (uint16_t *)out + (size_t)y * width;
            for (uint32_t x = 0; x < width; ++x) d[x] = (uint16_t)((s[x] << 4) | (s[x] >> 12));
        }
        break;
    case CONV_L16:
        for (uint32_t y = 0; y < height; ++y) {
            const uint16_t *s = (const uint16_t *)(src + (size_t)y * pitch);
            float *d = (float *)out + (size_t)y * width;
            for (uint32_t x = 0; x < width; ++x) d[x] = (float)s[x] / 65535.0f;
        }
        break;
    case CONV_G16R16:
        for (uint32_t y = 0; y < height; ++y) {
            const uint16_t *s = (const uint16_t *)(src + (size_t)y * pitch);
            float *d = (float *)out + (size_t)y * width * 2;
            for (uint32_t x = 0; x < width * 2; ++x) d[x] = (float)s[x] / 65535.0f;
        }
        break;
    case CONV_A16B16G16R16:
        for (uint32_t y = 0; y < height; ++y) {
            const uint16_t *s = (const uint16_t *)(src + (size_t)y * pitch);
            float *d = (float *)out + (size_t)y * width * 4;
            for (uint32_t x = 0; x < width * 4; ++x) d[x] = (float)s[x] / 65535.0f;
        }
        break;
    case CONV_BGRA_TO_RGBA:
        for (uint32_t y = 0; y < height; ++y) {
            const uint8_t *s = src + (size_t)y * pitch;
            uint8_t *d = out + (size_t)y * width * 4;
            for (uint32_t x = 0; x < width; ++x) {
                d[4 * x + 0] = s[4 * x + 2]; d[4 * x + 1] = s[4 * x + 1];
                d[4 * x + 2] = s[4 * x + 0]; d[4 * x + 3] = f->d3d == 22 ? 255 : s[4 * x + 3];
            }
        }
        break;
    default:
        memset(out, 0, size);
        break;
    }
    return out;
}
