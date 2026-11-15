"""The streaming ring grows when a frame asks more than a segment holds (d3d9_gl.c ring region).

The real ring code against fake GL: a frame that outgrows its 16 MiB segment falls back for its rest,
then the ring is released at the frame's end and the next request maps 3 segments sized to the frame's
demand + 25%, in 4 MiB steps up to 64 MiB; a frame that fits changes nothing; a grown ring that
cannot be mapped falls back to 16 MiB segments; and the fences of the old ring are deleted with it."""
import unittest

from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned GLenum; typedef unsigned GLuint; typedef intptr_t GLsizeiptr; typedef intptr_t GLintptr;
typedef unsigned GLbitfield; typedef uint64_t GLuint64; typedef void *GLsync; typedef unsigned char GLubyte;
#define GL_EXTENSIONS 0x1F03u
#define GL_COPY_WRITE_BUFFER 0x8F37u
#define GL_STREAM_DRAW 0x88E0u
#define GL_MAP_WRITE_BIT 2u
#define GL_MAP_PERSISTENT_BIT_EXT 0x40u
#define GL_MAP_COHERENT_BIT_EXT 0x80u
#define GL_SYNC_GPU_COMMANDS_COMPLETE 0x9117u
#define GL_SYNC_FLUSH_COMMANDS_BIT 1u
#define GL_ALREADY_SIGNALED 0x911Au
#define GL_CONDITION_SATISFIED 0x911Cu
#define GL_WAIT_FAILED 0x911Du
typedef void (*PFNGLBUFFERSTORAGEEXTPROC)(GLenum, GLsizeiptr, const void *, GLbitfield);
static char logged[256];
#define void_log(...) snprintf(logged, sizeof logged, __VA_ARGS__)
static GLuint next_name = 1, live_buffers;
static size_t mapped_bytes, storage_bytes, map_limit = (size_t)1 << 40;
static unsigned maps, unmaps, fences, deleted_fences, per_draw_stores;
static uint8_t *map_memory;
static const GLubyte *glGetString(GLenum e) { assert(e == GL_EXTENSIONS); return (const GLubyte *)"GL_EXT_buffer_storage"; }
static void storage_proc(GLenum t, GLsizeiptr n, const void *d, GLbitfield f) { (void)t; (void)d; (void)f; storage_bytes = (size_t)n; }
static void *eglGetProcAddress(const char *name) { assert(!strcmp(name, "glBufferStorageEXT")); return (void *)storage_proc; }
static void glGenBuffers(int n, GLuint *b) { assert(n == 1); *b = next_name++; ++live_buffers; }
static void glDeleteBuffers(int n, const GLuint *b) { assert(n == 1 && *b); --live_buffers; }
static void glBindBuffer(GLenum t, GLuint b) { (void)t; (void)b; }
static void glBufferData(GLenum t, GLsizeiptr n, const void *d, GLenum u) { (void)t; (void)n; (void)d; (void)u; ++per_draw_stores; }
static void *glMapBufferRange(GLenum t, GLintptr o, GLsizeiptr n, GLbitfield f) {
    (void)t; (void)o; (void)f;
    if ((size_t)n > map_limit) return NULL;
    ++maps; mapped_bytes = (size_t)n; map_memory = realloc(map_memory, (size_t)n); return map_memory;
}
static int glUnmapBuffer(GLenum t) { (void)t; ++unmaps; return 1; }
static GLenum glGetError(void) { return 0; }
static GLsync glFenceSync(GLenum c, GLbitfield f) { (void)c; (void)f; ++fences; return (GLsync)(uintptr_t)fences; }
static void glDeleteSync(GLsync s) { assert(s); ++deleted_fences; }
static GLenum glClientWaitSync(GLsync s, GLbitfield f, GLuint64 t) { (void)s; (void)f; (void)t; return GL_ALREADY_SIGNALED; }
static GLuint stream_vbos[16];
#include "ring.h"

static void frame(uint32_t draws, uint32_t bytes)
{
    for (uint32_t i = 0; i < draws; ++i) {
        uint8_t data[64] = {0};
        (void)data;
        uint32_t at;
        if (!ring_alloc(bytes, &at)) ++per_draw_stores;
    }
    ring_frame_end();
}

int main(void)
{
    assert(ring_ready() && mapped_bytes == 3u * (16u << 20));
    frame(1000, 10000);                                  /* 10 MB: fits, nothing changes */
    assert(ring_state == 1 && RING_SEGMENT_BYTES == (16u << 20) && !per_draw_stores && maps == 1);
    frame(3000, 10000);                                  /* one 30 MB frame (as at every start): no growth */
    assert(per_draw_stores > 1000 && ring_state == 1 && RING_SEGMENT_BYTES == (16u << 20));
    frame(1000, 10000);                                  /* a frame that fits ends the run */
    per_draw_stores = 0;
    frame(2000, 10000); frame(1900, 10000);              /* 20 MB frames: two in a row, still no growth */
    assert(per_draw_stores > 300 && ring_state == 1 && RING_SEGMENT_BYTES == (16u << 20));
    frame(1950, 10000);                                  /* the third: the ring grows to the run's peak */
    assert(ring_state == 0 && !ring_buffer && unmaps == 1 && live_buffers == 0);
    uint32_t grown = RING_SEGMENT_BYTES;
    assert(grown == (24u << 20) && strstr(logged, "segments grow to 24 MiB"));   /* 20 MB + 25% in 4 MiB steps */
    unsigned before = per_draw_stores;
    frame(2400, 10000);                                  /* 24 MB now fits the grown ring */
    assert(per_draw_stores == before && mapped_bytes == 3u * (size_t)grown && ring_state == 1);
    for (int i = 0; i < 9; ++i) frame(20000, 10000);     /* 200 MB a frame: capped at 64 MiB segments */
    assert(RING_SEGMENT_BYTES == (64u << 20));
    map_limit = 3u * (16u << 20);                        /* a grown ring cannot be mapped: back to 16 MiB */
    ring_release();
    assert(ring_ready() && RING_SEGMENT_BYTES == (16u << 20) && mapped_bytes == 3u * (16u << 20));
    ring_release();
    assert(!ring_state && !ring_buffer && fences == deleted_fences);
    printf("PASS ring growth: 16 MiB fits 10 MB frames, one 30 MB frame or two 20 MB frames change nothing, three 20 MB frames grow the segments to %u MiB (demand + 25%%, 4 MiB steps), "
           "capped at 64 MiB, a ring that cannot be mapped falls back to 16 MiB, fences released\n", grown >> 20);
    return 0;
}
'''


class RingGrowthTest(unittest.TestCase):
    def test_ring_growth(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
        ring = source[source.index("/* Per-draw uploads go to one persistently mapped buffer"):source.index("static uint32_t enabled_attribs;")]
        compile_probe("ring_growth", HARNESS, {"ring.h": ring})


if __name__ == "__main__":
    unittest.main()
