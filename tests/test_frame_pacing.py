"""Execute the production deadline scheduler with interrupted waits and guest ownership."""
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#define CLOCK_MONOTONIC 1
#define TIMER_ABSTIME 1
#define EGL_NO_SURFACE 0
static int window_mode=1,egl_surface=1,owned=1,interrupts,fail_wait;
static uint64_t frame_deadline_ns,frame_period_ns,fake_now=1000000000ull,oversleep;
static unsigned waits,releases,acquires,audio_work,errors;
static float limit=60;
static float void_port_fps_limit(void){return limit;}
static uint64_t void_perf_now_ns(void){assert(owned);return fake_now;}
static void void_blocking_begin(void){assert(owned);owned=0;++releases;}
static void void_blocking_end(void){assert(!owned);owned=1;++acquires;}
static void void_log(const char *format,int error){assert(format&&error==EINVAL);++errors;}
static int clock_nanosleep(int clock,int flags,const struct timespec *deadline,struct timespec *remaining){
 assert(!owned&&clock==CLOCK_MONOTONIC&&flags==TIMER_ABSTIME&&!remaining);
 ++waits;++audio_work;
 uint64_t target=(uint64_t)deadline->tv_sec*1000000000ull+(uint64_t)deadline->tv_nsec;
 assert(target==frame_deadline_ns&&target>fake_now);
 if(interrupts){--interrupts;return EINTR;}
 if(fail_wait)return EINVAL;
 fake_now=target+oversleep;return 0;
}
#include "pacing.h"
int main(void){
 d3d_gl_frame_pace();assert(!waits&&frame_deadline_ns==fake_now+16666666ull);
 fake_now+=5000000ull;interrupts=2;d3d_gl_frame_pace();
 assert(waits==3&&releases==1&&acquires==1&&audio_work==3&&owned);
 assert(fake_now==1016666666ull&&frame_deadline_ns==1033333332ull);
 /* Absolute deadlines retain phase rather than adding render time to each period. */
 fake_now+=4000000ull;d3d_gl_frame_pace();assert(fake_now==1033333332ull&&frame_deadline_ns==1049999998ull);
 /* A long transition or oversleep starts a fresh schedule, without catch-up sleeps. */
 fake_now+=2000000000ull;unsigned before=waits;d3d_gl_frame_pace();assert(waits==before&&frame_deadline_ns==fake_now+16666666ull);
 fake_now+=1000000ull;oversleep=1000000000ull;d3d_gl_frame_pace();assert(frame_deadline_ns==fake_now+16666666ull);oversleep=0;
 /* Every exposed mode changes immediately. Zero leaves presentation to the display. */
 limit=30;d3d_gl_frame_pace();assert(frame_period_ns==33333333ull&&frame_deadline_ns==fake_now+33333333ull);
 fake_now+=2000000ull;d3d_gl_frame_pace();assert(frame_deadline_ns==fake_now+33333333ull);
 limit=45;d3d_gl_frame_pace();assert(frame_period_ns==22222222ull&&frame_deadline_ns==fake_now+22222222ull);
 before=waits;limit=0;d3d_gl_frame_pace();assert(!frame_deadline_ns&&waits==before);
 limit=60;d3d_gl_frame_pace();assert(frame_deadline_ns==fake_now+16666666ull);
 window_mode=0;d3d_gl_frame_pace();assert(!frame_deadline_ns&&waits==before);window_mode=1;
 d3d_gl_frame_pace();egl_surface=EGL_NO_SURFACE;d3d_gl_frame_pace();assert(!frame_deadline_ns&&waits==before);egl_surface=1;
 d3d_gl_frame_pace();fail_wait=1;d3d_gl_frame_pace();assert(errors==1&&owned&&!frame_deadline_ns&&releases==acquires);
 puts("PASS frame cap: 30/45/60/display, absolute phase, EINTR, released guest for audio, stalls/oversleep/mode/surface reset, failed wait reacquires");
 return 0;
}
'''


class FramePacingTest(unittest.TestCase):
    def test_actual_deadlines_and_guest_release(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
        pace = function(source, "void d3d_gl_frame_pace(")
        compile_probe("frame_pacing", HARNESS, {"pacing.h": pace})
        with self.assertRaisesRegex(AssertionError, "Assertion failed"):
            compile_probe("frame_pacing_missing_release", HARNESS,
                          {"pacing.h": pace.replace("void_blocking_begin();", "/* omitted */", 1)})

    def test_surface_and_device_reset_deadline(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf8")
        for name in ("static void follow_window(", "int d3d_gl_init(", "void d3d_gl_device_destroy("):
            self.assertIn("frame_deadline_ns = 0;", function(source, name))


if __name__ == "__main__":
    unittest.main()
