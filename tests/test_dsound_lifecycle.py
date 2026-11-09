"""Exercise real COM registration and DirectSound's embedded interface lifetime."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
static uint8_t memory[0x40000],guest_used[1024];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
#define RS_TAPS 32u
#define DSBCAPS_CTRL3D 0x10u
#define E_NOINTERFACE_ 0x80004002u
#define DSTRACE(...) ((void)0)
typedef struct void_com_class {const char *name;} void_com_class;
typedef struct void_com_object {
    void_com_class *cls;uint32_t guest;int refs;void (*destroy)(struct void_com_object *);
} void_com_object;
static const uint8_t IID_IUnknown[16]={1},IID_IDirectSoundBuffer[16]={2},IID_IDirectSoundBuffer8[16]={3};
static const uint8_t IID_IDirectSound3DBuffer[16]={4},IID_IDirectSound3DListener[16]={5},IID_IDirectSoundNotify[16]={6};
#include "buffer_type.h"
static dsbuf_t *buffers,*active_buffer;
static int mix_lock,com_lock;
static unsigned guest_alive,buffer_alive,buffer_frees;
static void *objects[65536];static uint32_t object_hint=1;
#define MAX_OBJECTS 65536
static jmp_buf trap;
static uint32_t g_cur_func;
static int pthread_mutex_lock(int *p){assert(!*p);*p=1;return 0;}
static int pthread_mutex_unlock(int *p){assert(*p);*p=0;return 0;}
static void void_fatal(const char *why,...){fprintf(stderr,"%s\n",why);abort();}
static void void_lift_trap(uint32_t va,const char *why){(void)va;assert(why);longjmp(trap,1);}
static uint32_t void_galloc(uint32_t size) {
    assert(size<=128);
    for(unsigned i=0;i<1024;++i)if(!guest_used[i]){
        guest_used[i]=1;++guest_alive;uint32_t p=0x1000+128*i;memset(GPTR(p),0,128);return p;
    }
    assert(!"guest allocations leaked");return 0;
}
static void void_gfree(uint32_t p) {
    if(!p)return;assert(p>=0x1000 && !((p-0x1000)%128));unsigned i=(p-0x1000)/128;
    assert(i<1024 && guest_used[i]);guest_used[i]=0;--guest_alive;
}
static int void_vm_readable(uint32_t p,uint32_t size) {
    if(p<0x1000 || (uint64_t)p+size>0x21000)return 0;
    return guest_used[(p-0x1000)/128] && (p-0x1000)%128+size<=128;
}
static uint32_t void_com_vtable(void_com_class *cls){assert(cls);return 0xF000;}
static int void_guid_equal(uint32_t p,const uint8_t guid[16]){return p && !memcmp(GPTR(p),guid,16);}
static void void_guid_format(uint32_t p,char out[40]){(void)p;strcpy(out,"unknown");}
static void void_log(const char *format,...){(void)format;}
static void checked_free(void *p) {
    assert(p==active_buffer && buffer_alive==1);--buffer_alive;++buffer_frees;active_buffer=NULL;free(p);
}
#define free checked_free
#include "com_actual.h"
#include "buffer_actual.h"
static uint32_t args[3];
#define ARG(i) args[i]
#define THIS_ ARG(0)
#define B3 (((facet_t *)void_com_host(THIS_))->owner)
#define COM_METHOD(p,n,c) static uint32_t p##_##n(void)
#include "facet_actual.h"
static unsigned registered(void){unsigned n=0;for(unsigned i=1;i<MAX_OBJECTS;++i)n+=objects[i]!=NULL;return n;}
static uint32_t query(dsbuf_t *b,const uint8_t guid[16]) {
    memcpy(GPTR(0x100),guid,16);MEM32(0x200)=0;
    assert(!buffer_query(b,0x100,0x200));return MEM32(0x200);
}
static void released(uint32_t guest) {
    if(!setjmp(trap)){void_com_host(guest);assert(!"released interface still registered");}
}
static dsbuf_t *create_buffer(int primary) {
    assert(!active_buffer);active_buffer=calloc(1,sizeof *active_buffer);assert(active_buffer);++buffer_alive;
    active_buffer->primary=primary;active_buffer->flags=DSBCAPS_CTRL3D;
    active_buffer->data=primary?0:void_galloc(64);
    void_com_wrap(&active_buffer->com,&buffer_class,0);active_buffer->com.destroy=buffer_destroy;
    active_buffer->next=buffers;buffers=active_buffer;return active_buffer;
}
int main(void) {
    for(unsigned i=0;i<4096;++i) {
        dsbuf_t *b=create_buffer(0);uint32_t base=b->com.guest;
        uint32_t f3d=query(b,IID_IDirectSound3DBuffer),notify=query(b,IID_IDirectSoundNotify);
        assert(query(b,IID_IDirectSound3DBuffer)==f3d);
        assert(b->com.refs==4 && b->f3d.com.refs==1 && b->notify.com.refs==1);
        args[0]=f3d;assert(d3b_AddRef()==5);assert(d3b_Release()==4);assert(d3b_Release()==3);
        assert(void_com_release(&b->com)==2); /* owner interface released first */
        args[0]=notify;assert(ntf_Release()==1 && buffer_alive==1);
        args[0]=f3d;assert(!d3b_Release());
        assert(!buffer_alive && !guest_alive && !buffers);
        released(base);released(f3d);released(notify);
        b=create_buffer(1);base=b->com.guest;
        uint32_t listener=query(b,IID_IDirectSound3DListener);
        assert(void_com_release(&b->com)==1);
        args[0]=listener;assert(lst_AddRef()==2 && lst_Release()==1 && !lst_Release());
        assert(!buffer_alive && !guest_alive && !buffers);
        released(base);released(listener);
        if(!(i%64))assert(!registered());
    }
    assert(!registered() && !mix_lock && !com_lock && buffer_frees==8192);
    puts("PASS DirectSound lifetime: 4096 3D+notify and listener cycles, duplicate queries/shared owner references, owner released before facets, all COM/guest allocations reclaimed, released interfaces rejected");
    return 0;
}
'''


class DirectSoundLifecycleTest(unittest.TestCase):
    def test_embedded_interfaces_release_with_owner(self):
        sound = (ROOT / "android/host/dsound.c").read_text(encoding="utf8")
        com = (ROOT / "android/host/com.c").read_text(encoding="utf8")
        types = sound[sound.index("typedef struct dsbuf dsbuf_t;"):sound.index("/* Kaiser-windowed")]
        types += sound[sound.index("struct dsbuf {"):sound.index("static float rs_table")]
        buffers = "static void_com_class buffer_class,ds3d_class,notify_class,listener_class;\n"
        for name in ("static void facet_destroy(", "static uint32_t facet_wrap(",
                     "static void buffer_destroy(", "static uint32_t buffer_query("):
            buffers += function(sound, name)
        com_helpers = "".join(function(com, name) for name in (
            "uint32_t void_com_wrap(", "void *void_com_host(",
            "uint32_t void_com_addref(", "uint32_t void_com_release("))
        facets = "".join(function(sound, f"COM_METHOD({prefix}, {name},")
                         for prefix in ("d3b", "lst", "ntf") for name in ("AddRef", "Release"))
        compile_probe("dsound-lifecycle", HARNESS, {
            "buffer_type.h": types,
            "com_actual.h": com_helpers,
            "buffer_actual.h": buffers,
            "facet_actual.h": facets,
        }, extra_flags=("/O2",))


if __name__ == "__main__":
    unittest.main()
