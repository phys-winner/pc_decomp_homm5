"""Execute contextual hint detection and HUD cancellation with each edition's real layout."""
import json
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_patches


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "touch.h"
#define VLOG(...) ((void)0)
static unsigned char memory[0x10000];
#define MEM8(p) (memory[(uint32_t)(p)])
#define MEM32(p) (*(uint32_t *)(memory+(uint32_t)(p)))
enum {SCREEN_MENU,SCREEN_ADVENTURE,SCREEN_COMBAT,SCREEN_TOWN};
static struct {
 int kind,ui,committed,cancelled,combat_aim,placement;
 uint32_t screen,controller;
} gesture;
static int selected_kind,console_enabled,same=1,counts[6];
static int allowed=1,blocked,eligible=1,guest_checks,creature=1;
static int stops,cancels,combat_cancels,releases,cards,hidden;
static uint32_t targets[]={TARGET_A,TARGET_B,TARGET_C};
static int void_vm_readable(uint32_t address,uint32_t size){return address>=0x100&&(uint64_t)address+size<=sizeof memory;}
static uint32_t read32(uint32_t address){return void_vm_readable(address,4)?MEM32(address):0;}
static uint32_t current_screen(void){return 0x1000;}
static int screen_kind(uint32_t screen){assert(screen==0x1000);return selected_kind;}
int void_port_console_enabled(void){return console_enabled;}
static void void_android_touch_hint(int id){assert(id>=1&&id<=5);counts[id]++;}
static uint32_t virtual_base(uint32_t actor,uint32_t offset){assert(offset==4);return actor==0x3000?0x3100:0;}
static uint32_t object_query(uint32_t actor,uint32_t offset){assert(actor==0x3000&&offset==CREATURE_SLOT);return creature?0x3200:0;}
static int same_screen(void){return same;}
static void ui_release(int abort){assert(abort);releases++;}
static void combat_card_end(void){cards++;}
static void publish_point(float x,float y){assert(x==-1&&y==-1);hidden++;}
static void combat_cancel(void){
 assert(gesture.kind==SCREEN_COMBAT);combat_cancels++;
 for(unsigned i=0;i<3;++i)MEM32(gesture.screen+targets[i])=0;
}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args){
 if(self==0x1000){
  guest_checks++;
  if(va==0x00511890u){assert(n==0&&!args);return eligible;}
  assert(n==1&&args[0]==0x3000);
  if(va==VA_ALLOWED)return allowed;
  assert(va==VA_BLOCKED);return blocked;
 }
 assert(self==0x2000);
 if(va==VA_MODE){assert(n==1&&args[0]==3);return MEM32(self+MODE)==3;}
 assert(n==0&&!args);
 if(va==VA_STOP)stops++;
 else {assert(va==VA_CANCEL);cancels++;}
 MEM32(self+MODE)=0;return 1;
}
#define touch_hint_pump hint_adventure
#include "hint.h"
#undef touch_hint_pump
#define touch_hint_pump hint_combat_a
#include "hint.h"
#undef touch_hint_pump
#define touch_hint_pump hint_combat_b
#include "hint.h"
#undef touch_hint_pump
#define touch_hint_pump hint_combat_c
#include "hint.h"
#undef touch_hint_pump
#define touch_hint_pump hint_first_turn
#include "hint.h"
#undef touch_hint_pump
#include "cancel.h"
static void reset(int kind){
 memset(memory,0,sizeof memory);memset(counts,0,sizeof counts);memset(&gesture,0,sizeof gesture);
 selected_kind=kind;console_enabled=0;same=1;allowed=eligible=creature=1;blocked=guest_checks=0;stops=cancels=combat_cancels=releases=cards=hidden=0;
 gesture.kind=kind;gesture.screen=0x1000;gesture.controller=0x2000;
 MEM32(0x1000+ADV_CONTROLLER)=0x2000;
}
int main(void){
 reset(SCREEN_MENU);hint_adventure();assert(!counts[1]&&!counts[2]&&!counts[3]&&!counts[4]);
 selected_kind=SCREEN_TOWN;hint_adventure();hint_adventure();assert(counts[4]==1);
 selected_kind=SCREEN_ADVENTURE;hint_adventure();assert(!counts[2]&&!counts[3]);
 console_enabled=1;hint_adventure();hint_adventure();assert(counts[2]==1&&!counts[1]);
 MEM32(0x2000+MODE)=3;hint_adventure();hint_adventure();assert(counts[3]==1&&!counts[1]);
 MEM32(0x2000+MODE)=5;hint_adventure();hint_adventure();assert(counts[1]==1&&counts[2]==1&&counts[3]==1&&counts[4]==1);
 void (*combat_pumps[3])(void)={hint_combat_a,hint_combat_b,hint_combat_c};
 for(unsigned i=0;i<3;++i){
  reset(SCREEN_COMBAT);MEM32(0x1000+PHASE)=0x1000;MEM32(0x1000+targets[i])=42;
  combat_pumps[i]();assert(!counts[1]&&counts[4]==1); // Deployment is not a selected ability.
  MEM32(0x1000+PHASE)=0x188;combat_pumps[i]();combat_pumps[i]();
  assert(counts[1]==1&&counts[4]==1&&!counts[2]&&!counts[3]);
 }
 reset(SCREEN_COMBAT);MEM32(0x1000+ACTOR)=0x3000;MEM32(0x1000+PHASE)=0x1000;
 hint_first_turn();assert(!counts[5]&&!guest_checks); // Deployment never consumes the first-turn hint.
 MEM32(0x1000+PHASE)=0x200;hint_first_turn();assert(!counts[5]&&!guest_checks); // Animation/command dispatch.
 MEM32(0x1000+PHASE)=0x188;MEM32(0x1000+UI_MODE)=1;hint_first_turn();assert(!counts[5]&&!guest_checks);
 MEM32(0x1000+UI_MODE)=0;MEM32(0x1000+ACTOR)=0;hint_first_turn();assert(!counts[5]);
 MEM32(0x1000+ACTOR)=0x3000;MEM8(0x3107)=0x80;hint_first_turn();assert(!counts[5]); // Expired actor reference.
 MEM8(0x3107)=0;creature=0;hint_first_turn();assert(!counts[5]); // A hero without the creature interface is not a troop.
 creature=1;allowed=0;hint_first_turn();assert(!counts[5]); // Opposing/AI-controlled side.
 allowed=1;blocked=1;eligible=0;hint_first_turn();assert(!counts[5]); // Ownership/animation native gate.
 blocked=0;eligible=1;hint_first_turn();assert(counts[5]==1);
 int first_turn_checks=guest_checks;hint_first_turn();hint_first_turn();assert(counts[5]==1&&guest_checks==first_turn_checks);
 MEM32(0x1000+PHASE)=0x1000;hint_first_turn();MEM32(0x1000+PHASE)=0x188;hint_first_turn();
 assert(counts[5]==1&&guest_checks==first_turn_checks); // No per-frame native calls after showing it.
 void_touch_event pair={.kind=TOUCH_TWO_FINGER_TAP,.scale=1};
 for(int ui=0;ui<=1;++ui){
  reset(SCREEN_ADVENTURE);gesture.ui=ui;MEM32(0x2000+MODE)=5;
  assert(target_armed());cancel_dispatch(&pair);
  assert(cancels==1&&!stops&&!combat_cancels&&releases==ui&&cards==1&&hidden==1&&gesture.committed&&gesture.cancelled);
  cancel_dispatch(&pair);assert(cancels==1); // No command or duplicate cancellation after release.
  reset(SCREEN_ADVENTURE);gesture.ui=ui;MEM32(0x2000+MODE)=3;cancel_dispatch(&pair);
  assert(stops==1&&!cancels&&!combat_cancels&&releases==ui&&gesture.cancelled);
  reset(SCREEN_ADVENTURE);gesture.ui=ui;cancel_dispatch(&pair);
  assert(!stops&&!cancels&&!gesture.cancelled&&!releases&&!hidden);
  for(unsigned i=0;i<3;++i){
   reset(SCREEN_COMBAT);gesture.ui=ui;gesture.combat_aim=1;MEM32(0x1000+targets[i])=42;
   assert(target_armed());cancel_dispatch(&pair);
   assert(combat_cancels==1&&!cancels&&!stops&&releases==ui&&cards==1&&hidden==1&&gesture.cancelled&&!gesture.combat_aim);
  }
 }
 reset(SCREEN_ADVENTURE);MEM32(0x2000+MODE)=5;same=0;cancel_dispatch(&pair);
 assert(!cancels&&!releases&&!hidden&&!gesture.cancelled);
 puts("PASS actual per-edition contextual hint offsets, deployment exclusion, once-per-session requests and UI/world command cancellation");
 return 0;
}
'''


class TouchHintNativeTest(unittest.TestCase):
    def test_actual_all_edition_hints_and_cancel_dispatch(self):
        # Independent constructor/controller field facts, matching target_armed's established layout.
        fields = {
            "toe": (0x5F4, 0x44, 0x2E0, 0x394, 0x388, 0x38C, 0x2AC, 0x2D4),
            "vanilla": (0x56C, 0x3C, 0x2D8, 0x380, 0x374, 0x378, 0x28C, 0x2CC),
            "hof": (0x578, 0x44, 0x2F0, 0x398, 0x38C, 0x390, 0x2A0, 0x2E4),
        }
        for edition, values in fields.items():
            with self.subTest(edition=edition):
                path = ROOT / "android/host/touch_engine.c"
                if edition != "toe":
                    path, _ = port_patches.adapt_host_source(path, ROOT / "build/tests" / ("hint-adapter-" + edition), edition)
                source = path.read_text(encoding="utf8")
                hint = function(source, "static void touch_hint_pump(void)")
                helpers = "\n".join(function(source, signature) for signature in (
                    "static int target_armed(void)", "static int adventure_stop(void)", "static void adventure_cancel(void)"))
                start = source.index("    if (kind == TOUCH_TWO_FINGER_TAP && same_screen()) {")
                stop = source.index("    if (gesture.card &&", start)
                helpers += "\nstatic void cancel_dispatch(const void_touch_event *event) {\nint kind=event->kind;\n" + source[start:stop] + "}\n"
                addresses = json.loads((ROOT / "config" / (edition + ".patches.json")).read_text(encoding="utf8")).get("addresses", {})
                defines = [f"#define {name} 0x{value:X}u" for name, value in zip(
                    ("ADV_CONTROLLER", "MODE", "PHASE", "TARGET_A", "TARGET_B", "TARGET_C", "ACTOR", "UI_MODE"), values)]
                defines += ["#define CREATURE_SLOT 0x%Xu" % {"toe": 0x6C, "vanilla": 0x64, "hof": 0x04}[edition]]
                defines += ["#define %s 0x%sU" % (name, addresses.get(address, address)) for name, address in (
                    ("VA_MODE", "00603370"), ("VA_STOP", "00604D60"), ("VA_CANCEL", "00604E20"),
                    ("VA_ALLOWED", "0053E3D0"), ("VA_BLOCKED", "0053FBE0"))]
                compile_probe("touch-hint-native-" + edition, "\n".join(defines) + "\n" + HARNESS, {
                    "hint.h": hint, "cancel.h": helpers,
                    "touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf8"),
                })


if __name__ == "__main__":
    unittest.main()
