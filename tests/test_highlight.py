"""Exercise native highlight ownership and bounded refresh work in every edition
(1.6/2.1: the contract-adapted highlight.c with their CSelectionRender update and handle release)."""
import json
import sys
import unittest
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / 'tools'))
import port_patches   # noqa: E402

class HighlightTest(unittest.TestCase):
    def run_edition(self, edition):
        path=ROOT/'android/host/highlight.c'
        if edition!='toe':
            path,_=port_patches.adapt_host_source(path,ROOT/'build/tests'/('highlight-'+edition),edition)
        addresses=json.loads((ROOT/'config'/(edition+'.patches.json')).read_text(encoding='utf-8'))['addresses'] if edition!='toe' else {}
        update,release=(int(addresses.get(a,a),16) for a in ('005A0DB0','008C61D0'))
        source=path.read_text().replace('#include "host.h"','')
        self.assertIn('0x%08Xu'%update,source)
        self.assertIn('0x%08Xu'%release,source)
        harness='#define UPDATE_VA 0x%Xu\n#define RELEASE_VA 0x%Xu\n'%(update,release)+r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x200000];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
static uint32_t g_ecx=0x1000,g_esp=0x80000;
typedef void (*void_fn)(void);
typedef struct {uint32_t ecx,esp;} void_regs;
static void void_regs_save(void_regs *r){r->ecx=g_ecx;r->esp=g_esp;}
static void void_regs_load(const void_regs *r){g_ecx=r->ecx;g_esp=r->esp;}
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static unsigned originals,creates,destroys,next_handle=0x20000;
static void original(void){
    ++originals;MEM32(0x2000)=0x3000;MEM32(0x2004)=0x3000+70*4;
    for(unsigned i=0;i<70;++i){uint32_t h=next_handle;next_handle+=16;MEM32(0x3000+i*4)=h;MEM32(h+4)=1;}
    g_esp+=4;
}
static void_fn void_dispatch_find(uint32_t va){return va==UPDATE_VA||va==0xB18F00?original:NULL;}
static void void_dispatch_add(uint32_t va,void_fn fn){assert(va==UPDATE_VA&&fn);}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *a){
    if(va==RELEASE_VA){assert(n==1&&a[0]==0xFFFFF&&!MEM32(self+4));++destroys;return 0;}
    assert(va==0xB18F00&&self==0x4000&&n==3);
    assert(a[0]<70&&a[2]==(uint32_t)(a[0]<2));++creates;
    uint32_t h=next_handle;next_handle+=16;return h;
}
#include "highlight_actual.h"
static void update(void){g_ecx=0x1000;g_esp=0x80000;selection_update();assert(g_ecx==0x1000&&g_esp==0x80004);}
int main(void){
    MEM32(0x1010)=0x2000;MEM32(0x100C)=0x4000;MEM32(0x4000)=0x4100;MEM32(0x4130)=0xB18F00;
    MEM32(0x1014)=0x5000;MEM32(0x1018)=0x5000+40;MEM32(0x1020)=0x6000;MEM32(0x1024)=0x6000+68*20;
    for(unsigned i=0;i<70;++i) MEM32(i<2?0x5000+i*20:0x6000+(i-2)*20)=i;
    void_highlight_init();update();assert(originals==1);
    for(unsigned i=0;i<120;++i){unsigned before=creates;update();assert(creates-before==3&&originals==1);}
    assert(creates==360&&destroys==360);
    MEM32(0x6000+25*20+4)=0x3F800000;
    unsigned before=creates;update();assert(creates-before<=4&&originals==1);
    assert(!memcmp(last.entries+2*20,GPTR(0x6000),68*20));
    for(unsigned i=0;i<70;++i) assert(MEM32(MEM32(0x3000+i*4)+4)==1);
    MEM32(0x2004)-=4;update();assert(originals==2);
    MEM32(0x1018)=0x5000+20;update();assert(originals==3);
    free(last.entries);
    puts("PASS highlight: 70 handles refresh 3 per frame, one colour changes one entry, refcounts balanced, invalid vector falls back");
    return 0;
}
'''
        compile_probe('highlight-incremental-'+edition,harness,{'highlight_actual.h':source})

    def test_tribes_of_the_east(self):
        self.run_edition('toe')

    def test_heroes_v_1_6(self):
        self.run_edition('vanilla')

    def test_hammers_of_fate(self):
        self.run_edition('hof')

if __name__=='__main__': unittest.main()
