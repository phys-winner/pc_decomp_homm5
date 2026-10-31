/* Touch intent enters below DirectInput: UI owns its windows, the map owns orders. */
#include "host.h"
#include "touch.h"
#include "input.h"
#include <math.h>
#include <string.h>

enum { SCREEN_MENU, SCREEN_ADVENTURE, SCREEN_COMBAT, SCREEN_TOWN };
typedef struct {
    uint32_t screen, root, controller, dnd;
    uint32_t combo;
    int kind, active, ui, book, announcement, aiming, committed, cancelled, held, pressed, placement, panning, retiring;
    uint64_t release_frame, begin_frame;
    float start_x, start_y, x, y;
    int dnd_claim, dnd_pressed, ghost_energy, second_troop, army_portrait;
    /* info: a held finger shows the world tooltip (the right-click info) and
     * gives no order; world_hover: the held finger hovers the world for it;
     * combat_aim: one finger in combat is the cursor, released into an order. */
    int info, world_hover, combat_aim, second_info, inspecting;
    float inspect_x, inspect_y;
    int details;   /* a still hold on the world (or a combat control): 1 waits for its tooltip, 2 asked for the details card */
    int card;   /* a second finger rests while the first aims in combat (2: the first lifted, no order) */
    /* A second-finger tap keeps the card until the first finger lifts (no order); later taps
     * switch the card and the effects ("status") panel. card_mode: 1 card, 2 effects. */
    int card_sticky, card_mode, card_retries;
    uint64_t card_frame;
    int atb;   /* the touch began on the selected initiative portrait and keeps its point */
    int melee;   /* a drag from the active shooter attacks in melee (Ctrl held, as Ctrl+click) */
    /* A slider dragged from its lever's centre (logical lever, logical finger start). */
    int slider;
    float slider_x, slider_y, slider_fx, slider_fy;
} touch_gesture;
static touch_gesture gesture;
static uint32_t scratch;
static int touch_mode;
static uint64_t cursor_started_ns;
static float touch_cursor_x = -1, touch_cursor_y = -1;
static struct { uint32_t screen; float x, y; uint64_t frame; int pending; } pointer_text;
static void_fn original_cursor;
static void_fn original_cursor_draw;
static void_fn original_cursor_hardware_query;
static uint32_t cursor_software_owner;
static uint64_t touch_frame;
static struct {
    uint32_t screen, root, root_window, field, table, epoch;
    int kind, pending;
    uint64_t frame;
} text_target;
static struct { uint32_t screen, root, helper; int invalid; } drag_owner;

void void_touch_frame_presented(void) { ++touch_frame; }

int void_touch_engine_ready(int kind)
{
    if (kind == TOUCH_ABORT || kind == TOUCH_POINTER || kind == TOUCH_PAD_CAMERA) return 1;
    if (kind == TOUCH_BEGIN && gesture.retiring && touch_frame == gesture.release_frame) return 0;
    return !(gesture.active && gesture.ui &&
             (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP) && touch_frame == gesture.begin_frame);
}

static uint32_t read32(uint32_t address)
{
    return void_vm_readable(address, 4) ? MEM32(address) : 0;
}

static uint32_t virtual_base(uint32_t object, unsigned slot)
{
    uint32_t table = read32(object + 4), offset;
    if (!object || !table || !void_vm_readable(table + slot, 4)) return 0;
    offset = MEM32(table + slot);
    uint32_t base = object + 4 + offset;
    return void_vm_readable(base, 4) ? base : 0;
}

static uint32_t current_screen(void)
{
    uint32_t list = read32(0x00FE719Cu);
    if (!list || !void_vm_readable(list, 12) || !void_dispatch_find(0x008385A0u)) return 0;
    uint32_t interface = void_call_guest(0x008385A0u, 0, NULL, 1);
    uint32_t base = virtual_base(interface, 4);
    if (!base) return 0;
    const uint32_t args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
    uint32_t screen = void_call_guest(0x00D119FCu, 5, args, 0);
    return void_vm_readable(screen, 0x164) ? screen : 0;
}

static int screen_kind(uint32_t screen)
{
    uint32_t table = read32(screen);
    return table == 0x00E230E4u ? SCREEN_ADVENTURE :
           table == 0x00E1DA84u ? SCREEN_COMBAT :
           table == 0x00E2A64Cu ? SCREEN_TOWN : SCREEN_MENU;
}

static int spellbook_kind(uint32_t screen)
{
    uint32_t table = read32(screen);
    return table == 0x00E30EB4u ? 1 : table == 0x00E30CA4u ? 2 : 0;
}

#ifdef VOID_ANDROID_APP
void void_android_return_to_launcher(void);
void void_android_gamepad_help(void);
void void_android_switch_game(void);
int void_android_take_game_switch(void);
static void_fn original_game_message, original_exit_confirm;
static int launcher_pending, launcher_question_seen, switch_confirm_pending;

/* CARSendGameMessage::Run is virtual; keep direct lifted callers and PGO intact. */
static void port_game_message(void)
{
    uint32_t self = g_ecx;
    void_regs saved;
    void_regs_save(&saved);
    uint32_t db = void_call_guest_this(0x00B299F0u, self + 0xC, 0, NULL);
    uint32_t begin = read32(db + 0x48), end = read32(db + 0x4C);
    int launcher = db && end - begin == 13 && void_vm_readable(begin, 13) &&
                   !memcmp(GPTR(begin), "port_launcher", 13);
    int gamepad = db && end - begin == 12 && void_vm_readable(begin, 12) &&
                  !memcmp(GPTR(begin), "port_gamepad", 12);
    int switch_game = db && end - begin == 16 && void_vm_readable(begin, 16) &&
                      !memcmp(GPTR(begin), "port_switch_game", 16);
    void_regs_load(&saved);
    if (gamepad || switch_game) {
        if (switch_game) void_android_switch_game();
        else void_android_gamepad_help();
        g_eax = (g_eax & ~255u) | 1u;
        g_esp += 16;
        return;
    }
    if (!launcher) { original_game_message(); return; }
    uint32_t screen = current_screen(), table = read32(screen);
    if (table == 0x00E3DA1Cu && read32(screen + 0x1A0) == 2) {
        /* Accept pending options through the original profile-saving path. */
        void_call_guest_this(0x0075C8E0u, screen, 0, NULL);
        launcher_pending = 1;
        launcher_question_seen = 0;
        void_call_guest(0x00689790u, 0, NULL, 1); /* Original exit-attempt command. */
    }
    void_regs_load(&saved);
    g_eax = (g_eax & ~255u) | 1u;
    g_esp += 16;                         /* Run's return address and three arguments */
}

static void port_exit_confirm(void)
{
    if (launcher_pending) void_android_return_to_launcher();
    launcher_pending = launcher_question_seen = switch_confirm_pending = 0;
    original_exit_confirm();
}

static void port_launcher_visibility(uint32_t window, unsigned depth, int visible)
{
    if (depth > 4 || !void_vm_readable(window, 0xAC)) return;
    uint32_t getter = read32(read32(window) + 8);
    if (!void_dispatch_find(getter)) return;
    uint32_t placement = void_call_guest_this(getter, window, 0, NULL);
    uint32_t begin = read32(placement + 0x58), end = read32(placement + 0x5C);
    int button = end - begin == 19 && void_vm_readable(begin, 19) && !memcmp(GPTR(begin), "PortOptionsLauncher", 19);
    if (button && void_vm_readable(placement + 0x70, 1)) {
        /* Children store CWindow; SetVisible belongs to its virtual IWindow base. */
        uint32_t vb = read32(window + 0x10), interface = vb ? window + 0x10 + read32(vb + 8) : 0;
        uint32_t show = button && visible, setter = read32(read32(interface) + 0x44);
        if (MEM8(placement + 0x70) != show && void_dispatch_find(setter))
            void_call_guest_this(setter, interface, 1, &show);
        return;
    }
    if (!void_vm_readable(placement + 0x70, 1) || !MEM8(placement + 0x70)) return;
    begin = read32(window + 0xA4); end = read32(window + 0xA8);
    if (!begin || end < begin || (end - begin) % 4 || end - begin > 4096 || !void_vm_readable(begin, end - begin)) return;
    for (uint32_t at = begin; at < end; at += 4) port_launcher_visibility(MEM32(at), depth + 1, visible);
}

static void port_menu_pump(void)
{
    uint32_t screen = current_screen(), table = read32(screen);
    if (table == 0x00E3DA1Cu) {
        uint32_t root = read32(screen + 0xA0);
        if (root >= 0xF8) port_launcher_visibility(root - 0xF8, 0, read32(screen + 0x1A0) == 2);
    }
    if (void_android_take_game_switch() && screen && !switch_confirm_pending) {
        void_android_return_to_launcher();
        switch_confirm_pending = 1;
        void_call_guest(0x00689790u, 0, NULL, 1);
        return;
    }
    if (switch_confirm_pending && table == 0x00E3112Cu) {
        uint32_t zero = 0;
        switch_confirm_pending = 0;
        void_call_guest_this(0x006895E0u, screen + 0x174, 1, &zero);
        return;
    }
    if (launcher_pending) {
        if (table == 0x00E3112Cu) launcher_question_seen = 1;
        else if (launcher_question_seen) launcher_pending = launcher_question_seen = 0;
    }
}
#endif

static int same_screen(void)
{
    uint32_t screen = current_screen();
    return screen && screen == gesture.screen && screen_kind(screen) == gesture.kind &&
           read32(screen + 0xA0) == gesture.root &&
           ((gesture.kind == SCREEN_MENU || gesture.kind == SCREEN_TOWN) ||
            read32(screen + (gesture.kind == SCREEN_ADVENTURE ? 0x5F4 : 0x2B4)) == gesture.controller);
}

static uint32_t logical_point(float x, float y)
{
    if (!scratch) scratch = void_galloc(512);
    if (!scratch || !void_vm_writable(scratch, 512)) return 0;
    MEMF(scratch) = x; MEMF(scratch + 4) = y;
    /* The UI's outside sentinel is logical, independent of letterboxing. */
    if (x < 0 || y < 0) { MEMF(scratch) = MEMF(scratch + 4) = -1.0f; return scratch; }
    uint32_t point = void_call_guest_this(0x00B29220u, scratch, 0, NULL);
    if (!void_vm_readable(point, 8)) return 0;
    memcpy((void *)ADDR(scratch), (const void *)ADDR(point), 8);
    return scratch;
}

static int publish_point(float x, float y)
{
    touch_cursor_x = x; touch_cursor_y = y;
    uint32_t point = logical_point(x, y);
    if (point) memcpy((void *)ADDR(scratch + 480), (const void *)ADDR(point), 8);
    return point != 0;
}

static int target_armed(void)
{
    return gesture.kind == SCREEN_ADVENTURE ? read32(gesture.controller + 0x44) == 5 :
           gesture.kind == SCREEN_COMBAT && (read32(gesture.screen + 0x394) ||
           read32(gesture.screen + 0x388) || read32(gesture.screen + 0x38C));
}

static int refresh_target_mode(void)
{
    if (gesture.ui || gesture.placement || gesture.committed || gesture.cancelled) return !gesture.cancelled;
    int armed = target_armed();
    if (gesture.aiming && !armed) {
        /* A turn change or native cancellation must never turn this release into a move. */
        gesture.cancelled = 1;
        publish_point(-1, -1);
        VLOG("[touch] target expired screen=%08X kind=%d", gesture.screen, gesture.kind);
        return 0;
    }
    if (armed) gesture.aiming = 1;
    return 1;
}

static int adventure_announcement(float x, float y, int activate)
{
    if (gesture.kind != SCREEN_ADVENTURE || !same_screen()) return 0;
    uint32_t manager = read32(gesture.screen + 0xEC), point = logical_point(x, y);
    if (!manager || !point || !void_vm_readable(manager, 4) || !same_screen()) return 0;
    /* The native manager alone owns icon actions; activation zero only probes its hit list. */
    const uint32_t args[] = {point, (uint32_t)activate};
    return (void_call_guest_this(0x00667470u, manager, 2, args) & 0xFFu) != 0;
}

static void touch_cursor_query(void)
{
    if (!touch_mode) {
        uint32_t x, y; uint64_t moved;
        if (void_input_pointer(&x, &y, &moved) && void_vm_writable(0x00FE6DA0u, 8)) {
            MEMF(0x00FE6DA0u) = (float)x; MEMF(0x00FE6DA4u) = (float)y;
        }
        original_cursor(); return;
    }
    g_eax = scratch + 480;
    g_esp += 4;
}

static void touch_cursor_hardware_query(void)
{
    if (cursor_software_owner && g_ecx == cursor_software_owner) {
        g_eax &= ~255u;
        g_esp += 4;
        return;
    }
    original_cursor_hardware_query();
}

static void touch_cursor_software_draw(void)
{
    uint32_t owner = g_ecx, table = read32(owner);
    if (table == 0x00E49494u && void_vm_readable(owner, 0x50) &&
        read32(table + 8) == 0x00836440u && read32(table + 0x24) == 0x00835B90u) {
        if (!original_cursor_hardware_query) {
            original_cursor_hardware_query = void_dispatch_find(0x00835B90u);
            if (original_cursor_hardware_query)
                void_dispatch_add(0x00835B90u, touch_cursor_hardware_query);
        }
        if (original_cursor_hardware_query) {
            uint32_t previous = cursor_software_owner;
            cursor_software_owner = owner;
            original_cursor_draw();
            cursor_software_owner = previous;
            return;
        }
    }
    original_cursor_draw();
}

static void touch_cursor_draw(void)
{
    if (touch_mode && gesture.active && !gesture.cancelled && void_port_touch_cursor() &&
        touch_cursor_x >= 0 && touch_cursor_y >= 0 &&
        (gesture.ui || !gesture.panning || gesture.combat_aim) && void_vm_writable(0x00FE6DA0u, 8)) {
        MEMF(0x00FE6DA0u) = touch_cursor_x; MEMF(0x00FE6DA4u) = touch_cursor_y;
        touch_cursor_software_draw(); return;
    }
    uint32_t x, y; uint64_t moved;
    int physical = void_input_pointer(&x, &y, &moved);
    uint64_t since = moved ? moved : cursor_started_ns;
    if (!touch_mode && void_perf_now_ns() - since < UINT64_C(30000000000)) {
        if (physical && void_vm_writable(0x00FE6DA0u, 8)) {
            MEMF(0x00FE6DA0u) = (float)x; MEMF(0x00FE6DA4u) = (float)y;
        }
        original_cursor_draw(); return;
    }
    g_esp += 8; /* Original ICursor::Draw takes one renderer argument (RET 4). */
}

/* ------------------------------------------------------------- tooltips */
/* A finger is not a hovering mouse: a tap rests on its button for a frame or
 * two, which with an instant tooltip delay showed that button's tooltip, and
 * a screen switched by the tap kept it. Tooltips belong to a held finger
 * (the touch right-click) only, and leave with it. Both bodies are
 * NATIVE_OVERRIDES of tools/build_android.py: direct calls reach them too. */
void sub_008863A0_lifted(void);
void sub_006B92E0_lifted(void);
static uint32_t object_method(uint32_t object, unsigned offset);

/* A tapped initiative bar portrait (combat screen +494, 0x0055DC40) stays selected, hovered as by a
 * resting mouse; a second tap on it shows its card as the right button does (0x00669E60: UI root +70) and
 * holds it without a finger, and each later tap switches card and effects. A touch elsewhere ends it: on
 * another portrait that one is selected, beside an open card the touch only closes the card. */
static struct { uint32_t screen, root, controller, unit; float x, y; int card, mode, retries; uint64_t frame; } atb;
static struct { uint32_t screen, root, row, icon, left, right; uint64_t frame; } choice;

static int tooltip_held(void)
{
    if (atb.card || choice.icon) return 1;   /* selected portraits keep their information visible */
    return gesture.active && gesture.held && !gesture.cancelled;
}

/* CWindowScreen tooltip tracker update: thiscall (elapsed ms, screen, force), RET 0xC.
 * +0 shown tooltip window, +8/+C last point, +10 elapsed, +18 moved. */
void sub_008863A0(void)
{
    uint32_t tracker = g_ecx;
    if (!touch_mode || !void_vm_writable(tracker, 0x20)) { sub_008863A0_lifted(); return; }
    int shown = read32(tracker) != 0;
    if (tooltip_held()) {
        if (!shown) MEM32(tracker + 0x10) = 0x3FFFFFFFu;    /* past any delay: show now */
        sub_008863A0_lifted();
    } else if (shown) {
        /* The finger left this screen's pointer: hide as the original does on a move away. */
        MEMF(tracker + 8) = -1.0f;
        MEMF(tracker + 0xC) = -1.0f;
        MEM8(tracker + 0x18) = 1;
        sub_008863A0_lifted();
    } else {
        MEM32(tracker + 0x10) = 0;
        g_esp += 16;
    }
}

/* Options.Tooltips.HoverTimeout in ms, for screen tooltip controllers and
 * window roots: hover tooltips never start under a touch. */
void sub_006B92E0(void)
{
    if (!touch_mode || tooltip_held()) { sub_006B92E0_lifted(); return; }
    g_eax = 0x7FFFFFFFu;
    g_esp += 4;
}

/* Held modifier keys the original reads through its bindings (screen +0x54 Ctrl, +0x5C Alt): a
 * two-finger tap toggles the adventure map's object highlight (Alt held, 0x00669420); a drag from
 * the active shooter holds Ctrl (0x00669410) for the melee attack Ctrl+click gives. */
static uint32_t alt_screen;
static int ctrl_held;

static void alt_latch(uint32_t screen)
{
    if (!alt_screen == !screen) return;
    void_input_key(0x12, screen != 0);
    alt_screen = screen;
    VLOG("[touch] object highlight %s", screen ? "on" : "off");
}

static void ctrl_latch(int on)
{
    if (!ctrl_held == !on) return;
    void_input_key(0x11, on);
    ctrl_held = on;
}

/* The adventure controller's mode 3 (0x00603370) is a hero on the move; the left-button-down
 * handler 0x00592730 then queues NWorld::CCancelActionCmd through 0x00604D60. */
static int adventure_stop(void)
{
    uint32_t controller = gesture.controller, three = 3;
    if (gesture.kind != SCREEN_ADVENTURE || !controller || !same_screen()) return 0;
    if (!(void_call_guest_this(0x00603370u, controller, 1, &three) & 0xFFu)) return 0;
    void_call_guest_this(0x00604D60u, controller, 0, NULL);
    VLOG("[touch] hero movement stopped");
    return 1;
}

/* The world's right-click info at the finger: the original right-button-down
 * handlers (adventure 0x0058C910, combat 0x0053F010, town 0x00619280) force
 * their screen's CScreenTooltipController update with the cursor point. */
static void world_tooltip(void)
{
    uint32_t screen = gesture.screen;
    unsigned offset = gesture.kind == SCREEN_ADVENTURE ? 0x5EC : gesture.kind == SCREEN_COMBAT ? 0x434 :
                      gesture.kind == SCREEN_TOWN ? 0x388 : 0;
    if (!offset || !same_screen()) return;
    if (gesture.kind == SCREEN_COMBAT && read32(screen + 0x2D4)) return;   /* a window owns combat input */
    uint32_t controller = read32(screen + offset);
    if (!void_vm_readable(controller, 0x48) || object_method(controller, 0x1C) != 0x006B89D0u) return;
    if (void_verbose) {
        /* What 0x006B89D0 sees: the cursor, the UI's claim on it and the picked objects. */
        uint32_t cursor = scratch + 480, ui = read32(controller + 12), picker = read32(controller + 16);
        uint32_t iface = ui ? read32(read32(ui + 4) + 8) + ui + 4 : 0;
        uint32_t over_method = iface ? object_method(iface, 52) : 0;
        uint32_t over = over_method ? void_call_guest_this(over_method, iface, 1, &cursor) & 0xFFu : 0xFFu;
        uint32_t pick_method = picker ? object_method(picker, 0) : 0, out = void_galloc(64);
        if (!out) return;
        void_call_guest_this(0x0054E440u, out, 0, NULL);   /* the empty pick 0x006B89D0 builds */
        uint32_t pick_args[] = {out, cursor};
        if (pick_method) void_call_guest_this(pick_method, picker, 2, pick_args);
        VLOG("[touch] world-info probe cursor=%.1f,%.1f over-ui=%u picker=%08X/%08X list=%u obj=%08X,%08X extra=%08X "
             "current=%08X,%08X last=%u now=%u",
             MEMF(cursor), MEMF(cursor + 4), over, picker, pick_method, (MEM32(out + 4) - MEM32(out)) / 4,
             MEM32(out + 12), MEM32(out + 16), MEM32(out + 40), read32(controller + 36), read32(controller + 64),
             read32(controller + 20), read32(0x00FDD12Cu));
        if (pick_method) void_call_guest_this(0x0054E0F0u, out, 0, NULL);
        void_gfree(out);
    }
    const uint32_t args[] = {1, read32(0x00FDD12Cu)};
    void_call_guest_this(0x006B89D0u, controller, 2, args);
    VLOG("[touch] world-info screen=%08X kind=%d", screen, gesture.kind);
}

/* With Options.Tooltips.RightClickEnabled (0x00F39CA0) the world's right button follows its
 * tooltip with the details card (3.1: adventure 0x0058C910, combat 0x0053F010 and town 0x00619280
 * all end in 0x00669E60: UI root +70 with the point, forced, +6C in 1.6/2.1; 0x00487A80 repicks
 * the source and asks its tooltip provider): asked once the tooltip the held finger raised, over an
 * object, a creature or a combat control such as the initiative bar, is on screen (UI root +8). */
static void world_details_request(int waited);

static void world_details(void)
{
    world_details_request(1);
}

/* waited 0: ask at once, as the right button does, instead of after the tooltip. */
static void world_details_request(int waited)
{
    uint32_t method = object_method(gesture.root, 0x70);
    if ((waited && !read32(gesture.root + 8)) || !same_screen()) return;
    if (gesture.kind == SCREEN_COMBAT && read32(gesture.screen + 0x2D4)) return;   /* a window owns combat input */
    gesture.details = 2;
    uint32_t point = logical_point(gesture.x, gesture.y);
    if (!method || !point || !void_vm_readable(0x00F39CA0u, 1) || !MEM8(0x00F39CA0u)) return;
    const uint32_t args[] = {point, 1};
    void_call_guest_this(method, gesture.root, 2, args);
    gesture.card_mode = 1;
    VLOG("[touch] world-details screen=%08X kind=%d point=%.1f,%.1f shown=%08X", gesture.screen, gesture.kind,
         gesture.x, gesture.y, read32(gesture.root + 8));
}

static uint32_t ui_method(uint32_t screen, unsigned offset)
{
    uint32_t root = virtual_base(read32(screen + 0xA0), 8);
    uint32_t method = read32(read32(root) + offset);
    return root && method && void_dispatch_find(method) ? method : 0;
}

static uint32_t ui_point_call(uint32_t screen, unsigned offset, uint32_t point, uint32_t button)
{
    uint32_t root = virtual_base(read32(screen + 0xA0), 8);
    uint32_t method = ui_method(screen, offset);
    const uint32_t args[] = {point, button};
    return method ? void_call_guest_this(method, root, 2, args) : 0;
}

static uint32_t ui_pick(uint32_t screen, float x, float y)
{
    uint32_t point = logical_point(x, y);
    return point ? ui_point_call(screen, 0x28, point, 1) : 0;
}

static uint32_t object_method(uint32_t object, unsigned offset)
{
    uint32_t method = read32(read32(object) + offset);
    return object && method && void_dispatch_find(method) ? method : 0;
}

static uint32_t object_query(uint32_t object, unsigned offset)
{
    uint32_t method = object_method(object, offset);
    return method ? void_call_guest_this(method, object, 0, NULL) : 0;
}

static uint32_t text_edit_at(uint32_t screen, float x, float y, int *kind)
{
    uint32_t window = ui_pick(screen, x, y);
    for (unsigned depth = 0; window && depth < 16; ++depth) {
        const uint32_t line[] = {window, 0, 0x00F2DAF4u, 0x00F7A234u, 0};
        uint32_t field = void_call_guest(0x00D119FCu, 5, line, 0);
        if (field && void_vm_readable(field, 322) && !MEM8(field + 321)) { *kind = 1; return field; }
        const uint32_t box[] = {window, 0, 0x00F2DAF4u, 0x00F7AE0Cu, 0};
        field = void_call_guest(0x00D119FCu, 5, box, 0);
        if (field && void_vm_readable(field, 272)) { *kind = 2; return field; }
        uint32_t parent = object_query(window, 0xD8);
        if (parent == window) break;
        window = parent;
    }
    return 0;
}

static void text_choose(uint32_t screen, uint32_t provider, float x, float y)
{
    int kind = 0;
    uint32_t field = text_edit_at(screen, x, y, &kind);
    ++text_target.epoch;
    text_target.screen = 0;
    if (!field) { void_touch_text_cancel(); return; }
    uint32_t window = virtual_base(provider, 8);
    const uint32_t cast[] = {window, 0, 0x00F2DAF4u, 0x00F2DA88u, 0};
    if (!window) { void_touch_text_cancel(); return; }
    uint32_t root = void_call_guest(0x00D119FCu, 5, cast, 0);
    VLOG("[ime] choose field=%08X kind=%d provider=%08X interface=%08X root=%08X",
         field, kind, provider, window, root);
    if (!root || !void_vm_readable(root, 64)) { void_touch_text_cancel(); return; }
    text_target.screen = screen; text_target.root = provider;
    text_target.root_window = root; text_target.field = field; text_target.table = read32(field);
    text_target.kind = kind; text_target.pending = 1; text_target.frame = touch_frame;
    void_touch_text_arm();
}

int void_touch_text_focus(uint32_t *field, int *kind, uint32_t *epoch)
{
    *field = 0;
    if (!text_target.screen) return 0;
    uint32_t screen = current_screen();
    if (screen != text_target.screen || read32(screen + 0xA0) != text_target.root ||
        !void_vm_readable(text_target.root_window, 64)) {
        VLOG("[ime] drop changed screen/root for field=%08X", text_target.field);
        text_target.screen = 0;
        return 0;
    }
    uint32_t focused = void_call_guest_this(0x00A4DCB0u, text_target.root_window, 0, NULL);
    if (focused != text_target.field || read32(focused) != text_target.table ||
        !void_vm_readable(focused, text_target.kind == 1 ? 322 : 272)) {
        if (!text_target.pending || touch_frame - text_target.frame > 3) {
            VLOG("[ime] drop focus expected=%08X actual=%08X", text_target.field, focused);
            text_target.screen = 0;
        }
        return 0;
    }
    if (text_target.kind == 1 && MEM8(focused + 321)) { text_target.screen = 0; return 0; }
    if (text_target.pending) VLOG("[ime] focused field=%08X kind=%d epoch=%u", focused, text_target.kind, text_target.epoch);
    text_target.pending = 0;
    *field = focused; *kind = text_target.kind; *epoch = text_target.epoch;
    return 1;
}

void void_touch_text_dispatch(uint32_t field, int kind, int key, uint32_t value)
{
    if (!scratch) scratch = void_galloc(512);
    if (!scratch || !void_vm_writable(scratch + 320, 40)) return;
    uint32_t message = scratch + 320;
    memset((void *)ADDR(message), 0, 40);
    MEM32(message + 36) = value;
    uint32_t callback = kind == 1 ? (key ? 0x00C3EC00u : 0x00C3EF90u)
                                  : (key ? 0x00C89570u : 0x00C89510u);
    void_call_guest_this(callback, field, 1, &message);
}

static int ui_scroll(const void_touch_event *event)
{
    uint32_t window = ui_pick(gesture.screen, gesture.start_x, gesture.start_y);
    for (unsigned depth = 0; window && depth < 64; ++depth) {
        const uint32_t cast[] = {window, 0, 0x00F2DAF4u, 0x00F44B08u, 0};
        uint32_t container = void_call_guest(0x00D119FCu, 5, cast, 0);
        uint32_t scrollbar = read32(container + 0x154);
        uint32_t slider = scrollbar ? scrollbar + 0xF8 : 0;
        uint32_t get = object_method(slider, 0x10), set = object_method(slider, 0xC);
        uint32_t orient = object_method(slider, 0x18);
        uint32_t notify = object_method(container ? container + 0x100 : 0, 0);
        if (container && get && set && orient && notify) {
            uint32_t point = logical_point(event->x - event->dx, event->y - event->dy);
            if (!point) return 1;
            float before_x = MEMF(point), before_y = MEMF(point + 4);
            point = logical_point(event->x, event->y);
            if (!point) return 1;
            float dx = MEMF(point) - before_x, dy = MEMF(point + 4) - before_y;
            int horizontal = (void_call_guest_this(orient, slider, 0, NULL) & 0xFFu) != 0;
            void_call_guest_this(get, slider, 0, NULL);
            float value = (float)fp_pop_impl(g_st, &g_fp_top) - (horizontal ? dx : dy);
            uint32_t bits;
            memcpy(&bits, &value, sizeof bits);
            void_call_guest_this(set, slider, 1, &bits);
            void_call_guest_this(get, slider, 0, NULL);
            value = (float)fp_pop_impl(g_st, &g_fp_top);
            memcpy(&bits, &value, sizeof bits);
            const uint32_t args[] = {bits, scrollbar};
            void_call_guest_this(notify, container + 0x100, 2, args);
            return 1;
        }
        uint32_t parent = object_method(window, 0xD8);
        if (!parent) break;
        uint32_t next = void_call_guest_this(parent, window, 0, NULL);
        if (next == window) break;
        window = next;
    }
    return 0;
}

static void ui_hover(float x, float y)
{
    uint32_t point = logical_point(x, y);
    if (point) ui_point_call(gesture.screen, 0x24, point, 0);
}

static void ui_release(int outside)
{
    if (outside) gesture.combo = 0;
    uint32_t point = logical_point(outside ? -1.0f : gesture.x, outside ? -1.0f : gesture.y);
    if (gesture.pressed && point) ui_point_call(gesture.screen, 0x1C, point, 1);
    gesture.pressed = gesture.held = 0;
    if (same_screen()) ui_hover(-1.0f, -1.0f);
}

/* The book's part under the point: its descriptor (borrowed from the book, never kept), 0 for none. */
static uint32_t book_part(float x, float y)
{
    if (!gesture.book || !same_screen() || spellbook_kind(gesture.screen) != gesture.book) return 0;
    uint32_t picker = gesture.book == 1 ? 0x00683450u : 0x0067BAB0u;
    unsigned vector = gesture.book == 1 ? 0x1B4 : 0x1A8;
    unsigned stride = gesture.book == 1 ? 36 : 40;
    unsigned scene = gesture.book == 1 ? 0x1CC : 0x1C0;
    unsigned closing = gesture.book == 1 ? 0x1ED : 0x1D4;
    if (!void_vm_readable(gesture.screen, closing + 1) || MEM8(gesture.screen + closing) ||
        !void_vm_readable(read32(gesture.screen + scene), 4) ||
        !void_dispatch_find(picker) || !void_dispatch_find(0x00493ED0u)) return 0;
    uint32_t point = logical_point(x, y);
    if (!point) return 0;
    /* The book's icons/tabs are mesh parts, resolved by its own camera and scene. */
    const uint32_t args[] = {point, 0, 0, 1};
    uint32_t descriptor = void_call_guest_this(picker, gesture.screen, 4, args);
    if (!same_screen() || spellbook_kind(gesture.screen) != gesture.book || MEM8(gesture.screen + closing)) return 0;
    uint32_t begin = read32(gesture.screen + vector), end = read32(gesture.screen + vector + 4);
    if (!begin || end < begin || (end - begin) % stride || descriptor < begin ||
        (uint64_t)descriptor + stride > end || (descriptor - begin) % stride ||
        !void_vm_readable(descriptor, stride)) return 0;
    uint32_t text = read32(descriptor + 4), text_end = read32(descriptor + 8);
    if (!text || text_end <= text || text_end - text > 128 || !void_vm_readable(text, text_end - text)) return 0;
    return descriptor;
}

/* A bookmark (school, combat or adventure tab) is a narrow strip of the mesh whose part sends
 * "MB_Button_School" (its hover 0x00683F8E compares the same text): a tap that hits no part takes the
 * nearest bookmark within reach, rings of 8 probes outwards. */
static uint32_t book_bookmark_near(float x, float y)
{
    int width, height;
    void_input_screen_size(&width, &height);
    float reach = 0.07f * (float)(width < height ? width : height);
    for (int ring = 1; ring <= 3 && same_screen(); ++ring)
        for (int i = 0; i < 8; ++i) {
            float radius = reach * (float)ring / 3.0f, angle = (float)i * 0.78539816f;
            uint32_t descriptor = book_part(x + radius * cosf(angle), y + radius * sinf(angle));
            uint32_t text = descriptor ? read32(descriptor + 4) : 0;
            if (text && read32(descriptor + 8) - text == 16 && !memcmp((const void *)ADDR(text), "MB_Button_School", 16)) return descriptor;
        }
    return 0;
}

/* A swipe across the book turns its page, left for the next one, and up or down steps its bookmark, as the
 * keys of its input section do (CSpellBook input_next_page / input_previous_page 0x00686020 / 0x00686080,
 * input_bookmark_up / input_bookmark_down 0x006860C0 / 0x006860E0; the orcish book's pages 0x0067E2E0 /
 * 0x0067E320 and its input_tab 0x0067E2A0). Thiscall message handlers, RET 4; they read no message. */
static int book_swipe(float x, float y)
{
    int width, height;
    void_input_screen_size(&width, &height);
    float dx = x - gesture.start_x, dy = y - gesture.start_y, reach = 0.08f * (float)(width < height ? width : height);
    int across = fabsf(dx) >= reach && fabsf(dx) >= 1.5f * fabsf(dy), along = fabsf(dy) >= reach && fabsf(dy) >= 1.5f * fabsf(dx);
    unsigned closing = gesture.book == 1 ? 0x1ED : 0x1D4;
    if ((!across && !along) || !same_screen() || spellbook_kind(gesture.screen) != gesture.book ||
        ui_pick(gesture.screen, gesture.start_x, gesture.start_y) || !same_screen() ||
        !void_vm_readable(gesture.screen, closing + 1) || MEM8(gesture.screen + closing)) return 0;
    uint32_t action = gesture.book == 1 ? (across ? (dx < 0 ? 0x00686020u : 0x00686080u) : (dy < 0 ? 0x006860C0u : 0x006860E0u))
                                        : (across ? (dx < 0 ? 0x0067E2E0u : 0x0067E320u) : 0x0067E2A0u), unused = 0;
    if (!void_dispatch_find(action)) return 0;
    void_call_guest_this(action, gesture.screen, 1, &unused);
    VLOG("[touch] book-swipe screen=%08X book=%d %s", gesture.screen, gesture.book,
         across ? (dx < 0 ? "next page" : "previous page") : dy < 0 ? "bookmark up" : "bookmark down");
    return 1;
}

static void spellbook_activate(float x, float y)
{
    uint32_t descriptor = book_part(x, y);
    if (!descriptor && same_screen()) descriptor = book_bookmark_near(x, y);
    if (!descriptor || !same_screen()) return;
    uint32_t argument = read32(descriptor + 0x10), zero = 0;
    VLOG("[touch] book-action screen=%08X book=%d part=%u argument=%u", gesture.screen,
         gesture.book, read32(descriptor), argument);
    /* Original 683720/67BD80: borrowed descriptor, fastcall action, RET 4. */
    g_edx = argument;
    void_call_guest_this(0x00493ED0u, descriptor + 4, 1, &zero);
}

static int ui_idle(void)
{
    uint32_t head = read32(gesture.screen + 0x14C);
    return head && read32(head) == head;
}

static int window_contains(uint32_t hit, uint32_t window)
{
    for (unsigned depth = 0; hit && depth < 32; ++depth) {
        if (!same_screen()) return 0;
        if (hit == window) return 1;
        uint32_t parent = object_query(hit, 0xD8);
        if (parent == hit) break;
        hit = parent;
    }
    return 0;
}

static int dnd_identity(uint32_t helper)
{
    return helper && same_screen() && read32(gesture.screen + 0x150) == helper &&
           void_vm_readable(helper, 36) && read32(helper) == 0x00E47794u;
}

static int dnd_held(uint32_t helper)
{
    return read32(read32(helper + 0xC)) == 0x00E4775Cu;
}

static void dnd_track(uint32_t helper)
{
    if (dnd_identity(helper) && dnd_held(helper)) {
        drag_owner.screen = gesture.screen; drag_owner.root = gesture.root;
        drag_owner.helper = helper; drag_owner.invalid = 0;
    } else if (drag_owner.helper == helper) memset(&drag_owner, 0, sizeof drag_owner);
}

static void dnd_cancel(void)
{
    uint32_t helper = gesture.dnd;
    if (dnd_identity(helper) && object_method(helper, 0x34)) object_query(helper, 0x34);
    if (drag_owner.helper == helper) memset(&drag_owner, 0, sizeof drag_owner);
    gesture.dnd_pressed = 0;
}

/* The window a drop or pickup at the point would take. A held pickup asks its own slot map, as the
 * native drop 0x00812980 does, with no visibility test: an empty army cell keeps its creature icon
 * hidden (army screens 0x0064AC90), so the visible-slot probe misses it. Otherwise the first slot whose
 * window is visible there (0x00813DE0, geometry/visibility probe, never the pickup probe). */
static uint32_t dnd_target_at(uint32_t helper, float x, float y)
{
    uint32_t point = logical_point(x, y), map = 0;
    if (!point) return 0;
    uint32_t held = dnd_held(helper) ? read32(helper + 0x1C) : 0;
    if (held && void_vm_readable(held, 0x14)) map = read32(held + 0x10);
    else {
        const uint32_t args[] = {point, 1};
        uint32_t slot = void_call_guest_this(0x00813DE0u, helper, 2, args);
        map = slot ? read32(slot + 0x10) : 0;
    }
    uint32_t method = object_method(map, 0x24);
    point = logical_point(x, y);
    return method && point ? void_call_guest_this(method, map, 1, &point) : 0;
}

/* The picked top window owns the point for that target: the target or its contents, or (a hidden or
 * backgroundless cell, transparent to the picker) a container of the target. A modal or another panel
 * above it is neither. */
static int dnd_owns(uint32_t hit, uint32_t window)
{
    return window_contains(hit, window) || (hit && window_contains(window, hit));
}

static int dnd_claim_at(uint32_t helper, float x, float y)
{
    if (!dnd_identity(helper) || !ui_idle() || !void_dispatch_find(0x00813DE0u)) return 0;
    uint32_t window = dnd_target_at(helper, x, y);
    if (!dnd_identity(helper) || !ui_idle()) return 0;
    uint32_t hit = ui_pick(gesture.screen, x, y);
    int claim = window ? dnd_identity(helper) && ui_idle() && dnd_owns(hit, window) : dnd_held(helper) && !hit;
    VLOG("[touch] dnd-target point=%.1f,%.1f window=%08X hit=%08X held=%d claim=%d", x, y, window, hit,
         dnd_identity(helper) && dnd_held(helper), claim);
    return claim;
}

static void dnd_point(unsigned offset, float x, float y)
{
    uint32_t helper = gesture.dnd;
    if (!dnd_identity(helper) || !ui_idle()) { dnd_cancel(); return; }
    uint32_t point = logical_point(x, y), method = object_method(helper, offset);
    if (point && method) void_call_guest_this(method, helper, 1, &point);
    dnd_track(helper);
}

static void dnd_owner_pump(int abort)
{
    if (!drag_owner.helper) return;
    uint32_t screen = current_screen();
    if (screen != drag_owner.screen || read32(screen + 0xA0) != drag_owner.root) {
        drag_owner.invalid = 1;
        if (!gesture.active || gesture.screen == drag_owner.screen) publish_point(-1, -1);
        return; /* The native screen owns destruction; never call through a stale owner. */
    }
    uint32_t helper = drag_owner.helper;
    if (read32(screen + 0x150) != helper || read32(helper) != 0x00E47794u) {
        memset(&drag_owner, 0, sizeof drag_owner);
    } else if (abort || drag_owner.invalid) {
        uint32_t method = object_method(helper, 0x34);
        if (method) void_call_guest_this(method, helper, 0, NULL);
        memset(&drag_owner, 0, sizeof drag_owner);
        publish_point(-1, -1);
    } else if (!dnd_held(helper)) memset(&drag_owner, 0, sizeof drag_owner);
}

static int town_army_ready(void)
{
    uint32_t screen = gesture.screen;
    if (read32(screen) != 0x00E2A64Cu || !same_screen() || !ui_idle() ||
        !void_vm_readable(screen, 0x479) ||
        MEM8(screen + 0x29C) || MEM8(screen + 0x478)) return 0;
    if ((void_call_guest_this(0x00614200u, screen, 0, NULL) & 0xFFu) || !same_screen() ||
        (void_call_guest_this(0x006146C0u, screen, 0, NULL) & 0xFFu) || !same_screen()) return 0;
    return ui_idle();
}

static int town_ready(void)
{
    return read32(gesture.screen + 0x294) && town_army_ready();
}

static void town_activate(float x, float y)
{
    uint32_t screen = gesture.screen;
    if (!town_ready()) return;
    uint32_t transition = read32(screen + 0x3DC);
    if (!object_method(transition, 0x48) || (object_query(transition, 0x48) & 0xFFu) || !same_screen()) return;
    uint32_t point = logical_point(x, y);
    if (point) {
        /* Original city handler's native building pick, permissions and action dispatch. */
        void_call_guest_this(0x0061B760u, screen, 1, &point);
        VLOG("[touch] town-building screen=%08X", screen);
    }
}

/* Endpoint discovery stays in the UI; the original controller owns validation/orders. */
typedef struct { uint32_t window,army,owner,row,command,world,policy; unsigned index,stride; } troop_cell;

/* Two-army screens built on NUI::CTransformCreatureScreenBase (common move/split handler 0x00649E70):
 * caravan meeting, raising the dead, creatures joining a full army, adventure garrison and creature
 * exchange. Sacrifice, transformation, training, upgrade and slave market keep native moves. Field
 * offsets and vtable slots of Tribes of the East; the legacy contracts patch this block (1.6: -8 and
 * slots -4, 2.1: -0xC and slots -8). */
#define ARMY_HANDLER_SLOT 0x78u   /* the common move/split handler */
#define ARMY_FACTORY_SLOT 0x6Cu   /* the screen's own split controller factory, 0 for the common one */
#define ARMY_OWNERS 0x194u        /* the two armies' owners */
#define ARMY_COMMAND 0x1A4u       /* command processor; the world follows it */
#define ARMY_ROWS 0x1B0u          /* bucket vector of the row hash map (begin, end) */
#define ARMY_UPDATE 0x1C4u        /* update helper; its dirty byte is +3C */

static int army_screen(uint32_t screen)
{
    uint32_t vtable=read32(screen);
    return (vtable==0x00E42BD4u || vtable==0x00E42A1Cu || vtable==0x00E349F4u || vtable==0x00E35BF4u ||
            vtable==0x00E40CE4u) && void_vm_readable(screen,0x1F0) && read32(vtable+ARMY_HANDLER_SLOT)==0x00649E70u;
}

/* Row record of such a screen (hash map keys 0/1, as the drop client 0x0064B770 reads them): +0 owner,
 * +4 army, +8 portrait window ("heroicon%d"), +C/+10 cells of 48 bytes (+0 creature icon, the drag window). */
static uint32_t army_row(uint32_t screen, unsigned key)
{
    uint32_t begin=read32(screen+ARMY_ROWS),end=read32(screen+ARMY_ROWS+4);
    if (!begin || end<=begin || (end-begin)%4 || (end-begin)/4>4096 || !void_vm_readable(begin,end-begin)) return 0;
    uint32_t node=read32(begin+4*(key%((end-begin)/4)));
    for (unsigned depth=0;node && depth<64;++depth) {
        if (!void_vm_readable(node,0x20)) return 0;
        if (read32(node+4)==key) return node+8;
        node=read32(node);
    }
    return 0;
}

/* After an order or a split dialog the original handler marks the screen's update helper. */
static void army_screen_dirty(void)
{
    uint32_t helper=read32(gesture.screen+ARMY_UPDATE);
    if (same_screen() && army_screen(gesture.screen) && void_vm_writable(helper+0x3C,1)) MEM8(helper+0x3C)=1;
}

/* troop_cell_window for a two-army screen: -1 when the screen is none. */
static int army_cell_window(uint32_t screen, uint32_t window, troop_cell *cell)
{
    if (!army_screen(screen)) return -1;
    for (unsigned row=0;row<2;++row) {
        uint32_t record=army_row(screen,row),cells=read32(record+0xC),end=read32(record+0x10);
        if (!record || !cells || end<cells || end-cells>7*48 || (end-cells)%48 || !void_vm_readable(cells,end-cells)) continue;
        for (unsigned index=0;index<(end-cells)/48;++index) {
            if (read32(cells+48*index)!=window) continue;
            uint32_t army=read32(record+4);
            if (!army || !object_method(army,8) || !same_screen() || !ui_idle()) return 0;
            cell->window=window;cell->army=army;cell->owner=read32(record);cell->row=cells;cell->index=index;cell->stride=48;
            cell->command=read32(screen+ARMY_COMMAND);cell->world=read32(screen+ARMY_COMMAND+4);
            return cell->command && cell->world;
        }
    }
    return 0;
}

/* troop_portrait_at for a two-army screen (each row's portrait stands for its army): -1 when none. */
static int army_portrait_at(uint32_t screen, float x, float y, troop_cell *cell)
{
    if (!army_screen(screen)) return -1;
    if (!same_screen() || !ui_idle()) return 0;
    uint32_t hit=ui_pick(screen,x,y);
    for (unsigned row=0;row<2;++row) {
        uint32_t record=army_row(screen,row),portrait=read32(record+8);
        if (record && portrait && window_contains(hit,portrait) &&
            army_cell_window(screen,read32(read32(record+0xC)),cell)==1) return 1;
    }
    return 0;
}

/* As the screen's move/split handler: the other army's owner is whichever of the two the source is not
 * (same object compared through its CObjectBase part, 0x00433CF0); the screen's own controller first
 * (raising the dead: CRiseDeadDragStackController with its energy; a blocked garrison stack: a refusing
 * one), else CCommonDragStackController with the command processor and the world. */
static uint32_t army_controller(const troop_cell *source, const troop_cell *target)
{
    uint32_t first=read32(gesture.screen+ARMY_OWNERS),second=read32(gesture.screen+ARMY_OWNERS+4),owner=source->owner;
    if (virtual_base(source->army,4)!=virtual_base(target->army,4)) {
        uint32_t mine=virtual_base(source->owner,4);
        owner=(second?mine==virtual_base(second,4):!mine)?first:second;
    }
    const uint32_t args[]={source->army,source->index,source->owner,target->army,target->index,owner};
    uint32_t make=object_method(gesture.screen,ARMY_FACTORY_SLOT),controller=make?void_call_guest_this(make,gesture.screen,6,args):0;
    if (controller || !same_screen() || !void_dispatch_find(0x00786E20u)) return same_screen()?controller:0;
    g_edx=source->world;
    return void_call_guest_this(0x00786E20u,source->command,6,args);
}

static int troop_cell_window(uint32_t window, troop_cell *cell)
{
    uint32_t screen=gesture.screen;
    if (!window || !same_screen() || !ui_idle()) return 0;
    memset(cell,0,sizeof *cell);
    int exchange=army_cell_window(screen,window,cell);
    if (exchange>=0) return exchange;
    if (read32(screen)==0x00E3584Cu && void_vm_readable(screen,0x75C)) {
        uint32_t config=screen+(MEM8(screen+0x4B8)?0x338:0x1B8);
        if (read32(config+4)!=1) return 0;
        if (read32(screen+0x1B4) && (!void_dispatch_find(0x006C1B90u) ||
            !(void_call_guest_this(0x006C1B90u,screen,0,NULL)&0xFFu) || !same_screen())) return 0;
        for (unsigned row=0;row<2;++row) {
            if (row && !MEM8(config)) continue;
            uint32_t vector=screen+(row?0x654:0x53C),cells=read32(vector),end=read32(vector+4);
            if (!cells || end-cells!=7*12 || !void_vm_readable(cells,7*12)) continue;
            for (unsigned index=0;index<7;++index) {
                if (virtual_base(read32(cells+12*index),8)!=window) continue;
                uint32_t owner=read32(screen+(row?0x1B4:0x1B0)),army=object_query(owner,0x48);
                if (!army || !object_method(army,8) || !same_screen() || !ui_idle()) return 0;
                cell->window=window;cell->army=army;cell->owner=owner;cell->row=cells;cell->index=index;cell->stride=12;
                cell->command=read32(screen+0x1A8);cell->world=read32(screen+0x1A4);cell->policy=read32(screen+0x758);
                return cell->command && cell->world;
            }
        }
        return 0;
    }
    if (read32(screen)!=0x00E2A64Cu || !town_army_ready()) return 0;
    for (unsigned row=0;row<2;++row) {
        uint32_t cells=read32(screen+(row?0x2B4:0x2A8));
        if (!cells || !void_vm_readable(cells,28)) continue;
        for (unsigned index=0;index<7;++index) {
            if (read32(cells+4*index)!=window) continue;
            uint32_t side=row,view=object_query(read32(screen+0x220),0x90);
            uint32_t method=object_method(view,0),army_side=row?1:2;
            uint32_t owner=method?void_call_guest_this(method,view,1,&side):0;
            uint32_t army=void_call_guest_this(0x00614160u,screen,1,&army_side);
            if (!army || !object_method(army,8) || !same_screen() || !ui_idle()) return 0;
            cell->window=window;cell->army=army;cell->owner=owner;
            cell->row=cells;cell->index=index;cell->stride=4;
            cell->command=read32(screen+0x224);cell->world=read32(screen+0x21C);
            return cell->command && cell->world;
        }
    }
    return 0;
}

static uint32_t troop_row_window(const troop_cell *cell,unsigned index)
{
    uint32_t window=read32(cell->row+cell->stride*index);
    return cell->stride==12?virtual_base(window,8):window;
}

static int troop_cell_at(float x,float y,troop_cell *cell)
{
    uint32_t helper=gesture.dnd;
    if (!dnd_identity(helper) || !ui_idle()) return 0;
    /* A held stack's empty target cell is found as its drop finds it; a modal still refuses. */
    uint32_t window=dnd_target_at(helper,x,y);
    if (!window || !dnd_identity(helper) || !dnd_owns(ui_pick(gesture.screen,x,y),window)) return 0;
    return troop_cell_window(window,cell);
}

static int troop_stack(const troop_cell *cell,uint32_t *stack)
{
    uint32_t vector=object_query(cell->army,8),begin=read32(vector),end=read32(vector+4);
    if (!begin || end<begin || (end-begin)%4 || cell->index>=(end-begin)/4 ||
        !void_vm_readable(begin+4*cell->index,4)) return 0;
    *stack=read32(begin+4*cell->index);
    return !*stack || void_vm_readable(*stack,0x24);
}

static void troop_inactive(uint32_t window)
{
    if (!same_screen() || !ui_idle()) return;
    uint32_t constants=void_call_guest_this(0x00490DB0u,0x0103FF38u,0,NULL);
    uint32_t sound=object_query(window,0xDC),play=object_method(sound,0x28);
    const uint32_t cast[]={window,0,0x00F2DAF4u,0x00F2DA88u,0};
    uint32_t owner=constants&&play?void_call_guest(0x00D119FCu,5,cast,0):0;
    if (owner && void_vm_readable(constants+0x7C,4) && same_screen()) {
        const uint32_t args[]={constants+0x7C,owner};
        void_call_guest_this(play,sound,2,args);
    }
}

static uint32_t troop_controller(const troop_cell *source,const troop_cell *target)
{
    if (!same_screen() || source->command!=target->command || source->world!=target->world || source->policy!=target->policy) return 0;
    if (army_screen(gesture.screen)) return army_controller(source,target);
    if (read32(gesture.screen)==0x00E3584Cu) {
        if (!void_dispatch_find(0x006BD740u)) return 0;
        const uint32_t args[]={source->command,source->world,source->army,source->index,source->owner,
                               target->army,target->index,target->owner,source->policy};
        memcpy((void *)ADDR(scratch+320),args,sizeof args);
        return void_call_guest_this(0x006BD740u,scratch+320,0,NULL);
    }
    if (!void_dispatch_find(0x00786E20u)) return 0;
    const uint32_t args[]={source->army,source->index,source->owner,target->army,target->index,target->owner};
    g_edx=source->world;
    return void_call_guest_this(0x00786E20u,source->command,6,args);
}

static int troop_portrait_at(float x,float y,troop_cell *cell)
{
    uint32_t screen=gesture.screen;int hero=read32(screen)==0x00E3584Cu;
    int exchange=army_portrait_at(screen,x,y,cell);
    if (exchange>=0) return exchange;
    if (!hero && (gesture.kind!=SCREEN_TOWN || !town_army_ready())) return 0;
    uint32_t hit=ui_pick(gesture.screen,x,y);
    for (unsigned row=0;row<2;++row) {
        uint32_t portrait=read32(screen+(hero?(row?0x600:0x4E8):(row?0x2A4:0x2A0)));
        uint32_t cells=read32(screen+(hero?(row?0x654:0x53C):(row?0x2B4:0x2A8)));
        uint32_t window=hero?virtual_base(read32(cells),8):read32(cells);
        if (portrait && window_contains(hit,portrait) && troop_cell_window(window,cell)) return 1;
    }
    return 0;
}

static int troop_count(const troop_cell *cell,uint32_t *count,uint32_t *type)
{
    uint32_t stack;
    if (!troop_stack(cell,&stack)) return 0;
    *count=stack?read32(stack+0x20):0;*type=stack?read32(stack+0x1C):0;
    return *count<=0x7FFFFFFFu;
}

/* Orders are asynchronous, including local play. One batch waits for each native result. */
enum { ARMY_TRANSFER=1, ARMY_COLLECT, ARMY_BALANCE };
static struct {
    int mode,waiting;
    troop_cell source,target,from,to;
    uint32_t type,quota[7],before_from,before_to,after_from,after_to,waiting_type;
    unsigned next,limit;
    uint64_t deadline;
} army_batch;

static int troop_current(troop_cell *cell)
{
    troop_cell current;
    if (!troop_cell_window(cell->window,&current) || current.army!=cell->army || current.owner!=cell->owner ||
        current.row!=cell->row || current.command!=cell->command || current.world!=cell->world || current.policy!=cell->policy) return 0;
    *cell=current;return 1;
}

static int troop_order(troop_cell *source,troop_cell *target,uint32_t destination,int all)
{
    uint32_t source_count,target_count,source_type,target_type;
    if (!troop_current(source) || !troop_current(target) || source->window==target->window ||
        !troop_count(source,&source_count,&source_type) || !source_count ||
        !troop_count(target,&target_count,&target_type) || (target_count && target_type!=source_type) ||
        (uint64_t)source_count+target_count>0x7FFFFFFFu) return 0;
    uint32_t controller=troop_controller(source,target);
    if (!controller) return 0;
    uint32_t pin=scratch+400;MEM32(pin)=0;
    void_call_guest_this(0x0055AF30u,pin,1,&controller);
    int sent=0;
    if (same_screen() && object_method(controller,0x18) && (object_query(controller,0xC)&0xFFu)) {
        uint32_t minimum=object_query(controller,0x18),target_minimum=object_query(controller,0x1C),total=source_count+target_count;
        if (all && minimum<=total) destination=total-minimum;
        uint32_t validate=object_method(controller,0x10),commit=object_method(controller,0x14);
        uint32_t fresh_source,fresh_target,fresh_type;
        if (destination!=target_count && destination<=total && total-destination>=minimum && destination>=target_minimum && validate && commit &&
            (void_call_guest_this(validate,controller,1,&destination)&0xFFu) &&
            troop_current(source) && troop_current(target) &&
            troop_count(source,&fresh_source,&fresh_type) && fresh_source==source_count && fresh_type==source_type &&
            troop_count(target,&fresh_target,&fresh_type) && fresh_target==target_count && (!target_count || fresh_type==target_type)) {
            army_batch.from=*source;army_batch.to=*target;
            army_batch.before_from=source_count;army_batch.before_to=target_count;
            army_batch.after_from=total-destination;army_batch.after_to=destination;
            army_batch.waiting_type=source_type;
            army_batch.waiting=1;army_batch.deadline=void_perf_now_ns()+5000000000ull;
            void_call_guest_this(commit,controller,1,&destination);sent=1;
            army_screen_dirty();
            VLOG("[touch] army-order from=%08X:%u to=%08X:%u count=%u",source->army,source->index,target->army,target->index,destination);
        }
    }
    void_call_guest_this(0x0059F6B0u,pin,0,NULL);MEM32(pin)=0;
    return sent;
}

static void army_pump(void)
{
    if (!army_batch.mode) return;
    if (!same_screen() || !troop_current(&army_batch.source) || !troop_current(&army_batch.target)) goto stop;
    if (army_batch.waiting) {
        uint32_t from,to,from_type,to_type;
        if (!troop_current(&army_batch.from) || !troop_current(&army_batch.to) ||
            !troop_count(&army_batch.from,&from,&from_type) || !troop_count(&army_batch.to,&to,&to_type) ||
            (from && from_type!=army_batch.waiting_type) || (to && to_type!=army_batch.waiting_type)) goto stop;
        if (from!=army_batch.after_from || to!=army_batch.after_to) {
            if (from!=army_batch.before_from || to!=army_batch.before_to || void_perf_now_ns()>=army_batch.deadline) goto stop;
            return;
        }
        army_batch.waiting=0;
    }
    troop_cell source=army_batch.source,target=army_batch.target;
    if (army_batch.mode==ARMY_BALANCE) {
        uint32_t counts[7],type;int surplus=-1,deficit=-1;
        for (unsigned i=0;i<7;++i) {
            if (army_batch.quota[i]==UINT32_MAX) continue;
            troop_cell cell;
            if (!troop_cell_window(troop_row_window(&source,i),&cell) || !troop_count(&cell,&counts[i],&type) ||
                (counts[i] && type!=army_batch.type)) goto stop;
            if (counts[i]>army_batch.quota[i]) surplus=(int)i;
            if (counts[i]<army_batch.quota[i]) deficit=(int)i;
        }
        if (surplus<0 || deficit<0) goto stop;
        if (!troop_cell_window(troop_row_window(&source,(unsigned)surplus),&source) ||
            !troop_cell_window(troop_row_window(&target,(unsigned)deficit),&target)) goto stop;
        uint32_t move=counts[surplus]-army_batch.quota[surplus],need=army_batch.quota[deficit]-counts[deficit];
        if (troop_order(&source,&target,counts[deficit]+(move<need?move:need),0)) return;
        goto stop;
    }
    while (army_batch.next<army_batch.limit) {
        unsigned index=army_batch.next++;uint32_t count,type;
        if (!troop_cell_window(troop_row_window(&source,index),&source) || !troop_count(&source,&count,&type)) goto stop;
        if (!count) continue;
        if (army_batch.mode==ARMY_COLLECT) {
            if (source.window==target.window || type!=army_batch.type) continue;
        } else {
            troop_cell empty={0};int found=0;
            for (unsigned i=0;i<7;++i) {
                uint32_t other_count,other_type;
                if (!troop_cell_window(troop_row_window(&army_batch.target,i),&target) || !troop_count(&target,&other_count,&other_type)) goto stop;
                if (!other_count && !empty.window) empty=target;
                if (other_count && other_type==type) { found=1;break; }
            }
            if (!found) { if (!empty.window) continue;target=empty; }
        }
        if (troop_order(&source,&target,0,1)) return;
        if (!same_screen()) goto stop;
    }
stop:
    memset(&army_batch,0,sizeof army_batch);
}

static void army_start(int mode,const troop_cell *source,const troop_cell *target,int one)
{
    memset(&army_batch,0,sizeof army_batch);
    army_batch.mode=mode;army_batch.source=*source;army_batch.target=*target;army_batch.limit=7;
    uint32_t held=dnd_identity(gesture.dnd)?read32(gesture.dnd+0x1C):0;
    dnd_cancel();gesture.cancelled=gesture.committed=1;
    /* Cancel retains the pickup source; clear it before army redraw, or the next pickup reveals its stale icon. */
    if (held && dnd_identity(gesture.dnd) && !dnd_held(gesture.dnd) &&
        read32(gesture.dnd+0x1C)==held && void_dispatch_find(0x00812880u))
        void_call_guest_this(0x00812880u,held,0,NULL);
    uint32_t count;
    if (!troop_count(source,&count,&army_batch.type)) { army_batch.mode=0;return; }
    if (mode==ARMY_BALANCE) {
        if (count<=1) { army_batch.mode=0;return; }
        uint64_t total=0;unsigned slots=0;
        for (unsigned i=0;i<7;++i) {
            troop_cell cell;uint32_t type;
            if (!troop_cell_window(troop_row_window(source,i),&cell) || !troop_count(&cell,&count,&type)) { army_batch.mode=0;return; }
            army_batch.quota[i]=UINT32_MAX;
            if (!count || (type==army_batch.type && (count>1 || i==source->index))) {
                army_batch.quota[i]=0;total+=count;++slots;
            }
        }
        if (!slots || total>0x7FFFFFFFu) { army_batch.mode=0;return; }
        unsigned remainder=(unsigned)(total%slots);
        for (unsigned i=0;i<7;++i) if (army_batch.quota[i]!=UINT32_MAX) {
            army_batch.quota[i]=(uint32_t)(total/slots);
            if (remainder) { ++army_batch.quota[i];--remainder; }
        }
    }
    if (one) { army_batch.next=source->index;army_batch.limit=source->index+1; }
    army_pump();
}

static int troop_drop(float x,float y)
{
    troop_cell source,target;uint32_t stack;
    if (gesture.army_portrait && gesture.held && gesture.panning &&
        troop_portrait_at(gesture.start_x,gesture.start_y,&source) && troop_portrait_at(x,y,&target) && source.row!=target.row) {
        army_start(ARMY_TRANSFER,&source,&target,0);return 1;
    }
    if (!gesture.dnd_pressed || !dnd_identity(gesture.dnd) || !dnd_held(gesture.dnd) ||
        !troop_cell_window(read32(read32(gesture.dnd+0x1C)+0xC),&source) || !troop_stack(&source,&stack) || !stack) return 0;
    if (troop_portrait_at(x,y,&target)) {
        if (source.row!=target.row) army_start(ARMY_TRANSFER,&source,&target,1);
        else army_start(gesture.held?ARMY_BALANCE:ARMY_COLLECT,&source,&source,0);
        return 1;
    }
    return 0;
}

static struct { troop_cell source; uint32_t helper,held,count,type; } troop_preview;

static void troop_preview_pump(void)
{
    if (!troop_preview.helper) return;
    uint32_t helper=troop_preview.helper,held=troop_preview.held,count,type;
    if (!gesture.active || !dnd_identity(helper) || !dnd_held(helper) || read32(helper+0x1C)!=held ||
        !troop_current(&troop_preview.source) || !troop_count(&troop_preview.source,&count,&type) ||
        !count || type!=troop_preview.type) { troop_preview.helper=0;return; }
    if (count==troop_preview.count) return;
    troop_preview.helper=0;
    uint32_t map=read32(held+0x10),handler=read32(held+8),visual=read32(held+0x20);
    uint32_t query=object_method(map,0x28),paint=object_method(handler,0),window=object_query(visual,0x28);
    if (!query || !paint || !window) return;
    uint32_t source=troop_preview.source.window;
    uint32_t data=void_call_guest_this(query,map,1,&source);
    if (!dnd_identity(helper) || !dnd_held(helper) || read32(helper+0x1C)!=held) return;
    /* Native 8128D0 paints the floating window through this same pickup callback. */
    const uint32_t args[]={source,data,window};
    void_call_guest_this(paint,handler,3,args);
}

static void troop_split(float second_x,float second_y,int dialog)
{
    troop_cell source,primary,target;
    uint32_t helper=gesture.dnd,held=read32(helper+0x1C),stack;
    if (!gesture.second_troop || !dnd_identity(helper) || !dnd_held(helper) ||
        !troop_cell_window(read32(held+0xC),&source) || !troop_stack(&source,&stack) || !stack ||
        !troop_cell_at(gesture.x,gesture.y,&primary) || !troop_cell_at(second_x,second_y,&target)) return;
    if (!dialog) {
        /* The held troop stays over its source; the other finger may use a separate army cell. */
        if (primary.window!=source.window) return;
        int found=0;
        for (unsigned index=0;index<7;++index) {
            uint32_t window=troop_row_window(&primary,index);
            if (window==source.window || !troop_cell_window(window,&target) || !troop_stack(&target,&stack) || stack) continue;
            found=1;break;
        }
        if (!found) {
            VLOG("[touch] troop-full screen=%08X row=%08X",gesture.screen,primary.row);
            troop_inactive(primary.window);return;
        }
    } else {
        if (target.window==source.window || !troop_stack(&target,&stack)) return;
        if (stack) {
            uint32_t source_count,target_count,source_type,target_type;
            if (!troop_count(&source,&source_count,&source_type) || !source_count || !troop_count(&target,&target_count,&target_type) || !target_count ||
                source_type!=target_type || (uint64_t)source_count+target_count>0x7FFFFFFFu) return;
            dnd_cancel();gesture.cancelled=gesture.committed=1;gesture.second_troop=0;
            if (!troop_order(&source,&target,(source_count+target_count)/2,0)) troop_inactive(source.window);
            return;
        }
    }
    uint32_t controller=troop_controller(&source,&target);
    if (!controller) return;
    uint32_t pin=scratch+400;MEM32(pin)=0;
    void_call_guest_this(0x0055AF30u,pin,1,&controller);
    if (same_screen() && dnd_identity(helper) && dnd_held(helper) && (object_query(controller,0xC)&0xFFu)) {
        if (dialog) {
            uint32_t modal=void_call_guest_this(0x00587CF0u,controller,0,NULL);
            if (modal && same_screen()) {
                dnd_cancel();gesture.committed=gesture.cancelled=1;gesture.second_troop=0;
                if (same_screen()) {
                    VLOG("[touch] troop-dialog screen=%08X from=%08X:%u to=%08X:%u",
                         gesture.screen,source.army,source.index,target.army,target.index);
                    void_call_guest_this(0x0066D290u,gesture.screen,1,&modal);
                    army_screen_dirty();
                }
            }
        } else {
            uint32_t one=1,validate=object_method(controller,0x10),commit=object_method(controller,0x14);
            uint32_t count,type;
            int limits=troop_count(&source,&count,&type) && count>1 &&
                       object_query(controller,0x18)<=count-1 && object_query(controller,0x1C)<=1;
            if (limits && validate && commit && (void_call_guest_this(validate,controller,1,&one)&0xFFu) &&
                same_screen() && dnd_identity(helper) && dnd_held(helper)) {
                troop_preview.source=source;troop_preview.helper=helper;troop_preview.held=held;
                troop_preview.count=count;troop_preview.type=type;
                void_call_guest_this(commit,controller,1,&one);dnd_track(helper);
                army_screen_dirty();
                VLOG("[touch] troop-one screen=%08X from=%08X:%u to=%08X:%u",
                     gesture.screen,source.army,source.index,target.army,target.index);
            } else troop_inactive(primary.window);
        }
    } else if (!dialog) troop_inactive(primary.window);
    void_call_guest_this(0x0059F6B0u,pin,0,NULL);MEM32(pin)=0;
}

static int window_hit(uint32_t window, uint32_t point);

static int tooltip_target_at(float x, float y)
{
    if (!same_screen()) return 0;
    uint32_t shown=read32(gesture.root+8),point=logical_point(x,y);
    /* Tooltips are transparent to the normal UI picker. Test the displayed
       window's native bounds before falling back to interactive UI. */
    if (shown && point && window_hit(shown,point))
        return same_screen() && read32(gesture.root+8)==shown;
    return same_screen() && ui_pick(gesture.screen,x,y) && same_screen();
}

/* A held combat control (initiative bar portrait, stack info) takes the second finger anywhere. */
static int combat_ui_hold(void)
{
    return gesture.ui && gesture.kind == SCREEN_COMBAT && gesture.held && !gesture.dnd && !gesture.combo &&
           !gesture.placement;
}

static uint32_t window_placement(uint32_t window);

/* What the card shows (verbose): UI root +8 and its placement's name (+58/+5C). */
static void card_trace(uint32_t root, int mode)
{
    uint32_t shown = read32(root + 8), placement = shown ? window_placement(shown) : 0;
    uint32_t name = placement ? read32(placement + 0x58) : 0, end = placement ? read32(placement + 0x5C) : 0;
    int length = name && end > name && end - name < 64 && void_vm_readable(name, end - name) ? (int)(end - name) : 0;
    VLOG("[touch] combat-card %s shown=%08X %.*s", mode == 2 ? "effects" : "card", shown, length,
         length ? (const char *)ADDR(name) : "");
}

/* One switch of the combat details card at the point between the card and the effects panel. Each UI
 * root +70 request steps its source's tooltip (short info, card, effects, then round again), so the card
 * comes back from the effects with two. mode: 0 short info, 1 card, 2 effects; returns the new mode. */
static int card_step(uint32_t root, float x, float y, int mode)
{
    uint32_t method = object_method(root, 0x70);
    for (int step = mode == 2 ? 2 : 1; method && step > 0 && same_screen(); --step) {
        uint32_t point = logical_point(x, y);
        if (!point) break;
        const uint32_t args[] = {point, 1};
        void_call_guest_this(method, root, 2, args);
    }
    mode = mode == 1 ? 2 : 1;
    if (void_verbose && same_screen()) card_trace(root, mode);
    return mode;
}

/* The unit whose initiative bar portrait is under the point (0x0055DC40 on combat screen +494, as the
 * right button and the combat pick ask), 0 for none. */
static uint32_t atb_unit_at(uint32_t screen, float x, float y)
{
    uint32_t bar = read32(screen + 0x494), point;
    if (read32(screen) != 0x00E1DA84u || !void_vm_readable(bar, 0x28) || !(point = logical_point(x, y))) return 0;
    return void_call_guest_this(0x0055DC40u, bar, 1, &point);
}

/* The selection ends: its card and hover leave as from a mouse moved away (the next touch has its own). */
static void atb_clear(void)
{
    if (!atb.unit) return;
    uint32_t screen = atb.screen, point;
    int current = current_screen() == screen && read32(screen + 0xA0) == atb.root;
    memset(&atb, 0, sizeof atb);
    if (current && !gesture.active && (point = logical_point(-1, -1))) ui_point_call(screen, 0x24, point, 0);
    if (!gesture.active) publish_point(-1, -1);
    VLOG("[touch] initiative portrait released");
}

/* The second tap on the selected portrait: its card, asked at once as the right button does. */
static void atb_card_show(float x, float y)
{
    uint32_t method = object_method(gesture.root, 0x70), point = logical_point(x, y);
    if (!method || !point || !void_vm_readable(0x00F39CA0u, 1) || !MEM8(0x00F39CA0u)) return;
    atb.x = x; atb.y = y;
    publish_point(x, y);
    const uint32_t args[] = {point, 1};
    void_call_guest_this(method, gesture.root, 2, args);
    if (!same_screen()) return;
    atb.card = atb.mode = 1; atb.frame = touch_frame; atb.retries = 0;
    if (void_verbose) card_trace(gesture.root, 1);
}

/* A tap in combat: 1 when it showed or switched the selected portrait's card (no click); a first tap on
 * a portrait selects it and clicks it as before. */
static int atb_tap(float x, float y)
{
    uint32_t unit = atb_unit_at(gesture.screen, x, y);
    if (!same_screen()) return 1;
    if (unit && unit == atb.unit && atb.screen == gesture.screen && atb.root == gesture.root) {
        if (atb.card) atb.mode = card_step(gesture.root, atb.x, atb.y, atb.mode);
        else atb_card_show(x, y);
        return 1;
    }
    atb_clear();
    if (!unit) return 0;
    atb.screen = gesture.screen; atb.root = gesture.root; atb.controller = gesture.controller;
    atb.unit = unit; atb.x = x; atb.y = y;
    VLOG("[touch] initiative portrait selected unit=%08X point=%.1f,%.1f", unit, x, y);
    return 0;
}

/* A touch with a portrait selected: on it, the touch takes the card's point (the card holds still);
 * elsewhere the selection ends. Returns 1 for a touch beside an open card, which only closes it. */
static int atb_begin(float x, float y)
{
    if (!atb.unit) return 0;
    int same = gesture.kind == SCREEN_COMBAT && gesture.screen == atb.screen && gesture.root == atb.root;
    uint32_t unit = same ? atb_unit_at(gesture.screen, x, y) : 0;
    if (same && unit == atb.unit) { gesture.atb = 1; return 0; }
    int closes = atb.card && same && !unit;
    atb_clear();
    return closes;
}

/* Between touches the selected portrait stays hovered and its open card held, until the bar or the
 * screen changes under it. */
static void atb_pump(void)
{
    uint32_t screen = current_screen(), point;
    if (screen != atb.screen || read32(screen + 0xA0) != atb.root || read32(screen + 0x2B4) != atb.controller ||
        atb_unit_at(screen, atb.x, atb.y) != atb.unit) { atb_clear(); return; }
    publish_point(atb.x, atb.y);
    if ((point = logical_point(atb.x, atb.y))) ui_point_call(screen, 0x24, point, 0);
    /* A card that did not appear: ask again, a few times. */
    if (atb.card && !read32(atb.root + 8) && atb.retries < 3 && touch_frame > atb.frame + 4) {
        uint32_t method = object_method(atb.root, 0x70);
        atb.frame = touch_frame; ++atb.retries;
        if (method && (point = logical_point(atb.x, atb.y))) {
            const uint32_t args[] = {point, 1};
            void_call_guest_this(method, atb.root, 2, args);
        }
    }
}

/* The adventure screen's minimap (NUI::CAdvMinimap, RTTI 0x00F34164, vtable 0x00E23B50) under the point. */
static int minimap_at(float x, float y)
{
    uint32_t window = ui_pick(gesture.screen, x, y);
    for (unsigned depth = 0; window && depth < 16 && same_screen(); ++depth) {
        const uint32_t cast[] = {window, 0, 0x00F2DAF4u, 0x00F34164u, 0};
        uint32_t minimap = void_call_guest(0x00D119FCu, 5, cast, 0);
        if (minimap && read32(minimap) == 0x00E23B50u) return 1;
        uint32_t parent = object_query(window, 0xD8);
        if (parent == window) break;
        window = parent;
    }
    return 0;
}

/* A minimap tap clicks once no second tap can follow it (GameActivity's MULTI_TAP_MS, 300 ms, and
 * a frame's delivery), so that a double tap toggles the object highlight without the camera move of
 * a first click. Another touch elsewhere clicks it at once. */
#define MINIMAP_TAP_WAIT_NS UINT64_C(400000000)
static struct { uint32_t screen, root; float x, y; uint64_t due, retire; } minimap_tap;

static void minimap_click(void)
{
    uint32_t screen = minimap_tap.screen, root = minimap_tap.root, point;
    float x = minimap_tap.x, y = minimap_tap.y;
    minimap_tap.due = 0;
    if (current_screen() != screen || read32(screen + 0xA0) != root) return;
    publish_point(x, y);
    /* The click a tap gives: hover, press, release (the hover leaves after its frame). */
    for (unsigned step = 0; step < 3; ++step) {
        if (current_screen() != screen || !(point = logical_point(x, y))) return;
        ui_point_call(screen, step == 0 ? 0x24 : step == 1 ? 0x18 : 0x1C, point, step != 0);
    }
    minimap_tap.retire = touch_frame + 1;
    VLOG("[touch] minimap click point=%.1f,%.1f", x, y);
}

static void minimap_pump(void)
{
    uint32_t point;
    if (minimap_tap.due && !gesture.active && void_perf_now_ns() >= minimap_tap.due) minimap_click();
    if (minimap_tap.retire && touch_frame >= minimap_tap.retire && !gesture.active) {
        if (current_screen() == minimap_tap.screen && (point = logical_point(-1, -1)))
            ui_point_call(minimap_tap.screen, 0x24, point, 0);
        if (!atb.unit) publish_point(-1, -1);
        minimap_tap.retire = 0;
    }
}

static void troop_second(const void_touch_event *event)
{
    if (!same_screen() || gesture.cancelled) return;
    if (event->kind==TOUCH_SECOND_BEGIN) {
        troop_cell cell;
        gesture.second_troop=gesture.ui && gesture.dnd && troop_cell_at(gesture.x,gesture.y,&cell);
        if (gesture.second_troop) {
            uint32_t source=read32(read32(gesture.dnd+0x1C)+0xC);
            gesture.second_troop=dnd_held(gesture.dnd) ? troop_cell_window(source,&cell) :
                                troop_cell_at(gesture.start_x,gesture.start_y,&cell);
        }
        if (gesture.second_troop && !dnd_held(gesture.dnd)) {
            /* Stationary hold was tooltip-only. Pick up only this proven troop slot. */
            dnd_point(0x28,gesture.start_x,gesture.start_y);
            if (dnd_identity(gesture.dnd)) dnd_point(0x2C,gesture.start_x,gesture.start_y);
            if (dnd_identity(gesture.dnd) && dnd_held(gesture.dnd)) {
                gesture.dnd_pressed=1;dnd_point(0x24,gesture.x,gesture.y);
            }
        }
        gesture.second_troop=gesture.second_troop && dnd_identity(gesture.dnd) && dnd_held(gesture.dnd);
        VLOG("[touch] troop-second screen=%08X claimed=%d held=%d",gesture.screen,gesture.second_troop,
             dnd_identity(gesture.dnd) && dnd_held(gesture.dnd));
        gesture.second_info = !gesture.combo && !gesture.second_troop && gesture.held &&
                              object_method(gesture.root, 0x70) &&
                              (combat_ui_hold() || tooltip_target_at(event->x,event->y));
        if (!gesture.second_troop && !gesture.second_info && gesture.ui) {dnd_cancel();ui_release(1);gesture.panning=1;}
    } else if (gesture.second_troop) troop_split(event->x,event->y,event->kind==TOUCH_SECOND_HOLD);
    else if (gesture.second_info && gesture.held && same_screen()) {
        uint32_t point=logical_point(gesture.x,gesture.y),method=object_method(gesture.root,0x70);
        if (point && method && (combat_ui_hold() || tooltip_target_at(event->x,event->y)) && same_screen()) {
            point=logical_point(gesture.x,gesture.y);
            const uint32_t args[]={point,1};
            /* 487A80 -> 8867D0 repicks the source before asking its tooltip provider
               for details. Keep the held source point; the second finger only triggers it. */
            publish_point(gesture.x,gesture.y);
            /* In combat each tap switches the card and the effects once (the hold's details wait no more). */
            if (gesture.kind==SCREEN_COMBAT) {
                float card_x=gesture.inspecting?gesture.inspect_x:gesture.x,card_y=gesture.inspecting?gesture.inspect_y:gesture.y;
                publish_point(card_x,card_y);
                gesture.card_mode=card_step(gesture.root,card_x,card_y,gesture.card_mode);
                gesture.details=2;
            } else
            void_call_guest_this(method,gesture.root,2,args);
            if (same_screen()) {
                gesture.inspecting=1;gesture.inspect_x=gesture.x;gesture.inspect_y=gesture.y;
                ui_hover(gesture.x,gesture.y);
                VLOG("[touch] tooltip-inspect screen=%08X point=%.1f,%.1f",gesture.screen,gesture.x,gesture.y);
            }
        }
    }
    /* The secondary finger must never move the held troop/camera/ability point. */
    if (same_screen() && !gesture.cancelled)
        publish_point(gesture.inspecting?gesture.inspect_x:gesture.x,gesture.inspecting?gesture.inspect_y:gesture.y);
    else publish_point(-1,-1);
}

static void loading_continue(void)
{
    uint32_t screen = gesture.screen;
    if (read32(screen) != 0x00E34674u || !same_screen() || !ui_idle() ||
        !void_vm_writable(screen + 0x1A4, 4) || read32(screen + 0x1A4) != 5 ||
        !void_dispatch_find(0x006B2830u) || !void_dispatch_find(0x00689390u) ||
        !void_dispatch_find(0x00AC3590u) || !void_dispatch_find(0x00838C10u)) return;
    /* Original ready-only branch of 6B2BB0: consume readiness before cleanup/queue callbacks. */
    MEM32(screen + 0x1A4) = 0;
    void_call_guest_this(0x006B2830u, screen, 0, NULL);
    void_call_guest_this(0x00689390u, 1, 0, NULL);
    uint32_t command = void_call_guest(0x00AC3590u, 0, NULL, 1);
    if (command) void_call_guest_this(0x00838C10u, command, 0, NULL);
    VLOG("[touch] loading-continue screen=%08X command=%08X", screen, command);
}

static unsigned window_vector(uint32_t begin, uint32_t end, unsigned stride)
{
    return begin && end >= begin && (end - begin) % stride == 0 && (end - begin) / stride <= 4096 &&
           void_vm_readable(begin, end - begin) ? (end - begin) / stride : 0;
}

static int window_hit(uint32_t window, uint32_t point)
{
    if (!same_screen()) return 0;
    uint32_t method = object_method(window, 0x5C);
    return method && (void_call_guest_this(method, window, 1, &point) & 0xFFu);
}

static int town_portrait_double(float x, float y)
{
    if (!town_ready() || !void_dispatch_find(0x00619320u)) return 0;
    uint32_t screen = gesture.screen, point = logical_point(x, y);
    if (!point) return 0;
    uint32_t portrait = read32(screen + 0x2A0);
    if (!window_hit(portrait, point)) {
        portrait = read32(screen + 0x2A4);
        point = logical_point(x, y);
        if (!point || !window_hit(portrait, point)) return 0;
    }
    if (!same_screen() || !window_contains(ui_pick(screen, x, y), portrait) || !same_screen() || !ui_idle()) return 0;
    /* Native dblclick_pointer action before WM queues a cursor-dependent deferred duplicate. */
    gesture.committed = 1;
    uint32_t page = 1;
    void_call_guest_this(0x00619320u, screen, 1, &page);
    VLOG("[touch] town-hero-double screen=%08X", screen);
    return 1;
}

static uint32_t mentor_window(uint32_t point)
{
    uint32_t screen = gesture.screen;
    uint32_t state = screen + (MEM8(screen + 0x4B8) ? 0x338 : 0x1B8);
    uint32_t mode = read32(state + 4), begin, end;
    if (mode == 3) {
        begin = read32(screen + 0x5A0); end = read32(screen + 0x5A4);
        for (unsigned i = 0, n = window_vector(begin, end, 16); i < n; ++i) {
            uint32_t window = read32(begin + i * 16);
            if (window_hit(window, point)) return window;
        }
        begin = read32(screen + 0x5AC); end = read32(screen + 0x5B0);
        for (unsigned i = 1, n = window_vector(begin, end, 4); i < n; ++i) {
            uint32_t window = read32(begin + i * 4);
            if (window_hit(window, point)) return window;
        }
    } else if (mode == 4) {
        begin = read32(screen + 0x5D4); end = read32(screen + 0x5D8);
        for (unsigned i = 0, n = window_vector(begin, end, 36); i < n; ++i) {
            uint32_t entry = begin + i * 36, window = read32(entry + 4);
            if (window_hit(window, point)) return window;
            uint32_t children = read32(entry + 8), children_end = read32(entry + 12);
            for (unsigned j = 0, count = window_vector(children, children_end, 4); j < count; ++j) {
                window = read32(children + j * 4);
                if (window_hit(window, point)) return window;
            }
        }
    }
    return 0;
}

static void mentor_activate(float x, float y, int twice)
{
    uint32_t screen = gesture.screen;
    if (read32(screen) != 0x00E3584Cu || !same_screen() || !ui_idle() ||
        !void_vm_readable(screen, 0x7EC) || read32(screen + 0x7DC) != 6 || read32(screen + 0x7E8)) return;
    uint32_t point = logical_point(x, y), window = point ? mentor_window(point) : 0;
    if (!window || !same_screen() || !window_contains(ui_pick(screen, x, y), window) || !same_screen() || !ui_idle()) return;
    if (read32(screen + 0x7DC) != 6 || read32(screen + 0x7E8)) return;
    point = logical_point(x, y);
    if (point && (void_call_guest_this(0x006C15D0u, screen, 1, &point) & 0xFFu) &&
        twice && same_screen() && ui_idle()) void_call_guest_this(0x006C0FB0u, screen, 0, NULL);
}

static uint32_t ghost_window(uint32_t point, int energy_only)
{
    uint32_t begin = read32(gesture.screen + 0x1D8), end = read32(gesture.screen + 0x1DC);
    for (unsigned i = 0, n = window_vector(begin, end, 36); i < n; ++i) {
        uint32_t entry = begin + i * 36, window = read32(entry + 0x20);
        if (window_hit(window, point)) return window;
        window = read32(entry + 0x1C);
        if (!energy_only && window_hit(window, point)) return window;
    }
    return 0;
}

static int ghost_owned_point(float x, float y, int energy_only)
{
    uint32_t screen = gesture.screen;
    if (read32(screen) != 0x00E4094Cu || !same_screen() || !ui_idle() || !void_vm_readable(screen, 0x218)) return 0;
    uint32_t point = logical_point(x, y), window = point ? ghost_window(point, energy_only) : 0;
    if (!window || !same_screen() || !window_contains(ui_pick(screen, x, y), window) || !same_screen() || !ui_idle()) return 0;
    return 1;
}

static int ghost_point(float x, float y, int activate)
{
    uint32_t screen = gesture.screen;
    if (!ghost_owned_point(x, y, !activate)) return 0;
    if (activate) {
        if (x < 0 || y < 0 || x > 32767 || y > 32767) return 1;
        uint32_t argument = scratch + 320;
        memset((void *)ADDR(argument), 0, 40);
        MEM32(argument + 0x24) = ((uint32_t)x & 0x7FFFu) | (((uint32_t)y & 0x7FFFu) << 15);
        /* This UI-only handler reads only the explicit point, then uses the original command builder. */
        void_call_guest_this(0x0078FDF0u, screen, 1, &argument);
    } else {
        uint32_t point = logical_point(x, y);
        if (point) void_call_guest_this(0x0078FBC0u, screen, 1, &point);
    }
    return 1;
}

static uint32_t window_placement(uint32_t window);

/* The slider (CWindowSlider) under the point and its lever's centre in logical UI coordinates:
 * the lever is the CWindowMSButton the slider's layout caches at +134, placed at +64/+68. */
static int slider_lever_at(float x, float y, float *lx, float *ly)
{
    uint32_t window = ui_pick(gesture.screen, x, y);
    for (unsigned depth = 0; window && depth < 16 && same_screen(); ++depth) {
        const uint32_t cast[] = {window, 0, 0x00F2DAF4u, 0x00F2DC80u, 0};
        uint32_t slider = void_call_guest(0x00D119FCu, 5, cast, 0);
        if (read32(slider) == 0x00E13F2Cu && void_vm_readable(slider, 0x138)) {
            uint32_t lever = MEM32(slider + 0x134), placement = lever ? window_placement(lever) : 0;
            if (!placement || !void_vm_readable(lever + 0x64, 8)) return 0;
            *lx = MEMF(lever + 0x64) + MEMF(placement + 0xA4) * 0.5f;
            *ly = MEMF(lever + 0x68) + MEMF(placement + 0xA8) * 0.5f;
            return isfinite(*lx) && isfinite(*ly);
        }
        uint32_t parent = object_query(window, 0xD8);
        if (parent == window) break;
        window = parent;
    }
    return 0;
}

/* The lever's point for the finger at (x, y): it moves by the finger's travel from its start. */
static uint32_t slider_point(float x, float y)
{
    uint32_t point = logical_point(x, y);
    if (!point) return 0;
    MEMF(point) = gesture.slider_x + MEMF(point) - gesture.slider_fx;
    MEMF(point + 4) = gesture.slider_y + MEMF(point + 4) - gesture.slider_fy;
    memcpy((void *)ADDR(scratch + 480), (const void *)ADDR(point), 8);   /* the cursor the slider reads too */
    return point;
}

/* The combobox under the point opened through its normal click (disabled ones stay shut). */
static int combo_open(float x, float y)
{
    uint32_t window = ui_pick(gesture.screen, x, y);
    for (unsigned depth = 0; window && depth < 16 && same_screen(); ++depth) {
        const uint32_t cast[] = {window, 0, 0x00F2DAF4u, 0x00F786F0u, 0};
        uint32_t combo = void_call_guest(0x00D119FCu, 5, cast, 0);
        if (read32(combo) == 0x00E8603Cu && void_vm_readable(combo, 0x168)) {
            uint32_t point = logical_point(x, y);
            if (!point) return 0;
            ui_point_call(gesture.screen, 0x18, point, 1);
            if (same_screen()) ui_point_call(gesture.screen, 0x1C, point, 1);
            if (same_screen() && read32(combo) == 0x00E8603Cu) gesture.combo = combo;
            VLOG("[touch] combobox opened by a swipe %08X", combo);
            return gesture.combo != 0;
        }
        uint32_t parent = object_query(window, 0xD8);
        if (parent == window) break;
        window = parent;
    }
    return 0;
}

static void_fn original_choice_update;

/* CPlayerSlot::Update rebuilds the original localized tooltip before its specialization details. */
static void choice_update(void)
{
    static uint32_t buffer;
    static unsigned depth;
    uint32_t row = g_ecx;
    ++depth;
    original_choice_update();
    if (--depth || !void_vm_readable(row, 0xA0)) return;
    void_regs saved;
    void_regs_save(&saved);
    uint32_t hero = void_call_guest_this(0x004A6740u, row + 0x88, 0, NULL);
    if (void_vm_readable(hero, 0x124)) {
        uint32_t description = void_call_guest_this(0x004C7430u, hero + 0x118, 0, NULL);
        const uint32_t cast[] = {read32(row + 0x98), 0, 0x00F2DAF4u, 0x00F2DA88u, 0};
        uint32_t icon = void_call_guest(0x00D119FCu, 5, cast, 0), provider = read32(icon + 0x24);
        uint32_t a = read32(provider + 8), b = read32(provider + 12);
        uint32_t c = read32(description), d = read32(description + 4);
        if (read32(provider) == 0x00E4E754u && b > a && d > c && !((b - a) & 1) && !((d - c) & 1) &&
            b - a < 8192 && d - c < 49152 && void_vm_readable(a, b - a) && void_vm_readable(c, d - c)) {
            if (!buffer) buffer = void_galloc(65536);
            if (buffer) {
                static const uint16_t separator[] = {'<','b','r','>','<','b','r','>'};
                memcpy((void *)ADDR(buffer), (const void *)ADDR(a), b - a);
                memcpy((void *)ADDR(buffer + b - a), separator, sizeof separator);
                memcpy((void *)ADDR(buffer + b - a + sizeof separator), (const void *)ADDR(c), d - c);
                const uint32_t range[] = {buffer, buffer + b - a + sizeof separator + d - c};
                void_call_guest_this(0x0040E960u, provider + 8, 2, range);
            }
        }
    }
    void_regs_load(&saved);
}

static int choice_named(uint32_t window, const char *name)
{
    uint32_t placement = window_placement(window);
    uint32_t begin = read32(placement + 0x58), end = read32(placement + 0x5C);
    size_t length = strlen(name);
    return placement && end - begin == length && void_vm_readable(begin, (uint32_t)length) &&
           !memcmp((const void *)ADDR(begin), name, length);
}

static uint32_t choice_child(uint32_t parent, const char *name)
{
    uint32_t begin = read32(parent + 0xA4), end = read32(parent + 0xA8);
    if (end < begin || (end - begin) % 4 || end - begin > 1024 || !void_vm_readable(begin, end - begin)) return 0;
    for (uint32_t at = begin; at < end; at += 4)
        if (choice_named(MEM32(at), name)) return MEM32(at);
    return 0;
}

static void choice_frame(uint32_t icon, uint32_t show)
{
    uint32_t frame = choice_child(icon, "PortChoiceSelection"), vb = read32(frame + 0x10);
    uint32_t interface = vb ? frame + 0x10 + read32(vb + 8) : 0, setter = object_method(interface, 0x44);
    if (setter) void_call_guest_this(setter, interface, 1, &show);
}

static void choice_clear(void)
{
    if (choice.icon && current_screen() == choice.screen && read32(choice.screen + 0xA0) == choice.root)
        choice_frame(choice.icon, 0);
    memset(&choice, 0, sizeof choice);
}

/* The original arrows own the allowed hero/faction/bonus lists, including map and multiplayer rules. */
static int choice_begin(float x, float y)
{
    static const char *names[][3] = {
        {"heroicon", "hero_change_left", "hero_change_right"},
        {"race", "race_change_left", "race_change_right"},
        {"bonus", "bonus_change_left", "bonus_change_right"},
        {"team", "team_color_left", "team_color_right"},
        {"state", "open_close_left", "open_close_right"}
    };
    if (gesture.kind != SCREEN_MENU) return 0;
    uint32_t hit = ui_pick(gesture.screen, x, y);
    const uint32_t cast[] = {hit, 0, 0x00F2DAF4u, 0x00F2DA88u, 0};
    uint32_t icon = hit ? void_call_guest(0x00D119FCu, 5, cast, 0) : 0;
    for (unsigned depth = 0; icon && depth < 3 && same_screen(); ++depth, icon = read32(icon + 0x28)) {
        for (unsigned i = 0; i < sizeof names / sizeof *names; ++i) {
            if (!choice_named(icon, names[i][0])) continue;
            uint32_t row = read32(icon + 0x28), left = choice_child(row, names[i][1]), right = choice_child(row, names[i][2]);
            if (!left || !right) return 0;
            choice_clear();
            choice.screen = gesture.screen; choice.root = gesture.root; choice.row = row;
            choice.icon = icon; choice.left = left; choice.right = right; choice.frame = touch_frame;
            choice_frame(icon, 1);
            return 1;
        }
    }
    return 0;
}

static uint32_t choice_point(uint32_t window)
{
    uint32_t placement = window_placement(window), point = logical_point(-1, -1);
    if (!placement || !point || !MEM8(placement + 0x70)) return 0;
    MEMF(point) = MEMF(window + 0x64) + MEMF(placement + 0xA4) * .5f;
    MEMF(point + 4) = MEMF(window + 0x68) + MEMF(placement + 0xA8) * .5f;
    memcpy((void *)ADDR(scratch + 480), (const void *)ADDR(point), 8);
    return point;
}

static void choice_pump(void)
{
    if (!choice.icon) return;
    if (current_screen() != choice.screen || read32(choice.screen + 0xA0) != choice.root ||
        read32(choice.icon + 0x28) != choice.row) { memset(&choice, 0, sizeof choice); return; }
    if (touch_frame <= choice.frame + 1 || gesture.active) return;
    uint32_t point = choice_point(choice.icon);
    if (point) ui_point_call(choice.screen, 0x24, point, 0);
    else choice_clear();
}

static int choice_end(float x, float y)
{
    if (!choice.icon || choice.screen != gesture.screen || !same_screen()) return 0;
    float dx = x - gesture.start_x, dy = y - gesture.start_y;
    if (gesture.panning && !gesture.held && fabsf(dx) > fabsf(dy) && fabsf(dx) >= 24) {
        uint32_t point = choice_point(dx < 0 ? choice.right : choice.left);
        if (point) {
            ui_point_call(gesture.screen, 0x24, point, 0);
            if (same_screen()) ui_point_call(gesture.screen, 0x18, point, 1);
            if (same_screen()) ui_point_call(gesture.screen, 0x1C, point, 1);
            VLOG("[touch] scenario choice %08X direction=%d", choice.icon, dx < 0 ? 1 : -1);
        }
    }
    choice.frame = touch_frame;
    gesture.held = gesture.pressed = 0;
    gesture.committed = gesture.retiring = 1;
    gesture.release_frame = touch_frame;
    return 1;
}

static void ui_event(const void_touch_event *event)
{
    gesture.x = event->x; gesture.y = event->y;
    switch (event->kind) {
    case TOUCH_BEGIN:
        if (!choice_begin(event->x, event->y)) choice_clear();
        ui_hover(event->x, event->y);
        break;
    case TOUCH_TAP:
    case TOUCH_DOUBLE_TAP: {
        if (gesture.committed || gesture.held || gesture.panning) break;
        if (choice.icon) { gesture.committed = 1; break; }
        if (gesture.kind == SCREEN_COMBAT && atb_tap(event->x, event->y)) { gesture.committed = 1; break; }
        /* A double tap on the minimap toggles the map's object highlight, as Alt held; its single taps
           click once no second one can follow (minimap_tap), so the double tap leaves the camera. */
        if (gesture.kind == SCREEN_ADVENTURE && minimap_at(event->x, event->y)) {
            if (!same_screen()) break;
            if (event->kind == TOUCH_DOUBLE_TAP) {
                minimap_tap.due = 0;
                alt_latch(alt_screen ? 0 : gesture.screen);
            } else {
                if (minimap_tap.due) minimap_click();   /* an earlier tap, followed too late */
                minimap_tap.screen = gesture.screen; minimap_tap.root = gesture.root;
                minimap_tap.x = event->x; minimap_tap.y = event->y;
                minimap_tap.due = void_perf_now_ns() + MINIMAP_TAP_WAIT_NS;
            }
            gesture.committed = 1;
            break;
        }
        if (!same_screen()) break;
        int consumed = adventure_announcement(event->x, event->y, 1);
        if (consumed || gesture.announcement) {
            gesture.committed = 1;
            break;
        }
        if (!same_screen()) break;
        if (gesture.dnd && !gesture.dnd_claim) { dnd_cancel(); if (!same_screen()) break; }
        uint32_t point = logical_point(event->x, event->y);
        if (!point) break;
        float lever_x, lever_y;
        if (slider_lever_at(event->x, event->y, &lever_x, &lever_y)) { gesture.committed = 1; break; }   /* a swipe moves it */
        point = logical_point(event->x, event->y);
        if (!point) break;
        ui_point_call(gesture.screen, 0x24, point, 0);
        if (!same_screen()) break;
        uint32_t child = ui_pick(gesture.screen, event->x, event->y);
        if (!same_screen()) break;
        text_choose(gesture.screen, gesture.root, event->x, event->y);
        if (!same_screen()) break;
        if (event->kind == TOUCH_DOUBLE_TAP && town_portrait_double(event->x, event->y)) break;
        if (!same_screen()) break;
        uint32_t window_consumed = ui_point_call(gesture.screen, event->kind == TOUCH_DOUBLE_TAP ? 0x20 : 0x18, point, 1) & 0xFFu;
        if (!same_screen()) break;
        window_consumed |= ui_point_call(gesture.screen, 0x1C, point, 1) & 0xFFu;
        gesture.committed = 1;
        if (read32(gesture.screen) == 0x00E34674u) { loading_continue(); break; }
        if (gesture.dnd_claim && dnd_claim_at(gesture.dnd, event->x, event->y)) {
            dnd_point(event->kind == TOUCH_DOUBLE_TAP ? 0x30 : 0x28, event->x, event->y);
            if (dnd_identity(gesture.dnd)) dnd_point(0x2C, event->x, event->y);
            break;
        }
        if (same_screen()) mentor_activate(event->x, event->y, event->kind == TOUCH_DOUBLE_TAP);
        if (same_screen()) ghost_point(event->x, event->y, 1);
        if (!child && !window_consumed && same_screen() && !ui_pick(gesture.screen, event->x, event->y)) {
            if (gesture.book) spellbook_activate(event->x, event->y);
            else town_activate(event->x, event->y);
        }
        break;
    }
    case TOUCH_HOLD_BEGIN:
    case TOUCH_HOLD_DRAG:
        if (gesture.combo) {
            gesture.held = 1;
            if (event->kind == TOUCH_HOLD_DRAG) gesture.panning = 1;
            ui_hover(event->x, event->y);
            break;
        }
        if (event->kind==TOUCH_HOLD_DRAG && gesture.army_portrait) {
            gesture.panning=gesture.held=1;ui_hover(event->x,event->y);break;
        }
        if (event->kind == TOUCH_HOLD_DRAG && gesture.dnd && gesture.dnd_claim) {
            if (!gesture.dnd_pressed) {
                dnd_point(0x28, gesture.start_x, gesture.start_y);
                gesture.dnd_pressed = 1;
            }
            if (dnd_identity(gesture.dnd)) dnd_point(0x24, event->x, event->y);
        }
        gesture.held = 1;
        ui_hover(event->x, event->y);
        break;
    case TOUCH_PAN: {
        gesture.panning = 1;
        if (choice.icon) break;
        if (gesture.ghost_energy && !gesture.held) {
            ghost_point(event->x, event->y, 0);
            ui_hover(event->x, event->y);
            break;
        }
        if (gesture.dnd && (!gesture.held || gesture.dnd_pressed)) {
            if (!gesture.dnd_claim) dnd_cancel();
            else {
                if (!gesture.dnd_pressed) {
                    dnd_point(0x28, gesture.start_x, gesture.start_y);
                    gesture.dnd_pressed = 1;
                }
                if (dnd_identity(gesture.dnd)) dnd_point(0x24, event->x, event->y);
                ui_hover(event->x, event->y);
                break;
            }
        }
        if (gesture.book) {
            gesture.panning = 1;
            if (!ui_pick(gesture.screen, gesture.start_x, gesture.start_y)) { ui_hover(event->x, event->y); break; }
        }
        if (gesture.held || gesture.announcement) { ui_hover(event->x, event->y); break; }
        if (gesture.slider) {
            uint32_t point = slider_point(event->x, event->y);
            if (point) ui_point_call(gesture.screen, 0x24, point, 0);
            break;
        }
        /* A swipe that starts on a slider takes its lever where it is and moves it by the finger's travel. */
        float lever_x, lever_y;
        if (!gesture.pressed && !gesture.dnd && slider_lever_at(gesture.start_x, gesture.start_y, &lever_x, &lever_y)) {
            uint32_t start = logical_point(gesture.start_x, gesture.start_y);
            if (!start) break;
            gesture.slider = gesture.pressed = 1;
            gesture.slider_x = lever_x; gesture.slider_y = lever_y;
            gesture.slider_fx = MEMF(start); gesture.slider_fy = MEMF(start + 4);
            uint32_t point = slider_point(gesture.start_x, gesture.start_y);
            if (point) ui_point_call(gesture.screen, 0x24, point, 0);
            point = slider_point(gesture.start_x, gesture.start_y);
            if (point && same_screen()) ui_point_call(gesture.screen, 0x18, point, 1);
            point = slider_point(event->x, event->y);
            if (point && same_screen()) ui_point_call(gesture.screen, 0x24, point, 0);
            VLOG("[touch] slider swipe lever=%.1f,%.1f", lever_x, lever_y);
            break;
        }
        /* A swipe that starts on a combobox opens it and the release picks the item under the finger. */
        if (!gesture.pressed && !gesture.dnd && combo_open(gesture.start_x, gesture.start_y)) {
            gesture.held = 1;
            ui_hover(event->x, event->y);
            break;
        }
        if (!gesture.pressed && ui_scroll(event)) break;
        if (!gesture.pressed) {
            uint32_t point = logical_point(gesture.start_x, gesture.start_y);
            if (!point) break;
            ui_point_call(gesture.screen, 0x18, point, 1);
            gesture.pressed = 1;
        }
        if (same_screen()) ui_hover(event->x, event->y);
        break;
    }
    case TOUCH_TWO_FINGER_BEGIN:
        choice_clear();
        dnd_cancel();
        gesture.second_troop = 0;
        ui_release(1);
        gesture.panning = 1;
        break;
    case TOUCH_TRANSFORM:
        gesture.panning = 1;
        if (!gesture.dnd_pressed && !gesture.pressed)
            void_touch_ui_pan(gesture.screen, event->dx, event->dy);
        break;
    case TOUCH_TWO_FINGER_CANCEL:
    case TOUCH_ABORT:
        dnd_cancel();
        dnd_owner_pump(1);
        ui_release(1);
        gesture.cancelled = 1;
        break;
    case TOUCH_END:
        if (choice_end(event->x, event->y)) break;
        if (gesture.book && gesture.panning && !gesture.held && !gesture.pressed && !gesture.dnd_pressed &&
            book_swipe(event->x, event->y)) {
            gesture.committed = 1;
            ui_release(0);
            break;
        }
        if (gesture.combo) {
            uint32_t popup = read32(gesture.combo + 0x134);
            uint32_t vb = read32(popup + 0x10);
            uint32_t popup_interface = vb ? popup + 0x10 + read32(vb + 8) : 0;
            if (gesture.panning && read32(gesture.combo) == 0x00E8603Cu && popup && same_screen() &&
                window_contains(ui_pick(gesture.screen, event->x, event->y), popup_interface) && same_screen()) {
                uint32_t point = logical_point(event->x, event->y);
                if (point) {
                    ui_point_call(gesture.screen, 0x18, point, 1);
                    if (same_screen()) ui_point_call(gesture.screen, 0x1C, point, 1);
                    gesture.committed = 1;
                }
            }
            gesture.combo = 0;
            if (gesture.committed) {
                gesture.held = 0; gesture.retiring = 1; gesture.release_frame = touch_frame;
            } else ui_release(0);
            break;
        }
        if (gesture.slider) {
            uint32_t point = slider_point(event->x, event->y);
            if (point) ui_point_call(gesture.screen, 0x1C, point, 1);
            gesture.slider = gesture.pressed = 0;
            gesture.committed = 1;
            ui_release(0);
            break;
        }
        if (troop_drop(event->x,event->y)) { ui_release(1);break; }
        if (gesture.dnd_pressed) {
            if (dnd_claim_at(gesture.dnd, event->x, event->y)) dnd_point(0x2C, event->x, event->y);
            else dnd_cancel();
            gesture.dnd_pressed = 0;
        }
        if (gesture.committed && !gesture.pressed) {
            /* Hover exit cancels a button's deferred reaction; let its native frame finish. */
            gesture.held = 0;
            gesture.retiring = 1;
            gesture.release_frame = touch_frame;
        } else ui_release(0);
        break;
    default:
        break;
    }
}

#ifndef VOID_ANDROID_APP
void void_android_load_ready(void) {}
#endif

/* The startup is over once a game screen has drawn a few frames. */
static void startup_pump(void)
{
    static int frames, announced;
    static uint64_t started;
    if (announced) return;
    if (!started) started = void_perf_now_ns();
    if (!current_screen()) { frames = 0; return; }
    if (++frames < 12) return;
    announced = 1;
    void_log("[startup] first screen after %.1f s, %llu files opened, %llu views mapped",
             (double)(void_perf_now_ns() - started) / 1e9,
             (unsigned long long)void_perf_calls(VOID_PERF_FILE_OPEN),
             (unsigned long long)void_perf_calls(VOID_PERF_FILE_MAP));
    void_android_load_ready();
}

void void_touch_ui_pump(void)
{
    if (pointer_text.pending && touch_frame > pointer_text.frame) {
        pointer_text.pending = 0;
        uint32_t screen = current_screen();
        if (!touch_mode && screen == pointer_text.screen)
            text_choose(screen, read32(screen + 0xA0), pointer_text.x, pointer_text.y);
    }
#ifdef VOID_ANDROID_APP
    port_menu_pump();
#endif
    startup_pump();
    army_pump();
    dnd_owner_pump(0);
    troop_preview_pump();
    if (gesture.retiring) {
        int current = same_screen();
        if (!current || touch_frame != gesture.release_frame) {
            int keep = 0;
            keep = atb.unit != 0 || choice.icon != 0;   /* the selected initiative portrait keeps the cursor (atb_pump) */
            if (current && !keep) ui_hover(-1, -1);
            if (!drag_owner.helper && !keep) publish_point(-1, -1);
            gesture.retiring = 0;
        }
    }
    if (gesture.details == 1 && gesture.active && gesture.held && !gesture.cancelled && same_screen()) world_details();
    if (atb.unit && !gesture.active) atb_pump();
    choice_pump();
    minimap_pump();
    /* A card that did not appear (its source was still being picked): ask again, a few times. */
    if (gesture.card && gesture.active && !read32(gesture.root + 8) && gesture.card_retries < 3 &&
        touch_frame > gesture.card_frame + 4 && same_screen()) {
        gesture.card_frame = touch_frame; ++gesture.card_retries;
        world_details_request(0);
    }
    if (alt_screen && current_screen() != alt_screen) alt_latch(0);
    if (ctrl_held && !gesture.active) ctrl_latch(0);
    /* A held finger hovers like the resting mouse: UI tooltips, and the world
       information its screen's tooltip controller hands to the UI root. */
    if (gesture.active && gesture.held && (gesture.ui || gesture.world_hover) && !gesture.cancelled) {
        if (same_screen()) {
            float x=gesture.inspecting?gesture.inspect_x:gesture.x,y=gesture.inspecting?gesture.inspect_y:gesture.y;
            publish_point(x,y);ui_hover(x,y);
        }
        else { gesture.active = 0; publish_point(-1, -1); }
    } else if (gesture.world_hover) {
        /* Aborted or cancelled by a second finger: the information goes too. */
        if (same_screen()) ui_hover(-1, -1);
        gesture.world_hover = 0;
    }
}

static void combat_reset_context(void)
{
    uint32_t temporary = scratch + 160;
    memset((void *)ADDR(temporary), 0, 156);
    void_call_guest_this(0x00550A70u, temporary, 0, NULL);
    void_call_guest_this(0x00550EB0u, gesture.screen + 0x2EC, 1, &temporary);
    void_call_guest_this(0x00550B00u, temporary, 0, NULL);
}

static void combat_cancel(void)
{
    if (gesture.placement) {
        uint32_t placement = read32(gesture.screen + 0x488);
        if (placement) void_call_guest_this(0x00576260u, placement, 0, NULL);
    }
    void_call_guest_this(0x00542A30u, gesture.screen, 0, NULL);
    combat_reset_context();
    MEM32(gesture.screen + 0x31C) = 1;
    void_call_guest_this(0x005498C0u, gesture.screen, 0, NULL);
}

static int combat_prepare(float x, float y, int diagnostics)
{
    uint32_t screen = gesture.screen, point = logical_point(x, y);
    if (!point || !same_screen() || !void_vm_writable(screen + 0x2EC, 156)) {
        if (diagnostics) VLOG("[touch] combat-prepare rejected point=%08X screen=%08X", point, screen);
        return 0;
    }
    float px = MEMF(point), py = MEMF(point + 4);
    if (diagnostics) VLOG("[touch] combat-prepare before state=%X ui=%X active=%08X controller=%08X logical=%.3f,%.3f spell=%u caster=%08X second=%08X",
                         read32(screen + 0x2E0), read32(screen + 0x2D4), read32(screen + 0x2AC),
                         read32(screen + 0x2B4), px, py, read32(screen + 0x394), read32(screen + 0x388), read32(screen + 0x38C));
    void_call_guest_this(0x00540DA0u, screen, 0, NULL);
    combat_reset_context();
    if (!same_screen()) return 0;
    MEMF(screen + 0x2EC) = px; MEMF(screen + 0x2F0) = py;
    if (diagnostics) VLOG("[touch] combat-ownership state=%X ui=%X", read32(screen + 0x2E0), read32(screen + 0x2D4));
    if (!(read32(screen + 0x2E0) & 0x188u) || read32(screen + 0x2D4) == 1) return 0;
    const uint32_t pick[] = {screen + 0x2F4, screen + 0x2EC};
    void_call_guest_this(0x00544230u, screen, 2, pick);
    if (!same_screen()) return 0;
    if (diagnostics) VLOG("[touch] combat-pick refs=%08X,%08X extra=%08X,%08X cell=%d,%d tail=%08X,%08X,%08X",
                         read32(screen + 0x2F4), read32(screen + 0x2F8), read32(screen + 0x2FC), read32(screen + 0x300),
                         (int32_t)read32(screen + 0x304), (int32_t)read32(screen + 0x308), read32(screen + 0x30C),
                         read32(screen + 0x310), read32(screen + 0x314));
    uint32_t active = read32(screen + 0x2AC), base = virtual_base(active, 4);
    int unit_live = base && void_vm_readable(base, 8) && !(MEM8(base + 7) & 0x80u);
    uint32_t unit_allowed = unit_live ? void_call_guest_this(0x0053E3D0u, screen, 1, &active) & 0xFFu : 0;
    uint32_t unit_blocked = unit_allowed ? void_call_guest_this(0x0053FBE0u, screen, 1, &active) & 0xFFu : 0;
    if (diagnostics) VLOG("[touch] combat-unit active=%08X base=%08X live=%d allowed53E3D0=%u blocked53FBE0=%u",
                         active, base, unit_live, unit_allowed, unit_blocked);
    if (!unit_live || !unit_allowed || unit_blocked) {
        MEM32(screen + 0x31C) = 1;
        return 0;
    }
    uint32_t active_slot = screen + 0x2AC;
    void_call_guest_this(0x0083F2B0u, screen + 0x320, 1, &active_slot);
    MEM32(screen + 0x32C) = MEM32(screen + 0x304);
    MEM32(screen + 0x330) = MEM32(screen + 0x308);
    uint32_t context_blocked = void_call_guest_this(0x0053EEE0u, screen, 0, NULL) & 0xFFu;
    if (diagnostics) VLOG("[touch] combat-guard blocked53EEE0=%u selected=%08X cell=%d,%d",
                         context_blocked, read32(screen + 0x320), (int32_t)read32(screen + 0x32C), (int32_t)read32(screen + 0x330));
    if (context_blocked) return 0;
    const uint32_t context[] = {screen + 0x2EC, screen + 0x2F4};
    void_call_guest_this(0x00548270u, screen, 2, context);
    if (diagnostics) VLOG("[touch] combat-resolved action=%u command=%08X command-vt=%08X command-flags=%08X target=%08X cell=%d,%d state=%X ui=%X",
                         read32(screen + 0x31C), read32(screen + 0x33C), read32(read32(screen + 0x33C)),
                         read32(read32(screen + 0x33C) + 4), read32(screen + 0x324), (int32_t)read32(screen + 0x32C),
                         (int32_t)read32(screen + 0x330), read32(screen + 0x2E0), read32(screen + 0x2D4));
    return same_screen();
}

static void combat_point(float x, float y, int commit)
{
    if (x < 0 || y < 0 || x > 32767 || y > 32767) return;
    if (!combat_prepare(x, y, commit)) return;
    if (!refresh_target_mode()) return;
    if (!commit) {
        void_call_guest_this(0x005498C0u, gesture.screen, 0, NULL);
        return;
    }
    /* The commit consumes prepared engine context; this point is never queued as input. */
    uint32_t argument = scratch + 320;
    memset((void *)ADDR(argument), 0, 40);
    MEM32(argument + 0x24) = ((uint32_t)x & 0x7FFFu) | (((uint32_t)y & 0x7FFFu) << 15);
    VLOG("[touch] combat-before-commit state=%X ui=%X action=%u command=%08X controller=%08X active=%08X spell=%u caster=%08X second=%08X",
         read32(gesture.screen + 0x2E0), read32(gesture.screen + 0x2D4), read32(gesture.screen + 0x31C),
         read32(gesture.screen + 0x33C), read32(gesture.screen + 0x2B4), read32(gesture.screen + 0x2AC),
         read32(gesture.screen + 0x394), read32(gesture.screen + 0x388), read32(gesture.screen + 0x38C));
    uint32_t result = void_call_guest_this(0x00545490u, gesture.screen, 1, &argument) & 0xFFu;
    VLOG("[touch] combat-context point=%.1f,%.1f state=%X result=%u ui=%X action=%u command=%08X active=%08X spell=%u caster=%08X second=%08X",
         x, y, read32(gesture.screen + 0x2E0), result, read32(gesture.screen + 0x2D4), read32(gesture.screen + 0x31C),
         read32(gesture.screen + 0x33C), read32(gesture.screen + 0x2AC), read32(gesture.screen + 0x394),
         read32(gesture.screen + 0x388), read32(gesture.screen + 0x38C));
}

static int combat_double(float x, float y)
{
    if (gesture.aiming || target_armed() || !combat_prepare(x, y, 1)) return 0;
    uint32_t screen = gesture.screen, active = read32(screen + 0x320), base = virtual_base(active, 4);
    if (!base || !void_vm_readable(base, 8) || (MEM8(base + 7) & 0x80u) ||
        active != read32(screen + 0x2F4) || !(read32(screen + 0x2E0) & 0x188u) ||
        read32(screen + 0x2D4) != 0 || target_armed() || !object_query(active, 0x74) ||
        !same_screen() || ui_pick(screen, x, y) || !same_screen() || target_armed()) return 0;
    /* Native double-click's input_Combat_Cast helper never reads its forwarded argument. */
    uint32_t unused = 0;
    gesture.committed = 1;
    void_call_guest_this(0x00545160u, screen, 1, &unused);
    int current = same_screen();
    if (!current || ui_pick(screen, x, y) || !same_screen()) publish_point(-1, -1);
    if (!current) gesture.active = 0;
    VLOG("[touch] combat-double active=%08X current=%d", active, current);
    return 1;
}

/* A window's placement (IWindow +8 is `mov eax, [ecx+offset]; ret`), as touch_scale.c reads it. */
static uint32_t window_placement(uint32_t window)
{
    uint32_t table = read32(window), getter = table ? read32(table + 8) : 0;
    if (!getter || !void_vm_readable(getter, 7)) return 0;
    const uint8_t *code = (const uint8_t *)ADDR(getter);
    if (code[0] != 0x8B || code[1] != 0x81 || code[6] != 0xC3) return 0;
    uint32_t offset;
    memcpy(&offset, code + 2, 4);
    if (offset > 0x1000 || !void_vm_readable(window + offset, 4)) return 0;
    uint32_t placement = MEM32(window + offset);
    return void_vm_readable(placement, 0xC4) ? placement : 0;
}

/* The dragged stack's portrait hangs from its top-left corner, which 0x008126E0 puts at the point:
 * over the reserve the finger seemed to point with that corner, while on the field the stack stands
 * under the finger. Centre the portrait on the finger (helper +84: shown +10, window +C). */
static void placement_icon_center(uint32_t placement, float x, float y)
{
    uint32_t helper = read32(placement + 0x84);
    if (!helper || !void_vm_readable(helper, 0x14) || !MEM8(helper + 0x10)) return;
    uint32_t icon = window_placement(read32(helper + 0xC)), point;
    if (!icon) return;
    float width = MEMF(icon + 0xA4), height = MEMF(icon + 0xA8);
    if (!(width > 0 && height > 0 && width < 512 && height < 512) || !(point = logical_point(x, y))) return;
    MEMF(point) -= width * 0.5f;
    MEMF(point + 4) -= height * 0.5f;
    void_call_guest_this(0x008126E0u, helper, 1, &point);
}

static void placement_point(float x, float y, int phase)
{
    uint32_t point = logical_point(x, y), placement = read32(gesture.screen + 0x488);
    if (!point || !placement || !same_screen()) return;
    uint32_t pick = scratch + 8;
    memset((void *)ADDR(pick), 0, 40);
    const uint32_t pick_args[] = {pick, point};
    void_call_guest_this(0x00544230u, gesture.screen, 2, pick_args);
    if (phase == 1) {
        const uint32_t args[] = {point, pick + 0x10};
        void_call_guest_this(0x005767A0u, placement, 2, args);
        placement_icon_center(placement, x, y);
    } else {
        uint32_t player = void_call_guest_this(0x00669430u, gesture.screen, 0, NULL);
        const uint32_t args[] = {point, pick + 0x10, player};
        void_call_guest_this(phase == 0 ? 0x005779D0u : 0x00577DC0u, placement, 3, args);
    }
    void_call_guest_this(0x0054E030u, pick, 0, NULL);
}

/* The tactics reserve slot under the point, -1 for none: the placement controller's own
 * hit test over its PlacementBar slots (+2C..+30), thiscall (point), RET 4. */
static int placement_reserve_slot(float x, float y)
{
    uint32_t placement = read32(gesture.screen + 0x488), point = logical_point(x, y);
    if (!placement || !point || !void_vm_readable(placement + 0x2C, 8)) return -1;
    return (int)void_call_guest_this(0x005764A0u, placement, 1, &point);
}

/* CCombatSplitStackController is the same controller the original Shift-drop opens. */
static int placement_second(const void_touch_event *event)
{
    if (!gesture.placement || gesture.kind != SCREEN_COMBAT || !same_screen() || gesture.cancelled ||
        read32(gesture.screen + 0x2E0) != 0x1000) return 0;
    uint32_t placement = read32(gesture.screen + 0x488);
    int source_slot = placement_reserve_slot(gesture.start_x, gesture.start_y);
    if (!void_vm_readable(placement, 0xA0) || !MEM8(placement + 0x9C) || source_slot < 0 ||
        source_slot != placement_reserve_slot(gesture.x, gesture.y)) return 0;
    if (event->kind == TOUCH_SECOND_BEGIN) {
        gesture.second_troop = 1;
        return 1;
    }
    if (!gesture.second_troop) return 0;
    int target_slot = placement_reserve_slot(event->x, event->y);
    if (target_slot < 0) return 1;
    uint32_t source_index = (uint32_t)source_slot;
    uint32_t source = void_call_guest_this(0x00576200u, placement, 1, &source_index);
    if (!void_vm_readable(source, 0x24) || read32(source + 8) < 2) return 1;
    uint32_t target = 0;
    if (event->kind == TOUCH_SECOND_TAP) {
        uint32_t begin = read32(placement + 0x2C), end = read32(placement + 0x30);
        if (end < begin || end - begin > 7 * 4 || (end - begin) % 4) return 1;
        target_slot = -1;
        for (uint32_t i = 0; i < (end - begin) / 4; ++i) {
            if (i != source_index && !void_call_guest_this(0x00576200u, placement, 1, &i)) {
                target_slot = (int)i;
                break;
            }
        }
        if (target_slot < 0) return 1;
    } else {
        if (target_slot == source_slot) return 1;
        uint32_t index = (uint32_t)target_slot;
        target = void_call_guest_this(0x00576200u, placement, 1, &index);
        if (target && !void_vm_readable(target, 0x24)) return 1;
    }
    uint32_t source_type = read32(source + 0x1C), target_type = target ? read32(target + 0x1C) : source_type;
    uint32_t count = read32(source + 8), target_count = target ? read32(target + 8) : 0;
    if (source_type != target_type || (uint64_t)count + target_count > INT32_MAX) return 1;
    uint32_t source_creature = void_call_guest_this(0x004DB320u, source, 0, NULL);
    uint32_t target_creature = target ? void_call_guest_this(0x004DB320u, target, 0, NULL) : source_creature;
    if (!source_creature || !target_creature || !same_screen()) return 1;
    uint32_t bytes = 0x50, controller = void_call_guest(0x00878FD0u, 1, &bytes, 0);
    if (!controller) return 1;
    const uint32_t args[] = {placement, source_creature, target_creature, source_type, target_type,
                             count, target_count, source_index, (uint32_t)target_slot, 1};
    void_call_guest_this(0x0057A350u, controller, 10, args);
    void_call_guest_this(0x0063EE50u, placement + 0x80, 1, &controller);
    if (!(object_query(controller, 0xC) & 0xFFu) || !same_screen()) return 1;
    uint32_t one = 1;
    if (event->kind == TOUCH_SECOND_TAP &&
        !(void_call_guest_this(0x0057A1A0u, controller, 1, &one) & 0xFFu)) return 1;
    void_call_guest_this(0x00576260u, placement, 0, NULL);
    gesture.committed = 1;
    gesture.world_hover = gesture.details = 0;
    if (event->kind == TOUCH_SECOND_TAP) {
        void_call_guest_this(0x0057A290u, controller, 1, &one);
        VLOG("[touch] reserve-one from=%d to=%d count=%u", source_slot, target_slot, count);
    } else {
        uint32_t modal = void_call_guest_this(0x00587CF0u, controller, 0, NULL);
        if (modal && same_screen()) {
            gesture.cancelled = 1;
            void_call_guest_this(0x0066D290u, gesture.screen, 1, &modal);
        }
    }
    return 1;
}

/* Combat: a second finger resting while the first one aims asks about what the aiming finger
 * is on, as the right button does (its tooltip, then the details card), and keeps the aim. Its lift
 * hides the card and the aim goes on; the first finger lifted while it rests gives no order, and the
 * card stays until the second one lifts too. */
static void combat_card_toggle(void)
{
    if (same_screen()) gesture.card_mode = card_step(gesture.root, gesture.inspect_x, gesture.inspect_y, gesture.card_mode);
}

static int combat_card_event(int kind)
{
    if (gesture.card && kind == TOUCH_SECOND_TAP) {
        /* A tap (not a resting finger): the card stays until the first finger lifts, without an order. */
        gesture.card_sticky = gesture.committed = 1;
        return 1;
    }
    if (gesture.card && kind == TOUCH_SECOND_BEGIN && gesture.card_sticky) {
        combat_card_toggle();
        return 1;
    }
    if (kind != TOUCH_SECOND_BEGIN) return gesture.card;   /* its tap or hold: nothing more */
    if (gesture.ui || gesture.kind != SCREEN_COMBAT || gesture.placement || gesture.cancelled ||
        gesture.committed || !(gesture.combat_aim || gesture.aiming)) return 0;
    gesture.card = 1;
    gesture.held = gesture.world_hover = gesture.details = 1;
    publish_point(gesture.x, gesture.y);
    world_tooltip();
    /* The card at once, at the point the first finger had (the aim and camera hold still). */
    gesture.inspecting = 1; gesture.inspect_x = gesture.x; gesture.inspect_y = gesture.y;
    gesture.card_mode = 1; gesture.card_frame = touch_frame; gesture.card_retries = 0;
    world_details_request(0);
    VLOG("[touch] combat-card point=%.1f,%.1f", gesture.x, gesture.y);
    return 1;
}

/* The hover ends with the card: while a finger counts as held, the tooltip tracker keeps showing
 * the card (sub_008863A0), so the first finger's own hold information goes too. */
static void combat_card_end(void)
{
    if (!gesture.card) return;
    gesture.card = gesture.details = 0;
    gesture.held = gesture.world_hover = 0;
    gesture.inspecting = gesture.card_sticky = gesture.card_mode = 0;
    if (same_screen()) ui_hover(-1, -1);
}

/* Controller state after a touch step: +38 picked entry, +6C dragging, +9C command mode. */
static void placement_trace(const char *what, float x, float y)
{
    uint32_t placement = read32(gesture.screen + 0x488);
    if (!void_verbose || !void_vm_readable(placement + 0x38, 0x68)) return;
    VLOG("[touch] placement %s point=%.1f,%.1f reserve=%d picked=%d drag=%u commands=%u",
         what, x, y, placement_reserve_slot(x, y), (int)MEM32(placement + 0x38),
         MEM8(placement + 0x6C), MEM8(placement + 0x9C));
}

/* ------------------------------------------------- combat taps and camera */
/* The battle camera as the battle began: its arena camera set has no
 * separate "default position" action, so the first touch of a battle
 * screen records it. */
static struct { uint32_t screen, controller; int valid; float pose[10]; } combat_home;

static void combat_home_capture(void)
{
    if (gesture.kind != SCREEN_COMBAT) return;
    if (combat_home.valid && combat_home.screen == gesture.screen && combat_home.controller == gesture.controller) return;
    combat_home.valid = void_touch_camera_pose(gesture.screen, 1, combat_home.pose, 0, 0);
    combat_home.screen = gesture.screen;
    combat_home.controller = gesture.controller;
}

static void combat_camera_home(void)
{
    if (!combat_home.valid || combat_home.screen != gesture.screen || combat_home.controller != gesture.controller) return;
    float pose[10];
    memcpy(pose, combat_home.pose, sizeof pose);
    /* Not immediate: the operator glides to the restored target. */
    int moved = void_touch_camera_pose(gesture.screen, 1, pose, 1, 0);
    VLOG("[touch] combat-camera-home screen=%08X moved=%d", gesture.screen, moved);
}

static void adventure_camera_home(void)
{
    float pose[10];
    if (!void_vm_readable(0x00F339F4u, 8) ||
        !void_touch_camera_pose(gesture.screen, 0, pose, 0, 0)) return;
    /* The original default-camera action reads these angles; keep the current zoom and anchor. */
    pose[1] = MEMF(0x00F339F4u);
    pose[2] = MEMF(0x00F339F8u);
    void_touch_camera_pose(gesture.screen, 0, pose, 1, 1);
}

static int camera_world(void)
{
    return !gesture.ui && !gesture.aiming && !gesture.placement &&
           (gesture.kind == SCREEN_ADVENTURE || gesture.kind == SCREEN_COMBAT);
}

static void adventure_cancel(void)
{
    if (gesture.kind == SCREEN_ADVENTURE && void_vm_readable(gesture.controller, 0xF0))
        void_call_guest_this(0x00604E20u, gesture.controller, 0, NULL);
}

static void adventure_point(float x, float y, int commit)
{
    uint32_t controller = gesture.controller;
    if (!void_vm_readable(controller, 0xF0) ||
        (void_call_guest_this(0x00603980u, controller, 0, NULL) & 0xFFu)) return;
    uint32_t point = logical_point(x, y);
    if (!point || !same_screen()) return;
    uint32_t pick = scratch + 8;
    memset((void *)ADDR(pick), 0, 32);
    MEM32(pick + 0xC) = 0x000E739Cu;
    uint32_t args[] = {pick, point};
    int picked = void_call_guest_this(0x005913B0u, gesture.screen, 2, args) & 0xFFu;
    if (picked && same_screen() && refresh_target_mode()) {
        if (commit) {
            /* This evaluates context and queues the original CWorldCmd objects. */
            void_call_guest_this(0x00597360u, gesture.screen, 1, &pick);
            VLOG("[touch] adventure-context point=%.1f,%.1f", x, y);
        } else {
            uint32_t action = scratch + 40;
            memset((void *)ADDR(action), 0, 72);
            MEM32(action + 0xC) = 0x000E739Cu;
            MEM8(action + 0x38) = 1;
            const uint32_t evaluate[] = {action, pick, 0};
            void_call_guest_this(0x00600E70u, controller, 3, evaluate);
            void_call_guest_this(0x005A0F40u, action, 0, NULL);
        }
    }
    void_call_guest_this(0x0059F450u, pick, 0, NULL);
}

static uint32_t adventure_borrow(uint32_t cast, uint32_t reference)
{
    uint32_t output = scratch + 400;
    MEM32(output) = 0;
    void_call_guest_this(cast, output, 1, &reference);
    return MEM32(output);
}

static void adventure_double(float x, float y)
{
    MEM8(gesture.screen + 0x5E8) = 1;
    uint32_t controller = gesture.controller;
    if (!void_vm_readable(controller, 0xF0)) return;
    uint32_t allowed = void_call_guest_this(0x00603360u, controller, 0, NULL) & 0xFFu;
    VLOG("[touch] double-begin controller=%08X mode=%X allowed=%u details=%u point=%.1f,%.1f",
         controller, read32(controller + 0x44), allowed, MEM8(gesture.screen + 0x55C), x, y);
    if (!allowed) return;
    uint32_t point = logical_point(x, y), pick = scratch + 8;
    if (!point || !same_screen()) return;
    memset((void *)ADDR(pick), 0, 32);
    MEM32(pick + 0xC) = 0x000E739Cu;
    const uint32_t pick_args[] = {pick, point};
    int picked = void_call_guest_this(0x005913B0u, gesture.screen, 2, pick_args) & 0xFFu;
    VLOG("[touch] double-pick valid=%d world=%.3f,%.3f,%.3f cell=%08X object=%08X secondary=%08X flags=%u,%u",
         picked, MEMF(pick), MEMF(pick + 4), MEMF(pick + 8), read32(pick + 0xC),
         read32(pick + 0x10), read32(pick + 0x14), MEM8(pick + 0x18), MEM8(pick + 0x19));
    if (picked && same_screen()) {
        uint32_t previous_cell = gesture.screen + 0x750;
        if (read32(gesture.screen + 0x760) == 1 &&
            (void_call_guest_this(0x0041A760u, pick + 0xC, 1, &previous_cell) & 0xFFu) &&
            read32(pick + 0x10) == read32(gesture.screen + 0x754) &&
            read32(pick + 0x14) == read32(gesture.screen + 0x758) &&
            MEM8(pick + 0x18) == MEM8(gesture.screen + 0x75C) &&
            MEM8(pick + 0x19) == MEM8(gesture.screen + 0x75D))
            MEM32(gesture.screen + 0x760) = 2;
        uint32_t reference = read32(pick + 0x10);
        if (void_vm_readable(reference, 8) && !(MEM8(reference + 7) & 0x80u)) {
            int ghost = void_call_guest_this(0x00603560u, controller, 0, NULL) & 0xFFu;
            uint32_t object = adventure_borrow(ghost ? 0x0059EB60u : 0x0059EAC0u, pick + 0x10);
            VLOG("[touch] double-cast ghost=%d picked=%08X cast=%08X", ghost, reference, object);
            if (!object && !ghost) {
                uint32_t ship = adventure_borrow(0x0059EAF0u, pick + 0x10);
                uint32_t passenger = object_query(ship, 0);
                if (passenger) object = adventure_borrow(0x0059EB20u, passenger);
                VLOG("[touch] double-ship ship=%08X passenger=%08X hero=%08X", ship, passenger, object);
            }
            if (object) {
                uint32_t selected = void_call_guest_this(ghost ? 0x006038A0u : 0x00603860u,
                                                        controller, 0, NULL);
                g_edx = object;
                int same = void_call_guest_this(0x00433CF0u, selected, 0, NULL) & 0xFFu;
                uint32_t identity = object_query(ghost ? object : virtual_base(object, 0xC), 0);
                if (ghost) identity = object_query(identity, 4);
                uint32_t owner_method = object_method(identity, 0x2C);
                VLOG("[touch] double-selection selected=%08X selected-base=%08X object=%08X object-base=%08X same=%d identity=%08X owner-method=%08X",
                     selected, virtual_base(selected, 4), object, virtual_base(object, 4), same, identity, owner_method);
                if (same && owner_method) {
                    uint32_t owner = void_call_guest_this(owner_method, identity, 0, NULL);
                    uint32_t is_own = void_call_guest_this(0x00603580u, controller, 1, &owner) & 0xFFu;
                    VLOG("[touch] double-owner id=%u owned=%u", owner, is_own);
                    if (is_own) {
                        if (ghost) void_call_guest_this(0x00594E60u, gesture.screen, 1, &object);
                        else {
                            uint32_t blocked = void_call_guest_this(0x00603980u, controller, 0, NULL) & 0xFFu;
                            if (!blocked) MEM8(gesture.screen + 0x55C) = 1;
                            VLOG("[touch] double-details busy=%u flag=%u", blocked, MEM8(gesture.screen + 0x55C));
                        }
                    }
                }
            }
        }
        reference = read32(pick + 0x14);
        if (same_screen() && void_vm_readable(reference, 8) && !(MEM8(reference + 7) & 0x80u)) {
            uint32_t town = adventure_borrow(0x00433F40u, pick + 0x14);
            uint32_t cell = scratch + 404, location = object_method(town, 0xC4);
            if (town && location && !(void_call_guest_this(0x00603980u, controller, 0, NULL) & 0xFFu)) {
                void_call_guest_this(location, town, 1, &cell);
                uint32_t owner_method = object_method(town, 0xBC);
                if (owner_method && !(void_call_guest_this(0x00603560u, controller, 0, NULL) & 0xFFu)) {
                    uint32_t owner = void_call_guest_this(owner_method, town, 0, NULL);
                    if ((void_call_guest_this(0x006035A0u, controller, 1, &owner) & 0xFFu) && !MEM8(pick + 0x19)) {
                        uint32_t player = void_call_guest_this(0x0058D5C0u, gesture.screen, 0, NULL);
                        uint32_t fog_method = object_method(player, 0x19C), layer = read32(gesture.screen + 0xB4);
                        uint32_t fog = fog_method ? void_call_guest_this(fog_method, player, 1, &layer) : 0;
                        uint32_t packed = MEM32(cell), rows = read32(fog + 0x20);
                        uint32_t row = read32(rows + 4 * ((packed >> 10) & 0x3FFu));
                        uint32_t visible = row + (packed & 0x3FFu);
                        if (row && void_vm_readable(visible, 1) && MEM8(visible)) {
                            if (void_call_guest_this(0x00603580u, controller, 1, &owner) & 0xFFu)
                                void_call_guest_this(0x00604470u, controller, 1, &town);
                            void_call_guest_this(0x006047F0u, controller, 1, &town);
                        }
                    }
                }
            }
        }
    }
    void_call_guest_this(0x0059F450u, pick, 0, NULL);
    VLOG("[touch] adventure-double point=%.1f,%.1f", x, y);
}

void void_touch_engine_init(void)
{
#ifdef VOID_ANDROID_APP
    if (!original_game_message) {
        original_game_message = void_dispatch_find(0x00B29970u);
        if (original_game_message) void_dispatch_add(0x00B29970u, port_game_message);
        original_exit_confirm = void_dispatch_find(0x006895E0u);
        if (original_exit_confirm) void_dispatch_add(0x006895E0u, port_exit_confirm);
    }
#endif
    memset(&gesture, 0, sizeof gesture);
    memset(&text_target, 0, sizeof text_target);
    memset(&drag_owner, 0, sizeof drag_owner);
    memset(&combat_home, 0, sizeof combat_home);
    memset(&army_batch, 0, sizeof army_batch);
    memset(&atb, 0, sizeof atb);
    memset(&choice, 0, sizeof choice);
    memset(&minimap_tap, 0, sizeof minimap_tap);
    if (!original_choice_update) {
        original_choice_update = void_dispatch_find(0x007148E0u);
        if (original_choice_update) void_dispatch_add(0x007148E0u, choice_update);
    }
    touch_mode = 0;
    cursor_started_ns = void_perf_now_ns();
    if (!original_cursor) {
        original_cursor = void_dispatch_find(0x00835C90u);
        if (original_cursor) void_dispatch_add(0x00835C90u, touch_cursor_query);
    }
    if (!original_cursor_draw) {
        original_cursor_draw = void_dispatch_find(0x00836440u);
        if (original_cursor_draw) void_dispatch_add(0x00836440u, touch_cursor_draw);
    }
    void_touch_camera_init();
}

int void_touch_active_mode(void) { return touch_mode; }

/* One finger on the battlefield is the mouse cursor of the original: it
 * previews the order where it rests and gives it where it is released. */
static int combat_world(void)
{
    return gesture.kind == SCREEN_COMBAT && !gesture.ui && !gesture.placement && !gesture.aiming;
}

static float cursor_axis(float point, int dimension, float offset)
{
    if (dimension <= 1) return 0;
    float last = (float)(dimension - 1);
    point = fminf(last, fmaxf(0, point));
    float distance = fminf(last * .25f, fmaxf(-last * .25f, offset));
    if (distance == 0) return point;
    /* Smoothly recover both edges; slope stays >= .25, so no input band is lost. */
    float t = fminf(1, fminf(point, last - point) / (2 * fabsf(distance)));
    return point + distance * t * t * (3 - 2 * t);
}

void void_touch_engine_event(const void_touch_event *event)
{
    if (!event || !isfinite(event->x) || !isfinite(event->y) ||
        !isfinite(event->dx) || !isfinite(event->dy) || !isfinite(event->scale) ||
        !isfinite(event->rotation)) return;
    void_touch_event shifted = *event;
    if (event->kind != TOUCH_ABORT && event->kind != TOUCH_POINTER && event->kind != TOUCH_POINTER_CLICK &&
        event->kind != TOUCH_PAD_CAMERA && event->kind != TOUCH_TRANSFORM && event->kind != TOUCH_TILT &&
        event->kind != TOUCH_THREE_FINGER_TAP && event->kind != TOUCH_TWO_FINGER_TAP &&
        event->kind != TOUCH_TWO_FINGER_BEGIN && event->kind != TOUCH_TWO_FINGER_CANCEL && event->x >= 0 && event->y >= 0) {
        float ox = void_port_cursor_offset(0), oy = void_port_cursor_offset(1);
        if (ox != 0 || oy != 0) {
            int width, height; void_input_screen_size(&width, &height);
            if (width <= 0 || height <= 0) return;
            float side = (float)(width < height ? width : height);
            shifted.x = cursor_axis(event->x, width, ox * side);
            shifted.y = cursor_axis(event->y, height, oy * side);
        }
    }
    /* A touch on the selected initiative portrait keeps its card's point: the card holds still. */
    if (gesture.active && gesture.atb && event->kind != TOUCH_BEGIN && event->x >= 0 && event->y >= 0) {
        shifted.x = atb.x; shifted.y = atb.y;
    }
    event = &shifted;
    if (event->kind == TOUCH_POINTER_CLICK) {
        pointer_text.screen = current_screen();
        pointer_text.x = event->x; pointer_text.y = event->y;
        pointer_text.frame = touch_frame; pointer_text.pending = 1;
        return;
    }
    if (event->kind == TOUCH_POINTER) {
        void_touch_event abort = {TOUCH_ABORT, 0, 0, 0, 0, 1, 0};
        void_touch_engine_event(&abort);
        atb_clear();   /* the mouse owns the cursor again */
        memset(&minimap_tap, 0, sizeof minimap_tap);
        touch_mode = 0;
        return;
    }
    if (event->kind == TOUCH_PAD_CAMERA) {
        uint32_t screen = current_screen();
        int kind = screen_kind(screen);
        if (kind == SCREEN_MENU) return;
        int camera = kind == SCREEN_TOWN ? 2 : kind == SCREEN_COMBAT ? 1 : 0;
        int w, h; void_input_screen_size(&w, &h);
        if (event->rotation != 0)
            void_touch_camera(screen, camera, w * .5f, h * .5f, 0, 0, 1, event->rotation);
        if (event->dy != 0) {
            if (camera == 1) void_touch_camera(screen, camera, w * .5f, h * .5f, 0, event->dy * h, 1, 0);
            else void_touch_camera_tilt(screen, camera, event->dy * h);
        }
        return;
    }
    if (event->kind==TOUCH_ABORT) {
        choice_clear();
        memset(&army_batch,0,sizeof army_batch);
    }
    if (event->kind == TOUCH_BEGIN) {
        pointer_text.pending = 0;
        memset(&army_batch,0,sizeof army_batch);
        dnd_owner_pump(0);
        if (gesture.active && gesture.dnd_pressed) dnd_cancel();
        if (gesture.active && gesture.ui && same_screen()) ui_release(1);
        memset(&gesture, 0, sizeof gesture);
        gesture.begin_frame = touch_frame;
        gesture.screen = current_screen();
        if (!gesture.screen) return;
        gesture.kind = screen_kind(gesture.screen);
        /* A later battle may reuse the screen's address: forget the old home. */
        if (gesture.kind != SCREEN_COMBAT) combat_home.valid = 0;
        gesture.book = spellbook_kind(gesture.screen);
        gesture.start_x = gesture.x = event->x;
        gesture.start_y = gesture.y = event->y;
        gesture.root = read32(gesture.screen + 0xA0);
        if (!gesture.root || !ui_method(gesture.screen, 0x28)) return;
        gesture.controller = (gesture.kind == SCREEN_MENU || gesture.kind == SCREEN_TOWN) ? 0 :
                             read32(gesture.screen + (gesture.kind == SCREEN_ADVENTURE ? 0x5F4 : 0x2B4));
        if (atb_begin(event->x, event->y)) {
            /* Beside the open card: the touch closes it and does nothing else. */
            gesture.active = gesture.committed = gesture.cancelled = 1;
            touch_mode = 1;
            publish_point(-1, -1);
            return;
        }
        if (gesture.atb) {
            shifted.x = gesture.start_x = gesture.x = atb.x;
            shifted.y = gesture.start_y = gesture.y = atb.y;
        }
        /* A waiting minimap tap is clicked before a touch anywhere but the minimap. */
        if (minimap_tap.due && (gesture.kind != SCREEN_ADVENTURE || !minimap_at(event->x, event->y))) minimap_click();
        gesture.announcement = adventure_announcement(event->x, event->y, 0);
        gesture.ui = gesture.announcement || gesture.kind == SCREEN_MENU ||
                     ui_pick(gesture.screen, event->x, event->y) != 0;
        uint32_t helper = read32(gesture.screen + 0x150);
        if (read32(helper) == 0x00E47794u && ui_idle()) {
            gesture.dnd_claim = dnd_claim_at(helper, event->x, event->y);
            if (gesture.dnd_claim || dnd_held(helper)) gesture.dnd = helper;
            if (gesture.dnd_claim) gesture.ui = 1;
        }
        gesture.ghost_energy = ghost_owned_point(event->x, event->y, 1);
        troop_cell portrait;
        gesture.army_portrait=troop_portrait_at(event->x,event->y,&portrait);
        if (!same_screen()) { publish_point(-1, -1); return; }
        gesture.aiming = !gesture.ui && target_armed();
        gesture.placement = !gesture.ui && gesture.kind == SCREEN_COMBAT &&
                            read32(gesture.screen + 0x2E0) == 0x1000;
        /* The tactics reserve (CombatArena PlacementBar) is interface, yet the original hands
           every arena press to the placement controller, which tests the reserve slots itself:
           a stack is picked up from there, not clicked as a button. */
        if (gesture.ui && !gesture.announcement && !gesture.dnd_claim && gesture.kind == SCREEN_COMBAT &&
            read32(gesture.screen + 0x2E0) == 0x1000 && placement_reserve_slot(event->x, event->y) >= 0) {
            gesture.ui = 0;
            gesture.placement = 1;
        }
        if (gesture.placement) gesture.aiming = 1;
        gesture.active = 1;
        if (!publish_point(event->x, event->y)) { gesture.active = 0; return; }
        touch_mode = 1;
        if (!gesture.ui) void_touch_text_cancel();
        VLOG("[touch] begin screen=%08X kind=%d ui=%d aim=%d point=%.1f,%.1f",
             gesture.screen, gesture.kind, gesture.ui, gesture.aiming, event->x, event->y);
        if (gesture.ui) ui_event(event);
        else if (gesture.placement) placement_point(event->x, event->y, 0);
        else if (gesture.aiming) {
            if (gesture.kind == SCREEN_ADVENTURE) adventure_point(event->x, event->y, 0);
            else combat_point(event->x, event->y, 0);
        } else if (gesture.kind == SCREEN_COMBAT) {
            combat_home_capture();
            gesture.combat_aim = 1;
            combat_point(event->x, event->y, 0);
            /* Pressed on the acting stack (+2F4 under the cursor, +2AC acting) that can shoot (+1E0). */
            uint32_t acting = read32(gesture.screen + 0x2AC), shoots = acting ? object_method(acting, 0x1E0) : 0;
            gesture.melee = acting && read32(gesture.screen + 0x2F4) == acting && shoots &&
                            (void_call_guest_this(shoots, acting, 0, NULL) & 0xFFu);
        }
        if (gesture.placement) placement_trace("down", event->x, event->y);
        return;
    }
    if (!gesture.active) {
        if (event->kind == TOUCH_ABORT) dnd_owner_pump(1);
        if (event->kind == TOUCH_ABORT && gesture.retiring) {
            if (same_screen()) ui_hover(-1, -1);
            gesture.retiring = 0;
            publish_point(-1, -1);
        }
        return;
    }
    int kind = event->kind;
    if (gesture.card && (kind == TOUCH_TWO_FINGER_BEGIN || kind == TOUCH_TRANSFORM || kind == TOUCH_TILT ||
                         kind == TOUCH_TWO_FINGER_CANCEL || kind == TOUCH_TWO_FINGER_TAP)) {
        /* The card holds the view still: a drifting second finger is no camera gesture. */
        gesture.committed = 1;
        return;
    }
    /* A tapped card ends with the first finger, which Java reports as a tap once the second finger
       cancelled its hold: no order (TOUCH_END follows and hides the card). */
    if (gesture.card_sticky && (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP)) return;
    if (kind == TOUCH_TWO_FINGER_TAP) {
        /* On the map it cancels the aim or stops the hero; on the minimap it toggles the object highlight
           (the map's own two-finger taps were too often a camera gesture's start). */
        if (gesture.kind == SCREEN_ADVENTURE && same_screen() && (!gesture.ui || minimap_at(gesture.start_x, gesture.start_y))) {
            if (gesture.ui) alt_latch(alt_screen ? 0 : gesture.screen);
            else if (gesture.aiming && !gesture.cancelled) adventure_cancel();
            else adventure_stop();
            gesture.committed = gesture.cancelled = 1;
            publish_point(-1, -1);
            return;
        }
        kind = TOUCH_TWO_FINGER_CANCEL;   /* elsewhere it is the resting pair it always was */
    }
    /* Fingers added on the selected portrait's open card change nothing (its taps switch it). */
    if (gesture.atb && atb.card && (kind == TOUCH_SECOND_BEGIN || kind == TOUCH_SECOND_TAP || kind == TOUCH_SECOND_HOLD)) return;
    if (kind == TOUCH_THREE_FINGER_TAP) {
        if (same_screen() && camera_world() && !gesture.cancelled) {
            if (gesture.kind == SCREEN_ADVENTURE) adventure_camera_home();
            else combat_camera_home();
        }
        /* A chord over UI or a targeting mode is consumed, never a click. */
        if (gesture.ui && same_screen()) {
            void_touch_event abort = {TOUCH_ABORT, 0, 0, 0, 0, 1, 0};
            ui_event(&abort);
        }
        gesture.committed = gesture.cancelled = 1;
        gesture.combat_aim = 0;
        publish_point(-1, -1);
        return;
    }
    if (kind == TOUCH_SECOND_BEGIN || kind == TOUCH_SECOND_TAP || kind == TOUCH_SECOND_HOLD) {
        if (placement_second(event)) return;
        if (same_screen() && combat_card_event(kind)) return;
        if (!same_screen()) {
            gesture.active = 0;
            publish_point(-1, -1);
            return;
        }
        troop_second(event);
        if (!gesture.ui && kind == TOUCH_SECOND_BEGIN && (gesture.aiming || gesture.combat_aim) && !gesture.cancelled) {
            if (gesture.kind == SCREEN_ADVENTURE) adventure_cancel();
            else if (gesture.kind == SCREEN_COMBAT) combat_cancel();
            gesture.cancelled = 1; publish_point(-1, -1);
        }
        return;
    }
    if (kind == TOUCH_FIRST_END) {
        /* The first finger lifted while the second rests. Under a combat card: no order, the card
           stays with the resting finger; any other gesture ends here, as it always did. */
        if (gesture.card) { gesture.card = 2; return; }
        void_touch_event abort = {TOUCH_ABORT, 0, 0, 0, 0, 1, 0};
        void_touch_engine_event(&abort);
        return;
    }
    if (kind == TOUCH_SECOND_END) {
        int released = gesture.card == 2;
        if (gesture.card_sticky && !released) return;   /* a tapped card stays with the first finger */
        combat_card_end();
        if (released) {
            /* Both fingers are up and no order was given: the gesture is over (its ABORT follows). */
            if (gesture.world_hover && same_screen()) ui_hover(-1, -1);
            gesture.world_hover = 0;
            gesture.active = 0;
            if (!gesture.retiring && !drag_owner.helper) publish_point(-1, -1);
        }
        return;
    }
    gesture.x = event->x; gesture.y = event->y;
    /* A camera gesture on the battlefield has no cursor under it. */
    if (!gesture.ui && gesture.kind == SCREEN_COMBAT && gesture.panning) publish_point(-1, -1);
    else publish_point(event->x, event->y);
    if (!same_screen()) {
        gesture.active = 0;
        publish_point(-1, -1);
        return;
    }
    if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP)
        VLOG("[touch] intent=%s screen=%08X kind=%d ui=%d aim=%d point=%.1f,%.1f",
             kind == TOUCH_DOUBLE_TAP ? "double" : "tap",
             gesture.screen, gesture.kind, gesture.ui, gesture.aiming, event->x, event->y);
    refresh_target_mode();
    if (kind == TOUCH_ABORT) {
        ctrl_latch(0);
        combat_card_end();
        if (gesture.ui) ui_event(event);
        else if (gesture.aiming && !gesture.cancelled) {
            if (gesture.kind == SCREEN_ADVENTURE) adventure_cancel();
            else if (gesture.kind == SCREEN_COMBAT) combat_cancel();
        }
        dnd_owner_pump(1);
        gesture.active = 0;
        publish_point(-1, -1);
        return;
    }
    /* The resting finger moved: a camera gesture, with no information under it. */
    if (kind == TOUCH_TWO_FINGER_BEGIN) combat_card_end();
    if (kind == TOUCH_TWO_FINGER_BEGIN && !gesture.ui && gesture.combat_aim && !gesture.aiming) {
        /* Two fingers on the battlefield move the camera: no order at release. */
        gesture.combat_aim = 0;
        gesture.panning = 1;
        publish_point(-1, -1);
    }
    if (kind == TOUCH_TWO_FINGER_BEGIN && gesture.aiming && !gesture.cancelled) {
        if (gesture.kind == SCREEN_ADVENTURE) adventure_cancel();
            else if (gesture.kind == SCREEN_COMBAT) combat_cancel();
        gesture.cancelled = 1;
        publish_point(-1, -1);
    }
    if (gesture.cancelled) {
        publish_point(-1, -1);
        if (kind == TOUCH_END) gesture.active = 0;
        return;
    }
    if (gesture.ui) {
        ui_event(event);
        /* A held combat control (initiative bar, portraits) shows its details too; not a drag source. */
        if (kind == TOUCH_HOLD_BEGIN && gesture.kind == SCREEN_COMBAT && gesture.held && !gesture.dnd && !gesture.combo &&
            !(gesture.atb && atb.card) &&   /* a held open card stays as it is */
            !gesture.placement && same_screen()) gesture.details = 1;
    } else if (kind == TOUCH_TWO_FINGER_CANCEL) {
        if (gesture.kind == SCREEN_ADVENTURE) adventure_cancel();
            else if (gesture.kind == SCREEN_COMBAT) combat_cancel();
        gesture.cancelled = 1;
        gesture.combat_aim = 0;
        publish_point(-1, -1);
    } else if (kind == TOUCH_TILT) {
        gesture.panning = 1;
        void_touch_camera_tilt(gesture.screen,
                               gesture.kind == SCREEN_TOWN ? 2 : gesture.kind == SCREEN_COMBAT,
                               event->dy);
    } else if (kind == TOUCH_PAN && combat_world()) {
        gesture.combat_aim = 1;
        if (gesture.melee) ctrl_latch(1);   /* dragged off the shooter: its melee attack, as Ctrl+click */
        combat_point(event->x, event->y, 0);
    } else if (kind == TOUCH_PAN || kind == TOUCH_TRANSFORM) {
        if (gesture.placement) placement_point(event->x, event->y, 1);
        else if (gesture.aiming) {
            if (gesture.kind == SCREEN_ADVENTURE) adventure_point(event->x, event->y, 0);
            else combat_point(event->x, event->y, 0);
        }
        else {
            if (!gesture.panning) VLOG("[touch] camera screen=%08X kind=%d", gesture.screen, gesture.kind);
            gesture.panning = 1;
            gesture.combat_aim = 0;
            void_touch_camera(gesture.screen, gesture.kind == SCREEN_TOWN ? 2 : gesture.kind == SCREEN_COMBAT,
                              event->x, event->y, event->dx, event->dy, event->scale, event->rotation);
        }
    } else if (kind == TOUCH_HOLD_BEGIN) {
        if (gesture.kind == SCREEN_COMBAT) {
            /* The right-click info of the creature under the finger; the
               release still gives the order (a second finger cancels it). */
            gesture.held = gesture.world_hover = 1;
            world_tooltip();
        } else if (gesture.aiming) {
            if (gesture.kind == SCREEN_ADVENTURE) adventure_cancel();
            gesture.cancelled = 1;
            publish_point(-1, -1);
        } else {
            /* Map and town objects: their information while held, no action. */
            gesture.held = gesture.info = gesture.world_hover = 1;
            world_tooltip();
            gesture.details = 1;
        }
    } else if (kind == TOUCH_HOLD_DRAG) {
        if (gesture.placement) placement_point(event->x, event->y, 1);
        else if (gesture.combat_aim || (gesture.aiming && gesture.kind == SCREEN_COMBAT)) combat_point(event->x, event->y, 0);
        else if (gesture.aiming && gesture.kind == SCREEN_ADVENTURE) adventure_point(event->x, event->y, 0);
    } else if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP ||
               (kind == TOUCH_END && (gesture.aiming || gesture.combat_aim) && !gesture.committed)) {
        /* A panel appearing after DOWN still owns the point at release. */
        if (adventure_announcement(event->x, event->y, 0)) {
            if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP)
                adventure_announcement(event->x, event->y, 1);
            gesture.committed = 1;
        } else if (!ui_pick(gesture.screen, event->x, event->y)) {
            if (gesture.placement) placement_point(event->x, event->y, 2);
            else if (gesture.kind == SCREEN_ADVENTURE) {
                /* The second tap still commits the native map action (preview -> move). */
                adventure_point(event->x, event->y, 1);
                if (kind == TOUCH_DOUBLE_TAP && same_screen() && !gesture.aiming)
                    adventure_double(event->x, event->y);
            }
            else if (gesture.kind == SCREEN_COMBAT) {
                if (kind != TOUCH_DOUBLE_TAP || !combat_double(event->x, event->y))
                    combat_point(event->x, event->y, 1);
            } else if (gesture.kind == SCREEN_TOWN) town_activate(event->x, event->y);
            if (gesture.placement) placement_trace("drop", event->x, event->y);
            gesture.committed = 1;
        } else if (gesture.placement) {
            uint32_t placement = read32(gesture.screen + 0x488);
            /* Released over the reserve: the original drops there as well, into that slot. */
            if (placement_reserve_slot(event->x, event->y) >= 0) {
                placement_point(event->x, event->y, 2);
                placement_trace("drop-reserve", event->x, event->y);
            } else
            if (placement) void_call_guest_this(0x00576260u, placement, 0, NULL);
            gesture.cancelled = 1;
        }
    }
    if (kind == TOUCH_END) {
        ctrl_latch(0);
        combat_card_end();
        if (gesture.world_hover && same_screen()) ui_hover(-1, -1);   /* the information leaves with the finger */
        gesture.world_hover = 0;
        gesture.active = 0;
        if (!gesture.retiring && !drag_owner.helper) publish_point(-1, -1);
    }
}
