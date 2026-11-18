"""Cutout conversion/hero-only anchoring, plus the production root-layout integration."""
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_touch_scale import HARNESS

sys.path.insert(0, str(ROOT / "tools"))
import port_patches

PROBE = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEMF(a) (*(float *)GPTR(a))
#define MEM8(a) (*GPTR(a))
typedef int pthread_mutex_t;
static pthread_mutex_t scale_lock;
static int locked;
static void pthread_mutex_lock(int *p){(void)p;assert(!locked++);}
static void pthread_mutex_unlock(int *p){(void)p;assert(!--locked);}
static struct {int width,height,edge[4];} safe_pending,safe_current;
static float safe_active[4];
static uint32_t safe_root;
static struct {uint32_t screen;} viewport;
static int buffer_w=2400,buffer_h=1080;
static void void_input_screen_size(int *w,int *h){*w=buffer_w;*h=buffer_h;}
static int void_vm_readable(uint32_t p,uint32_t n){return p>0&&(uint64_t)p+n<=sizeof memory;}
/* ACTUAL */
static void near(float a,float b){if(fabsf(a-b)>.0002f)fprintf(stderr,"%.4f != %.4f\n",a,b);assert(fabsf(a-b)<.0002f);}
int main(void){
 viewport.screen=0x20000;MEM32(viewport.screen)=HERO;safe_root=0x10000;
 const float views[][2]={{1707,768},{1365.6f,614.4f},{853.5f,384},{3414,1536}};
 void_touch_safe_area(2400,1080,96,16,48,20);
 assert(!safe_current.width&&!safe_active[0]&&!locked);safe_current=safe_pending;
 for(unsigned v=0;v<4;++v){
  float w=views[v][0],h=views[v][1],edge[4];scale_cutout_insets(viewport.screen,w,h,edge);
  near(edge[0],ceilf(w*.04f));near(edge[1],ceilf(h*16/1080));
  near(edge[2],ceilf(w*.02f));near(edge[3],ceilf(h*20/1080));
  memcpy(safe_active,edge,sizeof edge);
  /* Root's actual position need not equal its supplied parent origin (+7,+9). */
  float parent[4]={edge[0]+7,edge[1]+9,fmaxf(w,1024)-edge[2]+7,fmaxf(h,768)-edge[3]+9};
  float position[2],size[2],shift[2];
  MEMF(0x30A4)=80;MEMF(0x30A8)=64;
  for(unsigned mode=0;mode<4;++mode){
   MEM32(0x309C)=mode;MEM32(0x3094)=mode;
   scale_place_safe(safe_root,0x3000,parent,parent,w,h,position,size,shift);
   for(int axis=0;axis<2;++axis){
    float lo=position[axis]+shift[axis],view=axis?h:w;
    assert(lo>=edge[axis]-.0002f);
    if(size[axis]<=view-edge[axis]-edge[axis+2])assert(lo+size[axis]<=view-edge[axis+2]+.0002f);
   }
  }
  /* The same placement on an unrelated modal root is not translated/inset. */
  float plain[4]={0,0,w,h};MEM32(0x309C)=MEM32(0x3094)=0;
  scale_place_safe(safe_root+0x1000,0x3000,plain,plain,w,h,position,size,shift);
  near(position[0]+shift[0],0);near(position[1]+shift[1],0);
 }
 /* Live HoF UI100 regression: HeroPage_Self is a structural 396x768 page
    with resource position (60,125), centered vertically. Its trailing empty
    area intentionally extends below the canvas. A cutout must not turn that
    native Y offset into zero, including on an axis with no cutout at all.
    The +7,+9 origin also exercises the original setter's actual rectangle. */
 const int sides[][4]={{93,0,0,0},{0,0,93,0},{0,16,0,0},{0,0,0,20},{96,16,48,20}};
 MEMF(0x30A4)=396;MEMF(0x30A8)=768;MEMF(0x3088)=60;MEMF(0x308C)=125;
 MEM32(0x309C)=0;MEM32(0x3094)=1;
 for(unsigned side=0;side<5;++side)for(unsigned v=0;v<4;++v){
  void_touch_safe_area(2400,1080,sides[side][0],sides[side][1],sides[side][2],sides[side][3]);
  safe_current=safe_pending;
  float w=views[v][0],h=views[v][1],edge[4];scale_cutout_insets(viewport.screen,w,h,edge);
  memcpy(safe_active,edge,sizeof edge);
  float parent[4]={edge[0]+7,edge[1]+9,fmaxf(w,1024)-edge[2]+7,fmaxf(h,768)-edge[3]+9};
  float position[2],size[2],shift[2];
  scale_place_safe(safe_root,0x3000,parent,parent,w,h,position,size,shift);
  float native_y=scale_native_position(1,parent[1],parent[3]-parent[1],125,0,768);
  if(h>=767.5f)near(position[1]+shift[1],native_y);
  else near(position[1]+shift[1],edge[1]); /* Keep genuinely reduced-canvas anchoring. */
  near(size[1],768);near(MEMF(0x308C),125);near(MEMF(0x30A8),768);
 }
 void_touch_safe_area(2400,1080,96,16,48,20);safe_current=safe_pending;
 /* Cutouts in letterbox bars do not remove any of the horizontal UI area. */
 buffer_w=1920;buffer_h=1080;scale_cutout_insets(viewport.screen,1366,768,safe_active);
 near(safe_active[0],0);near(safe_active[2],0);near(safe_active[1],12);near(safe_active[3],15);
 buffer_w=1440;scale_cutout_insets(viewport.screen,1024,768,safe_active);near(safe_active[0],0);near(safe_active[2],0);
 MEM32(viewport.screen)=0;scale_cutout_insets(viewport.screen,1707,768,safe_active);
 for(int i=0;i<4;++i)near(safe_active[i],0);
 assert(!scale_safe_owner(safe_root));
 /* Invalid JNI bounds leave the last good publication intact. */
 for(unsigned bad=0;bad<7;++bad){
  if(bad==0)void_touch_safe_area(0,1080,0,0,0,0);
  if(bad==1)void_touch_safe_area(2400,20000,0,0,0,0);
  if(bad==2)void_touch_safe_area(2400,1080,-1,0,0,0);
  if(bad==3)void_touch_safe_area(2400,1080,2400,0,0,0);
  if(bad==4)void_touch_safe_area(2400,1080,1200,0,1200,0);
  if(bad==5)void_touch_safe_area(2400,1080,0,540,0,540);
  if(bad==6)void_touch_safe_area(2400,1080,0,0,0,-1);
  assert(safe_pending.width==2400&&safe_pending.edge[0]==96&&safe_pending.edge[3]==20&&!locked);
 }
 puts("PASS actual edition hero cutout: record-only JNI publication, UI50/100/125/200, all anchors, both edges, native origin, unrelated roots/pointer reuse, letterbox bars and invalid bounds");
 return 0;
}
'''

ROOT_PROBE = r'''
    {
    backbuffer_w=2400;backbuffer_h=1080;dimensions(2400,1080,1707,768);
    MEM32(0x22000)=0xE3584C;viewport.root=0;void_touch_set_scale(1);
    uint32_t p0=MEM32(elements[0]+0x140),p1=MEM32(elements[1]+0x140);
    for(unsigned i=0;i<5;++i){
        uint32_t p=MEM32(elements[i]+0x140);MEM8(p+0x70)=(uint8_t)(i<2);
        MEMF(p+0xA4)=80;MEMF(p+0xA8)=64;
        MEMF(p+0x88)=MEMF(p+0x8C)=MEMF(p+0xB0)=MEMF(p+0xB4)=MEMF(p+0xBC)=MEMF(p+0xC0)=0;
    }
    MEM32(p0+0x9C)=MEM32(p0+0x94)=0;MEM32(p1+0x9C)=MEM32(p1+0x94)=2;
    void_touch_safe_area(2400,1080,96,16,48,20);pump();
    near(MEMF(0xF74BE0),1707);near(MEMF(0xF74BE4),768);
    near(viewport.rect[0],69);near(viewport.rect[1],12);near(viewport.rect[2],1707-35);near(viewport.rect[3],768-15);
    assert(safe_root==0x24000-0xF8&&fit.requested==100&&scale_percent==100);
    assert(MEMF(elements[0]+0x64)>=69&&MEMF(elements[0]+0x68)>=12);
    near(MEMF(elements[1]+0x64)+80,1707-35);near(MEMF(elements[1]+0x68)+64,768-15);
    int calls=viewport_calls;
    for(int i=0;i<8;++i)pump();assert(viewport_calls==calls); /* No repeated native relayout. */
    void_touch_safe_area(2400,1080,0,0,96,0);pump();
    assert(viewport_calls==calls+1);near(viewport.rect[0],0);near(viewport.rect[2],1707-69);
    near(MEMF(elements[1]+0x64)+80,1707-69);
    void_touch_safe_area(2400,1080,0,0,0,0);pump();assert(!safe_root);
    near(viewport.rect[0],0);near(viewport.rect[2],1707);
    calls=viewport_calls;for(int i=0;i<8;++i)pump();assert(viewport_calls==calls);
    /* A full-height hero page is not a screen-sized modal to be clamped to Y0.
       Exercise the frame pump and dispatch path independently, all four sides,
       native origin offsets, unchanged metadata, idle and complete removal. */
    uint32_t header=elements[2],hp=MEM32(header+0x140);
    MEM8(hp+0x70)=1;MEMF(hp+0xA4)=396;MEMF(hp+0xA8)=768;
    MEM32(hp+0x9C)=0;MEM32(hp+0x94)=1;MEMF(hp+0x88)=60;MEMF(hp+0x8C)=125;
    memcpy(GPTR(0x7C100),"HeroPage_Self",13);MEM32(hp+0x58)=0x7C100;MEM32(hp+0x5C)=0x7C10D;
    const int edges[][4]={{93,0,0,0},{0,0,93,0},{0,16,0,0},{0,0,0,20},{0,0,0,0}};
    for(unsigned edge=0;edge<5;++edge){
        void_touch_safe_area(2400,1080,edges[edge][0],edges[edge][1],edges[edge][2],edges[edge][3]);pump();
        float parent[4];assert(scale_rect(root,parent));
        float expected_y=native_axis(1,parent[1],parent[3]-parent[1],125,0,768);
        near(MEMF(header+0x68),expected_y);
        layout_through_override(header,parent);near(MEMF(header+0x68),expected_y);
        /* Merely having an active safe root must not activate UI100 anchoring
           for a retained window of a different root during native dispatch. */
        uint32_t other=0x65000,op=0x65400;
        MEM32(other)=0x71000;MEM32(other+0x140)=op;MEM32(other+0x28)=0x25000-0xF8;
        MEM8(op+0x70)=1;MEM32(op+0x94)=1;MEMF(op+0xA4)=396;MEMF(op+0xA8)=768;MEMF(op+0x8C)=125;
        MEMF(0x73000+0xA4)=1707;MEMF(0x73000+0xA8)=768;
        const float plain[4]={0,0,1707,768};layout_through_override(other,plain);
        near(MEMF(other+0x68),125);
        int layouts=lifted_layouts;
        for(int idle=0;idle<8;++idle){pump();near(MEMF(header+0x68),expected_y);}
        assert(lifted_layouts==layouts);near(MEMF(hp+0x8C),125);near(MEMF(hp+0xA8),768);
        near(MEMF(0xF74BE0),1707);near(MEMF(0xF74BE4),768);
    }
    puts("PASS actual root cutout integration at UI100: full canvas, native parent/children and full-height hero offset, pump/dispatch paths, four sides, idempotence and removal");
    }
'''


class HeroSafeAreaTest(unittest.TestCase):
    def test_cutout_and_anchors_all_edition_schemas(self):
        signatures = ("static uint32_t scale_read32(", "static float scale_native_position(",
                      "static float scale_clamp(", "static float scale_anchor_shift(", "static int scale_named(",
                      "static float scale_size(", "static void scale_cutout_insets(", "static int scale_safe_owner(",
                      "void void_touch_safe_area(", "static void scale_place(", "static void scale_place_safe(")
        for edition, hero in {"toe": "00E3584C", "vanilla": "00E13F0C", "hof": "00DE93D4"}.items():
            with self.subTest(edition=edition):
                path = ROOT / "android/host/touch_scale.c"
                if edition != "toe":
                    self.assertEqual(port_patches.load_contract(edition)["addresses"]["00E3584C"], hero)
                    path, _ = port_patches.adapt_host_source(path, ROOT / "build/tests" / ("hero-safe-" + edition), edition)
                source = path.read_text(encoding="utf8")
                actual = "\n".join(function(source, name) for name in signatures)
                compile_probe("hero-safe-" + edition, PROBE.replace("/* ACTUAL */", actual), {}, ["/DHERO=0x" + hero])

    def root_fixture(self):
        source = (ROOT / "android/host/touch_scale.c").read_text(encoding="utf8")
        for name in ("host.h", "input.h", "touch.h"):
            source = source.replace('#include "' + name + '"\n', "")
        source = "\n".join(line for line in source.splitlines() if not line.startswith("extern int void_android_"))
        # This derived fixture admits the deliberately inset parent; the original
        # no-cutout suite still enforces its old >=1024x768 parent invariant.
        harness = HARNESS.replace('assert(rect[2]-rect[0]>=1024&&rect[3]-rect[1]>=768);',
                                  'assert(rect[2]-rect[0]>=400&&rect[3]-rect[1]>=300);')
        marker = '    puts("PASS native UI scale:'
        self.assertEqual(harness.count(marker), 1)
        harness = harness.replace(marker, ROOT_PROBE + marker)
        return harness, source

    def test_native_root_and_children_keep_full_width_canvas(self):
        harness, source = self.root_fixture()
        compile_probe("hero-safe-root", harness, {"touch_scale_impl.h": source})

    def test_native_root_regressions_fail_at_runtime(self):
        harness, source = self.root_fixture()
        mutants = {
            "unreduced_axis_fit": (
                "if ((axis ? view_h >= 767.5f : view_w >= 1023.5f)) shift[axis] = 0;",
                "/* Reintroduce ordinary fitting on a native-sized axis. */"),
            "clamp_axis_without_cutout": (
                "if ((safe_active[axis] || safe_active[axis + 2]) && size[axis] <= inner_view[axis])",
                "if (size[axis] <= inner_view[axis])"),
            "unrelated_owner_fit": (
                " ||\n        (!reduced && !scale_safe_owner(owner))", ""),
            "fit_after_inset_removal": (
                "if (root && safe_root) (void)scale_fits(root - 0xF8, 1, wanted_w, wanted_h, base_w, base_h, requested);",
                "if (root) (void)scale_fits(root - 0xF8, 1, wanted_w, wanted_h, base_w, base_h, requested);"),
        }
        for label, (old, new) in mutants.items():
            with self.subTest(mutation=label):
                self.assertEqual(source.count(old), 1)
                # Compile errors must not satisfy the negative control.
                with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                    compile_probe("hero-safe-root-" + label, harness,
                                  {"touch_scale_impl.h": source.replace(old, new)})


if __name__ == "__main__":
    unittest.main()
