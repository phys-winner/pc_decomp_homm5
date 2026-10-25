"""Exercise both production Present bodies and the swap fragment with the real FIFO."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body
from test_fmod_yield import HARNESS, builder, production_fixture


PRESENT_DECLS=r'''
typedef struct {uint32_t frame;int fbo_dirty;} d3d_device;
typedef struct {d3d_device *dev;} swapchain_t;
static d3d_device device;
static swapchain_t chain={&device};
static unsigned egl_complete,gl_complete,spawn_workers;
static unsigned touch_presents,paces;
static void void_touch_frame_presented(void) {
    assert(egl_complete && gl_complete && device.frame==42);
    ++touch_presents;
}
static void d3d_gl_frame_pace(void) {
    assert(egl_complete && gl_complete && device.frame==42 && touch_presents==paces+1);
    ++paces;
}
static HANDLE present_workers[2];
static uint64_t swap_ns;
static int egl_display=1,egl_surface=2,fbo=4;
#define CLOCK_MONOTONIC 1
#define GL_FRAMEBUFFER 3
#define D3D_OK 0u
#define DEV (&device)
#define SC (&chain)
#define COM_METHOD(type,name,args) static uint32_t type##_##name(void)
static DWORD WINAPI renderer(void *arg);
static void present_guest_entry(void) {
    int present_frame_committed=egl_complete && gl_complete && device.fbo_dirty && device.frame==42;
    assert(present_frame_committed);
}
static int clock_gettime(int clock,struct timespec *value) {
    assert(clock==CLOCK_MONOTONIC);value->tv_sec=1;value->tv_nsec=0;return 0;
}
static int eglSwapBuffers(int display,int surface) {
    assert(display==1 && surface==2 && !egl_complete && device.frame==41);
    if(spawn_workers) {
        uint64_t first_target=ticket_next+1;
        present_workers[0]=CreateThread(NULL,0,renderer,(void *)(uintptr_t)0,0,NULL);
        assert(present_workers[0]);queue_waiter(first_target);
        present_workers[1]=CreateThread(NULL,0,renderer,(void *)(uintptr_t)1,0,NULL);
        assert(present_workers[1]);queue_waiter(first_target+1);
        assert(!progress); /* Both have tickets, but EGL still owns the machine. */
        handoff_owner=t_self;expected_next=ticket_next+1;expected_serving=ticket_serving+1;
    }
    egl_complete=1;return 1;
}
static void glBindFramebuffer(int target,int buffer) {
    assert(target==GL_FRAMEBUFFER && buffer==fbo && egl_complete && !progress);
    gl_complete=1;
}
'''

PRESENT_MAIN=r'''
int main(void) {
    (void)run_lifted;(void)sleep_ms;
    uint32_t (*present[2])(void)={dev_Present,sc_Present};
    for(unsigned round=0;round<3;++round) {
        ticket_next=ticket_serving=t_lock_wait_ns=0;handoffs=progress=yields=0;pins=0;
        handoff_owner=NULL;egl_complete=gl_complete=0;spawn_workers=round!=2;
        device.frame=41;device.fbo_dirty=0;
        void_regs initial,actual;initialize(&initial,0x12340000u+round);
        initialize(&render[0].regs,0x43210000u);initialize(&render[1].regs,0x56780000u);
        render[0].depth=render[1].depth=1;
        t_self=&audio;audio.depth=1;machine_acquire();void_regs_load(&initial);expected_yield=initial;
        recomp_yield_hook=spawn_workers ? yield_hook : NULL;
        unsigned previous_touch_presents=touch_presents;
        assert(present[round%2]()==D3D_OK);
        assert(touch_presents==previous_touch_presents+1);
        assert(paces==touch_presents);
        int present_workers_completed=!spawn_workers || progress==2;
        assert(present_workers_completed);
        assert(device.frame==42 && device.fbo_dirty && egl_complete && gl_complete);
        if(spawn_workers) {
            assert(handoffs==1 && seen_order[0]==1 && seen_order[1]==2 && pins==4);
        } else assert(!handoffs && pins==1);
        assert(!yields && audio.depth==1 && !machine_contended());
        memset(&actual,0,sizeof actual);void_regs_save(&actual);assert(!memcmp(&initial,&actual,sizeof initial));
        machine_release();
        if(spawn_workers) for(unsigned i=0;i<2;++i) {
            assert(WaitForSingleObject(present_workers[i],2000)==WAIT_OBJECT_0);
            CloseHandle(present_workers[i]);
        }
    }
    puts("PASS actual device/swapchain Present + swap fragment: EGL/GL/frame committed before FIFO handoff; owner return ticket reserved; full guest context/depth/affinity exact; NULL hook safe");
    return 0;
}
'''


def present_fixture(early_release=False, omit_tail=False):
    gl=(ROOT/"android/host/d3d9_gl.c").read_text(encoding="utf8")
    start=gl.index("        struct timespec swap_start, swap_end;")
    last="        dev->fbo_dirty = 1;"
    end=gl.index(last,start)+len(last)
    swap=gl[start:end]
    if early_release:
        call="        eglSwapBuffers(egl_display, egl_surface);"
        swap=swap.replace(call,"        void_blocking_begin();\n"+call+"\n        void_blocking_end();")
    wrapper="static void d3d_gl_present(d3d_device *dev)\n{\n"+swap+"\n}\n"
    methods="\n".join(body((ROOT/"android/host"/filename).read_text(encoding="utf8"),signature)
                      for filename,signature in [("d3d9_device.c","COM_METHOD(dev, Present,"),
                                                 ("d3d9_resource.c","COM_METHOD(sc, Present,")])
    if omit_tail:
        methods=methods.replace("    if (recomp_yield_hook) recomp_yield_hook();\n","")
    harness=HARNESS.replace("static DWORD WINAPI renderer(void *arg) {",PRESENT_DECLS+"\nstatic DWORD WINAPI renderer(void *arg) {")
    harness=harness.replace("    t_self=&render[which];machine_acquire();",
                            "    t_self=&render[which];machine_acquire();present_guest_entry();")
    harness=harness.replace(body(harness,"int main(void)"),wrapper+methods+PRESENT_MAIN)
    return production_fixture(harness)


def run_probe(name,fixture):
    compile_probe(name,fixture,{},extra_flags=("/O2","/DRECOMP_GENERATED_CODE","/DRECOMP_LOCAL_REGS"),
                  compiler_override=builder.TOOLCHAIN/"bin/clang-cl.exe")


class PresentHandoffTest(unittest.TestCase):
    def test_present_commits_before_atomic_handoff(self):
        run_probe("present_handoff",present_fixture())

    def test_prior_swap_release_is_rejected_before_frame_commit(self):
        with self.assertRaisesRegex(AssertionError,"present_frame_committed"):
            run_probe("present_early_release",present_fixture(early_release=True))

    def test_missing_present_tail_is_rejected_by_worker_progress(self):
        with self.assertRaisesRegex(AssertionError,"present_workers_completed"):
            run_probe("present_no_tail",present_fixture(omit_tail=True))


if __name__=="__main__":unittest.main()
