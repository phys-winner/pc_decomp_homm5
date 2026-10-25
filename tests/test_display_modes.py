"""Execute production D3D9 mode methods and the Android physical-size cache."""
from pathlib import Path
import unittest
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


ENUM_HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#define D3D_OK 0u
#define D3DERR_INVALIDCALL 0x8876086Cu
static uint8_t memory[1024];static uint32_t args[5];
#define MEM32(va) (*(uint32_t *)(memory+(va)))
#define ARG(n) args[n]
#define COM_METHOD(iface,name,argc) static uint32_t iface##_##name(void)
static struct {uint32_t max_texture;} d3d_gl_limits;
static int input_w=640,input_h=480,physical_w=2944,physical_h=1840,physical_valid=1;
static void void_input_screen_size(int*w,int*h){*w=input_w;*h=input_h;}
static int physical_size(int*w,int*h){*w=physical_w;*h=physical_h;return physical_valid;}
static int (*void_android_display_size)(int*,int*)=physical_size;
#include "modes.h"
#include "format.h"
#include "size.h"
#include "extra.h"
#include "count.h"
#include "enum.h"
#include "display.h"
static uint32_t count(uint32_t adapter,uint32_t format){args[1]=adapter;args[2]=format;return d3d9_GetAdapterModeCount();}
static uint32_t mode(uint32_t adapter,uint32_t format,uint32_t index){args[1]=adapter;args[2]=format;args[3]=index;args[4]=64;memset(memory+64,0xA5,16);return d3d9_EnumAdapterModes();}
static void unchanged(void){for(unsigned i=64;i<80;++i)assert(memory[i]==0xA5);}
int main(void){
 const uint32_t legacy[18][2]={{640,480},{800,600},{1024,768},{1152,864},{1280,720},{1280,768},{1280,800},{1280,960},
 {1280,1024},{1360,768},{1366,768},{1440,900},{1560,720},{1600,900},{1600,1200},{1680,1050},{1920,1080},{2340,1080}};
 d3d_gl_limits.max_texture=16384;
 assert(count(0,22)==19&&count(0,23)==19);
 for(unsigned format=22;format<=23;++format){for(unsigned i=0;i<18;++i){
  assert(mode(0,format,i)==D3D_OK);assert(MEM32(64)==legacy[i][0]&&MEM32(68)==legacy[i][1]&&MEM32(72)==60&&MEM32(76)==format);
 }assert(mode(0,format,18)==D3D_OK&&MEM32(64)==2944&&MEM32(68)==1840&&MEM32(76)==format);}
 args[1]=0;args[2]=64;assert(d3d9_GetAdapterDisplayMode()==D3D_OK&&MEM32(64)==2944&&MEM32(68)==1840&&MEM32(72)==60&&MEM32(76)==22);
 assert(!count(1,22)&&!count(0,21)&&!count(0,0));
 assert(mode(1,22,0)==D3DERR_INVALIDCALL);unchanged();assert(mode(0,21,0)==D3DERR_INVALIDCALL);unchanged();
 assert(mode(0,22,19)==D3DERR_INVALIDCALL);unchanged();assert(mode(0,22,UINT32_MAX)==D3DERR_INVALIDCALL);unchanged();
 for(unsigned i=0;i<18;++i){physical_w=(int)legacy[i][0];physical_h=(int)legacy[i][1];assert(count(0,22)==18);assert(mode(0,22,18)==D3DERR_INVALIDCALL);unchanged();}
 physical_w=2560;physical_h=1600;assert(count(0,22)==19);assert(mode(0,22,18)==D3D_OK&&MEM32(64)==2560&&MEM32(68)==1600);
 physical_w=0;assert(count(0,22)==18);assert(mode(0,22,18)==D3DERR_INVALIDCALL);unchanged();
 physical_w=-1;assert(count(0,22)==18);physical_w=INT_MAX;assert(count(0,22)==18);
 physical_w=2944;physical_h=-1;assert(count(0,22)==18);physical_h=1840;d3d_gl_limits.max_texture=2048;assert(count(0,22)==18);
 d3d_gl_limits.max_texture=0;assert(count(0,22)==19);physical_w=8193;assert(count(0,22)==18);
 physical_w=2944;physical_h=1840;physical_valid=0;input_w=1664;input_h=936;assert(count(0,22)==19);
 assert(mode(0,22,18)==D3D_OK&&MEM32(64)==1664&&MEM32(68)==936);
 void_android_display_size=NULL;assert(count(0,23)==19);assert(mode(0,23,18)==D3D_OK&&MEM32(64)==1664&&MEM32(68)==936);
 input_w=0;assert(count(0,22)==18);args[1]=0;args[2]=64;memset(memory+64,0xA5,16);assert(d3d9_GetAdapterDisplayMode()==D3DERR_INVALIDCALL);unchanged();
 puts("PASS actual display modes: native physical source, 18 preserved modes, dedup, formats, bounds, hardware limit, no writes on error, source changes, CLI fallback");return 0;
}
'''

CACHE_HARNESS = r'''
#include <assert.h>
#include <stdio.h>
typedef struct {int w,h;} ANativeWindow;
static ANativeWindow *window;
static int window_lock,depth,display_width,display_height;
static int pthread_mutex_lock(int*p){assert(p==&window_lock&&!depth++);return 0;}
static int pthread_mutex_unlock(int*p){assert(p==&window_lock&&depth--==1);return 0;}
static int ANativeWindow_getWidth(ANativeWindow*p){assert(depth==1&&p==window);return p->w;}
static int ANativeWindow_getHeight(ANativeWindow*p){assert(depth==1&&p==window);return p->h;}
#include "remember.h"
#include "physical.h"
#include "seed.h"
int main(void){
 int w=77,h=88;assert(!void_android_display_size(&w,&h)&&!w&&!h&&!depth);
 start_seed(-1,100);start_seed(1840,2944);assert(!void_android_display_size(&w,&h));
 start_seed(2944,1840);assert(void_android_display_size(&w,&h)&&w==2944&&h==1840);
 start_seed(1024,768);assert(void_android_display_size(&w,&h)&&w==2944&&h==1840);
 display_width=display_height=0;
 ANativeWindow surface={2944,1840};window=&surface;assert(void_android_display_size(&w,&h)&&w==2944&&h==1840&&!depth);
 window=NULL;assert(void_android_display_size(&w,&h)&&w==2944&&h==1840&&!depth);
 ANativeWindow incomplete={0,1600};window=&incomplete;assert(void_android_display_size(&w,&h)&&w==2944&&h==1840);
 incomplete.w=-1;assert(void_android_display_size(&w,&h)&&w==2944&&h==1840);
 incomplete.w=2560;assert(void_android_display_size(&w,&h)&&w==2560&&h==1600&&!depth);
 window=NULL;pthread_mutex_lock(&window_lock);remember_display_size_locked(0,0);pthread_mutex_unlock(&window_lock);
 assert(void_android_display_size(&w,&h)&&w==2560&&h==1600);
 puts("PASS actual physical-size getter: all window access under lock, missing/invalid surface retains valid dimensions, live resize updates both, no backbuffer dependency");return 0;
}
'''


class DisplayModesTest(unittest.TestCase):
    def test_actual_mode_count_enum_and_physical_source(self):
        source = (ROOT / "android/host/d3d9_device.c").read_text(encoding="utf-8")
        table = source[source.index("static const uint32_t modes[][2]"):source.index("COM_METHOD(d3d9, QueryInterface")]
        optional = lambda name: function(source, name) if name in source else ""
        compile_probe("display_modes", ENUM_HARNESS, {
            "modes.h": table, "format.h": function(source, "static int mode_format_ok("),
            "size.h": optional("static int adapter_display_size("), "extra.h": optional("static int extra_display_mode("),
            "count.h": function(source, "COM_METHOD(d3d9, GetAdapterModeCount,"),
            "enum.h": function(source, "COM_METHOD(d3d9, EnumAdapterModes,"),
            "display.h": function(source, "COM_METHOD(d3d9, GetAdapterDisplayMode,"),
        })

    def test_actual_android_window_cache_lifetime(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf-8")
        seed_if = source.index("    if (!display_width && screen_w")
        seed_start = source.rfind("    pthread_mutex_lock(&window_lock);", 0, seed_if)
        seed_end = source.index("    pthread_mutex_unlock(&window_lock);", seed_if) + len("    pthread_mutex_unlock(&window_lock);")
        compile_probe("display_physical", CACHE_HARNESS, {
            "remember.h": function(source, "static void remember_display_size_locked("),
            "physical.h": function(source, "int void_android_display_size("),
            "seed.h": "static void start_seed(int screen_w,int screen_h) {\n" + source[seed_start:seed_end] + "\n}\n",
        })


if __name__ == "__main__":
    unittest.main()
