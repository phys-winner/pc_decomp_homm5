"""Run production JNI entrypoints and DirectInput state, including untrusted values."""
import unittest

from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function
from test_mouse_messages import HOST


HARNESS = r'''
#include <math.h>
#include <stdio.h>
#include "host.h"
#include "touch.h"
static void void_post_message(uint32_t hwnd,uint32_t msg,uint32_t wp,uint32_t lp) {
    (void)hwnd;(void)msg;(void)wp;(void)lp;
}
#include "production_input.c"
static void_touch_event received[256];static unsigned count;
void void_touch_enqueue(const void_touch_event *e) {assert(count<256);received[count++]=*e;}
static int window_lock;
static void *window=&window_lock;
static int ANativeWindow_getWidth(void *p) {assert(p==window);return 2560;}
static int ANativeWindow_getHeight(void *p) {assert(p==window);return 1440;}
#define JNIEXPORT
#define JNICALL
typedef void JNIEnv;typedef void *jobject;typedef int jint;typedef float jfloat;typedef int jboolean;
#include "hardware_jni.h"
int main(void) {
    uint32_t x,y;uint64_t moved;
    assert(!void_input_pointer(&x,&y,&moved));
    Java_org_homm5_port_GameActivity_nativePointer(0,0,.75f,.25f,0);
    assert(void_input_pointer(&x,&y,&moved)&&x==960&&y==180&&moved==now_ns);
    assert(count==1&&received[0].kind==TOUCH_POINTER);
    int32_t dx,dy,dz;uint8_t buttons[8];void_input_mouse_snapshot(&dx,&dy,&dz,buttons);
    assert(dx==320&&dy==-180&&!dz);
    unsigned before=count;
    Java_org_homm5_port_GameActivity_nativePointer(0,0,NAN,0,0);
    Java_org_homm5_port_GameActivity_nativePointer(0,0,5,0,1);
    Java_org_homm5_port_GameActivity_nativePointer(0,0,0,INFINITY,1);
    assert(count==before);
    Java_org_homm5_port_GameActivity_nativePointer(0,0,.4f/1280,0,1);
    Java_org_homm5_port_GameActivity_nativePointer(0,0,.4f/1280,0,1);
    assert(count==before);
    Java_org_homm5_port_GameActivity_nativePointer(0,0,.4f/1280,0,1);
    assert(void_input_pointer(&x,&y,&moved)&&x==961&&y==180);
    Java_org_homm5_port_GameActivity_nativeMouseButton(0,0,0,1);
    assert(received[count-1].kind==TOUCH_POINTER_CLICK&&received[count-1].x==961);
    Java_org_homm5_port_GameActivity_nativeMouseButton(0,0,0,0);
    void_input_event events[32];int n=void_input_mouse_events(events,32,0);
    assert(n==5&&events[n-2].ofs==12&&events[n-2].data==128&&events[n-1].data==0);
    Java_org_homm5_port_GameActivity_nativeHardwareKey(0,0,'C',1);
    Java_org_homm5_port_GameActivity_nativeHardwareKey(0,0,'C',0);
    n=void_input_keyboard_events(events,32,0);assert(n==2&&events[0].ofs==0x2E&&events[0].data==128&&!events[1].data);
    Java_org_homm5_port_GameActivity_nativeWheel(0,0,-240);
    void_input_mouse_snapshot(&dx,&dy,&dz,buttons);assert(dz==-240);
    Java_org_homm5_port_GameActivity_nativePadCamera(0,0,.2f,-.1f);
    assert(received[count-1].kind==TOUCH_PAD_CAMERA&&received[count-1].rotation==.2f&&received[count-1].dy==-.1f);
    before=count;
    Java_org_homm5_port_GameActivity_nativeHardwareKey(0,0,-1,1);
    Java_org_homm5_port_GameActivity_nativeHardwareKey(0,0,256,1);
    Java_org_homm5_port_GameActivity_nativeMouseButton(0,0,8,1);
    Java_org_homm5_port_GameActivity_nativeWheel(0,0,12001);
    Java_org_homm5_port_GameActivity_nativePadCamera(0,0,INFINITY,0);
    Java_org_homm5_port_GameActivity_nativePadCamera(0,0,0,NAN);
    assert(count==before);
    puts("PASS JNI hardware bridge: absolute aspect fit, DirectInput deltas, fractional stick motion, click selection, scan codes, signed wheel, camera and invalid boundary rejection");
}
'''


class HardwareBridgeTest(unittest.TestCase):
    def test_production_jni(self):
        source = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        signatures = ["static int map_touch_point(", "static void physical_input_mode("]
        signatures += ["JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_" + name + "("
                       for name in ("nativeHardwareKey", "nativePointer", "nativeMouseButton", "nativeWheel", "nativePadCamera")]
        compile_probe("hardware_bridge", HARNESS, {
            "host.h": HOST,
            "touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf8"),
            "input.h": (ROOT / "android/host/input.h").read_text(encoding="utf8"),
            "production_input.c": (ROOT / "android/host/input.c").read_text(encoding="utf8"),
            "hardware_jni.h": "\n".join(function(source, name) for name in signatures),
        })


if __name__ == "__main__":
    unittest.main()
