"""Run production input.c through its event pump, including DirectInput receipts."""
import unittest
from test_static_tls import ROOT, compile_probe


HOST = r'''
#pragma once
#include <assert.h>
#include <stdint.h>
#include <string.h>
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static void pthread_mutex_lock(pthread_mutex_t *p) { assert(!*p); *p = 1; }
static void pthread_mutex_unlock(pthread_mutex_t *p) { assert(*p); *p = 0; }
#define VLOG(...) ((void)0)
static uint64_t now_ns=1000000000ull;
static uint64_t void_monotonic_ns(void) {return now_ns;}
static uint32_t void_tick_ms(void) { static uint32_t time; return ++time; }
static uint32_t void_window_main(void) { return 0x10010; }
static void void_post_message(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp);
static unsigned touch_pumps;
static void void_touch_pump(void) { ++touch_pumps; }
'''

HARNESS = r'''
#include <stdio.h>
#include "host.h"
static uint32_t captured_msg, captured_wp, captured_lp;
static unsigned mouse_messages;
static void void_post_message(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp) {
    assert(hwnd == 0x10010);
    if (msg < 0x200) return;
    ++mouse_messages; captured_msg = msg; captured_wp = wp; captured_lp = lp;
}
#include "production_input.c"
static unsigned checks;
static void expect(uint32_t msg, uint32_t wp, int x, int y) {
    mouse_messages = 0; void_input_pump();
    assert(touch_pumps == checks + 1);
    assert(mouse_messages == 1 && captured_msg == msg && captured_wp == wp);
    assert(captured_lp == ((uint32_t)y << 16 | (uint32_t)x)); ++checks;
}
int main(void) {
    void_input_mouse_warp(100, 200); expect(0x200, 0, 100, 200);
    void_input_key(0x10, 1); void_input_key(0xA3, 1); /* SHIFT and right CTRL */
    void_input_mouse_button(0, 1); expect(0x201, 13, 100, 200);
    void_input_mouse_move(3, -4); expect(0x200, 13, 103, 196);
    void_input_mouse_warp(50, 60); expect(0x200, 13, 50, 60);
    void_input_mouse_wheel(-120); expect(0x20A, 0xFF88000D, 50, 60);
    void_input_mouse_button(1, 1); expect(0x204, 15, 50, 60);
    void_input_mouse_button(0, 0); expect(0x202, 14, 50, 60);
    void_input_mouse_button(2, 1); expect(0x207, 30, 50, 60);
    void_input_key(0x10, 0); void_input_key(0xA3, 0);
    void_input_mouse_button(1, 0); expect(0x205, 16, 50, 60);
    void_input_mouse_button(2, 0); expect(0x208, 0, 50, 60);
    void_input_mouse_button(3, 1); void_input_mouse_button(4, 1);
    void_input_mouse_move(0, 0); expect(0x200, 0x60, 50, 60);
    void_input_mouse_button(3, 0); void_input_mouse_move(0, 0); expect(0x200, 0x40, 50, 60);
    void_input_mouse_button(4, 0); void_input_mouse_move(0, 0); expect(0x200, 0, 50, 60);
    void_input_event events[64];
    const uint32_t offsets[] = {12, 0, 4, 8, 13, 12, 14, 13, 14, 15, 16, 15, 16};
    const uint32_t values[] = {128, 3, (uint32_t)-4, (uint32_t)-120, 128, 0, 128, 0, 0, 128, 128, 0, 0};
    int n = void_input_mouse_events(events, 64, 0);
    assert(n == sizeof offsets / sizeof offsets[0]);
    for (int i = 0; i < n; ++i) {
        assert(events[i].ofs == offsets[i] && events[i].data == values[i]);
        if (i) assert(events[i].seq > events[i - 1].seq);
    }
    n = void_input_keyboard_events(events, 64, 0);
    assert(n == 4 && events[0].ofs == 0x2A && events[1].ofs == 0x9D);
    assert(events[0].data == 128 && events[1].data == 128 && !events[2].data && !events[3].data);
    uint32_t x,y;uint64_t moved;
    assert(void_input_pointer(&x,&y,&moved)&&x==50&&y==60&&moved==1000000000ull);
    now_ns+=30000000000ull;
    void_input_mouse_button(0,1);void_input_mouse_wheel(120);void_input_mouse_move(0,0);
    void_input_mouse_warp(50,60);void_input_set_cursor(50,60);
    assert(void_input_pointer(&x,&y,&moved)&&moved==1000000000ull);
    void_input_mouse_move(1,0);assert(void_input_pointer(&x,&y,&moved)&&x==51&&moved==now_ns);
    void_input_mouse_warp(0,0);now_ns++;void_input_mouse_move(-5,-5);
    assert(void_input_pointer(&x,&y,&moved)&&x==0&&y==0&&moved==now_ns-1);
    assert(void_vk_to_dik(0x60)==0x52&&void_vk_to_dik(0x69)==0x49);
    assert(void_vk_to_dik(0x0C)==0x9C&&void_vk_to_dik(0x0D)==0x1C);
    printf("PASS %u mouse messages: down/up, dragging, warp, modifiers, signed wheel and X-button flags; DirectInput ring unchanged\n", checks);
    return 0;
}
'''


class MouseMessagesTest(unittest.TestCase):
    def test_win32_messages_and_directinput_ring(self):
        compile_probe("mouse_messages", HARNESS, {
            "host.h": HOST,
            "input.h": (ROOT / "android/host/input.h").read_text(encoding="utf-8"),
            "touch.h": "",
            "production_input.c": (ROOT / "android/host/input.c").read_text(encoding="utf-8"),
        })


if __name__ == "__main__":
    unittest.main()
