"""Run native cursor drawing and prediction placement for all three editions."""
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_patches


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define GPTR(a) (memory+(uint32_t)(a))
#define ADDR(a) GPTR(a)
#define MEM8(a) (*GPTR(a))
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
#define MEMF(a) (*(float *)(memory+(uint32_t)(a)))
typedef void (*void_fn)(void);
static uint32_t g_ecx,g_eax,g_esp;
static int touch_mode,option,hardware=1,nested,depth;
static unsigned software_draws,hardware_draws,queries,bindings;
static float drawn_x,drawn_y,icon_width=32,icon_height=48,hot_x=5,hot_y=7;
static unsigned rect_queries,cast_calls;
static int failed_cast,missing_cast;
static uint32_t scratch=0x10000;
enum {SCREEN_COMBAT=2};
static uint64_t cursor_started_ns=1;
static float touch_cursor_x=230,touch_cursor_y=170;
static struct {int active,cancelled,ui,panning,combat_aim,kind,aiming,placement;uint32_t screen;} gesture;
typedef struct {uint32_t ecx,eax,esp;} void_regs;
static void void_regs_save(void_regs *r) {*r=(void_regs){g_ecx,g_eax,g_esp};}
static void void_regs_load(const void_regs *r) {g_ecx=r->ecx;g_eax=r->eax;g_esp=r->esp;}
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
static void rectangle_stub(void) {}
static void_fn void_dispatch_find(uint32_t va) {if(va==DYNAMIC_CAST)return missing_cast?NULL:rectangle_stub;if(va==0x123400)return rectangle_stub;assert(va==HARDWARE_QUERY);return hardware_hook;}
static void void_dispatch_add(uint32_t va,void_fn fn) {assert(va==HARDWARE_QUERY&&fn);++bindings;hardware_hook=fn;}
static void touch_cursor_software_draw(void);
static int same_screen(void) {return 1;}
static void void_input_screen_size(int *width,int *height) {*width=1280;*height=800;}
static uint32_t logical_point(float x,float y) {
 MEMF(scratch)=x*MEMF(CANVAS_W)/1280+11;MEMF(scratch+4)=y*MEMF(CANVAS_H)/800-7;return scratch;
}
static uint32_t void_call_guest(uint32_t method,int count,const uint32_t *args,int pops) {
 assert(method==DYNAMIC_CAST&&count==5&&!pops&&args[0]==0x713C&&!args[1]&&
        args[2]==TYPE_IWINDOW&&args[3]==TYPE_CWINDOW&&!args[4]);
 ++cast_calls;g_ecx=0xBADCA57;g_eax=0xDEADCA57;g_esp=0xBAD5;
 return failed_cast?0:0x7000;
}
static uint32_t void_call_guest_this(uint32_t method,uint32_t owner,int count,const uint32_t *args) {
 assert(method==0x123400&&owner==0x3000&&count==1);++rect_queries;
 float rect[4]={MEMF(CURSOR_X)-hot_x,MEMF(CURSOR_Y)-hot_y,0,0};
 rect[2]=rect[0]+icon_width;rect[3]=rect[1]+icon_height;memcpy(GPTR(args[0]),rect,16);
 g_ecx=0xBAD;g_eax=0xDEADBEEF;return args[0];
}
static unsigned query(uint32_t owner) {
    uint32_t saved_self=g_ecx,saved_sp=g_esp,saved_eax=g_eax;
    g_ecx=owner;g_eax=0xAABBCC01;hardware_hook();
    assert(g_esp==saved_sp+4&&(g_eax&~255u)==0xAABBCC00);
    unsigned result=g_eax&255;g_ecx=saved_self;g_esp=saved_sp;g_eax=saved_eax;return result;
}
static void native_draw(void) {
    uint32_t owner=g_ecx,sp=g_esp;++depth;drawn_x=MEMF(CURSOR_X);drawn_y=MEMF(CURSOR_Y);
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
    /* Native attack/shoot textures keep their own dimensions and hotspots above prediction. */
    MEM32(0x3000)=CURSOR_TABLE;MEM32(CURSOR_TABLE+HARDWARE_SLOT)=HARDWARE_QUERY;
    MEM32(CURSOR_TABLE+0x10)=0x123400;
    gesture.kind=SCREEN_COMBAT;gesture.screen=0x6000;gesture.combat_aim=1;
    /* Original all3 CWindowTextView RTTI: CWindow+0, ITextView+F8, virtual IWindow+13C. */
    MEM32(0x6000+PREDICTION_OFFSET)=0x70F8;MEM32(0x70FC)=0xA100;
    MEM32(0xA100)=0xFFFFFFFC;MEM32(0xA104)=0x30;MEM32(0xA108)=0x40;
    assert(0x70FC+MEM32(0xA108)==0x713C&&MEM32(0x7044)==0);
    MEM32(0x7000)=0xA000;MEM32(0xA008)=0xB000;
    const unsigned char getter[7]={0x8B,0x81,0xAC,0,0,0,0xC3};memcpy(GPTR(0xB000),getter,7);
    MEM32(0x70AC)=0x9000;MEM32(0x9058)=0xC000;MEM32(0x905C)=0xC011;
    memcpy(GPTR(0xC000),"cursor_prediction",17);MEM8(0x9070)=1;
    MEM32(scratch+480)=0x12345678;MEM32(scratch+484)=0x23456789;
    for(option=0;option<2;++option) for(int scale=0;scale<2;++scale) {
      unsigned before_software=software_draws,before_hardware=hardware_draws;
      MEMF(CANVAS_W)=scale?320.0f:640.0f;MEMF(CANVAS_H)=scale?100.0f:200.0f;
      MEMF(0x7064)=scale?40.0f:100.0f;MEMF(0x7068)=scale?40.0f:70.0f;MEMF(0x90A4)=scale?100.0f:200.0f;
      icon_width=scale?64.0f:32.0f;icon_height=scale?24.0f:48.0f;hot_x=scale?11.0f:5.0f;hot_y=scale?19.0f:7.0f;
      float logical_x=touch_cursor_x*MEMF(CANVAS_W)/1280+11;
      float logical_y=touch_cursor_y*MEMF(CANVAS_H)/800-7;
      float center=touch_cursor_x+(MEMF(0x7064)+MEMF(0x90A4)*.5f-logical_x)*1280/MEMF(CANVAS_W);
      float bottom=touch_cursor_y+(MEMF(0x7068)-4-logical_y)*800/MEMF(CANVAS_H);
      g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
      assert(software_draws==before_software+1&&hardware_draws==before_hardware);
      assert(fabsf(drawn_x-hot_x+icon_width*.5f-center)<.001f);
      assert(fabsf(drawn_y-hot_y+icon_height-bottom)<.001f);
      assert(g_ecx==0x3000&&g_esp==1008&&g_eax==0xD00D&&!cursor_software_owner);
      assert(MEMF(CURSOR_X)==touch_cursor_x&&MEMF(CURSOR_Y)==touch_cursor_y);
      assert(MEM32(scratch+480)==0x12345678&&MEM32(scratch+484)==0x23456789);
    }
    assert(rect_queries==4&&cast_calls==4);option=1;
    MEM8(0x9070)=0;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(drawn_x==touch_cursor_x&&drawn_y==touch_cursor_y&&rect_queries==4);
    MEM8(0x9070)=1;MEMF(0x7068)=NAN;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(drawn_x==touch_cursor_x&&drawn_y==touch_cursor_y);
    MEMF(0x7068)=40;gesture.ui=1;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(drawn_x==touch_cursor_x&&drawn_y==touch_cursor_y);
    gesture.ui=0;gesture.placement=1;g_ecx=0x3000;g_esp=1000;touch_cursor_draw();
    assert(drawn_x==touch_cursor_x&&drawn_y==touch_cursor_y);
    /* Default option0: no unrelated cursor and no transient coordinate/register leaks. */
    gesture.placement=0;option=0;
    for(int reason=0;reason<7;++reason) {
      failed_cast=reason==5;missing_cast=reason==6;
      MEM8(0x9070)=reason!=0;MEMF(0x7068)=reason==1?NAN:40;
      gesture.ui=reason==2;gesture.placement=reason==3;gesture.aiming=reason==4;
      MEMF(CURSOR_X)=1234;MEMF(CURSOR_Y)=5678;
      unsigned before_software=software_draws,before_hardware=hardware_draws;
      g_ecx=0x3000;g_eax=0xAABBCCDD;g_esp=1000;touch_cursor_draw();
      assert(software_draws==before_software&&hardware_draws==before_hardware);
      assert(g_ecx==0x3000&&g_eax==0xAABBCCDD&&g_esp==1008&&!cursor_software_owner);
      assert(MEMF(CURSOR_X)==1234&&MEMF(CURSOR_Y)==5678);
      assert(MEM32(scratch+480)==0x12345678&&MEM32(scratch+484)==0x23456789);
    }
    failed_cast=missing_cast=0;
    gesture.ui=gesture.placement=gesture.aiming=0;MEM8(0x9070)=1;MEMF(0x7068)=40;
    /* Physical-mouse mode never substitutes a prediction icon or queries its rectangle. */
    touch_mode=0;unsigned before_rect=rect_queries,before_software=software_draws,before_hardware=hardware_draws;
    g_ecx=0x3000;g_eax=0xAABBCCDD;g_esp=1000;touch_cursor_draw();
    assert(software_draws==before_software&&hardware_draws==before_hardware+1&&rect_queries==before_rect);
    assert(drawn_x==70&&drawn_y==80&&g_ecx==0x3000&&g_esp==1008&&g_eax==0xD00D);
    puts("PASS touch cursor: hardware preference1, software only for verified drawn instance, physical/disabled original path, nested owner restoration, native multiple-inheritance RTTI and failed-cast guards, AL/callee stack ABI, unchanged hardware setting");
}
'''


def cursor_bodies(source):
    return "\n".join(function(source, signature) for signature in (
        "static void touch_cursor_hardware_query(",
        "static void touch_cursor_software_draw(",
        "static uint32_t virtual_base(",
        "static uint32_t window_placement(uint32_t window)\n{",
        "static int touch_cursor_prediction(",
        "static void touch_cursor_draw(",
    ))


class TouchCursorNativeTest(unittest.TestCase):
    def test_hardware_profile_during_touch_and_physical_draw(self):
        for edition, offset in (("toe", 0x4C0), ("vanilla", 0x494), ("hof", 0x4BC)):
            with self.subTest(edition=edition):
                path = ROOT / "android/host/touch_engine.c"
                if edition != "toe":
                    path, _ = port_patches.adapt_host_source(path, ROOT / "build/tests" / ("cursor-" + edition), edition, root=ROOT)
                source = path.read_text(encoding="utf8")
                mapping = {} if edition == "toe" else port_patches.load_contract(edition)["addresses"]
                def address(original):
                    return "0x" + mapping.get(original, original)
                defines = ("#define CURSOR_TABLE " + address("00E49494") + "\n#define CURSOR_DRAW " + address("00836440") +
                           "\n#define HARDWARE_QUERY " + address("00835B90") + "\n#define HARDWARE_SLOT " + ("0x24" if edition == "toe" else "0x28") + "\n" +
                           "#define CURSOR_X " + address("00FE6DA0") + "\n#define CURSOR_Y " + address("00FE6DA4") +
                           "\n#define CANVAS_W " + address("00F74BE0") + "\n#define CANVAS_H " + address("00F74BE4") +
                           "\n#define DYNAMIC_CAST " + address("00D119FC") +
                           "\n#define TYPE_IWINDOW " + address("00F2DAF4") +
                           "\n#define TYPE_CWINDOW " + address("00F2DA88") +
                           "\n#define PREDICTION_OFFSET " + hex(offset) + "\n")
                compile_probe("touch_cursor_native_" + edition,
                              defines + HARNESS.replace("/* ACTUAL */", cursor_bodies(source)), {})



if __name__ == "__main__":
    unittest.main()
