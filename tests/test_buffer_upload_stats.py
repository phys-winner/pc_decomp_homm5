"""Verify production compact-upload accounting, with and without the streaming ring."""
import re
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <string.h>
#ifndef RING
#error RING selects GL_EXT_buffer_storage (1) or its absence (0)
#endif
typedef unsigned GLuint,GLenum,GLbitfield;
typedef unsigned char GLboolean,GLubyte;
typedef intptr_t GLsizeiptr,GLintptr;
typedef uint64_t GLuint64;
typedef struct probe_sync *GLsync;
typedef void (*PFNGLBUFFERSTORAGEEXTPROC)(GLenum,GLsizeiptr,const void*,GLbitfield);
typedef void (*egl_proc)(void);
#define GL_TRUE 1
#define GL_COPY_WRITE_BUFFER 0x8F37u
#define GL_STREAM_DRAW 0x88E0u
#define GL_EXTENSIONS 0x1F03u
#define GL_MAP_WRITE_BIT 0x0002u
#define GL_MAP_PERSISTENT_BIT_EXT 0x0040u
#define GL_MAP_COHERENT_BIT_EXT 0x0080u
#define GL_SYNC_GPU_COMMANDS_COMPLETE 0x9117u
#define GL_SYNC_FLUSH_COMMANDS_BIT 0x1u
#define GL_ALREADY_SIGNALED 0x911Au
#define GL_CONDITION_SATISFIED 0x911Cu
#define GL_WAIT_FAILED 0x911Du
static uint8_t memory[8192];
#define GPTR(p) (memory+(uint32_t)(p))
typedef struct {uint32_t shadow;void *dirty_pages;uint32_t size;GLuint gl;int locks;} d3d_buffer;
typedef struct {struct {void *streams[16];uint32_t stream_stride[16],stream_freq[16];} st;uint32_t frame;} d3d_device;
static GLuint stream_vbos[16],next_buffer=1;
static uint32_t sparse_count,sparse_bytes[16],sparse_offsets[16];
static uint8_t *sparse_data=memory;
static unsigned gl_calls,uploads,uploaded_bytes,extension_queries,ring_logs;
static GLuint bound;
static uint8_t *ring_store;
static void glGenBuffers(int n,GLuint*out){assert(n==1);*out=next_buffer++;++gl_calls;}
static void glBindBuffer(GLenum target,GLuint name){assert(target==GL_COPY_WRITE_BUFFER&&name);bound=name;++gl_calls;}
static void glBufferData(GLenum target,uint32_t size,const void*data,GLenum usage){
 assert(bound&&target==GL_COPY_WRITE_BUFFER&&size&&data&&usage==GL_STREAM_DRAW);
 ++uploads;uploaded_bytes+=size;++gl_calls;
}
static const GLubyte *glGetString(GLenum name){
 assert(name==GL_EXTENSIONS);++extension_queries;
 return (const GLubyte*)(RING?"GL_EXT_buffer_storage GL_KHR_debug":"GL_KHR_debug");
}
static void buffer_storage(GLenum target,GLsizeiptr size,const void*data,GLbitfield flags){
 assert(target==GL_COPY_WRITE_BUFFER&&bound&&size>0&&!data&&flags==(GL_MAP_WRITE_BIT|GL_MAP_PERSISTENT_BIT_EXT|GL_MAP_COHERENT_BIT_EXT));
 assert(!ring_store);ring_store=calloc(1,(size_t)size);assert(ring_store);++gl_calls;
}
static egl_proc eglGetProcAddress(const char*name){assert(RING);assert(!strcmp(name,"glBufferStorageEXT"));return (egl_proc)buffer_storage;}
static void *glMapBufferRange(GLenum target,GLintptr offset,GLsizeiptr length,GLbitfield access){
 assert(target==GL_COPY_WRITE_BUFFER&&!offset&&length>0&&access==(GL_MAP_WRITE_BIT|GL_MAP_PERSISTENT_BIT_EXT|GL_MAP_COHERENT_BIT_EXT));
 ++gl_calls;return ring_store;
}
static GLenum glGetError(void){return 0;}
static void glDeleteBuffers(int n,const GLuint*names){(void)n;(void)names;assert(0);}
static GLboolean glUnmapBuffer(GLenum target){(void)target;assert(0);return GL_TRUE;}
static GLsync glFenceSync(GLenum condition,GLbitfield flags){(void)condition;(void)flags;assert(0);return NULL;}
static GLenum glClientWaitSync(GLsync sync,GLbitfield flags,GLuint64 timeout){(void)sync;(void)flags;(void)timeout;assert(0);return GL_WAIT_FAILED;}
static void glDeleteSync(GLsync sync){(void)sync;assert(0);}
static int logs;
static char last_log[512];
static void void_log(const char*format,...){
 va_list a;va_start(a,format);vsnprintf(last_log,sizeof last_log,format,a);va_end(a);
 if(strstr(last_log,"[gl] streaming ring: ")==last_log)++ring_logs;else ++logs;
}
#include "ring_actual.h"
#include "stats_globals.h"
#include "upload_actual.h"
static void consume(d3d_device *d,uint32_t *stream_end,uint32_t *stream_bytes,uint32_t *stream_lo){
 int local_streams=1;
 if(!local_streams)assert(0);
#include "consumed_actual.h"
}
#define CLOCK_MONOTONIC 1
#define CLOCK_THREAD_CPUTIME_ID 2
struct timespec {int64_t tv_sec,tv_nsec;};
static int64_t seconds=100;
static void clock_gettime(int clock,struct timespec*out){assert(clock==1||clock==2);out->tv_sec=seconds;out->tv_nsec=0;}
static uint64_t swap_ns;
static int raster_state_valid,thunk_frames;
static void depth_trace_present(d3d_device*d){(void)d;}
static uint64_t void_lock_wait_ns(void){return 0;}
static void void_thunk_stats(uint32_t frames){thunk_frames+=(int)frames;}
static void present_stats(d3d_device*dev){
#include "present_actual.h"
}
int main(void){
 _putenv("VOID_NO_RING=");
 d3d_device d={0};d3d_buffer a={64,(void*)1,8192,7,0},b={1024,(void*)1,8192,8,0},clean={0};
 d.st.streams[0]=&a;d.st.streams[1]=&b;d.st.streams[2]=&clean;
 for(unsigned i=0;i<sizeof memory;++i)memory[i]=(uint8_t)(i*7u+i/251u);
 uint32_t end[16]={4,4,4},bytes[16]={500,524,1234},lo[16]={4,8,0};
 present_stats(&d);assert(!logs&&!vb_upload_calls&&!vb_upload_bytes&&!vb_upload_frame_bytes&&!vb_upload_peak_bytes);
 consume(&d,end,bytes,lo);
 assert(vb_upload_calls==2&&vb_upload_bytes==1024&&vb_upload_frame_bytes==1024&&!vb_upload_peak_bytes);
#if RING
 /* The ring is created once (store + mapping); the data is copied, no GL command per upload. */
 assert(extension_queries==1&&ring_logs==1&&!uploads&&!uploaded_bytes&&gl_calls==4);
 assert(stream_ring[0]==0&&stream_ring[1]==512&&ring_used==1036);
 assert(!memcmp(ring_store,GPTR(64+4),500)&&!memcmp(ring_store+512,GPTR(1024+8),524));
#else
 /* Without GL_EXT_buffer_storage the ring is probed once; every upload is its own store. */
 assert(extension_queries==1&&!ring_logs&&ring_state==-1&&uploads==2&&uploaded_bytes==1024&&gl_calls==6);
 assert(stream_ring[0]==UINT32_MAX&&stream_ring[1]==UINT32_MAX&&stream_vbos[0]&&stream_vbos[1]&&!stream_vbos[2]);
#endif
 ++d.frame;++seconds;present_stats(&d);assert(!vb_upload_frame_bytes&&vb_upload_peak_bytes==1024&&!logs);
 /* IB/static/UP upload helpers are deliberately outside the compact dirty VB account. */
 unsigned calls=gl_calls,stores=uploads,stored=uploaded_bytes;
 GLuint separate=0;draw_buffer_upload(&separate,100,GPTR(0));
 assert(uploads==stores+1&&uploaded_bytes==stored+100&&gl_calls==calls+3&&vb_upload_calls==2&&vb_upload_bytes==1024);
 bytes[0]=2048;bytes[1]=1024;consume(&d,end,bytes,lo);
 assert(vb_upload_calls==4&&vb_upload_frame_bytes==3072);
#if RING
 assert(gl_calls==calls+3&&uploads==stores+1&&stream_ring[0]==1040&&stream_ring[1]==3088&&ring_used==4112);
#else
 assert(gl_calls==calls+3+4&&uploads==stores+3&&uploaded_bytes==stored+100+3072);
#endif
 vb_sparse_calls=2;vb_sparse_saved=4u*1024u*1024u;
 ++d.frame;seconds=106;present_stats(&d);
 assert(logs==1&&thunk_frames==2&&strstr(last_log,"compact VB 2.0 KiB/frame, 2.0 calls/frame, 3.0 KiB peak"));
 assert(strstr(last_log,"sparse 2 draws 2.0 MiB/frame saved")&&!vb_sparse_calls&&!vb_sparse_saved);
 assert(!vb_upload_calls&&!vb_upload_bytes&&!vb_upload_frame_bytes&&!vb_upload_peak_bytes);
 /* Empty frames count in the average; a logging boundary resets the peak. */
 ++d.frame;++seconds;present_stats(&d);bytes[0]=128;end[1]=end[2]=0;consume(&d,end,bytes,lo);
 ++d.frame;seconds=112;present_stats(&d);
 assert(logs==2&&strstr(last_log,"compact VB 0.1 KiB/frame, 0.5 calls/frame, 0.1 KiB peak"));
 assert(!vb_upload_calls&&!vb_upload_bytes&&!vb_upload_frame_bytes&&!vb_upload_peak_bytes);
#if RING
 assert(gl_calls==7&&uploads==1&&uploaded_bytes==100&&stream_ring[0]==4112&&ring_used==4240&&extension_queries==1);
#else
 assert(uploads==6&&uploaded_bytes==4324&&gl_calls==15&&extension_queries==1);
#endif
 free(ring_store);
 printf("PASS actual compact VB accounting (%s): dirty consumed bytes/calls, clean exclusion, GL command identity, per-Present peak, logging-window averages/reset\n",
        RING?"streaming ring":"per-draw stores");
 return 0;
}
'''


def extracted(source):
    declaration=re.search(r'^static uint64_t vb_upload_calls[^;]*;',source,re.M)
    assert declaration
    ring=source[source.index('/* Per-draw uploads go to one persistently mapped buffer'):source.index('static uint32_t enabled_attribs;')]
    start=source.index('    else for (unsigned stream = 0; stream < 16; ++stream) if (stream_end[stream]) {', source.index('int d3d_gl_draw('))
    end=source.index('    uint32_t want = 0;',start)
    present=source[source.index('    depth_trace_present(dev);',source.index('void d3d_gl_present(')):]
    present=present[:present.index('    if (tracing(dev))')]
    return {'ring_actual.h':ring,
            'stats_globals.h':'static uint64_t draw_calls;\n'+declaration.group(),
            'upload_actual.h':function(source,'static void draw_buffer_upload('),
            'consumed_actual.h':source[start:end], 'present_actual.h':present}


def probe(name, headers, ring):
    compile_probe(name + ('_ring' if ring else '_stores'), HARNESS, headers, extra_flags=('/DRING=%d' % ring,))


class BufferUploadStatsTest(unittest.TestCase):
    def test_actual_consumed_upload_and_present_statistics(self):
        source=(ROOT/'android/host/d3d9_gl.c').read_text()
        for ring in (0, 1):
            with self.subTest(ring=ring):
                probe('buffer_upload_stats',extracted(source),ring)
        destroyed=function(source,'void d3d_gl_device_destroy(')
        self.assertIn('vb_upload_calls = vb_upload_bytes = vb_upload_frame_bytes = vb_upload_peak_bytes = vb_sparse_calls = vb_sparse_saved = 0;',destroyed)
        self.assertIn('ring_release();',destroyed)

    def test_missing_frame_reset_is_rejected(self):
        source=(ROOT/'android/host/d3d9_gl.c').read_text()
        headers=extracted(source)
        self.assertIn('vb_upload_frame_bytes = 0;',headers['present_actual.h'])
        headers['present_actual.h']=headers['present_actual.h'].replace('vb_upload_frame_bytes = 0;','',1)
        for ring in (0, 1):
            with self.subTest(ring=ring):
                with self.assertRaises(AssertionError) as caught:
                    probe('buffer_upload_stats_no_reset',headers,ring)
                self.assertIn('Assertion failed:',str(caught.exception))


if __name__=='__main__':
    unittest.main()
