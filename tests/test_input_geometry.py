"""Exercise the real backbuffer/input/touch mapping helpers across mode changes."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static int locked;
static int input_lock;
static int screen_w = 1280, screen_h = 720, cursor_x = 1200, cursor_y = 700;
static void pthread_mutex_lock(int *p) { (void)p; assert(!locked); locked = 1; }
static void pthread_mutex_unlock(int *p) { (void)p; assert(locked); locked = 0; }
#include "input_geometry.h"
typedef struct { int unused; } void_com_object;
typedef struct { void_com_object com; uint32_t width, height; } d3d_surface;
typedef struct {
    uint32_t pp[14], window;
    d3d_surface *backbuffer, *auto_depth, *rt[4], *ds;
    int fbo_dirty;
} d3d_device;
#define D3DUSAGE_RENDERTARGET 1u
#define D3DUSAGE_DEPTHSTENCIL 2u
#define D3DPOOL_DEFAULT 0u
static d3d_surface surfaces[32];
static unsigned surface_count;
static void void_com_release(void_com_object *p) { assert(p); }
static int bind_surface(d3d_surface **slot, d3d_surface *s) { *slot = s; return 1; }
static void void_window_client_size(uint32_t hwnd, int *w, int *h) { (void)hwnd; *w = 1280; *h = 800; }
static d3d_surface *d3d_surface_new(d3d_device *dev, uint32_t w, uint32_t h, uint32_t f,
    uint32_t usage, uint32_t pool, uint32_t ms) {
    (void)dev; (void)f; (void)usage; (void)pool; (void)ms;
    assert(surface_count < 32);
    d3d_surface *s = &surfaces[surface_count++]; s->width = w; s->height = h; return s;
}
#include "backbuffer.h"
static int native_w = 2944, native_h = 1750;
static int window_lock;
static void *window = &native_w;
static int ANativeWindow_getWidth(void *p) { (void)p; return native_w; }
static int ANativeWindow_getHeight(void *p) { (void)p; return native_h; }
#include "touch_mapping.h"
static void size_is(int expected_w, int expected_h) {
    int w, h; void_input_screen_size(&w, &h); assert(w == expected_w && h == expected_h);
}
int main(void) {
    d3d_device probe = {0}; probe.pp[0] = 640; probe.pp[1] = 480;
    make_backbuffer(&probe); size_is(640, 480);
    assert(cursor_x == 320 && cursor_y == 240);
    probe.pp[0] = 800; probe.pp[1] = 600; /* Reset uses the same helper. */
    make_backbuffer(&probe); size_is(800, 600);
    d3d_device actual = {0}; actual.pp[0] = 1280; actual.pp[1] = 800;
    make_backbuffer(&actual); size_is(1280, 800);
    int gx, gy;
    view_to_game(1472.0f / 2944.0f, 952.0f / 1750.0f, &gx, &gy);
    assert(gx == 640 && gy == 435); /* Actual profile OK button center. */
    view_to_game(0.5f, 0.5f, &gx, &gy); assert(gx == 640 && gy == 400);
    actual.pp[0] = actual.pp[1] = 0; make_backbuffer(&actual); size_is(1280, 800);
    void_input_set_screen_size(0, -1); size_is(1280, 800);
    window = NULL;
    view_to_game(0.75f, 0.25f, &gx, &gy); assert(gx == 960 && gy == 200);
    assert(!locked);
    puts("PASS input geometry: probe, Reset, recreate, window-size fallback, exact profile touch mapping and locked size pair");
    return 0;
}
'''


class InputGeometryTest(unittest.TestCase):
    def test_backbuffer_and_touch_use_same_dimensions(self):
        device = (ROOT / "android/host/d3d9_device.c").read_text(encoding="utf-8")
        inputs = (ROOT / "android/host/input.c").read_text(encoding="utf-8")
        android = (ROOT / "android/host/android_main.c").read_text(encoding="utf-8")
        compile_probe("input_geometry", HARNESS, {
            "input_geometry.h": function(inputs, "void void_input_screen_size(") +
                                function(inputs, "void void_input_set_screen_size("),
            "backbuffer.h": function(device, "static void make_backbuffer("),
            "touch_mapping.h": function(android, "static int map_touch_point(") +
                               function(android, "static void view_to_game("),
        })


if __name__ == "__main__":
    unittest.main()
