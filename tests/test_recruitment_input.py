"""Run each original edit-width validator; the fix is resource metadata, not an order bypass."""
from pathlib import Path
import re
import sys
import unittest
import xml.etree.ElementTree as ET

from test_d3d_lifecycle import function
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_windows
import prepare_windows_runtime
import port_ui
from editions import game_directory, generated_root

# Independently located in the three input executables, not an edition delta.
VALIDATORS = {"toe": ("00C3DAE0", "game_0643.c"),
              "vanilla": ("00A7D840", "game_0521.c"),
              "hof": ("00B080E0", "game_0572.c")}

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
enum { EDIT=0x10000, SHARED=0x20000, TEXT=0x30000, FONT=0x40000, GLYPHS=0x41000, STACK=0x80000 };
static unsigned length, frees;
static float field_width, measured_width;
static void fixture_call(unsigned target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#define RECOMP_CALL(fn) fixture_call((unsigned)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((unsigned)(va))
/* ACTUAL */
static void fixture_call(unsigned target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 /* Controlled rectangle/font/string helpers. The width/MaxLength/TextScroll
    decision and the RET/register/x87 paths above are the untouched game body. */
 if(target==RECT) {
  assert(g_ecx==EDIT);uint32_t p=MEM32(g_esp+4);
  MEMF(p)=MEMF(p+4)=0;MEMF(p+8)=field_width;MEMF(p+12)=37;
  g_esp+=8;return;
 }
 if(target==1) {
  uint32_t p=MEM32(g_esp+4);assert(p==TEXT);
  unsigned n=0;while(MEM16(p+2*n))++n;assert(n==length);
  g_eax=n;g_esp+=4;return; /* cdecl wcslen; caller discards its argument. */
 }
 if(target==STRING) {
  assert(MEM32(g_esp+4)==TEXT&&MEM32(g_esp+8)==TEXT+2*length);
  MEM32(g_ecx)=TEXT;MEM32(g_ecx+4)=TEXT+2*length;MEM32(g_ecx+8)=TEXT+2*(length+1);
  g_eax=g_ecx;g_esp+=12;return;
 }
 if(target==MEASURE) {
  assert(g_ecx==EDIT);MEM32(EDIT+0x114)=FONT;
  MEM32(FONT)=MEM32(FONT+4)=GLYPHS;MEM32(GLYPHS)=FONT;MEMF(GLYPHS+0x10)=measured_width;
  g_esp+=8;return;
 }
 if(target==FREE) {assert(MEM32(g_esp+4)==TEXT);++frees;g_esp+=4;return;}
 if(target==ROUND) {g_eax=(uint32_t)(int32_t)MEMF(g_esp+4);g_esp+=8;return;}
 fprintf(stderr,"unexpected callback %08X\n",target);abort();
}
static int accepts(unsigned n,int scrolling,int max_length,float width,float glyph_width) {
 memset(memory,0,sizeof memory);length=n;frees=0;field_width=width;measured_width=n*glyph_width;
 assert(n<64);for(unsigned i=0;i<n;++i)MEM16(TEXT+2*i)=(uint16_t)('0'+i%10);
 MEM32(EDIT+0x134)=TEXT;MEM32(EDIT+0x138)=TEXT+2*n;MEM32(EDIT+0x13C)=TEXT+2*(n+1);
 MEM32(EDIT+0x14C)=SHARED;MEM32(SHARED+0x12C)=(uint32_t)max_length;MEM8(SHARED+0x130)=(uint8_t)scrolling;
 MEM32(IMPORT)=1;MEMF(PADDING)=10;
 g_esp=STACK;g_ecx=EDIT;MEM32(STACK)=RECOMP_RETADDR;
 g_eax=0x11223344;g_ebx=0x22334455;g_esi=0x33445566;g_edi=0x44556677;g_ebp=0x55667788;
 fp_set_cw(0x0C7F);g_fp_sp=128;g_fp_top=0;
 VALIDATE();
 assert(g_esp==STACK+4&&g_ebx==0x22334455&&g_esi==0x33445566&&g_edi==0x44556677&&g_ebp==0x55667788);
 assert(g_fp_sp==128&&g_fp_top==0&&g_fpu_cw==0x0C7F&&frees==1);
 assert(MEM32(EDIT+0x134)==TEXT&&MEM32(EDIT+0x138)==TEXT+2*n);
 assert(MEM32(SHARED+0x12C)==(uint32_t)max_length&&MEM8(SHARED+0x130)==scrolling);
 return (g_eax&255)!=0;
}
int main(void) {
 /* Original 70px field: strict width-minus-10 check, even with unlimited length. */
 assert(accepts(4,0,-1,70,12));assert(!accepts(5,0,-1,70,12));
 for(unsigned n=1;n<=10;++n) {
  assert(accepts(n,1,10,70,12));
  assert(accepts(n,1,10,35,24)); /* Larger text/narrower field is not a quantity limit. */
 }
 assert(!accepts(11,1,10,70,12));assert(!accepts(11,1,10,2000,1));
 assert(!accepts(3,1,2,70,1));assert(accepts(12,1,-1,70,12));
 puts("PASS actual edition edit validator: original width rejection, scroll permits 1-10 digits, independent MaxLength, narrow/large fonts, unchanged text/metadata and RET/GPR/x87 ABI");
 return 0;
}
'''


class RecruitmentInputTest(unittest.TestCase):
    def test_actual_width_validator_each_edition(self):
        core = (ROOT / "android/host/core.c").read_text()
        state = core[core.index("VOID_HIDDEN uint32_t g_eax"):core.index("#define VOID_ENTER_RING")]
        runtime = prepare_windows_runtime.platform_header((ROOT / "android/runtime/recomp_types.h").read_text())
        compiler, _, _ = build_windows.compiler_environment()
        flags = ["/clang:-Wno-unused-variable", "/clang:-Wno-unused-label", "/clang:-Wno-unused-function"]
        for edition, (address, filename) in VALIDATORS.items():
            with self.subTest(edition=edition):
                path = generated_root(edition, ROOT) / "game-x86" / filename
                if not path.is_file():
                    self.skipTest("Original generated input required: " + edition)
                body = function(path.read_text(), "void sub_" + address + "(")
                calls = re.findall(r"RECOMP_CALL\(sub_([0-9A-F]{8})\)", body)
                # ToE rounds the available width; both legacy originals compare it in x87.
                self.assertEqual(len(calls), 7 if edition == "toe" else 6)
                self.assertEqual(calls[3], calls[4])
                self.assertEqual(calls[3], calls[-1])
                constants = dict(zip(("RECT", "STRING", "MEASURE", "FREE", "ROUND"),
                                     (*calls[:4], calls[5] if edition == "toe" else "FFFFFFFF")))
                constants["IMPORT"] = re.search(r"RECOMP_ICALL\(MEM32\(0x([0-9A-F]+)\)\)", body)[1]
                constants["PADDING"] = re.search(r"_st\[0\] -= \(double\)\*\(float\*\)ADDR\(0x([0-9A-F]+)\)", body)[1]
                definitions = "\n".join("#define " + key + " 0x" + value + "u" for key, value in constants.items())
                definitions += "\n#define VALIDATE sub_" + address + "\n"
                harness = PROBE.replace("/* STATE */", state).replace("/* ACTUAL */", definitions + body)
                compile_probe("recruitment-input-" + edition, harness, {"runtime.h": runtime}, flags, compiler)

    def test_original_numeric_resource_overlay_each_edition(self):
        for edition in VALIDATORS:
            with self.subTest(edition=edition):
                resources = port_ui.recruitment_input(game_directory(edition), edition)
                self.assertEqual(len(resources), 1)
                root = ET.fromstring(next(iter(resources.values())))
                self.assertEqual(root.findtext("Name"), "jd_editbox")
                self.assertEqual(root.findtext("TextEntryType"), "ETET_NUMERIC")
                self.assertEqual(root.findtext("TextScroll"), "true")
                self.assertEqual(root.findtext("MaxLength"), "10")


if __name__ == "__main__":
    unittest.main()
