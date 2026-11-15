"""Direct3D 9 fog on OpenGL ES: the production rules, adapters and generated halves.

The engine computes its distance/height fog in vs_1_1 shaders (oFog) and turns
D3DRS_FOGENABLE on per material (0x009ADE70); D3D9 then blends the pixel
shader's colour toward D3DRS_FOGCOLOR. These checks run the production code of
android/host/d3d9_ff.c and d3d9_shader.c (extracted by anchor) on the real
embedded H5 shaders and render the results with local ANGLE.
"""
import ctypes as C
import json
import math
import re
import unittest
from pathlib import Path

import test_legacy_shaders as shaders
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function

OUT = ROOT / "build/tests/fog"
SHADER = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
FF = (ROOT / "android/host/d3d9_ff.c").read_text(encoding="utf-8")
FOG_OFF, FOG_LINEAR, FOG_EXP, FOG_EXP2 = range(4)
FFOG = dict(NONE=0, SPECULAR=1, DEPTH=2, RANGE=3, ORTHO=4, TRANSFORMED=5, SHADER_DEPTH=6)


def fog_state_probe():
    """Wine's rule table, run through the production d3d_fog_state."""
    block = FF[FF.index("/* ----------------------------------------------------- fog state */"):
               FF.index("/* ------------------------------------------------------- vertex half */")]
    enums = FF[FF.index("enum { FOG_OFF, FOG_LINEAR"):FF.index("#define FOG_AVAILABLE")]
    harness = r'''
#define _CRT_NONSTDC_NO_DEPRECATE
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef struct { uint16_t stream, offset; uint8_t type, method, usage, usage_index; } d3d_vertex_element;
typedef struct { int count; d3d_vertex_element elements[64]; } d3d_decl;
typedef struct { struct { uint32_t rs[256]; void *decl; float transforms[512][16]; } st; } d3d_device;
static int port = 1;
static int d3d_gl_fog_enabled(void) { return port; }
#include "enums.h"
#include "state.h"
static uint32_t u(float f) { uint32_t v; memcpy(&v, &f, 4); return v; }
static int run(d3d_device *d, int vs, int ps, uint32_t want_coord, float end, float scale) {
 uint32_t coord = 99; float p[4] = {9, 9, 9, 9}, c[4];
 int formula = d3d_fog_state(d, vs, ps, &coord, p, c);
 if (formula) { assert(coord == want_coord); assert(fabsf(p[0] - end) < 1e-6f && fabsf(p[1] - scale) < 1e-6f); }
 return formula;
}
int main(void) {
 static d3d_device d; static d3d_decl post;
 post.count = 1; post.elements[0].usage = 9; post.elements[0].type = 3;
 for (int i = 0; i < 4; ++i) d.st.transforms[3][i * 5] = 1.0f;        /* identity projection: ortho */
 d.st.rs[34] = 0xFF336699u; d.st.rs[36] = u(10); d.st.rs[37] = u(110); d.st.rs[38] = u(0.5f);
 assert(run(&d, 1, 1, 0, 0, -1) == FOG_OFF);                          /* FOGENABLE 0 */
 d.st.rs[28] = 1;
 assert(run(&d, 1, 1, FFOG_NONE, 0, -1) == FOG_LINEAR);                /* vs oFog: start 1, end 0 */
 d.st.rs[140] = 1; assert(run(&d, 1, 2, FFOG_NONE, 0, -1) == FOG_LINEAR); /* FOGVERTEXMODE ignored */
 assert(run(&d, 1, 3, 0, 0, 0) == FOG_OFF && run(&d, 3, 0, 0, 0, 0) == FOG_OFF);   /* SM3 */
 d.st.rs[140] = 0; assert(run(&d, 0, 1, FFOG_SPECULAR, 0, -1) == FOG_LINEAR);      /* FF, vertex NONE */
 d.st.decl = &post; d.st.rs[140] = 3; assert(run(&d, 0, 0, FFOG_SPECULAR, 0, -1) == FOG_LINEAR); /* transformed */
 d.st.decl = NULL; assert(run(&d, 0, 0, FFOG_DEPTH, 110, 0.01f) == FOG_LINEAR);   /* vertex LINEAR */
 d.st.rs[48] = 1; assert(run(&d, 0, 0, FFOG_RANGE, 110, 0.01f) == FOG_LINEAR);   /* RANGEFOGENABLE */
 d.st.rs[48] = 0; d.st.rs[140] = 1; assert(run(&d, 0, 0, FFOG_DEPTH, 110, 0.01f) == FOG_EXP);
 d.st.rs[140] = 2; assert(run(&d, 0, 0, FFOG_DEPTH, 110, 0.01f) == FOG_EXP2);
 d.st.rs[35] = 3; assert(run(&d, 1, 2, FFOG_SHADER_DEPTH, 110, 0.01f) == FOG_LINEAR); /* table + vs */
 assert(run(&d, 0, 0, FFOG_ORTHO, 110, 0.01f) == FOG_LINEAR);
 d.st.transforms[3][11] = 1.0f; d.st.transforms[3][15] = 0.0f;         /* perspective: eye depth */
 assert(run(&d, 0, 0, FFOG_DEPTH, 110, 0.01f) == FOG_LINEAR);
 d.st.decl = &post; assert(run(&d, 0, 0, FFOG_TRANSFORMED, 110, 0.01f) == FOG_LINEAR);
 d.st.rs[35] = 1; assert(run(&d, 0, 0, FFOG_TRANSFORMED, 110, 0.01f) == FOG_EXP);
 d.st.rs[35] = 2; assert(run(&d, 0, 0, FFOG_TRANSFORMED, 110, 0.01f) == FOG_EXP2);
 d.st.rs[37] = u(10); assert(run(&d, 0, 0, FFOG_TRANSFORMED, 0, 0) == FOG_EXP2);  /* start == end */
 { uint32_t coord; float p[4], c[4]; d3d_fog_state(&d, 0, 0, &coord, p, c);
   assert(fabsf(p[2] - 0.5f) < 1e-7f && fabsf(c[0] - 0.2f) < 1e-6f && fabsf(c[1] - 0.4f) < 1e-6f && fabsf(c[2] - 0.6f) < 1e-6f); }
 port = 0; assert(run(&d, 1, 1, 0, 0, 0) == FOG_OFF);                  /* port_fog off */
 puts("PASS D3D9 fog rules: enable, SM3, vs oFog, specular, depth/range, ortho, transformed, EXP/EXP2, start==end, port switch");
 return 0;
}
'''
    compile_probe("fog_state", harness, {"enums.h": enums.replace("#define FOG_OUTPUT (11u << 8 | 1u)\n", ""),
                                         "state.h": block})


def adapter_probe(sources):
    """fog_source / fog_depth_source / alpha_test_source over real GLSL, results to files."""
    OUT.mkdir(parents=True, exist_ok=True)
    adapters = SHADER[SHADER.index("static char *insert_before("):SHADER.index("static char *fix_pixel_varyings(")]
    adapters += SHADER[SHADER.index("/* Direct3D 9 fog: after a pre-3.0 pixel shader"):SHADER.index("static int alpha_test_mode(")]
    adapters += function(SHADER, "static char *alpha_test_source(")
    paths = []
    for index, source in enumerate(sources):
        path = OUT / f"in_{index:02d}.glsl"
        path.write_bytes(source)
        paths.append(path.as_posix())
    harness = r'''
#define _CRT_NONSTDC_NO_DEPRECATE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "adapters.h"
static char *load(const char *path) {
 FILE *f = fopen(path, "rb"); if (!f) exit(2); fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
 char *s = malloc((size_t)n + 1); if (fread(s, 1, (size_t)n, f) != (size_t)n) exit(3); s[n] = 0; fclose(f); return s;
}
static void store(const char *path, const char *s) { FILE *f = fopen(path, "wb"); if (!f) exit(4); fputs(s, f); fclose(f); }
static size_t count(const char *s, const char *what) { size_t n = 0; for (const char *p = strstr(s, what); p; p = strstr(p + 1, what)) ++n; return n; }
static const char *inputs[] = { INPUTS };
int main(void) {
 for (size_t i = 0; i < sizeof inputs / sizeof *inputs; ++i) {
  char *src = load(inputs[i]), path[1024];
  char *same = fog_source(src, 0); if (strcmp(same, src)) return 10; free(same);
  for (int mode = 1; mode <= 3; ++mode) {
   char *fog = fog_source(src, mode);
   if (count(fog, "void_fog();") != count(src, "void_alpha_test();") || !count(fog, "void_fog();")) return 11;
   if (count(fog, "in highp vec4 io_11_1;") != 1) return 12;
   char *opaque = alpha_test_source(fog, 0), *cut = alpha_test_source(fog, 7);
   if (count(opaque, "void_alpha_test();") || count(opaque, "void_fog();") != count(fog, "void_fog();")) return 13;
   if (count(cut, "void_fog(); void_alpha_test();") + count(cut, "\tvoid_fog(); void_alpha_test();") == 0) return 14;
   snprintf(path, sizeof path, "%s.fog%d", inputs[i], mode); store(path, fog);
   snprintf(path, sizeof path, "%s.fog%d.opaque", inputs[i], mode); store(path, opaque);
   snprintf(path, sizeof path, "%s.fog%d.cut", inputs[i], mode); store(path, cut);
   free(fog); free(opaque); free(cut);
  }
  free(src);
 }
 puts("PASS fog adapter on every pixel shader: one call per alpha test, alpha variants keep fog");
 return 0;
}
'''.replace("INPUTS", ", ".join(json.dumps(p) for p in paths))
    compile_probe("fog_adapters", harness, {"adapters.h": "#define FOURCC(a,b,c,d) 0\n" + adapters})
    return paths


def vertex_probe(source):
    """fog_depth_source on one vertex shader."""
    adapters = SHADER[SHADER.index("static char *insert_before("):SHADER.index("static char *fix_pixel_varyings(")]
    adapters += SHADER[SHADER.index("/* Direct3D 9 fog: after a pre-3.0 pixel shader"):SHADER.index("static int alpha_test_mode(")]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "vertex.glsl").write_bytes(source)
    harness = r'''
#define _CRT_NONSTDC_NO_DEPRECATE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "adapters.h"
int main(void) {
 FILE *f = fopen(IN, "rb"); static char src[1 << 20]; size_t n = fread(src, 1, sizeof src - 1, f); src[n] = 0; fclose(f);
 char *out = fog_depth_source(src); f = fopen(OUTPUT, "wb"); fputs(out, f); fclose(f);
 puts("PASS fog depth variant written"); return 0;
}
'''.replace("IN", json.dumps((OUT / "vertex.glsl").as_posix())).replace("OUTPUT", json.dumps((OUT / "vertex.depth.glsl").as_posix()))
    compile_probe("fog_vertex", harness, {"adapters.h": "#define FOURCC(a,b,c,d) 0\n" + adapters})
    return (OUT / "vertex.depth.glsl").read_bytes()


def fixed_function_probe():
    """Generated FF halves with fog: transformed specular-alpha coordinate, eye depth, pixel blend."""
    types = FF[FF.index("enum { IN_POS"):FF.index("typedef struct ff_vs")]
    append = FF[FF.index("#define APPEND"):FF.index("/* ------------------------------------------------------------ helpers */")]
    out = ROOT / "build/tests/fog_ff"
    out.mkdir(parents=True, exist_ok=True)
    names = {key: (out / f"{key}.glsl").as_posix() for key in ("post_vs", "depth_vs", "linear_ps", "exp2_ps", "unwritten_ps")}
    harness = """
#define _CRT_NONSTDC_NO_DEPRECATE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "d3d9_filter.h"
typedef uint32_t GLuint;
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
static const char *target;
static GLuint compile_ff(GLuint type, const char *source) {
 (void)type; FILE *f = fopen(target, "wb"); if (!f) abort(); fwrite(source, 1, strlen(source), f); fclose(f); return 1;
}
""" + "".join(f"static const char *{k} = {json.dumps(v)};\n" for k, v in names.items())
    harness += types + append + "".join(function(FF, name) for name in
        ("static GLuint vertex_shader(", "static void arg_expr(", "static void op_expr(", "static GLuint pixel_shader("))
    harness += """
int main(void) {
 ff_vkey v = {0}; v.inputs = IN_POST | IN_DIFFUSE | IN_SPECULAR; v.bgra = 3;
 v.output_count = 3; v.outputs[0] = 10 << 8; v.outputs[1] = (10 << 8) | 1; v.outputs[2] = FOG_OUTPUT;
 v.fog_coord = FFOG_SPECULAR; target = post_vs; vertex_shader(&v);
 ff_vkey w = {0}; w.inputs = IN_POS | IN_DIFFUSE; w.output_count = 2; w.outputs[0] = 10 << 8; w.outputs[1] = FOG_OUTPUT;
 w.fog_coord = FFOG_DEPTH; target = depth_vs; vertex_shader(&w);
 ff_fkey f = {0}; f.available = 3 | FOG_AVAILABLE; f.fog = FOG_LINEAR; f.stage_count = 1;
 f.stages[0][0] = 3; f.stages[0][1] = 2; f.stages[0][2] = 0; f.stages[0][3] = 3; f.stages[0][4] = 2; f.stages[0][5] = 0;
 target = linear_ps; pixel_shader(&f);
 f.fog = FOG_EXP2; target = exp2_ps; pixel_shader(&f);
 f.fog = FOG_LINEAR; f.available = 3; target = unwritten_ps; pixel_shader(&f);
 puts("PASS fog FF halves generated"); return 0;
}
"""
    compile_probe("fog_ff", harness, {name: (ROOT / "android/host" / name).read_text()
                                      for name in ("d3d9_filter.h", "fsr1.h")})
    return {key: (out / f"{key}.glsl").read_bytes() for key in names}


def gles():
    angle = shaders.Angle()
    shaders.Angle.api(angle.gl, "glUniform4f", None, C.c_int, C.c_float, C.c_float, C.c_float, C.c_float)
    return angle


class FogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous = shaders.OUT
        try:
            shaders.OUT = ROOT / "build/tests/fog_mojo"
            cls.lib = shaders.build_mojo()
        finally:
            shaders.OUT = previous
        cls.pixel = [(address, shaders.translate_host(cls.lib, code, pixel=True)[0])
                     for address, code in shaders.embedded_shaders()]
        cls.vertex = [(address, shaders.translate_host(cls.lib, code, pixel=False)[0])
                      for address, code in shaders.embedded_shaders(vertex=True)]

    def test_rules_follow_d3d9(self):
        fog_state_probe()

    def test_engine_vertex_shaders_write_ofog_as_io_11_1(self):
        fogged = [address for address, source in self.vertex if b"#define vs_oFog io_11_1.x" in source]
        self.assertGreaterEqual(len(fogged), 30)

    def test_every_pixel_shader_compiles_with_each_formula(self):
        paths = adapter_probe([source for _, source in self.pixel])
        angle = gles()
        for (address, _), path in zip(self.pixel, paths):
            for mode in (1, 2, 3):
                for suffix in ("", ".opaque", ".cut"):
                    with self.subTest(address=f"{address:08X}", mode=mode, variant=suffix):
                        source = Path(f"{path}.fog{mode}{suffix}").read_bytes()
                        angle.gl.glDeleteShader(angle.compile(source))

    def draw(self, angle, vertex, fragment, uniforms=(), samplers=()):
        gl = angle.gl
        vs, ps = angle.compile(vertex, 0x8B31), angle.compile(fragment)
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, ps)
        gl.glLinkProgram(program)
        status = C.c_int()
        gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        if not status.value:
            log = C.create_string_buffer(4096)
            gl.glGetProgramInfoLog(program, 4096, None, log)
            self.fail(log.value.decode())
        gl.glUseProgram(program)
        for name, values in uniforms:
            location = gl.glGetUniformLocation(program, name)
            if isinstance(values, int):
                gl.glUniform1i(location, values)
            else:
                gl.glUniform4f(location, *(float(v) for v in values))
        for stage, colour in samplers:
            texture = C.c_uint()
            gl.glGenTextures(1, C.byref(texture))
            gl.glActiveTexture(0x84C0 + stage)
            gl.glBindTexture(0x0DE1, texture)
            for key, value in ((0x2801, 0x2600), (0x2800, 0x2600)):
                gl.glTexParameteri(0x0DE1, key, value)
            gl.glTexImage2D(0x0DE1, 0, 0x8058, 1, 1, 0, 0x1908, 0x1401, bytes((*colour, 255)))
        gl.glDrawArrays(4, 0, 3)
        pixel = (C.c_ubyte * 4)()
        gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, pixel)
        self.assertEqual(gl.glGetError(), 0)
        gl.glDeleteProgram(program)
        gl.glDeleteShader(vs)
        gl.glDeleteShader(ps)
        return tuple(pixel)

    @staticmethod
    def constant_vertex(names, values):
        source = b"#version 310 es\nprecision highp float;\n" + b"".join(b"out highp vec4 " + n + b";\n" for n in names)
        source += b"void main() { vec2 p[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3)); gl_Position = vec4(p[gl_VertexID],0,1);\n"
        for name in names:
            v = values.get(name.decode(), (0, 0, 0, 1))
            source += name + b" = vec4(" + ",".join(repr(float(x)) for x in v).encode() + b");\n"
        return source + b"}\n"

    def test_pixels_blend_toward_the_fog_colour(self):
        # PS 0x00F61820 (mov r0, c0): c0 = (0.2, 0.6, 1.0, 1); fog colour red.
        paths = adapter_probe([source for _, source in self.pixel])
        angle = gles()
        target = next(i for i, (address, _) in enumerate(self.pixel) if address == 0x00F61820)
        fragment = {mode: Path(f"{paths[target]}.fog{mode}.opaque").read_bytes() for mode in (1, 2, 3)}
        names = re.findall(rb"in highp vec4 (io_\d+_\d+);", fragment[1])
        self.assertIn(b"io_11_1", names)
        uniforms = [(b"vpFogColor", (1, 0, 0, 1)), (b"ps_uniforms_vec4[0]", (0.2, 0.6, 1.0, 1.0))]
        def pixel(mode, coordinate, params):
            return self.draw(angle, self.constant_vertex(names, dict(io_11_1=(coordinate, 0, 0, 0))), fragment[mode],
                             uniforms + [(b"vpFogParams", params), (b"vpAlphaFunc", 8)])
        # Vertex shader oFog: LINEAR with end 0, scale -1 -> f = oFog.
        for f in (1.0, 0.25, 0.0):
            expected = tuple(round(255 * (f * c + (1 - f) * r)) for c, r in zip((0.2, 0.6, 1.0), (1, 0, 0)))
            got = pixel(1, f, (0, -1, 0, 0))
            for a, b in zip(got[:3], expected):
                self.assertLessEqual(abs(a - b), 1, (f, got, expected))
            self.assertEqual(got[3], 255)                                # alpha is never fogged
        self.assertEqual(pixel(1, 2.0, (0, -1, 0, 0))[:3], (51, 153, 255))   # clamped: no fog above 1
        # EXP and EXP2 with density 2 at c = 0.5: f = e^-1 for both.
        f = math.exp(-1.0)
        expected = tuple(round(255 * (f * c + (1 - f) * r)) for c, r in zip((0.2, 0.6, 1.0), (1, 0, 0)))
        for mode in (2, 3):
            got = pixel(mode, 0.5, (0, 0, 2, 0))
            for a, b in zip(got[:3], expected):
                self.assertLessEqual(abs(a - b), 1, (mode, got, expected))

    def test_unwritten_ofog_is_fully_fogged(self):
        # D3D9 (Wine) reads an oFog the vertex shader never writes as 0: the production
        # varying reconciliation turns the fog input into that constant.
        reconcile = function(SHADER, "static char *insert_before(") + function(SHADER, "static void reconcile_varyings(")
        paths = adapter_probe([source for _, source in self.pixel])
        source = Path(f"{paths[0]}.fog1.opaque").read_bytes()
        self.assertIn(b"in highp vec4 io_11_1;", source)
        harness = r'''
#define _CRT_NONSTDC_NO_DEPRECATE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "reconcile.h"
int main(void) {
 const char *vs = "out highp vec4 io_10_0;\nvoid main()\n{\n\tgl_Position.y = gl_Position.y * vpFlip;\n}\n";
 const char *ps = "in highp vec4 io_11_1;\nin highp vec4 io_10_0;\nvoid main() {}\n";
 char *v, *p; reconcile_varyings(vs, ps, &v, &p);
 if (v || !p || !strstr(p, "const highp vec4 io_11_1 = vec4(0.0);") || !strstr(p, "in highp vec4 io_10_0;")) return 1;
 puts("PASS unwritten oFog reads 0"); return 0;
}
'''
        compile_probe("fog_reconcile", harness, {"reconcile.h": reconcile})

    def test_vertex_shader_depth_variant_writes_clip_z(self):
        address, source = next((a, s) for a, s in self.vertex if b"#define vs_oFog io_11_1.x" in s)
        patched = vertex_probe(source)
        self.assertEqual(patched.count(b"io_11_1 = vec4(gl_Position.z);"), 1)
        self.assertLess(patched.index(b"io_11_1 = vec4(gl_Position.z);"), patched.index(b"gl_Position.y = gl_Position.y * vpFlip;"))
        self.assertEqual(patched.count(b"out highp vec4 io_11_1;"), 1)
        angle = gles()
        angle.gl.glDeleteShader(angle.compile(patched, 0x8B31))
        plain = next(s for a, s in self.vertex if b"io_11_1" not in s)
        patched = vertex_probe(plain)
        self.assertEqual(patched.count(b"out highp vec4 io_11_1;"), 1)
        angle.gl.glDeleteShader(angle.compile(patched, 0x8B31))

    def test_fixed_function_halves(self):
        generated = fixed_function_probe()
        self.assertIn(b"io_11_1 = vec4(ff_a_specular.bgra.a);", generated["post_vs"])
        self.assertIn(b"float ff_fog = abs(ec_pos.z);", generated["depth_vs"])
        self.assertIn(b"io_11_1 = vec4(ff_fog);", generated["depth_vs"])
        self.assertIn(b"mix(vpFogColor.rgb, current.rgb, clamp((vpFogParams.x - io_11_1.x) * vpFogParams.y, 0.0, 1.0))",
                      generated["linear_ps"])
        self.assertIn(b"exp(-(vpFogParams.z * io_11_1.x) * (vpFogParams.z * io_11_1.x))", generated["exp2_ps"])
        self.assertIn(b"clamp((vpFogParams.x - 0.0) * vpFogParams.y, 0.0, 1.0)", generated["unwritten_ps"])
        angle = gles()
        for key in ("post_vs", "depth_vs"):
            angle.gl.glDeleteShader(angle.compile(generated[key], 0x8B31))
        # Pre-transformed quad with specular alpha 0.25 -> f = 0.25 (start 1, end 0), diffuse white, fog blue.
        vertex = generated["post_vs"]
        names = [b"io_10_0", b"io_10_1", b"io_11_1"]
        fragment = generated["linear_ps"]
        constant = self.constant_vertex(names, dict(io_10_0=(1, 1, 1, 1), io_10_1=(0, 0, 0, 0.25), io_11_1=(0.25, 0, 0, 0)))
        got = self.draw(angle, constant, fragment, [(b"vpFogColor", (0, 0, 1, 1)), (b"vpFogParams", (0, -1, 0, 0)),
                                                    (b"vpAlphaFunc", 8), (b"vpUiFilter", -1)])
        self.assertEqual(got[:3], (64, 64, 255))
        self.assertIn(b"layout(location = 3) in vec4 ff_a_specular;", vertex)


if __name__ == "__main__":
    unittest.main()
