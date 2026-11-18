"""Actual all-edition army-bar selection/layout with distinct IWindow and CWindow subobjects.

The original RTTI and coordinate calls are controlled adapters here. This checks their exact ABI
identities, caller behavior and selection guards; real army ordering is covered by test_touch_army,
and phone appearance is a separate integration gate.
"""
import json
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
from port_patches import adapt_host_source

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
static unsigned char memory[0x40000];
#define ADDR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)ADDR(a))
#define MEM8(a) (*(uint8_t *)ADDR(a))
#define MEMF(a) (*(float *)ADDR(a))
typedef struct {uint32_t window,army,owner,row,command,world,policy;unsigned index,stride;} troop_cell;
typedef struct {uint32_t screen,root;int kind;} touch_gesture;
enum {SCREEN_TOWN=3};
static touch_gesture gesture;
static struct {int mode;} army_batch;
static struct {uint32_t generation,type;troop_cell cell;touch_gesture context;} army_selection;
static uint32_t scratch=0x10000,iw,cw=0x4000,test_place=0x6000,units=22,neighbor_iw;
static unsigned callbacks,cancel_calls,cast_calls,coordinate_calls;
static uint32_t shown_generation;static float shown_x,shown_y,ui_sx,ui_sy,ox,oy;
static int enabled,same,count_valid,current_valid,bad_cast,change_on_cancel;
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static uint32_t read32(uint32_t p){return void_vm_readable(p,4)?MEM32(p):0;}
static uint32_t void_galloc(uint32_t n){assert(n==512);return 0x10000;}
static int same_screen(void){return same;}
static int void_port_army_actions(void){return enabled;}
static int troop_current(troop_cell *cell){assert(cell->window==iw);return current_valid;}
static int troop_count(const troop_cell *cell,uint32_t *count,uint32_t *type){
 assert(cell->window==iw);*count=units;*type=5;return count_valid;
}
static void dnd_cancel(void){++cancel_calls;if(change_on_cancel)same=0;}
static void void_android_army_actions(uint32_t generation,float x,float y){
 ++callbacks;shown_generation=generation;shown_x=x;shown_y=y;
}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *args,int pops){
 assert(va==CAST_VA&&n==5&&!pops&&(args[0]==iw||args[0]==neighbor_iw)&&!args[1]&&args[2]==RTTI_IWINDOW&&args[3]==RTTI_CWINDOW&&!args[4]);
 ++cast_calls;return bad_cast?0:args[0]==iw?cw:0x8000;
}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args){
 assert(va==POINT_VA&&self==scratch&&!n&&!args);++coordinate_calls;
 MEMF(scratch+64)=MEMF(scratch)*ui_sx+ox;MEMF(scratch+68)=MEMF(scratch+4)*ui_sy+oy;
 return scratch+64;
}
/* ACTUAL */
static void setup(uint32_t delta){
 memset(memory,0,sizeof memory);memset(&army_selection,0,sizeof army_selection);
 iw=cw+delta;neighbor_iw=0;enabled=0;same=current_valid=count_valid=1;units=22;bad_cast=change_on_cancel=0;
 army_batch.mode=0;callbacks=cancel_calls=cast_calls=coordinate_calls=0;
 gesture=(touch_gesture){0x2000,0x3000,0};
 MEM32(cw)=0x20000;MEM32(0x20008)=0x31000;
 MEM8(0x31000)=0x8B;MEM8(0x31001)=0x81;MEM32(0x31002)=0x100;MEM8(0x31006)=0xC3;
 MEM32(cw+0x100)=test_place;MEM8(test_place+0x70)=1;
 MEMF(test_place+0xA4)=55;MEMF(test_place+0xA8)=55;
 MEMF(cw+0x64)=238;MEMF(cw+0x68)=327;
 MEM32(iw)=0x22000;MEM32(0x22008)=0x32000;
 MEM8(0x32000)=0x2B;MEM8(0x32001)=0x49;MEM8(0x32002)=0xFC; /* IWindow adjustor, not CWindow's getter. */
 ui_sx=ui_sy=2.8444445f;ox=-13.5f;oy=17.25f;
}
static troop_cell cell(void){troop_cell result={0};result.window=iw;return result;}
int main(void){
 const uint32_t deltas[]={0xF8,0x160,0x178};
 for(unsigned i=0;i<sizeof deltas/sizeof deltas[0];++i){
  setup(deltas[i]);troop_cell source=cell();
  assert(!army_actions_select(&source,94.5f,125)&&!callbacks&&!cast_calls); /* Default off. */
  enabled=1;assert(army_actions_select(&source,94.5f,125));
  assert(callbacks==1&&cast_calls==1&&cancel_calls==1&&coordinate_calls==2);
  assert(shown_generation==1&&army_selection.cell.window==iw&&army_selection.type==5);
  assert(!memcmp(&army_selection.context,&gesture,sizeof gesture));
  assert(fabsf(shown_x-(238+27.5f-ox)/ui_sx)<.002f&&fabsf(shown_y-(327-oy)/ui_sy)<.002f);
  assert(army_selection.cell.window!=cw); /* Layout must never change native cell/command identity. */
  ui_sx=.71f;ui_sy=1.3333334f;ox=122;oy=-80;
  assert(army_actions_select(&source,690.25f,501.75f)&&shown_generation==2);
  assert(fabsf(shown_x-(238+27.5f-ox)/ui_sx)<.002f&&fabsf(shown_y-(327-oy)/ui_sy)<.002f);
  army_selection.generation=0xFFFFFF;
  assert(army_actions_select(&source,94.5f,125)&&shown_generation==1);
 }
 for(unsigned row=0;row<2;++row){
  setup(0x160);enabled=1;gesture.kind=SCREEN_TOWN;neighbor_iw=0x8200;
  troop_cell source=cell();source.row=0x9000+0x100*row;source.index=3;
  MEM32(gesture.screen+TOWN_ROW0)=0x9000;
  MEM32(gesture.screen+(row?TOWN_PORTRAIT0:TOWN_PORTRAIT1))=neighbor_iw;
  MEM32(0x8000)=MEM32(cw);MEM32(0x8100)=0x8400;MEM8(0x8400+0x70)=1;
  MEMF(0x8000+0x68)=row?367.0f:271.0f;
  assert(army_actions_select(&source,94.5f,125)&&callbacks==1&&cast_calls==2);
  assert(fabsf(shown_x-(238+27.5f-ox)/ui_sx)<.002f);
  assert(fabsf(shown_y-((row?327:271)-oy)/ui_sy)<.002f);
  MEM8(0x8400+0x70)=0;MEMF(0x8000+0x68)=0;
  assert(army_actions_select(&source,94.5f,125)&&callbacks==2);
  assert(fabsf(shown_y-(327-oy)/ui_sy)<.002f); /* A hidden companion may have no layout. */
 }
 for(unsigned bad=0;bad<11;++bad){
  setup(0x160);troop_cell source=cell();enabled=1;
  if(bad==0)current_valid=0;if(bad==1)count_valid=0;if(bad==2)units=1;
  if(bad==3)army_batch.mode=1;if(bad==4)bad_cast=1;if(bad==5)same=0;
  if(bad==6)MEM8(0x31000)=0x90;if(bad==7)MEM8(test_place+0x70)=0;
  if(bad==8)ui_sx=0;if(bad==9)ui_sy=-1;if(bad==10)change_on_cancel=1;
  assert(!army_actions_select(&source,94.5f,125)&&!callbacks&&!army_selection.cell.window);
 }
 puts("PASS " EDITION " actual army selection/layout: original IWindow-to-CWindow cast ABI, independent subobject offsets, inverse nonuniform UI transform, native identity retained, generation/ownership/modal/layout guards");
 return 0;
}
'''


class ArmyActionsLayoutTest(unittest.TestCase):
    def test_actual_layout_all_editions(self):
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                path = ROOT / "android/host/touch_engine.c"
                if edition != "toe":
                    path, _ = adapt_host_source(path, ROOT / "build/tests" / ("army-layout-" + edition), edition)
                text = path.read_text(encoding="utf8")
                actual = "\n".join(function(text[text.rfind("\n" + signature):], signature) for signature in (
                    "static uint32_t logical_point(", "static uint32_t window_placement(",
                    "static uint32_t choice_point(", "static uint32_t town_army_row(",
                    "static uint32_t town_army_portrait(", "static int army_actions_select("))
                contract = json.loads((ROOT / "config" / (edition + ".patches.json")).read_text(encoding="utf8"))
                addresses = contract.get("addresses", {}) if edition != "toe" else {}
                mapped = lambda address: int(addresses.get(address, address), 16)
                definitions = "\n".join([
                    '#define EDITION "' + edition + '"',
                    "#define CAST_VA 0x%08Xu" % mapped("00D119FC"),
                    "#define POINT_VA 0x%08Xu" % mapped("00B29220"),
                    "#define RTTI_IWINDOW 0x%08Xu" % mapped("00F2DAF4"),
                    "#define RTTI_CWINDOW 0x%08Xu" % mapped("00F2DA88"),
                    "#define TOWN_ROW0 0x%03Xu" % {"toe": 0x2A8, "vanilla": 0x2A0, "hof": 0x29C}[edition],
                    "#define TOWN_PORTRAIT0 0x%03Xu" % {"toe": 0x2A0, "vanilla": 0x298, "hof": 0x294}[edition],
                    "#define TOWN_PORTRAIT1 0x%03Xu" % {"toe": 0x2A4, "vanilla": 0x29C, "hof": 0x298}[edition],
                ]) + "\n"
                fixture = definitions + HARNESS.replace("/* ACTUAL */", actual)
                compile_probe("army_actions_layout_" + edition, fixture, {})
                # The old interface-as-concrete-layout error must fail as a runtime assertion.
                before = "uint32_t window=void_call_guest(0x%08Xu,5,cast,0);" % mapped("00D119FC")
                self.assertEqual(fixture.count(before), 1)
                with self.assertRaises(AssertionError) as error:
                    compile_probe("army_actions_layout_bad_" + edition,
                                  fixture.replace(before, "(void)cast;uint32_t window=cell->window;"), {})
                self.assertIn("Assertion failed:", str(error.exception))


if __name__ == "__main__":
    unittest.main()
