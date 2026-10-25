"""Execute production sparse remap/gather and the real draw routing with tracked GL data.

Every probe runs twice: without GL_EXT_buffer_storage (per-draw glBufferData
stores) and with it (the persistently mapped streaming ring, as on the tablet).
"""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef RING
#error RING selects GL_EXT_buffer_storage (1) or its absence (0)
#endif
typedef unsigned GLuint,GLenum,GLbitfield;
typedef int GLint,GLsizei;
typedef unsigned char GLboolean,GLubyte;
typedef intptr_t GLsizeiptr,GLintptr;
typedef uint64_t GLuint64;
typedef struct probe_sync *GLsync;
#define GL_FALSE 0
#define GL_TRUE 1
#define GL_FLOAT 1
#define GL_UNSIGNED_BYTE 2
#define GL_SHORT 3
#define GL_UNSIGNED_SHORT 4
#define GL_UNSIGNED_INT_2_10_10_10_REV 5
#define GL_INT_2_10_10_10_REV 6
#define GL_HALF_FLOAT 7
#define GL_UNSIGNED_INT 8
#define GL_COPY_WRITE_BUFFER 9
#define GL_STREAM_DRAW 10
#define GL_ARRAY_BUFFER 11
#define GL_ELEMENT_ARRAY_BUFFER 12
#define GL_EXTENSIONS 13
#define GL_SYNC_GPU_COMMANDS_COMPLETE 14
#define GL_ALREADY_SIGNALED 15
#define GL_CONDITION_SATISFIED 16
#define GL_WAIT_FAILED 17
#define GL_SYNC_FLUSH_COMMANDS_BIT 1u
#define GL_MAP_WRITE_BIT 0x2u
#define GL_MAP_PERSISTENT_BIT_EXT 0x40u
#define GL_MAP_COHERENT_BIT_EXT 0x80u
#define FB_UNKNOWN UINT32_MAX
typedef void (*PFNGLBUFFERSTORAGEEXTPROC)(GLenum,GLsizeiptr,const void*,GLbitfield);
typedef void (*egl_proc)(void);
static uint8_t memory[16*1024*1024];
#define GPTR(p) (memory+(uint32_t)(p))
typedef struct {uint32_t size,format,shadow;GLuint gl;uint8_t *dirty_pages;int locks;} d3d_buffer;
typedef struct {uint16_t stream,offset;uint8_t type,method,usage,usage_index;} d3d_vertex_element;
typedef struct {struct {void *indices,*streams[16];uint32_t stream_freq[16],stream_stride[16],stream_offset[16];} st;} d3d_device;
typedef struct {GLuint buffer;GLint size;GLenum type;GLboolean norm;GLsizei stride;uintptr_t offset;GLuint divisor;} attr_state;
static attr_state attr_cache[16];
static int attr_cache_ready;
static GLuint stream_vbos[16],up_ibo,up_vbo,enabled_attribs,elem_buffer=FB_UNKNOWN;
static uint64_t vb_upload_calls,vb_upload_bytes,vb_upload_frame_bytes,vb_upload_peak_bytes,vb_sparse_calls,vb_sparse_saved;
static int fail_alloc,allocations;
static void *probe_realloc(void*p,size_t n){++allocations;if(fail_alloc&&allocations==fail_alloc)return NULL;return realloc(p,n);}
static void *probe_calloc(size_t n,size_t size){++allocations;if(fail_alloc&&allocations==fail_alloc)return NULL;return calloc(n,size);}
/* The tracked GL: buffer storage the draws read back, by name. */
static struct {uint8_t *data;size_t size;} gpu[64];
static GLuint copy_bound,array_bound,element_bound,next_name=16;
static unsigned uploads,draws,index_uploads,flushes,storages,maps,unmaps,fences,sync_waits,deleted_syncs,ring_logs,range_draws;
static uintptr_t last_indices;
static void glGenBuffers(int n,GLuint*out){assert(n==1&&next_name<64);*out=next_name++;}
static void glDeleteBuffers(int n,const GLuint*names){assert(n==1&&*names<64);free(gpu[*names].data);gpu[*names].data=NULL;gpu[*names].size=0;}
static void glBindBuffer(GLenum target,GLuint b){assert(b<64);if(target==GL_COPY_WRITE_BUFFER)copy_bound=b;else if(target==GL_ARRAY_BUFFER)array_bound=b;else{assert(target==GL_ELEMENT_ARRAY_BUFFER);element_bound=b;}}
static void glBufferData(GLenum target,uint32_t n,const void*p,GLenum usage){
 assert(target==GL_COPY_WRITE_BUFFER&&usage==GL_STREAM_DRAW&&copy_bound&&n&&p);
 free(gpu[copy_bound].data);gpu[copy_bound].data=malloc(n);assert(gpu[copy_bound].data);
 memcpy(gpu[copy_bound].data,p,n);gpu[copy_bound].size=n;++uploads;if(copy_bound==up_ibo)++index_uploads;
}
static const GLubyte *glGetString(GLenum name){
 assert(name==GL_EXTENSIONS);
 return (const GLubyte*)(RING?"GL_OES_texture_npot GL_EXT_buffer_storage GL_KHR_debug":"GL_OES_texture_npot GL_KHR_debug");
}
static GLenum glGetError(void){return 0;}
/* GL_EXT_buffer_storage: an immutable store; the coherent persistent mapping is the store itself. */
static void buffer_storage(GLenum target,GLsizeiptr size,const void*data,GLbitfield flags){
 assert(target==GL_COPY_WRITE_BUFFER&&copy_bound&&size>0&&!data&&flags==(GL_MAP_WRITE_BIT|GL_MAP_PERSISTENT_BIT_EXT|GL_MAP_COHERENT_BIT_EXT));
 free(gpu[copy_bound].data);gpu[copy_bound].data=calloc(1,(size_t)size);assert(gpu[copy_bound].data);gpu[copy_bound].size=(size_t)size;++storages;
}
static egl_proc eglGetProcAddress(const char*name){assert(RING);assert(!strcmp(name,"glBufferStorageEXT"));return (egl_proc)buffer_storage;}
static void *glMapBufferRange(GLenum target,GLintptr offset,GLsizeiptr length,GLbitfield access){
 assert(target==GL_COPY_WRITE_BUFFER&&!offset&&(size_t)length==gpu[copy_bound].size);
 assert(access==(GL_MAP_WRITE_BIT|GL_MAP_PERSISTENT_BIT_EXT|GL_MAP_COHERENT_BIT_EXT));++maps;return gpu[copy_bound].data;
}
static GLboolean glUnmapBuffer(GLenum target){assert(target==GL_COPY_WRITE_BUFFER&&gpu[copy_bound].data);++unmaps;return GL_TRUE;}
static GLsync glFenceSync(GLenum condition,GLbitfield flags){assert(condition==GL_SYNC_GPU_COMMANDS_COMPLETE&&!flags);return (GLsync)(uintptr_t)++fences;}
static GLenum glClientWaitSync(GLsync sync,GLbitfield flags,GLuint64 timeout){assert(sync&&flags==GL_SYNC_FLUSH_COMMANDS_BIT&&timeout);++sync_waits;return GL_CONDITION_SATISFIED;}
static void glDeleteSync(GLsync sync){assert(sync);++deleted_syncs;}
static void void_log(const char*fmt,...){assert(strstr(fmt,"[gl] streaming ring: ")==fmt);++ring_logs;}
#include "ring.h"
#define realloc probe_realloc
#define calloc probe_calloc
#include "sparse.h"
#undef realloc
#undef calloc
#include "ranges.h"
static d3d_device *active;
static uint32_t *reference_indices,reference_count,reference_instances,reference_base;
static d3d_vertex_element elements[3];
static const d3d_vertex_element *find_element(d3d_device*d,int usage,int index){(void)d;(void)index;return &elements[usage];}
static void d3d_buffer_flush(d3d_buffer*b){
 free(gpu[b->gl].data);gpu[b->gl].data=malloc(b->size);assert(gpu[b->gl].data);
 memcpy(gpu[b->gl].data,GPTR(b->shadow),b->size);gpu[b->gl].size=b->size;++flushes;
}
static void d3d_buffer_flush_range(d3d_buffer*b,uint32_t lo,uint32_t hi){assert(lo<hi&&hi<=b->size);d3d_buffer_flush(b);}
#include "vertices.h"
#include "formats.h"
#include "upload.h"
static void glVertexAttrib4f(GLuint slot,float x,float y,float z,float w){(void)slot;(void)x;(void)y;(void)z;(void)w;assert(0);}
static void glVertexAttribPointer(GLuint slot,GLint n,GLenum type,GLboolean norm,GLsizei stride,const void*p){
 (void)n;(void)type;(void)norm;assert(slot<3&&array_bound);attr_cache[slot].buffer=array_bound;attr_cache[slot].stride=stride;attr_cache[slot].offset=(uintptr_t)p;
}
static void glVertexAttribDivisor(GLuint slot,GLuint divisor){assert(slot<3);attr_cache[slot].divisor=divisor;}
static void glEnableVertexAttribArray(GLuint slot){assert(slot<3);}
static void glDisableVertexAttribArray(GLuint slot){assert(slot<3);}
static void check_draw(GLsizei count,GLenum type,const void*indices,GLsizei instances,GLint base){
 assert(count==(GLsizei)reference_count&&instances==(GLsizei)reference_instances&&element_bound);
 last_indices=(uintptr_t)indices;
 const uint8_t *data=gpu[element_bound].data+(uintptr_t)indices;
 for(unsigned instance=0;instance<(unsigned)instances;++instance)for(unsigned j=0;j<(unsigned)count;++j){
  uint32_t index;if(type==GL_UNSIGNED_INT)memcpy(&index,data+4*j,4);else{assert(type==GL_UNSIGNED_SHORT);uint16_t value;memcpy(&value,data+2*j,2);index=value;}
  int64_t fetched=(int64_t)index+base,original=(int64_t)reference_indices[j]+(int32_t)reference_base;assert(fetched>=0&&original>=0);
  for(unsigned slot=0;slot<3;++slot){
   unsigned stream=elements[slot].stream;d3d_buffer*b=active->st.streams[stream];
   uint64_t vertex=attr_cache[slot].divisor?instance:(uint64_t)fetched;
   uint64_t old_vertex=attr_cache[slot].divisor?instance:(uint64_t)original;
   uint64_t address=attr_cache[slot].offset+vertex*(uint32_t)attr_cache[slot].stride;
   uint64_t old=active->st.stream_offset[stream]+elements[slot].offset+old_vertex*active->st.stream_stride[stream];
   assert(address+8<=gpu[attr_cache[slot].buffer].size&&old+8<=b->size);
   assert(!memcmp(gpu[attr_cache[slot].buffer].data+address,GPTR(b->shadow)+old,8));
  }
 }
 ++draws;
}
static GLenum gl_mode(uint32_t p){return p;}
static void glDrawElementsBaseVertex(GLenum mode,GLsizei n,GLenum type,const void*p,GLint base){assert(mode==4);check_draw(n,type,p,1,base);}
static void glDrawRangeElementsBaseVertex(GLenum mode,GLuint lo,GLuint hi,GLsizei n,GLenum type,const void*p,GLint base){
 uint32_t minimum=UINT32_MAX,maximum=0;const uint8_t *data=gpu[element_bound].data+(uintptr_t)p;
 for(GLsizei i=0;i<n;++i){uint32_t v;if(type==GL_UNSIGNED_INT)memcpy(&v,data+4*i,4);else{uint16_t s;memcpy(&s,data+2*i,2);v=s;}
  if(v<minimum)minimum=v;if(v>maximum)maximum=v;}
 assert(lo==minimum&&hi==maximum);++range_draws;glDrawElementsBaseVertex(mode,n,type,p,base);
}
static void glDrawElementsInstancedBaseVertex(GLenum mode,GLsizei n,GLenum type,const void*p,GLsizei instances,GLint base){assert(mode==4);check_draw(n,type,p,instances,base);}
static void glDrawElements(GLenum mode,GLsizei n,GLenum type,const void*p){(void)mode;(void)n;(void)type;(void)p;assert(0);}
static void glDrawArrays(GLenum mode,GLint first,GLsizei n){(void)mode;(void)first;(void)n;assert(0);}
static void glDrawArraysInstanced(GLenum mode,GLint first,GLsizei n,GLsizei instances){(void)mode;(void)first;(void)n;(void)instances;assert(0);}
static int actual_draw(d3d_device*d,uint32_t vertex_count,uint32_t base_vertex,uint32_t start_index){
 int attr_count=3,attr_usage[3]={0,1,2},attr_index[3]={0};
 uint32_t start_vertex=0,primitive=4,up_stride=0;int indexed=1,up_index32=0;
 const void*up_vertices=NULL,*up_indices=NULL;(void)up_stride;
#include "streams.h"
#include "draw.h"
 return 1;
}
static void cleanup_sparse(void){
#include "destroy.h"
}
static void setup(d3d_device*d,d3d_buffer buffers[4],int wide,int instances,uint32_t base,uint32_t *indices,uint32_t count){
 memset(d,0,sizeof*d);memset(buffers,0,4*sizeof*buffers);
 for(unsigned i=0;i<3;++i){
  buffers[i]=(d3d_buffer){6*1024*1024,0,4096+i*4*1024*1024,1+i,(uint8_t*)1,0};
  if(i)buffers[i].size=2*1024*1024;
  d->st.streams[i]=&buffers[i];d->st.stream_offset[i]=i*12;d->st.stream_stride[i]=i==0?8:16;
  elements[i]=(d3d_vertex_element){(uint16_t)i,(uint16_t)(i==0?0:4),1,0,(uint8_t)i,0};
  for(uint32_t j=0;j<buffers[i].size;++j)GPTR(buffers[i].shadow)[j]=(uint8_t)((j*17u+i*31u)^(j>>12));
 }
 buffers[1].dirty_pages=NULL; /* Static per-vertex stream must be gathered too. */
 if(instances){d->st.stream_freq[0]=0x40000002;d->st.stream_freq[2]=0x80000001;}
 else d->st.stream_freq[2]=0;
 buffers[3]=(d3d_buffer){count*4+16,(uint32_t)(wide?102:101),14*1024*1024,4,NULL,0};d->st.indices=&buffers[3];
 memset(GPTR(buffers[3].shadow),0xCC,16);
 for(uint32_t i=0;i<count;++i)if(wide)memcpy(GPTR(buffers[3].shadow)+16+4*i,&indices[i],4);else{uint16_t value=(uint16_t)indices[i];memcpy(GPTR(buffers[3].shadow)+8+2*i,&value,2);}
 active=d;reference_indices=indices;reference_count=count;reference_instances=instances?2:1;reference_base=base;
}
static uint64_t source_hash(void){uint64_t hash=1469598103934665603ull;for(size_t i=0;i<sizeof memory;++i)hash=(hash^memory[i])*1099511628211ull;return hash;}
int main(void){
 _putenv("VOID_NO_RING=");
 d3d_device d;d3d_buffer buffers[4];uint32_t values[7]={1003,1000,1999,1003,1999,1000,1003};
 setup(&d,buffers,1,1,(uint32_t)-1000,values,7);unsigned before=uploads;
 uint8_t old_ib[44];memcpy(old_ib,GPTR(buffers[3].shadow),sizeof old_ib);
 uint64_t original_source=source_hash();assert(actual_draw(&d,7,(uint32_t)-1000,4));assert(source_hash()==original_source);
 assert(vb_sparse_calls==1&&sparse_indices[0]==0&&sparse_indices[1]==1&&sparse_indices[2]==2);
 assert(sparse_indices[3]==0&&sparse_indices[4]==2&&sparse_vertices[0]==3&&sparse_vertices[2]==999);
 assert(!memcmp(old_ib,GPTR(buffers[3].shadow),sizeof old_ib)&&attr_cache[2].divisor==1);
 /* 8000 dirty bytes against 24 + 44 gathered bytes, the second stream 16-byte aligned. */
 assert(vb_sparse_saved==8000-76&&vb_upload_calls==3&&vb_upload_bytes==96&&vb_upload_frame_bytes==96);
#if RING
 /* Gather, instance stream and remapped IB all in this frame's ring segment. */
 assert(uploads==before&&!index_uploads&&storages==1&&maps==1&&ring_logs==1&&ring_buffer&&element_bound==ring_buffer);
 assert(attr_cache[0].buffer==ring_buffer&&attr_cache[0].offset==0&&attr_cache[1].buffer==ring_buffer&&attr_cache[1].offset==32+4);
 assert(attr_cache[2].buffer==ring_buffer&&attr_cache[2].offset==80+4&&last_indices==112&&ring_used==140);
#else
 assert(uploads==before+4&&index_uploads==1&&!storages&&!ring_buffer&&ring_state==-1&&!ring_logs);
 assert(attr_cache[1].buffer==stream_vbos[1]&&attr_cache[2].buffer==stream_vbos[2]&&element_bound==up_ibo&&gpu[up_ibo].size==28&&!last_indices);
#endif
 uint64_t optimized=vb_sparse_calls;
 /* 16-bit source, negative base and raw maximum are ordinary keys. */
 uint32_t short_values[3]={5,65535,5};setup(&d,buffers,0,0,(uint32_t)-5,short_values,3);
 assert(actual_draw(&d,3,(uint32_t)-5,4)&&vb_sparse_calls==optimized+1);
 assert(range_draws==1);
#if RING
 /* Present: fence the segment, take the next; a segment is reused only after its fence. */
 ring_frame_end();assert(ring_segment==1&&!ring_used&&fences==1&&!sync_waits);
 ring_frame_end();ring_frame_end();assert(ring_segment==0&&fences==3&&sync_waits==1&&deleted_syncs==1);
 ring_frame_end();assert(ring_segment==1&&fences==4&&sync_waits==2&&deleted_syncs==2);
#else
 ring_frame_end();assert(!fences&&!sync_waits&&ring_state==-1);
#endif
 /* Dense topology rejects the optional path before touching scratch. */
 uint32_t dense[3]={0,1,2};setup(&d,buffers,0,1,0,dense,3);optimized=vb_sparse_calls;
 assert(actual_draw(&d,3,0,4)&&vb_sparse_calls==optimized);
#if RING
 assert(attr_cache[0].buffer==ring_buffer&&attr_cache[0].offset==(16u<<20)&&attr_cache[1].buffer==buffers[1].gl);
 /* A frame that outgrows its segment uploads the rest the old way. */
 setup(&d,buffers,1,1,(uint32_t)-1000,values,7);ring_used=(16u<<20)-80u;before=uploads;optimized=vb_sparse_calls;
 assert(actual_draw(&d,7,(uint32_t)-1000,4)&&vb_sparse_calls==optimized+1&&uploads==before+2&&index_uploads==1);
 assert(attr_cache[0].buffer==ring_buffer&&attr_cache[0].offset==(16u<<20)+(16u<<20)-80u);
 assert(attr_cache[1].buffer==ring_buffer&&attr_cache[1].offset==(16u<<20)+(16u<<20)-80u+36u);
 assert(attr_cache[2].buffer==stream_vbos[2]&&attr_cache[2].offset==4&&element_bound==up_ibo&&!last_indices);
#endif
 /* Non-sparse ranges stay raw even when dynamic vertices rebase the draw. */
 uint32_t shifted[3]={1003,1004,1005};unsigned ranged=range_draws;
 for(unsigned i=0;i<3;++i){uint32_t base=i==0?13u:(uint32_t)-1000;
  setup(&d,buffers,i==0,0,base,shifted,3);
  if(i==2)for(unsigned s=0;s<3;++s)buffers[s].dirty_pages=NULL;
  optimized=vb_sparse_calls;assert(actual_draw(&d,3,base,4)&&vb_sparse_calls==optimized);
 }
 assert(range_draws==ranged+3);
 /* Each allocation failure must leave the existing draw valid. */
 const int needed=RING?2:3; /* remap scratch, span map, and gather scratch when there is no ring */
 for(int failure=1;failure<=needed+1;++failure){
  cleanup_sparse();setup(&d,buffers,1,1,(uint32_t)-1000,values,7);
  allocations=0;fail_alloc=failure;optimized=vb_sparse_calls;
  assert(actual_draw(&d,7,(uint32_t)-1000,4)&&vb_sparse_calls==optimized+(failure>needed));
  assert(allocations==(failure>needed?needed:failure));fail_alloc=0;
 }
 /* Unsupported overlapping attributes also fall back, preserving fetches. */
 setup(&d,buffers,1,1,(uint32_t)-1000,values,7);d.st.stream_stride[1]=8;optimized=vb_sparse_calls;
 assert(actual_draw(&d,7,(uint32_t)-1000,4)&&vb_sparse_calls==optimized);
 /* All 32 raw bits participate; UINT_MAX is not an empty-entry sentinel (span map and hash). */
 uint32_t extremes[3]={UINT32_MAX,UINT32_MAX-1,UINT32_MAX};
 buffers[3]=(d3d_buffer){12,102,14*1024*1024,4,NULL,0};memcpy(GPTR(buffers[3].shadow),extremes,12);
 uint32_t unique;assert(draw_sparse_indices(&buffers[3],0,3,0x80000000u,0x7FFFFFFEu,0x7FFFFFFFu,&unique));
 assert(unique==2&&sparse_indices[0]==0&&sparse_indices[1]==1&&sparse_indices[2]==0&&sparse_vertices[0]==0x7FFFFFFFu);
 assert(!sparse_hash&&draw_sparse_indices(&buffers[3],0,3,0,0,UINT32_MAX,&unique)&&sparse_hash);
 assert(unique==2&&sparse_indices[0]==0&&sparse_indices[1]==1&&sparse_indices[2]==0&&sparse_vertices[0]==UINT32_MAX&&sparse_vertices[1]==UINT32_MAX-1);
 assert(!draw_sparse_indices(&buffers[3],UINT32_MAX,3,0,0,1,&unique));
 assert(!draw_sparse_indices(&buffers[3],0,SPARSE_MAX_INDICES+1u,0,0,1,&unique));
 assert(!draw_sparse_indices(&buffers[3],0,3,0,0,1,&unique));
 uint8_t small[16];assert(!draw_sparse_gather(&buffers[0],0,4,8,1,small,8));
 assert(!draw_sparse_gather(&buffers[0],UINT32_MAX,8,8,1,small,8));
 /* More than 65535 unique references remain uint32 after remapping. */
 uint32_t *many=malloc(70000*4);assert(many);for(uint32_t i=0;i<70000;++i)many[i]=i*10;
 setup(&d,buffers,1,1,0,many,70000);d.st.stream_stride[1]=1;elements[1].offset=0; /* Test remap width independently of stream policy. */
 assert(draw_sparse_indices(&buffers[3],4,70000,0,0,699990,&unique)&&unique==70000&&sparse_indices[69999]==69999);
 unsigned unmapped=unmaps;
 free(many);cleanup_sparse();assert(!sparse_indices&&!sparse_vertices&&!sparse_hash&&!sparse_data&&!sparse_capacity&&!sparse_hash_capacity&&!sparse_data_capacity);
 assert(!sparse_map&&!sparse_map_capacity&&!sparse_map_generation);
 assert(!ring_buffer&&!ring_map&&!ring_state&&!ring_segment&&!ring_used&&unmaps==unmapped+RING);
 for(unsigned i=0;i<3;++i)assert(!ring_fence[i]);
 /* VOID_NO_RING keeps the per-draw stores even where the extension exists. */
 uint32_t at;_putenv("VOID_NO_RING=1");assert(!ring_alloc(16,&at)&&ring_state==-1);_putenv("VOID_NO_RING=");
 for(unsigned i=0;i<64;++i)free(gpu[i].data);
 printf("PASS actual sparse (%s): order/full32/negativebase/dedup, span map+hash, static+dynamic+instance streams, real attrib/IB routing, OOM/dense/overlap fallback, immutable source and teardown\n",
        RING?"streaming ring, segment rotation/fences, overflow fallback":"per-draw stores");
 return 0;
}
'''


def sparse_headers(source=None):
    source = source or (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
    ring = source[source.index("/* Per-draw uploads go to one persistently mapped buffer"):source.index("static uint32_t enabled_attribs;")]
    sparse = source[source.index("/* Sparse pooled meshes"):source.index("/* A compact immutable data store")]
    ranges = "\n".join(function(source, name) for name in
                       ("static int draw_vertex_bounds(", "static int draw_stream_range(", "static int draw_rebase("))
    start = source.index("    uint32_t instances =", source.index("int d3d_gl_draw("))
    end = source.index("    GLuint trace_query =", start)
    draw = source[source.index("    GLenum mode = gl_mode(primitive);", end):]
    draw = draw[:draw.index("    GLenum e = ")]
    destroy = function(source, "void d3d_gl_device_destroy(")
    a = destroy.index("    ring_release();")
    z = destroy.index("    vao =", a)
    return {"ring.h": ring, "sparse.h": sparse, "ranges.h": ranges,
            "vertices.h": function(source, "static void buffer_flush_vertices("),
            "formats.h": source[source.index("typedef struct { GLint size;"):source.index("static const d3d_vertex_element *find_element(")],
            "upload.h": function(source, "static void draw_buffer_upload("),
            "streams.h": source[start:end], "draw.h": draw, "destroy.h": destroy[a:z]}


def probe(name, source=None, ring=1):
    compile_probe(name + ("_ring" if ring else "_stores"), HARNESS, sparse_headers(source), extra_flags=("/DRING=%d" % ring,))


class BufferSparseTests(unittest.TestCase):
    def test_actual_sparse_helpers_and_draw_routing(self):
        for ring in (0, 1):
            with self.subTest(ring=ring):
                probe("buffer_sparse", ring=ring)

    def test_missing_base_static_gather_or_remapped_ib_is_rejected(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
        changes = [("(int64_t)raw + (int32_t)base", "(int64_t)raw + ((int32_t)base & 0)", (0, 1)),
                   ("b->dirty_pages || (sparse_count && !instanced)", "b->dirty_pages", (0, 1)),
                   ("int i32 = sparse_count || ib->format == 102;", "int i32 = ib->format == 102;", (0, 1)),
                   ("first_vertex - base_vertex", "first_vertex - draw_base", (0, 1)),
                   # The ring IB is read at its own offset, not at the store's start.
                   ("(compact ? compact_at :", "(compact ? 0u :", (1,))]
        for i, (old, new, rings) in enumerate(changes):
            self.assertIn(old, source)
            for ring in rings:
                with self.subTest(change=new, ring=ring), self.assertRaisesRegex(AssertionError, "Assertion failed"):
                    probe("buffer_sparse_negative_" + str(i), source.replace(old, new, 1), ring)


if __name__ == "__main__":
    unittest.main()
