/* Touch intent enters below DirectInput: UI owns its windows, the map owns orders. */
#include "host.h"
#include "touch.h"
#include "input.h"
#include <math.h>
#include <string.h>

enum { SCREEN_MENU, SCREEN_ADVENTURE, SCREEN_COMBAT, SCREEN_TOWN };
typedef struct {
    uint32_t screen, root, controller, dnd;
    int kind, active, ui, book, announcement, aiming, committed, cancelled, held, pressed, placement, panning, retiring;
    uint64_t release_frame, begin_frame;
    float start_x, start_y, x, y;
    int dnd_claim, dnd_pressed, ghost_energy, second_troop, army_portrait;
    /* info: a held finger shows the world tooltip (the right-click info) and
     * gives no order; world_hover: the held finger hovers the world for it;
     * combat_aim: one finger in combat is the cursor, released into an order. */
    int info, world_hover, combat_aim, second_info, inspecting;
    float inspect_x, inspect_y;
} touch_gesture;
static touch_gesture gesture;
static uint32_t scratch;
static int touch_mode;
static uint64_t cursor_started_ns;
static struct { uint32_t screen; float x, y; uint64_t frame; int pending; } pointer_text;
static void_fn original_cursor;
static void_fn original_cursor_draw;
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
static void_fn original_game_message, original_exit_confirm;
static int launcher_pending, launcher_question_seen;

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
    void_regs_load(&saved);
    if (gamepad) {
        void_android_gamepad_help();
        g_eax = (g_eax & ~255u) | 1u;
        g_esp += 16;
        return;
    }
    if (!launcher) { original_game_message(); return; }
    uint32_t screen = current_screen(), table = read32(screen), zero = 0;
    if (table == 0x00E3112Cu) {
        launcher_pending = 1;
        void_call_guest_this(0x006895E0u, screen + 0x174, 1, &zero);
    } else if (table == 0x00E3DA1Cu && read32(screen + 0x1A0) == 2) {
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
    launcher_pending = launcher_question_seen = 0;
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
    if (table == 0x00E3112Cu) {
        uint32_t root = read32(screen + 0xA0);
        uint32_t begin = root >= 0xF8 ? read32(root - 0xF8 + 0xA4) : 0;
        uint32_t end = root >= 0xF8 ? read32(root - 0xF8 + 0xA8) : 0;
        if (begin && end > begin && (end - begin) % 4 == 0 && end - begin <= 4096 && void_vm_readable(begin, end - begin)) {
            uint32_t box = 0;
            for (uint32_t at = begin; at < end; at += 4)
                if (read32(MEM32(at)) == 0x00E3091Cu) box = MEM32(at);
            for (uint32_t at = begin; box && at < end; at += 4) {
                uint32_t window = MEM32(at), getter = read32(read32(window) + 8);
                if (!void_dispatch_find(getter)) continue;
                uint32_t placement = void_call_guest_this(getter, window, 0, NULL);
                uint32_t name = read32(placement + 0x58);
                if (read32(placement + 0x5C) - name != 16 || !void_vm_readable(name, 16) ||
                    memcmp(GPTR(name), "PortExitLauncher", 16) || !void_vm_readable(placement + 0x70, 1) ||
                    !MEM8(placement + 0x70)) continue;
                uint32_t vb = read32(window + 0x10), parent_vb = read32(box + 0x10);
                uint32_t interface = vb ? window + 0x10 + read32(vb + 8) : 0;
                uint32_t parent = parent_vb ? box + 0x10 + read32(parent_vb + 8) : 0;
                uint32_t setter = read32(read32(interface) + 0x44), zero = 0;
                if (!interface || !parent || !void_dispatch_find(setter) || !void_dispatch_find(0x00A4D570u)) break;
                /* Clone into the modal box so its own hit testing and lifetime own the button. */
                g_ecx = parent; g_edx = interface;
                if (void_call_guest(0x00A4D570u, 0, NULL, 1))
                    void_call_guest_this(setter, interface, 1, &zero);
                break;
            }
        }
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

static void touch_cursor_draw(void)
{
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

static int tooltip_held(void)
{
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
    uint32_t point = logical_point(outside ? -1.0f : gesture.x, outside ? -1.0f : gesture.y);
    if (gesture.pressed && point) ui_point_call(gesture.screen, 0x1C, point, 1);
    gesture.pressed = gesture.held = 0;
    if (same_screen()) ui_hover(-1.0f, -1.0f);
}

static void spellbook_activate(float x, float y)
{
    if (!gesture.book || !same_screen() || spellbook_kind(gesture.screen) != gesture.book) return;
    uint32_t picker = gesture.book == 1 ? 0x00683450u : 0x0067BAB0u;
    unsigned vector = gesture.book == 1 ? 0x1B4 : 0x1A8;
    unsigned stride = gesture.book == 1 ? 36 : 40;
    unsigned scene = gesture.book == 1 ? 0x1CC : 0x1C0;
    unsigned closing = gesture.book == 1 ? 0x1ED : 0x1D4;
    if (!void_vm_readable(gesture.screen, closing + 1) || MEM8(gesture.screen + closing) ||
        !void_vm_readable(read32(gesture.screen + scene), 4) ||
        !void_dispatch_find(picker) || !void_dispatch_find(0x00493ED0u)) return;
    uint32_t point = logical_point(x, y);
    if (!point) return;
    /* The book's icons/tabs are mesh parts, resolved by its own camera and scene. */
    const uint32_t args[] = {point, 0, 0, 1};
    uint32_t descriptor = void_call_guest_this(picker, gesture.screen, 4, args);
    if (!same_screen() || spellbook_kind(gesture.screen) != gesture.book || MEM8(gesture.screen + closing)) return;
    uint32_t begin = read32(gesture.screen + vector), end = read32(gesture.screen + vector + 4);
    if (!begin || end < begin || (end - begin) % stride || descriptor < begin ||
        (uint64_t)descriptor + stride > end || (descriptor - begin) % stride ||
        !void_vm_readable(descriptor, stride)) return;
    uint32_t text = read32(descriptor + 4), text_end = read32(descriptor + 8);
    if (!text || text_end <= text || text_end - text > 128 || !void_vm_readable(text, text_end - text)) return;
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

static int dnd_claim_at(uint32_t helper, float x, float y)
{
    if (!dnd_identity(helper) || !ui_idle() || !void_dispatch_find(0x00813DE0u)) return 0;
    uint32_t point = logical_point(x, y);
    if (!point) return 0;
    const uint32_t args[] = {point, 1}; /* Geometry/visibility probe; never the pickup probe. */
    uint32_t slot = void_call_guest_this(0x00813DE0u, helper, 2, args);
    if (!dnd_identity(helper) || !ui_idle()) return 0;
    uint32_t hit = ui_pick(gesture.screen, x, y);
    if (!slot) return dnd_held(helper) && !hit;
    uint32_t map = read32(slot + 0x10), method = object_method(map, 0x24);
    point = logical_point(x, y);
    uint32_t window = method && point ? void_call_guest_this(method, map, 1, &point) : 0;
    return window && dnd_identity(helper) && ui_idle() && window_contains(hit, window);
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

static int troop_cell_window(uint32_t window, troop_cell *cell)
{
    uint32_t screen=gesture.screen;
    if (!window || !same_screen() || !ui_idle()) return 0;
    memset(cell,0,sizeof *cell);
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
    uint32_t point=logical_point(x,y);const uint32_t args[]={point,1};
    uint32_t slot=point?void_call_guest_this(0x00813DE0u,helper,2,args):0;
    uint32_t map=read32(slot+0x10),pick=object_method(map,0x24);
    point=logical_point(x,y);
    uint32_t window=point&&pick?void_call_guest_this(pick,map,1,&point):0;
    /* A modal/overlay gets first refusal even over a registered native slot. */
    if (!window || !dnd_identity(helper) || !window_contains(ui_pick(gesture.screen,x,y),window)) return 0;
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
        gesture.second_info = !gesture.second_troop && gesture.held &&
                              object_method(gesture.root, 0x70) && tooltip_target_at(event->x,event->y);
        if (!gesture.second_troop && !gesture.second_info && gesture.ui) {dnd_cancel();ui_release(1);gesture.panning=1;}
    } else if (gesture.second_troop) troop_split(event->x,event->y,event->kind==TOUCH_SECOND_HOLD);
    else if (gesture.second_info && gesture.held && same_screen()) {
        uint32_t point=logical_point(gesture.x,gesture.y),method=object_method(gesture.root,0x70);
        if (point && method && tooltip_target_at(event->x,event->y) && same_screen()) {
            point=logical_point(gesture.x,gesture.y);
            const uint32_t args[]={point,1};
            /* 487A80 -> 8867D0 repicks the source before asking its tooltip provider
               for details. Keep the held source point; the second finger only triggers it. */
            publish_point(gesture.x,gesture.y);
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

static void ui_event(const void_touch_event *event)
{
    gesture.x = event->x; gesture.y = event->y;
    switch (event->kind) {
    case TOUCH_BEGIN:
        ui_hover(event->x, event->y);
        break;
    case TOUCH_TAP:
    case TOUCH_DOUBLE_TAP: {
        if (gesture.committed || gesture.held || gesture.panning) break;
        int consumed = adventure_announcement(event->x, event->y, 1);
        if (consumed || gesture.announcement) {
            gesture.committed = 1;
            break;
        }
        if (!same_screen()) break;
        if (gesture.dnd && !gesture.dnd_claim) { dnd_cancel(); if (!same_screen()) break; }
        uint32_t point = logical_point(event->x, event->y);
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

/* Battlefield taps waiting out the multi-tap window (see combat_taps_event). */
static struct {
    int count, awaiting;
    uint32_t screen, root, controller;
    float x, y;
    uint64_t due;
} combat_taps;
static void combat_taps_commit(void);

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
    if (combat_taps.count && !combat_taps.awaiting && void_perf_now_ns() >= combat_taps.due) combat_taps_commit();
    dnd_owner_pump(0);
    troop_preview_pump();
    if (gesture.retiring) {
        int current = same_screen();
        if (!current || touch_frame != gesture.release_frame) {
            if (current) ui_hover(-1, -1);
            if (!drag_owner.helper) publish_point(-1, -1);
            gesture.retiring = 0;
        }
    }
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
    } else {
        uint32_t player = void_call_guest_this(0x00669430u, gesture.screen, 0, NULL);
        const uint32_t args[] = {point, pick + 0x10, player};
        void_call_guest_this(phase == 0 ? 0x005779D0u : 0x00577DC0u, placement, 3, args);
    }
    void_call_guest_this(0x0054E030u, pick, 0, NULL);
}

/* ------------------------------------------------- combat taps and camera */
/* A triple tap returns the battle camera home. Taps on the battlefield are
 * orders, so a battlefield tap waits out the multi-tap window first: one tap
 * then commits as before, two run the original double-click shortcut, three
 * only reset the camera. Spell targeting and placement are never delayed. */
#define MULTI_TAP_NS 340000000ull          /* GameActivity's 300 ms window and the event latency */

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

static void combat_taps_commit(void)
{
    if (!combat_taps.count) return;
    int count = combat_taps.count;
    float x = combat_taps.x, y = combat_taps.y;
    uint32_t screen = combat_taps.screen, root = combat_taps.root, controller = combat_taps.controller;
    memset(&combat_taps, 0, sizeof combat_taps);
    touch_gesture saved = gesture;
    memset(&gesture, 0, sizeof gesture);
    gesture.screen = screen; gesture.root = root; gesture.controller = controller;
    gesture.kind = SCREEN_COMBAT; gesture.active = 1;
    if (same_screen() && !target_armed() && !ui_pick(screen, x, y) && same_screen()) {
        VLOG("[touch] combat-tap-commit count=%d point=%.1f,%.1f", count, x, y);
        if (count < 2 || !combat_double(x, y)) combat_point(x, y, 1);
    }
    gesture = saved;
}

/* A battlefield tap, double tap or triple tap of the current gesture. */
static void combat_taps_event(int kind, float x, float y)
{
    uint64_t now = void_perf_now_ns();
    int same = combat_taps.count && combat_taps.screen == gesture.screen && combat_taps.controller == gesture.controller;
    if (kind == TOUCH_TRIPLE_TAP && same) {
        memset(&combat_taps, 0, sizeof combat_taps);
        combat_camera_home();
        return;
    }
    if (kind == TOUCH_DOUBLE_TAP && same && combat_taps.count == 1) {
        combat_taps.count = 2;
    } else {
        combat_taps_commit();             /* an unrelated earlier tap goes first */
        combat_taps.count = kind == TOUCH_DOUBLE_TAP ? 2 : 1;
        combat_taps.screen = gesture.screen;
        combat_taps.root = gesture.root;
        combat_taps.controller = gesture.controller;
    }
    combat_taps.x = x; combat_taps.y = y;
    combat_taps.awaiting = 0;
    combat_taps.due = now + MULTI_TAP_NS;
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

void void_touch_engine_event(const void_touch_event *event)
{
    if (!event || !isfinite(event->x) || !isfinite(event->y) ||
        !isfinite(event->dx) || !isfinite(event->dy) || !isfinite(event->scale) ||
        !isfinite(event->rotation)) return;
    if (event->kind == TOUCH_POINTER_CLICK) {
        pointer_text.screen = current_screen();
        pointer_text.x = event->x; pointer_text.y = event->y;
        pointer_text.frame = touch_frame; pointer_text.pending = 1;
        return;
    }
    if (event->kind == TOUCH_POINTER) {
        void_touch_event abort = {TOUCH_ABORT, 0, 0, 0, 0, 1, 0};
        void_touch_engine_event(&abort);
        memset(&combat_taps, 0, sizeof combat_taps);
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
    if (event->kind==TOUCH_ABORT) memset(&army_batch,0,sizeof army_batch);
    if (event->kind == TOUCH_BEGIN) {
        pointer_text.pending = 0;
        memset(&army_batch,0,sizeof army_batch);
        dnd_owner_pump(0);
        if (gesture.active && gesture.dnd_pressed) dnd_cancel();
        if (gesture.active && gesture.ui && same_screen()) ui_release(1);
        memset(&gesture, 0, sizeof gesture);
        gesture.begin_frame = touch_frame;
        gesture.screen = current_screen();
        if (!gesture.screen) { combat_taps_commit(); return; }
        gesture.kind = screen_kind(gesture.screen);
        /* A later battle may reuse the screen's address: forget the old home. */
        if (gesture.kind != SCREEN_COMBAT) combat_home.valid = 0;
        gesture.book = spellbook_kind(gesture.screen);
        gesture.start_x = gesture.x = event->x;
        gesture.start_y = gesture.y = event->y;
        gesture.root = read32(gesture.screen + 0xA0);
        if (!gesture.root || !ui_method(gesture.screen, 0x28)) { combat_taps_commit(); return; }
        gesture.controller = (gesture.kind == SCREEN_MENU || gesture.kind == SCREEN_TOWN) ? 0 :
                             read32(gesture.screen + (gesture.kind == SCREEN_ADVENTURE ? 0x5F4 : 0x2B4));
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
        if (gesture.placement) gesture.aiming = 1;
        /* A battlefield tap waiting for its multi-tap window waits for this
           gesture's outcome; any other gesture lets it go first. */
        if (combat_taps.count) {
            if (combat_world() && combat_taps.screen == gesture.screen && combat_taps.controller == gesture.controller)
                combat_taps.awaiting = 1;
            else
                combat_taps_commit();
        }
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
        }
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
    /* Only a battlefield tap has a triple meaning; elsewhere the third tap is a tap. */
    void_touch_event normalized = *event;
    if (normalized.kind == TOUCH_TRIPLE_TAP && !combat_world()) normalized.kind = TOUCH_TAP;
    event = &normalized;
    int kind = event->kind;
    if (combat_taps.awaiting && kind != TOUCH_TAP && kind != TOUCH_DOUBLE_TAP && kind != TOUCH_TRIPLE_TAP &&
        kind != TOUCH_END) {
        /* This gesture is not the next tap: the waiting tap is an order. */
        combat_taps.awaiting = 0;
        if (kind != TOUCH_ABORT) combat_taps_commit();
    }
    if (kind == TOUCH_SECOND_BEGIN || kind == TOUCH_SECOND_TAP || kind == TOUCH_SECOND_HOLD) {
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
    gesture.x = event->x; gesture.y = event->y;
    /* A camera gesture on the battlefield has no cursor under it. */
    if (!gesture.ui && gesture.kind == SCREEN_COMBAT && gesture.panning) publish_point(-1, -1);
    else publish_point(event->x, event->y);
    if (!same_screen()) {
        gesture.active = 0;
        publish_point(-1, -1);
        return;
    }
    if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP || kind == TOUCH_TRIPLE_TAP)
        VLOG("[touch] intent=%s screen=%08X kind=%d ui=%d aim=%d point=%.1f,%.1f",
             kind == TOUCH_TRIPLE_TAP ? "triple" : kind == TOUCH_DOUBLE_TAP ? "double" : "tap",
             gesture.screen, gesture.kind, gesture.ui, gesture.aiming, event->x, event->y);
    refresh_target_mode();
    if (kind == TOUCH_ABORT) {
        combat_taps.awaiting = 0;
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
        if (kind == TOUCH_END) { gesture.active = 0; combat_taps.awaiting = 0; }
        return;
    }
    if (gesture.ui) {
        ui_event(event);
    } else if (kind == TOUCH_TWO_FINGER_CANCEL) {
        if (gesture.kind == SCREEN_ADVENTURE) adventure_cancel();
            else if (gesture.kind == SCREEN_COMBAT) combat_cancel();
        gesture.cancelled = 1;
        gesture.combat_aim = 0;
        publish_point(-1, -1);
    } else if (kind == TOUCH_TILT) {
        gesture.panning = 1;
        if (gesture.kind == SCREEN_ADVENTURE || gesture.kind == SCREEN_TOWN)
            void_touch_camera_tilt(gesture.screen, gesture.kind == SCREEN_TOWN ? 2 : 0, event->dy);
        else if (gesture.kind == SCREEN_COMBAT)   /* the battle keeps its pitch: a vertical move */
            void_touch_camera(gesture.screen, 1, event->x, event->y, 0, event->dy, 1, 0);
    } else if (kind == TOUCH_PAN && combat_world()) {
        gesture.combat_aim = 1;
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
        }
    } else if (kind == TOUCH_HOLD_DRAG) {
        if (gesture.placement) placement_point(event->x, event->y, 1);
        else if (gesture.combat_aim || (gesture.aiming && gesture.kind == SCREEN_COMBAT)) combat_point(event->x, event->y, 0);
        else if (gesture.aiming && gesture.kind == SCREEN_ADVENTURE) adventure_point(event->x, event->y, 0);
    } else if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP || kind == TOUCH_TRIPLE_TAP ||
               (kind == TOUCH_END && (gesture.aiming || gesture.combat_aim) && !gesture.committed)) {
        /* A panel appearing after DOWN still owns the point at release. */
        if (adventure_announcement(event->x, event->y, 0)) {
            if (kind == TOUCH_TAP || kind == TOUCH_DOUBLE_TAP)
                adventure_announcement(event->x, event->y, 1);
            gesture.committed = 1;
        } else if (!ui_pick(gesture.screen, event->x, event->y)) {
            if (gesture.placement) placement_point(event->x, event->y, 2);
            else if (gesture.kind == SCREEN_ADVENTURE) {
                if (kind == TOUCH_DOUBLE_TAP && !gesture.aiming) adventure_double(event->x, event->y);
                else adventure_point(event->x, event->y, 1);
            }
            else if (gesture.kind == SCREEN_COMBAT) {
                if (kind != TOUCH_END && combat_world()) combat_taps_event(kind, event->x, event->y);
                else if (kind != TOUCH_DOUBLE_TAP || !combat_double(event->x, event->y))
                    combat_point(event->x, event->y, 1);
            } else if (gesture.kind == SCREEN_TOWN) town_activate(event->x, event->y);
            gesture.committed = 1;
        } else if (gesture.placement) {
            uint32_t placement = read32(gesture.screen + 0x488);
            if (placement) void_call_guest_this(0x00576260u, placement, 0, NULL);
            gesture.cancelled = 1;
        }
    }
    if (kind == TOUCH_END) {
        if (gesture.world_hover && same_screen()) ui_hover(-1, -1);   /* the information leaves with the finger */
        gesture.world_hover = 0;
        gesture.active = 0;
        combat_taps.awaiting = 0;
        if (!gesture.retiring && !drag_owner.helper) publish_point(-1, -1);
    }
}
