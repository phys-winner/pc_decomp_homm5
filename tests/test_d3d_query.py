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
#include <time.h>
#include <errno.h>
#define _Thread_local __declspec(thread)
#define _Atomic
#define memory_order_acquire 0
#define memory_order_release 0
#define memory_order_relaxed 0
#define memory_order_acq_rel 0
#define atomic_load(p) (*(p))
#define atomic_load_explicit(p,o) (*(p))
#define atomic_store_explicit(p,v,o) (*(p)=(v))
#define atomic_fetch_add_explicit(p,v,o) (*(p)+=(v))
static int exchange(int *p,int v){int old=*p;*p=v;return old;}
#define atomic_exchange_explicit(p,v,o) exchange(p,v)
typedef unsigned GLenum, GLuint;
typedef uintptr_t GLsync;
typedef struct { int unused; } void_com_object;
typedef struct { struct { uint32_t viewport[4]; } st;uint32_t frame; } d3d_device;
#include "query_type.h"
#include "query_rt.h"
#define QRY_RT(q) ((d3d_query_rt *)(q))
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
static int threaded;
static int d3d_rt_threaded(void){return threaded;}
static void d3d_rt_call(void (*fn)(void *),const void *p,unsigned n){(void)n;fn((void *)p);}
static void d3d_rt_flush(void){}
static void void_log(const char *fmt,...){(void)fmt;}
static unsigned sleeps,blocking;
static uint64_t void_monotonic_ns(void){static uint64_t t;return ++t;}
static void void_blocking_begin(void){++blocking;}
static void void_blocking_end(void){}
static int nanosleep(const struct timespec *t,struct timespec *rest){assert(t->tv_nsec==50000&&rest);++sleeps;return 0;}
static d3d_device *d3d_rt_device(void);
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
static void glGenQueries(int n,GLuint *id){assert(n==1);*id=7;}
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
static d3d_device device;
static d3d_device *d3d_rt_device(void){return &device;}
int main(void) {
    device.st.viewport[2]=640;device.st.viewport[3]=480;
    d3d_query_rt x={0};d3d_query *q=&x.q;q->dev=&device;q->type=9;current=q;++query_live;
    assert(qry_GetDataSize()==4);
    reset_spies();assert(poll(4,4,1)==D3D_OK && memory[1]==0 && !availability_reads);
    issue(2);assert(q->issued&&!q->ended&&begins==1);
    issue(1);assert(!q->issued&&q->ended&&ends==1);
    reset_spies();ready=0;
    assert(poll(4,4,1)==S_FALSE_D3D && flushes==1 && availability_reads==1 && !result_reads && memory[1]==0xCDCDCDCDu);
    reset_spies();assert(poll(0,0,0)==S_FALSE_D3D&&!flushes&&!result_reads&&availability_reads==1);
    assert(poll(4,3,2)==S_FALSE_D3D&&!flushes&&!result_reads&&memory[1]==0xCDCDCDCDu);
    assert(poll(0,0,3)==S_FALSE_D3D&&flushes==1&&!result_reads);
    reset_spies();ready=1;samples=1;
    assert(poll(4,4,0)==D3D_OK&&memory[1]==640u*480u&&result_reads==1);
    samples=0;assert(poll(4,4,1)==D3D_OK&&memory[1]==640u*480u&&result_reads==1); /* one immutable GPU result per END */
    issue(2);reset_spies();assert(poll(4,4,1)==D3D_OK&&!memory[1]&&!availability_reads);issue(1);
    assert(poll(4,4,0)==D3D_OK&&!memory[1]&&result_reads==1);
    reset_spies();assert(poll(4,3,0)==D3D_OK&&memory[1]==0xCDCDCDCDu);
    assert(poll(4,0,0)==D3D_OK&&memory[1]==0xCDCDCDCDu);
    assert(poll(0,0,0)==D3D_OK&&memory[0]==0xCDCDCDCDu);
    assert(poll(4,8,0)==D3D_OK&&!memory[1]&&memory[2]==0xCDCDCDCDu);
    /* Fresh END cannot reuse the previous serial; unavailable results never hide a draw. */
    issue(2);issue(1);ready=0;reset_spies();
    for(int i=0;i<10;++i)assert(poll(4,4,1)==S_FALSE_D3D&&memory[1]==0xCDCDCDCDu);
    assert(!result_reads&&blocking==sleeps&&sleeps>=2);
    ready=1;samples=1;assert(poll(4,4,0)==D3D_OK&&memory[1]==640u*480u);
    /* Simulate the idle worker: the queue publishes before a GetData request. Real threading/GPU has a device oracle. */
    threaded=1;issue(2);issue(1);reset_spies();ready=0;
    assert(d3d_query_watch(1)&&flushes==1&&!result_reads);
    ready=1;samples=0;assert(!d3d_query_watch(2));
    unsigned reads=availability_reads;assert(poll(4,4,1)==D3D_OK&&!memory[1]&&availability_reads==reads);
    threaded=0;
    /* Destroy through the queued destructor; the bounded GL pool retains its name for reuse. */
    d3d_query_rt *owned=calloc(1,sizeof *owned);assert(owned);owned->q.type=9;++query_live;
    current=&owned->q;issue(2);issue(1);query_destroy(&owned->q.com);assert(!deleted_queries&&query_free_count==1);
    current=q;memset(&x,0,sizeof x);q->dev=&device;q->type=8;
    reset_spies();assert(poll(4,4,1)==D3D_OK&&memory[1]==1&&!waits&&!flushes);
    issue(2);assert(!q->fence);issue(1);assert(q->fence==101);
    wait_result=GL_TIMEOUT_EXPIRED;expected_wait_flags=0;reset_spies();
    assert(poll(4,4,0)==S_FALSE_D3D&&waits==1&&!flushes&&memory[1]==0xCDCDCDCDu);
    assert(poll(0,0,1)==S_FALSE_D3D&&waits==2&&flushes==1&&!wait_flags);
    wait_result=GL_ALREADY_SIGNALED;assert(poll(4,4,0)==D3D_OK&&memory[1]==1);
    reset_spies();assert(poll(4,3,0)==D3D_OK&&memory[1]==0xCDCDCDCDu);
    assert(poll(0,0,3)==D3D_OK&&!waits);issue(1);assert(q->fence==102&&deleted_fences==1);
    wait_result=GL_TIMEOUT_EXPIRED;assert(poll(0,0,1)==S_FALSE_D3D);
    memset(&x,0,sizeof x);q->type=4;reset_spies();assert(qry_GetDataSize()==16);
    assert(poll(4,16,1)==D3D_OK&&memory[1]==FOURCC('C','A','C','H')&&memory[2]==1&&memory[3]==16&&memory[4]==7&&memory[5]==0xCDCDCDCDu);
    reset_spies();assert(poll(4,15,1)==D3D_OK&&memory[1]==0xCDCDCDCDu);
    assert(poll(0,0,1)==D3D_OK&&!flushes&&!waits&&!availability_reads&&!result_reads);
    puts("PASS D3D queries: nonblocking FLUSH, immutable serial results, watch publication, bounded writes, event fences and pooled lifetime");
    return 0;
}

'''


class D3DQueryTest(unittest.TestCase):
    def test_nonblocking_query_contract(self):
        source = (ROOT / "android/host/d3d9_resource.c").read_text(encoding="utf-8")
        types = (ROOT / "android/host/d3d9_internal.h").read_text(encoding="utf-8")
        start = types.index("typedef struct d3d_query {")
        query_type = types[start:types.index("} d3d_query;", start) + len("} d3d_query;")]
        a = source.index("/* Occlusion queries borrow")
        b = source.index("static void run_query_create", a)
        c = source.index("static _Thread_local unsigned query_pending_spins", b)
        d = source.index("static const void_fn query_methods", c)
        bodies = source[a:b] + function(source, "COM_METHOD(qry, GetDataSize,") + source[c:d]
        inc = (ROOT / "android/host/d3d9_thread.inc").read_text()
        a = inc.index("typedef struct {\n    d3d_query q;")
        query_rt = inc[a:inc.index("} d3d_query_rt;", a) + len("} d3d_query_rt;")]
        compile_probe("d3d_query", HARNESS, {"query_type.h": query_type, "query_rt.h": query_rt, "query_bodies.h": bodies})



if __name__ == "__main__":
    unittest.main()
