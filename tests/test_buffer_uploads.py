"""Execute the real GPU buffer flush body with recorded GL storage operations."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned GLenum, GLuint;
typedef intptr_t GLintptr, GLsizeiptr;
typedef struct {
    uint32_t size, usage, shadow, dirty_lo, dirty_hi;
    GLuint gl;
    int discard_pending, overwrite_pending;
    uint8_t *dirty_pages;
    uint32_t page_count, dirty_page_count;
} d3d_buffer;
#define GL_COPY_WRITE_BUFFER 0x8F37u
#define GL_DYNAMIC_DRAW 0x88E8u
#define GL_STATIC_DRAW 0x88E4u
#define GL_MAP_WRITE_BIT 2u
#define GL_MAP_UNSYNCHRONIZED_BIT 0x20u
#define GL_MAP_INVALIDATE_RANGE_BIT 4u
#define D3DUSAGE_DYNAMIC 0x200u
#define BUFFER_PAGE_SIZE 4096u
static uint8_t shadow[1024], gpu[512];
#define GPTR(va) (shadow + (va))
static char operations[32];
static unsigned calls, uploaded, map_flags;
static int map_fails;
static void record(char operation) { assert(calls < 31); operations[calls++] = operation; operations[calls] = 0; }
static void glBindBuffer(GLenum target, GLuint buffer) { assert(target == GL_COPY_WRITE_BUFFER && buffer == 7); record('B'); }
static void glBufferData(GLenum target, GLsizeiptr size, const void *data, GLenum usage) {
    assert(target == GL_COPY_WRITE_BUFFER && size == 256 && usage == GL_DYNAMIC_DRAW); record('D');
    if (data) { memcpy(gpu, data, (size_t)size); uploaded += (unsigned)size; }
    else memset(gpu, 0xCD, (size_t)size); /* Undefined new storage must not receive the whole shadow. */
}
static void glBufferSubData(GLenum target, GLintptr offset, GLsizeiptr size, const void *data) {
    assert(target == GL_COPY_WRITE_BUFFER && offset >= 0 && size >= 0 && offset + size <= 256); record('S');
    memcpy(gpu + offset, data, (size_t)size); uploaded += (unsigned)size;
}
static void *glMapBufferRange(GLenum target, GLintptr offset, GLsizeiptr size, unsigned flags) {
    assert(target == GL_COPY_WRITE_BUFFER && offset >= 0 && size >= 0 && offset + size <= 256); record('M');
    map_flags = flags; return map_fails ? NULL : gpu + offset;
}
static int glUnmapBuffer(GLenum target) { assert(target == GL_COPY_WRITE_BUFFER); record('U'); return 1; }
static void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi);
#include "flush.h"
#include "range.h"
static unsigned checks;
static d3d_buffer setup(uint32_t lo, uint32_t hi, int discard, int overwrite) {
    for (unsigned i = 0; i < sizeof shadow; ++i) shadow[i] = (uint8_t)i;
    memset(gpu, 0xA5, sizeof gpu); operations[0] = 0; calls = uploaded = map_flags = 0; map_fails = 0;
    d3d_buffer b = {256, D3DUSAGE_DYNAMIC, 16, lo, hi, 7, discard, overwrite, NULL, 0, 0}; return b;
}
static void flushed(d3d_buffer *b, const char *expected) {
    assert(!strcmp(operations, expected));
    assert(b->dirty_lo == UINT32_MAX && b->dirty_hi == 0 && !b->discard_pending && !b->overwrite_pending); ++checks;
}
int main(void) {
    d3d_buffer b = setup(64, 80, 1, 0); d3d_buffer_flush(&b); flushed(&b, "BDS");
    assert(uploaded == 16 && !memcmp(gpu + 64, GPTR(16 + 64), 16) && gpu[63] == 0xCD && gpu[80] == 0xCD);
    b = setup(0, 256, 1, 1); d3d_buffer_flush(&b); flushed(&b, "BDS");
    assert(uploaded == 256 && !memcmp(gpu, GPTR(16), 256));
    b = setup(0, 256, 0, 1); d3d_buffer_flush(&b); flushed(&b, "BD");
    assert(uploaded == 256 && !memcmp(gpu, GPTR(16), 256));
    b = setup(64, 80, 0, 1); d3d_buffer_flush(&b); flushed(&b, "BS");
    assert(uploaded == 16 && !memcmp(gpu + 64, GPTR(80), 16) && gpu[63] == 0xA5 && gpu[80] == 0xA5);
    b = setup(64, 80, 0, 0); d3d_buffer_flush(&b); flushed(&b, "BMU");
    assert(map_flags == (GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT | GL_MAP_INVALIDATE_RANGE_BIT));
    assert(!memcmp(gpu + 64, GPTR(80), 16) && gpu[63] == 0xA5 && gpu[80] == 0xA5);
    b = setup(64, 80, 0, 0); map_fails = 1; d3d_buffer_flush(&b); flushed(&b, "BMS"); assert(uploaded == 16);
    d3d_buffer_flush(&b); assert(!strcmp(operations, "BMS")); /* A second draw does not upload again. */
    b = setup(UINT32_MAX, 0, 0, 0); d3d_buffer_flush(&b); assert(!calls); ++checks;
    b = setup(0, 0, 0, 0); b.size = 0; d3d_buffer_flush(&b); assert(!calls); ++checks;
    printf("PASS %u buffer flush cases: partial DISCARD uploads16/256 bytes, full storage, NOOVERWRITE, map fallback, clean and zero size\n", checks);
    return 0;
}
'''


class BufferUploadsTest(unittest.TestCase):
    def test_upload_only_discarded_dirty_range(self):
        resource = (ROOT / "android/host/d3d9_resource.c").read_text(encoding="utf-8")
        compile_probe("buffer_uploads", HARNESS, {
            "flush.h": function(resource, "void d3d_buffer_flush("),
            "range.h": function(resource, "void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi)\n{"),
        })


if __name__ == "__main__":
    unittest.main()
