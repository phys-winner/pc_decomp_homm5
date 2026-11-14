"""Execute the actual all-edition forecast anchor and duel swipe handlers."""
import re
import unittest

from test_d3d_lifecycle import function
from test_legacy_ported_touch import host_text
from test_static_tls import compile_probe
import port_patches


PREFIX = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
static unsigned char memory[0x1100000];
#define GPTR(p) (memory+(uint32_t)(p))
#define ADDR(p) GPTR(p)
#define MEM32(p) (*(uint32_t *)GPTR(p))
#define MEMF(p) (*(float *)GPTR(p))
typedef void (*void_fn)(void);
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static uint32_t read32(uint32_t p){return void_vm_readable(p,4)?MEM32(p):0;}
'''

FORECAST = r'''
enum {SCREEN_COMBAT=2};
static int touch_mode=1,same=1,binds,calls;
static uint32_t g_ecx,g_esp,g_eax;
typedef struct {uint32_t ecx,esp,eax;} void_regs;
static void void_regs_save(void_regs *r){*r=(void_regs){g_ecx,g_esp,g_eax};}
static void void_regs_load(const void_regs *r){g_ecx=r->ecx;g_esp=r->esp;g_eax=r->eax;}
static struct {int kind,ui,placement,cancelled,combat_aim;uint32_t screen;} gesture={SCREEN_COMBAT,0,0,0,1,0x4000};
static struct {uint32_t generation;} combat_pending;
static void_fn original_prediction_position,hook;
static float actual_x,actual_y;
static int same_screen(void){g_ecx=0xDEAD0000;g_eax=0x4000;return same;}
static void native_position(void){assert(g_ecx==0x713C);++calls;actual_x=MEMF(g_esp+4);actual_y=MEMF(g_esp+8);g_esp+=16;g_eax=0xABCDEF;}
static void_fn void_dispatch_find(uint32_t method){return method==0x123456?native_position:NULL;}
static void void_dispatch_add(uint32_t method,void_fn fn){assert(method==0x123456&&fn);hook=fn;++binds;}
/* HOST */
static void position(float x,float y){g_ecx=0x713C;g_esp=0x10000;MEMF(g_esp+4)=x;MEMF(g_esp+8)=y;MEM32(g_esp+12)=0;
 hook();assert(g_esp==0x10010&&g_eax==0xABCDEF&&MEMF(0x10004)==x&&MEMF(0x10008)==y);}
int main(void){
 MEM32(0x4000+PREDICTION)=0x70F8;MEM32(0x70FC)=0xA100;MEM32(0xA108)=0x40;
 MEM32(0x713C)=0xB000;MEM32(0xB058)=0x123456;
 for(int i=0;i<10;++i)combat_prediction_bind();assert(binds==1&&hook);
 for(int scale=0;scale<5;++scale){float h=768.0f/(.5f+.25f*scale),w=h*2.166667f;MEMF(WIDTH)=w;MEMF(HEIGHT)=h;
  for(int direction=0;direction<8;++direction){position((float)(10+direction*13),(float)(20+direction*17));assert(actual_x==roundf(w*.055f)&&actual_y==roundf(h*.4f));}
 }
 gesture.combat_aim=0;combat_pending.generation=4;position(10,20);assert(actual_y==roundf(MEMF(HEIGHT)*.4f));
 combat_pending.generation=0;position(10,20);assert(actual_x==10&&actual_y==20);gesture.combat_aim=1;
 for(int bad=0;bad<7;++bad){touch_mode=bad!=0;gesture.ui=bad==1;gesture.placement=bad==2;gesture.cancelled=bad==3;same=bad!=4;
  MEMF(HEIGHT)=bad==5?NAN:768;MEM32(0x4000+PREDICTION)=bad==6?0:0x70F8;
  position(10,20);assert(actual_x==10&&actual_y==20);
 }
 puts("PASS forecast: fixed position across eight directions and five scales, pending preview, original mouse/modal/stale behavior and callee ABI");return 0;
}
'''

DUEL = r'''
typedef struct {float x,y,dx,dy;} void_touch_event;
static struct {uint32_t screen,scroll_slider;float start_x,start_y,scroll_value;} gesture={0x4000,0,100,200,0};
static float mock_value,fp[8];static int g_fp_top,notifies,sets,index,mock_steps=3,named=1,has_listener=1;
#define g_st fp
static double fp_pop_impl(float *s,int *top){return s[--*top];}
static uint32_t ui_pick(uint32_t screen,float x,float y){assert(screen==0x4000&&x==100&&y==200);return 0x6800;}
static uint32_t logical_point(float x,float y){MEMF(0x10000)=x*.5f;MEMF(0x10004)=y*.5f;return 0x10000;}
static uint32_t window_placement(uint32_t w){return w==0xD000?0xE000:0;}
static int choice_named(uint32_t w,const char *name){return named&&w==0xB000&&!strcmp(name,"presets_grid");}
static uint32_t choice_child(uint32_t w,const char *name){assert(w==0xB000);return !strcmp(name,"table_slider")?0xC000:!strcmp(name,"line_0")?0xD000:0;}
static uint32_t void_call_guest(uint32_t method,int n,const uint32_t *a,int pops){assert(method==CAST&&n==5&&!pops&&a[2]==IWINDOW);
 return a[3]==CWINDOW?0xB000:0;}
static int void_dispatch_find(uint32_t method){return method>=0x7010&&method<=0x7070;}
static uint32_t void_call_guest_this(uint32_t method,uint32_t self,int n,const uint32_t *args){
 if(method==0x7010){assert(self==0xC0F8&&!n);return (uint32_t)mock_steps;}
 if(method==0x7020){assert(self==0xC0F8&&!n);fp[g_fp_top++]=mock_value;return 0;}
 if(method==0x7030){assert(self==0xC0F8&&n==1);memcpy(&mock_value,args,4);mock_value=fminf(100,fmaxf(0,mock_value));++sets;return 0;}
 if(method==0x7040){assert(self==0xC0F8&&!n);return 0xCAFE00;}
 if(method==0x7050){assert(self==0xF000&&n==2&&args[1]==0xC000&&has_listener);++notifies;index=(int)roundf(mock_value*(mock_steps-1)/100);
  mock_value=100.0f*index/(mock_steps-1);return 0;}
 assert(method==0x7060&&self==0x6800&&!n);return 0;
}
/* HOST */
int main(void){
 MEM32(0x6800)=0xA000;MEM32(0xA0D8)=0x7060;
 MEM32(0xC0F8)=0xA100;MEM32(0xA100+STEPS)=0x7010;MEM32(0xA110)=0x7020;MEM32(0xA10C)=0x7030;MEM32(0xA118)=0x7040;
 MEM32(0xC118)=0xC800;MEM32(0xC938)=0xF000;MEM32(0xF000)=0xA200;MEM32(0xA200)=0x7050;MEMF(0xE0A8)=68;
 /* Slow motion must accumulate despite the native callback quantizing its thumb each frame. */
 void_touch_event e={100,200,0,-2};for(int i=0;i<68;++i)assert(ui_scroll(&e));
 assert(index==1&&notifies==68&&sets==68&&!g_fp_top);
 for(int i=0;i<300;++i)assert(ui_scroll(&e));assert(index==2&&gesture.scroll_value==100);
 e.dy=2;for(int i=0;i<400;++i)assert(ui_scroll(&e));assert(index==0&&gesture.scroll_value==0);
 int before=notifies;named=0;assert(!ui_scroll(&e)&&notifies==before);named=1;
 mock_steps=1;assert(ui_scroll(&e)&&notifies==before);mock_steps=3;
 MEMF(0xE0A8)=NAN;assert(ui_scroll(&e)&&notifies==before);MEMF(0xE0A8)=68;
 MEM32(0xC938)=0;has_listener=0;assert(!ui_scroll(&e)&&notifies==before);
 puts("PASS duel swipe: native row listener, slow-motion accumulation, both directions, clamped ends, no click/selection synthesis, malformed/empty guards");return 0;
}
'''


class PlanningControlsTest(unittest.TestCase):
    def test_controls_all_editions(self):
        for edition, prediction in (("toe",0x4C0),("vanilla",0x494),("hof",0x4BC)):
            with self.subTest(edition=edition):
                source=host_text(edition)
                mapping=port_patches.load_contract(edition)["addresses"]
                def mapped(address):return int(mapping.get(f"{address:08X}",f"{address:08X}"),16)
                defines=f"#define PREDICTION {prediction}\n#define WIDTH {mapped(0xF74BE0)}\n#define HEIGHT {mapped(0xF74BE4)}\n"
                common=function(source,"static uint32_t object_method(uint32_t object, unsigned offset)\n{")
                forecast=common+''.join(function(source,signature) for signature in (
                    "static uint32_t virtual_base(uint32_t object, unsigned slot)\n{",
                    "static void touch_prediction_position(void)\n{","static void combat_prediction_bind(void)\n{"))
                compile_probe("forecast-anchor-"+edition,PREFIX+defines+FORECAST.replace("/* HOST */",forecast),{})
                with self.assertRaisesRegex(AssertionError, "g_ecx==0x713C"):
                    compile_probe("forecast-register-negative-"+edition,
                                  PREFIX+defines+FORECAST.replace("/* HOST */",forecast.replace("void_regs_load(&saved);", "")),{})
                defines=f"#define CAST {mapped(0xD119FC)}\n#define IWINDOW {mapped(0xF2DAF4)}\n#define CWINDOW {mapped(0xF2DA88)}\n"
                defines+=f"#define STEPS {0x28 if edition=='vanilla' else 0x24}\n"
                scroll=common+function(source,"static int ui_scroll(const void_touch_event *event)\n{")
                compile_probe("duel-scroll-"+edition,PREFIX+defines+DUEL.replace("/* HOST */",scroll),{})


if __name__ == "__main__":unittest.main()
