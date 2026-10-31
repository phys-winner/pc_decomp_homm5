/* Native UI virtual coordinates; the renderer and camera keep their resolution. */
#include "host.h"
#include "input.h"
#include "touch.h"
#include <math.h>
#include <string.h>

extern int void_android_display_size(int *w, int *h) __attribute__((weak));

static pthread_mutex_t scale_lock = PTHREAD_MUTEX_INITIALIZER;
static int scale_percent = 100;
static uint32_t viewport_scratch;
static struct {
    uint32_t screen, root;
    float width, height, actual_x, actual_y;
    float rect[4];
} viewport;
/* The scale the current screen is shown at: the requested one, or less when an
   element of it would not fit on the screen otherwise. */
static struct { uint32_t screen; int requested, percent; } fit;

static uint32_t scale_read32(uint32_t address)
{
    return void_vm_readable(address, 4) ? MEM32(address) : 0;
}

static uint32_t scale_virtual_base(uint32_t object, unsigned slot)
{
    uint32_t table = scale_read32(object + 4);
    if (!object || !table || !void_vm_readable(table + slot, 4)) return 0;
    uint32_t base = object + 4 + MEM32(table + slot);
    return void_vm_readable(base, 4) ? base : 0;
}

static uint32_t scale_current_screen(void)
{
    uint32_t screens = scale_read32(0x00FE719Cu);
    if (!screens || !void_vm_readable(screens, 12) ||
        !void_dispatch_find(0x008385A0u) || !void_dispatch_find(0x00D119FCu)) return 0;
    uint32_t interface = void_call_guest(0x008385A0u, 0, NULL, 1);
    uint32_t base = scale_virtual_base(interface, 4);
    if (!base) return 0;
    const uint32_t args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
    uint32_t screen = void_call_guest(0x00D119FCu, 5, args, 0);
    return void_vm_readable(screen, 0x150) ? screen : 0;
}

static uint32_t scale_screen_root(uint32_t screen)
{
    uint32_t root = scale_read32(screen + 0xA0), table = scale_read32(root);
    uint32_t head = scale_read32(screen + 0x14C);
    /* This is the original CWindowScreen parent-rectangle ABI, not an arbitrary window. */
    return root >= 0xF8 && head && scale_read32(head) == head &&
           void_vm_readable(root - 0xF8, 0x200) &&
           scale_read32(table + 0x48) == 0x00487990u
#ifndef HOMM5_LEGACY_UI
           && scale_read32(table + 0x4C) == 0x00488330u
#endif
           ? root : 0;
}

#ifdef HOMM5_LEGACY_UI
/* 1.6/2.1 keep a mutable canvas getter, but their coordinate conversions
   still load fixed constants. Checked generated patches use that same canvas.
   Their IScreen has no ToE Reposition virtual method: reproduce its geometry
   through the original parent-rectangle layout and invalidation calls. */
void void_touch_legacy_root_rect(uint32_t root, uint32_t destination)
{
    if (!void_vm_writable(destination, 16)) return;
    (void)root;
    float rect[4] = {0, 0, MEMF(0x00F74BE0u), MEMF(0x00F74BE4u)};
    if (!isfinite(rect[2]) || !isfinite(rect[3]) || rect[2] <= 0 || rect[3] <= 0) return;
    /* The old WindowScreen schema has no ToE HorAlign/VerAlign tail.
       Give its original CWindow::Layout the canvas as parent; the existing
       Placement alignment/margins still decide the root's own geometry. */
    memcpy(GPTR(destination), rect, sizeof rect);
}

void void_touch_legacy_relayout(void)
{
    uint32_t interface = void_call_guest(0x008385A0u, 0, NULL, 1), seen[64];
    unsigned count = 0;
    if (!viewport_scratch) viewport_scratch = void_galloc(16);
    while (interface && viewport_scratch && count < 64) {
        for (unsigned i = 0; i < count; ++i) if (seen[i] == interface) return;
        seen[count++] = interface;
        uint32_t base = scale_virtual_base(interface, 4);
        if (base) {
            const uint32_t args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
            uint32_t screen = void_call_guest(0x00D119FCu, 5, args, 0);
            uint32_t root = screen ? scale_screen_root(screen) : 0;
            if (root) {
                void_touch_legacy_root_rect(root, viewport_scratch);
                void_call_guest_this(0x00487990u, root, 1, &viewport_scratch);
                void_call_guest_this(0x00A504B0u, root + 0x14, 0, NULL);
                void_call_guest_this(0x00488220u, root - 0xF8, 0, NULL);
            }
        }
        interface = void_call_guest_this(0x008384D0u, interface, 0, NULL);
    }
}

void void_touch_legacy_resize(uint32_t width, uint32_t height)
{
    if (!width || !height || width > 16384 || height > 16384) return;
    MEMF(0x00F74BF0u) = (float)width;
    MEMF(0x00F74BF4u) = (float)height;
    double aspect = (double)width / height;
    MEMF(0x00F74BE0u) = aspect > (double)1.3333334f ? (float)floor(768.0 * aspect + (double).99f) : 1024;
    MEMF(0x00F74BE4u) = aspect > (double)1.3333334f ? 768 : (float)floor(1024.0 / aspect + (double).99f);
    void_touch_legacy_relayout();
}
#endif

static int scale_viewport_apply(void)
{
    if (!viewport.root || scale_current_screen() != viewport.screen ||
        scale_screen_root(viewport.screen) != viewport.root ||
        !void_dispatch_find(0x00487990u) || !void_dispatch_find(0x00A504B0u) ||
        !void_dispatch_find(0x00488220u)) return 0;
    if (!viewport_scratch) viewport_scratch = void_galloc(16);
    if (!viewport_scratch || !void_vm_writable(viewport_scratch, 16)) return 0;
    memcpy(GPTR(viewport_scratch), viewport.rect, sizeof viewport.rect);
    /* Exactly 488330's native geometry/invalidation sequence; resource anchors stay intact. */
    void_call_guest_this(0x00487990u, viewport.root, 1, &viewport_scratch);
    if (scale_current_screen() != viewport.screen || scale_screen_root(viewport.screen) != viewport.root) return 0;
    void_call_guest_this(0x00A504B0u, viewport.root + 0x14, 0, NULL);
    if (scale_current_screen() != viewport.screen || scale_screen_root(viewport.screen) != viewport.root) return 0;
    void_call_guest_this(0x00488220u, viewport.root - 0xF8, 0, NULL);
    if (scale_current_screen() != viewport.screen || scale_screen_root(viewport.screen) != viewport.root) return 0;
    viewport.actual_x = MEMF(viewport.root - 0xF8 + 0x64);
    viewport.actual_y = MEMF(viewport.root - 0xF8 + 0x68);
    return isfinite(viewport.actual_x) && isfinite(viewport.actual_y);
}

/* The screen's root keeps the 1024x768 frame its windows are drawn for, anchored at
   the top-left of the screen; scale_anchor then brings every element onto it. */
static int scale_viewport_ready(float width, float height)
{
    uint32_t screen = scale_current_screen(), root = screen ? scale_screen_root(screen) : 0;
    if (!root || !isfinite(width) || !isfinite(height) || width <= 0 || height <= 0) {
        viewport.root = 0;
        return 0;
    }
    if (viewport.screen == screen && viewport.root == root &&
        viewport.width == width && viewport.height == height) {
        /* Original resize/layout can run between gestures. Restore our parent rectangle once. */
        if (MEMF(root - 0xF8 + 0x64) != viewport.actual_x ||
            MEMF(root - 0xF8 + 0x68) != viewport.actual_y) return scale_viewport_apply();
        return 1;
    }
#ifdef HOMM5_LEGACY_UI
    uint32_t horizontal = 3, vertical = 3;
#else
    uint32_t resource = scale_read32(root + 0xC8);
    if (!resource || !void_vm_readable(resource, 0x104)) return 0;
    uint32_t horizontal = MEM32(resource + 0xFC), vertical = MEM32(resource + 0x100);
    if (horizontal > 3 || vertical > 3) return 0;
#endif
    float canvas_w = fmaxf(width, 1024), canvas_h = fmaxf(height, 768);
    float span_w = horizontal == 3 ? canvas_w : 1024;
    float span_h = vertical == 3 ? canvas_h : 768;
    float base_x = horizontal == 1 ? (canvas_w - 1024) * 0.5f : horizontal == 2 ? canvas_w - 1024 : 0;
    float base_y = vertical == 1 ? (canvas_h - 768) * 0.5f : vertical == 2 ? canvas_h - 768 : 0;
    viewport.screen = screen; viewport.root = root;
    viewport.width = width; viewport.height = height;
    viewport.rect[0] = base_x; viewport.rect[1] = base_y;
    viewport.rect[2] = base_x + span_w; viewport.rect[3] = base_y + span_h;
    if (scale_viewport_apply()) return 1;
    viewport.root = 0;
    return 0;
}

/* Every element of an anchored screen stays on it: there is nothing left to pan to. */
int void_touch_ui_pan(uint32_t screen, float dx, float dy)
{
    (void)screen; (void)dx; (void)dy;
    return 0;
}

/* ------------------------------------------------------------ anchoring */

/* A CWindow's placement (its primary vtable slot +8): the original getters are all
   "mov eax, [ecx+disp32]; ret", read here without a guest call. Fields used, as the
   original layout 0x00A50560 / 0x00A4D630 and IWindow::IsVisible 0x00A4EC70 use them:
   +0x70 visible, +0x88/+0x8C position, +0x94/+0x9C vertical/horizontal mode,
   +0xA4/+0xA8 size, +0xB0/+0xB4 low and +0xBC/+0xC0 high margins. */
static uint32_t scale_placement(uint32_t window)
{
    uint32_t table = scale_read32(window), getter = table ? scale_read32(table + 8) : 0;
    if (!getter || !void_vm_readable(getter, 7)) return 0;
    const uint8_t *code = (const uint8_t *)GPTR(getter);
    if (code[0] != 0x8B || code[1] != 0x81 || code[6] != 0xC3) return 0;
    uint32_t offset;
    memcpy(&offset, code + 2, 4);
    if (offset > 0x1000 || !void_vm_readable(window + offset, 4)) return 0;
    uint32_t placement = MEM32(window + offset);
    return void_vm_readable(placement, 0xC4) ? placement : 0;
}

/* 0x00A4D630: an element's position on one axis inside its parent's span. */
static float scale_native_position(uint32_t mode, float origin, float span, float position,
                                   float low, float size)
{
    switch (mode) {
    case 1: return origin + truncf((span - truncf(size)) * 0.5f) + position;
    case 2: return origin + span - size + position;
    case 3: return origin + low;
    default: return origin + position;
    }
}

static int scale_near(float a, float b) { return fabsf(a - b) <= 1.5f; }

/* [lo, lo+size) moved inside [0, view), or to 0 when it is larger. */
static float scale_clamp(float lo, float size, float view)
{
    if (size >= view) return 0;
    return roundf(fminf(fmaxf(lo, 0), view - size));
}

/* The shift that brings [lo, lo+size) of a frame [frame_lo, frame_hi) onto the
   screen's [0, view): to the edge it belongs to (its mode, else where it is drawn
   in the frame), or the centre, and never past an edge when it fits. */
static float scale_anchor_shift(uint32_t mode, float lo, float size, float frame_lo, float frame_hi, float view)
{
    float frame = frame_hi - frame_lo;
    if (frame <= view + 0.5f) {
        /* Self-positioned dialogs may retain their old position after the root has resized. */
        if (mode != 2 && size <= view) return scale_clamp(lo, size, view) - lo;
        return 0;
    }
    float centre = (lo + size * 0.5f - frame_lo) / frame, shift;
    if (mode == 2 || (mode != 1 && centre > 0.6f)) shift = view - frame_hi;
    else if (mode == 1 || centre >= 0.4f) shift = (view - frame) * 0.5f - frame_lo;
    else shift = -frame_lo;
    /* Far-edge resources may intentionally overdraw (JogDialBase: +6,+16).
       Clamping that background alone separates it from sibling buttons. */
    if (size <= view) {
        if (lo + shift < 0) shift = -lo;
        if (mode != 2 && lo + shift + size > view) shift = view - size - lo;
    } else if (size > view) {
        shift = -lo;
    }
    return roundf(shift);
}

/* A window's rectangle as IWindow 0xD4 (0x00A4DFF0) gives it to its children. */
static int scale_rect(uint32_t window, float rect[4])
{
    uint32_t placement = scale_placement(window);
    if (!placement || !void_vm_readable(window + 0x64, 8)) return 0;
    rect[0] = MEMF(window + 0x64); rect[1] = MEMF(window + 0x68);
    rect[2] = rect[0] + MEMF(placement + 0xA4); rect[3] = rect[1] + MEMF(placement + 0xA8);
    for (int i = 0; i < 4; ++i) if (!isfinite(rect[i])) return 0;
    return 1;
}

/* A CWindowScreen (its IScreen at +0xF8 is the original root ABI). */
static int scale_is_root(uint32_t window)
{
    uint32_t table = window ? scale_read32(window + 0xF8) : 0;
    return table && scale_read32(table + 0x48) == 0x00487990u
#ifndef HOMM5_LEGACY_UI
           && scale_read32(table + 0x4C) == 0x00488330u
#endif
           ;
}

/* The size an element gets laid out at: margins decide it on a stretched axis. */
static float scale_size(uint32_t mode, float span, float size, float low, float high)
{
    return mode == 3 ? span - low - high : size;
}

static int scale_covers(const float rect[4], const float frame[4])
{
    return rect[2] - rect[0] >= frame[2] - frame[0] - 1 && rect[3] - rect[1] >= frame[3] - frame[1] - 1;
}

static int scale_named(uint32_t placement, const char *expected)
{
    uint32_t name = scale_read32(placement + 0x58), end = scale_read32(placement + 0x5C);
    size_t length = strlen(expected);
    return name && end - name == length && void_vm_readable(name, end - name) && !memcmp(GPTR(name), expected, length);
}

/* An element of a screen: a child of its root, or of a container as large as the
   root (the screens' "Main" windows), shown with its ancestors. Gives the root's
   frame, and whether the element is such a container itself. */
static int scale_element(uint32_t window, uint32_t placement, float frame[4], int *container)
{
    uint32_t parent = scale_read32(window + 0x28), root = 0;
    if (!MEM8(placement + 0x70) || !parent) return 0;
    /* StackInfo positions already come from world-to-screen projection. */
    if (scale_named(placement, "StackInfo")) return 0;
    uint32_t own = scale_placement(parent);
    if (!own || !MEM8(own + 0x70)) return 0;
    if (scale_is_root(parent)) {
        root = parent;
    } else {
        uint32_t grand = scale_read32(parent + 0x28), outer = grand ? scale_placement(grand) : 0;
        float rect[4];
        if (!outer || !MEM8(outer + 0x70) || !scale_is_root(grand) || !scale_rect(parent, rect) ||
            !scale_rect(grand, frame) || !scale_covers(rect, frame)) return 0;
        root = grand;
    }
    if (!scale_rect(root, frame)) return 0;
    float rect[4] = {0, 0, MEMF(placement + 0xA4), MEMF(placement + 0xA8)};
    rect[2] = scale_size(MEM32(placement + 0x9C), frame[2] - frame[0], rect[2],
                         MEMF(placement + 0xB0), MEMF(placement + 0xBC));
    rect[3] = scale_size(MEM32(placement + 0x94), frame[3] - frame[1], rect[3],
                         MEMF(placement + 0xB4), MEMF(placement + 0xC0));
    *container = parent == root && scale_covers(rect, frame);
    return 1;
}

/* Where the original layout 0x00A50560 places an element inside the parent
   rectangle, and the shift that anchors it on the view. */
static void scale_place(uint32_t placement, const float parent[4], const float frame[4], float view_w, float view_h,
                        float position[2], float size[2], float shift[2])
{
    for (int axis = 0; axis < 2; ++axis) {
        uint32_t mode = MEM32(placement + (axis ? 0x94 : 0x9C));
        float span = parent[axis + 2] - parent[axis];
        size[axis] = scale_size(mode, span, MEMF(placement + 0xA4 + 4 * axis),
                                MEMF(placement + 0xB0 + 4 * axis), MEMF(placement + 0xBC + 4 * axis));
        position[axis] = scale_native_position(mode, parent[axis], span, MEMF(placement + 0x88 + 4 * axis),
                                               MEMF(placement + 0xB0 + 4 * axis), size[axis]);
        shift[axis] = scale_anchor_shift(mode, position[axis], size[axis], frame[axis], frame[axis + 2],
                                         axis ? view_h : view_w);
    }
    /* Its border is part of the left-anchored ATB texture, not this text panel. */
    if (scale_read32(viewport.screen) == 0x00E1DA84u && scale_named(placement, "PredictionBox") &&
        frame[2] - frame[0] > view_w + 0.5f)
        shift[0] = -frame[0];
    /* Deployment text must not cover the army after the camera frames it. */
    if (scale_read32(viewport.screen) == 0x00E1DA84u && scale_named(placement, "WindowFadedText"))
        shift[1] = roundf(fminf(50.0f, view_h * .1f) - position[1]);
}

/* CWindow::Layout(const float parent[4]), thiscall, RET 4, as virtual calls reach
   it (its dispatch entry): a dialog's modal loop lays out its windows while the
   frame pumps wait for it. Above 100% an element of a screen gets its parent's
   rectangle shifted by its anchor, so the original layout places it, its children
   and its text on the smaller view. Subclasses that call it directly are anchored
   by the frame pump (scale_anchor). */
void sub_00A50560(void);

static void scale_layout_override(void)
{
    static uint32_t scratch;
    static unsigned depth;
    uint32_t window = g_ecx, rect = scale_read32(g_esp + 4), placement = 0;
    float view_w = MEMF(0x00F74BE0u), view_h = MEMF(0x00F74BE4u), parent[4], frame[4];
    float position[2], size[2], shift[2];
    int container = 0;
    if (!(view_w < 1023.5f || view_h < 767.5f) || !isfinite(view_w) || !isfinite(view_h) ||
        !rect || !void_vm_readable(rect, 16) || !(placement = scale_placement(window)) ||
        !scale_element(window, placement, frame, &container) || container) {
        sub_00A50560();
        return;
    }
    /* A rectangle this file shifted already is laid out as given. */
    if (!scratch) scratch = void_galloc(16 * 8);
    if ((scratch && rect >= scratch && rect < scratch + 16 * 8) || (viewport_scratch && rect == viewport_scratch)) {
        sub_00A50560();
        return;
    }
    memcpy(parent, GPTR(rect), sizeof parent);
    for (int i = 0; i < 4; ++i) {
        if (!isfinite(parent[i])) { sub_00A50560(); return; }
    }
    /* A root's own children are laid out in the rectangle given (a dialog's is the screen's). */
    if (scale_is_root(scale_read32(window + 0x28))) memcpy(frame, parent, sizeof frame);
    scale_place(placement, parent, frame, view_w, view_h, position, size, shift);
    if ((!shift[0] && !shift[1]) || !scratch || !void_vm_writable(scratch, 16 * 8)) {
        sub_00A50560();
        return;
    }
    /* Nested layouts (its children) take the next slot. */
    uint32_t shifted = scratch + 16 * (depth++ % 8);
    float moved[4] = {parent[0] + shift[0], parent[1] + shift[1], parent[2] + shift[0], parent[3] + shift[1]};
    memcpy(GPTR(shifted), moved, sizeof moved);
    MEM32(g_esp + 4) = shifted;
    sub_00A50560();
    --depth;
}

typedef struct {
    float view_w, view_h;
    float need_w, need_h;          /* the largest elements: sizes do not change with the scale */
    float combat_left, combat_right;
    int anchor;                    /* move them; else only measure (the original 100% layout) */
    unsigned remaining, moved;
    unsigned stacks, map_army;
    float stack_top, stack_bottom, hud_top, map_top, map_bottom;
} scale_pass;

/* Anchors (or measures) the shown elements under a screen root or its containers. */
static void scale_anchor(uint32_t parent, unsigned depth, scale_pass *pass)
{
    float rect[4];
    if (depth == 3 || !scale_rect(parent, rect)) return;
    for (unsigned i = 0; pass->remaining; ++i) {
        /* Native layout may change the vector: reread it every time. */
        uint32_t begin = scale_read32(parent + 0xA4), end = scale_read32(parent + 0xA8);
        if (!begin || end < begin || (end - begin) % 4 || (end - begin) / 4 > 1024 ||
            i >= (end - begin) / 4 || !void_vm_readable(begin, end - begin)) break;
        --pass->remaining;
        uint32_t child = MEM32(begin + i * 4), placement = child && child != parent ? scale_placement(child) : 0;
        float frame[4], position[2], size[2], shift[2];
        int container = 0;
        if (placement && MEM8(placement + 0x70) && scale_named(placement, "StackInfo")) {
            float y = MEMF(placement + 0x8C), h = MEMF(placement + 0xA8);
            if (isfinite(y) && isfinite(h) && h > 0) {
                pass->stack_top = pass->stacks ? fminf(pass->stack_top, y) : y;
                pass->stack_bottom = pass->stacks ? fmaxf(pass->stack_bottom, y + h) : y + h;
                ++pass->stacks;
            }
        }
        if (!placement || !void_vm_readable(child, 0xF0) || !scale_element(child, placement, frame, &container)) continue;
        if (container) {
            scale_anchor(child, depth + 1, pass);
            continue;
        }
        scale_place(placement, rect, frame, pass->view_w, pass->view_h, position, size, shift);
        if (scale_read32(viewport.screen) == 0x00E1DA84u && MEM32(placement + 0x94) == 2) {
            if (scale_named(placement, "ATBBar") && MEM32(placement + 0x9C) == 0)
                pass->combat_left = fmaxf(pass->combat_left, MEMF(placement + 0x88) + size[0]);
            if (scale_named(placement, "Jogdial") && MEM32(placement + 0x9C) == 2)
                pass->combat_right = fmaxf(pass->combat_right, size[0] - MEMF(placement + 0x88));
        }
        if (scale_named(placement, "TownHeroPanel")) pass->map_army = 1;
        if (size[0] > 100 && size[1] > 40 && MEM32(placement + 0x94) == 2)
            pass->map_bottom = fminf(pass->map_bottom, position[1] + shift[1]);
        if (size[0] > pass->view_w * .5f && position[1] + shift[1] < 10 && size[1] < pass->view_h * .2f)
            pass->map_top = fmaxf(pass->map_top, position[1] + shift[1] + size[1]);
        if (size[0] > pass->view_w * .45f && size[1] > 40 && MEM32(placement + 0x94) == 2)
            pass->hud_top = fminf(pass->hud_top, position[1] + shift[1]);
        float x = MEMF(child + 0x64), y = MEMF(child + 0x68);
        int native = scale_near(x, position[0]) && scale_near(y, position[1]);
        int placed = scale_near(x, position[0] + shift[0]) && scale_near(y, position[1] + shift[1]);
        /* Every shown element is measured, also one its own code repositions (a modal, or an adventure
           dialog such as level-up that centres itself without a modal loop): otherwise fitting
           alternates between scales and aborts every pending click. */
        if (size[0] >= 1 && size[1] >= 1) {
            /* Keep a far-edge inset too, so moving one panel cannot cover its siblings. */
            float inset_x = MEM32(placement + 0x9C) == 2 ? fmaxf(0, -MEMF(placement + 0x88)) : 0;
            float inset_y = MEM32(placement + 0x94) == 2 ? fmaxf(0, -MEMF(placement + 0x8C)) : 0;
            pass->need_w = fmaxf(pass->need_w, size[0] + inset_x);
            pass->need_h = fmaxf(pass->need_h, size[1] + inset_y);
        }
        if (native || placed) {
            if (placed) continue;
        } else {
            /* Windows their own code places (dialogs it centres on 1024x768, tooltips,
               dragged icons) are only kept on the screen, from where that code put them. */
            float keep_x = scale_clamp(x, size[0], pass->view_w), keep_y = scale_clamp(y, size[1], pass->view_h);
            if (size[0] < 1 || size[1] < 1 || (keep_x == x && keep_y == y)) continue;
            shift[0] = keep_x - position[0];
            shift[1] = keep_y - position[1];
        }
        if (!pass->anchor) continue;
        uint32_t layout = scale_read32(scale_read32(child) + 0x24);
        if (!layout || !void_dispatch_find(layout) || !viewport_scratch ||
            !void_vm_writable(viewport_scratch, 16)) continue;
        /* The element's own layout, its children and text against a shifted parent. */
        float moved[4] = {rect[0] + shift[0], rect[1] + shift[1], rect[2] + shift[0], rect[3] + shift[1]};
        memcpy(GPTR(viewport_scratch), moved, sizeof moved);
        void_call_guest_this(layout, child, 1, &viewport_scratch);
        ++pass->moved;
    }
}

/* Anchors (or only measures) the shown elements of a screen root (a CWindowScreen).
   Returns the largest scale (100..percent) they fit on the screen at, or 0 when it
   cannot tell. */
static int scale_fits(uint32_t root, int anchor, float width, float height, float base_w, float base_h, int percent)
{
    scale_pass pass = {.view_w = width, .view_h = height, .anchor = anchor, .remaining = 4096, .hud_top = height, .map_bottom = height};
    if (!scale_is_root(root)) return 0;
    scale_anchor(root, 0, &pass);
    /* Both ends of the combat HUD must fit together, not merely on their own. */
    if (pass.combat_left > 0 && pass.combat_right > 0)
        pass.need_w = fmaxf(pass.need_w, pass.combat_left + pass.combat_right);
    if (anchor && pass.stacks && scale_read32(viewport.screen) == 0x00E1DA84u)
        void_touch_combat_frame(viewport.screen, width, height, pass.hud_top, pass.stack_top, pass.stack_bottom);
    if (anchor && scale_read32(viewport.screen) == 0x00E230E4u)
        void_touch_adventure_frame(viewport.screen, height, pass.map_army ? pass.map_top : 0,
                                    pass.map_army ? pass.map_bottom : height);
    if (pass.moved) VLOG("[touch] ui-anchor root=%08X moved=%u view=%.0fx%.0f", root, pass.moved, width, height);
    int fits = percent;
    if (pass.need_w > 0) fits = (int)fminf((float)fits, floorf(base_w * 100.0f / pass.need_w));
    if (pass.need_h > 0) fits = (int)fminf((float)fits, floorf(base_h * 100.0f / pass.need_h));
    return fits < 100 ? 100 : fits;
}

/* ------------------------------------------------------------------ text */

static void_fn original_list_layout;

/* Scrollable text rows must grow with wrapped columns before the native list places the next row. */
static int scale_text_rows(uint32_t list)
{
    uint32_t holder = scale_read32(list + 0x15C), begin = scale_read32(holder + 0xA4), end = scale_read32(holder + 0xA8);
    if (!begin || end < begin || (end - begin) % 4 || end - begin > 16384 || !void_vm_readable(begin, end - begin)) return 0;
    int changed = 0;
    for (uint32_t at = begin; at < end; at += 4) {
        uint32_t row = MEM32(at), placement = scale_placement(row);
        uint32_t a = scale_read32(row + 0xA4), b = scale_read32(row + 0xA8);
        if (!placement || !MEM8(placement + 0x70) || !a || b <= a || (b - a) % 4 || b - a > 128 ||
            !void_vm_readable(a, b - a)) continue;
        float height = 0;
        int text_only = 1;
        for (uint32_t child = a; child < b; child += 4) {
            uint32_t window = MEM32(child), p = scale_placement(window);
            if (scale_read32(scale_read32(window) + 4) != 0x00B95AC0u || !p || MEM32(p + 0x94) != 0) {
                text_only = 0; break;
            }
            if (!MEM8(p + 0x70)) continue;
            float y = MEMF(p + 0x8C), h = MEMF(p + 0xA8);
            if (!isfinite(y) || !isfinite(h) || y < 0 || h < 0 || y + h > 4096) { text_only = 0; break; }
            height = fmaxf(height, ceilf(y + h));
        }
        if (text_only && height > 0 && height != MEMF(placement + 0xA8) && void_vm_writable(placement + 0xA8, 4)) {
            MEMF(placement + 0xA8) = height;
            changed = 1;
        }
    }
    return changed;
}

static void scale_list_layout(void)
{
    static unsigned depth;
    uint32_t list = g_ecx;
    original_list_layout();
    if (!depth && scale_read32(list) == 0x00E94034u) {
        ++depth;
        void_regs saved;
        void_regs_save(&saved);
        uint32_t bar = scale_read32(list + 0x154), method = scale_read32(scale_read32(bar + 0xF8) + 0x18);
        if (method && void_dispatch_find(method) && !(void_call_guest_this(method, bar + 0xF8, 0, NULL) & 0xFFu) &&
            scale_text_rows(list)) {
            void_call_guest_this(0x008888E0u, list, 0, NULL);
            void_call_guest_this(0x00887BA0u, list, 0, NULL);
        }
        void_regs_load(&saved);
        --depth;
    }
}

static int scale_has_text(uint32_t begin, uint32_t end)
{
    return begin && end > begin && end - begin <= 0x100000u &&
           void_vm_readable(begin, end - begin);
}

static void scale_refresh_window(uint32_t window, unsigned depth, unsigned *remaining)
{
    if (depth == 64 || !*remaining || !void_vm_readable(window, 0xAC)) return;
    --*remaining;
    uint32_t table = scale_read32(window), refresh = scale_read32(table + 4);
    /* These are every CWindow-derived text refresh implementation in original RTTI. */
    if (refresh != 0x00A4E570u && refresh != 0x00B95AC0u && refresh != 0x00ABE980u) return;
    int has_text = 0;
    if (refresh == 0x00A4E570u) {
        uint32_t text = scale_read32(window + 0x70);
        has_text = text && void_vm_readable(text, 120) &&
                   scale_has_text(MEM32(text + 4), MEM32(text + 8));
    } else if (refresh == 0x00B95AC0u && void_vm_readable(window + 0x100, 0x28)) {
        uint32_t format = MEM32(window + 0x100);
        has_text = format && void_vm_readable(format, 250) &&
                   scale_has_text(MEM32(window + 0x10C), MEM32(window + 0x110));
    } else if (refresh == 0x00ABE980u) {
        uint32_t text = scale_read32(window + 0x104), methods = scale_read32(text);
        has_text = text && methods && void_vm_readable(methods, 0x3C);
    }
    if (has_text && void_dispatch_find(refresh))
        void_call_guest_this(refresh, window, 0, NULL);

    /* Native layout may resize a child while rebuilding text: reread the vector. */
    for (unsigned i = 0; *remaining; ++i) {
        uint32_t begin = scale_read32(window + 0xA4), end = scale_read32(window + 0xA8);
        if (!begin || end < begin || (end - begin) % 4 ||
            (end - begin) / 4 > 4096 || i >= (end - begin) / 4 ||
            !void_vm_readable(begin, end - begin)) break;
        uint32_t child = MEM32(begin + i * 4);
        if (child != window) scale_refresh_window(child, depth + 1, remaining);
    }
    if (table == 0x00E94034u && original_list_layout) {
        void_regs saved;
        void_regs_save(&saved);
        uint32_t bar = scale_read32(window + 0x154), method = scale_read32(scale_read32(bar + 0xF8) + 0x18);
        if (method && void_dispatch_find(method) && !(void_call_guest_this(method, bar + 0xF8, 0, NULL) & 0xFFu) &&
            scale_text_rows(window)) {
            void_call_guest_this(0x008888E0u, window, 0, NULL);
            void_call_guest_this(0x00887BA0u, window, 0, NULL);
        }
        void_regs_load(&saved);
    }
}

static void scale_refresh_text(void)
{
    if (!void_dispatch_find(0x00D119FCu) || !void_dispatch_find(0x008384D0u)) return;
    uint32_t interface = void_call_guest(0x008385A0u, 0, NULL, 1);
    uint32_t seen[64];
    unsigned count = 0, remaining = 4096;
    while (interface && count < 64 && remaining) {
        for (unsigned i = 0; i < count; ++i) if (seen[i] == interface) return;
        seen[count++] = interface;
        uint32_t base = scale_virtual_base(interface, 4);
        if (base) {
            const uint32_t screen_args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
            uint32_t screen = void_call_guest(0x00D119FCu, 5, screen_args, 0);
            uint32_t root = screen ? scale_read32(screen + 0xA0) : 0;
            uint32_t window_interface = scale_virtual_base(root, 8);
            if (window_interface) {
                const uint32_t window_args[] = {window_interface, 0, 0x00F2DAF4u, 0x00F2DA88u, 0};
                uint32_t window = void_call_guest(0x00D119FCu, 5, window_args, 0);
                if (window) scale_refresh_window(window, 0, &remaining);
            }
        }
        interface = void_call_guest_this(0x008384D0u, interface, 0, NULL);
    }
}

void void_touch_set_scale(float scale)
{
    if (!isfinite(scale)) return;
    scale = fminf(2.0f, fmaxf(0.5f, scale));
    pthread_mutex_lock(&scale_lock);
    scale_percent = (int)lroundf(scale * 100.0f);
    pthread_mutex_unlock(&scale_lock);
}

void void_touch_scale_pump(void)
{
    /* Readiness also prevents applying initial PE defaults before D3D resizes UI. */
    if (void_module_exe_base() != 0x00400000u ||
        !void_vm_writable(0x00F74BE0u, 8) ||
        !void_vm_readable(0x00F74BE8u, 16) ||
        !void_vm_readable(0x00FE719Cu, 4) ||
#ifndef HOMM5_LEGACY_UI
        !void_dispatch_find(0x0066A4D0u) ||
#endif
        !void_dispatch_find(0x008385A0u)) return;
    if (MEMF(0x00F74BE8u) != 1024.0f || MEMF(0x00F74BECu) != 768.0f) return;
    static int layout_hooked;
    if (!original_list_layout) {
        original_list_layout = void_dispatch_find(0x008885D0u);
        if (original_list_layout) void_dispatch_add(0x008885D0u, scale_list_layout);
    }
    if (!layout_hooked && void_dispatch_find(0x00A50560u) == (void_fn)sub_00A50560) {
        void_dispatch_add(0x00A50560u, scale_layout_override);
        layout_hooked = 1;
    }
    float physical_w = MEMF(0x00F74BF0u), physical_h = MEMF(0x00F74BF4u);
    float current_w = MEMF(0x00F74BE0u), current_h = MEMF(0x00F74BE4u);
    if (!isfinite(physical_w) || !isfinite(physical_h) ||
        !isfinite(current_w) || !isfinite(current_h) ||
        physical_w < 1 || physical_h < 1 || physical_w > 16384 || physical_h > 16384 ||
        current_w <= 0 || current_h <= 0 || current_w > 16384 || current_h > 16384) return;
    int buffer_w, buffer_h;
    void_input_screen_size(&buffer_w, &buffer_h);
    if (buffer_w <= 0 || buffer_h <= 0 ||
        physical_w != (float)buffer_w || physical_h != (float)buffer_h) return;

    pthread_mutex_lock(&scale_lock);
    int requested = scale_percent;
    pthread_mutex_unlock(&scale_lock);
    /* Match B295D0's original aspect threshold and integer rounding first. */
    double aspect = (double)buffer_w / (double)buffer_h;
    int display_w, display_h;
    if (void_android_display_size && void_android_display_size(&display_w, &display_h) &&
        display_w > 0 && display_h > 0 && display_w <= 16384 && display_h <= 16384 &&
        fabs((double)buffer_w * display_h - (double)buffer_h * display_w) <= (double)display_w + display_h)
        /* Render-scale rounding must not change the UI's reference canvas.
           A deliberately letterboxed game mode keeps its own original aspect. */
        aspect = (double)display_w / (double)display_h;
    float base_w = 1024.0f, base_h = 768.0f;
    if (aspect > (double)1.3333334f) base_w = (float)floor(768.0 * aspect + (double)0.99f);
    else base_h = (float)floor(1024.0 / aspect + (double)0.99f);

    /* Above 100% the scale is the screen's: a new screen, or a new request, starts
       from the request and anchoring lowers it while an element does not fit. */
    uint32_t screen = requested > 100 ? scale_current_screen() : 0;
    if (scale_read32(screen) != 0x00E1DA84u && scale_read32(screen) != 0x00E230E4u)
        void_touch_combat_frame(0, 0, 0, 0, 0, 0);
    if (requested <= 100 || fit.screen != screen || fit.requested != requested) {
        fit.screen = screen;
        fit.requested = fit.percent = requested;
    }
    for (int round = 0; round < 2; ++round) {
        int percent = fit.percent;
        double factor = 100.0 / (double)percent;
        float wanted_w = (float)((double)base_w * factor);
        float wanted_h = (float)((double)base_h * factor);
        if (wanted_w < 1 || wanted_h < 1 || wanted_w > 16384 || wanted_h > 16384) return;
        /* The original resize path may reset virtual coordinates: compare every pump,
           but relayout only when their actual values differ from the requested pair. */
        if (current_w != wanted_w || current_h != wanted_h) {
            uint32_t screens = MEM32(0x00FE719Cu);
            if (!screens || !void_vm_readable(screens, 12) ||
                !void_call_guest(0x008385A0u, 0, NULL, 1)) return;
            const void_touch_event abort = {.kind = TOUCH_ABORT, .scale = 1};
            void_touch_engine_event(&abort);
            viewport.root = 0;
            MEMF(0x00F74BE0u) = current_w = wanted_w;
            MEMF(0x00F74BE4u) = current_h = wanted_h;
#ifdef HOMM5_LEGACY_UI
            void_touch_legacy_relayout();
#else
            const uint32_t unused = 0;
            void_call_guest(0x0066A4D0u, 1, &unused, 1);
#endif
            /* Fixed-width buttons cache physical glyph geometry across virtual-only resizes. */
            scale_refresh_text();
            VLOG("[touch] ui-scale=%d%% (requested %d%%) virtual=%.2fx%.2f backbuffer=%dx%d",
                 percent, requested, wanted_w, wanted_h, buffer_w, buffer_h);
        }
        if (requested <= 100) return;
        int fits;
        if (percent > 100) {
            uint32_t root = scale_viewport_ready(wanted_w, wanted_h) ? viewport.root : 0;
            if (!root) {
                /* A screen whose root is not the parent-rectangle ABI (the message boxes')
                   keeps its original frame; its elements are still brought onto the view. */
                if (!viewport_scratch) viewport_scratch = void_galloc(16);
                root = screen ? scale_read32(screen + 0xA0) : 0;
                if (root < 0xF8 || !scale_is_root(root - 0xF8)) return;
            }
            fits = scale_fits(root - 0xF8, 1, wanted_w, wanted_h, base_w, base_h, requested);
        } else {
            /* Shown at 100% because an element needs it: the original layout, measured
               to see whether it still does. */
            uint32_t root = screen ? scale_screen_root(screen) : 0;
            if (!root) return;
            fits = scale_fits(root - 0xF8, 0, wanted_w, wanted_h, base_w, base_h, requested);
        }
        if (!fits || fits == fit.percent) return;
        VLOG("[touch] ui-fit screen=%08X %d%% -> %d%%", screen, fit.percent, fits);
        fit.percent = fits;
    }
}
