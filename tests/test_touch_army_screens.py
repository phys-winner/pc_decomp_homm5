"""Two-army screens (caravan, raising the dead, joining creatures, garrison, exchange) in all three editions.

The actual helpers from touch_engine.c (for 1.6/2.1 the contract-adapted text with their vtables, handler
and field offsets) resolve cells through the screen's row hash map, pick the other army's owner as the
original move/split handler does, prefer the screen's own controller factory and mark the update helper.
"""
import json
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_patches   # noqa: E402

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define ADDR(p) (memory + (uint32_t)(p))
#define MEM32(p) (*(uint32_t *)ADDR(p))
#define MEM8(p) (*(uint8_t *)ADDR(p))
typedef void (*void_fn)(void);
static uint32_t g_edx, scratch = 0x10000, picked, factory_result, common_args[6], factory_args[6];
static int factory_calls, common_calls, same;
static struct { uint32_t screen; } gesture = {0x4000};
/* VTABLES */
typedef struct { uint32_t window,army,owner,row,command,world,policy; unsigned index,stride; } troop_cell;
static int void_vm_readable(uint32_t p, uint32_t n) { return p >= 0x100 && (uint64_t)p + n <= sizeof memory; }
static int void_vm_writable(uint32_t p, uint32_t n) { return void_vm_readable(p, n); }
static uint32_t read32(uint32_t p) { return void_vm_readable(p, 4) ? MEM32(p) : 0; }
static int same_screen(void) { return same; }
static int ui_idle(void) { return 1; }
static uint32_t ui_pick(uint32_t screen, float x, float y) { (void)x; (void)y; assert(screen == 0x4000); return picked; }
static int window_contains(uint32_t hit, uint32_t window) {
    /* Icon children 0x70010 / 0x70110 sit inside the portraits 0x70000 / 0x70100. */
    return hit == window || (hit == window + 0x10 && (window == 0x70000 || window == 0x70100));
}
static void dummy(void) {}
static void_fn void_dispatch_find(uint32_t va) { return va ? dummy : NULL; }
static uint32_t object_method(uint32_t object, unsigned offset) {
    uint32_t method = read32(read32(object) + offset);
    return object && method ? method : 0;
}
static uint32_t void_call_guest_this(uint32_t va, uint32_t self, int n, const uint32_t *args) {
    if (va == FACTORY_VA) {
        assert(self == 0x4000 && n == 6); memcpy(factory_args, args, 24); ++factory_calls; return factory_result;
    }
    if (va == COMMON_VA) {
        assert(self == 0x41000 && g_edx == 0x42000 && n == 6); memcpy(common_args, args, 24); ++common_calls; return 0xA5000;
    }
    assert(0); return 0;
}
/* HOST */
static void owner(uint32_t object) { MEM32(object + 4) = object + 0x20; MEM32(object + 0x24) = 0x10; }
static void setup(uint32_t vtable) {
    memset(memory, 0, 0x100000); same = 1; factory_result = 0; factory_calls = common_calls = 0;
    MEM32(0x4000) = vtable; MEM32(VTABLE_OF_HANDLER) = HANDLER_VA; MEM32(VTABLE_OF_FACTORY) = FACTORY_VA;
    MEM32(0x4000 + ARMY_OWNERS) = 0x40000; MEM32(0x4000 + ARMY_OWNERS + 4) = 0x40100;
    owner(0x40000); owner(0x40100);
    MEM32(0x4000 + ARMY_COMMAND) = 0x41000; MEM32(0x4000 + ARMY_COMMAND + 4) = 0x42000;
    MEM32(0x4000 + ARMY_UPDATE) = 0x9000;
    /* Two buckets; key 2 (another record) chained in front of key 0. */
    MEM32(0x4000 + ARMY_ROWS) = 0x8000; MEM32(0x4000 + ARMY_ROWS + 4) = 0x8008;
    MEM32(0x8000) = 0x8400; MEM32(0x8400) = 0x8100; MEM32(0x8404) = 2;
    MEM32(0x8004) = 0x8300;
    for (unsigned row = 0; row < 2; ++row) {
        uint32_t node = row ? 0x8300 : 0x8100, cells = 0xA000 + row * 0x1000, army = 0x60000 + row * 0x100;
        MEM32(node + 4) = row;
        MEM32(node + 8) = row ? 0x40100 : 0x40000; MEM32(node + 12) = army; MEM32(node + 16) = 0x70000 + row * 0x100;
        MEM32(node + 20) = cells; MEM32(node + 24) = cells + 7 * 48;
        MEM32(army) = 0x61000; owner(army);
        for (unsigned i = 0; i < 7; ++i) MEM32(cells + 48 * i) = 0x50000 + row * 0x100 + i * 0x10;
    }
    MEM32(0x61008) = 0x123456;
}
int main(void) {
    troop_cell cell, source, target;
    for (unsigned k = 0; k < sizeof vtables / sizeof vtables[0]; ++k) {
        if (!vtables[k]) continue;
        setup(vtables[k]);
        /* troop_cell_window clears the cell before asking the two-army helper. */
        memset(&cell, 0, sizeof cell); memset(&source, 0, sizeof source); memset(&target, 0, sizeof target);
        assert(army_cell_window(0x4000, 0x50140, &cell) == 1);
        assert(cell.window == 0x50140 && cell.army == 0x60100 && cell.owner == 0x40100 && cell.index == 4 && cell.stride == 48);
        assert(cell.row == 0xB000 && cell.command == 0x41000 && cell.world == 0x42000);
        assert(army_cell_window(0x4000, 0x50020, &cell) == 1 && cell.index == 2 && cell.army == 0x60000);
        assert(army_cell_window(0x4000, 0x50070, &cell) == 0);       /* not a cell */
        picked = 0x70110;
        assert(army_portrait_at(0x4000, 1, 1, &cell) == 1 && cell.army == 0x60100 && cell.index == 0);
        picked = 0x6FFFF;
        assert(army_portrait_at(0x4000, 1, 1, &cell) == 0);
        /* Rows to each other: the target owner is the other of the two; common controller. */
        assert(army_cell_window(0x4000, 0x50020, &source) == 1 && army_cell_window(0x4000, 0x50140, &target) == 1);
        assert(troop_controller(&source, &target) == 0xA5000 && factory_calls == 1 && common_calls == 1);
        uint32_t want[6] = {0x60000, 2, 0x40000, 0x60100, 4, 0x40100};
        assert(!memcmp(common_args, want, 24) && !memcmp(factory_args, want, 24));
        assert(troop_controller(&target, &source) == 0xA5000 && common_args[5] == 0x40000 && common_args[2] == 0x40100);
        /* Within one army the owner stays the source's. */
        assert(army_cell_window(0x4000, 0x50050, &target) == 1);
        assert(troop_controller(&source, &target) == 0xA5000 && common_args[5] == 0x40000 && common_args[4] == 5);
        /* The screen's own controller (raising the dead, a blocked garrison stack) wins. */
        factory_result = 0xC0000; common_calls = 0;
        assert(troop_controller(&source, &target) == 0xC0000 && !common_calls);
        army_screen_dirty(); assert(MEM8(0x903C) == 1);
        same = 0; MEM8(0x903C) = 0; army_screen_dirty(); assert(!MEM8(0x903C)); same = 1;
        /* Another screen, or this vtable without the common handler, is no two-army screen. */
        MEM32(VTABLE_OF_HANDLER) = HANDLER_VA + 1;
        assert(army_cell_window(0x4000, 0x50020, &cell) == -1 && army_portrait_at(0x4000, 1, 1, &cell) == -1);
    }
    setup(0x00E2A64Cu);
    assert(army_cell_window(0x4000, 0x50020, &cell) == -1);
    puts("PASS two-army screens " EDITION ": row map cells, portraits, owner choice, own/common controller, update mark");
    return 0;
}
'''

VTABLES = ("00E42BD4", "00E42A1C", "00E349F4", "00E35BF4", "00E40CE4")   # caravan, raise, join, garrison, exchange


def host_text(edition):
    if edition == "toe":
        return (ROOT / "android/host/touch_engine.c").read_text(encoding="utf-8")
    adapted, _ = port_patches.adapt_host_source(ROOT / "android/host/touch_engine.c",
                                                ROOT / "build/tests" / ("army-screens-" + edition), edition)
    return adapted.read_text(encoding="utf-8")


class ArmyScreensTest(unittest.TestCase):
    def run_edition(self, edition):
        text = host_text(edition)
        layout = text[text.index("#define ARMY_HANDLER_SLOT"):text.index("static int army_screen(")]
        host = layout + "\n".join(function(text, signature) for signature in (
            "static uint32_t virtual_base(", "static int army_screen(", "static uint32_t army_row(",
            "static void army_screen_dirty(", "static int army_cell_window(", "static int army_portrait_at(",
            "static uint32_t army_controller(", "static uint32_t troop_controller("))
        slot = lambda name: int(re.search(r"#define %s (0x[0-9A-Fa-f]+)u" % name, layout).group(1), 16)
        contract = json.loads((ROOT / "config" / (edition + ".patches.json")).read_text(encoding="utf-8"))
        addresses = contract.get("addresses", {}) if edition != "toe" else {}
        mapped = lambda toe: int(addresses.get(toe, toe), 16)
        vtables = [mapped(v) for v in VTABLES]
        handler = int(re.search(r"read32\(vtable\+ARMY_HANDLER_SLOT\)==(0x[0-9A-F]{8})u", host).group(1), 16)
        self.assertEqual(handler, mapped("00649E70"))
        common = int(re.search(r"void_call_guest_this\((0x[0-9A-F]{8})u,source->command,6,args\);\n}", host).group(1), 16)
        defines = "\n".join([
            "#define EDITION \"%s\"" % edition,
            "#define HANDLER_VA 0x%08Xu" % handler, "#define COMMON_VA 0x%08Xu" % common,
            "#define FACTORY_VA 0x007B4A90u",
            # every tested vtable lives at a different address: point the slots of the current one
            "#define VTABLE_OF_HANDLER (MEM32(0x4000) + ARMY_HANDLER_SLOT)",
            "#define VTABLE_OF_FACTORY (MEM32(0x4000) + ARMY_FACTORY_SLOT)",
        ]) + "\n"
        harness = HARNESS.replace("/* HOST */", host).replace(
            "/* VTABLES */", "static const uint32_t vtables[] = {%s};" % ", ".join("0x%08Xu" % v for v in vtables))
        if edition == "vanilla":
            self.assertEqual(vtables[0], 0)   # no caravans in 1.6
        self.assertEqual(slot("ARMY_HANDLER_SLOT"), {"toe": 0x78, "vanilla": 0x74, "hof": 0x70}[edition])
        compile_probe("touch_army_screens_" + edition, defines + harness, {})

    def test_tribes_of_the_east(self):
        self.run_edition("toe")

    def test_heroes_v_1_6(self):
        self.run_edition("vanilla")

    def test_hammers_of_fate(self):
        self.run_edition("hof")


if __name__ == "__main__":
    unittest.main()
