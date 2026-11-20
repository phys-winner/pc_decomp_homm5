/* The port's settings as the game's own console variables, so the native
 * options pages (data/UI/uiconsts override) show and change them and the
 * player profile (user_a2.cfg) keeps them:
 *
 *   port_ui_scale            0.5 .. 2     UI virtual-coordinate scale
 *   port_render_scale        0.25 .. 1    backbuffer size against the display
 *   port_camera_sensitivity  0.25 .. 4    touch camera rotation, zoom and tilt
 *   port_fps_limit           legacy numeric setting; port_fps_choice owns the active cap
 *   port_cursor_offset_x/y   -0.2 .. 0.2  fraction of the shorter screen side
 *   port_touch_cursor        0 or 1      draw the cursor during finger contact
 *   port_lan_vpn             0 or 1      LAN discovery to listed VPN peers, network.c
 *   port_combat_fit          0 or 1      fit the battlefield in the visible view (default 1)
 *   port_combat_confirm      0 or 1      confirm battlefield gestures (default 0)
 *   port_attack_hints        0 or 1      show alternate attack hints (default 0)
 *   port_combat_route        0 or 1      show movement paths and attack directions (default 1)
 *   port_lod_fix             0 or 1      full-detail creature/hero models on the adventure map (default 0)
 *   port_fog                 0 or 1      the engine's D3D9 fog on OpenGL ES (default 1)
 *   port_battle_blur         0 or 1      smooth battle-entry blur instead of the blocky original (default 0)
 *
 * The frame rate is a combobox like the original resolution one: string
 * variables port_fps_items ("30;60;...", the display's rates from
 * Java, level 0) and port_fps_choice (the chosen item's text, profile level).
 * The engine's string copier 0x00499700 assigns the default's text to a
 * {begin, end, capacity} string storage, which, as the engine's own static
 * initializers make them (0x00DC13E0 for gfx_availible_resolutions), starts
 * as an 8-byte buffer from its allocator 0x008791F0: its assign 0x00404150
 * writes through begin (3.1 addresses; 1.6/2.1 map them in their patch contracts).
 * port_fps_limit stays registered for old profiles.
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

enum { PORT_UI, PORT_RENDER, PORT_CAMERA, PORT_FPS, PORT_CURSOR_X, PORT_CURSOR_Y, PORT_TOUCH_CURSOR, PORT_LAN_VPN,
       PORT_CONSOLE, PORT_WORLD_FILTER, PORT_UI_FILTER, PORT_SHARPNESS, PORT_COMBAT_FIT,
       PORT_SPLIT_HINTS, PORT_SPLIT_ZONES, PORT_COMBAT_CONFIRM, PORT_ATTACK_HINTS, PORT_COMBAT_ROUTE,
       PORT_LOD_FIX, PORT_FOG, PORT_BATTLE_BLUR, PORT_FAST_AI, PORT_ARMY_ACTIONS, PORT_SHADOW_FIX,
       PORT_COUNT };
static const char *const port_names[PORT_COUNT] = {
    "port_ui_scale", "port_render_scale", "port_camera_sensitivity", "port_fps_limit",
    "port_cursor_offset_x", "port_cursor_offset_y", "port_touch_cursor", "port_lan_vpn",
    "port_console", "port_world_filter", "port_ui_filter", "port_sharpness", "port_combat_fit",
    "port_split_hints", "port_split_zones", "port_combat_confirm", "port_attack_hints", "port_combat_route",
    "port_lod_fix", "port_fog", "port_battle_blur", "port_fast_ai", "port_army_actions", "port_shadow_fix",
};
static float port_defaults[PORT_COUNT] = { 1.0f, 1.0f, 1.0f, 60.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                         0.0f, 2.0f, 1.0f, 0.25f, 1.0f
                                         , 1.0f, 1.0f, 0.0f, 0.0f, 1.0f
                                         , 0.0f, 1.0f, 0.0f, 1.0f, 0.0f
                                       };
enum { PORT_TEXT_FPS_ITEMS, PORT_TEXT_FPS_CHOICE, PORT_TEXT_COUNT };
static const char *const port_text_names[PORT_TEXT_COUNT] = { "port_fps_items", "port_fps_choice" };
static const uint32_t port_text_levels[PORT_TEXT_COUNT] = { 0, 2 };
/* Plain numbers: a profile stores the choice unquoted (setvar port_fps_choice = 60). */
static char port_text_defaults[PORT_TEXT_COUNT][256] = { "20;30;60", "60" };
static uint32_t port_text_storage;        /* PORT_TEXT_COUNT guest strings {begin, end, capacity} */
static float port_applied[PORT_COUNT] = { -1.0f, -1.0f, -1.0f, -1.0f, [PORT_ARMY_ACTIONS] = -1.0f };
static uint32_t port_storage;             /* PORT_COUNT guest floats */
static int port_state;                    /* 0 not yet, 1 registering, 2 registered */
/* The interface scale is a list (tools/port_ui.py: OPTION_COMBO_BOX). A native combobox stores
 * its item's index, so the list has a variable of its own, port_ui_scale_item (level 2, -1 until
 * known); port_ui_scale keeps the value everything else reads. Profiles from the former slider hold
 * only the value: the list then shows the nearest item and the saved value stays as it is until
 * the player picks an item. The items must match port_ui.py's port_ui_scale values. */
static const float port_ui_items[] = { 0.5f, 0.75f, 1.0f, 1.25f, 1.5f, 1.75f, 2.0f };
enum { PORT_UI_ITEMS = (int)(sizeof port_ui_items / sizeof *port_ui_items) };
static uint32_t port_ui_item_storage;     /* guest float: the list's item index */
static float port_ui_item_seen, port_ui_value_seen;
static int port_ui_list_synced;
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
    port_ui_item_storage = void_galloc(4);
    if (port_ui_item_storage) {
        MEMF(port_ui_item_storage) = -1.0f;
        if (!register_variable(scratch, "port_ui_scale_item", port_ui_item_storage, 0x00499630u, -1.0f, "-1", 2))
            port_ui_item_storage = 0;
    }
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
int void_port_lan_vpn(void) { return port_value(PORT_LAN_VPN, 0.0f, 1.0f) >= 0.5f; }
int void_port_console_enabled(void) { return port_value(PORT_CONSOLE, 0.0f, 1.0f) >= 0.5f; }
int void_port_combat_fit(void) { return port_value(PORT_COMBAT_FIT, 0.0f, 1.0f) >= 0.5f; }
int void_port_split_hints(void) { return port_value(PORT_SPLIT_HINTS, 0.0f, 1.0f) >= 0.5f; }
int void_port_split_zones(void) { return port_value(PORT_SPLIT_ZONES, 0.0f, 1.0f) >= 0.5f; }
int void_port_combat_confirm(void) { return port_value(PORT_COMBAT_CONFIRM, 0.0f, 1.0f) >= 0.5f; }
int void_port_attack_hints(void) { return port_value(PORT_ATTACK_HINTS, 0.0f, 1.0f) >= 0.5f; }
int void_port_combat_route(void) { return port_value(PORT_COMBAT_ROUTE, 0.0f, 1.0f) >= 0.5f; }
int void_port_army_actions(void) { return port_value(PORT_ARMY_ACTIONS, 0.0f, 1.0f) >= 0.5f; }

static void port_set_variable(const char *name, float value);
/* Guest UI thread, after accepting the physical-mouse suggestion. */
void void_port_enable_army_actions(void)
{
    if (port_state != 2 || !port_storage) return;
    /* The storage is only the copier's mirror: the options page and the profile writer read the
     * engine's own value, so set it there and save as the options page does. 0x008353E0 writes
     * the global p2pdir.cfg and, unless profile_name is still "default_profile", the current
     * profile; it takes no arguments and leaves the stack as it was. */
    port_set_variable(port_names[PORT_ARMY_ACTIONS], 1.0f);
    void_call_guest(0x008353E0u, 0, NULL, 0);
    void_log("[port] army actions enabled for the mouse");
}
int void_port_lod_fix(void) { return port_value(PORT_LOD_FIX, 0.0f, 1.0f) >= 0.5f; }
int void_port_fog(void) { return port_value(PORT_FOG, 0.0f, 1.0f) >= 0.5f; }
int void_port_battle_blur(void) { return port_value(PORT_BATTLE_BLUR, 0.0f, 1.0f) >= 0.5f; }
int void_port_shadow_fix(void) { return port_value(PORT_SHADOW_FIX, 0.0f, 1.0f) >= 0.5f; }
int void_port_fast_ai(void) { return port_value(PORT_FAST_AI, 0.0f, 1.0f) >= 0.5f; }
int void_port_filter(int ui) { return (int)lroundf(port_value(ui ? PORT_UI_FILTER : PORT_WORLD_FILTER, 0.0f, ui ? 3.0f : 2.0f)); }
float void_port_sharpness(void) { return port_value(PORT_SHARPNESS, 0.0f, 1.0f); }

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

/* Java, before the game starts: each display rate and its /2 and /3 cadences.
 * Names are numeric for the original string combobox/profile. Java chooses the
 * lowest compatible display mode for the selected cap (30 -> 60/2, not 90/3).
 * Do not lroundf NaN/Inf supplied by a broken display service. */
void void_port_set_refresh_rates(const float *rates, int count)
{
    int list[64], n = 0;
    const float fallback = 60;
    int valid = 0;
    for (int i = 0; rates && i < count; ++i)
        if (isfinite(rates[i]) && rates[i] >= 30 && rates[i] <= 240) { valid = 1; break; }
    if (!valid) { rates = &fallback; count = 1; }
    for (int i = 0; i < count; ++i) {
        if (!isfinite(rates[i]) || rates[i] < 30 || rates[i] > 240) continue;
        for (int divisor = 1; divisor <= 3; ++divisor) {
            int rate = (int)lroundf(rates[i] / (float)divisor);
            if (rate < 10 || rate > 240) continue;
            int at = 0;
            while (at < n && list[at] < rate) ++at;
            if ((at < n && list[at] == rate) || n == 64) continue;
            memmove(list + at + 1, list + at, sizeof *list * (size_t)(n - at));
            list[at] = rate;
            ++n;
        }
    }
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
    return value >= 10 && value <= 240 ? (float)value : 60.0f;
}

#include "perf_diag.h"
/* The display's actual refresh rate (PerfMonitor.java: Display after each change, or the
 * Choreographer's measured rate when the two disagree by more than 10 %): HyperOS's thermal
 * limit, power saving or the system's own setting may drop it below the player's choice. The
 * limiter then paces at the largest cadence refresh/n (n = 1..3) not above the choice: 120 on
 * a 60 Hz panel -> 60, 40 on 60 Hz -> 30, 60 on 120 Hz -> 60. The choice itself, the profile
 * and the setFrameRate vote stay the player's, so the cap returns when the panel does. The
 * no-refresh-follow flag file keeps pacing by the choice alone. */
static volatile uint32_t display_hz_bits;   /* Java writes, the game's and sampler threads read */

void void_port_set_display_rate(float hz)
{
    if (!isfinite(hz) || hz < 20.0f || hz > 480.0f) hz = 0.0f;
    uint32_t bits;
    memcpy(&bits, &hz, sizeof bits);
    display_hz_bits = bits;
}

float void_port_display_rate(void)
{
    uint32_t bits = display_hz_bits;
    float hz;
    memcpy(&hz, &bits, sizeof hz);
    return hz;
}

/* Pure: the cadence for a choice on a panel (0 Hz: unknown, the choice applies). */
static float effective_cap(float choice, float hz, int *divisor)
{
    *divisor = 0;
    if (hz <= 0.0f || choice <= 0.0f) return choice;
    for (int n = 1; n <= 3; ++n)
        if (hz / (float)n <= choice + 0.5f) { *divisor = n; return hz / (float)n; }
    return choice;
}

static int pace_divisor;

float void_port_effective_fps(void)
{
    static float logged_choice = -1.0f, logged_hz = -1.0f, logged_cap = -1.0f;
    if (logged_cap < 0.0f) void_perf_log_summary();
    float choice = void_port_fps_limit(), hz = void_port_display_rate();
    if (void_perf_options() & PERF_OPT_NO_REFRESH_FOLLOW) hz = 0.0f;
    int divisor;
    float cap = effective_cap(choice, hz, &divisor);
    pace_divisor = divisor;
    if (cap != logged_cap || hz != logged_hz || choice != logged_choice) {
        if (logged_cap >= 0.0f && hz != logged_hz && hz > 0.0f && logged_hz > 0.0f)
            void_log("[refresh] %.0f→%.0f Hz, effective cap %.0f (choice %.0f)", logged_hz, hz, cap, choice);
        else if (logged_cap >= 0.0f && cap != logged_cap)
            void_log("[refresh] %.0f Hz, effective cap %.0f (choice %.0f)", hz, cap, choice);
        if (void_diag_on && logged_cap >= 0.0f)
            void_log("[hyperos] event t=%.3f diag=1 kind=eff_cap from=%.1f to=%.1f choice=%.1f display_hz=%.1f",
                     (double)void_perf_now_ns() / 1e6, logged_cap, cap, choice, hz);
        logged_cap = cap; logged_hz = hz; logged_choice = choice;
    }
    return cap;
}

/* The cap equals the refresh (n = 1) and the timer may yield to eglSwapInterval(1);
 * pace-timer keeps the timer, pace-vsync forces this whenever the cadence is 1. */
int void_port_vsync_paced(void)
{
    unsigned options = void_perf_options();
    if (options & PERF_OPT_PACE_TIMER) return 0;
    return pace_divisor == 1;
}

void void_port_scales(float *ui, float *render);
void void_port_scales(float *ui, float *render)
{
    *ui = port_value(PORT_UI, 0.5f, 2.0f);
    *render = port_value(PORT_RENDER, 0.25f, 1.0f);
}

/* The engine keeps each variable's value itself (the options pages and the profile writer
 * 0x00C11A20 read it); the registered storage is only the copier's mirror. 0x00C11900 is the
 * original setter (fastcall: ECX name {begin,end,cap}, EDX value {float, UTF-16 text},
 * stack: profile level, -1 keeps it; RET 4): it updates the value and runs the copiers. */
void sub_00C11900(void);

static void port_set_variable(const char *name, float value)
{
    uint32_t scratch = void_galloc(32);
    if (!scratch) return;
    char text[32];
    snprintf(text, sizeof text, "%g", (double)value);
    uint32_t name_chars = guest_string(name, scratch, 0);
    MEMF(scratch + 12) = value;
    uint32_t value_chars = guest_string(text, scratch + 16, 1);
    if (name_chars && value_chars) {
        void_regs saved;
        void_regs_save(&saved);
        g_ecx = scratch;
        g_edx = scratch + 12;
        uint32_t entry_esp = g_esp;
        PUSH32(g_esp, 0xFFFFFFFFu);
        PUSH32(g_esp, RECOMP_RETADDR);
        sub_00C11900();
        if (g_esp != entry_esp) void_fatal("port variable setter stack %08X != %08X", g_esp, entry_esp);
        void_regs_load(&saved);
    }
    if (name_chars) void_gfree(name_chars);
    if (value_chars) void_gfree(value_chars);
    void_gfree(scratch);
}

/* Guest window thread: an item the player picked (or a profile's) sets the value; a value
 * without an item (a slider profile, a Java seed, the console) selects its nearest item. */
static void port_ui_list_pump(void)
{
    if (!port_ui_item_storage || !port_storage) return;
    float item = MEMF(port_ui_item_storage), value = MEMF(port_storage + 4 * PORT_UI);
    int index = isfinite(item) && item >= 0.0f && item < (float)PORT_UI_ITEMS ? (int)item : -1;
    if (index >= 0 && (!port_ui_list_synced || item != port_ui_item_seen)) {
        if (value != port_ui_items[index]) {
            port_set_variable(port_names[PORT_UI], port_ui_items[index]);
            void_log("[port] interface scale item %d: %g", index, (double)port_ui_items[index]);
        }
    } else if (index < 0 || !port_ui_list_synced || value != port_ui_value_seen) {
        float scale = port_value(PORT_UI, 0.5f, 2.0f);
        int nearest = 0;
        for (int i = 1; i < PORT_UI_ITEMS; ++i)
            if (fabsf(port_ui_items[i] - scale) < fabsf(port_ui_items[nearest] - scale)) nearest = i;
        if (item != (float)nearest) {
            port_set_variable("port_ui_scale_item", (float)nearest);
            void_log("[port] interface scale %g shown as item %d", (double)scale, nearest);
        }
    }
    port_ui_item_seen = MEMF(port_ui_item_storage);
    port_ui_value_seen = MEMF(port_storage + 4 * PORT_UI);
    port_ui_list_synced = 1;
}

/* Guest window thread, every frame: options and profiles change the storage. */
void void_port_settings_pump(void)
{
    if (port_state != 2) return;
    port_ui_list_pump();
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
    float army_actions = (float)void_port_army_actions();
    if (army_actions != port_applied[PORT_ARMY_ACTIONS]) {
        port_applied[PORT_ARMY_ACTIONS] = army_actions;
        void_android_settings_changed(4, army_actions);
    }
    float camera = void_port_camera_sensitivity();
    if (camera != port_applied[PORT_CAMERA]) {
        port_applied[PORT_CAMERA] = camera;
        void_android_settings_changed(PORT_CAMERA, camera);
    }
    float fps = void_port_fps_limit();
    if (fps != port_applied[PORT_FPS]) {
        port_applied[PORT_FPS] = fps;
        void_android_settings_changed(PORT_FPS, fps);
    }
}
