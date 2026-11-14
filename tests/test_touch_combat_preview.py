"""Exercise real mapped combat overlay pumps, including caches across successive frames."""
import unittest
import re

from test_d3d_lifecycle import function
from test_legacy_ported_touch import host_text
from test_static_tls import ROOT, compile_probe
from test_touch_combat_confirm import ADDRESSES, FIELDS


FUNCTIONS = (
    "static uint32_t read32(uint32_t address)",
    "static uint32_t virtual_base(uint32_t object, unsigned slot)",
    "static int same_screen(void)",
    "static void ctrl_latch(int on)",
    "static void combat_pending_stage(uint32_t screen, float x, float y)",
    "static void combat_pending_clear(void)",
    "static int combat_direct_pending_state(void)",
    "static int combat_pending_valid(void)",
    "static void combat_pending_pump(void)",
)

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "touch_combat.h"
static unsigned char memory[0x20000];
#define ADDR(p) (memory + (uint32_t)(p))
#define MEM32(p) (*(uint32_t *)ADDR(p))
#define MEM8(p) (*(uint8_t *)ADDR(p))
#define FIELD(offset) MEM32(0x4000 + (offset))
#define VLOG(...) probe_log(__VA_ARGS__)
static void probe_log(const char *format, ...) { (void)format; }
enum { SCREEN_MENU, SCREEN_ADVENTURE, SCREEN_COMBAT, SCREEN_TOWN };
/* DECLARATIONS */
static uint32_t mock_screen, combat_generation;
static int ctrl_held, ctrl_keys, confirm_enabled, route_enabled, hints_enabled;
static int allowed, blocked, alternative_bits, alternative_queries, allowed_queries, blocked_queries;
static int available_bits, available_queries;
static int capture_ok, submit_status, poll_status, capture_calls, submit_calls, poll_calls, cancel_calls;
static uint32_t submitted_ticket, worker_ticket, reply_ticket, cancelled_ticket;
static void_touch_battle_grid worker_grid;
static int geometry_calls, overlay_calls, project_valid, camera_revision;
static uint64_t clock_ns;
static float cursor_x, cursor_y, last_route[COMBAT_ROUTE_FLOATS];
static uint32_t last_generation, last_epoch, geometry_screen, geometry_actor, geometry_serial;
static unsigned last_count;
static int last_hint, geometry_x, geometry_y, geometry_returning;
static int void_vm_readable(uint32_t p, uint32_t n) { return p >= 0x100 && (uint64_t)p + n <= sizeof memory; }
static uint32_t current_screen(void) { return mock_screen; }
static int screen_kind(uint32_t p) { return p == 0x4000 ? SCREEN_COMBAT : SCREEN_MENU; }
static int spellbook_kind(uint32_t p) { return p == 0x5000; }
static int void_port_combat_confirm(void) { return confirm_enabled; }
static int void_port_combat_route(void) { return route_enabled; }
static int void_port_attack_hints(void) { return hints_enabled; }
static uint64_t void_perf_now_ns(void) { return clock_ns; }
static void void_input_key(int key, int down) { assert(key == 0x11); ctrl_keys += down ? 1 : -1; }
static int publish_point(float x, float y) { cursor_x = x; cursor_y = y; return 1; }
static int combat_alternative(uint32_t actor) {
    assert(actor == FIELD(ACTOR)); ++alternative_queries; return alternative_bits;
}
static void require_eligible(uint32_t screen, uint32_t actor) {
    assert(screen == 0x4000 && actor == FIELD(ACTOR));
    assert(hints_enabled && alternative_bits && FIELD(PHASE) == 0x80 && FIELD(ARENA) && FIELD(CONTROLLER) && FIELD(ROOT));
    assert(!MEM32(FIELD(ROOT) + 8) && !FIELD(UI) && !FIELD(SPELL) && !FIELD(CASTER) && !FIELD(SECOND));
}
static int combat_grid_capture(uint32_t screen, uint32_t actor, void_touch_battle_grid *grid) {
    require_eligible(screen, actor); ++capture_calls;
    memset(grid, 0, sizeof *grid);
    grid->width = grid->height = 2; grid->cells[0][0] = actor;
    grid->cells[0][1] = FIELD(ARENA); grid->cells[1][0] = FIELD(CONTROLLER);
    return capture_ok;
}
int void_touch_battle_submit(uint32_t ticket, const void_touch_battle_grid *grid) {
    assert(ticket && grid->cells[0][0] == FIELD(ACTOR) && !grid->cells[1][1]);
    ++submit_calls; submitted_ticket = ticket;
    if (submit_status > 0) { worker_ticket = ticket; worker_grid = *grid; }
    return submit_status;
}
int void_touch_battle_poll(uint32_t ticket, void_touch_battle_grid *grid) {
    assert(ticket && ticket == worker_ticket); ++poll_calls;
    if (reply_ticket && reply_ticket != ticket) return 0; /* Real worker rejects stale tickets. */
    if (poll_status > 0) { *grid = worker_grid; grid->cells[1][1] = 0x5017ED; }
    return poll_status;
}
void void_touch_battle_cancel(void) {
    ++cancel_calls; cancelled_ticket = worker_ticket; worker_ticket = 0;
}
static int combat_alternative_available_grid(uint32_t screen, uint32_t actor, int capabilities,
                                            const void_touch_battle_grid *grid) {
    require_eligible(screen, actor);
    assert(capabilities == alternative_bits && grid->cells[0][0] == actor);
    assert(grid->cells[0][1] == FIELD(ARENA) && grid->cells[1][0] == FIELD(CONTROLLER));
    assert(grid->cells[1][1] == 0x5017ED); /* Never scan a busy/unprocessed capture. */
    ++available_queries; return available_bits;
}
static uint32_t void_call_guest_this(uint32_t va, uint32_t self, int n, const uint32_t *args) {
    assert(self == 0x4000);
    if (VA_ELIGIBLE && va == VA_ELIGIBLE) {
        assert(!n && !args); ++blocked_queries; return 0xCAFE00u | (uint32_t)!blocked;
    }
    assert(n == 1 && args[0] == FIELD(ACTOR));
    if (va == VA_ALLOWED) { ++allowed_queries; return 0xCAFE00u | (uint32_t)allowed; }
    assert(VA_BLOCKED && va == VA_BLOCKED); ++blocked_queries;
    return 0xCAFE00u | (uint32_t)blocked;
}
static unsigned void_touch_combat_route(uint32_t screen, uint32_t actor, int x, int y,
                                       uint32_t serial, int returning, uint32_t action, uint32_t target, float output[COMBAT_ROUTE_FLOATS]) {
    assert(serial && action == FIELD(ACTION) && target == FIELD(TARGET)); ++geometry_calls;
    geometry_screen = screen; geometry_actor = actor; geometry_x = x; geometry_y = y;
    geometry_serial = serial; geometry_returning = returning;
    if (!project_valid) return 0;
    output[0] = returning ? 2.0f : 1.0f; output[1] = 2; output[2] = 10; output[3] = 20;
    output[4] = (float)(x * 10 + camera_revision); output[5] = (float)(y * 10);
    for (unsigned i = 6; i < 14; ++i) output[i] = output[4] + (float)i;
    return 14;
}
static void void_android_combat_overlay(uint32_t generation, uint32_t epoch, int hint,
                                       const float *route, unsigned count) {
    assert(count <= COMBAT_ROUTE_FLOATS); ++overlay_calls;
    last_generation = generation; last_epoch = epoch; last_hint = hint; last_count = count;
    if (count) memcpy(last_route, route, count * sizeof(float));
}
/* HOST */
static void reset(void) {
    memset(memory, 0, sizeof memory); memset(&gesture, 0, sizeof gesture);
    memset(&combat_pending, 0, sizeof combat_pending);
    /* Drive real transitions to clear static caches: no source rewriting or test-only reset. */
    mock_screen = 0; route_enabled = confirm_enabled = 0; hints_enabled = 1;
    clock_ns += UINT64_C(100000000); combat_pending_pump();
    hints_enabled = 0; combat_pending_pump();
    gesture.screen = mock_screen = 0x4000; gesture.root = 0x6000; gesture.controller = 0x8000;
    gesture.kind = SCREEN_COMBAT; gesture.active = gesture.combat_aim = 1;
    FIELD(ROOT) = gesture.root; FIELD(CONTROLLER) = gesture.controller;
    FIELD(ACTOR) = 0x8200; FIELD(PHASE) = 0x80; FIELD(COMMAND) = 0x8300; FIELD(ARENA) = 0xA100;
    MEM32(0x8204) = 0x9000; MEM32(0x9004) = 0x20;
    MEM32(0x8504) = 0x9100; MEM32(0x9104) = 0x20;
    FIELD(ACTION) = 2; FIELD(TARGET) = 0x8400; FIELD(CELL_X) = 17; FIELD(CELL_Y) = 23;
    ctrl_held = ctrl_keys = geometry_calls = overlay_calls = 0;
    alternative_queries = allowed_queries = blocked_queries = available_queries = 0;
    capture_calls = submit_calls = poll_calls = cancel_calls = 0;
    capture_ok = submit_status = poll_status = 1;
    submitted_ticket = worker_ticket = reply_ticket = cancelled_ticket = 0;
    combat_order_revision = 0;
    allowed = project_valid = route_enabled = 1; blocked = camera_revision = 0; alternative_bits = 3;
    available_bits = 3;
    cursor_x = cursor_y = -1;
}
static uint32_t pending(void) {
    confirm_enabled = 1; gesture.active = 0;
    combat_pending_stage(0x4000, 900, 400);
    assert(combat_pending_valid()); return combat_pending.generation;
}
static void require_route(int generation) {
    assert(last_count == 14 && last_generation == (uint32_t)generation && geometry_calls);
    assert(geometry_screen == 0x4000 && geometry_actor == 0x8200 && geometry_x == 17 && geometry_y == 23);
}
static uint32_t pending_direct(int book) {
    confirm_enabled = 1; gesture.active = 0; FIELD(SPELL) = 42; FIELD(CASTER) = 0x8200;
    combat_pending_stage(0x4000, -1, -1);
    combat_pending.direct_spell = combat_pending.spell; combat_pending.action = 0;
    combat_pending.source_book = book ? 0x5000 : 0;
    combat_pending.direct_wait_until = clock_ns + UINT64_C(5000000000);
    return combat_pending.generation;
}
int main(void) {
    /* The route toggle is independent of the confirmation and alternative-hint toggles. */
    for (int route = 0; route < 2; ++route) for (int confirm = 0; confirm < 2; ++confirm)
    for (int hints = 0; hints < 2; ++hints) {
        reset(); route_enabled = route; confirm_enabled = confirm; hints_enabled = hints;
        combat_pending_pump();
        assert(last_generation == 0 && last_count == (route ? 14u : 0u));
        assert(geometry_calls == route && last_hint == (hints ? 3 : 0));
        assert(alternative_queries == (route || hints ? 1 : 0));
        assert(allowed_queries == alternative_queries);
        assert(available_queries == hints);
        assert(capture_calls == hints && submit_calls == hints && poll_calls == hints);
    }
    /* No per-frame native ability/ownership work, geometry throttled, unchanged JNI packet suppressed. */
    reset(); combat_pending_pump(); require_route(0);
    uint32_t serial = geometry_serial, epoch = last_epoch; int sent = overlay_calls;
    for (int frame = 0; frame < 20; ++frame) combat_pending_pump();
    assert(geometry_calls == 1 && alternative_queries == 1 && allowed_queries == 1 && overlay_calls == sent);
    clock_ns += UINT64_C(49999999); combat_pending_pump(); assert(geometry_calls == 1);
    ++clock_ns; combat_pending_pump(); assert(geometry_calls == 2 && overlay_calls == sent && geometry_serial == serial);
    camera_revision = 1; clock_ns += UINT64_C(50000000); combat_pending_pump();
    assert(geometry_calls == 3 && overlay_calls == sent + 1 && last_epoch == epoch);

    /* New terminal geometry bypasses the timer; changing mode without changing geometry reuses it. */
    reset(); combat_pending_pump(); serial = geometry_serial;
    FIELD(CELL_X) = 18; combat_pending_pump(); assert(geometry_calls == 2 && geometry_x == 18 && geometry_serial != serial);
    serial = geometry_serial; FIELD(CELL_Y) = 24; combat_pending_pump();
    assert(geometry_calls == 3 && geometry_y == 24 && geometry_serial != serial);
    FIELD(ACTION) = 3; combat_pending_pump(); assert(geometry_calls == 4 && geometry_returning);
    ctrl_latch(1); combat_pending_pump(); assert(geometry_calls == 5 && !geometry_returning);
    ctrl_latch(0); combat_pending_pump(); assert(geometry_calls == 6 && geometry_returning);
    FIELD(ACTOR) = 0x8500; combat_pending_pump(); assert(geometry_calls == 7 && geometry_actor == 0x8500);
    assert(alternative_queries == 2 && allowed_queries == 2);

    /* Shots and direct hero strikes reach the arrow renderer with either input mode. */
    const uint32_t arrow_actions[] = {4, 5, 9};
    for (unsigned i = 0; i < sizeof(arrow_actions) / sizeof(arrow_actions[0]); ++i) {
        reset(); FIELD(ACTION) = arrow_actions[i]; combat_pending_pump(); require_route(0);
        assert(!geometry_returning);
        reset(); FIELD(ACTION) = arrow_actions[i]; uint32_t arrow_token = pending();
        combat_pending_pump(); require_route((int)arrow_token); assert(!geometry_returning);
    }

    /* A new prepared command can reuse the same unit, endpoint and return mode. */
    reset(); combat_pending_pump(); serial = geometry_serial;
    ++combat_order_revision; combat_pending_pump();
    assert(geometry_calls == 2 && geometry_serial != serial); serial = geometry_serial;
    FIELD(TARGET) = 0x8410; combat_pending_pump();
    assert(geometry_calls == 3 && geometry_serial != serial); serial = geometry_serial;
    ctrl_latch(1); FIELD(ACTION) = 3; combat_pending_pump();
    assert(geometry_calls == 4 && geometry_serial != serial && !geometry_returning);
    FIELD(COMMAND) = 0x8310; combat_pending_pump();
    assert(geometry_calls == 4); /* Pointer churn alone is not a new order. */

    /* Hiding resets visibility so an identical destination appears immediately on re-enable. */
    reset(); combat_pending_pump(); serial = geometry_serial;
    route_enabled = 0; combat_pending_pump(); assert(!last_count && geometry_calls == 1);
    route_enabled = 1; combat_pending_pump(); require_route(0);
    assert(geometry_calls == 2 && geometry_serial != serial);
    project_valid = 0; clock_ns += UINT64_C(50000000); combat_pending_pump(); assert(!last_count);
    project_valid = 1; clock_ns += UINT64_C(50000000); combat_pending_pump(); require_route(0);

    /* Non-world gestures, stale screens, modal UI and non-spatial actions never draw a route. */
    for (int bad = 0; bad < 19; ++bad) {
        reset();
        switch (bad) {
        case 0: gesture.ui = 1; break;
        case 1: gesture.placement = 1; break;
        case 2: gesture.cancelled = 1; break;
        case 3: gesture.info = 1; break;
        case 4: gesture.card = 1; break;
        case 5: gesture.inspecting = 1; break;
        case 6: gesture.active = 0; break;
        case 7: gesture.combat_aim = gesture.aiming = 0; break;
        case 8: gesture.kind = SCREEN_ADVENTURE; break;
        case 9: mock_screen = 0x5000; break;
        case 10: FIELD(ROOT) = 0x6100; break;
        case 11: FIELD(CONTROLLER) = 0x8100; break;
        case 12: FIELD(UI) = 1; break;
        case 13: FIELD(PHASE) = 0x200; break;
        case 14: FIELD(COMMAND) = 0; break;
        case 15: MEM32(0x8304) = 0x80000000u; break;
        case 16: FIELD(ACTOR) = 0; break;
        case 17: FIELD(ACTION) = 10; break;
        case 18: MEM32(gesture.root + 8) = 0xA000; break;
        }
        combat_pending_pump(); assert(!geometry_calls && !last_count && !last_generation);
    }

    /* A pending action retains a button even with route hidden; replacement does not stale geometry. */
    reset(); uint32_t token = pending(); route_enabled = 0; combat_pending_pump();
    assert(last_generation == token && !last_count && !geometry_calls && cursor_x == 900 && cursor_y == 400);
    route_enabled = 1; combat_pending_pump(); require_route((int)token); serial = geometry_serial;
    token = pending(); combat_pending_pump(); assert(last_generation == token && geometry_calls == 1 && geometry_serial == serial);
    FIELD(CELL_X) = 18; token = pending(); combat_pending_pump();
    assert(last_generation == token && geometry_calls == 2 && geometry_x == 18);
    FIELD(ACTOR) = 0x8500; combat_pending_pump();
    assert(!combat_pending.generation && !last_generation && !last_count && cursor_x == -1 && cursor_y == -1);
    reset(); token = pending(); FIELD(ACTION) = 3; combat_pending.action = 3; combat_pending.ctrl = 1;
    combat_pending_pump(); require_route((int)token); assert(!geometry_returning && ctrl_held && ctrl_keys == 1);
    confirm_enabled = 0; combat_pending_pump();
    assert(!last_count && !last_generation && !ctrl_held && !ctrl_keys);
    reset(); pending_direct(0); combat_pending_pump();
    assert(last_generation && !last_count && !geometry_calls); /* targetless ability still has its button */
    reset(); token = pending_direct(1); mock_screen = 0x5000; combat_pending_pump();
    assert(combat_pending.generation == token && !last_generation && !last_count && !geometry_calls);
    FIELD(PHASE) = 8; /* Native next frame arms the spell after the hook captured idle phase128. */
    clock_ns += UINT64_C(1000000000); combat_pending_pump(); assert(combat_pending.generation == token && !last_generation);
    mock_screen = 0x4000; combat_pending_pump();
    assert(last_generation == token && !combat_pending.source_book && !last_count && !geometry_calls);
    clock_ns += UINT64_C(10000000000); combat_pending_pump();
    assert(last_generation == token && combat_pending.generation == token && !last_count);
    MEM32(gesture.root + 8) = 0xA000; combat_pending_pump(); assert(!last_generation && !combat_pending.generation);
    reset(); token = pending_direct(1); mock_screen = 0x5000; combat_pending_pump();
    clock_ns += UINT64_C(5000000000); combat_pending_pump(); assert(!combat_pending.generation && !last_generation);

    /* Alternative hints recheck ownership on actor/phase changes, not every animation frame. */
    reset(); hints_enabled = 1; route_enabled = 0; allowed = 0; combat_pending_pump();
    assert(!last_hint && allowed_queries == 1 && !blocked_queries);
    for (int frame = 0; frame < 20; ++frame) combat_pending_pump();
    assert(alternative_queries == 1 && allowed_queries == 1);
    assert(!available_queries);
    allowed = 1; FIELD(PHASE) = 0x100; combat_pending_pump();
    assert(!last_hint && allowed_queries == 2 && blocked_queries == 1 && !available_queries);
    FIELD(PHASE) = 0x80; combat_pending_pump();
    assert(last_hint == 3 && allowed_queries == 3 && blocked_queries == 2 && available_queries == 1);
    FIELD(SPELL) = 42; combat_pending_pump(); assert(!last_hint && allowed_queries == 3);
    FIELD(SPELL) = 0; combat_pending_pump(); assert(last_hint == 3 && allowed_queries == 3 && available_queries == 1);
    blocked = 1; FIELD(ACTOR) = 0x8500; combat_pending_pump();
    assert(!last_hint && blocked_queries == 3 && available_queries == 1);

    /* Reachability is cached even when no alternative is available; unchanged frames cost no guest queries. */
    for (int mask = 0; mask < 4; ++mask) {
        reset(); route_enabled = 0; hints_enabled = 1; available_bits = mask;
        combat_pending_pump(); assert(last_hint == mask && available_queries == 1);
        epoch = last_epoch; sent = overlay_calls;
        for (int frame = 0; frame < 1000; ++frame) {
            clock_ns += UINT64_C(16666667); combat_pending_pump();
        }
        assert(available_queries == 1 && alternative_queries == 1 && allowed_queries == 1 && blocked_queries == 1);
        assert(capture_calls == 1 && submit_calls == 1 && poll_calls == 1);
        assert(last_hint == mask && last_epoch == epoch && overlay_calls == sent && !geometry_calls);
    }

    /* Busy work never blocks a pump or recaptures native state: one bounded try per frame. */
    reset(); route_enabled = 0; hints_enabled = 1; submit_status = poll_status = 0;
    combat_pending_pump(); epoch = last_epoch;
    assert(capture_calls == 1 && submit_calls == 1 && !poll_calls && !available_queries && !last_hint);
    for (int frame = 0; frame < 100; ++frame) combat_pending_pump();
    assert(capture_calls == 1 && submit_calls == 101 && !poll_calls && !available_queries);
    submit_status = 1; combat_pending_pump();
    assert(capture_calls == 1 && submit_calls == 102 && poll_calls == 1 && !last_hint);
    for (int frame = 0; frame < 1000; ++frame) combat_pending_pump();
    assert(capture_calls == 1 && submit_calls == 102 && poll_calls == 1001 && !available_queries);
    assert(last_epoch == epoch && alternative_queries == 1 && allowed_queries == 1);
    poll_status = 1; combat_pending_pump();
    assert(last_hint == 3 && available_queries == 1 && poll_calls == 1002);
    for (int frame = 0; frame < 1000; ++frame) combat_pending_pump();
    assert(capture_calls == 1 && submit_calls == 102 && poll_calls == 1002 && available_queries == 1);

    /* Failure at any stage becomes a cached negative result until the next state key. */
    for (int stage = 0; stage < 3; ++stage) {
        reset(); route_enabled = 0; hints_enabled = 1;
        if (stage == 0) capture_ok = 0;
        if (stage == 1) submit_status = -1;
        if (stage == 2) poll_status = -1;
        combat_pending_pump();
        assert(capture_calls == 1 && submit_calls == (stage != 0) && poll_calls == (stage == 2));
        assert(!available_queries && !last_hint);
        for (int frame = 0; frame < 1000; ++frame) combat_pending_pump();
        assert(capture_calls == 1 && submit_calls == (stage != 0) && poll_calls == (stage == 2));
        assert(!available_queries && !last_hint);
        capture_ok = submit_status = poll_status = 1;
        FIELD(ARENA) = 0xA200; combat_pending_pump();
        assert(capture_calls == 2 && available_queries == 1 && last_hint == 3);
    }

    /* Any ownership/context key cancels in-flight work and rejects a late old-ticket result. */
    for (int key = 0; key < 6; ++key) {
        reset(); route_enabled = 0; hints_enabled = 1; poll_status = 0;
        combat_pending_pump(); uint32_t old_ticket = submitted_ticket;
        epoch = last_epoch;
        assert(old_ticket && capture_calls == 1 && cancel_calls == 1);
        switch (key) {
        case 0: FIELD(ARENA) = 0xA200; break;
        case 1: FIELD(CONTROLLER) = 0x8100; break;
        case 2: FIELD(ACTOR) = 0x8500; break;
        case 3: FIELD(PHASE) = 8; break;
        case 4: mock_screen = 0x5000; break;
        case 5: hints_enabled = 0; break;
        }
        combat_pending_pump();
        assert(cancelled_ticket == old_ticket && cancel_calls == 2 && !last_hint);
        if (key >= 3) {
            assert(capture_calls == 1 && submit_calls == 1 && poll_calls == 1);
            FIELD(PHASE) = 0x80; mock_screen = 0x4000; hints_enabled = 1;
            combat_pending_pump();
        }
        assert(submitted_ticket && submitted_ticket != old_ticket && last_epoch != epoch);
        assert(capture_calls == 2 && submit_calls == 2 && !available_queries);
        poll_status = 1; reply_ticket = old_ticket; combat_pending_pump();
        assert(!last_hint && !available_queries && capture_calls == 2 && submit_calls == 2);
        reply_ticket = submitted_ticket; combat_pending_pump();
        assert(last_hint == 3 && available_queries == 1 && capture_calls == 2);
    }

    /* Temporary UI/spell hiding pauses a pending poll without changing its ticket or dismissal epoch. */
    reset(); route_enabled = 0; hints_enabled = 1; poll_status = 0;
    combat_pending_pump(); epoch = last_epoch; uint32_t waiting_ticket = submitted_ticket;
    const unsigned busy_hidden_fields[] = {UI, SPELL, CASTER, SECOND};
    for (unsigned i = 0; i < sizeof busy_hidden_fields / sizeof busy_hidden_fields[0]; ++i) {
        int polls = poll_calls;
        FIELD(busy_hidden_fields[i]) = 1; combat_pending_pump();
        assert(!last_hint && poll_calls == polls && last_epoch == epoch);
        FIELD(busy_hidden_fields[i]) = 0; combat_pending_pump();
        assert(poll_calls == polls + 1 && submitted_ticket == waiting_ticket && last_epoch == epoch);
    }
    int polls = poll_calls;
    MEM32(gesture.root + 8) = 0xA000; combat_pending_pump();
    assert(!last_hint && poll_calls == polls && last_epoch == epoch);
    MEM32(gesture.root + 8) = 0; poll_status = 1; combat_pending_pump();
    assert(last_hint == 3 && available_queries == 1 && capture_calls == 1 && submit_calls == 1);
    assert(cancel_calls == 1 && submitted_ticket == waiting_ticket && last_epoch == epoch);

    /* Route mode depends on the ability, not on whether a hint has a usable target. */
    reset(); hints_enabled = 1; available_bits = 0; FIELD(ACTION) = 3;
    combat_pending_pump(); require_route(0);
    assert(!last_hint && available_queries == 1 && geometry_returning);
    ctrl_latch(1); combat_pending_pump(); assert(!geometry_returning && available_queries == 1);
    hints_enabled = 0; ctrl_latch(0); combat_pending_pump();
    assert(geometry_returning && available_queries == 1);

    /* Hidden/modal/non-player/invalid states must not start the original availability calculation. */
    for (int bad = 0; bad < 18; ++bad) {
        reset(); route_enabled = 0; hints_enabled = 1;
        switch (bad) {
        case 0: FIELD(PHASE) = 8; break;
        case 1: FIELD(PHASE) = 0x100; break;
        case 2: FIELD(PHASE) = 0x1000; break;
        case 3: FIELD(UI) = 1; break;
        case 4: FIELD(SPELL) = 42; break;
        case 5: FIELD(CASTER) = 0x8200; break;
        case 6: FIELD(SECOND) = 0x8400; break;
        case 7: FIELD(ROOT) = 0; break;
        case 8: MEM32(gesture.root + 8) = 0xA000; break;
        case 9: MEM8(0x822B) = 0x80; break;
        case 10: FIELD(ACTOR) = 0; break;
        case 11: mock_screen = 0x5000; break;
        case 12: alternative_bits = 0; break;
        case 13: allowed = 0; break;
        case 14: blocked = 1; break;
        case 15: MEM32(0x8204) = 0x1FFFF; break;
        case 16: FIELD(ARENA) = 0; break;
        case 17: FIELD(CONTROLLER) = 0; break;
        }
        combat_pending_pump();
        assert(!capture_calls && !submit_calls && !poll_calls && !available_queries && !last_hint);
    }

    /* Temporary hiding on the same idle phase preserves both the query cache and dismissal epoch. */
    reset(); route_enabled = 0; hints_enabled = 1; combat_pending_pump(); epoch = last_epoch;
    const unsigned hidden_fields[] = {UI, SPELL, CASTER, SECOND};
    for (unsigned i = 0; i < sizeof hidden_fields / sizeof hidden_fields[0]; ++i) {
        FIELD(hidden_fields[i]) = 1; combat_pending_pump();
        assert(!last_hint && available_queries == 1 && last_epoch == epoch);
        FIELD(hidden_fields[i]) = 0; combat_pending_pump();
        assert(last_hint == 3 && available_queries == 1 && last_epoch == epoch);
    }
    MEM32(gesture.root + 8) = 0xA000; combat_pending_pump();
    assert(!last_hint && available_queries == 1 && last_epoch == epoch);
    MEM32(gesture.root + 8) = 0; combat_pending_pump();
    assert(last_hint == 3 && available_queries == 1 && last_epoch == epoch);

    /* Camera/target/destination/command and confirmation changes do not alter reachable alternatives. */
    for (unsigned tap = 0; tap < 10; ++tap) {
        ++FIELD(CELL_X); ++FIELD(CELL_Y); FIELD(TARGET) = 0x8400 + 16 * tap;
        FIELD(COMMAND) = 0xB000 + 16 * tap; FIELD(ACTION) = 2 + tap % 3; ++camera_revision;
        clock_ns += UINT64_C(100000000); combat_pending_pump();
        pending(); combat_pending_pump();
        assert(available_queries == 1 && alternative_queries == 1 && last_epoch == epoch);
    }
    memset(&combat_pending, 0, sizeof combat_pending);
    FIELD(ARENA) = 0xA200; combat_pending_pump();
    assert(available_queries == 2 && last_epoch != epoch); epoch = last_epoch;
    FIELD(CONTROLLER) = gesture.controller = 0x8100; combat_pending_pump();
    assert(available_queries == 3 && last_epoch != epoch); epoch = last_epoch;
    FIELD(ACTOR) = 0x8500; combat_pending_pump();
    assert(available_queries == 4 && last_epoch != epoch); epoch = last_epoch;
    const unsigned phases[] = {8, 0x100, 0x1000};
    for (unsigned i = 0; i < sizeof phases / sizeof phases[0]; ++i) {
        FIELD(PHASE) = phases[i]; combat_pending_pump();
        assert(!last_hint && available_queries == 4 + (int)i);
        FIELD(PHASE) = 0x80; combat_pending_pump();
        assert(last_hint == 3 && available_queries == 5 + (int)i && last_epoch != epoch); epoch = last_epoch;
    }
    hints_enabled = 0; combat_pending_pump(); assert(!last_hint && available_queries == 7);
    hints_enabled = 1; combat_pending_pump(); assert(last_hint == 3 && available_queries == 8 && last_epoch != epoch);
    printf("PASS combat preview (%s): independent toggles/routes, async capture/submit/poll/cancel, late-ticket isolation, positive/negative caching, bounded queries, order revision and ownership/geometry/JNI caches\n", EDITION);
    return 0;
}
'''


class CombatPreviewTest(unittest.TestCase):
    def test_native_pump_all_editions(self):
        for column, edition in enumerate(("toe", "vanilla", "hof")):
            with self.subTest(edition=edition):
                text = host_text(edition)
                declarations = text[text.index("typedef struct {"):text.index("static uint32_t combat_generation;")]
                host = "\n".join(function(text, sig + "\n{") for sig in FUNCTIONS)
                header = (ROOT / "android/host/touch.h").read_text()
                defines = [re.search(r"enum \{ COMBAT_ROUTE_MAX_POINTS =[^;]+;", header)[0],
                           '#define EDITION "%s"' % edition,
                           '#define ARENA 0x%Xu' % (0x2A0, 0x280, 0x294)[column]]
                defines += ["#define %s 0x%Xu" % (name, values[column]) for name, values in (FIELDS | ADDRESSES).items()]
                harness = "\n".join(defines) + "\n" + HARNESS.replace("/* DECLARATIONS */", declarations).replace("/* HOST */", host)
                headers = {"touch_combat.h": (ROOT / "android/host/touch_combat.h").read_text()}
                compile_probe("combat-preview-" + edition, harness, headers, extra_flags=["/wd4505"])
                for label, before, after in (
                    ("ignored-toggle", "int route_wanted = void_port_combat_route() &&",
                     "int route_wanted = 1 &&"),
                    ("stale-cell", "if (!changed && now < next_route_ns)",
                     "if (now < next_route_ns)"),
                    ("availability-every-frame", "if (available < 0) {", "if (1) { grid_state = 0;"),
                    ("capability-only-hint", "combat_alternative_available_grid(screen, actor, alternatives, &hint_grid)",
                     "alternatives"),
                    ("uncancelled-worker", "            void_touch_battle_cancel();", "            (void)0;"),
                    ("stale-ticket", "if (!++grid_ticket) ++grid_ticket;", "if (!grid_ticket) ++grid_ticket;"),
                    ("busy-as-result", "if (ready) {", "if (ready >= 0) {"),
                    ("stale-order-route", "combat_order_revision != route_revision || action != route_action || target != route_target",
                     "0 != 0"),
                ):
                    self.assertEqual(harness.count(before), 1)
                    with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                        compile_probe("combat-preview-" + edition + "-" + label,
                                      harness.replace(before, after), headers, extra_flags=["/wd4505"])


if __name__ == "__main__":
    unittest.main()
