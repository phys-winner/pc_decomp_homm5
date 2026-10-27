/* Texture converter: the game's DXT (S3TC) textures re-encoded once, on the
 * device, into a format its GPU samples directly (ETC2 or ASTC).
 *
 * Output: <game>/<bank>/zz_port_textures.pak, a stored zip holding the converted
 * DDS files under the original paths. Each entry's DOS time is the winning
 * original's plus two seconds: H5 resolves equal paths across the data paks by
 * the newer entry (0x009DEF50), so the copy shadows exactly the file it was
 * made from and any later patch or mod still wins over it. A converted DDS
 * keeps the original header (sizes, mip count) with a port FourCC and a marker
 * in dwReserved1; the D3DX loader (android/host/d3dx9.c) uploads its blocks
 * as they are and reports the original DXT format to the game.
 *
 * <game>/<bank>/zz_port_textures.json describes the conversion for the
 * launcher. Removing the originals rewrites the source paks without the
 * converted entries (raw copies of every other entry). */
#ifndef HOMM5_TEXCONV_H
#define HOMM5_TEXCONV_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    TEXCONV_ETC2 = 1,
    TEXCONV_ASTC = 2,
};

enum {
    TEXCONV_IDLE = 0,
    TEXCONV_SCANNING,
    TEXCONV_CONVERTING,
    TEXCONV_FINISHING,
    TEXCONV_REMOVING,
    TEXCONV_DONE,
    TEXCONV_FAILED,
    TEXCONV_CANCELLED,
};

/* Port FourCCs of converted DDS files and their marker (dwReserved1[0]). */
#define TEXCONV_FOURCC(a, b, c, d) ((uint32_t)(a) | ((uint32_t)(b) << 8) | ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))
#define TEXCONV_MARKER TEXCONV_FOURCC('H', '5', 'T', 'C')
#define TEXCONV_ETC2_RGB TEXCONV_FOURCC('H', '5', 'E', '1')    /* GL_COMPRESSED_RGB8_ETC2, 8 bytes per 4x4 */
#define TEXCONV_ETC2_RGBA TEXCONV_FOURCC('H', '5', 'E', '2')   /* GL_COMPRESSED_RGBA8_ETC2_EAC, 16 per 4x4 */
#define TEXCONV_ASTC_4x4 TEXCONV_FOURCC('H', '5', 'A', '4')    /* GL_COMPRESSED_RGBA_ASTC_4x4_KHR */
#define TEXCONV_ASTC_5x5 TEXCONV_FOURCC('H', '5', 'A', '5')    /* GL_COMPRESSED_RGBA_ASTC_5x5_KHR */
#define TEXCONV_ASTC_6x6 TEXCONV_FOURCC('H', '5', 'A', '6')    /* GL_COMPRESSED_RGBA_ASTC_6x6_KHR */
#define TEXCONV_VERSION 2u
/* In dwReserved1 of a converted DDS (file offsets, little-endian DWORDs):
 *   36 TEXCONV_MARKER  40 TEXCONV_VERSION  44 original FourCC
 *   48 mip levels per face  52 flags: bit 0 opaque
 * The standard fields keep the original's values except the FourCC (84).
 * The payload keeps the original's layout: every level of every face in its
 * original DXT block slots, the converted blocks at the start of the slot and
 * zeros after them. H5's own DDS loader (0x00A9DF80) walks the levels by the
 * DXT sizes; android/host/texture_native.c tells it the original format. So
 * converted blocks must fit the slots: DXT1 (8 bytes per 4x4) takes ETC2 RGB;
 * DXT2..5 (16 per 4x4) ETC2 RGB or RGBA, or ASTC 4x4. A DXT1 with
 * transparency has no format that fits and stays as it is. */

typedef struct {
    int state;
    int64_t done, total;              /* textures */
    int64_t bytes_done, bytes_total;  /* source bytes (DXT data) */
    char message[512];                /* failure reason, English */
} texconv_progress;

typedef struct {
    int64_t textures;                 /* convertible originals */
    int64_t bytes;                    /* their DXT bytes */
    int64_t estimate_etc2, estimate_astc;   /* converted pak sizes */
    int converted_format;             /* 0, TEXCONV_ETC2 or TEXCONV_ASTC: an existing conversion */
    int64_t converted_textures, converted_bytes;
    int originals_removed;            /* originals may be gone; undo/format changes are guarded */
    int64_t removable_bytes;          /* what removing the originals frees (compressed size) */
} texconv_status;

/* Inspect <game>/data: what there is to convert and what is converted. 0 on
 * success, else -1 with the reason in the progress message. */
int texconv_scan(const char *game_dir, texconv_status *out);
/* Convert (blocking; run on a worker thread). threads <= 0: one per CPU. */
int texconv_convert(const char *game_dir, int format, int threads);
/* Rewrite the source paks without the entries the conversion replaced. */
int texconv_remove_originals(const char *game_dir);
/* Delete the conversion; refused (-1) once its originals are gone. */
int texconv_remove_converted(const char *game_dir);
/* Isolated installed data banks: data, DataLS (1.6), dataa1 (2.1). Preserve
 * the actual directory spelling; reject every other name before any write.
 * Each bank keeps its own archive, timestamps and bank-bound manifest. */
int texconv_scan_bank(const char *game_dir, const char *bank, texconv_status *out);
int texconv_convert_bank(const char *game_dir, const char *bank, int format, int threads);
int texconv_remove_originals_bank(const char *game_dir, const char *bank);
int texconv_remove_converted_bank(const char *game_dir, const char *bank);
void texconv_cancel(void);
void texconv_get_progress(texconv_progress *out);

/* Building blocks, exported for tests. texconv_convert_dds: 0 converted (free
 * *out with texconv_free), 1 kept as it is (a transparent DXT1), -1 error. */
int texconv_convert_dds(const uint8_t *dds, uint64_t size, int format, uint8_t **out, uint64_t *out_size);
void texconv_free(void *pointer);
int texconv_decode_dxt(uint32_t fourcc, const uint8_t *blocks, uint32_t width, uint32_t height, uint8_t *rgba);
int texconv_decode_converted(const uint8_t *dds, uint64_t size, uint32_t level, uint8_t *rgba);

#ifdef __cplusplus
}
#endif

#endif
