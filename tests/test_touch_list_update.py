"""New map-list rows rebuild glyph geometry after native Update, with guest results preserved."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
import port_patches
from test_d3d_lifecycle import function
from test_static_tls import compile_probe

WORK = ROOT

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x20000];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
#define MEMF(p) (*(float *)GPTR(p))
#define MEM8(p) (*(uint8_t *)GPTR(p))
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static uint32_t scale_read32(uint32_t p){if(p==VT_LIST+4)return COMMON_REFRESH;return void_vm_readable(p,4)?MEM32(p):0;}
static uint32_t scale_placement(uint32_t w){return scale_read32(w+0x140);}
typedef void (*void_fn)(void);
static uint32_t g_ecx,g_esp,g_eax;
static int g_fp_top;
typedef struct {uint32_t ecx,esp,eax;int fp;} void_regs;
static void void_regs_save(void_regs *r){*r=(void_regs){g_ecx,g_esp,g_eax,g_fp_top};}
static void void_regs_load(const void_regs *r){g_ecx=r->ecx;g_esp=r->esp;g_eax=r->eax;g_fp_top=r->fp;}
static int updates,refreshes,bindings,multi,reentrant,invalid;
static void scale_list_update(void);
static void native_update(void){
    assert(g_ecx==0x10F8);++updates;
    MEM32(0x30A8)=multi?0x8008:0x8004;
    MEM32(0x8000)=0x5000;MEM32(0x8004)=0x6000;
    MEMF(0x60D0)=32; /* newly constructed MP glyph geometry is stale */
    if(invalid)MEM32(0x1000)=0;
    g_ecx=0xBAD;g_eax=0xFFFFFFFFu;g_esp+=4;g_fp_top=7;
}
static void_fn update_dispatch=native_update;
static void bool_stub(void){}
static void_fn void_dispatch_find(uint32_t address){
    if(address==0x1040)return bool_stub;
    if(address==TEXT_REFRESH)return bool_stub;
    if(address==0x1050)return update_dispatch;
    return NULL;
}
static void void_dispatch_add(uint32_t address,void_fn fn){assert(address==0x1050&&fn);++bindings;update_dispatch=fn;}
static uint32_t void_call_guest_this(uint32_t address,uint32_t self,int n,const uint32_t *args){
    (void)args;assert(!n);
    if(address==0x1040){assert(self==0xC0F8);return 0xDEADBE00u;}
    if(address==REORDER||address==RESIZE){assert(self==0x1000);return 0;}
    assert(address==TEXT_REFRESH&&(self==0x5000||self==0x6000));
    ++refreshes;MEMF(self+0xD0)=21;
    if(reentrant){
        reentrant=0;uint32_t ecx=g_ecx,esp=g_esp;
        g_ecx=0x10F8;scale_list_update();assert(g_esp==esp+4);
        g_ecx=ecx;g_esp=esp;
    }
    g_eax=0x12345678;g_ecx=0xABC;g_fp_top=3;
    return 0;
}
static void native_layout(void){assert(g_ecx==0x1000);g_ecx=0xBEEF;g_esp+=8;g_eax=0x55;g_fp_top=2;}
/* ACTUAL */
int main(void){
    MEM32(0x1000)=VT_LIST;
    MEM32(0x10F8)=0xD000;MEM32(0xD00C)=0x1050;
    MEM32(0x1154)=0xC000;MEM32(0xC0F8)=0xD100;MEM32(0xD118)=0x1040;
    MEM32(0x10A4)=0x8100;MEM32(0x10A8)=0x8104;MEM32(0x8100)=0x2000;
    MEM32(0x2000)=0x9000;MEM32(0x9004)=COMMON_REFRESH;
    MEM32(0x2140)=0xA000;MEM8(0xA070)=1;MEMF(0xA0A8)=21;
    MEM32(0x20A4)=0x8200;MEM32(0x20A8)=0x8204;MEM32(0x8200)=0x3000;
    MEM32(0x3000)=0x9000;MEM32(0x3140)=0xA200;MEM8(0xA270)=1;MEMF(0xA2A8)=21;
    MEM32(0x115C)=0x2000; /* this list's dynamic row holder */
    MEM32(0x20A4)=0x8200;MEM32(0x20A8)=0x8204;MEM32(0x8200)=0x3000;
    MEM32(0x30A4)=0x8000;MEM32(0x30A8)=0x8004;MEM32(0x8000)=0x5000;
    for(uint32_t text=0x5000;text<=0x6000;text+=0x1000){
        MEM32(text)=0x9200;MEM32(0x9204)=TEXT_REFRESH;
        MEM32(text+0x140)=text+0x5000;MEM8(text+0x5070)=1;MEMF(text+0x50A8)=21;
        MEM32(text+0x100)=0xE000;MEM32(text+0x10C)=0xF000;MEM32(text+0x110)=0xF004;
        MEMF(text+0xD0)=21;
    }
    original_list_layout=native_layout;
    g_ecx=0x1000;g_esp=0x10000;scale_list_layout();
    assert(bindings==1&&update_dispatch==scale_list_update);
    assert(g_ecx==0xBEEF&&g_esp==0x10008&&g_eax==0x55&&g_fp_top==2);
    for(int toggle=0;toggle<6;++toggle){
        multi=toggle%2;int before=refreshes;
        g_ecx=0x10F8;g_esp=0x10000;update_dispatch();
        assert(MEMF(0x50D0)==21);
        if(multi)assert(MEMF(0x60D0)==21);
        assert(refreshes==before+1+multi);
        assert(g_ecx==0xBAD&&g_esp==0x10004&&g_eax==0xFFFFFFFFu&&g_fp_top==7);
    }
    multi=1;reentrant=1;g_ecx=0x10F8;g_esp=0x10000;int before=updates;
    update_dispatch();assert(updates==before+2&&!reentrant);
    assert(g_ecx==0xBAD&&g_esp==0x10004&&g_eax==0xFFFFFFFFu&&g_fp_top==7);
    before=refreshes;invalid=1;g_ecx=0x10F8;g_esp=0x10000;update_dispatch();
    assert(refreshes==before&&g_esp==0x10004&&g_eax==0xFFFFFFFFu);
    puts("PASS dynamic list text: lazy Update hook, MP new/reused rows refreshed, guest ABI/failure result, bounded recursion and invalidated owner");
}
'''

class ListUpdateTest(unittest.TestCase):
    def test_update(self):
        for edition in ('toe','vanilla','hof'):
            source=WORK/'android/host/touch_scale.c'
            if edition!='toe':
                source,_=port_patches.adapt_host_source(source,ROOT/'build/tests'/('list-update-'+edition),edition,root=WORK)
            text=source.read_text(encoding='utf-8')
            mapping={} if edition=='toe' else port_patches.load_contract(edition,root=WORK)['addresses']
            required={'VT_LIST':'00E94034','COMMON_REFRESH':'00A4E570','TEXT_REFRESH':'00B95AC0',
                      'REORDER':'008888E0','RESIZE':'00887BA0'}
            addresses={key:'0x'+mapping.get(val,val)+'u' for key,val in required.items()}
            globals_=text[text.index('static void_fn original_list_layout'):text.index('/* Scrollable text rows')]
            actual=globals_+'\n'.join(function(text,name) for name in (
                'static int scale_text_rows(', 'static void scale_list_layout(',
                'static int scale_has_text(', 'static void scale_refresh_window(uint32_t window, unsigned depth, unsigned *remaining)\n{'))
            defines=''.join('#define '+k+' '+v+'\n' for k,v in addresses.items())
            harness=defines+HARNESS.replace('/* ACTUAL */',actual)
            compile_probe('touch-list-update-'+edition,harness,{})
            old=actual.replace('scale_refresh_window(list, 0, &remaining);','(void)remaining;')
            self.assertNotEqual(old,actual)
            with self.assertRaisesRegex(AssertionError,'refreshes==before'):
                compile_probe('scale-list-update-negative-'+edition,defines+HARNESS.replace('/* ACTUAL */',old),{})

if __name__=='__main__':unittest.main()
