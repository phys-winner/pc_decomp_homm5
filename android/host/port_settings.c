/* The port's settings as the game's own console variables, so the native
 * options pages (data/UI/uiconsts override) show and change them and the
 * player profile (user_a2.cfg) keeps them:
 *
 *   port_ui_scale            0.5 .. 2     UI virtual-coordinate scale
 *   port_render_scale        0.25 .. 1    backbuffer size against the display
 *   port_camera_sensitivity  0.25 .. 4    touch camera rotation, zoom and tilt
 *   port_fps_limit           0 or 30..240 maximum frame rate; 0 follows the display
 *   port_cursor_offset_x/y   -0.2 .. 0.2  fraction of the shorter screen side
 *   port_touch_cursor        0 or 1      draw the cursor during finger contact
 *   port_lan_vpn             0 or 1      (ToE) LAN discovery to listed VPN peers, network.c
 *
 * ToE's frame rate is a combobox like the original resolution one: string
 * variables port_fps_items ("30;60;...", the display's rates from
 * Java, level 0) and port_fps_choice (the chosen item's text, profile level).
 * The engine's string copier 0x00499700 assigns the default's text to a
 * {begin, end, capacity} string storage, which, as the engine's own static
 * initializers make them (0x00DC13E0 for gfx_availible_resolutions), starts
 * as an 8-byte buffer from its allocator 0x008791F0: its assign 0x00404150
 * writes through begin. port_fps_limit stays registered for old profiles and
 * Vanilla/HoF.
 *
 * The engine registers its variables from static initializers through
 * 0x00C11400 (ECX name string, EDX value copier, stack: storage, default,
 * profile level; RET 0xC). The first registration, by then the C runtime's
 * heap is up, registers these as level-2 (profile) floats before any
 * profile runs. The frame pump applies changed values. */
#include "host.h"
#include "touch.h"
#include <math.h>
#include <string.h>

void sub_00C11400_lifted(void);

#ifdef VOID_ANDROID_APP
void void_android_settings_changed(int which, float value);
#else
static void void_android_settings_changed(int which, float value) { (void)which; (void)value; }
#endif

#ifndef HOMM5_LEGACY_UI
enum { PORT_UI, PORT_RENDER, PORT_CAMERA, PORT_FPS, PORT_CURSOR_X, PORT_CURSOR_Y, PORT_TOUCH_CURSOR, PORT_LAN_VPN, PORT_COUNT };
static const char *const port_names[PORT_COUNT] = {
    "port_ui_scale", "port_render_scale", "port_camera_sensitivity", "port_fps_limit",
    "port_cursor_offset_x", "port_cursor_offset_y", "port_touch_cursor", "port_lan_vpn",
};
static float port_defaults[PORT_COUNT] = { 1.0f, 1.0f, 1.0f, 60.0f, 0.0f, 0.0f, 0.0f, 0.0f };
enum { PORT_TEXT_FPS_ITEMS, PORT_TEXT_FPS_CHOICE, PORT_TEXT_COUNT };
static const char *const port_text_names[PORT_TEXT_COUNT] = { "port_fps_items", "port_fps_choice" };
static const uint32_t port_text_levels[PORT_TEXT_COUNT] = { 0, 2 };
/* Plain numbers: a profile stores the choice unquoted (setvar port_fps_choice = 60). */
static char port_text_defaults[PORT_TEXT_COUNT][256] = { "30;60", "60" };
static uint32_t port_text_storage;        /* PORT_TEXT_COUNT guest strings {begin, end, capacity} */
#else
enum { PORT_UI, PORT_RENDER, PORT_CAMERA, PORT_FPS, PORT_CURSOR_X, PORT_CURSOR_Y, PORT_TOUCH_CURSOR, PORT_COUNT };
static const char *const port_names[PORT_COUNT] = {
    "port_ui_scale", "port_render_scale", "port_camera_sensitivity", "port_fps_limit",
    "port_cursor_offset_x", "port_cursor_offset_y", "port_touch_cursor",
};
static float port_defaults[PORT_COUNT] = { 1.0f, 1.0f, 1.0f, 60.0f, 0.0f, 0.0f, 0.0f };
#endif
static float port_applied[PORT_COUNT] = { -1.0f, -1.0f, -1.0f, -1.0f };
static uint32_t port_storage;             /* PORT_COUNT guest floats */
static int port_state;                    /* 0 not yet, 1 registering, 2 registered */
static pthread_mutex_t port_lock = PTHREAD_MUTEX_INITIALIZER;

/* Java's saved values seed the defaults (they predate the profile variables). */
void void_port_set_default(int which, float value)
{
    if (which < 0 || which >= PORT_FPS || !isfinite(value) || value <= 0) return;
    pthread_mutex_lock(&port_lock);
    port_defaults[which] = value;
    pthread_mutex_unlock(&port_lock);
}

/* A guest string object as the engine builds them: {begin, end, capacity},
 * of bytes (`wide` 0: the variable's name) or of UTF-16 units (`wide` 1: the
 * default's text, which 0x0040E960 copies a unit at a time up to `end`). */
static uint32_t guest_string(const char *text, uint32_t object, int wide)
{
    size_t length = strlen(text), unit = wide ? 2 : 1;
    uint32_t chars = void_galloc((uint32_t)((length + 1) * unit));
    if (!chars) return 0;
    for (size_t i = 0; i <= length; ++i) {
        if (wide) MEM16(chars + 2 * (uint32_t)i) = (uint8_t)text[i];
        else MEM8(chars + (uint32_t)i) = (uint8_t)text[i];
    }
    MEM32(object) = chars;
    MEM32(object + 4) = chars + (uint32_t)(length * unit);
    MEM32(object + 8) = chars + (uint32_t)((length + 1) * unit);
    return chars;
}

/* scratch: name {begin,end,cap} at 0; default {float, wide begin,end,cap} at 12,
   as 0x004039A0 builds them for net_timeout. */
static int register_variable(uint32_t scratch, const char *name, uint32_t storage, uint32_t copier,
                             float value, const char *text, uint32_t level)
{
    uint32_t name_chars = guest_string(name, scratch, 0);
    MEMF(scratch + 12) = value;
    uint32_t value_chars = guest_string(text, scratch + 16, 1);
    if (!name_chars || !value_chars) return 0;
    const uint32_t args[3] = { storage, scratch + 12, level };
    g_ecx = scratch;
    g_edx = copier;
    uint32_t entry_esp = g_esp;
    for (int a = 2; a >= 0; --a) PUSH32(g_esp, args[a]);
    PUSH32(g_esp, RECOMP_RETADDR);
    sub_00C11400_lifted();
    if (g_esp != entry_esp) void_fatal("port variable registration stack %08X != %08X", g_esp, entry_esp);
    void_gfree(name_chars);
    void_gfree(value_chars);
    return 1;
}

static void register_port_variables(void)
{
    port_storage = void_galloc(4 * PORT_COUNT);
    uint32_t scratch = void_galloc(32);
    if (!port_storage || !scratch) { void_log("[port] settings: no guest memory"); return; }
    for (int i = 0; i < PORT_COUNT; ++i) {
        pthread_mutex_lock(&port_lock);
        float value = port_defaults[i];
        pthread_mutex_unlock(&port_lock);
        MEMF(port_storage + 4 * i) = value;
        char text[32];
        snprintf(text, sizeof text, "%g", (double)value);
        if (!register_variable(scratch, port_names[i], port_storage + 4 * i, 0x00499630u /* float copier */,
                               value, text, 2)) break;
    }
#ifndef HOMM5_LEGACY_UI
    port_text_storage = void_galloc(12 * PORT_TEXT_COUNT);
    if (port_text_storage) {
        for (int i = 0; i < PORT_TEXT_COUNT; ++i) {
            const uint32_t bytes = 8;
            uint32_t buffer = void_call_guest(0x008791F0u, 1, &bytes, 0), storage = port_text_storage + 12 * (uint32_t)i;
            MEM32(storage) = MEM32(storage + 4) = buffer;
            MEM32(storage + 8) = buffer ? buffer + bytes : 0;
        }
        pthread_mutex_lock(&port_lock);
        for (int i = 0; i < PORT_TEXT_COUNT; ++i)
            if (!register_variable(scratch, port_text_names[i], port_text_storage + 12 * i, 0x00499700u /* string copier */,
                                   0.0f, port_text_defaults[i], port_text_levels[i])) break;
        void_log("[port] frame rates: %s (default %s)", port_text_defaults[PORT_TEXT_FPS_ITEMS],
                 port_text_defaults[PORT_TEXT_FPS_CHOICE]);
        pthread_mutex_unlock(&port_lock);
    }
#endif
    void_gfree(scratch);
    void_log("[port] settings registered: ui %g, render %g, camera %g", (double)MEMF(port_storage),
             (double)MEMF(port_storage + 4), (double)MEMF(port_storage + 8));
}

/* Variable registration: the first one also registers the port's. */
void sub_00C11400(void)
{
    if (port_state) { sub_00C11400_lifted(); return; }
    port_state = 1;
    sub_00C11400_lifted();
    uint32_t result = g_eax, ebx = g_ebx, esi = g_esi, edi = g_edi, ebp = g_ebp;
    uint32_t ecx = g_ecx, edx = g_edx;
    register_port_variables();
    g_eax = result; g_ebx = ebx; g_esi = esi; g_edi = edi; g_ebp = ebp;
    g_ecx = ecx; g_edx = edx;
    port_state = 2;
}

static float port_value(int which, float low, float high)
{
    if (port_state != 2 || !port_storage) return port_defaults[which];
    float value = MEMF(port_storage + 4 * which);
    if (!isfinite(value)) value = port_defaults[which];
    return fminf(high, fmaxf(low, value));
}

float void_port_camera_sensitivity(void) { return port_value(PORT_CAMERA, 0.25f, 4.0f); }
float void_port_cursor_offset(int vertical) { return port_value(vertical ? PORT_CURSOR_Y : PORT_CURSOR_X, -0.2f, 0.2f); }
int void_port_touch_cursor(void) { return port_value(PORT_TOUCH_CURSOR, 0.0f, 1.0f) >= 0.5f; }
#ifndef HOMM5_LEGACY_UI
int void_port_lan_vpn(void) { return port_value(PORT_LAN_VPN, 0.0f, 1.0f) >= 0.5f; }

/* Leading decimal of a registered string variable ("60" -> 60), 0 if none. */
static int port_text_number(int which)
{
    if (port_state != 2 || !port_text_storage) return 0;
    uint32_t text = port_text_storage + 12 * (uint32_t)which, begin = MEM32(text), end = MEM32(text + 4);
    if (!begin || end < begin || end - begin > 64 || !void_vm_readable(begin, end - begin)) return 0;
    int value = 0;
    for (uint32_t p = begin; p < end && MEM8(p) >= '0' && MEM8(p) <= '9' && value < 10000; ++p)
        value = value * 10 + (MEM8(p) - '0');
    return value;
}

/* Java, before the game starts: the display's refresh rates make the items,
 * half-rate 30 first; 60 (or the nearest lower rate) is the default. */
void void_port_set_refresh_rates(const float *rates, int count)
{
    int list[16], n = 0;
    list[n++] = 30;
    for (int i = 0; i < count; ++i) {
        int rate = (int)lroundf(rates[i]);
        if (rate < 45 || rate > 240) continue;
        int at = 0;
        while (at < n && list[at] < rate) ++at;
        if (at < n && list[at] == rate) continue;
        if (n == 16) break;
        memmove(list + at + 1, list + at, sizeof *list * (size_t)(n - at));
        list[at] = rate;
        ++n;
    }
    if (n == 1) list[n++] = 60;
    char items[256] = "";
    int chosen = list[0];
    for (int i = 0; i < n; ++i) {
        size_t used = strlen(items);
        snprintf(items + used, sizeof items - used, "%s%d", i ? ";" : "", list[i]);
        if (list[i] <= 60) chosen = list[i];
    }
    pthread_mutex_lock(&port_lock);
    snprintf(port_text_defaults[PORT_TEXT_FPS_ITEMS], sizeof port_text_defaults[0], "%s", items);
    snprintf(port_text_defaults[PORT_TEXT_FPS_CHOICE], sizeof port_text_defaults[0], "%d", chosen);
    pthread_mutex_unlock(&port_lock);
}

float void_port_fps_limit(void)
{
    int value = port_text_number(PORT_TEXT_FPS_CHOICE);
    return value >= 30 && value <= 240 ? (float)value : 60.0f;
}
#else
float void_port_fps_limit(void)
{
    float value = port_value(PORT_FPS, 0.0f, 240.0f);
    return value > 0.0f ? fmaxf(30.0f, value) : 0.0f;
}
#endif

/* Guest window thread, every frame: options and profiles change the storage. */
void void_port_settings_pump(void)
{
    if (port_state != 2) return;
    float ui = port_value(PORT_UI, 0.5f, 2.0f), render = port_value(PORT_RENDER, 0.25f, 1.0f);
    if (ui != port_applied[PORT_UI]) {
        port_applied[PORT_UI] = ui;
        void_touch_set_scale(ui);
        void_android_settings_changed(PORT_UI, ui);
    }
    if (render != port_applied[PORT_RENDER]) {
        port_applied[PORT_RENDER] = render;
        void_touch_set_render_scale(render);
        void_android_settings_changed(PORT_RENDER, render);
    }
    float camera = void_port_camera_sensitivity();
    if (camera != port_applied[PORT_CAMERA]) {
        port_applied[PORT_CAMERA] = camera;
        void_android_settings_changed(PORT_CAMERA, camera);
    }
}
