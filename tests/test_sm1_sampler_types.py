"""SM1 dimensionality follows bound textures, including H5's ghost reflection shader."""
import ctypes as C
import unittest

import test_legacy_shaders as shaders


class Sm1SamplerTypesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = shaders.build_mojo()

    def source(self, code, types):
        pointer = self.lib.probe_typed_pixel(code, len(code), types)
        self.assertTrue(pointer)
        try:
            return C.string_at(pointer)
        finally:
            self.lib.probe_free(pointer)

    def test_real_ghost_reflection_and_legacy_versions_compile(self):
        angle = shaders.Angle()
        code = next(code for address, code in shaders.embedded_shaders() if address == 0xF60C70)
        plain, typed = self.source(code, 0), self.source(code, 1 << 8)
        self.assertIn(b"uniform sampler2D ps_s4;", plain)
        self.assertIn(b"uniform samplerCube ps_s4;", typed)
        self.assertIn(b"textureCube(ps_s4, ps_t4.xyz)", typed)
        self.assertIn(b"void_alpha_test();", typed)
        angle.gl.glDeleteShader(angle.compile(typed))
        for assembly in ("ps_1_1\ntex t0\nmov r0,t0\n", "ps_1_4\ntexld r0,t0\n"):
            code = shaders.assemble(self.lib, assembly)
            for kind, declaration in enumerate((b"sampler2D", b"samplerCube", b"sampler3D")):
                with self.subTest(assembly=assembly, kind=kind):
                    source = self.source(code, kind)
                    self.assertIn(b"uniform " + declaration + b" ps_s0;", source)
                    angle.gl.glDeleteShader(angle.compile(source))

    def test_pixels_cube_faces_volume_slices_and_alpha(self):
        angle = shaders.Angle()
        angle.api(angle.gl, "glUniform4fv", None, C.c_int, C.c_int, C.POINTER(C.c_float))
        angle.api(angle.gl, "glDeleteTextures", None, C.c_int, C.POINTER(C.c_uint))
        angle.api(angle.gl, "glTexImage3D", None, C.c_uint, C.c_int, C.c_int,
                  C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_void_p)
        vertex = b'''#version 310 es
precision highp float;
uniform vec4 point;
out highp vec4 io_5_4;
void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));
gl_Position=vec4(p[gl_VertexID],0,1);io_5_4=point;}
'''
        code = shaders.assemble(self.lib, "ps_1_4\ntexld r4,t4\nmov r0,r4\n")
        faces = [(40 + i * 30, 170 - i * 20, 60 + i * 10, 23 + i * 37) for i in range(6)]
        directions = [(1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)]
        for kind, target in enumerate((0x0DE1, 0x8513, 0x806F)):
            program = angle.gl.glCreateProgram()
            vs = angle.compile(vertex, 0x8B31)
            ps = angle.compile(self.source(code, kind << 8))
            angle.gl.glAttachShader(program, vs)
            angle.gl.glAttachShader(program, ps)
            angle.gl.glLinkProgram(program)
            status = C.c_int()
            angle.gl.glGetProgramiv(program, 0x8B82, C.byref(status))
            self.assertTrue(status.value)
            angle.gl.glUseProgram(program)
            texture = C.c_uint()
            angle.gl.glGenTextures(1, C.byref(texture))
            angle.gl.glActiveTexture(0x84C0 + 4)
            angle.gl.glBindTexture(target, texture.value)
            for key, value in ((0x2801,0x2600),(0x2800,0x2600),(0x2802,0x812F),(0x2803,0x812F)):
                angle.gl.glTexParameteri(target, key, value)
            if kind == 1:
                for face, color in enumerate(faces):
                    angle.gl.glTexImage2D(0x8515 + face, 0, 0x8058, 1, 1, 0, 0x1908, 0x1401, bytes(color))
                cases = zip(directions, faces)
            elif kind == 2:
                angle.gl.glTexImage3D(target, 0, 0x8058, 1, 1, 2, 0, 0x1908, 0x1401, bytes(faces[0] + faces[1]))
                cases = [((.5,.5,.25),faces[0]),((.5,.5,.75),faces[1])]
            else:
                angle.gl.glTexImage2D(target, 0, 0x8058, 1, 1, 0, 0x1908, 0x1401, bytes(faces[0]))
                cases = [((.5,.5,0),faces[0])]
            angle.gl.glUniform1i(angle.gl.glGetUniformLocation(program, b"ps_s4"), 4)
            angle.gl.glUniform1i(angle.gl.glGetUniformLocation(program, b"vpUiFilter"), -1)
            for point, expected in cases:
                angle.gl.glUniform4fv(angle.gl.glGetUniformLocation(program, b"point"), 1, (C.c_float * 4)(*point, 1))
                angle.gl.glDrawArrays(4, 0, 3)
                actual = (C.c_ubyte * 4)()
                angle.gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, actual)
                self.assertEqual(angle.gl.glGetError(), 0)
                self.assertEqual(tuple(actual), expected, (kind, point))
            angle.gl.glDeleteTextures(1, C.byref(texture))
            angle.gl.glDeleteProgram(program)
            angle.gl.glDeleteShader(vs)
            angle.gl.glDeleteShader(ps)


if __name__ == "__main__":
    unittest.main()
