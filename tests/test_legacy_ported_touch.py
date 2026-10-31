"""Touch features carried from Tribes of the East to 1.6 and 2.1, run on each edition's actual host text.

For 1.6/2.1 the contract-adapted touch_engine.c (mapped addresses, combat screen and hero offsets,
parent slot, book closing byte) drives: the initiative bar portrait pick, the minimap and slider
lookups through RTTI casts and parent windows, the spellbook swipes, the scenario hero description and
the tactics reserve split through CCombatSplitStackController.
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
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x100000];
#define ADDR(p) (memory + (uint32_t)(p))
#define MEM32(p) (*(uint32_t *)ADDR(p))
#define MEM16(p) (*(uint16_t *)ADDR(p))
#define MEM8(p) (*(uint8_t *)ADDR(p))
#define MEMF(p) (*(float *)ADDR(p))
#define VLOG(...) ((void)0)
typedef void (*void_fn)(void);
typedef struct { int unused; } void_regs;
enum { SCREEN_MENU, SCREEN_ADVENTURE, SCREEN_COMBAT, SCREEN_TOWN };
enum { TOUCH_SECOND_BEGIN = 11, TOUCH_SECOND_TAP = 12, TOUCH_SECOND_HOLD = 13 };
typedef struct { int kind; float x, y, dx, dy, scale, rotation; } void_touch_event;
static struct {
    uint32_t screen, root, controller;
    int kind, placement, cancelled, second_troop, committed, world_hover, details, book;
    float start_x, start_y, x, y;
} gesture;
static uint32_t g_ecx, scratch = 0x1000, picked, cast_target, cast_result, parent_of[2][2], updates;
static struct { uint32_t va, self, n, args[10]; } calls[32];
static unsigned call_count;
static uint32_t reserve[7];
static int void_vm_readable(uint32_t p, uint32_t n) { return p >= 0x100 && (uint64_t)p + n <= sizeof memory; }
static int void_vm_writable(uint32_t p, uint32_t n) { return void_vm_readable(p, n); }
static uint32_t read32(uint32_t p) { return void_vm_readable(p, 4) ? MEM32(p) : 0; }
static int same_screen(void) { return 1; }
static int spellbook_kind(uint32_t screen) { return screen == gesture.screen; }
static uint32_t ui_pick(uint32_t screen, float x, float y) { (void)screen; (void)x; (void)y; return picked; }
static void void_input_screen_size(int *w, int *h) { *w = 1000; *h = 500; }
static void dummy(void) { ++updates; }
static void_fn void_dispatch_find(uint32_t va) { return va ? dummy : NULL; }
static void_fn original_choice_update = dummy;
static void void_regs_save(void_regs *r) { (void)r; }
static void void_regs_load(void_regs *r) { (void)r; }
static uint32_t void_galloc(uint32_t n) { (void)n; return 0x80000; }
static uint32_t logical_point(float x, float y) { MEMF(0x2000) = x; MEMF(0x2004) = y; return 0x2000; }
static int placement_reserve_slot(float x, float y) { (void)y; return x >= 0 && x < 700 ? (int)(x / 100) : -1; }
static uint32_t window_placement(uint32_t window) { return window == 0x6200 ? 0x6300 : 0; }
static uint32_t object_query(uint32_t object, unsigned slot) {
    if (object == 0x30000 && slot == 0xC) return 1;           /* the split controller is ready */
    assert(slot == PARENT_SLOT);                              /* the edition's IWindow parent query */
    for (int i = 0; i < 2; ++i) if (parent_of[i][0] == object) return parent_of[i][1];
    return object;
}
static uint32_t log_call(uint32_t va, uint32_t self, int n, const uint32_t *args) {
    assert(call_count < 32 && n <= 10);
    calls[call_count].va = va; calls[call_count].self = self; calls[call_count].n = (uint32_t)n;
    for (int i = 0; i < n; ++i) calls[call_count].args[i] = args[i];
    return ++call_count;
}
static uint32_t void_call_guest_this(uint32_t va, uint32_t self, int n, const uint32_t *args) {
    log_call(va, self, n, args);
    if (va == VA_ATB) return 0x777;
    if (va == VA_RESERVE_GET) return reserve[args[0]];
    if (va == VA_CREATURE) return self + 0x40;
    if (va == VA_SPLIT_ONE) return 1;
    if (va == VA_HERO) return 0x21000;
    if (va == VA_TEXT) return 0x22000;
    return 0;
}
static uint32_t void_call_guest(uint32_t va, int n, const uint32_t *args, int convention) {
    (void)convention;
    log_call(va, 0, n, args);
    if (va == VA_ALLOC) { assert(n == 1 && args[0] == 0x50); return 0x30000; }
    assert(va == VA_CAST && n == 5 && args[2] == RTTI_IWINDOW);
    return args[0] == picked && args[3] == cast_target ? cast_result : 0;
}
/* HOST */
static void reset(void) { memset(memory, 0, sizeof memory); call_count = 0; memset(&gesture, 0, sizeof gesture); }
static unsigned find(uint32_t va) { for (unsigned i = 0; i < call_count; ++i) if (calls[i].va == va) return i + 1; return 0; }
int main(void) {
    /* The initiative bar on its combat screen offset; its pick is thiscall (point) on the bar. */
    reset();
    MEM32(0x4000) = VT_COMBAT; MEM32(0x4000 + BAR) = 0x9000;
    assert(atb_unit_at(0x4000, 10, 20) == 0x777 && calls[0].va == VA_ATB && calls[0].self == 0x9000);
    MEM32(0x4000) = 0x1234; assert(!atb_unit_at(0x4000, 10, 20));        /* another screen */

    /* The minimap under a child window: cast, then the parent through the edition's slot. */
    reset(); picked = 0x5200; parent_of[0][0] = 0x5200; parent_of[0][1] = 0x5000;
    cast_target = RTTI_MINIMAP; cast_result = 0; gesture.screen = 0x4000;
    assert(!minimap_at(1, 1));                                    /* nothing casts: the walk ends at the root */
    picked = 0x5000; cast_result = 0x5100; MEM32(0x5100) = VT_MINIMAP;
    assert(minimap_at(1, 1));
    MEM32(0x5100) = 0x4321; assert(!minimap_at(1, 1));

    /* A slider: its lever (+134) centre from the lever's position and its placement's size. */
    reset(); picked = 0x6000; cast_target = RTTI_SLIDER; cast_result = 0x6100; MEM32(0x6100) = VT_SLIDER;
    MEM32(0x6100 + 0x134) = 0x6200; MEMF(0x6200 + 0x64) = 100; MEMF(0x6200 + 0x68) = 50;
    MEMF(0x6300 + 0xA4) = 40; MEMF(0x6300 + 0xA8) = 20;
    float lx = 0, ly = 0;
    assert(slider_lever_at(1, 1, &lx, &ly) && lx == 120 && ly == 60);

    /* Spellbook swipes: left is the next page, up the bookmark above; a closing book takes none. */
    reset(); picked = 0; gesture.screen = 0x4000; gesture.book = 1; gesture.start_x = 500; gesture.start_y = 250;
    assert(book_swipe(300, 250) && calls[0].va == VA_NEXT_PAGE && calls[0].self == 0x4000 && calls[0].n == 1);
    assert(book_swipe(700, 250) && calls[1].va == VA_PREVIOUS_PAGE);
    assert(book_swipe(500, 100) && calls[2].va == VA_BOOKMARK_UP);
    assert(book_swipe(500, 400) && calls[3].va == VA_BOOKMARK_DOWN);
    MEM8(0x4000 + CLOSING) = 1; assert(!book_swipe(300, 250) && call_count == 4);
    picked = 0x7000; MEM8(0x4000 + CLOSING) = 0; assert(!book_swipe(300, 250));   /* a swipe from a button */

    /* The scenario hero icon's tooltip gets the specialization text (hero record field per edition). */
    reset(); g_ecx = 0x20000; updates = 0;
    MEM32(0x20000 + 0x98) = 0x23000; picked = 0x23000; cast_target = RTTI_WINDOW; cast_result = 0x24000;
    MEM32(0x24000 + 0x24) = 0x25000; MEM32(0x25000) = VT_PROVIDER;
    static const uint16_t name[] = {'N','a','m','e'}, special[] = {'S','p','e','c'};
    memcpy(ADDR(0x26000), name, sizeof name); memcpy(ADDR(0x27000), special, sizeof special);
    MEM32(0x25000 + 8) = 0x26000; MEM32(0x25000 + 12) = 0x26000 + sizeof name;
    MEM32(0x22000) = 0x27000; MEM32(0x22000 + 4) = 0x27000 + sizeof special;
    choice_update();
    unsigned hero = find(VA_HERO), text = find(VA_TEXT), assign = find(VA_ASSIGN);
    assert(updates == 1 && hero && calls[hero - 1].self == 0x20000 + 0x88);
    assert(text && calls[text - 1].self == 0x21000 + HERO_TEXT);
    assert(assign && calls[assign - 1].self == 0x25000 + 8 && calls[assign - 1].n == 2);
    assert(calls[assign - 1].args[1] - calls[assign - 1].args[0] == sizeof name + 16 + sizeof special);
    assert(!memcmp(ADDR(calls[assign - 1].args[0]), name, sizeof name) && MEM16(calls[assign - 1].args[0] + 8) == '<');
    reset(); g_ecx = 0x20000; MEM32(0x25000) = 0; choice_update(); assert(!find(VA_ASSIGN));

    /* Tactics reserve: a second-finger tap splits one creature into the first empty slot. */
    reset();
    gesture.screen = 0x4000; gesture.kind = SCREEN_COMBAT; gesture.placement = 1;
    gesture.start_x = gesture.x = 250; gesture.start_y = gesture.y = 10;
    MEM32(0x4000 + STATE) = 0x1000; MEM32(0x4000 + PLACEMENT) = 0x8000;
    MEM8(0x8000 + 0x9C) = 1; MEM32(0x8000 + 0x2C) = 0x8100; MEM32(0x8000 + 0x30) = 0x8100 + 7 * 4;
    memset(reserve, 0, sizeof reserve); reserve[2] = 0xA000; reserve[3] = 0xA100;
    MEM32(0xA000 + 8) = 5; MEM32(0xA000 + 0x1C) = 0x77;
    void_touch_event begin = {TOUCH_SECOND_BEGIN, 550, 10, 0, 0, 1, 0}, tap = {TOUCH_SECOND_TAP, 550, 10, 0, 0, 1, 0};
    assert(placement_second(&begin) && gesture.second_troop && !call_count);
    assert(placement_second(&tap) && gesture.committed);
    unsigned ctor = find(VA_SPLIT_CTOR), holder = find(VA_SPLIT_HOLDER), one = find(VA_SPLIT_ONE);
    unsigned cancel = find(VA_PLACEMENT_CANCEL), apply = find(VA_SPLIT_APPLY);
    assert(find(VA_ALLOC) && ctor && holder && one && cancel && apply);
    assert(ctor < holder && holder < one && one < cancel && cancel < apply);
    assert(calls[ctor - 1].self == 0x30000 && calls[ctor - 1].n == 10 && calls[ctor - 1].args[0] == 0x8000);
    assert(calls[ctor - 1].args[3] == 0x77 && calls[ctor - 1].args[5] == 5 && calls[ctor - 1].args[6] == 0);
    assert(calls[ctor - 1].args[7] == 2 && calls[ctor - 1].args[8] == 0 && calls[ctor - 1].args[9] == 1);
    assert(calls[holder - 1].self == 0x8000 + 0x80 && calls[cancel - 1].self == 0x8000);
    reset(); gesture.screen = 0x4000; gesture.kind = SCREEN_COMBAT; gesture.placement = 1;
    gesture.start_x = gesture.x = 250; MEM32(0x4000 + STATE) = 0x8; MEM32(0x4000 + PLACEMENT) = 0x8000;
    assert(!placement_second(&begin));                            /* not the tactics phase */
    printf("PASS ported touch helpers (%s)\n", EDITION);
    return 0;
}
'''

FUNCTIONS = ("static uint32_t atb_unit_at(", "static int minimap_at(", "static int slider_lever_at(",
             "static int book_swipe(", "static void choice_update(", "static int placement_second(")
# 3.1 field offsets and what 1.6 / 2.1 use.
FIELDS = {"BAR": (0x494, 0x468, 0x480), "STATE": (0x2E0, 0x2D8, 0x2F0), "PLACEMENT": (0x488, 0x45C, 0x474),
          "CLOSING": (0x1ED, 0x1E5, 0x1E1), "HERO_TEXT": (0x118, 0x108, 0x118), "PARENT_SLOT": (0xD8, 0xCC, 0xD4)}
ADDRESSES = {"VA_ATB": "0055DC40", "VT_COMBAT": "00E1DA84", "VA_CAST": "00D119FC", "RTTI_IWINDOW": "00F2DAF4",
             "RTTI_MINIMAP": "00F34164", "VT_MINIMAP": "00E23B50", "RTTI_SLIDER": "00F2DC80", "VT_SLIDER": "00E13F2C",
             "VA_NEXT_PAGE": "00686020", "VA_PREVIOUS_PAGE": "00686080", "VA_BOOKMARK_UP": "006860C0",
             "VA_BOOKMARK_DOWN": "006860E0", "RTTI_WINDOW": "00F2DA88", "VT_PROVIDER": "00E4E754",
             "VA_HERO": "004A6740", "VA_TEXT": "004C7430", "VA_ASSIGN": "0040E960", "VA_RESERVE_GET": "00576200",
             "VA_CREATURE": "004DB320", "VA_ALLOC": "00878FD0", "VA_SPLIT_CTOR": "0057A350",
             "VA_SPLIT_HOLDER": "0063EE50", "VA_SPLIT_ONE": "0057A1A0", "VA_PLACEMENT_CANCEL": "00576260",
             "VA_SPLIT_APPLY": "0057A290"}


def host_text(edition):
    if edition == "toe":
        return (ROOT / "android/host/touch_engine.c").read_text(encoding="utf-8")
    adapted, _ = port_patches.adapt_host_source(ROOT / "android/host/touch_engine.c",
                                                ROOT / "build/tests" / ("ported-touch-" + edition), edition)
    return adapted.read_text(encoding="utf-8")


class PortedTouchTest(unittest.TestCase):
    def run_edition(self, edition):
        text = host_text(edition)
        host = "\n".join(function(text, signature) for signature in FUNCTIONS)
        column = ("toe", "vanilla", "hof").index(edition)
        addresses = json.loads((ROOT / "config" / (edition + ".patches.json")).read_text(encoding="utf-8"))["addresses"] \
            if edition != "toe" else {}
        defines = ['#define EDITION "%s"' % edition]
        defines += ["#define %s 0x%Xu" % (name, values[column]) for name, values in FIELDS.items()]
        defines += ["#define %s 0x%sU" % (name, addresses.get(toe, toe)) for name, toe in ADDRESSES.items()]
        for name, toe in ADDRESSES.items():   # every ToE address is gone from the legacy helpers
            if edition != "toe" and addresses[toe] != toe:
                self.assertNotRegex(host, r"0x%su" % toe, name)
        if edition != "toe":   # no orcish book in 1.6/2.1: its handlers are not referenced
            self.assertNotRegex(host, r"0x0067E[23][0-9A-F]0u")
        self.assertEqual(len(re.findall(r"object_query\(window, 0x%X\)" % FIELDS["PARENT_SLOT"][column], host)), 2)
        compile_probe("ported-touch-" + edition, "\n".join(defines) + "\n" + HARNESS.replace("/* HOST */", host), {},
                      extra_flags=["/wd4505", "/wd4244", "/wd4267"])

    def test_tribes_of_the_east(self):
        self.run_edition("toe")

    def test_heroes_v_1_6(self):
        self.run_edition("vanilla")

    def test_hammers_of_fate(self):
        self.run_edition("hof")


if __name__ == "__main__":
    unittest.main()
