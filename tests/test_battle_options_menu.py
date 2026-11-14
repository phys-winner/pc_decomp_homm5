"""Run battle menu entry with each edition's original category navigation body."""
import json
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_legacy_ui import build_android, build_windows, prepare_windows_runtime


PROBE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x10000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
enum {SCREEN_MENU,SCREEN_ADVENTURE,SCREEN_COMBAT};
static uint32_t screen=0x1000;static int kind=SCREEN_MENU,calls,page_actions;
static int launcher_pending,launcher_question_seen,switch_confirm_pending;
static unsigned visible[3];
static uint32_t current_screen(void){return screen;}
static uint32_t read32(uint32_t p){assert(p<sizeof memory-4);return p?MEM32(p):0;}
static int screen_kind(uint32_t p){(void)p;return kind;}
static void port_launcher_visibility(uint32_t p,unsigned depth,int value){assert(p==0x6000-0xF8&&!depth);(void)value;}
static int void_android_take_game_switch(void){return 0;}
static void void_android_return_to_launcher(void){assert(0);}
static uint32_t void_call_guest(uint32_t va,unsigned n,const uint32_t *args,int callee){(void)va;(void)n;(void)args;(void)callee;assert(0);return 0;}
static void change_category(void){assert(g_ecx==0x1000&&MEM32(g_esp+4)==0&&MEM32(g_esp+8)==2);g_esp+=12;}
static void page_state(void){assert(g_ecx==0x1000&&MEM32(g_esp+4)==0x8200);++page_actions;g_esp+=12;}
static void show(void){assert(g_ecx>=0x3000&&g_ecx<=0x5000&&g_ecx%0x1000==0);visible[g_ecx/0x1000-3]=MEM32(g_esp+4);g_esp+=8;}
recomp_func_t void_resolve(uint32_t va){assert(va==0xF0001);return show;}
/* ORIGINAL */
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,unsigned n,const uint32_t *args){
 assert(va==MENU_FUNCTION&&self==0x1000&&n==1);++calls;
 g_esp=0xF000;g_ecx=self;PUSH32(g_esp,args[0]);PUSH32(g_esp,RECOMP_RETADDR);
 original_menu();assert(g_esp==0xF000);return g_eax;
}
/* PUMP */
int main(void){
 MEM32(0x1000)=OPTIONS_TABLE;MEM32(0x1000+ROOT_OFFSET)=0x6000;
 MEM32(0x1000+MODE_OFFSET)=2;MEM32(0x1000+SELECTED_OFFSET)=0;
 MEM32(0x1000+LIST_OFFSET)=0x7000;MEM32(0x1000+LIST_OFFSET+4)=0x700C;
 MEM32(0x7000)=0x8000;MEM32(0x7004)=0x8100;MEM32(0x7008)=0x8200;
 MEM32(0x8018)=0x4000;MEM32(0x1000+MENU_OFFSET)=0x3000;MEM32(0x1000+DETAIL_OFFSET)=0x5000;
 for(unsigned at=0x3000;at<=0x5000;at+=0x1000)MEM32(at)=0x9000;
 MEM32(0x9044)=0xF0001;visible[1]=visible[2]=1;
 assert(!visible[0]); /* Negative control: original battle entry leaves only category zero visible. */
 port_menu_pump();assert(calls==1&&visible[0]==1&&!visible[1]&&!visible[2]);
 assert(MEM32(0x1000+MODE_OFFSET)==2&&MEM32(0x1000+SELECTED_OFFSET)==0);
 port_menu_pump();assert(calls==1);
 const uint32_t additional=2;void_call_guest_this(MENU_FUNCTION,0x1000,1,&additional);
 assert(MEM32(0x1000+SELECTED_OFFSET)==2&&page_actions==2);
 port_menu_pump();assert(calls==2); /* User's chosen category is never overwritten. */
 MEM32(0x1000)=0;port_menu_pump();MEM32(0x1000)=OPTIONS_TABLE;port_menu_pump();assert(calls==2); /* A modal round-trip keeps selection. */
 MEM32(0x1000)=0;kind=SCREEN_COMBAT;port_menu_pump();kind=SCREEN_MENU;
 MEM32(0x1000)=OPTIONS_TABLE;MEM32(0x1000+SELECTED_OFFSET)=0;port_menu_pump();assert(calls==3);
 MEM32(0x1000)=0;kind=SCREEN_ADVENTURE;port_menu_pump();kind=SCREEN_MENU;
 MEM32(0x1000)=OPTIONS_TABLE;MEM32(0x1000+MODE_OFFSET)=1;port_menu_pump();assert(calls==3);
 puts("PASS actual battle options menu: all categories visible, original navigation ABI, battle restrictions preserved, no repeat/modal reset");return 0;
}
'''


class BattleOptionsMenuTest(unittest.TestCase):
    def test_original_category_navigation_all_editions(self):
        source = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf-8")
        pump = function(source, "static void port_menu_pump(void)")
        state = (ROOT / "android/host/core.c").read_text(encoding="utf-8")
        state = state[state.index("VOID_HIDDEN uint32_t g_eax"):state.index("#define VOID_ENTER_RING")]
        header = prepare_windows_runtime.platform_header((ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8"))
        compiler, _, _ = build_windows.compiler_environment()
        editions = {
            "toe": (0x75C030, 0x75BD30, 0x75BAC0, 0xE3DA1C, 0xA0, 0x1BC, 0x1A0, 0x1A4, 0x188, 0x198),
            "vanilla": (0x70AEA0, 0x70AA70, 0x70A800, 0xE1C2F4, 0x98, 0x1B4, 0x198, 0x19C, 0x180, 0x190),
            "hof": (0x706D30, 0x706A20, 0x706740, 0xDF1184, 0x98, 0x1B0, 0x194, 0x198, 0x17C, 0x18C),
        }
        for edition, values in editions.items():
            with self.subTest(edition=edition):
                address, change, page, table, root, mode, selected, listing, menu, detail = values
                directory = ROOT / "generated" / ("" if edition == "toe" else edition) / "game-x86"
                report = json.loads((directory / "report.json").read_text())
                entries = [int(value, 0) for value in report["dispatch_entries"]]
                path = directory / report["sources"][entries.index(address) // 100]
                generated = build_android.round_x87_precision(build_android.guard_fpu_memory(path.read_bytes())).decode()
                body = function(generated, f"void sub_{address:08X}(void)")
                for target, name in ((address, "original_menu"), (change, "change_category"), (page, "page_state")):
                    body = body.replace(f"sub_{target:08X}", name)
                adapted = pump.replace("0x0075C030u", f"0x{address:08X}u").replace("0x00E3DA1Cu", f"0x{table:08X}u")
                for before, after in (("0xA0", root), ("0x1BC", mode), ("0x1A0", selected)):
                    adapted = adapted.replace("screen + " + before, f"screen + 0x{after:X}")
                defines = dict(MENU_FUNCTION=address, OPTIONS_TABLE=table, ROOT_OFFSET=root, MODE_OFFSET=mode,
                               SELECTED_OFFSET=selected, LIST_OFFSET=listing, MENU_OFFSET=menu, DETAIL_OFFSET=detail)
                harness = "\n".join(f"#define {key} 0x{value:X}u" for key, value in defines.items()) + "\n" + PROBE
                harness = harness.replace("/* STATE */", state).replace("/* ORIGINAL */", body).replace("/* PUMP */", adapted)
                compile_probe("battle-options-" + edition, harness, {"runtime.h": header}, compiler_override=compiler,
                              extra_flags=["/clang:-Wno-unused-variable", "/clang:-Wno-unused-label", "/clang:-Wno-unused-function"])


if __name__ == "__main__":
    unittest.main()
