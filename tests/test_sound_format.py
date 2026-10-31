"""DirectSound must reject formats its PCM mixer cannot decode."""
import unittest
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

class SoundFormatTest(unittest.TestCase):
    def test_pcm_boundary_and_unsigned_silence(self):
        source=(ROOT/'android/host/dsound.c').read_text()
        code=function(source,'COM_METHOD(ds, CreateSoundBuffer,')
        harness=r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x10000];
#define GPTR(p) (memory+(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
#define MEM16(p) (*(uint16_t *)GPTR(p))
#define ARG(i) args[i]
#define COM_METHOD(p,n,c) static uint32_t p##_##n(void)
#define DSBCAPS_PRIMARYBUFFER 1
#define DSERR_INVALIDPARAM 0x80070057u
#define DS_OK 0
static uint32_t args[]={0,0x1000,0x2000,0};
typedef struct object {uint32_t guest;void (*destroy)(struct object *);} object;
typedef struct dsbuf {object com;uint32_t flags,channels,rate,bits,block,frequency,size,data;int primary;float min_distance,max_distance;struct dsbuf *next;} dsbuf_t;
static dsbuf_t *buffers;
static int mix_lock,buffer_class,dstrace,void_verbose,alloc_fail,wraps;
static void buffer_destroy(object *o){(void)o;}
static void pthread_mutex_lock(int *l){assert(!*l);*l=1;}
static void pthread_mutex_unlock(int *l){assert(*l);*l=0;}
static uint32_t void_galloc(uint32_t n){if(alloc_fail)return 0;assert(n<0x1000);memset(GPTR(0x4000),0,n);return 0x4000;}
static uint32_t void_com_wrap(object *o,int *c,int z){assert(c==&buffer_class&&!z);++wraps;o->guest=0x9000;return o->guest;}
static void void_log(const char *fmt,...){(void)fmt;}
#include "format_actual.h"
static void format(void){MEM32(0x1004)=0;MEM32(0x1008)=64;MEM32(0x1010)=0x3000;MEM16(0x3000)=1;MEM16(0x3002)=2;MEM32(0x3004)=44100;MEM16(0x300c)=4;MEM16(0x300e)=16;}
int main(void){
 format();MEM16(0x3000)=3;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM&&!MEM32(0x2000));
 format();MEM16(0x3002)=3;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM);
 format();MEM16(0x300e)=24;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM);
 format();MEM16(0x300c)=2;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM);
 format();MEM32(0x3004)=0;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM);
 format();MEM32(0x3004)=200001;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM);
 format();MEM32(0x1008)=1;assert(ds_CreateSoundBuffer()==DSERR_INVALIDPARAM);
 format();alloc_fail=1;assert(ds_CreateSoundBuffer()==0x8007000Eu&&!wraps);alloc_fail=0;
 format();MEM16(0x3002)=1;MEM16(0x300c)=1;MEM16(0x300e)=8;
 assert(!ds_CreateSoundBuffer()&&MEM32(0x2000)==0x9000&&wraps==1&&buffers->size==64&&!mix_lock);
 for(unsigned i=0;i<64;++i)assert(memory[0x4000+i]==128);
 free(buffers);buffers=NULL;
 format();assert(!ds_CreateSoundBuffer()&&buffers->frequency==44100&&buffers->block==4);free(buffers);buffers=NULL;
 format();MEM32(0x1004)=1;MEM32(0x1010)=0;assert(!ds_CreateSoundBuffer()&&buffers->primary&&!buffers->size);free(buffers);
 puts("PASS PCM format boundary: tag/channels/bits/alignment/rate/empty-frame/OOM; 8-bit silence, stereo and primary defaults");return 0;
}
'''
        compile_probe('sound-format',harness,{'format_actual.h':code})

if __name__=='__main__':unittest.main()
