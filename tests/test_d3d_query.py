"""Exercise production D3D query bodies with nonblocking GLES call spies."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned GLenum, GLuint;
typedef uintptr_t GLsync;
typedef struct { int unused; } void_com_object;
typedef struct { struct { uint32_t viewport[4]; } st; } d3d_device;
#include "query_type.h"
#define D3D_OK 0u
#define S_FALSE_D3D 1u
#define GL_ANY_SAMPLES_PASSED_CONSERVATIVE 0x8D6Au
#define GL_QUERY_RESULT_AVAILABLE 0x8867u
#define GL_QUERY_RESULT 0x8866u
#define GL_SYNC_GPU_COMMANDS_COMPLETE 0x9117u
#define GL_SYNC_FLUSH_COMMANDS_BIT 1u
#define GL_TIMEOUT_EXPIRED 0x911Bu
#define GL_ALREADY_SIGNALED 0x911Au
#define FOURCC(a,b,c,d) ((uint32_t)(a) | ((uint32_t)(b)<<8) | ((uint32_t)(c)<<16) | ((uint32_t)(d)<<24))
static uint32_t memory[8], arguments[4];
#define MEM32(va) memory[(va) / 4u]
#define ARG(n) arguments[n]
#define COM_METHOD(prefix,name,nargs) static uint32_t prefix##_##name(void)
static d3d_query *current;
#define QRY current
static GLuint ready, samples;
static GLenum wait_result;
static unsigned begins, ends, availability_reads, result_reads, flushes, waits;
static unsigned deleted_queries, deleted_fences, fences;
static uint32_t wait_flags, expected_wait_flags;
static int active;
static void glBeginQuery(GLenum target, GLuint id) {
    assert(target == GL_ANY_SAMPLES_PASSED_CONSERVATIVE && id == 7 && !active);
    active = 1; ++begins;
}
static void glEndQuery(GLenum target) {
    assert(target == GL_ANY_SAMPLES_PASSED_CONSERVATIVE && active);
    active = 0; ++ends;
}
static void glGetQueryObjectuiv(GLuint id, GLenum pname, GLuint *out) {
    assert(id == 7 && !active);
    if (pname == GL_QUERY_RESULT_AVAILABLE) { ++availability_reads; *out = ready; }
    else {
        assert(pname == GL_QUERY_RESULT && ready && "must never wait for an unavailable query");
        ++result_reads; *out = samples;
    }
}
static void glFlush(void) { ++flushes; }
static GLsync glFenceSync(GLenum condition, uint32_t flags) {
    assert(condition == GL_SYNC_GPU_COMMANDS_COMPLETE && !flags);
    return (GLsync)(100u + ++fences);
}
static GLenum glClientWaitSync(GLsync fence, uint32_t flags, uint64_t timeout) {
    assert(fence == current->fence && fence && timeout == 0);
    assert(flags == expected_wait_flags);
    ++waits; wait_flags = flags; return wait_result;
}
static void glDeleteSync(GLsync fence) { assert(fence); ++deleted_fences; }
static void glDeleteQueries(int count, const GLuint *ids) { assert(count == 1 && *ids == 7); ++deleted_queries; }
#include "query_bodies.h"
static uint32_t poll(uint32_t out, uint32_t size, uint32_t flags) {
    arguments[1] = out; arguments[2] = size; arguments[3] = flags;
    return qry_GetData();
}
static void issue(uint32_t flags) { arguments[1] = flags; assert(qry_Issue() == D3D_OK); }
static void reset_spies(void) {
    availability_reads = result_reads = flushes = waits = 0;
    for (unsigned i = 0; i < 8; ++i) memory[i] = 0xCDCDCDCDu;
}
int main(void) {
    d3d_device dev = {{{0,0,640,480}}};
    d3d_query q = {0}; q.dev = &dev; q.type = 9; q.gl = 7; current = &q;
    assert(qry_GetDataSize() == 4);
    issue(2); assert(q.issued && !q.ended && begins == 1);
    issue(1); assert(!q.issued && q.ended && ends == 1);

    /* Regression: FLUSH submits work, but may not read/wait for its result. */
    reset_spies(); ready = 0;
    assert(poll(4,4,1) == S_FALSE_D3D);
    assert(flushes == 1 && availability_reads == 1 && !result_reads && memory[1] == 0xCDCDCDCDu);
    reset_spies();
    assert(poll(0,0,0) == S_FALSE_D3D && !flushes && !result_reads && availability_reads == 1);
    assert(poll(0,0,1) == S_FALSE_D3D && flushes == 1 && !result_reads);
    assert(poll(0,4,1) == S_FALSE_D3D && flushes == 2 && !result_reads);
    assert(poll(4,3,0) == S_FALSE_D3D && memory[1] == 0xCDCDCDCDu);

    reset_spies(); ready = 1; samples = 1;
    assert(poll(4,4,0) == D3D_OK && memory[1] == 640u*480u);
    assert(!flushes && availability_reads == 1 && result_reads == 1);
    samples = 0; assert(poll(4,4,1) == D3D_OK && !memory[1] && flushes == 1);
    memory[1] = 0xCDCDCDCDu;
    assert(poll(4,3,0) == D3D_OK && memory[1] == 0xCDCDCDCDu);
    assert(poll(4,0,0) == D3D_OK && memory[1] == 0xCDCDCDCDu);
    assert(poll(0,0,0) == D3D_OK && memory[0] == 0xCDCDCDCDu);
    assert(poll(4,8,0) == D3D_OK && !memory[1] && memory[2] == 0xCDCDCDCDu);

    /* Keep the adapter's compatibility behavior for unknown flag bits. */
    reset_spies(); ready = 0;
    assert(poll(4,4,2) == S_FALSE_D3D && !flushes && !result_reads);
    assert(poll(4,4,3) == S_FALSE_D3D && flushes == 1 && !result_reads);

    /* A new BEGIN invalidates the completed state until its matching END. */
    reset_spies(); ready = 1; issue(2);
    assert(q.issued && !q.ended && begins == 2);
    assert(poll(4,4,1) == D3D_OK && !memory[1]);
    assert(!flushes && !availability_reads && !result_reads);
    issue(1); ready = 0;
    assert(q.ended && !q.issued && poll(4,4,0) == S_FALSE_D3D);
    ready = 1; samples = 1; assert(poll(4,4,0) == D3D_OK && memory[1] == 640u*480u);
    issue(1); issue(0); issue(4); assert(ends == 2 && begins == 2);
    issue(3); assert(begins == 3 && ends == 3 && q.ended && !q.issued);
    q.ended = 0; reset_spies();
    assert(poll(0,0,1) == D3D_OK && !flushes && !availability_reads && !result_reads);

    memset(&q,0,sizeof q); q.dev = &dev; q.type = 8;
    reset_spies(); assert(qry_GetDataSize() == 4);
    assert(poll(4,4,1) == D3D_OK && memory[1] == 1 && !waits && !flushes);
    issue(2); assert(!q.fence && !q.ended);
    issue(1); assert(q.fence == 101 && q.ended && fences == 1);
    reset_spies(); wait_result = GL_TIMEOUT_EXPIRED; expected_wait_flags = 0;
    assert(poll(4,4,0) == S_FALSE_D3D && waits == 1 && !wait_flags && memory[1] == 0xCDCDCDCDu);
    expected_wait_flags = GL_SYNC_FLUSH_COMMANDS_BIT;
    assert(poll(0,0,1) == S_FALSE_D3D && waits == 2 && wait_flags == 1);
    wait_result = GL_ALREADY_SIGNALED; expected_wait_flags = 0;
    assert(poll(4,4,0) == D3D_OK && memory[1] == 1 && waits == 3);
    memory[1] = 0xCDCDCDCDu;
    assert(poll(4,3,0) == D3D_OK && memory[1] == 0xCDCDCDCDu);
    assert(poll(4,0,0) == D3D_OK && memory[1] == 0xCDCDCDCDu);
    assert(poll(0,4,0) == D3D_OK && memory[0] == 0xCDCDCDCDu);
    assert(poll(0,0,2) == D3D_OK && !wait_flags);
    expected_wait_flags = 1; assert(poll(0,0,3) == D3D_OK && wait_flags == 1);
    issue(1); assert(q.fence == 102 && fences == 2 && deleted_fences == 1);
    wait_result = GL_TIMEOUT_EXPIRED;
    assert(poll(0,0,1) == S_FALSE_D3D);
    assert(!flushes && !availability_reads && !result_reads);

    memset(&q,0,sizeof q); q.type = 4; reset_spies();
    assert(qry_GetDataSize() == 16);
    assert(poll(4,16,1) == D3D_OK && memory[1] == FOURCC('C','A','C','H'));
    assert(memory[2] == 1 && memory[3] == 16 && memory[4] == 7 && memory[5] == 0xCDCDCDCDu);
    reset_spies(); assert(poll(4,15,1) == D3D_OK && memory[1] == 0xCDCDCDCDu);
    assert(poll(0,0,1) == D3D_OK && !flushes && !waits && !availability_reads && !result_reads);

    d3d_query *owned = calloc(1,sizeof *owned); assert(owned);
    owned->gl = 7; owned->fence = 102;
    query_destroy(&owned->com);
    assert(deleted_queries == 1 && deleted_fences == 2);
    puts("PASS D3D queries: nonblocking FLUSH, readiness/reset, status polls, bounded writes, event flags and query lifetime");
    return 0;
}
'''


class D3DQueryTest(unittest.TestCase):
    def test_nonblocking_query_contract(self):
        source = (ROOT / "android/host/d3d9_resource.c").read_text(encoding="utf-8")
        types = (ROOT / "android/host/d3d9_internal.h").read_text(encoding="utf-8")
        start = types.index("typedef struct d3d_query {")
        query_type = types[start:types.index("} d3d_query;", start) + len("} d3d_query;")]
        bodies = "".join(function(source, name) for name in (
            "static void query_destroy(", "COM_METHOD(qry, GetDataSize,", "COM_METHOD(qry, Issue,",
            "COM_METHOD(qry, GetData,"))
        compile_probe("d3d_query", HARNESS, {"query_type.h": query_type, "query_bodies.h": bodies})


if __name__ == "__main__":
    unittest.main()
