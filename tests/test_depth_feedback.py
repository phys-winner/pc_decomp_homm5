"""Execute the CPU-only retained-depth capture from the production renderer."""
from pathlib import Path
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN


def fixture():
    source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
    start = source.index("typedef struct { GLuint tex; GLenum target; GLint level, layer; } fb_attachment;")
    stop = source.index("void d3d_gl_forget_texture(", start)
    helpers = source[source.index("/* Dedicated CPU-only capture;"):
                     source.index("/* ------------------------------------------------------------ attributes */")]
    return ((ROOT / "tests/depth_feedback_probe.c").read_text(encoding="utf-8")
            .replace("/* ACTUAL_ATTACHMENTS */", source[start:stop])
            .replace("/* ACTUAL_DEPTH_POINT */", function(source, "static GLenum depth_attachment("))
            .replace("/* ACTUAL_FORGET */", function(source, "void d3d_gl_forget_texture("))
            .replace("/* ACTUAL_TARGETS */", "static void ui_prepare_depth(d3d_device *d) { (void)d; }\n"
                     "static d3d_surface *ui_surface(d3d_device *d,d3d_surface *s) { (void)d;return s; }\n" +
                     function(source, "void d3d_gl_bind_targets("))
            .replace("/* ACTUAL_HELPERS */", helpers))


class DepthFeedbackTest(unittest.TestCase):
    @staticmethod
    def compiler():
        # Atomic builtins are the same ones used by the Android host.
        return (TOOLCHAIN / 'bin/clang-cl.exe')

    def test_actual_production_capture_does_not_change_render_state(self):
        compile_probe("depth_feedback", fixture(), {}, extra_flags=("/O2",),
                      compiler_override=self.compiler())

    def test_inactive_samplers_must_not_be_reported_as_aliases(self):
        source = fixture()
        exclusion = "if (slot < 16 ? !(ps & (1u << slot)) : !(vs & (1u << (slot - 16)))) continue;"
        self.assertEqual(source.count(exclusion), 2)
        # Keep parameters consumed for -Werror, but admit inactive slots.
        source = source.replace(exclusion, "(void)ps; (void)vs;", 1)
        with self.assertRaises(AssertionError) as error:
            compile_probe("depth_feedback_bad_mask", source, {}, extra_flags=("/O2",),
                          compiler_override=self.compiler())
        self.assertIn("!retained_depth_sampler_mask(&d,0,0)", str(error.exception))

    def test_capture_hooks_are_bounded_and_separate_from_render_trace(self):
        source = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
        helpers = source[source.index("/* Dedicated CPU-only capture;"):
                         source.index("/* ------------------------------------------------------------ attributes */")]
        self.assertNotRegex(helpers, r"\b(?:glGet\w*|glRead\w*|glFinish|glFlush|glFence\w*|glBeginQuery)\s*\(")
        self.assertNotIn("detach_retained_depth_alias", source)
        request = function(source, "void d3d_request_depth_trace(")
        self.assertNotIn("g_d3d_device", request)
        self.assertIn("__atomic_store_n", request)
        self.assertIn("__atomic_exchange_n", function(source, "static void depth_trace_present("))
        draw = function(source, "int d3d_gl_draw(")
        self.assertIn("if (depth_trace_remaining) depth_trace_draw(", draw)
        self.assertLess(draw.index("for (int s = 0; s < 4; ++s) if (vs_samplers"),
                        draw.index("depth_trace_draw("))
        self.assertLess(draw.index("depth_trace_draw("), draw.index("/* UP data */"))
        present = function(source, "void d3d_gl_present(")
        self.assertEqual(present.count("depth_trace_present(dev);"), 1)
        destroy = function(source, "void d3d_gl_device_destroy(")
        self.assertIn("depth_trace_remaining = 0;", destroy)
        self.assertIn("__atomic_store_n(&depth_trace_requested, 0u", destroy)
        script = (ROOT / "android/host/script.c").read_text(encoding="utf-8")
        self.assertIn('!strcmp(e->action, "depthtrace")', script)
        event = function(script, "static void run_event(")
        branch = event[event.index('!strcmp(e->action, "depthtrace")'):
                       event.index('!strcmp(e->action, "trace")')]
        self.assertIn("d3d_request_depth_trace();", branch)
        self.assertNotIn("d3d_request_trace();", branch)


if __name__ == "__main__":
    unittest.main()
