"""Render the actual H5 RGBA8 shadow comparison through its production adapter."""
import ctypes as C
import json
import random
import re
import unittest

import test_legacy_shaders as shaders
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function

SHADOW_FAMILY = {0xF5E4D0, 0xF5EBF8, 0xF5EE58, 0xF5F450, 0xF5F6E0, 0xF5F9D0,
                 0xF5FEB0, 0xF60508, 0xF60788, 0xF60A48, 0xF61128}


def fixed_function_sources():
    text = (ROOT / "android/host/d3d9_ff.c").read_text()
    types = text[text.index("enum { IN_POS"):text.index("typedef struct ff_vs")]
    append = text[text.index("#define APPEND"):text.index("/* ------------------------------------------------------------ helpers */")]
    out = ROOT / "build/tests/shadow_ff"
    out.mkdir(parents=True, exist_ok=True)
    harness = """
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t GLuint;
#define GL_VERTEX_SHADER 0x8B31
#define GL_FRAGMENT_SHADER 0x8B30
static GLuint compile_ff(GLuint type, const char *source) {
 const char *path = type == GL_VERTEX_SHADER ? %s : %s;
 FILE *f = fopen(path, "wb"); if (!f) abort(); fwrite(source, 1, strlen(source), f); fclose(f); return 1;
}
""" % (json.dumps((out / "ff.vert").as_posix()), json.dumps((out / "ff.frag").as_posix()))
    harness += types + append + "".join(function(text, name) for name in
        ("static GLuint vertex_shader(", "static void arg_expr(", "static void op_expr(", "static GLuint pixel_shader("))
    harness += """
int main(void) {
 ff_vkey v = {0}; v.inputs = IN_POS | IN_NORMAL | IN_DIFFUSE | IN_SPECULAR;
 v.lighting = 1; v.lights = 8; v.diffuse_from_vertex = 1;
 v.output_count = 5; v.outputs[0] = 10 << 8; v.outputs[1] = (10 << 8) | 1;
 for (uint32_t i = 0; i < 3; ++i) {
  v.outputs[i + 2] = (5 << 8) | i; v.tex_dims[i] = 4; v.tc_set[i] = i; v.tc_flags[i] = 4;
 }
 v.tc_mode[1] = TCI_REFLECTION; v.tc_mode[2] = TCI_SPHEREMAP; vertex_shader(&v);
 ff_fkey f = {0}; f.available = 31; f.specular = 1; f.stage_count = 3;
 for (uint32_t i = 0; i < 3; ++i) {
  f.sampler[i] = i; f.stages[i][0] = 4; f.stages[i][1] = 2; f.stages[i][2] = 1;
  f.stages[i][3] = 4; f.stages[i][4] = 2; f.stages[i][5] = 1;
 }
 f.project[0] = 4; pixel_shader(&f); return 0;
}
"""
    compile_probe("shadow_ff", harness, {})
    return (out / "ff.vert").read_bytes(), (out / "ff.frag").read_bytes()


class ShadowFilterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        previous = shaders.OUT
        try:
            shaders.OUT = ROOT / "build/tests/shadow_filter"
            cls.lib = shaders.build_mojo()
        finally:
            shaders.OUT = previous
        cls.pixel_code = next(code for address, code in shaders.embedded_shaders() if address == 0x00F5E4D0)
        cls.fragment = shaders.translate_host(cls.lib, cls.pixel_code, pixel=True)[0]

    def render(self, u, v=.25, alphas=(51, 204, 204, 51), dimensions=(2, 2), fragment=None,
               reference=.5, bias=.484375, angle=None):
        angle = angle or shaders.Angle()
        vertex = ("""#version 310 es
precision highp float;
out highp vec4 io_10_0;out highp vec4 io_10_1;
out highp vec4 io_5_0;out highp vec4 io_5_1;out highp vec4 io_5_2;
void main(){
 vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
 gl_Position=vec4(p[gl_VertexID],0,1);
 io_10_0=vec4(.25,.25,.25,1);io_10_1=vec4(0);
 io_5_0=vec4(.5,.5,0,1);io_5_1=vec4(%s,%s,0,1);io_5_2=vec4(0,0,%s,1);
}
""" % (float(u), float(v), float(reference))).encode()
        vs, ps = angle.compile(vertex, 0x8B31), angle.compile(fragment or self.fragment)
        program = angle.gl.glCreateProgram()
        angle.gl.glAttachShader(program, vs)
        angle.gl.glAttachShader(program, ps)
        angle.gl.glLinkProgram(program)
        status = C.c_int()
        angle.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        self.assertTrue(status.value)
        angle.gl.glUseProgram(program)
        textures = (C.c_uint * 2)()
        angle.gl.glGenTextures(2, textures)
        for slot, size in ((0, (1, 1)), (1, dimensions)):
            angle.gl.glActiveTexture(0x84C0 + slot)
            angle.gl.glBindTexture(0x0DE1, textures[slot])
            for key, value in ((0x2801, 0x2601), (0x2800, 0x2601), (0x2802, 0x812F), (0x2803, 0x812F)):
                angle.gl.glTexParameteri(0x0DE1, key, value)
            pixels = bytes([255] * 4) if not slot else bytes(c for alpha in alphas for c in (255, 255, 255, alpha))
            angle.gl.glTexImage2D(0x0DE1, 0, 0x8058, *size, 0, 0x1908, 0x1401, pixels)
            angle.gl.glUniform1i(angle.gl.glGetUniformLocation(program, f"ps_s{slot}".encode()), slot)
        angle.api(angle.gl, "glUniform4fv", None, C.c_int, C.c_int, C.POINTER(C.c_float))
        angle.gl.glUniform4fv(angle.gl.glGetUniformLocation(program, b"ps_uniforms_vec4"), 1,
                            (C.c_float * 4)(0, 0, 0, bias))
        angle.gl.glDrawArrays(4, 0, 3)
        pixel = (C.c_ubyte * 4)()
        angle.gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, pixel)
        self.assertEqual(angle.gl.glGetError(), 0)
        angle.gl.glDeleteProgram(program)
        angle.gl.glDeleteShader(vs)
        angle.gl.glDeleteShader(ps)
        angle.api(angle.gl, "glDeleteTextures", None, C.c_int, C.POINTER(C.c_uint))
        angle.gl.glDeleteTextures(2, textures)
        return tuple(pixel)

    def test_gather_matches_four_sample_oracle_at_edges_and_fraction_ties(self):
        self.assertTrue(self.fragment.startswith(b"#version 310 es\n"))
        gather = b"vec4 depths = textureGather(ps_s1, uv, 3).wzxy;"
        self.assertEqual(self.fragment.count(gather), 1)
        # Keep the original atlas RGB/cloud read, separate from gathered depth.
        self.assertIn(b"ps_t1 = texture2D(ps_s1, ps_t1.xy);", self.fragment)
        reference = self.fragment.replace(gather, b"""vec2 lo = (floor(p) + 0.5) / size, stepUV = 1.0 / size;
 vec4 depths = vec4(textureLod(ps_s1, lo, 0.0).a,
  textureLod(ps_s1, lo + vec2(stepUV.x, 0), 0.0).a,
  textureLod(ps_s1, lo + vec2(0, stepUV.y), 0.0).a, textureLod(ps_s1, lo + stepUV, 0.0).a);""")
        angle, rng = shaders.Angle(), random.Random(97281)
        for width, height in ((1, 1), (1, 7), (7, 1), (2, 2), (3, 5), (4, 8), (16, 9), (1024, 1024)):
            alphas = tuple(rng.choice((0, 51, 127, 128, 129, 204, 255)) for _ in range(width * height))
            points = [(-.25, -.25), (0, 0), (1, 1), (1.25, 1.25), (-.25, 1.25), (1.25, -.25),
                      (.5 / width, .5 / height), (1 / width, 1 / height),
                      (1.5 / width, 1.5 / height), (2 / width, 2 / height),
                      (rng.random(), rng.random()), (rng.random(), rng.random())]
            for i, (u, v) in enumerate(points):
                with self.subTest(size=(width, height), uv=(u, v)):
                    depth, bias = (.5, .484375) if i % 3 else (rng.random(), rng.choice((0, .2, .5, 1)))
                    args = dict(alphas=alphas, dimensions=(width, height), reference=depth, bias=bias, angle=angle)
                    self.assertEqual(self.render(u, v, **args), self.render(u, v, fragment=reference, **args))

    def test_fixed_function_and_real_shader_mixed_stages_link_at_production_version(self):
        ff_vertex, ff_pixel = fixed_function_sources()
        for source in (ff_vertex, ff_pixel):
            self.assertTrue(source.startswith(b"#version 310 es\n"))
        for kind in (b"sampler2D", b"samplerCube", b"sampler3D"):
            self.assertIn(b"precision highp " + kind + b";", ff_pixel)
        vertex = next(shaders.translate_host(self.lib, code, pixel=False)[0]
                      for address, code in shaders.embedded_shaders(vertex=True) if address == 0xF4F808)
        angle = shaders.Angle()
        for v, p in ((vertex, self.fragment), (ff_vertex, self.fragment), (vertex, ff_pixel), (ff_vertex, ff_pixel)):
            vs, ps = angle.compile(v, 0x8B31), angle.compile(p)
            program = angle.gl.glCreateProgram()
            angle.gl.glAttachShader(program, vs)
            angle.gl.glAttachShader(program, ps)
            angle.gl.glLinkProgram(program)
            status = C.c_int()
            angle.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
            if not status.value:
                log = C.create_string_buffer(32768)
                angle.gl.glGetProgramInfoLog(program, len(log), None, log)
                self.fail(log.value.decode())
            angle.gl.glDeleteProgram(program)
            angle.gl.glDeleteShader(vs)
            angle.gl.glDeleteShader(ps)

    def test_rgba_atlas_edges_filter_comparisons_without_changing_bias(self):
        self.assertIn(b"vpShadowCoverage", self.fragment)
        for u, expected in ((.25, 0), (.375, 64), (.5, 128), (.625, 191), (.75, 255)):
            pixel = self.render(u)
            self.assertTrue(all(abs(value - expected) <= 1 for value in pixel[:3]), (u, pixel))
            self.assertEqual(pixel[3], 255)
        self.assertEqual(self.render(.5, .5, (128,) * 4), (0, 0, 0, 255))
        self.assertEqual(self.render(.5, .5, (129,) * 4), (255,) * 4)
        self.assertEqual(self.render(0, .25), (0, 0, 0, 255))

    def test_verified_family_only_and_real_h5_vertex_interface(self):
        patched = set()
        for address, code in shaders.embedded_shaders():
            source, _, _ = shaders.translate_host(self.lib, code, pixel=True)
            if b"vpShadowCoverage" in source:
                patched.add(address)
        self.assertEqual(patched, SHADOW_FAMILY)
        inputs = set(re.findall(rb"in highp vec4 (io_\d+_\d+);", self.fragment))
        vertex = None
        for address, code in shaders.embedded_shaders(vertex=True):
            if address == 0x00F4F808:
                vertex = shaders.translate_host(self.lib, code, pixel=False)[0]
                break
        self.assertIsNotNone(vertex)
        self.assertTrue(inputs <= set(re.findall(rb"out highp vec4 (io_\d+_\d+);", vertex)))
        angle = shaders.Angle()
        vs, ps = angle.compile(vertex, 0x8B31), angle.compile(self.fragment)
        program = angle.gl.glCreateProgram()
        angle.gl.glAttachShader(program, vs)
        angle.gl.glAttachShader(program, ps)
        angle.gl.glLinkProgram(program)
        status = C.c_int()
        angle.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        self.assertTrue(status.value)
        angle.gl.glDeleteProgram(program)
        angle.gl.glDeleteShader(vs)
        angle.gl.glDeleteShader(ps)

    def test_original_16_and_21_shadow_bytecode_family_and_real_pixels(self):
        original = {address: code for address, code in shaders.embedded_shaders() if address in SHADOW_FAMILY}
        vertex_code = next(code for address, code in shaders.embedded_shaders(vertex=True) if address == 0xF4F808)
        for edition in ('vanilla', 'hof'):
            image = ROOT / 'generated' / edition / 'input/H5_Game.exe'
            pixels = list(shaders.embedded_shaders(path=image))
            vertices = list(shaders.embedded_shaders(vertex=True, path=image))
            with self.subTest(edition=edition):
                # Compare complete token streams, including comments/CTAB, rather
                # than treating an equal hash or an address as shader coverage.
                for old_address, bytecode in original.items():
                    self.assertTrue(any(code == bytecode for _, code in pixels), hex(old_address))
                actual_vertex_code = next(code for _, code in vertices if code == vertex_code)
                vertex = shaders.translate_host(self.lib, actual_vertex_code, pixel=False)[0]
                angle = shaders.Angle()
                covered = []
                for address, code in pixels:
                    source = shaders.translate_host(self.lib, code, pixel=True)[0]
                    if b'vpShadowCoverage' in source:
                        covered.append(address)
                        shader = angle.compile(source)
                        angle.gl.glDeleteShader(shader)
                self.assertEqual(len(covered), 11)
                actual_pixel_code = next(code for _, code in pixels if code == self.pixel_code)
                fragment = shaders.translate_host(self.lib, actual_pixel_code, pixel=True)[0]
                self.assertEqual(fragment, self.fragment)
                vs, ps = angle.compile(vertex, 0x8B31), angle.compile(fragment)
                program = angle.gl.glCreateProgram()
                angle.gl.glAttachShader(program, vs)
                angle.gl.glAttachShader(program, ps)
                angle.gl.glLinkProgram(program)
                status = C.c_int()
                angle.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
                self.assertTrue(status.value)
                angle.gl.glDeleteProgram(program)
                angle.gl.glDeleteShader(vs)
                angle.gl.glDeleteShader(ps)
                for u in (0, .375, .5, .625, 1):
                    self.assertEqual(self.render(u, fragment=fragment, angle=angle),
                                     self.render(u, fragment=self.fragment, angle=angle))


if __name__ == "__main__":
    unittest.main()
