"""Run cursor offsets, touch cursor visibility and combo hold selection through the adapter."""
import unittest

from test_static_tls import ROOT, compile_probe
from test_touch_engine import HARNESS


CHECKS = r'''
static void reset_combo(void) {
    reset(0);force_ui=1;combo_child=0;
    MEM32(0x6684)=0xE8603C;MEM32(0x6800)=0xE85E94;
    MEM32(0x67B8)=0x80000;MEM32(0x80010)=0x81000;MEM32(0x81008)=0x16C;
    MEM32(0x6810)=0xA200;MEM32(0xA2D8)=0x4700D8;
}
int main(void) {
    reset(0);cursor_offset_x=0.1f;cursor_offset_y=-0.1f;
    event(TOUCH_BEGIN,200,300);
    assert(gesture.start_x==280 && gesture.start_y==220 && gesture.x==280 && gesture.y==220);
    event(TOUCH_HOLD_BEGIN,200,300);
    assert(gesture.held && gesture.x==280 && gesture.y==220);
    event(TOUCH_HOLD_DRAG,250,350);
    assert(gesture.x==330 && gesture.y==270);
    g_esp=1000;touch_cursor_query();
    assert(g_esp==1004 && fabsf(MEMF(g_eax)-(330*.8f+11))<.001f && fabsf(MEMF(g_eax+4)-(270*.8f+13))<.001f);
    cursor_draws=0;g_esp=1000;touch_cursor_draw();assert(!cursor_draws && g_esp==1008);
    show_touch_cursor=1;g_esp=1000;touch_cursor_draw();
    assert(cursor_draws==1 && g_esp==1008 && MEMF(0xFE6DA0)==330 && MEMF(0xFE6DA4)==270);
    event(TOUCH_END,250,350);assert(gesture.x==330 && gesture.y==270);
    g_esp=1000;touch_cursor_draw();assert(cursor_draws==1);
    reset(0);cursor_offset_x=-.2f;cursor_offset_y=.2f;
    event(TOUCH_BEGIN,1,799);assert(gesture.x>0 && gesture.x<1 && gesture.y==799);
    event(TOUCH_ABORT,0,0);assert(!gesture.active);
    /* Each sign and axis is continuous, strictly monotone and covers both edges.
       The old additive clamp fails both the endpoint and monotonicity checks. */
    const int dimensions[]={1,2,3,5,800,1280};
    const float offsets[]={-800,-160,-80,0,80,160,800};
    for(unsigned d=0;d<sizeof dimensions/sizeof *dimensions;++d) {
        int size=dimensions[d];float last=(float)(size-1);
        for(unsigned o=0;o<sizeof offsets/sizeof *offsets;++o) {
            assert(cursor_axis(0,size,offsets[o])==0 && cursor_axis(last,size,offsets[o])==last);
            float previous=-1;
            for(int i=0;i<=1024;++i) {
                float raw=last*i/1024,point=cursor_axis(raw,size,offsets[o]);
                assert(isfinite(point) && point>=0 && point<=last);
                if(size>1)assert(point>previous);
                if(offsets[o]==0)assert(point==raw);
                previous=point;
            }
        }
    }
    reset(0);cursor_offset_x=.2f;cursor_offset_y=-.2f;
    event(TOUCH_BEGIN,0,0);assert(gesture.x==0 && gesture.y==0);
    event(TOUCH_HOLD_BEGIN,0,0);assert(gesture.x==0 && gesture.y==0);
    event(TOUCH_HOLD_DRAG,1279,799);assert(gesture.x==1279 && gesture.y==799);
    event(TOUCH_END,1279,799);assert(gesture.x==1279 && gesture.y==799);
    reset(0);cursor_offset_x=cursor_offset_y=0;
    event(TOUCH_BEGIN,123,456);assert(gesture.x==123 && gesture.y==456);
    event(TOUCH_ABORT,0,0);
    reset(1);cursor_offset_x=.1f;cursor_offset_y=-.1f;
    event(TOUCH_PAD_CAMERA,500,400);assert(!gesture.active);
    event(TOUCH_BEGIN,500,400);assert(gesture.x==580 && gesture.y==320);
    show_touch_cursor=1;event(TOUCH_TWO_FINGER_BEGIN,500,400);
    event(TOUCH_TRANSFORM,510,410);assert(gesture.x==510 && gesture.y==410 && gesture.panning);
    cursor_draws=0;g_esp=1000;touch_cursor_draw();assert(!cursor_draws);
    /* Hold opens once; release over its own popup chooses with an ordinary native click. */
    reset_combo();
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    assert(gesture.combo==0x6684 && downs==1 && ups==1);
    ui_overlay=1;event(TOUCH_HOLD_DRAG,100,300);event(TOUCH_END,100,300);
    assert(downs==2 && ups==2 && gesture.committed && gesture.retiring && !gesture.active);
    reset_combo();combo_child=1;
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    assert(gesture.combo==0x6684 && downs==1 && ups==1);
    ui_overlay=1;event(TOUCH_HOLD_DRAG,100,300);event(TOUCH_END,100,300);
    assert(downs==2 && ups==2 && gesture.committed);
    /* A hold without drag opens the popup; a drag released outside cannot select anything. */
    reset_combo();
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);event(TOUCH_END,100,200);
    assert(downs==1 && ups==1 && !gesture.committed);
    reset_combo();
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    event(TOUCH_HOLD_DRAG,400,300);event(TOUCH_END,400,300);assert(downs==1 && ups==1);
    reset_combo();
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    ui_overlay=1;event(TOUCH_HOLD_DRAG,100,300);event(TOUCH_ABORT,0,0);assert(downs==1 && ups==1);
    reset_combo();
    event(TOUCH_BEGIN,100,200);event(TOUCH_HOLD_BEGIN,100,200);
    MEM32(0x6000)=0x94000;MEM32(0x94070)=0x487A80;
    ui_overlay=1;event(TOUCH_HOLD_DRAG,100,300);event(TOUCH_SECOND_BEGIN,100,300);
    assert(!gesture.combo && !gesture.second_info);event(TOUCH_SECOND_TAP,100,300);event(TOUCH_END,100,300);
    assert(downs==1 && ups==1 && !gesture.committed);
    puts("PASS cursor offsets at begin/hold/drag/end, smooth edge coverage/monotonicity, actual cursor coordinates/visibility, camera exclusion, combo hold/drag/release and cancellation");
    return 0;
}
'''


class TouchPointerOptionsTest(unittest.TestCase):
    def test_pointer_options_and_combo_hold(self):
        source = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf8")
        for name in ("host.h", "touch.h", "input.h"):
            source = source.replace(f'#include "{name}"', '')
        fixture = "static int combo_child;\n" + HARNESS.split('int main(void) {', 1)[0].replace(
            'if(ui_overlay)return 0x6900;', 'if(ui_overlay)return 0x8017C;if(combo_child)return 0x6810;') + CHECKS
        compile_probe("touch_pointer_options", fixture, {
            "touch_engine_actual.h": source,
            "touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf8"),
        }, extra_flags=("/wd4101", "/wd4102", "/wd4189"))


if __name__ == "__main__":
    unittest.main()
