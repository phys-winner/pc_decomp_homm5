/* zlib_deflate_native.c: zlib 1.3.1 deflate with zlib 1.2.3's data_type, for zlib_native.c. */
#ifndef ZLIB_DEFLATE_NATIVE_H
#define ZLIB_DEFLATE_NATIVE_H
#include <stdint.h>

typedef struct h5z_stream h5z_stream;

/* The fields of a guest z_stream the engine reads and writes on every call;
 * message: -1 when the call set none, else the index into zlib's z_errmsg. */
typedef struct h5z_io {
    const uint8_t *next_in;
    uint32_t avail_in, total_in;
    uint8_t *next_out;
    uint32_t avail_out, total_out, adler;
    int data_type, message;
} h5z_io;

int h5z_deflate_init(h5z_stream **out, int level, int method, int window_bits, int mem_level, int strategy);
int h5z_deflate(h5z_stream *s, h5z_io *io, int flush);
int h5z_deflate_end(h5z_stream *s);

#endif
