"""Run the touch-only cursor hardware query hook with native ABI/instance spies."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
#define MEMF(a) (*(float *)(memory+(uint32_t)(a)))
typedef void (*void_fn)(void);
static uint32_t g_ecx,g_eax,g_esp;
static int touch_mode,option,hardware=1,nested,depth;
static unsigned software_draws,hardware_draws,queries,bindings;
static uint64_t cursor_started_ns=1;
static float touch_cursor_x=230,touch_cursor_y=170;
static struct {int active,cancelled,ui,panning,combat_aim;} gesture;
static void_fn original_cursor_hardware_query;
static uint32_t cursor_software_owner;
static int void_vm_readable(uint32_t p,uint32_t n) {return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n) {return void_vm_readable(p,n);}
static uint32_t read32(uint32_t p) {return void_vm_readable(p,4)?MEM32(p):0;}
static int void_port_touch_cursor(void) {return option;}
static uint64_t void_perf_now_ns(void) {return 100;}
static int void_input_pointer(uint32_t *x,uint32_t *y,uint64_t *moved) {*x=70;*y=80;*moved=1;return 1;}
static void native_hardware_query(void) {++queries;g_eax=(g_eax&~255u)|(uint32_t)hardware;g_esp+=4;}
static void_fn hardware_hook=native_hardware_query;
static void_fn void_dispatch_find(uint32_t va) {assert(va==HARDWARE_QUERY);return hardware_hook;}
static void void_dispatch_add(uint32_t va,void_fn fn) {assert(va==HARDWARE_QUERY&&fn);++bindings;hardware_hook=fn;}
static void touch_cursor_software_draw(void);
static unsigned query(uint32_t owner) {
    uint32_t saved_self=g_ecx,saved_sp=g_esp,saved_eax=g_eax;
    g_ecx=owner;g_eax=0xAABBCC01;hardware_hook();
    assert(g_esp==saved_sp+4&&(g_eax&~255u)==0xAABBCC00);
    unsigned result=g_eax&255;g_ecx=saved_self;g_esp=saved_sp;g_eax=saved_eax;return result;
}
static void native_draw(void) {
    uint32_t owner=g_ecx,sp=g_esp;++depth;
    if(query(owner))++hardware_draws;else ++software_draws;
    if(cursor_software_owner)assert(query(owner==0x3000?0x4000:0x3000)==1);
    if(nested&&depth==1) {
        g_ecx=0x4000;g_esp=sp+1000;touch_cursor_software_draw();
        assert(g_esp==sp+1008&&cursor_software_owner==owner);
        g_ecx=owner;g_esp=sp;assert(query(owner)==0);
    }
    --depth;g_eax=0xD00D;g_esp=sp+8;
}
static void_fn original_cursor_draw=native_draw;
/* ACTUAL */
int main(void) {
    MEM32(0x3000)=MEM32(0x4000)=CURSOR_TABLE;
    MEM32(CURSOR_TABLE+8)=CURSOR_DRAW;MEM32(CURSOR_TABLE+HARDWARE_SLOT)=HARDWARE_QUERY;
    gesture.active=touch_mode=option=1;
    g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(software_draws==1&&!hardware_draws&&bindings==1&&g_esp==1008&&g_eax==0xD00D);
    assert(!cursor_software_owner&&query(0x3000)==1&&hardware==1);
    nested=1;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(software_draws==3&&!hardware_draws&&bindings==1&&!cursor_software_owner&&g_esp==1008);
    nested=0;touch_mode=0;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(hardware_draws==1&&software_draws==3&&g_esp==1008&&query(0x3000)==1);
    touch_mode=1;option=0;g_esp=1000;touch_cursor_draw();assert(hardware_draws==1&&software_draws==3&&g_esp==1008);
    option=1;MEM32(CURSOR_TABLE+HARDWARE_SLOT)=0xDEAD;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(hardware_draws==2&&software_draws==3&&!cursor_software_owner&&g_esp==1008);
    MEM32(CURSOR_TABLE+HARDWARE_SLOT)=HARDWARE_QUERY;MEM32(0x3000)=0x6000;g_esp=1000;touch_cursor_draw();
    assert(hardware_draws==3&&software_draws==3&&hardware==1&&queries>0);
    puts("PASS touch cursor: hardware preference1, software only for verified drawn instance, physical/disabled original path, nested owner restoration, AL/callee stack ABI, unchanged hardware setting");
}
'''


def cursor_bodies(source):
    return "\n".join(function(source, signature) for signature in (
        "static void touch_cursor_hardware_query(",
        "static void touch_cursor_software_draw(",
        "static void touch_cursor_draw(",
    ))


class TouchCursorNativeTest(unittest.TestCase):
    def test_hardware_profile_during_touch_and_physical_draw(self):
        source = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf8")
        defines = "#define CURSOR_TABLE 0xE49494\n#define CURSOR_DRAW 0x836440\n#define HARDWARE_QUERY 0x835B90\n#define HARDWARE_SLOT 0x24\n"
        compile_probe("touch_cursor_native", defines + HARNESS.replace("/* ACTUAL */", cursor_bodies(source)), {})


if __name__ == "__main__":
    unittest.main()
