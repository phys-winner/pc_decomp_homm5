"""Wrapped native columns determine their row height at every UI scale, in every edition.

1.6/2.1 run the contract-adapted touch_scale.c: their CWindowScrollableContainer vtable, text view
refresh and the list's reorder/resize methods (same bodies, same +154/+15C fields)."""
import json
import sys
import unittest
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / 'tools'))
import port_patches   # noqa: E402

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <math.h>
#include <stdio.h>
static unsigned char memory[0x10000];
#define MEM32(p) (*(uint32_t *)(memory+(p)))
#define MEMF(p) (*(float *)(memory+(p)))
#define MEM8(p) memory[p]
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static uint32_t scale_read32(uint32_t p){return void_vm_readable(p,4)?MEM32(p):0;}
static uint32_t scale_placement(uint32_t w){return scale_read32(w+0x140);}
typedef void (*void_fn)(void);
static uint32_t g_ecx, g_esp;
typedef struct {uint32_t ecx,esp;} void_regs;
static void void_regs_save(void_regs *r){r->ecx=g_ecx;r->esp=g_esp;}
static void void_regs_load(const void_regs *r){g_ecx=r->ecx;g_esp=r->esp;}
static int reordered,laid_out,resized;
static int void_dispatch_find(uint32_t address){return address==0x1040;}
static uint32_t void_call_guest_this(uint32_t address,uint32_t self,int n,const uint32_t *args){
 (void)args;assert(!n);
 if(address==0x1040){assert(self==0xc0f8);return 0xDEADBE00u;} /* Native bool writes only AL. */
 if(address==RESIZE){assert(self==0x1000&&reordered==1);++resized;return 0;}
 assert(address==REORDER&&self==0x1000);++reordered;g_ecx=0xdead;return 0;
}
static void native_layout(void){assert(g_ecx==0x1000);++laid_out;MEMF(0xb0a8)=39;g_ecx=0xbeef;g_esp+=4;}
#include "rows_actual.h"
int main(void){
 MEM32(0x115c)=0x2000;MEM32(0x20a4)=0x8000;MEM32(0x20a8)=0x8004;MEM32(0x8000)=0x3000;
 MEM32(0x3140)=0x4000;MEM8(0x4070)=1;MEMF(0x40a8)=21;
 MEM32(0x30a4)=0x8100;MEM32(0x30a8)=0x8108;MEM32(0x8100)=0x5000;MEM32(0x8104)=0x6000;
 MEM32(0x5000)=MEM32(0x6000)=0x9000;MEM32(0x9004)=TEXT_REFRESH;
 MEM32(0x5140)=0xa000;MEM32(0x6140)=0xb000;MEM8(0xa070)=MEM8(0xb070)=1;
 MEMF(0xa0a8)=21;MEMF(0xb0a8)=39;
 assert(scale_text_rows(0x1000)&&MEMF(0x40a8)==39);assert(!scale_text_rows(0x1000));
 MEMF(0xb0a8)=20;assert(scale_text_rows(0x1000)&&MEMF(0x40a8)==21);
 MEM32(0x9004)=OTHER_REFRESH;MEMF(0xb0a8)=99;assert(!scale_text_rows(0x1000));
 MEM32(0x9004)=TEXT_REFRESH;MEMF(0xb0a8)=NAN;assert(!scale_text_rows(0x1000));
 MEM32(0x20a8)=0xffffffff;assert(!scale_text_rows(0x1000));
 MEM32(0x20a8)=0x8004;MEMF(0xb0a8)=21;MEMF(0x40a8)=21;
 MEM32(0x1000)=VT_LIST;MEM32(0x1154)=0xc000;MEM32(0xc0f8)=0xd000;MEM32(0xd018)=0x1040;
 original_list_layout=native_layout;g_ecx=0x1000;g_esp=0xe000;scale_list_layout();
 assert(laid_out==1&&reordered==1&&resized==1&&MEMF(0x40a8)==39&&g_ecx==0xbeef&&g_esp==0xe004);
 MEM32(0x1000)=0x1234;laid_out=0;g_ecx=0x1000;scale_list_layout();assert(laid_out==1&&reordered==1);
 printf("PASS wrapped native list rows (%s): grow/shrink, geometry guards, reflow after text layout, preserved guest result\n", EDITION);
}
'''
ADDRESSES = {'VT_LIST': '00E94034', 'TEXT_REFRESH': '00B95AC0', 'OTHER_REFRESH': '00A4E570',
             'REORDER': '008888E0', 'RESIZE': '00887BA0'}


class ListRowsTest(unittest.TestCase):
    def run_edition(self, edition):
        source = ROOT / 'android/host/touch_scale.c'
        if edition == 'toe':
            text, addresses = source.read_text(), {}
        else:
            adapted, _ = port_patches.adapt_host_source(source, ROOT / 'build/tests' / ('list-rows-' + edition), edition)
            text = adapted.read_text()
            addresses = json.loads((ROOT / 'config' / (edition + '.patches.json')).read_text(encoding='utf-8'))['addresses']
        code = text[text.index('static void_fn original_list_layout;'):text.index('\nstatic int scale_has_text(')]
        defines = '#define EDITION "%s"\n' % edition + ''.join(
            '#define %s 0x%su\n' % (name, addresses.get(toe, toe) if name != 'OTHER_REFRESH' else toe)
            for name, toe in ADDRESSES.items())
        for name, toe in ADDRESSES.items():
            if edition != 'toe' and name != 'OTHER_REFRESH':
                self.assertNotIn('0x%su' % toe, code, name)   # mapped for this engine
        compile_probe('touch-list-rows-' + edition, defines + HARNESS, {'rows_actual.h': code})

    def test_tribes_of_the_east(self):
        self.run_edition('toe')

    def test_heroes_v_1_6(self):
        self.run_edition('vanilla')

    def test_hammers_of_fate(self):
        self.run_edition('hof')


if __name__ == '__main__':
    unittest.main()
