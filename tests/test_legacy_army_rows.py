"""Compare host army cells with the original 1.6/2.1 troop handlers.

The independent fixture uses the native named Army group, not the adjacent
Inventory group. The complete original troop handler must resolve both endpoints
and pass their armies, indices and owners into its own split-controller factory.
Native UI policy and modal creation are bounded spies; endpoint discovery is real.
"""
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_legacy_ui import generated_body
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import build_windows
import port_patches
import prepare_windows_runtime


HARNESS = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
static struct {uint32_t screen;int kind;} gesture={0x20000,0};
enum {SCREEN_TOWN=3};
typedef struct { uint32_t window,army,owner,row,command,world,policy; unsigned index,stride; } troop_cell;
static uint32_t picked,native_args[9];
static unsigned native_factories;
static int void_vm_readable(uint32_t p,uint32_t n) {return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static uint32_t read32(uint32_t p) {return void_vm_readable(p,4)?MEM32(p):0;}
static int same_screen(void) {return 1;}
static int ui_idle(void) {return 1;}
static int town_army_ready(void) {assert(0);return 0;}
static uint32_t object_method(uint32_t self,unsigned slot) {assert(self==0x80000||self==0x80100);assert(slot==8);return 1;}
static uint32_t object_query(uint32_t self,unsigned slot) {
    assert(self==0x40000||self==0x40100);assert(slot==ARMY_SLOT);
    return self==0x40000?0x80000:0x80100;
}
static int void_dispatch_find(uint32_t va) {assert(va==TRANSFER_VA);return 1;}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,unsigned n,const uint32_t *args) {
    assert(va==TRANSFER_VA&&self==gesture.screen&&n==0&&!args);return 1;
}
static uint32_t ui_pick(uint32_t screen,float x,float y) {(void)x;(void)y;assert(screen==gesture.screen);return picked;}
static int window_contains(uint32_t hit,uint32_t window) {return hit==window;}
static void native_army(void) {
    assert(g_ecx==0x40000||g_ecx==0x40100);
    g_eax=g_ecx==0x40000?0x80000:0x80100;g_esp+=4;
}
recomp_func_t void_resolve(uint32_t va) {assert(va==0xE3000);return native_army;}
static void native_borrow(void) {assert(g_ecx==0x90010||g_ecx==0x90020);g_eax=0;g_esp+=4;}
static void native_can_transfer(void) {assert(g_ecx==gesture.screen);g_eax=(g_eax&~255u)|1;g_esp+=4;}
static void native_split_mode(void) {assert(g_ecx==gesture.screen+SPLIT_FIELD);g_eax=(g_eax&~255u)|1;g_esp+=4;}
static void native_controller(void) {
    assert(void_vm_readable(g_ecx,36));memcpy(native_args,(void *)(VOID_GUEST_BASE+g_ecx),36);
    ++native_factories;g_eax=0xD0000;g_esp+=4;
}
static void native_modal(void) {assert(g_ecx==0xD0000);g_eax=0;g_esp+=4;}
/* GENERATED */
/* HOST */
static uint32_t cell_window(unsigned row,unsigned index) {
    return virtual_base(read32((row?0x70100:0x70000)+12*index),8);
}
static void native_pick(uint32_t source,uint32_t target) {
    native_factories=0;memset(native_args,0xFF,sizeof native_args);
    g_ecx=gesture.screen;g_esp=0x10004;MEM32(g_esp)=RECOMP_RETADDR;
    MEM32(g_esp+4)=source;MEM32(g_esp+8)=0x90010;
    MEM32(g_esp+12)=target;MEM32(g_esp+16)=0x90020;
    RESOLVE();assert(g_esp==0x10018&&g_fp_sp==128&&g_fp_top==0);
}
int main(void) {
    MEM32(gesture.screen)=HERO_VTABLE;
    MEM32(gesture.screen+OWNER0)=0x40000;MEM32(gesture.screen+OWNER1)=0x40100;
    MEM32(0x40000)=MEM32(0x40100)=0xE2000;
    MEM32(0x40004)=MEM32(0x40104)=0xE1000;MEM32(0xE1004)=0x20;
    MEM32(0xE2000+ARMY_SLOT)=0xE3000;
    MEM32(gesture.screen+COMMAND)=0xA0000;MEM32(gesture.screen+WORLD)=0xA1000;
    MEM32(gesture.screen+POLICY)=7;
    for(unsigned c=0;c<2;++c) {
        uint32_t config=gesture.screen+CONFIG+c*0x180;MEM8(config)=1;MEM32(config+4)=1;
    }
    MEM32(gesture.screen+ROW0)=0x70000;MEM32(gesture.screen+ROW0+4)=0x70054;
    MEM32(gesture.screen+ROW1)=0x70100;MEM32(gesture.screen+ROW1+4)=0x70154;
    /* Live original Inventory has ten equipped slots and separate backpack slots. */
    MEM32(gesture.screen+EQUIPMENT0)=0x71000;MEM32(gesture.screen+EQUIPMENT0+4)=0x71028;
    MEM32(gesture.screen+EQUIPMENT1)=0x71100;MEM32(gesture.screen+EQUIPMENT1+4)=0x71128;
    MEM32(gesture.screen+EQUIPMENT0+12)=0x71200;MEM32(gesture.screen+EQUIPMENT0+16)=0x7120C;
    MEM32(gesture.screen+EQUIPMENT1+12)=0x71300;MEM32(gesture.screen+EQUIPMENT1+16)=0x7130C;
    MEM32(0xE0008)=0x18;
    for(unsigned row=0;row<2;++row) {
        for(unsigned i=0;i<7;++i) {
            uint32_t object=(row?0x60000:0x50000)+0x100*i;
            MEM32((row?0x70100:0x70000)+12*i)=object;MEM32(object+4)=0xE0000;
        }
        for(unsigned i=0;i<10;++i) {
            uint32_t object=(row?0xC0000:0xB0000)+0x100*i;
            MEM32((row?0x71100:0x71000)+4*i)=object;MEM32(object+4)=0xE0000;
        }
        for(unsigned i=0;i<3;++i) {
            uint32_t object=(row?0xC2000:0xB2000)+0x100*i;
            MEM32((row?0x71300:0x71200)+4*i)=object;MEM32(object+4)=0xE0000;
        }
    }
    MEM32(gesture.screen+PORTRAIT0)=0xD1000;MEM32(gesture.screen+PORTRAIT1)=0xD2000;
    g_fp_sp=128;g_fp_top=0;fp_set_cw(0x007F);unsigned cases=0;
    for(unsigned selector=0;selector<2;++selector) {
        MEM8(gesture.screen+SELECTOR)=(uint8_t)selector;
        for(unsigned row=0;row<2;++row)for(unsigned i=0;i<7;++i) {
            uint32_t window=cell_window(row,i),target=cell_window(!row,6);troop_cell cell;
            native_pick(window,target);assert(native_factories==1);
            assert(native_args[0]==0xA0000&&native_args[1]==0xA1000);
            assert(native_args[2]==(row?0x80100u:0x80000u)&&native_args[3]==i&&native_args[4]==(row?0x40100u:0x40000u));
            assert(native_args[5]==(row?0x80000u:0x80100u)&&native_args[6]==6&&native_args[7]==(row?0x40000u:0x40100u)&&native_args[8]==7);
            assert(troop_cell_window(window,&cell));
            assert(cell.owner==native_args[4]&&cell.index==native_args[3]&&cell.army==native_args[2]);
            assert(cell.window==window&&cell.stride==12&&cell.row==(row?0x70100u:0x70000u));
            assert(cell.command==native_args[0]&&cell.world==native_args[1]&&cell.policy==native_args[8]);
            assert(troop_row_window(&cell,i)==window);++cases;
        }
        for(unsigned row=0;row<2;++row)for(unsigned bank=0;bank<2;++bank) {
            uint32_t begin=bank?(row?0x71300:0x71200):(row?0x71100:0x71000);
            for(unsigned i=0;i<(bank?3u:10u);++i) {
                uint32_t window=virtual_base(read32(begin+4*i),8);troop_cell cell;
                native_pick(window,cell_window(0,6));assert(!native_factories);
                assert(!troop_cell_window(window,&cell));++cases;
            }
        }
        for(unsigned row=0;row<2;++row) {
            troop_cell cell;picked=row?0xD2000:0xD1000;
            assert(troop_portrait_at(10,10,&cell));assert(cell.index==0&&cell.row==(row?0x70100u:0x70000u));++cases;
        }
    }
    troop_cell cell;native_pick(0xF0000,cell_window(0,6));assert(!native_factories&&!troop_cell_window(0xF0000,&cell));++cases;
    printf("PASS %u original troop-handler/host cases: Army7x12, Inventory10 equipment+3backpack rejected, both selectors/rows, native controller args, portraits, RET16/x87 ABI\n",cases);
    return 0;
}
"""


# The original row builder resolves named child Army (row+18), whose initializer
# reserves seven records at +24. Native troop handlers confirm row+3C, stride12.
# The ten Helm/Necklace/... equipment windows belong to Inventory at row+58.
ENGINES = {
    "vanilla": {
        "resolver": 0x679DE0, "borrow": 0xA51BE0, "split": 0x8BE840,
        "controller": 0x676AA0, "modal": 0x556DD0,
        "SPLIT_FIELD": 0x194, "HERO_VTABLE": 0xE13F0C, "ROW0": 0x50C, "ROW1": 0x5FC,
        "EQUIPMENT0": 0x528, "EQUIPMENT1": 0x618,
        "OWNER0": 0x1A8, "OWNER1": 0x1AC,
        "COMMAND": 0x1A0, "WORLD": 0x19C, "POLICY": 0x700,
        "CONFIG": 0x1B0, "SELECTOR": 0x4B0,
        "PORTRAIT0": 0x4E0, "PORTRAIT1": 0x5D0,
        "ARMY_SLOT": 0x48, "TRANSFER_VA": 0x6784B0,
    },
    "hof": {
        "resolver": 0x67C440, "borrow": 0x81C380, "split": 0x9FE8A0,
        "controller": 0x678A50, "modal": 0x56E180,
        "SPLIT_FIELD": 0x190, "HERO_VTABLE": 0xDE93D4, "ROW0": 0x508, "ROW1": 0x5F8,
        "EQUIPMENT0": 0x524, "EQUIPMENT1": 0x614,
        "OWNER0": 0x1A4, "OWNER1": 0x1A8,
        "COMMAND": 0x19C, "WORLD": 0x198, "POLICY": 0x6FC,
        "CONFIG": 0x1AC, "SELECTOR": 0x4AC,
        "PORTRAIT0": 0x4DC, "PORTRAIT1": 0x5CC,
        "ARMY_SLOT": 0x18, "TRANSFER_VA": 0x67A490,
    },
}


class LegacyArmyRowsTest(unittest.TestCase):
    def run_original_resolver(self, edition):
        native = ENGINES[edition]
        out = ROOT / "build/tests" / ("legacy-army-rows-" + edition)
        adapted, _ = port_patches.adapt_host_source(
            ROOT / "android/host/touch_engine.c", out, edition)
        text = adapted.read_text(encoding="utf-8")
        # The two-army screen helpers come first: a hero screen is none of them (-1 falls through).
        layout = text[text.index("#define ARMY_HANDLER_SLOT"):text.index("static int army_screen(")]
        host = layout + "\n".join(function(text, signature) for signature in (
            "static uint32_t virtual_base(", "static int army_screen(", "static uint32_t army_row(",
            "static int army_cell_window(", "static int army_portrait_at(", "static int troop_cell_window(",
            "static uint32_t troop_row_window(", "static int troop_portrait_at(",
        ))
        generated = generated_body(edition, native["resolver"])
        callbacks = {native["borrow"]: "native_borrow", native["split"]: "native_split_mode",
                     native["controller"]: "native_controller", native["modal"]: "native_modal",
                     native["TRANSFER_VA"]: "native_can_transfer"}
        for address, name in callbacks.items():
            generated = generated.replace("sub_%08X" % address, name)
        # Unreached order/error branches must fail if the fixture unexpectedly
        # enters them; only native policy and modal callbacks are simulated.
        callees = sorted(set(re.findall(r"RECOMP_CALL\((sub_[0-9A-F]{8})\)", generated)))
        stubs = "\n".join("static void %s(void) {assert(0);}" % name for name in callees)
        state = (ROOT / "android/host/core.c").read_text(encoding="utf-8")
        state = state[state.index("VOID_HIDDEN uint32_t g_eax"):
                      state.index("#define VOID_ENTER_RING")]
        harness = (HARNESS.replace("/* STATE */", state)
                   .replace("/* GENERATED */", stubs + "\n" + generated)
                   .replace("/* HOST */", host)
                   .replace("RESOLVE()", "sub_%08X()" % native["resolver"]))
        defines = "\n".join("#define %s 0x%X" % (name, value)
                            for name, value in native.items() if name.isupper()) + "\n"
        compiler, _, _ = build_windows.compiler_environment()
        header = prepare_windows_runtime.platform_header(
            (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8"))
        compile_probe("legacy_army_rows_" + edition, defines + harness,
                      {"runtime.h": header}, compiler_override=compiler,
                      extra_flags=["/clang:-Wno-unused-variable",
                                   "/clang:-Wno-unused-label",
                                   "/clang:-Wno-unused-function"])

    def test_vanilla_native_resolver_matches_host_rows(self):
        self.run_original_resolver("vanilla")

    def test_hof_native_resolver_matches_host_rows(self):
        self.run_original_resolver("hof")


if __name__ == "__main__":
    unittest.main()
