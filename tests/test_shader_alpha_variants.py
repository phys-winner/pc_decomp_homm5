"""Specialize only the port's alpha-test injection; keep game TEXKILL intact."""
import ctypes as C
import math
import unittest

import test_legacy_shaders as shaders
from test_d3d_lifecycle import function
from test_shadow_filter import fixed_function_sources
from test_static_tls import ROOT, compile_probe


def compare(alpha, func, reference):
    return (False, alpha < reference, alpha == reference, alpha <= reference,
            alpha > reference, alpha != reference, alpha >= reference, True)[func - 1]


class ShaderAlphaVariantsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = shaders.build_mojo()

    def opaque(self, source):
        return self.variant(source, 0)

    def variant(self, source, mode):
        pointer = self.lib.probe_alpha_variant(source, mode)
        try:
            return C.string_at(pointer)
        finally:
            self.lib.probe_free(pointer)

    def test_effective_test_matches_all_unsigned_alpha_values_and_references(self):
        state = (C.c_uint32 * 256)()
        for enabled in (0, 1):
            state[15] = enabled
            for func in range(1, 9):
                state[25] = func
                for reference in range(256):
                    state[24] = 0xABCDEF00 | reference
                    required = enabled and not all(compare(a, func, reference) for a in range(256))
                    self.assertEqual(self.lib.probe_alpha_mode(state), func if required else 0,
                                     (enabled, func, reference))
        for invalid in (0, 9, 255, 0xFFFFFFFF):
            state[15], state[25] = 1, invalid
            self.assertEqual(self.lib.probe_alpha_mode(state), 9)

    def test_original_texkill_remains_and_real_mixed_programs_link(self):
        code = shaders.assemble(self.lib, "ps_1_1\ntexkill t0\nmov r0,c0\n")
        source = shaders.translate_host(self.lib, code, pixel=True)[0]
        opaque = self.opaque(source)
        self.assertNotIn(b"void_alpha_test", opaque)
        self.assertNotIn(b"vpAlphaFunc", opaque)
        self.assertEqual(opaque.count(b"discard;"), 1)
        self.assertEqual(source.count(b"discard;"), 2)
        self.assertEqual(self.variant(source, 7).count(b"discard;"), 2)
        self.assertIn(b"bool pass = a >= vpAlphaRef;", self.variant(source, 7))
        self.assertNotIn(b"vpAlphaFunc", self.variant(source, 7))
        self.assertEqual(self.variant(source, 9), source)
        untouched = b"void main() { if (true) discard; }\n"
        self.assertEqual(self.opaque(untouched), untouched)
        ff_vertex, _ = fixed_function_sources()
        real_vertex = next(shaders.translate_host(self.lib, c, pixel=False)[0]
                           for address, c in shaders.embedded_shaders(vertex=True) if address == 0xF4F808)
        real_pixel = next(shaders.translate_host(self.lib, c, pixel=True)[0]
                          for address, c in shaders.embedded_shaders() if address == 0xF5E4D0)
        angle = shaders.Angle()
        for vertex in (real_vertex, ff_vertex):
            for pixel in (self.variant(real_pixel, mode) for mode in (0, 2, 4, 7, 9)):
                vs, ps = angle.compile(vertex, 0x8B31), angle.compile(pixel)
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

    def test_finite_alpha_pixels_and_original_texkill(self):
        angle = shaders.Angle()
        for name, result, args in (("glUniform4fv", None, [C.c_int, C.c_int, C.POINTER(C.c_float)]),
                                   ("glUniform1f", None, [C.c_int, C.c_float]),
                                   ("glClearColor", None, [C.c_float] * 4),
                                   ("glClear", None, [C.c_uint])):
            angle.api(angle.gl, name, result, *args)
        vertex = b"""#version 310 es
precision highp float;
uniform vec4 probeKill;
out highp vec4 io_5_0;
void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
gl_Position=vec4(p[gl_VertexID],0,1);io_5_0=probeKill;}
"""
        state = (C.c_uint32 * 256)()
        programs = {}
        for kill in (False, True):
            assembly = "ps_1_1\n" + ("texkill t0\n" if kill else "") + "mov r0,c0\n"
            source = shaders.translate_host(self.lib, shaders.assemble(self.lib, assembly), pixel=True)[0]
            for mode in (0, 1, 2, 3, 4, 5, 6, 7, 9):
                pixel = self.variant(source, mode)
                vs, ps = angle.compile(vertex, 0x8B31), angle.compile(pixel)
                program = angle.gl.glCreateProgram()
                angle.gl.glAttachShader(program, vs)
                angle.gl.glAttachShader(program, ps)
                angle.gl.glLinkProgram(program)
                status = C.c_int()
                angle.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
                self.assertTrue(status.value)
                angle.gl.glDeleteShader(vs)
                angle.gl.glDeleteShader(ps)
                programs[kill, mode] = program
                if mode != 9:
                    self.assertEqual(angle.gl.glGetUniformLocation(program, b"vpAlphaFunc"), -1)
                if 2 <= mode <= 7:
                    self.assertGreaterEqual(angle.gl.glGetUniformLocation(program, b"vpAlphaRef"), 0)
        def draw(program, alpha, func, reference, kill):
            angle.gl.glUseProgram(program)
            angle.gl.glUniform4fv(angle.gl.glGetUniformLocation(program, b"ps_uniforms_vec4"), 1,
                                 (C.c_float * 4)(1, 0, 0, alpha))
            angle.gl.glUniform4fv(angle.gl.glGetUniformLocation(program, b"probeKill"), 1,
                                 (C.c_float * 4)(-1 if kill else 1, 1, 1, 1))
            angle.gl.glUniform1i(angle.gl.glGetUniformLocation(program, b"vpAlphaFunc"), func)
            angle.gl.glUniform1f(angle.gl.glGetUniformLocation(program, b"vpAlphaRef"), reference)
            angle.gl.glClearColor(0, 1, 0, 1)
            angle.gl.glClear(0x4000)
            angle.gl.glDrawArrays(4, 0, 3)
            pixel = (C.c_ubyte * 4)()
            angle.gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, pixel)
            self.assertEqual(angle.gl.glGetError(), 0)
            return tuple(pixel)
        # NaN outputs have no claimed equivalence; cover finite saturated and unsaturated alpha.
        for alpha in (-2, 0, 1 / 255, .49 / 255, .5, 119 / 255, 120 / 255, 150 / 255, 180 / 255, 254 / 255, 1, 3):
            quantized = math.floor(min(max(alpha, 0), 1) * 255 + .5)
            for func in range(1, 9):
                for reference in (0, 120, 180, 255):
                    state[15], state[24], state[25] = 1, reference, func
                    original = draw(programs[False, 9], alpha, func, reference, False)
                    expected = (255, 0, 0) if compare(quantized, func, reference) else (0, 255, 0)
                    self.assertEqual(original[:3], expected, (alpha, func, reference))
                    mode = self.lib.probe_alpha_mode(state)
                    self.assertEqual(original, draw(programs[False, mode], alpha, func, reference, False))
        for func, reference in ((8, 120), (7, 0), (4, 255)):
            for kill in (False, True):
                self.assertEqual(draw(programs[True, 9], .5, func, reference, kill),
                                 draw(programs[True, 0], .5, func, reference, kill))
                self.assertEqual(draw(programs[True, 0], .5, func, reference, kill)[:3],
                                 (0, 255, 0) if kill else (255, 0, 0))
        self.assertEqual(draw(programs[False, 7], 150 / 255, 7, 120, False)[:3], (255, 0, 0))
        self.assertEqual(draw(programs[False, 7], 150 / 255, 7, 180, False)[:3], (0, 255, 0))
        for program in programs.values():
            angle.gl.glDeleteProgram(program)

    def test_production_cache_modes_reference_upload_and_unchanged_ff_pixel_path(self):
        text = (ROOT / "android/host/d3d9_shader.c").read_text()
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
typedef unsigned GLuint;
typedef int GLint;
typedef struct { int usage, index; } attribute;
typedef struct { int attribute_count; attribute *attributes; } parse_data;
typedef struct { parse_data *parse; const char *source; } d3d_shader;
typedef struct { struct { uint32_t rs[256]; } st; } d3d_device;
typedef struct { int type,index,count; } umap_t;
#include "program.h"
static program_t *programs[1024], *current_program;
static uint32_t d3d_constant_generation=1;
static unsigned links, binds, uniforms;
static int shader_type_ok(d3d_shader *s, int p) { (void)s; (void)p; return 1; }
static GLuint d3d_ff_vertex_stage(d3d_device *d, const char *s, uint32_t *id) { (void)d; (void)s; *id=21; return 21; }
static GLuint d3d_ff_pixel_stage(d3d_device *d, const char *s, uint32_t *id, uint32_t *mask) { (void)d; (void)s; *id=22; *mask=0; return 22; }
static void d3d_ff_uniforms(d3d_device *d, GLuint gl, int v, int p) { (void)d; (void)gl; (void)v; (void)p; ++uniforms; }
static void glUseProgram(GLuint gl) { assert(gl); ++binds; }
static int bgra_of(d3d_device *d, int u, int i) { (void)d; (void)u; (void)i; return 0; }
static program_t *link_program(d3d_shader *vs, d3d_shader *ps, uint32_t mask, GLuint ff, uint32_t id, uint32_t samplers, int alpha) {
 (void)ff; (void)samplers; program_t *p=calloc(1,sizeof *p); assert(p); p->vs=vs;p->ps=ps;
 p->bgra_mask=mask;p->ff_id=id;p->alpha_mode=alpha;p->gl=++links;return p;
}
#include "gate.h"
#include "bind.h"
static unsigned function_uploads, reference_uploads;
static float uploaded_reference;
static void glUniform1i(GLint loc, int value) { assert(loc==24&&value==7);++function_uploads; }
static void glUniform1f(GLint loc, float value) { assert(loc==23);++reference_uploads;uploaded_reference=value; }
static void glUniform2f(GLint loc, float x, float y) { (void)loc;(void)x;(void)y;abort(); }
static volatile int unexpected_constants;
#define pack(...) ((void)dev, assert(unexpected_constants))
#define upload_vec4(...) assert(unexpected_constants)
#define upload_ints(...) assert(unexpected_constants)
#define void_fatal(...) abort()
#include "upload.h"
static program_t *bind(d3d_device *d, d3d_shader *v, d3d_shader *p) {
 int n; const int *u,*i,*pt,*vt; uint32_t ps,vs;
 assert(d3d_shader_bind2(d,v,p,bgra_of,&n,&u,&i,&ps,&vs,&pt,&vt)); return current_program;
}
static int bucket(program_t *p) {
 for(int i=0;i<1024;++i) for(program_t *q=programs[i];q;q=q->next) if(q==p)return i;
 abort();
}
int main(void) {
 parse_data parsed={0};d3d_shader v={&parsed,"v"},p={&parsed,"p"};d3d_device d={0};
 program_t *opaque=bind(&d,&v,&p);assert(!opaque->alpha_mode&&links==1);
 d.st.rs[15]=1;d.st.rs[25]=7;d.st.rs[24]=0;assert(bind(&d,&v,&p)==opaque&&links==1);
 d.st.rs[24]=120;program_t *cutout=bind(&d,&v,&p);assert(cutout->alpha_mode==7&&cutout!=opaque&&links==2);
 assert(bucket(cutout)!=bucket(opaque));
 d.st.rs[25]=4;program_t *lequal=bind(&d,&v,&p);assert(lequal->alpha_mode==4&&links==3);
 d.st.rs[25]=2;program_t *less=bind(&d,&v,&p);assert(less->alpha_mode==2&&links==4);
 assert(bucket(cutout)!=bucket(lequal)&&bucket(lequal)!=bucket(less));
 d.st.rs[25]=4;d.st.rs[24]=180;assert(bind(&d,&v,&p)==lequal&&links==4);
 d.st.rs[25]=7;assert(bind(&d,&v,&p)==cutout&&links==4);
 d.st.rs[25]=4;d.st.rs[24]=255;assert(bind(&d,&v,&p)==opaque);
 d.st.rs[25]=8;d.st.rs[24]=120;assert(bind(&d,&v,&p)==opaque);
 d.st.rs[25]=9;program_t *generic=bind(&d,&v,&p);assert(generic->alpha_mode==9&&links==5);
 d.st.rs[25]=0;assert(bind(&d,&v,&p)==generic&&links==5);
 d.st.rs[25]=7;d.st.rs[24]=120;assert(bind(&d,&v,&p)==cutout&&links==5);
 cutout->uploaded_generation=1;cutout->loc_half=-1;cutout->loc_alpha_func=-1;cutout->loc_alpha_ref=23;
 d3d_shader_upload(&d,0,0,7,120);assert(!function_uploads&&reference_uploads==1&&uploaded_reference==120);
 d3d_shader_upload(&d,0,0,7,180);assert(!function_uploads&&reference_uploads==2&&uploaded_reference==180);
 d3d_shader_upload(&d,0,0,7,180);assert(reference_uploads==2);
 cutout->loc_alpha_func=24;cutout->last_alpha_func=-1;
 d3d_shader_upload(&d,0,0,7,180);assert(function_uploads==1&&reference_uploads==2);
 d.st.rs[15]=0;program_t *mixed=bind(&d,NULL,&p);assert(!mixed->alpha_mode&&links==6);
 d.st.rs[15]=1;assert(bind(&d,NULL,&p)->alpha_mode==7&&links==7);
 program_t *ff=bind(&d,&v,NULL);assert(ff->alpha_mode==9&&links==8);
 d.st.rs[15]=0;assert(bind(&d,&v,NULL)==ff&&links==8);
 for(int i=0;i<1024;++i)while(programs[i]){program_t *q=programs[i];programs[i]=q->next;free(q);}
 puts("PASS alpha modes 7-4-2 cache reuse, dynamic ref120-180 upload without function uniform, generic invalid and unchanged FF pixels");
 return 0;
}
'''
        program = text[text.index("typedef struct program {"):text.index("static program_t *programs[")]
        compile_probe("shader_alpha_cache", harness, {"gate.h": function(text, "static int alpha_test_mode("),
                      "bind.h": function(text, "int d3d_shader_bind2("), "program.h": program,
                      "upload.h": function(text, "void d3d_shader_upload(")})


if __name__ == "__main__":
    unittest.main()
