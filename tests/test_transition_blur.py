"""port_battle_blur: the battle-entry transition's layered quads merge into one smooth zoom.

The transition (0x00CB31E0) draws two batches of ten translucent UI quads of two 256x256 render
targets, each quad a scaled and shifted copy of the one before (0x00CB2E10, 0x00CB2FB0).
android/host/d3d9_gl.c fits each quad's uv = map.xy * position + map.zw (xt_fit), derives each
layer's step to its neighbour (xt_steps) and the uv rectangle of its edges inside the viewport
(xt_layers), draws the layers one at a time into a half-size canvas (gl_draw, xt_canvas) and UI
filter 4 (android/host/d3d9_filter.h, vpZoomBlur) blurs each along its step and feathers its edges.
Production code is extracted by anchor; the shader runs on local ANGLE.
"""
import ctypes as C
import json
import unittest

import test_legacy_shaders as shaders
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

GL = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")


def entry_type():
    start = GL.index("typedef struct { GLuint key, tex, depth;")
    return GL[start:GL.index("} xt_entry;", start) + len("} xt_entry;")] + "\n"


LAYERS_HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned GLuint;
typedef int GLsizei;
typedef struct { GLuint gl; uint32_t width, height; } d3d_texture;
typedef struct { struct { uint32_t viewport[4]; } st; uint32_t frame; } d3d_device;
#include "entry.h"
#define XT_LAYERS 32
static xt_entry table[3];
static int adopted;
static xt_entry *xt_find(GLuint key) { for (int i = 0; i < 3; ++i) if (key && table[i].key == key) return &table[i]; return NULL; }
static xt_entry *xt_adopt(d3d_texture *t) { ++adopted; memset(&table[t->gl], 0, sizeof table[t->gl]); table[t->gl].key = t->gl; return &table[t->gl]; }
static int render_xt_blur;
static float render_xt_steps[XT_LAYERS][4], render_xt_rects[XT_LAYERS][4], render_xt_spread;
#define XT_QUARTER_SPREAD 16.0f
static uint32_t xt_spread_frame;
static float xt_spread_now, xt_spread_last;
#include "fit.h"
#include "steps.h"
#include "layers.h"
#include "divisor.h"

/* 0x00A47580 + 0x00A47260: integer destination, source shrunk so texel centres meet pixel centres,
 * positions - 0.5, uv = source / 256; corners (x0,y0) (x0,y1) (x1,y1) (x1,y0). */
static int quad(const float dst[4], const float src_in[4], float map[4], float extent[2], float rect[4])
{
    float x0 = (float)(int)dst[0], y0 = (float)(int)dst[1], x1 = (float)(int)dst[2], y1 = (float)(int)dst[3], src[4];
    memcpy(src, src_in, sizeof src);
    for (int a = 0; a < 2; ++a) {
        float d = fabsf((a ? y1 - y0 : x1 - x0)), s = fabsf(src[2 + a] - src[a]), mid = (src[a] + src[2 + a]) * 0.5f;
        if (d != s && d > s && s > 0.0f && d > 1.0f) {
            float k = (s - 1.0f) / s * d / (d - 1.0f);
            src[a] = (src[a] - mid) * k + mid;
            src[2 + a] = (src[2 + a] - mid) * k + mid;
        }
    }
    float pos[4][2] = { { x0 - 0.5f, y0 - 0.5f }, { x0 - 0.5f, y1 - 0.5f }, { x1 - 0.5f, y1 - 0.5f }, { x1 - 0.5f, y0 - 0.5f } };
    float uv[4][2] = { { src[0] / 256, src[1] / 256 }, { src[0] / 256, src[3] / 256 }, { src[2] / 256, src[3] / 256 }, { src[2] / 256, src[1] / 256 } };
    return xt_fit(pos, uv, 4, map, extent, rect);
}

static const float drift = 3.0f, dir_c = -0.8202f, dir_s = -0.5721f;   /* device: ft_transition_length, angle */

/* Group 1 (0x00CB2E10): the whole texture into rectangles shrinking by 1 / lerp(1, 4, i / 9 * a), drifting. */
static void group1(int i, float a, float dst[4], float src[4])
{
    const float cx = 1200, cy = 540;
    float v = (float)i / 9.0f * a, z = 1.0f / (1.0f + 3.0f * v), ox = dir_c * cx * drift * z * v, oy = drift * cy * dir_s * z * v;
    dst[0] = cx - z * cx + ox; dst[1] = cy - z * cy + oy; dst[2] = ox + cx + z * cx; dst[3] = oy + cy + z * cy;
    src[0] = src[1] = 0; src[2] = src[3] = 256;
}

/* Group 2 (0x00CB2FB0): the whole screen from source rectangles of lerp(1, 0.5, i / 9 * (1 - a)), drifting. */
static void group2(int i, float a, float dst[4], float src[4])
{
    const float half = 128;
    float v = (float)i / 9.0f * (1.0f - a), z = 1.0f - 0.5f * v, ox = dir_c * drift * z * v * half, oy = v * (drift * dir_s * z) * half;
    dst[0] = 0; dst[1] = 0; dst[2] = 2400; dst[3] = 1080;
    src[0] = half - z * half + ox; src[1] = half - z * half + oy; src[2] = ox + z * half + half; src[3] = oy + z * half + half;
}

static double worst;
static int checked, inner_edges, border_edges;
static void check(const float *step, const float self[4], const float other[4])
{
    for (int px = 0; px <= 2400; px += 300)
        for (int py = 0; py <= 1080; py += 270) {
            float x = (float)px, y = (float)py, u = self[0] * x + self[2], v = self[1] * y + self[3];
            float du = u - (other[0] * x + other[2]), dv = v - (other[1] * y + other[3]);
            double eu = fabs(step[0] * u + step[2] - du), ev = fabs(step[1] * v + step[3] - dv);
            if (eu > worst) worst = eu;
            if (ev > worst) worst = ev;
            ++checked;
        }
}

/* An edge inside the viewport is the uv of that edge of the quad; an edge on the border is open. */
static void check_rect(const float *uvrect, const float map[4], const float rect[4])
{
    for (int a = 0; a < 2; ++a)
        for (int side = 0; side < 2; ++side) {
            float position = rect[2 * side + a], border = a ? (side ? 1080.0f : 0.0f) : (side ? 2400.0f : 0.0f);
            float edge = map[a] * position + map[2 + a];
            int inside = side ? position < border - 1.0f : position > border + 1.0f;
            float got = uvrect[2 * side + a];
            if (inside) { assert(fabsf(got - edge) < 1e-5f); ++inner_edges; }
            else { assert(got == (side ? 1e4f : -1e4f)); ++border_edges; }
        }
}

int main(void)
{
    d3d_device dev = { { { 0, 0, 2400, 1080 } }, 100 };
    d3d_texture ft1 = { 1, 256, 256 }, ft2 = { 2, 256, 256 };
    static float maps[XT_LAYERS][4], extents[XT_LAYERS][2], rects[XT_LAYERS][4];
    float dst[4], src[4];
    double longest = 0;
    int quarter = 0, half = 0, divisors[30];
    for (int frame = 0; frame < 30; ++frame, ++dev.frame) {
        float a = 1.0f - frame / 29.0f;                    /* reverse 1: groups run on 1 - t */
        for (int g = 0; g < 2; ++g) {
            d3d_texture *tex = g ? &ft1 : &ft2;              /* reverse: group 1 the battle, group 2 the map */
            for (int n = 0; n < 10; ++n) {
                int i = g ? n : 9 - n;                       /* group 1 draws its smallest layer first */
                if (g) group2(i, a, dst, src); else group1(i, a, dst, src);
                assert(quad(dst, src, maps[n], extents[n], rects[n]));
            }
            render_xt_blur = 0;
            xt_layers(&dev, tex, maps, extents, rects, 10);
            assert(render_xt_blur == 10 && render_xt_spread >= 0.0f);
            if (!g) { divisors[frame] = xt_canvas_divisor(); if (divisors[frame] == 4) ++quarter; else ++half; }
            for (int n = 0; n < 10; ++n) {
                check(render_xt_steps[n], maps[n], maps[n ? n - 1 : 1]);
                check_rect(render_xt_rects[n], maps[n], rects[n]);
                double len = hypot(render_xt_steps[n][0] * 0.5 + render_xt_steps[n][2], render_xt_steps[n][1] * 0.5 + render_xt_steps[n][3]);
                if (len > longest) longest = len;
            }
        }
    }
    assert(adopted == 2 && worst < 2e-4 && longest > 0.01 && inner_edges > 1000 && border_edges > 1000);
    /* Half while one group is nearly sharp (the first frame, the last ones), a quarter in between. */
    assert(divisors[0] == 2 && divisors[29] == 2 && divisors[15] == 4 && quarter > 20 && half >= 2);
    /* One quad alone is no layer; minified quads (GlowTex256 into GlowTex128) adopt nothing. */
    render_xt_blur = 0;
    xt_layers(&dev, &ft1, maps, extents, rects, 1);
    assert(!render_xt_blur);
    d3d_texture glow = { 0, 256, 256 };
    float small[4] = { 0, 0, 128, 128 }, whole[4] = { 0, 0, 256, 256 };
    assert(quad(small, whole, maps[0], extents[0], rects[0]) && quad(small, whole, maps[1], extents[1], rects[1]) && extents[0][0] < 256);
    xt_layers(&dev, &glow, maps, extents, rects, 2);
    assert(adopted == 2 && !render_xt_blur);
    printf("PASS transition layers: %d step checks over 600 layers exact to %.2g uv (longest step %.3f uv); "
           "%d inner edges feathered, %d viewport edges open; %d frames at quarter, %d at half size; "
           "2 targets adopted, single quads and minified glow not\n",
           checked, worst, longest, inner_edges, border_edges, quarter, half);
    return 0;
}
'''

FIT_HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include "fit.h"
int main(void)
{
    float map[4], extent[2], rect[4];
    float pos[6][2] = { { 0, 0 }, { 0, 100 }, { 200, 100 }, { 0, 0 }, { 200, 100 }, { 200, 0 } };
    float uv[6][2] = { { 0.25f, 0 }, { 0.25f, 1 }, { 0.75f, 1 }, { 0.25f, 0 }, { 0.75f, 1 }, { 0.75f, 0 } };
    assert(xt_fit(pos, uv, 6, map, extent, rect));
    assert(fabsf(map[0] - 0.0025f) < 1e-7f && fabsf(map[2] - 0.25f) < 1e-7f && fabsf(map[1] - 0.01f) < 1e-7f);
    assert(extent[0] == 200 && extent[1] == 100 && rect[0] == 0 && rect[1] == 0 && rect[2] == 200 && rect[3] == 100);
    uv[2][1] = 0.5f;                                    /* not affine: one corner elsewhere */
    assert(!xt_fit(pos, uv, 6, map, extent, rect));
    uv[2][1] = 1;
    float rotated[4][2] = { { 0, 0 }, { 0, 100 }, { 200, 100 }, { 200, 0 } };
    float swapped[4][2] = { { 0, 0 }, { 1, 0 }, { 1, 1 }, { 0, 1 } };   /* u follows y: rotated texture */
    assert(!xt_fit(rotated, swapped, 4, map, extent, rect));
    float line[4][2] = { { 0, 0 }, { 0, 0.5f }, { 200, 0.5f }, { 200, 0 } };
    assert(!xt_fit(line, swapped, 4, map, extent, rect));       /* no height */
    float flat[4][2] = { { 0.5f, 0 }, { 0.5f, 1 }, { 0.5f, 1 }, { 0.5f, 0 } };
    assert(!xt_fit(rotated, flat, 4, map, extent, rect));       /* one texel column stretched */
    float nan_uv[4][2] = { { NAN, 0 }, { NAN, 1 }, { NAN, 1 }, { NAN, 0 } };
    assert(!xt_fit(rotated, nan_uv, 4, map, extent, rect));
    puts("PASS transition fit: axis-aligned affine quads only, with their corners");
    return 0;
}
'''


class TransitionBlurTest(unittest.TestCase):
    def test_layer_steps_and_edges_follow_the_engine_layers(self):
        """Quads made as 0x00CB2E10/0x00CB2FB0 and 0x00A47580 make them (preset read on the device:
        group 1 z 1..4, group 2 z 1..0.5, drift length 3, reverse 1), ten per draw: each layer's step
        is the displacement to its neighbour at every pixel, its feathered edges are its own edges
        inside the viewport."""
        compile_probe("transition_layers", LAYERS_HARNESS, {
            "entry.h": entry_type(),
            "fit.h": function(GL, "static int xt_fit("),
            "steps.h": function(GL, "static void xt_steps("),
            "layers.h": function(GL, "static void xt_layers("),
            "divisor.h": function(GL, "static int xt_canvas_divisor(")})

    def test_fit_takes_only_axis_aligned_affine_quads(self):
        compile_probe("transition_fit", FIT_HARNESS, {"fit.h": function(GL, "static int xt_fit(")})

    def test_draw_splits_layers_into_a_half_size_canvas_resolved_before_any_other_use(self):
        draw = function(GL, "static int gl_draw(")
        self.assertLess(draw.index("xt_layers(d, t0, maps, extents, rects, quads)"), draw.index("d3d_gl_bind_targets(d)"))
        self.assertLess(draw.index("render_xt_blur = 0;"), draw.index("xt_layers(d, t0, maps, extents, rects, quads)"))
        # Every non-instanced GL draw goes out one layer at a time, each with its step and rectangle.
        self.assertEqual(draw.count("if (parts > 1) xt_uniforms(part);"), 3)
        begin, end = draw.index("int canvas = parts > 1 && xt_canvas_begin(d);"), draw.index("if (canvas) xt_canvas_end();")
        self.assertLess(begin, draw.index("glDrawElements(mode, part_count"))
        self.assertLess(draw.index("glDrawArrays(mode, draw_start + part * part_count, part_count)"), end)
        self.assertLess(end, draw.index("render_xt_blur = 0;                        /* a clear or blit"))
        # The canvas reaches its target before anything else draws, clears, copies, reads or presents it.
        self.assertIn("if (!render_xt_blur) xt_canvas_resolve();", function(GL, "void d3d_gl_bind_targets("))
        for name in ("static void gl_blit_ex(", "static int gl_read_rgba(", "static void gl_fill(", "static void gl_present("):
            with self.subTest(function=name):
                body = function(GL, name)
                self.assertLess(body.index("xt_canvas_resolve();"), body.index("\n", body.index("{") + 2) + 40)
        self.assertIn("xt_canvas_release();", function(GL, "static void gl_device_destroy("))
        canvas = function(GL, "static int xt_canvas_begin(")
        self.assertIn("(t->width + 1) / 2", canvas)
        self.assertIn("fb_color[0].samples", canvas)               # not for a multisampled target
        quads = function(GL, "static int xt_quads(")
        self.assertIn("d->st.vs_f[16][0]", quads)              # SHORT2 coordinates of the UI vertex shader
        self.assertIn("el[1]->type == 6 || el[1]->type == 7", quads)
        self.assertNotIn("glTexStorage2D", function(GL, "static xt_entry *xt_backing("))   # only xt_adopt makes backings
        self.assertEqual(GL.count("xt_adopt("), 2)          # definition and xt_layers
        bind = function(GL, "static int xt_bind(")
        self.assertIn("sampler_for(state, 0, 2, 0)", bind)
        self.assertNotIn("GL_CLAMP_TO_EDGE", bind)
        self.assertIn("return render_xt_blur ? 4 :", GL)


class TransitionShaderBase:
    """UI filter 4 on ANGLE: copies of a WIDTH-texel white line, each shifted by one step, blended as
    the transition blends its layers. Subclasses set the geometry."""
    W, H, STEP, LINE, LAYERS, WIDTH = 256, 8, 8, 200, 10, 2
    OPEN = (-1e4, -1e4, 1e4, 1e4)                 # vpUiBlurRect: no edge to feather

    @classmethod
    def setUpClass(cls):
        cls.out = ROOT / "build/tests/transition_blur"
        cls.out.mkdir(parents=True, exist_ok=True)
        pixel = ("#version 310 es\nprecision highp float;uniform sampler2D image;uniform vec4 layer;uniform float alpha;"
                 "layout(location=0)out vec4 color;"
                 "void main(){color=texture(image,gl_FragCoord.xy*layer.xy+layer.zw);color.a*=alpha;}")
        harness = r"""
#include <assert.h>
#include "d3d9_filter.h"
int main(void){
 char *ui=d3d_ui_filter_source(PIXEL);assert(ui&&strstr(ui,"vpZoomBlur(image,uv)"));
 FILE *f=fopen(OUT "/layer.frag","wb");assert(f);fputs(ui,f);fclose(f);free(ui);return 0;
}
""".replace("PIXEL", json.dumps(pixel))
        harness = "#define OUT " + json.dumps(cls.out.as_posix()) + "\n" + harness
        compile_probe("transition_blur_source", harness, {name: (ROOT / "android/host" / name).read_text()
                                                          for name in ("d3d9_filter.h", "fsr1.h")})

    def setUp(self):
        self.angle = angle = shaders.Angle()
        gl = angle.gl
        for name, result, args in [
                ("glUniform1f", None, [C.c_int, C.c_float]),
                ("glUniform4f", None, [C.c_int, C.c_float, C.c_float, C.c_float, C.c_float]),
                ("glGenFramebuffers", None, [C.c_int, C.POINTER(C.c_uint)]),
                ("glBindFramebuffer", None, [C.c_uint, C.c_uint]),
                ("glFramebufferTexture2D", None, [C.c_uint, C.c_uint, C.c_uint, C.c_uint, C.c_int]),
                ("glGenerateMipmap", None, [C.c_uint]),
                ("glEnable", None, [C.c_uint]),
                ("glDisable", None, [C.c_uint]),
                ("glBlendFunc", None, [C.c_uint, C.c_uint]),
                ("glClearColor", None, [C.c_float] * 4),
                ("glClear", None, [C.c_uint])]:
            angle.api(gl, name, result, *args)
        vertex = (b"#version 310 es\nvoid main(){vec2 p=vec2(gl_VertexID&1,gl_VertexID>>1)*2.0-1.0;"
                  b"gl_Position=vec4(p,0.0,1.0);}")
        vs, fs = angle.compile(vertex, 0x8B31), angle.compile((self.out / "layer.frag").read_bytes())
        self.program = gl.glCreateProgram()
        gl.glAttachShader(self.program, vs)
        gl.glAttachShader(self.program, fs)
        gl.glLinkProgram(self.program)
        status = C.c_int()
        gl.glGetProgramiv(self.program, 0x8B82, C.byref(status))
        self.assertTrue(status.value)
        gl.glUseProgram(self.program)
        # The image: a WIDTH-texel white line at x = LINE on black, as wide as the target,
        # mipmapped, trilinear, clamped.
        tex = C.c_uint()
        gl.glGenTextures(1, C.byref(tex))
        gl.glActiveTexture(0x84C0)
        gl.glBindTexture(0x0DE1, tex)
        white, black = bytes((255, 255, 255, 255)), bytes((0, 0, 0, 255))
        row = b"".join(white if self.LINE <= x < self.LINE + self.WIDTH else black for x in range(self.W))
        gl.glTexImage2D(0x0DE1, 0, 0x8058, self.W, 16, 0, 0x1908, 0x1401, row * 16)
        gl.glGenerateMipmap(0x0DE1)
        gl.glTexParameteri(0x0DE1, 0x2801, 0x2703)          # LINEAR_MIPMAP_LINEAR
        gl.glTexParameteri(0x0DE1, 0x2800, 0x2601)
        for key in (0x2802, 0x2803):
            gl.glTexParameteri(0x0DE1, key, 0x812F)
        target, fbo = C.c_uint(), C.c_uint()
        gl.glGenTextures(1, C.byref(target))
        gl.glActiveTexture(0x84C1)
        gl.glBindTexture(0x0DE1, target)
        gl.glTexImage2D(0x0DE1, 0, 0x8058, self.W, self.H, 0, 0x1908, 0x1401, None)
        gl.glActiveTexture(0x84C0)
        gl.glGenFramebuffers(1, C.byref(fbo))
        gl.glBindFramebuffer(0x8D40, fbo)
        gl.glFramebufferTexture2D(0x8D40, 0x8CE0, 0x0DE1, target, 0)
        gl.glViewport(0, 0, self.W, self.H)
        gl.glUniform1i(gl.glGetUniformLocation(self.program, b"image"), 0)

    def layers(self, mode, step, rect=None):
        gl, program = self.angle.gl, self.program
        gl.glClearColor(0, 0, 0, 1)
        gl.glClear(0x4000)
        gl.glEnable(0x0BE2)
        gl.glBlendFunc(0x0302, 0x0303)
        gl.glUniform1i(gl.glGetUniformLocation(program, b"vpUiFilter"), mode)
        s = self.STEP / float(self.W)
        gl.glUniform4f(gl.glGetUniformLocation(program, b"vpUiBlur"), 0.0, 0.0, s * step, 0.0)
        gl.glUniform4f(gl.glGetUniformLocation(program, b"vpUiBlurRect"), *(rect or self.OPEN))
        for k in range(self.LAYERS):   # each layer shifted by one step; the first opaque, then 0.264 (0x00CB2E10)
            gl.glUniform4f(gl.glGetUniformLocation(program, b"layer"), 1.0 / self.W, 1.0 / self.H, k * s, 0.0)
            gl.glUniform1f(gl.glGetUniformLocation(program, b"alpha"), 1.0 if k == 0 else 0.264)
            gl.glDrawArrays(5, 0, 4)
        gl.glDisable(0x0BE2)
        pixels = (C.c_ubyte * (self.W * self.H * 4))()
        gl.glReadPixels(0, 0, self.W, self.H, 0x1908, 0x1401, pixels)
        self.assertEqual(gl.glGetError(), 0)
        row = self.H // 2
        return [pixels[(row * self.W + x) * 4] for x in range(self.W)]

    @staticmethod
    def variation(profile):
        return sum(abs(b - a) for a, b in zip(profile, profile[1:]))


class StreakTests:
    def test_copies_merge_into_one_streak(self):
        plain, blurred = self.layers(1, 1.0), self.layers(4, 1.0)
        span = range(self.LINE - (self.LAYERS - 1) * self.STEP + self.WIDTH, self.LINE)
        # Plain sampling: separate copies of the line, black between them.
        self.assertEqual(min(plain[x] for x in span), 0)
        # Filter 4: one streak lit all along it, with a fraction of the ups and downs.
        self.assertGreater(min(blurred[x] for x in span), 0)
        self.assertLess(self.variation(blurred), 0.25 * self.variation(plain))
        # Light is moved, not lost.
        self.assertLess(abs(sum(blurred) - sum(plain)) / sum(plain), 0.15)

    def test_no_step_is_plain_sampling(self):
        plain, still = self.layers(1, 0.0), self.layers(4, 0.0)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(plain, still)), 1)


class TransitionBlurShaderTest(TransitionShaderBase, StreakTests, unittest.TestCase):
    """Ten copies of a thin line a step apart: plain sampling leaves ten ghosts; filter 4 one streak."""


class TransitionLongStepShaderTest(TransitionShaderBase, StreakTests, unittest.TestCase):
    """Steps of 192 texels (the drifting group's longest are ~340 on the 2048 backing): coarse mips
    still give one continuous streak with the light conserved. A 16-texel band keeps the spread
    light above 8-bit rounding; it stays far from the clamped edge, whose coarse mips would smear
    it across the empty side."""
    W, H, STEP, LINE, LAYERS, WIDTH = 2048, 8, 192, 1400, 4, 16


class TransitionFeatherShaderTest(TransitionShaderBase, unittest.TestCase):
    """One white layer whose own edges are at u = 0.25 and 0.75 (a shrinking layer inside the
    viewport): filter 4 fades it out over one step inside those edges instead of cutting it."""
    W, H, STEP, LINE, LAYERS, WIDTH = 256, 8, 16, 0, 1, 256

    def test_edges_inside_the_viewport_fade_over_one_step(self):
        cut = [255 if 64 <= x < 192 else 0 for x in range(self.W)]          # the same layer, hard-edged
        soft = self.layers(4, 1.0, (0.25, -1e4, 0.75, 1e4))
        self.assertLessEqual(max(soft[:64]), 1)                              # outside its rectangle: nothing
        self.assertTrue(all(abs(v - 255) <= 2 for v in soft[64 + 16:192 - 16]))   # one step in: the full layer
        ramp = soft[64:64 + 16]
        self.assertTrue(all(b >= a for a, b in zip(ramp, ramp[1:])) and 0 < ramp[8] < 255)
        self.assertLess(max(abs(b - a) for a, b in zip(soft, soft[1:])), 40)      # no step anywhere
        self.assertEqual(max(abs(b - a) for a, b in zip(cut, cut[1:])), 255)
        # The viewport's own edges (open rectangle) stay sharp.
        self.assertTrue(all(abs(v - 255) <= 2 for v in self.layers(4, 1.0)))


if __name__ == "__main__":
    unittest.main()
