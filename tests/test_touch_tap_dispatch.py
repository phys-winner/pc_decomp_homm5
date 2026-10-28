"""Execute the actual tap/chord dispatch from all three engine adapters."""
import sys
import unittest

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_patches


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "touch.h"
enum {SCREEN_MENU,SCREEN_ADVENTURE,SCREEN_COMBAT,SCREEN_TOWN};
static struct {int kind,ui,aiming,placement,committed,combat_aim,cancelled;uint32_t screen;} gesture;
static int orders,doubles,homes,blocked,shortcut,announcements,placements,aborts,cancels,reserve=-1;
static int same_screen(void) {return 1;}
static int camera_world(void) {return !gesture.ui&&!gesture.aiming&&!gesture.placement&&
 (gesture.kind==SCREEN_ADVENTURE||gesture.kind==SCREEN_COMBAT);}
static void adventure_camera_home(void) {assert(gesture.kind==SCREEN_ADVENTURE);++homes;}
static void combat_camera_home(void) {assert(gesture.kind==SCREEN_COMBAT);++homes;}
static void publish_point(float x,float y) {assert(x==-1&&y==-1);}
static void ui_event(const void_touch_event *e) {assert(e->kind==TOUCH_ABORT);++aborts;}
static int adventure_announcement(float x,float y,int commit) {(void)x;(void)y;(void)commit;return announcements;}
static int ui_pick(uint32_t screen,float x,float y) {assert(screen==0x1000&&x==41&&y==59);return blocked;}
static void placement_point(float x,float y,int phase) {assert(x==41&&y==59&&phase==2);++placements;}
static void adventure_point(float x,float y,int commit) {assert(x==41&&y==59&&commit);++orders;}
static void adventure_double(float x,float y) {assert(x==41&&y==59);++doubles;}
static void combat_point(float x,float y,int commit) {assert(x==41&&y==59&&commit);++orders;}
static int combat_double(float x,float y) {assert(x==41&&y==59);++doubles;return shortcut;}
static void town_activate(float x,float y) {assert(x==41&&y==59);++orders;}
static uint32_t read32(uint32_t address) {(void)address;return 0x8500;}
/* The only guest call of this dispatch: the placement controller's cancel (edition-mapped address). */
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int count,const uint32_t *args) {
 (void)va;assert(self==0x8500&&!count&&!args&&gesture.placement);++cancels;return 0;
}
/* The tactics reserve slot under the point (-1: none) and its diagnostics. */
static int placement_reserve_slot(float x,float y) {assert(x==41&&y==59);return reserve;}
static void placement_trace(const char *what,float x,float y) {(void)what;assert(x==41&&y==59);}
#include "dispatch.h"
static void reset(int kind) {
 memset(&gesture,0,sizeof gesture);gesture.kind=kind;gesture.screen=0x1000;
 orders=doubles=homes=blocked=shortcut=announcements=placements=aborts=cancels=0;reserve=-1;
}
int main(void) {
 (void)placement_reserve_slot;(void)placement_trace;
 void_touch_event tap={TOUCH_TAP,41,59,0,0,1,0},end={TOUCH_END,41,59,0,0,1,0};
 void_touch_event dbl={TOUCH_DOUBLE_TAP,41,59,0,0,1,0},home={TOUCH_THREE_FINGER_TAP,41,59,0,0,1,0};
 for(int kind=SCREEN_ADVENTURE;kind<=SCREEN_COMBAT;++kind) {
  reset(kind);gesture.combat_aim=kind==SCREEN_COMBAT;tap_dispatch(&tap);
  assert(orders==1&&gesture.committed);tap_dispatch(&end);assert(orders==1);
  reset(kind);shortcut=1;tap_dispatch(&dbl);assert(doubles==1&&orders==(kind==SCREEN_ADVENTURE)&&gesture.committed);
  tap_dispatch(&end);assert(orders==(kind==SCREEN_ADVENTURE));
  reset(kind);blocked=1;tap_dispatch(&tap);assert(!orders&&!doubles);
  reset(kind);gesture.aiming=1;tap_dispatch(&tap);assert(orders==1);
  reset(kind);home_dispatch(&home);assert(homes==1&&!orders&&gesture.cancelled&&gesture.committed);
  tap_dispatch(&end);assert(!orders);
  reset(kind);gesture.ui=1;home_dispatch(&home);assert(!homes&&!orders&&aborts==1&&gesture.cancelled);
  reset(kind);gesture.aiming=1;home_dispatch(&home);assert(!homes&&!orders&&gesture.cancelled);
  reset(kind);gesture.cancelled=1;home_dispatch(&home);assert(!homes&&!orders);
 }
 reset(SCREEN_ADVENTURE);tap_dispatch(&tap);assert(orders==1);tap_dispatch(&end);
 gesture.committed=0;tap_dispatch(&dbl);assert(orders==2&&doubles==1);tap_dispatch(&end);assert(orders==2);
 reset(SCREEN_ADVENTURE);gesture.aiming=1;tap_dispatch(&dbl);assert(orders==1&&!doubles);
 reset(SCREEN_COMBAT);tap_dispatch(&dbl);assert(doubles==1&&orders==1);
 reset(SCREEN_COMBAT);gesture.placement=1;tap_dispatch(&tap);assert(placements==1&&!orders);
 /* Released over interface: cancelled, unless it is a tactics reserve slot, where it drops. */
 reset(SCREEN_COMBAT);gesture.placement=1;blocked=1;tap_dispatch(&tap);
 assert(!placements&&cancels==1&&gesture.cancelled&&!orders);
 reset(SCREEN_COMBAT);gesture.placement=1;blocked=1;reserve=2;tap_dispatch(&tap);
 assert(placements==1&&!cancels&&gesture.cancelled&&!orders);
 reset(SCREEN_TOWN);tap_dispatch(&tap);assert(orders==1);
 reset(SCREEN_MENU);home_dispatch(&home);assert(!homes&&!orders&&gesture.cancelled);
 puts("PASS actual per-edition tap dispatch: immediate single/double, no release replay, chord home and UI/aim guards");
 return 0;
}
'''


class TouchTapDispatchTest(unittest.TestCase):
    def test_actual_dispatch_in_each_edition(self):
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                path = ROOT / "android/host/touch_engine.c"
                if edition != "toe":
                    path, _ = port_patches.adapt_host_source(path,
                        ROOT / "build/tests" / ("tap-dispatch-" + edition), edition)
                source = path.read_text(encoding="utf8")
                start = source.index("    } else if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP ||")
                stop = source.index("\n    if (kind == TOUCH_END)", start)
                tap = source[start:stop].replace("    } else if", "    if", 1)
                start = source.index("    if (kind == TOUCH_THREE_FINGER_TAP) {")
                stop = source.index("    if (kind == TOUCH_SECOND_BEGIN", start)
                home = source[start:stop]
                dispatch = ("static void tap_dispatch(const void_touch_event *event) {\n"
                    "    int kind=event->kind;\n" + tap + "}\n"
                    "static void home_dispatch(const void_touch_event *event) {\n"
                    "    int kind=event->kind;\n" + home + "}\n")
                compile_probe("tap-dispatch-" + edition, HARNESS, {
                    "dispatch.h": dispatch,
                    "touch.h": (ROOT / "android/host/touch.h").read_text(),
                })


if __name__ == "__main__":
    unittest.main()
