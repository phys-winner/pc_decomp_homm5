"""Execute the real BeginScene admission and register-protected render callback."""
import re
import sys
from types import SimpleNamespace
import unittest

from test_d3d_lifecycle import function
from test_fmod_yield import HARNESS as REGISTER_HARNESS, builder, production_fixture
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))   # the builders' source passes
from protocol_transform import rewrite_icalls  # noqa: E402


HARNESS = r'''
#include <math.h>
typedef SRWLOCK pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER SRWLOCK_INIT
static void pthread_mutex_lock(pthread_mutex_t *m){AcquireSRWLockExclusive(m);}
static void pthread_mutex_unlock(pthread_mutex_t *m){ReleaseSRWLockExclusive(m);}
#include "touch.h"
static uint32_t thread_id=7,window_thread=7,main_hwnd=0x1234;
static uint32_t void_window_main(void){return main_hwnd;}
static uint32_t void_window_thread(uint32_t w){assert(w==main_hwnd);return window_thread;}
static uint32_t void_thread_id(void){return thread_id;}
static void_regs expected,poison;
static unsigned settings,renders,scales,events,uis,texts,cleanups;
static int callback_mode,capture_bridge;
typedef struct {int in_scene,recording;} d3d_device;
static d3d_device device,other,*g_d3d_device=&device;
static unsigned char memory[8192];
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
#define ARG(n) MEM32(g_esp+4u+4u*(n))
#define FRAME_VTABLE 0x400u
static void *void_com_host(uint32_t guest){
    assert(guest==0x123);
    if(capture_bridge){memset(&expected,0,sizeof expected);void_regs_save(&expected);}
    return &device;
}
#define DEV ((d3d_device *)void_com_host(ARG(0)))
#define D3D_OK 0u
#define D3DERR_INVALIDCALL 0x8876086Cu
/* ACTUAL_COM_MACRO */
void void_touch_render_pump(void);
void void_touch_scale_pump(void);
int void_touch_engine_ready(int kind){(void)kind;return 1;}
void void_touch_engine_event(const void_touch_event *e){(void)e;++events;}
void void_touch_ui_pump(void){++uis;}
void void_touch_text_pump(void){++texts;}
#include "touch_queue.h"
#include "begin_scene.h"
static void assert_context(const void_regs *want){
    void_regs actual;memset(&actual,0,sizeof actual);void_regs_save(&actual);
    assert(!memcmp(&actual,want,sizeof actual));
}
static void assert_callback(void){
    void_regs want=expected;assert(want.fp_top!=0);want.fp_top=0;assert_context(&want);
}
void void_port_settings_pump(void){
    assert_callback();assert(!device.in_scene);++settings;void_regs_load(&poison);
    unsigned before=settings;void_touch_render_frame_pump();void_touch_pump();assert(settings==before);
}
void void_touch_render_pump(void){
    assert_callback();assert(!device.in_scene);++renders;
    if(callback_mode==1){
        /* Reset's recursive BeginScene must not become another frame boundary. */
        g_cur_func=0xA3FFC0;assert(dev_BeginScene_impl()==D3D_OK);
        assert(device.in_scene);device.in_scene=0;
    }
    if(callback_mode==2)g_d3d_device=&other;
    void_regs_load(&poison);
    unsigned before=renders;void_touch_render_frame_pump();void_touch_pump();assert(renders==before);
}
void void_touch_scale_pump(void){
    assert_callback();++scales;void_regs_load(&poison);
    unsigned before=scales;void_touch_render_frame_pump();void_touch_pump();assert(scales==before);
}
/* ACTUAL_INITIALIZE */

typedef void (*recomp_func_t)(void);
#define ICALL_TRACE_SIZE 16
static uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx;
/* A callee that records itself as the current function (traced host code). */
static void cleanup(void){g_cur_func=0xC31170;g_esp+=4;++cleanups;}
static recomp_func_t void_resolve(uint32_t target){
    if(target==1)return cleanup;assert(target==2);return dev_BeginScene;
}
#define RECOMP_RETADDR 0xDEAD0000u
#define PUSH32(sp,v) do{(sp)-=4;MEM32(sp)=(v);}while(0)
/* ACTUAL_FLAG_MACROS */
/* ACTUAL_LOCAL_MACROS */
/* ACTUAL_CALL_MACROS */
#include "frame_boundary.h"
#undef eax
#undef ecx
#undef edx
#undef ebx
#undef esp
#undef ebp
#undef esi
#undef edi
static uint32_t begin(uint32_t owner){
    g_cur_func=owner;expected.cur=owner;return dev_BeginScene_impl();
}
int main(void){
    initialize(&expected,0x12340000);expected.esp=0x1000;expected.backedges=0x13572468;
    initialize(&poison,0x43210000);poison.backedges=19;
    void_regs_load(&expected);MEM32(g_esp+4)=0x123;
    void_touch_event event={TOUCH_BEGIN,100,200,0,0,1,0};void_touch_enqueue(&event);
    unsigned pending=touch_count,head=touch_head;uint64_t sequence=touch_next;
    void_touch_render_frame_pump();assert_context(&expected);
    assert(settings==1&&renders==1&&scales==1&&!events&&!uis&&!texts);
    assert(touch_count==pending&&touch_head==head&&touch_next==sequence&&!touch_pumping);

    /* Main-window/thread and shared recursion admission are independent. */
    main_hwnd=0;void_touch_render_frame_pump();main_hwnd=0x1234;
    thread_id=8;void_touch_render_frame_pump();thread_id=7;
    window_thread=8;void_touch_render_frame_pump();window_thread=7;
    touch_pumping=1;void_touch_render_frame_pump();touch_pumping=0;
    assert(settings==1&&renders==1&&scales==1);assert_context(&expected);

    /* Initialization, Reset, state-block recording and nested scenes never admit. */
    assert(begin(0xA3FFC0)==D3D_OK);device.in_scene=0;
    assert(begin(0x123456)==D3D_OK);device.in_scene=0;
    device.recording=1;assert(begin(0xA3FB70)==D3D_OK);device.recording=0;device.in_scene=1;
    assert(begin(0xA3FB70)==D3D_OK);device.in_scene=0;
    assert(settings==1&&renders==1&&scales==1);
    void_regs_load(&expected);callback_mode=1;
    assert(begin(0xA3FB70)==D3D_OK);assert(device.in_scene&&settings==2&&renders==2&&scales==2);
    assert_context(&expected);device.in_scene=0;
    callback_mode=2;
    assert(begin(0xA3FB70)==D3DERR_INVALIDCALL);
    assert(!device.in_scene&&g_d3d_device==&other&&settings==3&&renders==3&&scales==3);
    assert_context(&expected);g_d3d_device=&device;callback_mode=0;

    /* Production frame function: only the builder-marked BeginScene call site is the boundary,
       whatever g_cur_func earlier callees left; the marker clears it after the call. */
    void_regs before=expected;before.cur=0xC0FFEE;void_regs_load(&before);
    MEM32(FRAME_VTABLE+0xA4)=2;
    capture_bridge=1;sub_00A3FB70();capture_bridge=0;
    assert(cleanups==3&&settings==4&&renders==4&&scales==4&&device.in_scene);
    before.eax=D3D_OK;before.edx=FRAME_VTABLE;before.cur=0;assert_context(&before);
    assert(!g_icall_trace_idx); /* call-site diagnostics are opt-in (RECOMP_CALL_DIAG) */
    assert(touch_count==pending&&touch_head==head&&touch_next==sequence&&!events&&!uis&&!texts);
    puts("PASS native frame boundary: actual BeginScene, builder-marked ICALL owner, Reset recursion, thread/window, replacement, settings/render/scale pumps, full VM restoration, no touch/UI drain");
    return 0;
}
'''

# The generated BeginScene call of H5's frame function (sub_00A3FB70), in the
# generator's format; the builders' passes below turn it into production code.
FRAME_SITE = "    RECOMP_ICALL(MEM32(edx + 0xA4)); /* 0x00A3FCE3: call dword ptr [edx + 0xa4] */\n"
FRAME_BODY = (
    "void sub_00A3FB70(void) {\n"
    "    RECOMP_REGS_LOCALS\n"
    "    uint32_t _flag_k = g_flag_k, _flag_a = g_flag_a, _flag_b = g_flag_b, _cf = g_flag_cf;\n"
    "    RECOMP_ICALL(1); RECOMP_ICALL(1); RECOMP_ICALL(1);\n"
    "    eax = 0x123; edx = FRAME_VTABLE;\n"
    "    PUSH32(esp, eax); /* 0x00A3FCE2: push eax */\n"
    "%s"
    "    RECOMP_REGS_OUT();\n"
    "}\n")


def frame_function(marked=True):
    # Masked call protocol for an ordinary indirect site, then the Android
    # builder's frame-owner marker (tools/build_android.py, applied last).
    text = rewrite_icalls((FRAME_BODY % FRAME_SITE).encode(), SimpleNamespace(problem_sites=set()))
    return (builder.mark_frame_begin_scene(text) if marked else text).decode()


def boundary_fixture():
    runtime = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf8")
    com = (ROOT / "android/host/com.h").read_text(encoding="utf8")
    queue = (ROOT / "android/host/touch_queue.c").read_text(encoding="utf8")
    device = (ROOT / "android/host/d3d9_device.c").read_text(encoding="utf8")
    queue = queue.replace('#include "host.h"', '').replace('#include "touch.h"', '')
    prefix = REGISTER_HARNESS[:REGISTER_HARNESS.index("/* Native Windows primitives")]
    fixture = production_fixture(prefix + HARNESS)
    macro = com[com.index("#define COM_METHOD("):com.index("/* An unimplemented slot:")]
    local = runtime[runtime.index("#if defined(RECOMP_GENERATED_CODE) && defined(RECOMP_LOCAL_REGS)"):
                    runtime.index("#if defined(RECOMP_GENERATED_CODE) && !defined(RECOMP_LOCAL_REGS)")]
    # Call-site diagnostics, the full-protocol ICALL and the masked protocol (no RECOMP_CALL_DIAG,
    # no RECOMP_PROTOCOL_CHECK: the production configuration).
    calls = (runtime[runtime.index("/* Call-site diagnostics:"):runtime.index("/* Direct call to a known recompiled function")] +
             runtime[runtime.index("#define RECOMP_ICALL("):runtime.index("/* Indirect tail call")] +
             runtime[runtime.index("/* Masked call protocol"):runtime.index("/* `push target; ret`")])
    flags = "\n".join(re.findall(r"^#define RECOMP_FLAGS_(?:OUT|IN)\(\).*", runtime, re.M))
    fixture = fixture.replace("/* ACTUAL_COM_MACRO */", macro)
    fixture = fixture.replace("/* ACTUAL_INITIALIZE */", function(REGISTER_HARNESS, "static void initialize("))
    fixture = fixture.replace("/* ACTUAL_LOCAL_MACROS */", local).replace("/* ACTUAL_CALL_MACROS */", calls)
    fixture = fixture.replace("/* ACTUAL_FLAG_MACROS */", flags)
    headers = {"touch.h": (ROOT / "android/host/touch.h").read_text(encoding="utf8"),
               "touch_queue.h": queue, "begin_scene.h": function(device, "COM_METHOD(dev, BeginScene,"),
               "frame_boundary.h": frame_function()}
    return fixture, headers


class RenderFrameBoundaryTests(unittest.TestCase):
    def test_builder_marks_only_the_frame_begin_scene_call(self):
        frame = frame_function()
        self.assertIn("    g_cur_func = 0x00A3FB70u; RECOMP_ICALL_P(MEM32(edx + 0xA4), 0x17u, 0x17u, 0, 0x00A3FCE3u);"
                      " g_cur_func = 0; /* 0x00A3FCE3: call dword ptr [edx + 0xa4] */\n", frame)
        self.assertEqual(frame.count("g_cur_func"), 2)
        self.assertEqual(builder.mark_frame_begin_scene(b"void sub_00A3FB71(void) {\n" + FRAME_SITE.encode()),
                         b"void sub_00A3FB71(void) {\n" + FRAME_SITE.encode())
        with self.assertRaises(ValueError):
            builder.mark_frame_begin_scene((FRAME_BODY % "").encode())

    def test_actual_frame_admission_and_full_vm_context(self):
        fixture, headers = boundary_fixture()
        compile_probe("render_frame_boundary", fixture, headers,
                      extra_flags=("/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS"))

    def test_missing_caller_or_register_restore_is_rejected(self):
        fixture, headers = boundary_fixture()
        mutants = [dict(headers), dict(headers), dict(headers)]
        mutants[0]["begin_scene.h"] = mutants[0]["begin_scene.h"].replace("g_cur_func == 0x00A3FB70u && ", "")
        # Target the new frame wrapper, leaving the ordinary input pump intact.
        at = mutants[1]["touch_queue.h"].index("void void_touch_render_frame_pump(")
        tail = mutants[1]["touch_queue.h"][at:].replace("    void_regs_load(&saved);", "", 1)
        mutants[1]["touch_queue.h"] = mutants[1]["touch_queue.h"][:at] + tail
        # Without the builder's marker the frame's BeginScene is not recognised.
        mutants[2]["frame_boundary.h"] = frame_function(marked=False)
        for index, mutated in enumerate(mutants):
            with self.assertRaisesRegex(AssertionError, "Assertion failed"):

                compile_probe("render_frame_boundary_negative_" + str(index), fixture, mutated,
                              extra_flags=("/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS"))


if __name__ == "__main__":
    unittest.main()
