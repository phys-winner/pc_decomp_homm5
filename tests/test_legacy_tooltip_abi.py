"""Execute edition-adapted tooltip callers against independently pinned native ABIs."""
from pathlib import Path
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import port_patches

# Native RET8 in Vanilla9BB3D0; RET0xC in ToE8863A0 and HoFBE5950.
# CLEANUP includes the return address. The following saved-EBP canary must
# remain the next stack word when the wrapper returns to its native caller.
TRACKER_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x4000];
#define MEM32(a) (*(uint32_t *)(memory+(a)))
#define MEMF(a) (*(float *)(memory+(a)))
#define MEM8(a) (*(uint8_t *)(memory+(a)))
static uint32_t g_ecx,g_esp;
static int touch_mode,writable,held;
static unsigned lifted_calls;
static uint32_t read32(uint32_t a) {return MEM32(a);}
static int tooltip_held(void) {return held;}
static int void_vm_writable(uint32_t a,uint32_t n) {assert(a==0x1000&&n==0x20);return writable;}
static void LIFTED(void) {++lifted_calls;g_esp+=CLEANUP;}
#include "tooltip_tracker_wrapper.h"
static void reset(void) {
 memset(memory,0,sizeof memory);g_ecx=0x1000;g_esp=0x3000;
 MEM32(g_esp)=0xdead0000;MEM32(g_esp+4)=16;MEM32(g_esp+8)=0x2000;
 if(CLEANUP==16)MEM32(g_esp+12)=0;
 MEM32(g_esp+CLEANUP)=0xcafebabe;
 touch_mode=writable=1;held=0;lifted_calls=0;
 MEM32(0x1010)=33;MEMF(0x1008)=100;MEMF(0x100c)=200;
}
static void balanced(void) {assert(g_esp==0x3000+CLEANUP && MEM32(g_esp)==0xcafebabe);}
int main(void) {
 reset();WRAPPER();balanced();assert(!lifted_calls&&MEM32(0x1010)==0);
 reset();held=1;WRAPPER();balanced();assert(lifted_calls==1&&MEM32(0x1010)==0x3fffffff);
 reset();MEM32(0x1000)=0x2222;held=1;WRAPPER();balanced();assert(lifted_calls==1&&MEM32(0x1010)==33);
 reset();MEM32(0x1000)=0x2222;WRAPPER();balanced();assert(lifted_calls==1&&MEMF(0x1008)==-1&&MEMF(0x100c)==-1&&MEM8(0x1018)==1);
 reset();touch_mode=0;WRAPPER();balanced();assert(lifted_calls==1&&MEM32(0x1010)==33&&MEMF(0x1008)==100);
 reset();writable=0;WRAPPER();balanced();assert(lifted_calls==1&&MEM32(0x1010)==33);
 puts("PASS edition-adapted tooltip tracker: native ESP cleanup/caller EBP canary, suppressed/shown/held/pointer/invalid branches");
}
'''

INSPECT_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
enum { TOUCH_SECOND_BEGIN=20, TOUCH_SECOND_TAP, TOUCH_SECOND_HOLD };
typedef struct {int kind;float x,y;} void_touch_event;
typedef struct {int unused;} troop_cell;
static struct {
 uint32_t screen,root,dnd,combo;
 int cancelled,second_troop,ui,dnd_pressed,second_info,held,panning,inspecting;
 float x,y,start_x,start_y,inspect_x,inspect_y;
} gesture;
static int screen_live,method_live,target_live,point_live,change_screen;
static unsigned calls,hovers,releases,cancels,lookups;
static float published_x,published_y;
#define VLOG(...) ((void)0)
static int same_screen(void) {return screen_live;}
static int troop_cell_at(float x,float y,troop_cell *c) {(void)x;(void)y;(void)c;return 0;}
static int troop_cell_window(uint32_t w,troop_cell *c) {(void)w;(void)c;return 0;}
static uint32_t read32(uint32_t va) {(void)va;return 0;}
static int dnd_held(uint32_t d) {(void)d;return 0;}
static int dnd_identity(uint32_t d) {(void)d;return 0;}
static void dnd_point(unsigned m,float x,float y) {(void)m;(void)x;(void)y;assert(0);}
static void dnd_cancel(void) {++cancels;}
static void ui_release(int cancel) {assert(cancel==1);++releases;}
static void troop_split(float x,float y,int hold) {(void)x;(void)y;(void)hold;assert(0);}
static uint32_t object_method(uint32_t root,unsigned slot) {
 assert(root==0x2000 && slot==SLOT);++lookups;return method_live?METHOD:0;
}
static int tooltip_target_at(float x,float y) {assert(x==500&&y==600);return target_live;}
static uint32_t logical_point(float x,float y) {assert(x==100&&y==200);return point_live?0x3000:0;}
static void publish_point(float x,float y) {published_x=x;published_y=y;}
static uint32_t void_call_guest_this(uint32_t method,uint32_t self,unsigned n,const uint32_t *args) {
 assert(method==METHOD && self==0x2000 && n==2 && args && args[0]==0x3000 && args[1]==1);
 assert(published_x==100 && published_y==200);++calls;
 if(change_screen)screen_live=0;
 return 0;
}
static void ui_hover(float x,float y) {assert(x==100&&y==200);++hovers;}
#include "root_tooltip_inspect.h"
static void reset(void) {
 memset(&gesture,0,sizeof gesture);gesture.screen=0x1000;gesture.root=0x2000;gesture.held=1;
 gesture.x=100;gesture.y=200;gesture.start_x=90;gesture.start_y=190;
 screen_live=method_live=target_live=point_live=1;change_screen=0;
 calls=hovers=releases=cancels=lookups=0;published_x=published_y=-9;
}
static void event(int kind) {const void_touch_event e={kind,500,600};troop_second(&e);}
int main(void) {
 reset();event(TOUCH_SECOND_BEGIN);assert(gesture.second_info && !calls && lookups==1);
 event(TOUCH_SECOND_TAP);assert(calls==1&&hovers==1&&gesture.inspecting);
 assert(gesture.inspect_x==100&&gesture.inspect_y==200&&published_x==100&&published_y==200);
 reset();event(TOUCH_SECOND_BEGIN);event(TOUCH_SECOND_HOLD);assert(calls==1&&hovers==1&&lookups==2);
 reset();gesture.held=0;gesture.ui=1;event(TOUCH_SECOND_BEGIN);assert(!gesture.second_info&&!calls&&releases==1&&cancels==1&&gesture.panning);
 reset();gesture.combo=0x4000;event(TOUCH_SECOND_BEGIN);event(TOUCH_SECOND_TAP);assert(!calls&&!gesture.second_info);
 reset();method_live=0;event(TOUCH_SECOND_BEGIN);event(TOUCH_SECOND_TAP);assert(!calls&&!gesture.second_info);
 reset();target_live=0;event(TOUCH_SECOND_BEGIN);event(TOUCH_SECOND_TAP);assert(!calls&&!gesture.second_info);
 reset();event(TOUCH_SECOND_BEGIN);method_live=0;event(TOUCH_SECOND_TAP);assert(!calls&&!gesture.inspecting);
 reset();event(TOUCH_SECOND_BEGIN);point_live=0;event(TOUCH_SECOND_TAP);assert(!calls&&!gesture.inspecting);
 reset();screen_live=0;event(TOUCH_SECOND_BEGIN);assert(!calls&&!lookups&&published_x==-9);
 reset();gesture.cancelled=1;event(TOUCH_SECOND_BEGIN);assert(!calls&&!lookups&&published_x==-9);
 reset();event(TOUCH_SECOND_BEGIN);change_screen=1;event(TOUCH_SECOND_TAP);assert(calls==1&&!hovers&&!gesture.inspecting&&published_x==-1&&published_y==-1);
 puts("PASS adapted troop_second: exact typed root slot, thiscall point+button ABI, tap/hold source preservation and cancellation gates");
}
'''

class LegacyTooltipAbiTest(unittest.TestCase):
    def adapted(self, edition, signature):
        path, _ = port_patches.adapt_host_source(
            ROOT / 'android/host/touch_engine.c',
            ROOT / 'build/tests/legacy-tooltip-abi' / edition, edition)
        return function(path.read_text(), signature)

    def test_tracker_cleanup_and_suppression_branches(self):
        for edition, name, cleanup in (
            ('toe', '008863A0', 16),
            ('vanilla', '009BB3D0', 12),
            ('hof', '00BE5950', 16),
        ):
            with self.subTest(edition=edition):
                body = self.adapted(edition, 'void sub_' + name + '(')
                defines = (f'#define CLEANUP {cleanup}\n#define WRAPPER sub_{name}\n'
                           f'#define LIFTED sub_{name}_lifted\n')
                compile_probe('legacy-tooltip-tracker-' + edition,
                              defines + TRACKER_HARNESS,
                              {'tooltip_tracker_wrapper.h': body})

    def test_secondary_tap_and_hold_use_native_inspect_slot_and_two_arguments(self):
        # Typed CWindowScreen+F8: VanillaE527BC+6C=AF8710 and
        # HoFE1D084+6C=A35FD0, both RET8(point,button). Their +70 is a
        # different RET4 method and cannot inspect the held source point.
        for edition, method in (('vanilla', '0x00AF8710'), ('hof', '0x00A35FD0')):
            with self.subTest(edition=edition):
                body = self.adapted(edition, 'static void troop_second(')
                defines = '#define SLOT 0x6C\n#define METHOD ' + method + '\n'
                compile_probe('legacy-tooltip-inspect-' + edition,
                              defines + INSPECT_HARNESS,
                              {'root_tooltip_inspect.h': body})


if __name__ == '__main__':
    unittest.main()
