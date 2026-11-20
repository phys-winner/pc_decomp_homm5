"""Tribes of the East's frame monitor (perf_diag.c), display-rate follower and single pacer.

Runs the production classifier, cadence selection and limiter wrapper in native harnesses, the
Java HyperOS check in a JVM, and guards that the legacy engines compile none of it."""
import re
import subprocess
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_touch_controls import JAVA

sys.path.insert(0, str(ROOT / "tools"))
from port_patches import legacy_ui_branch


def resolved(path, legacy=False):
    text = (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
    return legacy_ui_branch(text, legacy).decode("utf8")


CLASSIFY = r'''
#include <assert.h>
#include <stdio.h>
/* ACTUAL_ENUM */
/* ACTUAL_CLASSIFY */
static int run(double cpu,double runq,double lock,double pace,double swap,double io,double gpu,double wall) {
    double known=cpu+runq+lock+pace+swap+io;
    double c[C_COUNT]={cpu,runq,lock,pace,swap,io,gpu,wall>known?wall-known:0};
    return classify(c,wall);
}
int main(void) {
    assert(run(30,1,2,0,1,0,0,36)==C_CPU);
    assert(run(12,0,30,0,1,0,0,45)==C_LOCK);
    assert(run(12,0,1,30,1,0,0,45)==C_PACE);
    assert(run(12,0,1,0,30,0,0,45)==C_SWAP);
    assert(run(12,0,1,0,1,31,0,45)==C_IO);
    assert(run(5,25,1,0,1,0,0,33)==C_RUNQ);
    assert(run(10,0,0,0,2,0,0,45)==C_OTHER);         /* 33 ms nobody accounts for */
    /* gpu wins only above 0.6 of the frame and above every other component. */
    assert(run(12,0,0,0,20,0,28,45)==C_GPU);
    assert(run(12,0,0,0,20,0,26,45)==C_SWAP);         /* 26 < 0.6 * 45 */
    assert(run(30,0,0,0,1,0,29,36)==C_CPU);           /* above 0.6 but below cpu */
    puts("PASS long-frame cause: largest component, gpu only above 0.6 wall and the rest, unaccounted -> other");
    return 0;
}
'''

CADENCE = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
/* ACTUAL_CADENCE */
static float cap(float choice,float hz,int *n) {return effective_cap(choice,hz,n);}
int main(void) {
    int n;
    assert(cap(120,60,&n)==60 && n==1);               /* thermal 60 Hz under a 120 cap */
    assert(cap(40,60,&n)==30 && n==2);                /* uneven 40 on 60 Hz -> even 30 */
    assert(cap(60,120,&n)==60 && n==2);               /* 60 on a 120 Hz panel */
    assert(cap(60,60,&n)==60 && n==1);
    assert(cap(45,60,&n)==30 && n==2);
    assert(cap(30,90,&n)==30 && n==3);
    assert(fabsf(cap(60,59.94f,&n)-59.94f)<1e-3f && n==1);   /* nominal 60 within half a frame */
    assert(cap(20,120,&n)==20 && n==0);               /* below refresh/3: the choice paces alone */
    assert(cap(60,0,&n)==60 && n==0);                 /* unknown panel */
    assert(cap(120,90,&n)==90 && n==1);
    puts("PASS effective cap: largest refresh/n (n<=3) not above the choice; unknown panel or slow choice keeps the choice");
    return 0;
}
'''

PACE = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <time.h>
#define CLOCK_MONOTONIC 1
#define TIMER_ABSTIME 1
#define memory_order_relaxed 0
#define atomic_load(p) (*(p))
#define atomic_load_explicit(p,o) (*(p))
static int exchange(int *p,int v){int old=*p;*p=v;return old;}
#define atomic_exchange(p,v) exchange(p,v)
typedef struct { uint64_t records, bytes, syncs, sync_ns, frame_waits, frame_wait_ns, ring_waits, ring_wait_ns, render_busy_ns; } d3d_rt_stats_t;
typedef struct { uint32_t frame; int threaded, surface_live; uint64_t pace_ns, swap_ns, frame_wait_ns, sync_ns, ring_wait_ns, render_busy_ns; float cap, eff_cap; } void_frame_in;
typedef struct { uint32_t frame; } d3d_device;
static d3d_device device={100};
static d3d_device *g_d3d_device=&device;
static int surface_live=1,pace_restart,window_mode=1,game_swap_interval=1,void_frame_monitor_on=1,vsync_paced=1,owned=1;
static uint64_t frame_deadline_ns,frame_period_ns,fake_now=1000000000ull,swap_total_ns=7,lock_total,lock_extra,inject;
static unsigned timer_waits,naps,monitors,logs;
static float effective=60;
static void_frame_in last_in;
static float void_port_fps_limit(void){return 120;}
static float void_port_effective_fps(void){return effective;}
static int void_port_vsync_paced(void){return vsync_paced;}
static uint64_t void_diag_inject_pace(void){uint64_t v=inject;inject=0;return v;}
static uint64_t void_perf_now_ns(void){assert(owned);return fake_now;}
static uint64_t void_lock_wait_ns(void){return lock_total;}
static void void_blocking_begin(void){assert(owned);owned=0;}
static void void_blocking_end(void){assert(!owned);owned=1;fake_now+=lock_extra;lock_total+=lock_extra;}
static void void_log(const char *format,...){(void)format;++logs;}
static int threaded=1;
static int d3d_rt_threaded(void){return threaded;}
static void d3d_rt_stats(d3d_rt_stats_t *s){memset(s,0,sizeof *s);s->frame_wait_ns=11;s->render_busy_ns=13;}
static void void_frame_monitor(const void_frame_in *in){last_in=*in;++monitors;}
static int clock_nanosleep(int clock,int flags,const struct timespec *deadline,struct timespec *remaining){
 assert(!owned&&clock==CLOCK_MONOTONIC&&flags==TIMER_ABSTIME&&!remaining);
 fake_now=(uint64_t)deadline->tv_sec*1000000000ull+(uint64_t)deadline->tv_nsec;++timer_waits;return 0;
}
static int nanosleep(const struct timespec *want,struct timespec *left){
 assert(!owned);(void)left;fake_now+=(uint64_t)want->tv_sec*1000000000ull+(uint64_t)want->tv_nsec;++naps;return 0;
}
/* ACTUAL_PACE */
static void frames(int count,uint64_t step){for(int i=0;i<count;++i){fake_now+=step;d3d_gl_frame_pace();}}
int main(void) {
    /* The cap equals the refresh: vsync paces, the timer never waits; the monitor gets the frame. */
    frames(10,2000000ull);
    assert(!timer_waits && !frame_deadline_ns && monitors==10);
    assert(last_in.frame==99 && last_in.threaded==1 && last_in.surface_live==1 && last_in.swap_ns==7);
    assert(last_in.frame_wait_ns==11 && last_in.render_busy_ns==13 && last_in.cap==120 && last_in.eff_cap==60);
    /* A cadence below the refresh, or an immediate present interval: the timer paces. */
    vsync_paced=0;frames(3,2000000ull);assert(timer_waits>=2);
    unsigned before=timer_waits;vsync_paced=1;game_swap_interval=0;frames(3,2000000ull);assert(timer_waits>before);
    /* GL inline (no render thread): the swap holds the machine, the timer's sleep stays the other threads' time. */
    game_swap_interval=1;before=timer_waits;threaded=0;frames(3,2000000ull);assert(timer_waits>before);threaded=1;
    pace_restart=1;frames(1,2000000ull);assert(!pace_restart && !frame_deadline_ns);
    /* A driver that ignores the swap interval: 250 fps under vsync at 60 Hz turns the timer on. */
    before=timer_waits;frames(260,4000000ull);assert(vsync_unreliable && logs==1 && timer_waits>before);
    /* Injected pace: a released-machine nap counted as pace, the lock wait after it is not. */
    vsync_unreliable=0;vsync_window_start=0;
    uint64_t pace_before=pace_total_ns;inject=30000000ull;lock_extra=5000000ull;
    frames(1,0);lock_extra=0;
    assert(naps==1 && pace_total_ns-pace_before>=30000000ull && pace_total_ns-pace_before<35000000ull && owned);
    /* No monitor: no rt statistics are gathered. */
    void_frame_monitor_on=0;unsigned seen=monitors;frames(2,2000000ull);assert(monitors==seen);
    puts("PASS single pacer: vsync at cap==refresh with the render thread, timer for cadences/immediate/inline GL/unreliable vsync, injected pace without lock wait, monitor input");
    return 0;
}
'''


class PerfDiagTest(unittest.TestCase):
    def test_classifier(self):
        source = resolved("android/host/perf_diag.c")
        enum = source[source.index("enum { C_CPU,"):source.index("\n", source.index("enum { C_CPU,"))]
        compile_probe("perf_classify", CLASSIFY.replace("/* ACTUAL_ENUM */", enum)
                      .replace("/* ACTUAL_CLASSIFY */", function(source, "static int classify(")), {})

    def test_effective_cap(self):
        source = resolved("android/host/port_settings.c")
        compile_probe("perf_cadence", CADENCE.replace("/* ACTUAL_CADENCE */", function(source, "static float effective_cap(")), {})

    def test_single_pacer(self):
        source = resolved("android/host/d3d9_gl.c")
        statics = source[source.index("static uint64_t pace_total_ns;"):source.index("/* One pacer (C6)")]
        body = "\n".join([statics, function(source, "static void frame_limit("), function(source, "static int pace_by_vsync("),
                          function(source, "void d3d_gl_frame_pace(")])
        compile_probe("perf_pacer", PACE.replace("/* ACTUAL_PACE */", body), {})

    def test_hyperos_java_check(self):
        source = (ROOT / "android/app/src/org/homm5/port/PerfMonitor.java").read_text(encoding="utf8")
        pattern = re.search(r'private static final Pattern HYPEROS_VERSION = Pattern.compile\(".*?"\);', source).group(0)
        method = function(source, "    static boolean hyperOs(")
        check = ("import java.util.regex.Pattern;\npublic class HyperOsCheck {\n    " + pattern + "\n" + method + """
    public static void main(String[] a) {
        assert hyperOs("Xiaomi", "OS3.0.3.0.WNLRUXM");
        assert hyperOs("XIAOMI", "OS2.0.1.0.VNCCNXM");
        assert hyperOs("xiaomi", "OS1.0.7.0.UMQMIXM");
        assert !hyperOs("Xiaomi", "V14.0.5.0.TMRMIXM");
        assert !hyperOs("Xiaomi", "");
        assert !hyperOs("Xiaomi", null);
        assert !hyperOs("Google", "OS3.0.3.0.WNLRUXM");
        assert !hyperOs(null, "OS3.0.3.0.WNLRUXM");
        System.out.println("PASS Java HyperOS check: OSx.y incremental on Xiaomi only");
    }
}
""")
        out = ROOT / "build/java-hyperos-check"
        out.mkdir(parents=True, exist_ok=True)
        (out / "HyperOsCheck.java").write_text(check, encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-d", str(out), str(out / "HyperOsCheck.java")], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "HyperOsCheck"], check=True)

    def test_every_engine_compiles_all_of_it(self):
        # 2026-11-20: ported to 1.6/2.1 (TECHDEBT-LEGACY); their copies keep every hook and no edition guard.
        for legacy in (False, True):
            native = resolved("android/host/perf_diag.c", legacy=legacy)
            self.assertIn("void_frame_monitor", native)
            self.assertIn("JNIEXPORT", native)
            for path in ("android/host/threads.c", "android/host/d3d9_gl.c", "android/host/d3d9_dxvk.c", "android/host/perf.c",
                         "android/host/port_settings.c", "android/host/d3d9_thread.c", "android/host/android_main.c"):
                text = resolved(path, legacy=legacy)
                self.assertEqual(text, resolved(path), path)
        for name in ("void_frame_monitor", "void_port_effective_fps", "lock_wait_done", "VOID_RT_EARLY",
                     "h5-game", "void_diag_exit", "pin_checked", "slot_register"):
            self.assertTrue(any(name in resolved(path, legacy=True) for path in (
                "android/host/threads.c", "android/host/d3d9_gl.c", "android/host/d3d9_dxvk.c", "android/host/perf.c",
                "android/host/port_settings.c", "android/host/d3d9_thread.c", "android/host/android_main.c",
                "android/host/perf_diag.c")), name)
        activity = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8").replace("\r\n", "\n")
        self.assertIn('\n        perf = PerfMonitor.start(this, base, gameDir, renderer,', activity)
        self.assertNotIn('if ("toe".equals(gameEdition())) {\n            perf = PerfMonitor.start(', activity)
        self.assertEqual(activity.count("PerfMonitor.start("), 1)

    def test_java_natives_exist_in_the_toe_engine(self):
        java = (ROOT / "android/app/src/org/homm5/port/PerfMonitor.java").read_text(encoding="utf8")
        native = resolved("android/host/perf_diag.c")
        names = re.findall(r"static native \w+ (native\w+)\(", java)
        self.assertEqual(len(names), 6)
        for name in names:
            self.assertIn("Java_org_homm5_port_PerfMonitor_" + name + "(", native)
        header = (ROOT / "android/host/perf_diag.h").read_text(encoding="utf8")
        bits = re.findall(r"(OPT_\w+) = 1(?: << (\d+))?[,;]", java)
        self.assertEqual(len(bits), 10)
        for bit, shift in bits:
            self.assertRegex(header, r"PERF_%s = 1u << %d," % (bit, int(shift or 0)))

    def test_line_types_follow_the_format(self):
        native = resolved("android/host/perf_diag.c")
        java = (ROOT / "android/app/src/org/homm5/port/PerfMonitor.java").read_text(encoding="utf8")
        allowed = {"start", "env", "cpu", "threads", "display", "probe", "win", "long", "event", "vendorlog", "end"}
        self.assertEqual(set(re.findall(r'diag_line\("(\w+)"', native)) - allowed, set())
        self.assertEqual(set(re.findall(r'line\("(\w+)"', java)) - allowed, set())
        self.assertIn('"[hyperos] %s t=%.3f diag=1%s%s"', native)
        # The start line names the engine's own edition (edition.h), not a fixed one.
        self.assertNotIn("edition=toe", native)
        self.assertIn("build=%s edition=%s rt=%d", native)
        self.assertIn("void_build_id(), DIAG_EDITION,", native)
        self.assertIn("#define DIAG_EDITION HOMM5_EDITION", native)


if __name__ == "__main__":
    unittest.main()
