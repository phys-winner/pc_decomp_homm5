"""Execute the real JNI mapping and bounded VM-thread touch transport."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function
from test_fmod_yield import HARNESS as REGISTER_HARNESS, production_fixture

HARNESS = r'''
#include <math.h>
typedef SRWLOCK pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER SRWLOCK_INIT
static void pthread_mutex_lock(pthread_mutex_t *m) { AcquireSRWLockExclusive(m); }
static void pthread_mutex_unlock(pthread_mutex_t *m) { ReleaseSRWLockExclusive(m); }
#include "touch.h"
static __declspec(thread) uint32_t current_thread = 7;
typedef struct {uint32_t hwnd,thread;} window_t;
static window_t main_win = {0x1234,7};
static uint32_t main_hwnd = 0x1234;
static window_t *find_window(uint32_t hwnd) { return hwnd==main_win.hwnd ? &main_win : NULL; }
static uint32_t void_window_main(void) { return main_hwnd; }
static uint32_t void_thread_id(void) { return current_thread; }
#include "window_owner.h"
static void_regs expected,poison;
static void_touch_event received[1024];
static unsigned received_count,ui_pumps,scale_pumps,settings_pumps;
static char order[64];   /* pump order within one pass: p settings, r render, s scale, u UI, t text */
static void pumped(char which) { size_t n=strlen(order); assert(n+1<sizeof order); order[n]=which; order[n+1]=0; }
static int gate_mode;
static uint64_t touch_frame;
static struct {int active,ui,retiring;uint64_t begin_frame,release_frame;} gesture;
#include "engine_ready.h"
static int producer_on_callback,producer_abort;
static void assert_context(void) {
    void_regs actual; memset(&actual,0,sizeof actual); void_regs_save(&actual);
    assert(!memcmp(&actual,&expected,sizeof actual));
}
static void assert_callback_context(void) {
    void_regs actual,callback_expected=expected;
    memset(&actual,0,sizeof actual); void_regs_save(&actual);
    assert(expected.fp_top!=0 && g_fp_top==0);
    callback_expected.fp_top=0;
    assert(!memcmp(&actual,&callback_expected,sizeof actual));
}
static DWORD WINAPI producer(void *unused) {
    (void)unused; current_thread=42;
    unsigned before=received_count;
    void_touch_pump(); assert(received_count==before);
    void_touch_event event={TOUCH_PAN,200,300,4,5,1,0};
    if(producer_abort) {
        event.kind=TOUCH_ABORT;void_touch_enqueue(&event);
        event.kind=TOUCH_BEGIN;void_touch_enqueue(&event);
        event.kind=TOUCH_TAP;
    }
    void_touch_enqueue(&event); return 0;
}
static void void_touch_engine_event_spy(const void_touch_event *event) {
    assert(current_thread==7); assert_callback_context();
    assert(received_count<1024); received[received_count++]=*event;
    if (gate_mode) {
        if(event->kind==TOUCH_BEGIN) {
            memset(&gesture,0,sizeof gesture);gesture.active=1;
            gesture.ui=gate_mode==1;gesture.begin_frame=touch_frame;
        } else if(event->kind==TOUCH_END) {
            gesture.active=0;gesture.retiring=gesture.ui;gesture.release_frame=touch_frame;
        } else if(event->kind==TOUCH_ABORT) memset(&gesture,0,sizeof gesture);
    }
    if(producer_on_callback) {
        producer_on_callback=0;
        unsigned before=received_count;
        HANDLE thread=CreateThread(NULL,0,producer,NULL,0,NULL); assert(thread);
        assert(WaitForSingleObject(thread,1000)==WAIT_OBJECT_0); CloseHandle(thread);
        void_touch_pump(); assert(received_count==before);
    }
    void_regs_load(&poison);
}
#define void_touch_engine_event void_touch_engine_event_spy
static void void_port_settings_pump_spy(void) {
    assert(current_thread==7); assert_callback_context(); ++settings_pumps; pumped('p');
    void_regs_load(&poison); void_touch_pump();
}
#define void_port_settings_pump void_port_settings_pump_spy
static void void_touch_scale_pump_spy(void) {
    assert(current_thread==7); assert_callback_context(); ++scale_pumps; pumped('s');
    void_regs_load(&poison); void_touch_pump();
}
#define void_touch_scale_pump void_touch_scale_pump_spy
static void void_touch_render_pump_spy(void) {
    assert(current_thread==7);assert_callback_context();pumped('r');void_regs_load(&poison);void_touch_pump();
}
#define void_touch_render_pump void_touch_render_pump_spy
static void void_touch_ui_pump_spy(void) {
    assert(current_thread==7); assert_callback_context(); ++ui_pumps; pumped('u');
    void_regs_load(&poison); void_touch_pump();
}
#define void_touch_ui_pump void_touch_ui_pump_spy
static void void_touch_text_pump_spy(void) {
    assert(current_thread==7);assert_callback_context();pumped('t');void_regs_load(&poison);void_touch_pump();
}
#define void_touch_text_pump void_touch_text_pump_spy
#include "touch_queue.h"
static pthread_mutex_t window_lock=PTHREAD_MUTEX_INITIALIZER;
static int native_w=2944,native_h=1840;
static void *window=&native_w;
static int ANativeWindow_getWidth(void *p) {
    assert(p==window && !TryAcquireSRWLockExclusive(&window_lock)); return native_w;
}
static int ANativeWindow_getHeight(void *p) {
    assert(p==window && !TryAcquireSRWLockExclusive(&window_lock)); return native_h;
}
static void void_input_screen_size(int *w,int *h) { *w=1280; *h=800; }
#define JNIEXPORT
#define JNICALL
typedef void JNIEnv;
typedef void *jobject;
typedef int jint;
typedef float jfloat;
#include "touch_jni.h"
static void input(int kind,float x,float y,float dx,float dy,float scale) {
    Java_org_homm5_port_GameActivity_nativeTouch(NULL,NULL,kind,x,y,dx,dy,scale,0);
}
static void event(int kind) {
    void_touch_event e={kind,100,200,3,4,1,0}; void_touch_enqueue(&e);
}
static void drain(void) { void_touch_pump(); assert_context(); }
static void reset(void) {
    input(TOUCH_ABORT,0,0,0,0,1); drain();
    received_count=0; ui_pumps=scale_pumps=settings_pumps=0; order[0]=0;
}
static void close_float(float a,float b) { assert(fabsf(a-b)<0.001f); }
static void initialize(void_regs *r,uint32_t seed);
int main(void) {
    initialize(&expected,0x12340000u); expected.backedges=0x87654321u;
    initialize(&poison,0x43210000u); poison.backedges=17;
    void_regs_load(&expected);

    /* JNI is data-only; even a worker message pump cannot execute the engine. */
    input(TOUCH_BEGIN,.5f,.5f,0,0,1);
    input(TOUCH_TAP,.5f,.5f,0,0,1);
    input(TOUCH_END,.5f,.5f,0,0,1);
    assert(!received_count && !ui_pumps);
    current_thread=42; drain(); assert(!received_count && !ui_pumps);
    current_thread=7; main_hwnd=0; drain(); assert(!received_count && !ui_pumps);
    assert(!settings_pumps && !order[0]);
    main_hwnd=0x1234; drain(); assert(received_count==3 && ui_pumps==1 && scale_pumps==1 && settings_pumps==1);
    assert(!strcmp(order,"prsut"));   /* option changes are applied before this pass's render/scale pumps */
    assert(received[0].kind==TOUCH_BEGIN && received[1].kind==TOUCH_TAP && received[2].kind==TOUCH_END);
    close_float(received[0].x,640); close_float(received[0].y,400);
    drain(); assert(received_count==3 && ui_pumps==2 && scale_pumps==2 && settings_pumps==2);
    /* The render-frame pump (Present without a message pump): settings, render, scale. */
    order[0]=0; void_touch_render_frame_pump(); assert_context(); assert(!strcmp(order,"prs") && settings_pumps==3);
    current_thread=42; void_touch_render_frame_pump(); current_thread=7; assert(settings_pumps==3);
    reset();

    /* Actual readiness predicate preserves both UI frames and every subsequent FIFO gesture. */
    gate_mode=1;
    event(TOUCH_BEGIN);event(TOUCH_TAP);event(TOUCH_END);
    event(TOUCH_BEGIN);event(TOUCH_DOUBLE_TAP);event(TOUCH_END);
    drain();assert(received_count==1 && received[0].kind==TOUCH_BEGIN);
    drain();assert(received_count==1);
    ++touch_frame;drain();assert(received_count==3 && received[1].kind==TOUCH_TAP && received[2].kind==TOUCH_END);
    drain();assert(received_count==3);
    ++touch_frame;drain();assert(received_count==4 && received[3].kind==TOUCH_BEGIN);
    ++touch_frame;drain();assert(received_count==6 && received[4].kind==TOUCH_DOUBLE_TAP && received[5].kind==TOUCH_END);
    reset();
    event(TOUCH_BEGIN);event(TOUCH_TAP);event(TOUCH_END);drain();assert(received_count==1);
    event(TOUCH_ABORT);drain();assert(received_count==2 && received[1].kind==TOUCH_ABORT);
    ++touch_frame;drain();assert(received_count==2);reset();
    event(TOUCH_BEGIN);event(TOUCH_TAP);event(TOUCH_END);drain();
    ++touch_frame;drain();assert(received_count==3&&gesture.retiring);
    event(TOUCH_BEGIN);event(TOUCH_TAP);event(TOUCH_END);drain();assert(received_count==3);
    event(TOUCH_ABORT);drain();assert(received_count==4&&received[3].kind==TOUCH_ABORT&&!gesture.retiring);
    ++touch_frame;drain();assert(received_count==4);reset();
    gate_mode=2;event(TOUCH_BEGIN);event(TOUCH_TAP);event(TOUCH_END);drain();
    assert(received_count==3);reset();gate_mode=0;

    /* Engine callbacks may reenter PeekMessage; queued UI input waits for the next outer pump. */
    producer_on_callback=1; event(TOUCH_BEGIN); event(TOUCH_TAP); drain();
    assert(received_count==2 && received[0].kind==TOUCH_BEGIN && received[1].kind==TOUCH_TAP);
    drain(); assert(received_count==3 && received[2].kind==TOUCH_PAN);
    reset();
    producer_on_callback=producer_abort=1;event(TOUCH_BEGIN);event(TOUCH_TAP);drain();
    assert(received_count==1 && received[0].kind==TOUCH_BEGIN);
    drain();assert(received_count==4 && received[1].kind==TOUCH_ABORT && received[2].kind==TOUCH_BEGIN && received[3].kind==TOUCH_TAP);
    producer_abort=0;reset();

    /* Overflow cannot deliver a prefix followed by a stale commit. */
    event(TOUCH_BEGIN);
    for(unsigned i=1;i<256;i++) event(TOUCH_PAN);
    event(TOUCH_TAP); event(TOUCH_END); drain();
    assert(received_count==1 && received[0].kind==TOUCH_ABORT);
    event(TOUCH_PAN); event(TOUCH_TAP); drain(); assert(received_count==1);
    event(TOUCH_BEGIN); event(TOUCH_TAP); event(TOUCH_END); drain();
    assert(received_count==4 && received[1].kind==TOUCH_BEGIN && received[2].kind==TOUCH_TAP);
    reset();

    /* Every invalid trust-boundary field aborts the entire pending gesture. */
    for(unsigned i=0;i<10;i++) {
        event(TOUCH_BEGIN);
        void_touch_event bad={TOUCH_PAN,1,2,3,4,1,0};
        if(i==0) bad.kind=99; if(i==1) bad.x=NAN; if(i==2) bad.y=INFINITY;
        if(i==3) bad.dx=NAN; if(i==4) bad.dy=INFINITY; if(i==5) bad.scale=0;
        if(i==6) bad.scale=-1; if(i==7) bad.scale=NAN;
        if(i==8) bad.rotation=NAN; if(i==9) bad.rotation=3.2f;
        void_touch_enqueue(&bad); event(TOUCH_TAP); drain();
        assert(received_count==1 && received[0].kind==TOUCH_ABORT); reset();
    }
    event(TOUCH_BEGIN); void_touch_enqueue(NULL); drain();
    assert(received_count==1 && received[0].kind==TOUCH_ABORT); reset();

    Java_org_homm5_port_GameActivity_nativeTouch(NULL,NULL,TOUCH_BEGIN,.5f,.5f,0,0,1,0);
    Java_org_homm5_port_GameActivity_nativeTouch(NULL,NULL,TOUCH_TRANSFORM,.5f,.5f,0,0,1,3.14159274f);
    Java_org_homm5_port_GameActivity_nativeTouch(NULL,NULL,TOUCH_SECOND_TAP,.6f,.6f,0,0,1,0);
    drain(); assert(received_count==3 && received[2].kind==TOUCH_SECOND_TAP);
    close_float(received[1].rotation,3.14159274f);close_float(received[2].x,768);
    Java_org_homm5_port_GameActivity_nativeTouch(NULL,NULL,TOUCH_TRANSFORM,.5f,.5f,0,0,1,NAN);
    drain(); assert(received_count==4&&received[3].kind==TOUCH_ABORT);reset();

    /* Fit a 1280x800 image inside a square surface: bars never become map taps. */
    native_w=native_h=2000;
    input(TOUCH_BEGIN,.5f,.05f,0,0,1); input(TOUCH_TAP,.5f,.05f,0,0,1);
    input(TOUCH_END,.5f,.05f,0,0,1); drain(); assert(!received_count);
    input(TOUCH_BEGIN,.5f,.5f,0,0,1);
    input(TOUCH_PAN,.6f,.6f,.1f,.1f,1); drain();
    assert(received_count==2); close_float(received[1].x,768); close_float(received[1].y,528);
    close_float(received[1].dx,128); close_float(received[1].dy,128);
    input(TOUCH_TAP,.5f,.05f,0,0,1); input(TOUCH_END,.5f,.05f,0,0,1); drain();
    assert(received_count==3 && received[2].kind==TOUCH_ABORT); reset();
    input(TOUCH_BEGIN,-.01f,.5f,0,0,1); input(TOUCH_TAP,-.01f,.5f,0,0,1);
    drain(); assert(!received_count);
    window=NULL; input(TOUCH_BEGIN,.5f,.5f,0,0,1); drain(); assert(!received_count);
    reset(); window=&native_w;
    input(TOUCH_BEGIN,.5f,.5f,0,0,1); drain(); assert(received_count==1);
    window=NULL; input(TOUCH_PAN,.6f,.6f,.1f,.1f,1); drain();
    assert(received_count==2 && received[1].kind==TOUCH_ABORT);
    reset(); window=&native_w;
    input(TOUCH_BEGIN,.5f,.5f,0,0,1); input(TOUCH_PAN,NAN,.5f,0,0,1); drain();
    assert(received_count==1 && received[0].kind==TOUCH_ABORT);
    reset();event(TOUCH_BEGIN);event(TOUCH_TAP);event(TOUCH_POINTER);event(TOUCH_PAD_CAMERA);
    event(TOUCH_POINTER_CLICK);event(TOUCH_POINTER);drain();
    assert(received_count==3&&received[0].kind==TOUCH_POINTER&&received[1].kind==TOUCH_PAD_CAMERA&&received[2].kind==TOUCH_POINTER_CLICK);
    reset();event(TOUCH_POINTER);drain();assert(received_count==1&&received[0].kind==TOUCH_POINTER);
    puts("PASS touch transport: FIFO, window owner, full GPR/FPU/XMM/EH/backedges, recursive callbacks, concurrent producer, overflow abort, JNI aspect fit and bars; physical-mode reentry keeps camera/click events");
    return 0;
}
/* ACTUAL_INITIALIZE */
'''


class TouchTransportTests(unittest.TestCase):
    def test_actual_transport_and_jni(self):
        queue = (ROOT / "android/host/touch_queue.c").read_text(encoding="utf8")
        queue = queue.replace('#include "host.h"', '').replace('#include "touch.h"', '')
        android = (ROOT / "android/host/android_main.c").read_text(encoding="utf8")
        user = (ROOT / "android/host/user32.c").read_text(encoding="utf8")
        engine = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf8")
        prefix = REGISTER_HARNESS[:REGISTER_HARNESS.index("/* Native Windows primitives")]
        fixture = production_fixture(prefix + HARNESS)
        fixture = fixture.replace("/* ACTUAL_INITIALIZE */", function(REGISTER_HARNESS, "static void initialize("))
        compile_probe("touch_transport", fixture, {
            "touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf8"),
            "window_owner.h": function(user, "uint32_t void_window_thread("),
            "engine_ready.h": function(engine, "int void_touch_engine_ready("),
            "touch_queue.h": queue,
            "touch_jni.h": function(android, "static int map_touch_point(") +
                          function(android, "JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_nativeTouch("),
        })


if __name__ == "__main__":
    unittest.main()
