"""Run the mapped combat confirmation transaction for all three original screen layouts.

Only engine boundaries are spies: the host's context preparation, target-mode guard,
state validation and native commit path are the production functions.  The tables below
are independent native ABI expectations, not values read back from the patch contract.
"""
import unittest

from test_d3d_lifecycle import function
from test_legacy_ported_touch import host_text
from test_static_tls import compile_probe


# ToE 3.1, Heroes V 1.6, HoF 2.1: CCombatScreen and its embedded CCombatContext.
FIELDS = {
    "ROOT": (0xA0, 0x98, 0x98), "CONTROLLER": (0x2B4, 0x294, 0x2A8),
    "ACTOR": (0x2AC, 0x28C, 0x2A0), "UI": (0x2D4, 0x2CC, 0x2E4),
    "PHASE": (0x2E0, 0x2D8, 0x2F0), "CONTEXT": (0x2EC, 0x2E4, 0x2FC),
    "CONTEXT_SIZE": (156, 144, 144), "PICK": (0x2F4, 0x2EC, 0x304),
    "PICK_X": (0x304, 0x2FC, 0x314), "PICK_Y": (0x308, 0x300, 0x318),
    "ACTION": (0x31C, 0x314, 0x32C), "SELECTED": (0x320, 0x318, 0x330),
    "TARGET": (0x324, 0x31C, 0x334), "CELL_X": (0x32C, 0x324, 0x33C),
    "CELL_Y": (0x330, 0x328, 0x340), "COMMAND": (0x33C, 0x334, 0x34C),
    "SPELL": (0x394, 0x380, 0x398), "CASTER": (0x388, 0x374, 0x38C),
    "SECOND": (0x38C, 0x378, 0x390),
}
ADDRESSES = {
    "VA_LOGICAL": (0xB29220, 0x410D10, 0xB04480),
    "VA_CTOR": (0x550A70, 0x5230B0, 0x539E80),
    "VA_ASSIGN": (0x550EB0, 0x5238D0, 0x53A720),
    "VA_DTOR": (0x550B00, 0x523120, 0x539EF0),
    "VA_OWNERSHIP": (0x540DA0, 0x5134D0, 0x528AD0),
    "VA_PICK": (0x544230, 0x5165A0, 0x52BEB0),
    "VA_ALLOWED": (0x53E3D0, 0x510D80, 0x525D80),
    "VA_BLOCKED": (0x53FBE0, 0, 0x528590),
    "VA_ELIGIBLE": (0, 0x511890, 0),
    "VA_SELECTED": (0x83F2B0, 0x57DCF0, 0x7F7900),
    "VA_GUARD": (0x53EEE0, 0x5118E0, 0x526D90),
    "VA_RESOLVE": (0x548270, 0x51A1C0, 0x52FDE0),
    "VA_PREVIEW": (0x5498C0, 0x51B9C0, 0x531620),
    "VA_COMMIT": (0x545490, 0x5175E0, 0x52D4E0),
    "VA_DIRECT": (0x542420, 0x514870, 0x529AB0),
}
FUNCTIONS = (
    "static uint32_t read32(uint32_t address)",
    "static uint32_t virtual_base(uint32_t object, unsigned slot)",
    "static int same_screen(void)",
    "static uint32_t logical_point(float x, float y)",
    "static int publish_point(float x, float y)",
    "static int target_armed(void)",
    "static int refresh_target_mode(void)",
    "static void ctrl_latch(int on)",
    "static void combat_reset_context(void)",
    "static int combat_prepare(float x, float y, int diagnostics)",
    "static void combat_pending_stage(uint32_t screen, float x, float y)",
    "static void combat_point(float x, float y, int commit)",
    "static void combat_pending_clear(void)",
    "static int combat_direct_pending_state(void)",
    "static int combat_pending_valid(void)",
    "static void combat_confirm(uint32_t generation)",
)

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x20000];
#define ADDR(p) (memory + (uint32_t)(p))
#define MEM32(p) (*(uint32_t *)ADDR(p))
#define MEM8(p) (*(uint8_t *)ADDR(p))
#define MEMF(p) (*(float *)ADDR(p))
#define FIELD(offset) MEM32(0x4000 + (offset))
#define VLOG(...) do { if (0) printf(__VA_ARGS__); } while (0)
enum { SCREEN_MENU, SCREEN_ADVENTURE, SCREEN_COMBAT, SCREEN_TOWN };
/* DECLARATIONS */
static uint32_t scratch = 0x10000, mock_screen, combat_generation;
static int ctrl_held, ctrl_keys, confirm_enabled, commands, previews, resolutions, first_targets;
static int next_action, next_ctrl, invalid_command, no_command, mutate_during_resolve, native_blocked;
static int direct_commands, combat_direct_allowed;
static uint64_t clock_ns;
static float touch_cursor_x, touch_cursor_y;
static void combat_pending_clear(void);
static int combat_pending_valid(void);
static void combat_point(float x, float y, int commit);
static void combat_prediction_bind(void) {}
static int void_vm_readable(uint32_t p, uint32_t n) { return p >= 0x100 && (uint64_t)p + n <= sizeof memory; }
static int void_vm_writable(uint32_t p, uint32_t n) { return void_vm_readable(p, n); }
static uint32_t void_galloc(uint32_t n) { assert(n == 512); return 0x10000; }
static uint32_t current_screen(void) { return mock_screen; }
static int screen_kind(uint32_t p) { return p == 0x4000 ? SCREEN_COMBAT : SCREEN_MENU; }
static int spellbook_kind(uint32_t p) { return p == 0x5000; }
static uint64_t void_perf_now_ns(void) { return clock_ns; }
static int void_port_combat_confirm(void) { return confirm_enabled; }
static void void_input_key(int key, int down) { assert(key == 0x11); ctrl_keys += down ? 1 : -1; }

/* Native eligibility functions return AL only. Keep dirty upper bits to exercise that ABI. */
static uint32_t void_call_guest_this(uint32_t va, uint32_t self, int n, const uint32_t *args) {
    if (va == VA_LOGICAL) { assert(self == scratch && !n); return self; }
    if (va == VA_CTOR) {
        assert(self == scratch + 160 && !n);
        memset(ADDR(self), 0, CONTEXT_SIZE); return self;
    }
    if (va == VA_ASSIGN) {
        assert(self == 0x4000 + CONTEXT && n == 1 && args[0] == scratch + 160);
        memcpy(ADDR(self), ADDR(args[0]), CONTEXT_SIZE); return self;
    }
    if (va == VA_DTOR) { assert(self == scratch + 160 && !n); return 0; }
    assert(self == 0x4000 || va == VA_SELECTED);
    if (va == VA_OWNERSHIP) { assert(!n); return 0; }
    if (VANILLA && va == 0x511890) { assert(!n); return 0xCAFE00u | (FIELD(PHASE) & 0x188u ? 1u : 0u); }
    if (va == VA_PICK) {
        assert(n == 2 && args[0] == 0x4000 + PICK && args[1] == 0x4000 + CONTEXT);
        assert(MEMF(args[1]) == 900 && MEMF(args[1] + 4) == 400);
        FIELD(PICK) = 0x8400; FIELD(PICK_X) = 17; FIELD(PICK_Y) = 23; return 0;
    }
    if (va == VA_ALLOWED || va == VA_BLOCKED) {
        assert(n == 1 && args[0] == FIELD(ACTOR));
        return 0xCAFE00u | (va == VA_ALLOWED ? 1u : 0u);
    }
    if (va == VA_SELECTED) {
        assert(self == 0x4000 + SELECTED && n == 1 && args[0] == 0x4000 + ACTOR);
        MEM32(self) = MEM32(args[0]); return self;
    }
    if (va == VA_GUARD) { assert(!n); return 0xCAFE00u | (uint32_t)native_blocked; }
    if (va == VA_RESOLVE) {
        assert(n == 2 && args[0] == 0x4000 + CONTEXT && args[1] == 0x4000 + PICK);
        assert(FIELD(SELECTED) == FIELD(ACTOR) && FIELD(CELL_X) == 17 && FIELD(CELL_Y) == 23);
        FIELD(ACTION) = (uint32_t)next_action; FIELD(TARGET) = 0x8400;
        FIELD(COMMAND) = no_command ? 0 : 0x8300;
        MEM32(0x8304) = invalid_command ? 0x80000000u : 0;
        assert(ctrl_held == next_ctrl);
        ++resolutions;
        switch (mutate_during_resolve) {
        case 1: FIELD(ACTOR) = 0x8500; break;
        case 2: FIELD(PHASE) = 0x100; break;
        case 3: FIELD(SPELL) = 43; break;
        case 4: FIELD(CASTER) = 0x8600; break;
        case 5: FIELD(SECOND) = 0x8700; break;
        case 6: FIELD(ACTION)++; break;
        case 7: FIELD(TARGET) = 0x8500; break;
        case 8: FIELD(CELL_X)++; break;
        case 9: FIELD(CELL_Y)++; break;
        case 10: mock_screen = 0x5000; break;
        case 11: MEM32(gesture.root + 8) = 0xA000; break;
        case 12: FIELD(UI) = 1; break;
        case 13: FIELD(ROOT) = 0x6100; break;
        case 14: FIELD(CONTROLLER) = 0x8100; break;
        case 15: FIELD(SPELL) = FIELD(CASTER) = FIELD(SECOND) = 0; break;
        }
        return 0;
    }
    if (va == VA_PREVIEW) { assert(!n); ++previews; return 0; }
    if (va == VA_DIRECT) {
        assert(!n && !args && !combat_pending.generation && combat_direct_allowed);
        assert(FIELD(ACTOR) == 0x8200 && FIELD(PHASE) == 8 && !FIELD(UI));
        assert(FIELD(SPELL) == 42 && FIELD(CASTER) == 0x8600 && !FIELD(SECOND));
        ++direct_commands; FIELD(PHASE) = 0x200; return 0xCAFE01;
    }
    if (va == VA_COMMIT) {
        assert(n == 1 && args[0] == scratch + 320);
        assert(MEM32(args[0] + 0x24) == (900u | (400u << 15)));
        assert(FIELD(COMMAND) == 0x8300 && !MEM32(0x8304));
        assert(FIELD(ACTOR) == 0x8200 && FIELD(PHASE) == 8 && ctrl_held == next_ctrl);
        if (FIELD(ACTION) == 10) { FIELD(SECOND) = 0x8400; ++first_targets; return 0; }
        ++commands; FIELD(PHASE) = 0x200; return 1;
    }
    fprintf(stderr, "Unexpected guest call %08X\n", va); assert(0); return 0;
}
/* HOST */
static void reset(void) {
    memset(memory, 0, sizeof memory); memset(&gesture, 0, sizeof gesture);
    memset(&combat_pending, 0, sizeof combat_pending);
    gesture.screen = mock_screen = 0x4000; gesture.root = 0x6000; gesture.controller = 0x8000;
    gesture.kind = SCREEN_COMBAT; FIELD(ROOT) = gesture.root; FIELD(CONTROLLER) = gesture.controller;
    FIELD(ACTOR) = 0x8200; FIELD(PHASE) = 8;
    MEM32(0x8204) = 0x9000; MEM32(0x9004) = 0x20; /* live actor's virtual-base table */
    ctrl_held = ctrl_keys = commands = previews = resolutions = first_targets = 0;
    next_ctrl = invalid_command = no_command = mutate_during_resolve = native_blocked = 0;
    direct_commands = combat_direct_allowed = 0; clock_ns = 100;
    next_action = 2; confirm_enabled = 1; touch_cursor_x = touch_cursor_y = -1;
}
static uint32_t stage(void) {
    gesture.active = 1;
    combat_point(900, 400, 1);
    gesture.active = 0;
    assert(!commands && combat_pending.generation && combat_pending_valid());
    assert(combat_pending.actor == 0x8200 && combat_pending.phase == 8);
    assert(combat_pending.target == 0x8400 && combat_pending.cell_x == 17 && combat_pending.cell_y == 23);
    assert(combat_pending.x == 900 && combat_pending.y == 400 && combat_pending.ctrl == next_ctrl);
    return combat_pending.generation;
}
static void cancelled(uint32_t token) {
    combat_confirm(token);
    assert(!commands && !direct_commands && !combat_pending.generation && !ctrl_held && !ctrl_keys);
    assert(touch_cursor_x == -1 && touch_cursor_y == -1);
}
static uint32_t stage_direct(void) {
    /* Native interception has its own exact-ABI regression; supply its armed context here. */
    FIELD(SPELL) = 42; FIELD(CASTER) = 0x8600;
    MEM32(0x8604) = 0x9100; MEM32(0x9104) = 0x20;
    combat_pending_stage(0x4000, -1, -1);
    combat_pending.direct_spell = combat_pending.spell; combat_pending.action = 0;
    combat_pending.direct_wait_until = clock_ns + UINT64_C(5000000000);
    assert(combat_pending.generation && combat_pending_valid() && !commands && !direct_commands);
    assert(combat_pending.direct_spell == 42 && !combat_pending.action);
    return combat_pending.generation;
}
int main(void) {
    /* Default off preserves the original immediate commit; preview alone never commits. */
    reset(); confirm_enabled = 0; combat_point(900, 400, 0); assert(previews == 1 && !commands);
    combat_point(900, 400, 1); assert(commands == 1 && !combat_pending.generation);
    reset(); gesture.placement = 1; combat_point(900, 400, 1); assert(commands == 1 && !combat_pending.generation);

    /* Replacing a gesture invalidates the old button. Double taps on the current button execute once. */
    reset(); uint32_t old = stage(), token = stage(); assert(token != old && previews == 2);
    combat_confirm(0); combat_confirm(old); assert(!commands && combat_pending.generation == token);
    combat_confirm(token); assert(commands == 1 && !combat_pending.generation && resolutions == 3);
    combat_confirm(token); assert(commands == 1 && resolutions == 3);
    reset(); combat_generation = 0xFFFFFF; assert(stage() == 1); /* exact float token transport */

    /* State changes before confirmation invalidate it before even entering native preparation. */
    for (int changed = 0; changed < 15; ++changed) {
        reset(); token = stage();
        switch (changed) {
        case 0: FIELD(ACTOR) = 0x8500; break;
        case 1: FIELD(PHASE) = 0x100; break;
        case 2: FIELD(SPELL) = 42; break;
        case 3: FIELD(CASTER) = 0x8600; break;
        case 4: FIELD(SECOND) = 0x8700; break;
        case 5: FIELD(UI) = 1; break;
        case 6: MEM32(gesture.root + 8) = 0xA000; break;
        case 7: mock_screen = 0x5000; break;
        case 8: FIELD(ROOT) = 0x6100; break;
        case 9: FIELD(CONTROLLER) = 0x8100; break;
        case 10: gesture.root = 0x6100; break;
        case 11: gesture.controller = 0x8100; break;
        case 12: gesture.active = 1; break;
        case 13: confirm_enabled = 0; break;
        case 14: gesture.kind = SCREEN_ADVENTURE; break;
        }
        assert(!combat_pending_valid()); cancelled(token); assert(resolutions == 1);
    }
    /* A fresh native resolve must still describe the same actor, spell and terminal action. */
    for (int changed = 1; changed <= 14; ++changed) {
        reset(); token = stage(); mutate_during_resolve = changed;
        cancelled(token); assert(resolutions == 2);
    }
    reset(); token = stage(); native_blocked = 1; cancelled(token); assert(resolutions == 1);

    /* Spell IDs and creature-caster/second-target references survive context reconstruction. */
    for (int spell = 0; spell < 3; ++spell) {
        reset(); FIELD(SPELL) = spell == 0 ? 42 : 0;
        FIELD(CASTER) = spell != 0 ? 0x8600 : 0; FIELD(SECOND) = spell == 2 ? 0x8700 : 0;
        token = stage(); assert(gesture.aiming);
        assert(combat_pending.spell == FIELD(SPELL) && combat_pending.caster == FIELD(CASTER) &&
               combat_pending.second == FIELD(SECOND));
        combat_confirm(token); assert(commands == 1 && !combat_pending.generation);
    }
    reset(); FIELD(SPELL) = 42; token = stage(); mutate_during_resolve = 15;
    cancelled(token); assert(gesture.cancelled); /* expiring a spell cannot become movement */

    /* Native action 10 selects the first target without spending the turn. Only its final command waits. */
    reset(); FIELD(SPELL) = 42; next_action = 10; combat_point(900, 400, 1);
    assert(first_targets == 1 && !commands && !combat_pending.generation && FIELD(SECOND) == 0x8400);
    next_action = 3; token = stage(); assert(combat_pending.second == 0x8400);
    combat_confirm(token); assert(commands == 1 && first_targets == 1);

    /* Native Ctrl selection (melee / strike without return) is retained and released exactly once. */
    reset(); ctrl_latch(1); next_ctrl = 1; token = stage();
    assert(ctrl_held && ctrl_keys == 1); combat_confirm(token);
    assert(commands == 1 && !ctrl_held && !ctrl_keys);
    reset(); ctrl_latch(1); next_ctrl = 1; token = stage(); FIELD(ACTOR) = 0x8500; cancelled(token);

    /* Targetless abilities retain their armed context; confirmation never resolves a field target. */
    reset(); token = stage_direct(); combat_confirm(token);
    assert(direct_commands == 1 && !commands && !combat_pending.generation && !resolutions && !combat_direct_allowed);
    combat_confirm(token); assert(direct_commands == 1 && !resolutions);
    reset(); old = stage_direct(); token = stage_direct(); combat_confirm(old);
    assert(combat_pending.generation == token && !resolutions && !direct_commands);
    FIELD(SPELL)++; cancelled(token);
    for (int changed = 0; changed < 14; ++changed) {
        reset(); token = stage_direct();
        switch (changed) {
        case 0: FIELD(ACTOR) = 0x8500; break;
        case 1: FIELD(PHASE) = 0x100; break;
        case 2: FIELD(SPELL) = 0; break;
        case 3: FIELD(CASTER) = 0; break;
        case 4: FIELD(SECOND) = 0x8700; break;
        case 5: FIELD(UI) = 1; break;
        case 6: MEM32(0x6008) = 0xA000; break;
        case 7: mock_screen = 0x5000; break;
        case 8: FIELD(ROOT) = 0x6100; break;
        case 9: FIELD(CONTROLLER) = 0x8100; break;
        case 10: MEM8(0x822B) = 0x80; break;
        case 11: MEM8(0x862B) = 0x80; break;
        case 12: gesture.active = 1; break;
        case 13: confirm_enabled = 0; break;
        }
        assert(!combat_pending_valid()); cancelled(token); assert(!resolutions);
    }
    /* The releasing gesture may still describe the spellbook; the captured native screen owns the cast. */
    reset(); token = stage_direct(); gesture.screen = 0x5000; gesture.root = 0x6100;
    gesture.controller = 0; gesture.kind = SCREEN_MENU; combat_confirm(token);
    assert(direct_commands == 1 && !resolutions);
    reset(); token = stage_direct(); combat_pending.source_book = mock_screen = 0x5000;
    assert(combat_direct_pending_state() == 0 && !combat_pending_valid());
    mock_screen = 0x4000; assert(combat_pending_valid()); combat_confirm(token); assert(direct_commands == 1);

    /* A missing or native-invalid command must never advertise an executable button. */
    reset(); no_command = 1; combat_point(900, 400, 1); assert(!combat_pending.generation && !commands);
    reset(); invalid_command = 1; combat_point(900, 400, 1); assert(!combat_pending.generation && !commands);
    reset(); FIELD(UI) = 2; combat_point(900, 400, 1); assert(!combat_pending.generation && !commands);
    printf("PASS combat confirmation (%s): mapped native ABI, stale tokens, spells, action 10, Ctrl, reentrant changes\n", EDITION);
    return 0;
}
'''


class CombatConfirmTest(unittest.TestCase):
    def test_native_transaction_all_editions(self):
        for column, edition in enumerate(("toe", "vanilla", "hof")):
            with self.subTest(edition=edition):
                text = host_text(edition)
                declarations = text[text.index("typedef struct {"):text.index("static uint32_t combat_generation;")]
                host = "\n".join(function(text, sig + "\n{") for sig in FUNCTIONS)
                defines = ['#define EDITION "%s"' % edition, "#define VANILLA %d" % (edition == "vanilla")]
                defines += ["#define %s 0x%Xu" % (name, values[column]) for name, values in (FIELDS | ADDRESSES).items()]
                harness = "\n".join(defines) + "\n" + HARNESS.replace("/* DECLARATIONS */", declarations).replace("/* HOST */", host)
                compile_probe("combat-confirm-" + edition, harness, {}, extra_flags=["/wd4505"])
                # These controls fail during execution, not compilation: a stale button must not
                # consume the newer intent, and a turn change inside resolution must not commit.
                for label, before, after in (
                    ("stale-token", "if (!generation || generation != combat_pending.generation) return;",
                     "if (!generation) return;"),
                    ("changed-actor", "if (!combat_pending_valid() || read32(screen +",
                     "if (0 || read32(screen +"),
                ):
                    self.assertEqual(harness.count(before), 1)
                    with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                        compile_probe("combat-confirm-" + edition + "-" + label,
                                      harness.replace(before, after), {}, extra_flags=["/wd4505"])


if __name__ == "__main__":
    unittest.main()
