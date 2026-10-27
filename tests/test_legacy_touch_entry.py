"""Exercise the real gesture entry against original-engine screen objects."""
import re
import sys
import unittest

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_patches


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
static unsigned char memory[0x10000];
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
enum {SCREEN_MENU, SCREEN_ADVENTURE, SCREEN_COMBAT, SCREEN_TOWN};
enum {TOUCH_BEGIN};
typedef struct {int kind;float x,y;} void_touch_event;
static struct {uint32_t screen,root,controller,dnd;unsigned begin_frame;
 int active,dnd_pressed,ui,kind,book,announcement,dnd_claim;float start_x,start_y,x,y;} gesture;
static unsigned army_batch,touch_frame;
static struct {int pending;} pointer_text;
static struct {int valid;} combat_home;
static uint32_t selected=0x1000,expected_controller;
static int selected_kind,claims;
static uint32_t current_screen(void) {return selected;}
static int screen_kind(uint32_t s) {assert(s==selected);return selected_kind;}
static uint32_t read32(uint32_t a) {assert(a+4<=sizeof memory);return MEM32(a);}
static int void_vm_readable(uint32_t a,unsigned n) {return a && a+n<=sizeof memory;}
static void dnd_owner_pump(int abort) {assert(!abort);}
static void dnd_cancel(void) {}
static void ui_release(int abort) {(void)abort;}
static int spellbook_kind(uint32_t s) {assert(s==selected);return 0;}
static int ui_method(uint32_t s,unsigned slot) {assert(s==selected&&slot==0x28);return 1;}
static int adventure_announcement(float x,float y,int action) {(void)x;(void)y;assert(!action);return 0;}
static int ui_pick(uint32_t s,float x,float y) {(void)x;(void)y;assert(s==selected);return 0;}
static int dnd_held(uint32_t helper) {assert(helper==0x3000);return 0;}
static int dnd_claim_at(uint32_t helper,float x,float y) {
 assert(helper==0x3000&&x==41&&y==59);++claims;return 1;
}
#include "entry.h"
int main(void) {
 void_touch_event e={TOUCH_BEGIN,41,59};
 for(selected_kind=0;selected_kind<4;++selected_kind) {
  memset(memory,0xCD,sizeof memory);memset(&gesture,0,sizeof gesture);
  MEM32(selected+0x98)=0x2000;
  MEM32(selected+ADV_CONTROLLER)=0x4000;
  MEM32(selected+COMBAT_CONTROLLER)=0x5000;
  MEM32(selected+0x144)=0x2800;MEM32(0x2800)=0x2800;
  MEM32(selected+0x148)=0x3000;MEM32(0x3000)=DND_VTABLE;
  expected_controller=selected_kind==SCREEN_ADVENTURE?0x4000:selected_kind==SCREEN_COMBAT?0x5000:0;
  claims=0;entry(&e);
  assert(gesture.root==0x2000&&gesture.controller==expected_controller);
  assert(claims==1&&gesture.dnd==0x3000&&gesture.dnd_claim&&gesture.ui);
  assert(same_screen()&&ui_idle()&&dnd_identity(0x3000));
  MEM32(selected+0x98)=0;assert(!same_screen()&&!dnd_identity(0x3000));
  MEM32(selected+0x98)=0x2000;MEM32(0x2800)=0x2900;assert(!ui_idle());
  MEM32(selected+0x148)=0;assert(!dnd_identity(0x3000));
 }
 puts("PASS actual gesture entry: original root/controller/pending/DnD fields and stale-object rejection");
 return 0;
}
'''


def function(source, name):
    match = re.search(r"^static [^\n]+\b" + name + r"\([^;]*?\n\{\n.*?^\}\n", source, re.M | re.S)
    assert match, name
    return match[0]


class LegacyTouchEntryTest(unittest.TestCase):
    def source(self, edition):
        source, _ = port_patches.adapt_host_source(ROOT / "android/host/touch_engine.c",
            ROOT / "build/tests" / ("legacy-touch-entry-" + edition), edition)
        source = source.read_text()
        begin = source.index("    if (event->kind == TOUCH_BEGIN) {", source.index("void void_touch_engine_event("))
        stop = source.index("        gesture.ghost_energy =", begin)
        return (function(source, "same_screen") + function(source, "ui_idle") +
                function(source, "dnd_identity") + "static void entry(const void_touch_event *event)\n{\n" +
                source[begin:stop] + "    }\n}\n")

    def run_probe(self, edition, source, suffix=""):
        adventure, combat, table = (("0x56C", "0x294", "0x00E24364u") if edition == "vanilla"
                                   else ("0x578", "0x2A8", "0x00DF8814u"))
        # These native member offsets come from the original screen constructor,
        # controller getters and CWindowScreen DnD ownership, not the adapter.
        flags = ["/DADV_CONTROLLER=" + adventure, "/DCOMBAT_CONTROLLER=" + combat,
                 "/DDND_VTABLE=" + table, "/wd4505"]
        compile_probe("legacy-touch-entry-" + edition + suffix, HARNESS,
                      {"entry.h": source}, flags)

    def test_actual_entry_and_shared_owner_lifecycle(self):
        for edition in ("vanilla", "hof"):
            with self.subTest(edition=edition):
                self.run_probe(edition, self.source(edition))

    def test_toe_controller_or_dnd_layout_is_rejected(self):
        for edition in ("vanilla", "hof"):
            with self.subTest(edition=edition):
                source = self.source(edition)
                for old, wrong in (("gesture.screen + 0x148", "gesture.screen + 0x150"),
                                   ("gesture.screen + 0x98", "gesture.screen + 0xA0")):
                    self.assertIn(old, source)
                    with self.assertRaises(AssertionError):
                        self.run_probe(edition, source.replace(old, wrong), "-wrong-" + wrong[-4:])


if __name__ == "__main__":
    unittest.main()
