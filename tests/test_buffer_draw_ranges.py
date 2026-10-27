"""Run production Lock/Unlock, dirty-page uploads, and draw bounds with mock GL."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function


UPLOAD_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned GLenum, GLuint;
typedef intptr_t GLintptr, GLsizeiptr;
typedef struct {
    uint32_t size, usage, shadow, dirty_lo, dirty_hi;
    GLuint gl;
    int discard_pending, overwrite_pending;
    uint8_t *dirty_pages;
    uint32_t page_count, dirty_page_count;
    int locks;
    uint32_t bounds_count;
} d3d_buffer;
#define BUFFER_PAGE_SIZE 4096u
#define GL_COPY_WRITE_BUFFER 0x8F37u
#define GL_DYNAMIC_DRAW 0x88E8u
#define GL_STATIC_DRAW 0x88E4u
#define GL_MAP_WRITE_BIT 2u
#define GL_MAP_UNSYNCHRONIZED_BIT 0x20u
#define GL_MAP_INVALIDATE_RANGE_BIT 4u
#define D3DUSAGE_DYNAMIC 0x200u
#define D3DLOCK_READONLY 0x10u
#define D3DLOCK_DISCARD 0x2000u
#define D3DLOCK_NOOVERWRITE 0x1000u
#define D3DERR_INVALIDCALL 0x8876086Cu
#define D3D_OK 0u
static uint8_t memory[65536], gpu[16384];
#define GPTR(va) (memory + (va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
static d3d_buffer buffer;
static uint32_t args[5];
#define ARG(n) args[n]
#define BUF (&buffer)
#define COM_METHOD(iface, name, argc) static uint32_t iface##_##name(void)
static int fail_allocation;
static void *page_calloc(size_t count, size_t size) { return fail_allocation ? NULL : calloc(count, size); }
#define calloc page_calloc
static unsigned binds, uploads, orphans, maps, total_bytes, last_offset, last_length;
static void glBindBuffer(GLenum target, GLuint object) { assert(target == GL_COPY_WRITE_BUFFER && object == 7); ++binds; }
static void glBufferData(GLenum target, GLsizeiptr size, const void *data, GLenum usage) {
    assert(target == GL_COPY_WRITE_BUFFER && size == buffer.size && usage == GL_DYNAMIC_DRAW);
    if (data) { memcpy(gpu, data, (size_t)size); total_bytes += (unsigned)size; ++uploads; }
    else { memset(gpu, 0xCD, (size_t)size); ++orphans; }
}
static void glBufferSubData(GLenum target, GLintptr offset, GLsizeiptr size, const void *data) {
    assert(target == GL_COPY_WRITE_BUFFER && offset >= 0 && size > 0 && offset + size <= buffer.size);
    assert(data == GPTR(buffer.shadow) + offset);
    memcpy(gpu + offset, data, (size_t)size); ++uploads; total_bytes += (unsigned)size;
    last_offset = (unsigned)offset; last_length = (unsigned)size;
}
static void *glMapBufferRange(GLenum target, GLintptr offset, GLsizeiptr size, unsigned flags) {
    (void)target; (void)offset; (void)size; (void)flags; ++maps; return NULL;
}
static int glUnmapBuffer(GLenum target) { (void)target; assert(!"deferred pages must never map"); return 1; }
static void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi);
#include "dirty.h"
#include "flush.h"
#include "range.h"
#include "lock.h"
#include "unlock.h"
static void setup(void) {
    free(buffer.dirty_pages);
    memset(&buffer, 0, sizeof buffer);
    buffer.size = 3 * BUFFER_PAGE_SIZE + 97; buffer.usage = D3DUSAGE_DYNAMIC;
    buffer.shadow = 4096; buffer.gl = 7; buffer.dirty_lo = UINT32_MAX;
    for (unsigned i = 0; i < buffer.size; ++i) memory[buffer.shadow + i] = (uint8_t)(i * 7u + 1u);
    memset(gpu, 0xA5, sizeof gpu);
    binds = uploads = orphans = maps = total_bytes = last_offset = last_length = 0; fail_allocation = 0;
}
static void lock(uint32_t offset, uint32_t size, uint32_t flags) {
    args[1] = offset; args[2] = size; args[3] = 64; args[4] = flags;
    assert(buf_Lock() == D3D_OK && MEM32(64) == buffer.shadow + offset);
}
static void unlock(void) { assert(buf_Unlock() == D3D_OK); }
int main(void) {
    setup();buffer.bounds_count=17;lock(0,0,D3DLOCK_READONLY);unlock();assert(buffer.bounds_count==17);
    lock(1,4,D3DLOCK_NOOVERWRITE);assert(!buffer.bounds_count);unlock();
    buffer.bounds_count=19;args[1]=buffer.size+1;assert(buf_Lock()==D3DERR_INVALIDCALL && buffer.bounds_count==19);
    setup(); lock(0, 0, D3DLOCK_NOOVERWRITE); unlock();
    assert(buffer.dirty_pages && buffer.page_count == 4 && buffer.dirty_page_count == 4 && !binds);
    d3d_buffer_flush_range(&buffer, 4108, 4112);
    assert(uploads == 1 && total_bytes == 4096 && last_offset == 4096 && last_length == 4096);
    assert(buffer.dirty_page_count == 3 && gpu[4095] == 0xA5 && gpu[8192] == 0xA5);
    assert(!memcmp(gpu + 4096, GPTR(buffer.shadow + 4096), 4096));
    d3d_buffer_flush_range(&buffer, 4108, 4112); assert(uploads == 1);
    d3d_buffer_flush_range(&buffer, buffer.size - 1, buffer.size + 10);
    assert(last_offset == 12288 && last_length == 97 && buffer.dirty_page_count == 2);
    d3d_buffer_flush_range(&buffer, 1, 2); assert(buffer.dirty_page_count == 1);
    d3d_buffer_flush(&buffer); assert(!buffer.dirty_page_count && buffer.dirty_lo == UINT32_MAX && !buffer.dirty_hi);
    assert(!memcmp(gpu, GPTR(buffer.shadow), buffer.size) && total_bytes == buffer.size && !maps && !orphans);

    unsigned before = uploads;
    lock(4100, 4, D3DLOCK_NOOVERWRITE); memset(GPTR(buffer.shadow + 4100), 0xEE, 4); unlock();
    assert(buffer.dirty_page_count == 1 && uploads == before);
    d3d_buffer_flush_range(&buffer, 4100, 4104);
    assert(uploads == before + 1 && !buffer.dirty_page_count && gpu[4100] == 0xEE);
    lock(0, 0, D3DLOCK_READONLY); unlock(); assert(!buffer.dirty_page_count && uploads == before + 1);

    lock(0, 0, D3DLOCK_NOOVERWRITE); unlock();
    d3d_buffer_flush_range(&buffer, 0, 8); assert(buffer.dirty_page_count == 3);
    lock(8200, 8, D3DLOCK_DISCARD); memset(GPTR(buffer.shadow + 8200), 0x77, 8); unlock();
    assert(buffer.discard_pending && buffer.dirty_page_count == 4);
    d3d_buffer_flush_range(&buffer, 8200, 8208);
    assert(orphans == 1 && last_offset == 8192 && last_length == 4096 && buffer.dirty_page_count == 3);
    assert(gpu[8200] == 0x77 && gpu[0] == 0xCD && gpu[12288] == 0xCD);
    d3d_buffer_flush_range(&buffer, 12288, buffer.size);
    assert(orphans == 1 && !memcmp(gpu + 12288, GPTR(buffer.shadow + 12288), 97));
    d3d_buffer_flush(&buffer); assert(!memcmp(gpu, GPTR(buffer.shadow), buffer.size));

    setup(); lock(0, 0, D3DLOCK_NOOVERWRITE); lock(4100, 4, D3DLOCK_NOOVERWRITE);
    unlock(); assert(buffer.locks == 1 && !binds); unlock(); assert(!buffer.locks && !binds);
    d3d_buffer_flush_range(&buffer, 0, 1); assert(buffer.dirty_page_count == 3);
    lock(4097, UINT32_MAX, 0); unlock(); /* Clamp without uint32 overflow. */
    assert(buffer.dirty_page_count == 3 && !maps);
    d3d_buffer_flush(&buffer); assert(!buffer.dirty_page_count);
    args[1] = buffer.size + 1; assert(buf_Lock() == D3DERR_INVALIDCALL && !buffer.locks);
    assert(buf_Unlock() == D3DERR_INVALIDCALL);

    setup(); fail_allocation = 1; lock(0, 0, D3DLOCK_NOOVERWRITE); unlock();
    assert(!buffer.dirty_pages && total_bytes == buffer.size && !memcmp(gpu, GPTR(buffer.shadow), buffer.size));
    assert(!maps); free(buffer.dirty_pages);
    puts("PASS deferred uploads: partial consumption, retained tails, repeat/re-dirty, READONLY, partial DISCARD, nested locks, overflow, OOM fallback");
    return 0;
}
'''

BOUNDS_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct {
    uint32_t size, format, shadow;
    int locks;
    uint32_t bounds_start,bounds_count,bounds_format,bounds_lo,bounds_hi;
} d3d_buffer;
static uint8_t memory[512];
static unsigned shadow_maps;
static int forbid_shadow;
static void *checked_pointer(uint32_t va) { assert(!forbid_shadow);++shadow_maps;return memory+va; }
#define GPTR(va) checked_pointer(va)
static unsigned full_calls, range_calls;
static uint32_t range_lo, range_hi;
static void d3d_buffer_flush(d3d_buffer *b) { (void)b; ++full_calls; }
static void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi) {
    assert(lo < hi && hi <= b->size); range_lo = lo; range_hi = hi; ++range_calls;
}
#include "bounds.h"
#include "vertices.h"
#include "stream_range.h"
#include "rebase.h"
int main(void) {
    d3d_buffer ib = {20, 101, 16}; uint32_t first, last;
    const uint16_t words[] = {99, 99, 4, 1, 7, 99}; memcpy(GPTR(16), words, sizeof words);
    assert(draw_vertex_bounds(&ib, NULL, 0, 0, 3, 1, UINT32_MAX, 2, &first, &last));
    assert(first == 0 && last == 6);
    assert(!draw_vertex_bounds(&ib, NULL, 0, 0, 3, 1, UINT32_MAX - 1, 2, &first, &last));
    assert(!draw_vertex_bounds(&ib, NULL, 0, 0, 3, 1, 0, UINT32_MAX, &first, &last));
    assert(!draw_vertex_bounds(&ib, NULL, 0, 0, UINT32_MAX, 1, 0, 0, &first, &last));
    assert(!draw_vertex_bounds(NULL, NULL, 0, 0, 3, 1, 0, 0, &first, &last));
    assert(draw_vertex_bounds(NULL, NULL, 0, 8, 5, 0, 0, 0, &first, &last) && first == 8 && last == 12);
    assert(!draw_vertex_bounds(NULL, NULL, 0, UINT32_MAX, 2, 0, 0, 0, &first, &last));
    assert(!draw_vertex_bounds(NULL, NULL, 0, 0, 0, 0, 0, 0, &first, &last));
    uint8_t unaligned[13]; const uint32_t indices[] = {1000, 3, 60000}; memcpy(unaligned + 1, indices, 12);
    assert(draw_vertex_bounds(NULL, unaligned + 1, 1, 0, 3, 1, 2, 0, &first, &last));
    assert(first == 5 && last == 60002);
    uint32_t overflow = UINT32_MAX;
    assert(!draw_vertex_bounds(NULL, &overflow, 1, 0, 1, 1, 1, 0, &first, &last));
    ib.format = 102; ib.size = 12; memcpy(GPTR(16), indices, 12);
    assert(draw_vertex_bounds(&ib, NULL, 0, 0, 2, 1, 0, 1, &first, &last) && first == 3 && last == 60000);

    d3d_buffer repeat={12,101,16};memcpy(GPTR(16),words,sizeof words);shadow_maps=0;
    assert(draw_vertex_bounds(&repeat,NULL,0,0,3,1,0,2,&first,&last) && first==1 && last==7 && shadow_maps==1);
    forbid_shadow=1;
    assert(draw_vertex_bounds(&repeat,NULL,0,0,3,1,UINT32_MAX,2,&first,&last) && first==0 && last==6 && shadow_maps==1);
    assert(!draw_vertex_bounds(&repeat,NULL,0,0,3,1,UINT32_MAX-1,2,&first,&last));
    assert(!draw_vertex_bounds(&repeat,NULL,0,0,3,1,0,UINT32_MAX,&first,&last));
    repeat.size=8;assert(!draw_vertex_bounds(&repeat,NULL,0,0,3,1,0,2,&first,&last));repeat.size=12;
    forbid_shadow=0;
    assert(draw_vertex_bounds(&repeat,NULL,0,0,2,1,0,2,&first,&last) && first==1 && last==4 && shadow_maps==2);
    repeat.format=102;memcpy(GPTR(16),indices,12);shadow_maps=0;
    assert(draw_vertex_bounds(&repeat,NULL,0,0,2,1,0,0,&first,&last) && first==3 && last==1000 && shadow_maps==1);
    repeat.locks=1;repeat.bounds_count=0;
    assert(draw_vertex_bounds(&repeat,NULL,0,0,2,1,0,0,&first,&last) && !repeat.bounds_count);
    uint32_t changed[]={8,9};memcpy(GPTR(16),changed,sizeof changed);
    assert(draw_vertex_bounds(&repeat,NULL,0,0,2,1,0,0,&first,&last) && first==8 && last==9 && !repeat.bounds_count);

    d3d_buffer vb = {2048, 0, 0};
    buffer_flush_vertices(&vb, 20, 32, 12, 2, 4, 1); assert(range_lo == 84 && range_hi == 160);
    buffer_flush_vertices(&vb, 8, 0, 12, 2, 4, 1); assert(range_lo == 32 && range_hi == 68);
    buffer_flush_vertices(&vb, 16, 48, 4, 0, 7, 1); assert(range_lo == 16 && range_hi == 356); /* 8 instances, divisor1 */
    assert(range_calls == 3);
    buffer_flush_vertices(&vb, 20, 32, 12, 2, 4, 0); assert(full_calls == 1);
    buffer_flush_vertices(&vb, 2040, 32, 12, 0, 1, 1); assert(full_calls == 2);
    buffer_flush_vertices(&vb, UINT32_MAX, UINT32_MAX, 16, UINT32_MAX, UINT32_MAX, 1); assert(full_calls == 3);
    uint32_t lo, bytes; int32_t base;
    assert(draw_stream_range(8192, 12, 32, 28, 90, 93, &lo, &bytes) && lo == 2892 && bytes == 124);
    assert(draw_rebase((uint32_t)-10, 90, 1, &base) && base == -100);
    const uint32_t raw[] = {100, 103, 101};
    for (unsigned i = 0; i < 3; ++i) for (uint32_t attr = 0; attr <= 24; attr += 12) {
        uint64_t original = 12u + ((int64_t)raw[i] - 10) * 32u + attr;
        uint64_t compact = lo + ((int64_t)raw[i] + base) * 32u + attr;
        uint64_t static_biased = 12u + 90u * 32u + ((int64_t)raw[i] + base) * 32u + attr;
        assert(original == compact && original == static_biased);
    }
    assert(draw_stream_range(8192, 8, 16, 8, 0, 2, &lo, &bytes) && lo == 8 && bytes == 40); /* Instance stream */
    assert(draw_stream_range(8192, 20, 32, 28, 5, 7, &lo, &bytes) && lo == 180 && bytes == 92);
    assert(draw_rebase(0, 5, 0, &base) && !base); /* Arrays become start0. */
    for (uint32_t i = 0; i < 3; ++i) assert(20u + (5u + i) * 32u == lo + i * 32u);
    assert(!draw_stream_range(8192, 0, 0, 16, 0, 1, &lo, &bytes));
    assert(!draw_stream_range(8192, 0, 32, 0, 0, 1, &lo, &bytes));
    assert(!draw_stream_range(8192, 0, 32, 16, 8, 7, &lo, &bytes));
    assert(!draw_stream_range(64, 0, 32, 16, 0, 2, &lo, &bytes));
    assert(!draw_stream_range(UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, UINT32_MAX, &lo, &bytes));
    assert(!draw_rebase(0, 0x80000001u, 1, &base));
    assert(!draw_rebase(0x80000000u, 1, 1, &base));
    puts("PASS draw extents: indexed16/32, signed base, UP unaligned indices, overflow, multiple streams, tight stride, instancing, safe fallback");
    puts("PASS transient address equivalence: mixed static/local streams, signed base, arrays, instances, stride and GLint limits");
    return 0;
}
'''

LIFECYCLE_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
typedef unsigned GLuint;
typedef struct {int unused;} void_com_object;
typedef struct {GLuint gl;uint32_t shadow;void *dirty_pages;} d3d_buffer;
typedef struct {GLuint buffer;} attr_state;
#define FB_UNKNOWN UINT32_MAX
static attr_state attr_cache[16];
static GLuint elem_buffer;
static unsigned deletes,shadows,freed;
static void *live[6];
static void *allocate(unsigned slot,size_t n){assert(slot<6&&!live[slot]);return live[slot]=malloc(n);}
static void release(void*p){
 if(!p)return;
 for(unsigned i=0;i<6;++i)if(live[i]==p){live[i]=NULL;++freed;free(p);return;}
 assert(!"untracked/double free");
}
#define free release
#include "forget.h"
static void glDeleteBuffers(int count,const GLuint*names){
 assert(count==1&&*names==7&&elem_buffer==FB_UNKNOWN);
 for(unsigned i=0;i<16;++i)assert(attr_cache[i].buffer!=7);
 ++deletes;
}
static void void_gfree(uint32_t p){assert(p==100||p==200);++shadows;}
#include "destroy.h"
int main(void){
 for(unsigned round=0;round<2;++round){
  /* Reusing a GL name must not inherit an old vertex/element binding cache. */
  d3d_buffer*b=allocate(round*2,sizeof*b);assert(b);
  *b=(d3d_buffer){7,100+round*100,allocate(round*2+1,8)};
  for(unsigned i=0;i<16;++i)attr_cache[i].buffer=(i&1)?8:7;
  elem_buffer=7;buffer_destroy((void_com_object*)b);
  assert(deletes==round+1&&shadows==round+1&&freed==(round+1)*2);
  for(unsigned i=0;i<16;++i)assert(attr_cache[i].buffer==((i&1)?8:FB_UNKNOWN));
 }
 d3d_gl_forget_buffer(99);assert(elem_buffer==FB_UNKNOWN&&attr_cache[1].buffer==8);
 d3d_buffer*empty=allocate(4,sizeof*empty);assert(empty);*empty=(d3d_buffer){0,0,NULL};buffer_destroy((void_com_object*)empty);
 assert(deletes==2&&shadows==2&&freed==5);
 for(unsigned i=0;i<6;++i)assert(!live[i]);
 puts("PASS actual buffer destruction: selective vertex/element cache invalidation before GL deletion, GL name reuse, shadow/pages/object freed once, empty object");return 0;
}
'''


class BufferDrawRangesTest(unittest.TestCase):
    def test_dirty_pages_and_real_lock_contract(self):
        resource = (ROOT / "android/host/d3d9_resource.c").read_text(encoding="utf-8")
        compile_probe("buffer_draw_ranges", UPLOAD_HARNESS, {
            "dirty.h": function(resource, "static void buffer_dirty_pages("),
            "flush.h": function(resource, "void d3d_buffer_flush("),
            "range.h": function(resource, "void d3d_buffer_flush_range(d3d_buffer *b, uint32_t lo, uint32_t hi)\n{"),
            "lock.h": function(resource, "COM_METHOD(buf, Lock, 5)"),
            "unlock.h": function(resource, "COM_METHOD(buf, Unlock, 1)"),
        })

    def test_real_draw_bounds_helpers(self):
        gl = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
        compile_probe("buffer_draw_bounds", BOUNDS_HARNESS, {
            "bounds.h": function(gl, "static int draw_vertex_bounds("),
            "vertices.h": function(gl, "static void buffer_flush_vertices("),
            "stream_range.h": function(gl, "static int draw_stream_range("),
            "rebase.h": function(gl, "static int draw_rebase("),
        })

    def test_buffer_destruction_and_gl_name_reuse(self):
        gl = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
        resource = (ROOT / "android/host/d3d9_resource.c").read_text(encoding="utf-8")
        compile_probe("buffer_lifecycle", LIFECYCLE_HARNESS, {
            "forget.h": function(gl, "void d3d_gl_forget_buffer("),
            "destroy.h": function(resource, "static void buffer_destroy("),
        })


if __name__ == "__main__":
    unittest.main()
