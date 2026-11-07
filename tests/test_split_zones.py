"""Run the real one-finger split zones against the existing native-controller oracle."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_touch_troop_split import fixture


CASES = r'''
static void zone_begin(float x,float y) {
    troop_reset();
    event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);
    event(TOUCH_HOLD_DRAG,x,y);void_touch_ui_pump();
    assert(split_zone.visible&&gesture.panning&&gesture.dnd_pressed);
}
static void zone_tests(void) {
    mock_now_ns=1000000000ull;
    zone_begin(800,80);assert(split_zone.zone==2&&split_zone.progress==0);
    mock_now_ns+=999999999ull;void_touch_ui_pump();assert(!troop_commits&&split_zone.progress==99);
    ++mock_now_ns;void_touch_ui_pump();assert(troop_commits==1&&MEM32(0xA6020)==22&&split_zone.progress==0);
    mock_now_ns+=499999999ull;void_touch_ui_pump();assert(troop_commits==1);
    ++mock_now_ns;void_touch_ui_pump();assert(troop_commits==2&&MEM32(0xA6020)==21);
    event(TOUCH_END,800,80);assert(!gesture.active&&!split_zone.visible&&!dnd_held(0x60000));
    zone_begin(800,80);mock_now_ns+=750000000ull;void_touch_ui_pump();
    event(TOUCH_HOLD_DRAG,800,250);void_touch_ui_pump();assert(split_zone.zone==0);
    mock_now_ns+=3000000000ull;void_touch_ui_pump();assert(!troop_commits);
    event(TOUCH_HOLD_DRAG,800,80);void_touch_ui_pump();
    mock_now_ns+=999999999ull;void_touch_ui_pump();assert(!troop_commits);
    ++mock_now_ns;void_touch_ui_pump();assert(troop_commits==1);
    event(TOUCH_ABORT,0,0);assert(!split_zone.visible);
    zone_begin(450,80);assert(split_zone.zone==1&&!troop_commits);
    event(TOUCH_END,450,80);assert(troop_commits==1&&MEM32(0xA6020)==12&&!gesture.active);
    zone_begin(800,80);event(TOUCH_ABORT,0,0);mock_now_ns+=3000000000ull;
    void_touch_ui_pump();assert(!troop_commits&&!split_zone.visible);
    split_zones_enabled=0;troop_reset();
    event(TOUCH_BEGIN,100,400);event(TOUCH_HOLD_BEGIN,100,400);event(TOUCH_HOLD_DRAG,800,80);
    void_touch_ui_pump();assert(!split_zone.visible&&split_hint_visible&&!split_zone_at(800,80));
    mock_now_ns+=3000000000ull;void_touch_ui_pump();assert(!troop_commits);
    event(TOUCH_ABORT,0,0);assert(!split_hint_visible);
    split_zones_enabled=1;split_hints=0;zone_begin(800,80);
    assert(split_zone.visible&&!split_hint_visible);
    mock_now_ns+=1000000000ull;void_touch_ui_pump();assert(troop_commits==1);
    event(TOUCH_ABORT,0,0);split_hints=1;
    troop_mode=0;
    puts("PASS split zones: half on release, first unit at exactly 1s, repeats at 0.5s, independent hint/zone switches, exit and abort");
}
'''


class SplitZonesTest(unittest.TestCase):
    def test_real_split_controller_and_timing(self):
        source = (ROOT / "android/host/touch_engine.c").read_text()
        for header in ("host.h", "touch.h", "input.h"):
            source = source.replace('#include "' + header + '"', '')
        harness = fixture().replace('int main(void) {', CASES + '\nint main(void) {\n    zone_tests();', 1)
        compile_probe("split_zones", harness, {"touch_engine_actual.h": source,
                      "touch.h": (ROOT / "android/host/touch.h").read_text()})


if __name__ == "__main__":
    unittest.main()
