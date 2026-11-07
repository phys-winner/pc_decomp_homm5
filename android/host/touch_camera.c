#include "host.h"
#include "input.h"
#include "touch.h"
#include <math.h>
#include <string.h>

/* CameraPos and projection calls are the original H5 engine's interfaces. */
static uint32_t camera_scratch;
static void_fn original_edge_scroll;

static uint32_t camera_method(uint32_t object, uint32_t offset)
{
    if (!void_vm_readable(object, 4)) return 0;
    uint32_t table = MEM32(object);
    if (!void_vm_readable(table, offset + 4)) return 0;
    uint32_t method = MEM32(table + offset);
    return void_dispatch_find(method) ? method : 0;
}

static int camera_town_owner(uint32_t screen, uint32_t root, uint32_t controller)
{
    if (!void_vm_readable(screen, 0x479) || MEM32(screen) != 0x00E2A64Cu ||
        MEM32(screen + 0xA0) != root || MEM32(screen + 0x220) != controller ||
        MEM8(screen + 0x29C) || MEM8(screen + 0x478)) return 0;
    uint32_t pending = MEM32(screen + 0x14C);
    if (!void_vm_readable(pending, 4) || MEM32(pending) != pending ||
        !void_vm_readable(0x00FE719Cu, 4) ||
        !void_vm_readable(MEM32(0x00FE719Cu), 12) ||
        !void_dispatch_find(0x008385A0u) || !void_dispatch_find(0x00D119FCu)) return 0;
    uint32_t top = void_call_guest(0x008385A0u, 0, NULL, 1);
    if (!void_vm_readable(top, 8)) return 0;
    uint32_t table = MEM32(top + 4);
    if (!void_vm_readable(table, 8)) return 0;
    uint32_t base = top + 4 + MEM32(table + 4);
    if (!void_vm_readable(base, 4)) return 0;
    const uint32_t args[] = {base, 0, 0x00F272C0u, 0x00F323A8u, 0};
    return void_call_guest(0x00D119FCu, 5, args, 0) == screen;
}

static int camera_town_prepare(uint32_t screen)
{
    if (!void_vm_writable(screen, 0x479)) return 0;
    uint32_t root = MEM32(screen + 0xA0), controller = MEM32(screen + 0x220);
    if (!void_vm_readable(root, 4) || !camera_town_owner(screen, root, controller) ||
        !void_dispatch_find(0x00614200u) || !void_dispatch_find(0x006146C0u)) return 0;
    /* Original Town input interrupts the animated flyup before accepting manual motion. */
    if ((void_call_guest_this(0x00614200u, screen, 0, NULL) & 0xFFu) ||
        !camera_town_owner(screen, root, controller) ||
        (void_call_guest_this(0x006146C0u, screen, 0, NULL) & 0xFFu) ||
        !camera_town_owner(screen, root, controller)) return 0;
    if (!MEM32(screen + 0x294)) {
        if (!camera_method(controller, 0x90) || !void_dispatch_find(0x00618170u)) return 0;
        void_call_guest_this(0x00618170u, screen, 0, NULL);
        if (!camera_town_owner(screen, root, controller) || !MEM32(screen + 0x294)) return 0;
    }
    return 1;
}

static void camera_store(uint32_t address, float value)
{
    memcpy(GPTR(address), &value, sizeof value);
}

static int camera_plane_point(uint32_t screen, float x, float y, float height,
                              float result[2])
{
    uint32_t raw = camera_scratch + 0x6E0, point = camera_scratch + 0x6F0;
    uint32_t direction = camera_scratch + 0x700, origin = camera_scratch + 0x710;
    camera_store(raw, x); camera_store(raw + 4, y);
    uint32_t logical = void_call_guest_this(0x00B29220u, raw, 0, NULL);
    if (!void_vm_readable(logical, 8)) return 0;
    memcpy(GPTR(point), GPTR(logical), 8);
    uint32_t args[3] = {camera_scratch, 0, 0};
    memcpy(&args[1], &height, sizeof height);
    g_edx = point;
    void_call_guest_this(0x00671310u, screen, 2, args);
    args[0] = camera_scratch + 0x14;
    args[1] = camera_scratch + 0x0C;
    args[2] = camera_scratch + 0x04;
    g_edx = origin;
    void_call_guest_this(0x00CF6B20u, direction, 3, args);
    float ray[3], eye[3];
    memcpy(ray, GPTR(direction), sizeof ray);
    memcpy(eye, GPTR(origin), sizeof eye);
    for (int i = 0; i < 3; ++i)
        if (!isfinite(ray[i]) || !isfinite(eye[i])) return 0;
    if (fabsf(ray[2]) < 0.00001f) return 0;
    float distance = (height - eye[2]) / ray[2];
    if (!isfinite(distance) || distance <= 0) return 0;
    result[0] = eye[0] + distance * ray[0];
    result[1] = eye[1] + distance * ray[1];
    return isfinite(result[0]) && isfinite(result[1]);
}

int void_touch_camera(uint32_t screen, int kind, float x, float y,
                      float dx, float dy, float scale, float rotation)
{
    if (!isfinite(x) || !isfinite(y) || !isfinite(dx) || !isfinite(dy) ||
        !isfinite(scale) || !isfinite(rotation) || scale <= 0 || kind < 0 || kind > 2) return 0;
    /* The options' camera sensitivity scales turning and zooming; a pan keeps
       the ground under the fingers. */
    float sensitivity = void_port_camera_sensitivity();
    if (sensitivity != 1.0f) {
        rotation *= sensitivity;
        scale = powf(scale, sensitivity);
        if (!isfinite(rotation) || !isfinite(scale) || scale <= 0) return 0;
    }
    int town = kind == 2;
    uint32_t table = town ? 0x00E2A64Cu : kind == 1 ? 0x00E1DA84u : 0x00E230E4u;
    uint32_t operator_offset = town ? 0x374u : kind == 1 ? 0x3B8u : 0x5E4u;
    if (!void_vm_readable(screen, operator_offset + 4) ||
        MEM32(screen) != table) return 0;
    if (town && ((dx == 0 && scale == 1 && rotation == 0) || !camera_town_prepare(screen))) return 0;
    uint32_t camera = MEM32(screen + 0xA4), hand = MEM32(screen + operator_offset);
    if (!void_vm_readable(hand, town ? 0x178u : 0x14Cu)) return 0;
    if (town && (MEM32(hand) != 0x00E449BCu || MEM32(hand + 0x144) != camera)) return 0;
    uint32_t get = camera_method(camera, 0x54), set = camera_method(hand, 0x50);
    uint32_t unfollow = town ? 0 : camera_method(hand, 0x5C);
    if (!get || !set || (!town && !unfollow)) return 0;
    uint32_t source = void_call_guest_this(get, camera, 0, NULL);
    if (!void_vm_readable(source, 40)) return 0;
    float position[10];
    memcpy(position, GPTR(source), sizeof position);
    for (int i = 0; i < 10; ++i) if (!isfinite(position[i])) return 0;
    if (position[0] <= 0) return 0;
    if (!camera_scratch) camera_scratch = void_galloc(0x800);
    if (!camera_scratch) return 0;
    float before[2], after[2], old_rod = position[0], old_yaw = position[2];
    int anchored = !town && (dx != 0 || dy != 0 || scale != 1 || rotation != 0);
    if (anchored) {
        if (!camera_plane_point(screen, x - dx, y - dy, position[9], before) ||
            !camera_plane_point(screen, x, y, position[9], after)) return 0;
    }
    const float turn = 6.2831853071795864769f;
    if (town && dx != 0) {
        int width, height;
        void_input_screen_size(&width, &height);
        if (width <= 0 || height <= 0) return 0;
        rotation += turn * (dx / (float)width) * sensitivity;
        if (!isfinite(rotation)) return 0;
    }
    if (rotation != 0)
        position[2] = remainderf(remainderf(position[2], turn) - remainderf(rotation, turn), turn);
    float rod_limits[2];
    /* The town operator stores its camera at +144, and rod bounds in settings. */
    memcpy(rod_limits, GPTR(hand + (town ? 0x68u : 0x144u)), sizeof rod_limits);
    if (!isfinite(rod_limits[0]) || !isfinite(rod_limits[1]) ||
        rod_limits[0] > rod_limits[1] || rod_limits[1] <= 0) return 0;
    position[0] = fminf(rod_limits[1], fmaxf(fmaxf(0.0001f, rod_limits[0]), position[0] / scale));
    if (anchored) {
        /* Native yaw orbits +Z (7CD4F0); dolly scales plane intersections about the anchor. */
        float yaw = remainderf(position[2] - old_yaw, turn), ratio = position[0] / old_rod;
        float c = cosf(yaw), s = sinf(yaw), ax = after[0] - position[7], ay = after[1] - position[8];
        position[7] = before[0] - ratio * (c * ax - s * ay);
        position[8] = before[1] - ratio * (s * ax + c * ay);
    }
    if (!isfinite(position[0]) || position[0] <= 0 ||
        !isfinite(position[7]) || !isfinite(position[8])) return 0;
    uint32_t args[2] = {camera_scratch + 0x6B0, 1};
    memcpy(GPTR(args[0]), position, sizeof position);
    if (town) {
        void_call_guest_this(set, hand, 2, args);
        return 1;
    }
    uint32_t bounds[3] = {camera_scratch + 0x720, args[0], hand + 0x144};
    void_call_guest_this(0x007D4720u, hand, 3, bounds);
    g_esi = bounds[0]; g_edi = args[0];
    void_call_guest(0x007D46B0u, 0, NULL, 1);
    memcpy(position, GPTR(args[0]), sizeof position);
    for (int i = 0; i < 10; ++i) if (!isfinite(position[i])) return 0;
    /* Release the engine's follow target, as its existing manual view actions do. */
    uint32_t none[2] = {0, 0};
    void_call_guest_this(unfollow, hand, 2, none);
    void_call_guest_this(set, hand, 2, args);
    return 1;
}

/* The operator and camera of a screen: the shared preamble of the setters. */
static int camera_parts(uint32_t screen, int kind, uint32_t *camera_out, uint32_t *hand_out, uint32_t *get_out,
                        uint32_t *set_out, uint32_t *unfollow_out)
{
    int town = kind == 2;
    uint32_t table = town ? 0x00E2A64Cu : kind == 1 ? 0x00E1DA84u : 0x00E230E4u;
    uint32_t operator_offset = town ? 0x374u : kind == 1 ? 0x3B8u : 0x5E4u;
    if (kind < 0 || kind > 2 || !void_vm_readable(screen, operator_offset + 4) || MEM32(screen) != table) return 0;
    uint32_t camera = MEM32(screen + 0xA4), hand = MEM32(screen + operator_offset);
    if (!void_vm_readable(hand, town ? 0x178u : 0x14Cu)) return 0;
    if (town && (MEM32(hand) != 0x00E449BCu || MEM32(hand + 0x144) != camera)) return 0;
    uint32_t get = camera_method(camera, 0x54), set = camera_method(hand, 0x50);
    uint32_t unfollow = town ? 0 : camera_method(hand, 0x5C);
    if (!get || !set || (!town && !unfollow)) return 0;
    *camera_out = camera; *hand_out = hand; *get_out = get; *set_out = set; *unfollow_out = unfollow;
    return 1;
}

int void_touch_camera_pose(uint32_t screen, int kind, float pose[10], int set_pose, int immediate)
{
    uint32_t camera, hand, get, set, unfollow;
    if (!camera_parts(screen, kind, &camera, &hand, &get, &set, &unfollow)) return 0;
    if (!set_pose) {
        uint32_t source = void_call_guest_this(get, camera, 0, NULL);
        if (!void_vm_readable(source, 40)) return 0;
        memcpy(pose, GPTR(source), 40);
        for (int i = 0; i < 10; ++i) if (!isfinite(pose[i])) return 0;
        return pose[0] > 0;
    }
    for (int i = 0; i < 10; ++i) if (!isfinite(pose[i])) return 0;
    if (!camera_scratch) camera_scratch = void_galloc(0x800);
    if (!camera_scratch) return 0;
    uint32_t args[2] = {camera_scratch + 0x6B0, immediate ? 1u : 0u};
    memcpy(GPTR(args[0]), pose, 40);
    if (unfollow) {
        uint32_t none[2] = {0, 0};
        void_call_guest_this(unfollow, hand, 2, none);
    }
    void_call_guest_this(set, hand, 2, args);
    return 1;
}

static struct {
    uint32_t camera, screen, phase;
    float height, ratio, centre;
    unsigned stage;
    float idle_rod, idle_pitch, idle_fov, sample_pose[10];
    unsigned stable, fitted;
} framing;
static void_fn original_projection;

static int combat_hud_projection(uint32_t camera)
{
    if (framing.phase == 3 || !void_vm_readable(framing.screen, 0x2E4)) return 0;
    uint32_t state = MEM32(framing.screen + 0x2E0);
    return state == 0x1000 || (state & 0x188) ||
        (framing.idle_rod > 0 && fabsf(MEMF(camera + 0x70) - framing.idle_rod) < .05f &&
         fabsf(MEMF(camera + 0x74) - framing.idle_pitch) < .005f &&
         fabsf(MEMF(camera + 0x80) - framing.idle_fov) < .05f);
}

static void camera_projection(void)
{
    uint32_t camera = g_ecx;
    if (camera != framing.camera || !framing.stage ||
        !void_vm_readable(framing.screen, 0xA8) ||
        MEM32(framing.screen) != (framing.phase == 3 ? 0x00E230E4u : 0x00E1DA84u) ||
        MEM32(framing.screen + 0xA4) != camera ||
        MEMF(0x00F74BE4u) != framing.height ||
        !void_vm_writable(camera, 0x98)) {
        original_projection();
        return;
    }
    /* The deployment controller resets its target every frame. Apply the view
       correction only while building the shared render/picking projection. */
    float rod = MEMF(camera + 0x70), centre = MEMF(camera + 0x60);
    int hud = framing.height < 768 && combat_hud_projection(camera);
    if (framing.height < 768) {
        if (framing.phase == 3) MEMF(camera + 0x60) = centre + framing.centre;
        else if (hud) MEMF(camera + 0x60) = centre / framing.ratio + framing.centre;
    }
    /* Preserve the supplied PC 16:9 framing (native canvas1366x768), including attack close-ups. */
    float fov = MEMF(camera + 0x80);
    uint32_t viewport = ARG(1);
    if (framing.phase != 3 && void_vm_readable(viewport, 8)) {
        float w = MEMF(viewport), h = MEMF(viewport + 4);
        if (isfinite(w) && isfinite(h) && w > 0 && h > 0 && fov > 0 && fov < 180 &&
            (w / h > 1366.0f / 768.0f || (hud && framing.ratio != 1))) {
            double tangent = tan(fov * 0.008726646259971648);
            if (w / h > 1366.0f / 768.0f) tangent *= w / h * (768.0 / 1366.0);
            if (hud) tangent *= framing.ratio;
            MEMF(camera + 0x80) = (float)(atan(tangent) * 114.59155902616465);
        }
    }
    original_projection();
    MEMF(camera + 0x70) = rod;
    MEMF(camera + 0x60) = centre;
    MEMF(camera + 0x80) = fov;
}

void void_touch_adventure_frame(uint32_t screen, float height, float top, float bottom)
{
    if (!void_vm_readable(screen, 0xA8) || MEM32(screen) != 0x00E230E4u ||
        !isfinite(height) || height <= 0 || height >= 768 ||
        !isfinite(top) || !isfinite(bottom) || top < 0 || bottom > height ||
        bottom - top < height * .2f) return;
    uint32_t camera = MEM32(screen + 0xA4);
    if (!void_vm_readable(camera, 0x98) || MEM32(camera) != 0x00E44224u) return;
    if (!original_projection) {
        original_projection = void_dispatch_find(0x007CD0C0u);
        if (!original_projection) return;
        void_dispatch_add(0x007CD0C0u, camera_projection);
    }
    /* Keep native follow/pan targets, but put their centre in the unobscured map. */
    framing.camera = camera; framing.screen = screen; framing.phase = 3;
    framing.height = height; framing.ratio = 1;
    framing.centre = (top + bottom) / height - 1;
    framing.stage = 2;
}

/* Overview, deployment and attack operators retain their original distance and aim. */
void void_touch_combat_frame(uint32_t screen, float width, float height, float hud_top, float top, float bottom)
{
    if (!screen) { framing.camera = 0; return; }
    if (!void_vm_readable(screen, 0x3BC) || MEM32(screen) != 0x00E1DA84u ||
        !isfinite(width) || !isfinite(height) || height <= 0 ||
        !isfinite(hud_top) || hud_top < height * .35f || hud_top > height ||
        !isfinite(top) || !isfinite(bottom) || bottom < top) return;
    uint32_t camera = MEM32(screen + 0xA4);
    if (!void_vm_readable(camera, 0x98) || MEM32(camera) != 0x00E44224u) return;
    if (!original_projection) {
        original_projection = void_dispatch_find(0x007CD0C0u);
        if (!original_projection) return;
        void_dispatch_add(0x007CD0C0u, camera_projection);
    }
    uint32_t state = MEM32(screen + 0x2E0);
    uint32_t phase = state == 0x1000 ? (MEMF(camera + 0x78) < 0 ? 1u : 2u) : 0u;
    if (framing.camera != camera || framing.screen != screen || framing.phase != phase || framing.height != height) {
        framing.ratio = 1;
        framing.centre = 0;
        framing.stable = framing.fitted = 0;
        framing.idle_rod = 0;
    }
    framing.camera = camera; framing.screen = screen; framing.phase = phase;
    framing.height = height;
    if (state == 0x1000 || (state & 0x188)) {
        framing.idle_rod = MEMF(camera + 0x70);
        framing.idle_pitch = MEMF(camera + 0x74);
        framing.idle_fov = MEMF(camera + 0x80);
    }
    if (height < 768 && hud_top < height && (state == 0x1000 || (state & 0x188))) {
        if (!phase) {
            /* Map the original unobscured viewport to the enlarged HUD, keeping its top fixed. */
            float ratio = fmaxf(1, (1 - (height - hud_top) / 768) * height / hud_top);
            framing.ratio = ratio;
            framing.centre = 1 / ratio - 1;
        } else if (!framing.fitted && bottom > top && top >= 0 && bottom <= height) {
            float pose[10]; memcpy(pose, GPTR(camera + 0x70), sizeof pose);
            int stable = 1;
            for (int i = 0; i < 10; ++i)
                if (!isfinite(pose[i]) || fabsf(pose[i] - framing.sample_pose[i]) > .0001f) stable = 0;
            memcpy(framing.sample_pose, pose, sizeof pose);
            framing.stable = stable ? framing.stable + 1 : 0;
            if (framing.stable >= 2) {
                /* Measure once before any shift, so animated labels cannot feed back into the lens. */
                framing.centre = fminf(0, 2 * (hud_top - height * .015f - bottom) / height);
                framing.fitted = 1;
                VLOG("[touch] deployment-hud phase=%u height=%.1f hud=%.1f bottom=%.1f centre=%.3f",
                     phase, height, hud_top, bottom, framing.centre);
            }
        }
    }
    framing.stage = 2;

}

/* Two fingers moved up together tilt the view toward the horizon, within the
 * adventure camera mode's own pitch limits (0x0058A5E0: the mode's
 * {rod, rod, pitch, pitch, yaw, yaw} hard limits; combat uses its operator's
 * pitch bounds, and town keeps its range). */
int void_touch_camera_tilt(uint32_t screen, int kind, float dy)
{
    if (!isfinite(dy) || dy == 0) return 0;
    /* The town's pending UI, modal and busy checks gate tilting as they gate pan and zoom. */
    if (kind == 2 && !camera_town_prepare(screen)) return 0;
    float pose[10];
    if (!void_touch_camera_pose(screen, kind, pose, 0, 0)) return 0;
    int width, height;
    void_input_screen_size(&width, &height);
    if (height <= 0) return 0;
    float low = -1.5f, high = -0.05f;
    if (kind == 1) {
        uint32_t hand = MEM32(screen + 0x3B8);
        if (void_vm_readable(hand + 0x14C, 8)) {
            float a = MEMF(hand + 0x14C), b = MEMF(hand + 0x150);
            if (isfinite(a) && isfinite(b) && a < b && a > -1.6f && b < 0) { low = a; high = b; }
        }
    }
    if (kind == 0 && void_dispatch_find(0x0058A5E0u)) {
        uint32_t limits = void_call_guest_this(0x0058A5E0u, 1000, 0, NULL);
        if (void_vm_readable(limits, 24)) {
            float a = MEMF(limits + 8), b = MEMF(limits + 12);
            if (isfinite(a) && isfinite(b) && a < b && a > -1.6f && b < 1.6f) { low = a; high = b; }
            static int logged;
            if (!logged++) VLOG("[touch] adventure pitch limits %.3f..%.3f (rod %.1f..%.1f)", a, b,
                                MEMF(limits), MEMF(limits + 4));
        }
    }
    float pitch = pose[1] - dy / (float)height * 1.2f * void_port_camera_sensitivity();
    pitch = fminf(high, fmaxf(low, pitch));
    if (!isfinite(pitch) || pitch == pose[1]) return 0;
    pose[1] = pitch;
    return void_touch_camera_pose(screen, kind, pose, 1, 1);
}

static void touch_edge_scroll(void)
{
    if (!void_touch_active_mode()) {
        original_edge_scroll();
        return;
    }
    uint32_t output = ARG(0);
    if (!void_vm_writable(output, 8)) void_lift_trap(0x00835E50u, "touch edge-scroll output");
    MEM32(output) = MEM32(output + 4) = 0;
    g_eax = output;
    g_esp += 12;
}

void void_touch_camera_init(void)
{
    if (original_edge_scroll) return;
    original_edge_scroll = void_dispatch_find(0x00835E50u);
    if (original_edge_scroll) void_dispatch_add(0x00835E50u, touch_edge_scroll);
}
