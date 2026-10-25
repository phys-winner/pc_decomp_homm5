/* The port's settings as the game's own console variables, so the native
 * options pages (data/UI/uiconsts override) show and change them and the
 * player profile (user_a2.cfg) keeps them:
 *
 *   port_ui_scale            0.5 .. 2     UI virtual-coordinate scale
 *   port_render_scale        0.25 .. 1    backbuffer size against the display
 *   port_camera_sensitivity  0.25 .. 4    touch camera rotation, zoom and tilt
 *   port_fps_limit           0 or 30..240 maximum frame rate; 0 follows the display
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

enum { PORT_UI, PORT_RENDER, PORT_CAMERA, PORT_FPS, PORT_COUNT };
static const char *const port_names[PORT_COUNT] = {
    "port_ui_scale", "port_render_scale", "port_camera_sensitivity", "port_fps_limit",
};
static float port_defaults[PORT_COUNT] = { 1.0f, 1.0f, 1.0f, 60.0f };
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
        /* scratch: name {begin,end,cap} at 0; default {float, wide begin,end,cap} at 12,
           as 0x004039A0 builds them for net_timeout. */
        uint32_t name_chars = guest_string(port_names[i], scratch, 0);
        MEMF(scratch + 12) = value;
        uint32_t value_chars = guest_string(text, scratch + 16, 1);
        if (!name_chars || !value_chars) break;
        const uint32_t args[3] = { port_storage + 4 * i, scratch + 12, 2 };
        g_ecx = scratch;
        g_edx = 0x00499630u;                  /* the engine's float copier */
        uint32_t entry_esp = g_esp;
        for (int a = 2; a >= 0; --a) PUSH32(g_esp, args[a]);
        PUSH32(g_esp, RECOMP_RETADDR);
        sub_00C11400_lifted();
        if (g_esp != entry_esp) void_fatal("port variable registration stack %08X != %08X", g_esp, entry_esp);
        void_gfree(name_chars);
        void_gfree(value_chars);
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
float void_port_fps_limit(void)
{
    float value = port_value(PORT_FPS, 0.0f, 240.0f);
    return value > 0.0f ? fmaxf(30.0f, value) : 0.0f;
}

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
