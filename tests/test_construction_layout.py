"""Actual layout wrapper / native boundary model for construction root-owned arrows.

The original builders (ToE 65AAE0, Vanilla 620C70, HoF 626330) put arrows on
IScreen, using positions read from building windows inside BuildingsHolder.
This probe models native placement/RTTI/SetPlacement, not end-to-end gameplay.
"""
import re
import sys
import unittest
from pathlib import Path

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_patches

PROBE = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM32(p) (*(uint32_t*)GPTR(p))
#define MEMF(p) (*(float*)GPTR(p))
#define MEM8(p) (*GPTR(p))
#define VLOG(...) ((void)0)
typedef void (*void_fn)(void);
static uint32_t g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp;
static unsigned guest_flags,guest_fp;
typedef struct { uint32_t regs[8]; unsigned flags,fp; } void_regs;
static void void_regs_save(void_regs *s){
 uint32_t v[]={g_eax,g_ebx,g_ecx,g_edx,g_esi,g_edi,g_ebp,g_esp};
 memcpy(s->regs,v,sizeof v);s->flags=guest_flags;s->fp=guest_fp;
}
static void void_regs_load(const void_regs *s){
 g_eax=s->regs[0];g_ebx=s->regs[1];g_ecx=s->regs[2];g_edx=s->regs[3];
 g_esi=s->regs[4];g_edi=s->regs[5];g_ebp=s->regs[6];g_esp=s->regs[7];guest_flags=s->flags;guest_fp=s->fp;
}
static int void_vm_readable(uint32_t p,size_t n){return p>0&&(uint64_t)p+n<=sizeof memory;}
static int void_vm_writable(uint32_t p,size_t n){return void_vm_readable(p,n);}
static uint32_t void_galloc(size_t n){assert(n<=128);return 0xD0000;}
static struct {uint32_t screen;} viewport,fit;
static float safe_active[4];static uint32_t safe_root,viewport_scratch;
static uint32_t void_call_guest(uint32_t,unsigned,const uint32_t*,unsigned);
static uint32_t void_call_guest_this(uint32_t,uint32_t,unsigned,const uint32_t*);
static void marker(void){}
static void_fn void_dispatch_find(uint32_t target){return target==RTTI||target==SETTER?marker:NULL;}
/* ACTUAL */
enum { SCREEN=0x10000, ROOT_WINDOW=0x20000, HOLDER=0x22000, ARROW1=0x24000,
       ARROW2=0x26000, OTHER=0x28000, BUILDING=0x2A000, WINDOW_TABLE=0x30000,
       GETTER_CODE=0x31000, ROOT_TABLE=0x32000, IFACE_TABLE=0x33000,
       ROOT_VECTOR=0x34000, NEW_VECTOR=0x35000, HOLDER_VECTOR=0x36000,
       PLACE_BASE=0x40000, NAME_BASE=0x50000, STACK=0x80000, PARENT=0x90000 };
static unsigned casts,sets,allow_cast=1,interface_offset=0x160;
static void near(float a,float b){if(fabsf(a-b)>.0002f)fprintf(stderr,"%.4f != %.4f\n",a,b);assert(fabsf(a-b)<.0002f);}
static void clobber(void){g_eax=g_ecx=g_edx=0xBAD12345;g_esp=0xBAD0;guest_flags=0xBAD1;guest_fp=0xBAD2;}
static uint32_t void_call_guest(uint32_t target,unsigned count,const uint32_t *args,unsigned cdecl_call){
 assert(target==RTTI&&count==5&&!cdecl_call&&args[1]==0&&args[2]==CWINDOW&&args[3]==IWINDOW&&args[4]==0);
 assert(args[0]==ARROW1||args[0]==ARROW2);++casts;clobber();
 return allow_cast?args[0]+interface_offset:0;
}
static uint32_t void_call_guest_this(uint32_t target,uint32_t self,unsigned count,const uint32_t *args){
 assert(target==SETTER&&count==5&&args[2]==0&&args[3]==0&&args[4]==3);
 assert(self==ARROW1+interface_offset||self==ARROW2+interface_offset);
 uint32_t window=self-interface_offset,old=MEM32(window+0x140),owned=PLACE_BASE+0x1000+sets*0x100;
 assert(old!=owned);memcpy(GPTR(owned),GPTR(old),0xC4);MEM32(window+0x140)=owned;
 memcpy(GPTR(owned+0x88),args,8);MEMF(window+0x64)=MEMF(owned+0x88);MEMF(window+0x68)=MEMF(owned+0x8C);
 /* A native callback can replace the root's vector storage. */
 memcpy(GPTR(NEW_VECTOR),GPTR(ROOT_VECTOR),5*4);MEM32(ROOT_WINDOW+0xA4)=NEW_VECTOR;MEM32(ROOT_WINDOW+0xA8)=NEW_VECTOR+5*4;
 ++sets;clobber();return 0;
}
void native_layout(void){
 uint32_t window=g_ecx,placement=MEM32(window+0x140),parent=MEM32(g_esp+4);
 for(unsigned axis=0;axis<2;++axis){
  uint32_t mode=MEM32(placement+(axis?0x94:0x9C));float span=MEMF(parent+8+4*axis)-MEMF(parent+4*axis);
  MEMF(window+0x64+4*axis)=scale_native_position(mode,MEMF(parent+4*axis),span,MEMF(placement+0x88+4*axis),0,MEMF(placement+0xA4+4*axis));
 }
 g_eax=0x13572468;g_ecx=0x24681357;g_edx=0x12344321;g_esp+=8;guest_flags=0x5678;guest_fp=0xC7F;
}
static uint32_t place(uint32_t window,const char *name,unsigned index,uint32_t parent,float x,float y,float w,float h,unsigned vertical){
 uint32_t p=PLACE_BASE+index*0x100,s=NAME_BASE+index*0x100;
 MEM32(window)=WINDOW_TABLE;MEM32(window+0x140)=p;MEM32(window+0x28)=parent;
 MEM32(p+0x58)=s;MEM32(p+0x5C)=s+(uint32_t)strlen(name);memcpy(GPTR(s),name,strlen(name));
 MEM8(p+0x70)=1;MEMF(p+0x88)=x;MEMF(p+0x8C)=y;MEMF(p+0xA4)=w;MEMF(p+0xA8)=h;MEM32(p+0x94)=vertical;
 MEMF(window+0x64)=x;MEMF(window+0x68)=y;return p;
}
static void setup(void){
 memset(memory,0,sizeof memory);casts=sets=0;allow_cast=1;safe_root=0;viewport_scratch=0;
 viewport.screen=fit.screen=SCREEN;MEM32(SCREEN)=TOWN_BUILD;MEM32(SCREEN+ROOT_OFFSET)=ROOT_WINDOW+0xF8;
 MEM32(SCREEN+IDLE_OFFSET)=0xB0000;MEM32(0xB0000)=0xB0000;
 MEM32(ROOT_WINDOW+0xF8)=ROOT_TABLE;MEM32(ROOT_TABLE+0x48)=ROOT_SETTER;MEM32(ROOT_TABLE+0x4C)=ROOT_TAIL;
 MEM32(WINDOW_TABLE+8)=GETTER_CODE;const unsigned char getter[]={0x8B,0x81,0x40,1,0,0,0xC3};memcpy(GPTR(GETTER_CODE),getter,sizeof getter);
 place(ROOT_WINDOW,"",0,0,0,0,1138,512,0);
 place(HOLDER,"",1,ROOT_WINDOW,60,45,512,768,1);MEMF(HOLDER+0x68)=-83;
 place(ARROW1,"arrow_1",2,ROOT_WINDOW,131,94,38,30,0);
 place(ARROW2,"arrow_2",3,ROOT_WINDOW,204,110,42,90,0);MEM8(PLACE_BASE+3*0x100+0x70)=0;
 place(OTHER,"other",4,ROOT_WINDOW,777,110,42,90,0);
 place(BUILDING,"building_1_1",5,HOLDER,58,113,64,64,0);
 MEM32(HOLDER+0xA4)=HOLDER_VECTOR;MEM32(HOLDER+0xA8)=HOLDER_VECTOR+4;MEM32(HOLDER_VECTOR)=BUILDING;
 uint32_t children[]={HOLDER,ARROW1,OTHER,ARROW2,BUILDING};memcpy(GPTR(ROOT_VECTOR),children,sizeof children);
 /* The fifth entry is not a direct child of this root and must be ignored. */
 MEM32(ROOT_WINDOW+0xA4)=ROOT_VECTOR;MEM32(ROOT_WINDOW+0xA8)=ROOT_VECTOR+sizeof children;
 MEM32(ARROW1+interface_offset)=MEM32(ARROW2+interface_offset)=IFACE_TABLE;MEM32(IFACE_TABLE+0x58)=SETTER;
 MEMF(PARENT)=MEMF(PARENT+4)=0;MEMF(PARENT+8)=1138;MEMF(PARENT+12)=768;
 MEMF(VIRTUAL_X)=1138;MEMF(VIRTUAL_Y)=512;
}
static void layout(void){
 g_esp=STACK;g_ecx=HOLDER;MEM32(STACK+4)=PARENT;g_eax=g_ebx=g_edx=g_esi=g_edi=g_ebp=0x44556677;guest_flags=guest_fp=0;
 scale_layout_override();
 assert(g_eax==0x13572468&&g_ecx==0x24681357&&g_edx==0x12344321&&g_esp==STACK+8);
 assert(g_ebx==0x44556677&&g_esi==0x44556677&&g_edi==0x44556677&&g_ebp==0x44556677&&guest_flags==0x5678&&guest_fp==0xC7F);
}
int main(void){
 const unsigned offsets[]={0xF8,0x160,0x178};
 for(unsigned i=0;i<3;++i){
  interface_offset=offsets[i];setup();
  /* Native -83 -> anchored 0, then native UI100 Y45: cached root-owned
     arrows must follow both steps, without a hard-coded 128px correction. */
  layout();near(MEMF(HOLDER+0x68),0);near(MEMF(ARROW1+0x68),177);near(MEMF(ARROW2+0x68),193);
  assert(sets==2&&casts==2);near(MEMF(PLACE_BASE+2*0x100+0x8C),94); /* COW template unchanged. */
  MEMF(VIRTUAL_X)=1707;MEMF(VIRTUAL_Y)=768;MEMF(PARENT+8)=1707;MEMF(MEM32(ROOT_WINDOW+0x140)+0xA4)=1707;MEMF(MEM32(ROOT_WINDOW+0x140)+0xA8)=768;
  layout();near(MEMF(HOLDER+0x68),45);near(MEMF(ARROW1+0x68),222);near(MEMF(ARROW2+0x68),238);assert(sets==4);
  layout();assert(sets==4);near(MEMF(OTHER+0x68),110);near(MEMF(MEM32(ARROW2+0x140)+0xA8),90);assert(!MEM8(MEM32(ARROW2+0x140)+0x70));
  /* Follow actual horizontal/fractional movement, not a fixed Y-only fix. */
  MEMF(MEM32(HOLDER+0x140)+0x88)=87.5f;MEMF(MEM32(HOLDER+0x140)+0x8C)=46.25f;
  layout();near(MEMF(ARROW1+0x64),158.5f);near(MEMF(ARROW1+0x68),223.25f);near(MEMF(ARROW2+0x68),239.25f);assert(sets==6);
  layout();assert(sets==6);near(MEMF(PLACE_BASE+2*0x100+0x8C),94);
 }
 /* Unrelated screen, wrong owner, invalid building name and non-native origin
    are all fail-closed. No persistent pointer/offset cache survives reuse. */
 for(unsigned bad=0;bad<5;++bad){
  setup();
  if(bad==0)MEM32(SCREEN)=0x12345678;
  if(bad==1)MEM32(SCREEN+ROOT_OFFSET)=ROOT_WINDOW+0x10F8;
  if(bad==2){MEM32(PLACE_BASE+5*0x100+0x5C)=NAME_BASE+5*0x100+8;memcpy(GPTR(NAME_BASE+5*0x100),"building",8);}
  if(bad==3)MEMF(ROOT_WINDOW+0x64)=7;
  if(bad==4)allow_cast=0;
  layout();assert(!sets);near(MEMF(ARROW1+0x68),94);
 }
 puts("PASS actual edition layout/follower: two-step fit, hidden arrows, native COW setter, RTTI interface identity, vector replacement, idempotence, ownership/fail-closed guards and preserved native return state");
 return 0;
}
'''


class ConstructionLayoutTest(unittest.TestCase):
    def fixture(self, edition):
        source = ROOT / "android/host/touch_scale.c"
        path, _ = port_patches.adapt_host_source(source, ROOT / ("build/tests/construction-layout-" + edition), edition)
        text = port_patches.legacy_ui_branch(path.read_bytes().replace(b"\r\n", b"\n"), edition != "toe").decode()
        start = text.index("static uint32_t scale_placement(")
        stop = text.index("\ntypedef struct {", start)
        actual = "\n".join(function(text, signature) for signature in (
            "static uint32_t scale_read32(", "static uint32_t scale_root(",
            "static uint32_t scale_screen_root(", "static int scale_safe_owner(")) + text[start:stop]
        mapping = port_patches.load_contract(edition).get("addresses", {})
        va = lambda original: mapping.get(original, original)
        constants = {
            "RTTI": va("00D119FC"), "CWINDOW": va("00F2DA88"), "IWINDOW": va("00F2DAF4"),
            "TOWN_BUILD": {"toe": "00E2D9D4", "vanilla": "00E0BCCC", "hof": "00DE205C"}[edition],
            "ROOT_SETTER": va("00487990"), "ROOT_TAIL": va("00488330"),
            "VIRTUAL_X": va("00F74BE0"), "VIRTUAL_Y": va("00F74BE4"), "SETTER": "00000042",
        }
        definitions = "\n".join("#define " + k + " 0x" + v + "u" for k, v in constants.items()) + "\n"
        definitions += "#define ROOT_OFFSET " + ("0xA0" if edition == "toe" else "0x98") + "\n"
        definitions += "#define IDLE_OFFSET " + ("0x14C" if edition == "toe" else "0x144") + "\n"
        definitions += "#define sub_" + va("00A50560") + " native_layout\n"
        return definitions, actual, constants

    def probe(self, label, definitions, actual):
        compile_probe("construction-layout-" + label, definitions + PROBE.replace("/* ACTUAL */", actual), {}, ["/wd4505"])

    def test_actual_layout_follows_holder_all_editions(self):
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                definitions, actual, _ = self.fixture(edition)
                self.probe(edition, definitions, actual)

    def test_regressions_fail_at_runtime_all_editions(self):
        for edition in ("toe", "vanilla", "hof"):
            definitions, actual, constants = self.fixture(edition)
            cast = ("        const uint32_t cast[] = {child, 0, 0x" + constants['CWINDOW'] + "u, 0x" + constants['IWINDOW'] + "u, 0};\n"
                    "        uint32_t window = void_call_guest(0x" + constants['RTTI'] + "u, 5, cast, 0);")
            changes = {
                "no_follow": ("    scale_town_arrows(window, root, dx, dy);", "    (void)window;"),
                "raw_interface": (cast, "        uint32_t window = child;"),
                "unrelated_screen": ("    if (scale_read32(fit.screen) != 0x" + constants['TOWN_BUILD'] + "u) return 0;", "    (void)fit.screen;"),
                "no_native_state_restore": ("    void_regs_load(&saved);", "    (void)saved;"),
            }
            for label, (old, new) in changes.items():
                with self.subTest(edition=edition, mutation=label):
                    self.assertEqual(actual.count(old), 1)
                    with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                        self.probe(edition + '-' + label, definitions, actual.replace(old, new))

    def test_original_holder_and_arrow_names_all_editions(self):
        import xml.etree.ElementTree as ET
        from editions import game_directory
        from port_ui import source_resource
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                game = game_directory(edition)
                if not game.is_dir():
                    self.skipTest("Licensed original resources required: " + edition)
                raw, _ = source_resource(game, "UI/TownBuildNew/BuldingsHolder.(WindowSimple).xdb", edition)
                holder = ET.fromstring(raw)
                self.assertEqual(holder.findtext("Name"), "")
                self.assertEqual(holder.findtext("Placement/Position/First/x"), "60")
                self.assertEqual(holder.findtext("Placement/Position/First/y"), "45")
                for index in range(1, 4):
                    raw, _ = source_resource(game, "UI/TownBuildNew/BuildingsHolder/Arrows/Arrow_" + str(index) + ".(WindowSimple).xdb", edition)
                    self.assertEqual(ET.fromstring(raw).findtext("Name"), "arrow_" + str(index))


if __name__ == "__main__":
    unittest.main()
