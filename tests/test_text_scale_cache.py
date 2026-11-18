"""Execute each edition's CWindowTextView layout/cache decision, not a font renderer.

The native copy constructor retains the CML and +11C/+120 cache fields. The
fixture models that copy and the rectangle/base-layout/refresh callbacks; it
executes the actual lifted cache decision with the normal generated patches.
"""
from pathlib import Path
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android
import build_windows
import port_patches
import prepare_windows_runtime
from editions import generated_root

# Independently inspected CWindowTextView vtables and layout functions:
# ToE E81BFC/+24 -> B95940; Vanilla E53260/+24 -> B03250;
# HoF E2BCD8/+24 -> B0AEA0. Rect getters are edition-specific IWindow slots.
LAYOUTS = {
    "toe": ("00B95940", "game_0591.c", 0xD4),
    "vanilla": ("00B03250", "game_0569.c", 0xC8),
    "hof": ("00B0AEA0", "game_0574.c", 0xD0),
}

PROBE = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
enum { WINDOW=0x10000, CLONE=0x11000, VB=0x20000, IVT=0x21000, VT=0x22000,
       PARENT_RECT=0x23000, STACK=0x80000, GET_RECT=1, REFRESH=2 };
static uint32_t active=WINDOW;
static unsigned refreshes, base_calls;
static float old_width, new_width, refreshed_x, refreshed_y;
static void fixture_call(unsigned target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#define RECOMP_CALL(fn) fixture_call((unsigned)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((unsigned)(va))
/* ACTUAL */
static void fixture_call(unsigned target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 if(target==GET_RECT) {
  assert(g_ecx==active+0x200);
  uint32_t output=MEM32(g_esp+4);
  MEMF(output)=MEMF(output+4)=0;
  MEMF(output+8)=base_calls?new_width:old_width;MEMF(output+12)=26;
  g_eax=output;g_esp+=8;return;
 }
 if(target==BASE) {
  assert(g_ecx==active&&MEM32(g_esp+4)==PARENT_RECT&&!base_calls);
  ++base_calls;g_esp+=8;return;
 }
 if(target==REFRESH) {
  assert(g_ecx==active&&base_calls==1);
  ++refreshes;
  /* Modeled CML rebuild, not an actual glyph/font acceptance claim. */
  refreshed_x=MEMF(PHYSICAL_X)/MEMF(VIRTUAL_X);
  refreshed_y=MEMF(PHYSICAL_Y)/MEMF(VIRTUAL_Y);
  g_esp+=4;return;
 }
 fprintf(stderr,"unexpected callback %08X\n",target);abort();
}
static void dimensions(float pw,float ph,float vw,float vh) {
 MEMF(PHYSICAL_X)=pw;MEMF(PHYSICAL_Y)=ph;MEMF(VIRTUAL_X)=vw;MEMF(VIRTUAL_Y)=vh;
}
static void layout(float before,float after,unsigned wanted) {
 old_width=before;new_width=after;base_calls=refreshes=0;
 g_esp=STACK;g_ecx=active;MEM32(STACK)=RECOMP_RETADDR;MEM32(STACK+4)=PARENT_RECT;
 g_eax=0x11223344;g_ebx=0x22334455;g_esi=0x33445566;g_edi=0x44556677;g_ebp=0x55667788;
 fp_set_cw(0x0C7F);g_fp_sp=128;g_fp_top=0;
 LAYOUT();
 assert(g_esp==STACK+8&&g_ebx==0x22334455&&g_esi==0x33445566&&g_edi==0x44556677&&g_ebp==0x55667788);
 assert(g_fp_sp==128&&g_fp_top==0&&g_fpu_cw==0x0C7F&&base_calls==1);
 if(refreshes!=wanted)fprintf(stderr,"refreshes %u != %u at physical %.3fx%.3f / virtual %.3fx%.3f\n",refreshes,wanted,MEMF(PHYSICAL_X),MEMF(PHYSICAL_Y),MEMF(VIRTUAL_X),MEMF(VIRTUAL_Y));
 assert(refreshes==wanted);
 if(wanted) {
  assert(refreshed_x==MEMF(PHYSICAL_X)/MEMF(VIRTUAL_X));
  assert(refreshed_y==MEMF(PHYSICAL_Y)/MEMF(VIRTUAL_Y));
 }
}
int main(void) {
 MEM32(WINDOW)=VT;MEM32(VT+4)=REFRESH;
 MEM32(WINDOW+0x10)=VB;MEM32(VB+8)=0x1F0;
 MEM32(WINDOW+0x200)=IVT;MEM32(IVT+RECT_SLOT)=GET_RECT;
 MEMF(WINDOW+0x11C)=MEMF(WINDOW+0x120)=NAN;
 dimensions(2400,1080,1707,768);layout(200,200,1);layout(200,200,0);
 /* An enlarged template is laid out and then cloned with a cached CML. */
 dimensions(2400,1080,1138,512);layout(200,200,1);layout(200,200,0);
 memcpy(GPTR(CLONE),GPTR(WINDOW),0x12C);
 MEM32(CLONE+0x200)=IVT;active=CLONE;
 /* Same physical size and virtual rectangle width: only the scale changed. */
 dimensions(2400,1080,1707,768);layout(200,200,1);layout(200,200,0);
 /* Physical-only resize must not be lost when fixing virtual-only resize. */
 dimensions(1200,540,1707,768);layout(200,200,1);layout(200,200,0);
 dimensions(2400,1080,1707,768);layout(200,200,1);
 /* Independent axes, including a stable width and changing height. */
 dimensions(2400,1080,1724,768);layout(200,200,1);layout(200,200,0);
 dimensions(2400,1080,1724,768.5f);layout(200,200,1);layout(200,200,0);
 /* Width-dependent wrapping is still the original independent invalidation. */
 layout(200,180,1);layout(180,180,0);
 /* Equal pixel/UI-unit ratios need no rebuild despite proportional resize. */
 dimensions(1600,1200,800,600);layout(200,200,1);
 dimensions(800,600,400,300);layout(200,200,0);
 /* Fractional keys must compare at the stored float precision, not thrash. */
 dimensions(2345,987,1234.5f,567.25f);layout(200,200,1);
 for(unsigned i=0;i<16;++i)layout(200,200,0);
 puts("PASS actual edition text layout: virtual/physical-only resize, modeled copied CML cache, independent axes, native wrap invalidation, stable/fractional ratios and RET/GPR/x87 ABI");
 return 0;
}
'''


class TextScaleCacheTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        core = (ROOT / "android/host/core.c").read_text()
        cls.state = core[core.index("VOID_HIDDEN uint32_t g_eax"):core.index("#define VOID_ENTER_RING")]
        cls.runtime = prepare_windows_runtime.platform_header((ROOT / "android/runtime/recomp_types.h").read_text())
        cls.compiler, _, _ = build_windows.compiler_environment()
        cls.flags = ["/clang:-Wno-unused-variable", "/clang:-Wno-unused-label", "/clang:-Wno-unused-function"]

    def actual(self, edition):
        address, filename, slot = LAYOUTS[edition]
        path = generated_root(edition, ROOT) / "game-x86" / filename
        if not path.is_file():
            self.skipTest("Original generated input required: " + edition)
        body = function(path.read_text(), "void sub_" + address + "(")
        body = build_android.round_x87_precision(build_android.guard_fpu_memory(body.encode()))
        body = port_patches.adapt_generated_source(body, "game", edition).decode()
        calls = re.findall(r"RECOMP_CALL\(sub_([0-9A-F]{8})\)", body)
        self.assertEqual(len(calls), 1)
        mapping = port_patches.load_contract(edition).get("addresses", {})
        globals_ = {name: mapping.get(original, original) for name, original in (
            ("VIRTUAL_X", "00F74BE0"), ("VIRTUAL_Y", "00F74BE4"),
            ("PHYSICAL_X", "00F74BF0"), ("PHYSICAL_Y", "00F74BF4"))}
        definitions = "\n".join("#define " + k + " 0x" + v + "u" for k, v in globals_.items())
        definitions += "\n#define BASE 0x" + calls[0] + "u\n#define RECT_SLOT " + str(slot)
        definitions += "\n#define LAYOUT sub_" + address + "\n"
        return definitions, body, globals_

    def probe(self, label, definitions, body):
        harness = PROBE.replace("/* STATE */", self.state).replace("/* ACTUAL */", definitions + body)
        compile_probe("text-scale-cache-" + label, harness, {"runtime.h": self.runtime}, self.flags, self.compiler)

    def test_actual_layout_cache_each_edition(self):
        for edition in LAYOUTS:
            with self.subTest(edition=edition):
                definitions, body, _ = self.actual(edition)
                self.probe(edition, definitions, body)

    def test_bad_keys_fail_at_runtime_each_edition(self):
        for edition in LAYOUTS:
            definitions, body, globals_ = self.actual(edition)
            for mutation in ("physical_only", "virtual_only", "physical_y_only"):
                with self.subTest(edition=edition, mutation=mutation):
                    changed = body
                    for axis in ("X", "Y"):
                        if mutation == "physical_y_only" and axis != "Y":
                            continue
                        physical, virtual = (globals_[kind + axis].lstrip("0") for kind in ("PHYSICAL_", "VIRTUAL_"))
                        ratio = "*(float*)&MEM32(0x" + physical + ") / *(float*)&MEM32(0x" + virtual + ")"
                        self.assertEqual(changed.count(ratio), 2)
                        wrong = ("1.0f / *(float*)&MEM32(0x" + virtual + ")" if mutation == "virtual_only"
                                 else "*(float*)&MEM32(0x" + physical + ")")
                        changed = changed.replace(ratio, wrong)
                    with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                        self.probe(edition + "-" + mutation, definitions, changed)


if __name__ == "__main__":
    unittest.main()
