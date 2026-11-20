"""Exercise the real menu loader with the original renderer and actor calls stubbed."""
import json
import unittest

from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct { unsigned width, height; } d3d_surface;
typedef struct {
    uint32_t frame;
    d3d_surface *backbuffer;
    struct { uint32_t guest; } com;
} d3d_device;
typedef int void_regs;
static d3d_surface mock_surface = {1920, 1080};
static d3d_device mock_device = {100, &mock_surface, {0}};
static d3d_device *g_d3d_device = &mock_device;
static uint32_t memory[256];
#define MEM32(address) memory[(address) / 4]
static uint32_t void_thread_id(void) { return 7; }
static void void_regs_save(void_regs *regs) { *regs = 0; }
static void void_regs_load(const void_regs *regs) { (void)regs; }
static void void_log(const char *format, ...) { (void)format; }
static int void_vm_readable(uint32_t at, uint32_t bytes) { return at && at + bytes <= sizeof memory; }
static uint32_t void_galloc(uint32_t size) { assert(size == 0x5c); return 0x100; }
static uint32_t void_call_guest(uint32_t va, int n, const uint32_t *args, int pops)
{ (void)va; (void)n; (void)args; (void)pops; abort(); }
static unsigned clears, loaded, assembled, attached, published;
static uint32_t g_ecx, g_esp;
enum { ATTACH = 77, OWNER = 0x20, COLLECTION = 0x40, WORLD = 0x60, UPDATE = 78 };
static void mock_attach(void) { ++attached; g_esp += 8; }
static void (*void_resolve(uint32_t method))(void)
{ assert(method == ATTACH); return mock_attach; }
static int android_ready;
static int void_android_menu_ready(void) { return android_ready; }
#define VOID_ANDROID_APP 1
static void d3d_gl_fill(d3d_surface *target, const uint32_t *rect, uint32_t color)
{
    assert(target == &mock_surface && color == 0xff5e4a47u);
    assert(rect[0] == 0 && rect[1] == 0 && rect[2] == mock_surface.width && rect[3] == mock_surface.height);
    ++clears;
}

static uint32_t void_call_guest_this(uint32_t va, uint32_t scene, int n, const uint32_t *args);
#include "main_menu_impl.h"

enum { SCREEN = 3, SCENE = 5, VIEW = 1, ARENA = 0x200, ACTORS = 0x300 };

static uint32_t void_call_guest_this(uint32_t va, uint32_t receiver, int n, const uint32_t *args)
{
    if (va == ATTACH) {
        assert(receiver == OWNER && n == 1 && args[0] == COLLECTION && assembled == 1);
        ++attached;
        return 0;
    }
    if (va == UPDATE) {
        assert(receiver == WORLD && n == 0 && !args && attached == 2);
        ++published;
        return 0;
    }
    if (va == 0x00933db0u) {
        assert(n == 0 && !args && receiver == ACTORS + loaded * 8);
        ++loaded;
        return 0;
    }
    assert(va == 0x00a867c0 && receiver == SCENE && n == 1 && args[0] == VIEW);
    assert(loaded == 2 && void_menu_scene_slice(SCENE, ARENA, args[0]) == ARENA);
    ++assembled;
    return 0;
}

static uint32_t open_menu(void)
{
    void_menu_scene_begin(SCREEN, 0, WORLD);
    uint32_t result = void_menu_scene_slice(SCENE, ARENA, VIEW);
    g_ecx = OWNER;
    g_esp = 0x50;
    MEM32(OWNER) = 0x30;
    MEM32(0x30) = ATTACH;
    MEM32(g_esp + 4) = COLLECTION;
    void_menu_scene_attach();
    assert(g_esp == 0x58);
    void_menu_scene_end();
    return result;
}

int main(void)
{
    MEM32(ARENA + ARENA_OBJECTS) = ACTORS;
    MEM32(ARENA + ARENA_OBJECTS + 4) = ACTORS + 16;
    MEM32(WORLD) = 0x68;
    MEM32(0x68) = UPDATE;
    _putenv("PORT_OPTION_MAIN_MENU_3D=");
    _putenv("PORT_OPTION_FAST_MAIN_MENU=");
    assert(open_menu() == ARENA);
    void_menu_clear(SCREEN);
    assert(clears == 0 && attached == 1);

    _putenv("PORT_OPTION_FAST_MAIN_MENU=1");
    uint32_t proxy = open_menu();
    assert(proxy != ARENA && MEM32(proxy + ARENA_OBJECTS) == MEM32(proxy + ARENA_OBJECTS + 4));
    void_menu_scene_tick(SCREEN);
    mock_device.frame += 12;
    void_menu_scene_tick(SCREEN);
    assert(!loaded && !menu.first_frame);
    android_ready = 1;
    for (mock_device.frame = 100; mock_device.frame < 102; ++mock_device.frame) {
        void_menu_scene_tick(SCREEN);
        void_menu_clear(SCREEN);
        assert(loaded == 0);
    }
    void_menu_scene_tick(SCREEN + 1);
    assert(loaded == 0);
    void_menu_scene_tick(SCREEN);
    void_menu_scene_tick(SCREEN);
    void_menu_clear(SCREEN);
    assert(loaded == 1 && clears == 3 && attached == 1);
    ++mock_device.frame;
    void_menu_scene_tick(SCREEN);
    void_menu_clear(SCREEN);
    assert(loaded == 2 && clears == 4 && attached == 1 && !assembled);
    ++mock_device.frame;
    void_menu_scene_tick(SCREEN);
    void_menu_clear(SCREEN);
    assert(loaded == 2 && clears == 4 && assembled == 1 && published == 1);
    assert(MEM32(ARENA + ARENA_OBJECTS + 4) == ACTORS + 16);

    _putenv("PORT_OPTION_MAIN_MENU_3D=0");
    assert(open_menu() == proxy);
    void_menu_scene_tick(SCREEN);
    void_menu_clear(SCREEN);
    assert(loaded == 2 && clears == 5);
    _putenv("PORT_OPTION_MAIN_MENU_3D=1");
    MEM32(ARENA + ARENA_OBJECTS + 4) = ACTORS;
    assert(open_menu() == ARENA);
    void_menu_clear(SCREEN);
    assert(clears == 6);
    return 0;
}
'''


class MainMenuTest(unittest.TestCase):
    def test_launch_modes_and_static_mod(self):
        source = (ROOT / "android/host/main_menu.c").read_text(encoding="utf-8")
        compile_probe("main-menu", HARNESS, {"main_menu_impl.h": source, "d3d9_internal.h": ""})

    def test_launcher_defaults(self):
        launcher = json.loads((ROOT / "android/port.json").read_text(encoding="utf-8"))
        defaults = {option["key"]: option["default"] for option in launcher["options"]}
        self.assertEqual(defaults["main_menu_3d"], "1")
        self.assertEqual(defaults["fast_main_menu"], "0")
