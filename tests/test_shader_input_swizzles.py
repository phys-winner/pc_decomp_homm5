"""Actual Heroes world/UI shader pairs with D3DCOLOR BGRA and packed SHORT2 UVs."""
import ctypes as C
import re
import struct
import unittest

from test_legacy_shaders import (Angle, OUT, assemble, build_mojo, embedded_shaders,
                                 result, translate_host)


class Swizzle(C.Structure):
    _fields_ = [("usage", C.c_int), ("index", C.c_uint), ("swizzles", C.c_ubyte * 4)]


def variant(lib, code, semantics):
    swizzles = (Swizzle * len(semantics))(*(Swizzle(u, i, (C.c_ubyte * 4)(2, 1, 0, 3)) for u, i in semantics))
    source, _ = result(lib, lib.MOJOSHADER_parse(b"glsles3", b"main", code, len(code),
                                               swizzles, len(swizzles), None, 0, None, None, None))
    pointer = lib.probe_patch(source, 0)
    try:
        return C.string_at(pointer)
    finally:
        lib.probe_free(pointer)


class ShaderInputSwizzlesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = build_mojo()
        cls.vertex = dict(embedded_shaders(True))
        cls.pixel = dict(embedded_shaders(False))

    def test_declared_semantics_and_legacy_fallback(self):
        declared = assemble(self.lib, "vs_1_1\ndcl_position v0\ndcl_normal v1\ndcl_texcoord v3\n"
                            "mov oPos,v0\nmov oD0,v1\nmov oT0.xy,v3\n")
        source = variant(self.lib, declared, [(3, 0)])
        self.assertIn(b"vs_oD0 = vs_v1.zyxw;", source)
        self.assertIn(b"vs_oT0.xy = vs_v3.xy;", source)
        self.assertNotIn(b"vs_v3.zy", source)
        legacy = assemble(self.lib, "vs_1_1\nmov oPos,v0\nmov oD0,v3\nmov oT0.xy,v7\n")
        source = variant(self.lib, legacy, [(3, 0)])
        self.assertIn(b"vs_oD0 = vs_v3.zyxw;", source)
        self.assertIn(b"vs_oT0.xy = vs_v7.xy;", source)

    def test_actual_world_and_ui_packed_vertex_pixels(self):
        angle = Angle()
        gl = angle.gl
        for name, ret, args in [
            ("glBindAttribLocation", None, [C.c_uint, C.c_uint, C.c_char_p]),
            ("glGenBuffers", None, [C.c_int, C.POINTER(C.c_uint)]),
            ("glBindBuffer", None, [C.c_uint, C.c_uint]),
            ("glBufferData", None, [C.c_uint, C.c_ssize_t, C.c_void_p, C.c_uint]),
            ("glEnableVertexAttribArray", None, [C.c_uint]),
            ("glDisableVertexAttribArray", None, [C.c_uint]),
            ("glVertexAttribPointer", None, [C.c_uint, C.c_int, C.c_uint, C.c_ubyte, C.c_int, C.c_void_p]),
            ("glUniform4fv", None, [C.c_int, C.c_int, C.POINTER(C.c_float)]),
            ("glUniform1f", None, [C.c_int, C.c_float]),
            ("glUniform2f", None, [C.c_int, C.c_float, C.c_float])]:
            angle.api(gl, name, ret, *args)
        cases = [("world", 0xF4F808, 0xF5E8C8, 2048),
                 ("ui", 0xF4BBC0, 0xF61EE0, 4096)]
        for label, vs_va, ps_va, scale in cases:
            with self.subTest(stage=label):
                vs_source = variant(self.lib, self.vertex[vs_va], [(3, 0), (6, 0), (6, 1)])
                ps_source, _, _ = translate_host(self.lib, self.pixel[ps_va], True)
                (OUT / f"{label}-bgra.vert").write_bytes(vs_source)
                shaders = [angle.compile(vs_source, 0x8B31), angle.compile(ps_source)]
                program = gl.glCreateProgram()
                for shader in shaders:
                    gl.glAttachShader(program, shader)
                for slot, reg in enumerate((0, 1, 3, 4, 5, 6)):
                    gl.glBindAttribLocation(program, slot, f"vs_v{reg}".encode())
                gl.glLinkProgram(program)
                status = C.c_int()
                gl.glGetProgramiv(program, 0x8B82, C.byref(status))
                self.assertTrue(status.value)
                gl.glUseProgram(program)
                constants = {1: (1, 1, 1, 1), 3: (2, -1, 0, 0),
                             10: (1, 0, 0, 0), 11: (0, 1, 0, 0), 12: (0, 0, 0, 0), 13: (0, 0, 0, 1),
                             16: (1 / scale, 1 / scale, 0, 0), 29: (1, 1, 1, 1), 30: (0, 1, 0, 0),
                             38: (1 / scale, 0, 0, 1 / scale)}
                mapping = [(int(reg), int(slot)) for reg, slot in re.findall(rb"#define vs_c(\d+) vs_uniforms_vec4\[(\d+)\]", vs_source)]
                count = max(slot for _, slot in mapping) + 1
                packed = (C.c_float * (4 * count))()
                for reg, slot in mapping:
                    packed[4 * slot:4 * slot + 4] = constants.get(reg, (0, 0, 0, 0))
                gl.glUniform4fv(gl.glGetUniformLocation(program, b"vs_uniforms_vec4"), count, packed)
                gl.glUniform1f(gl.glGetUniformLocation(program, b"vpFlip"), -1)
                gl.glUniform2f(gl.glGetUniformLocation(program, b"vpHalfPixel"), 0, 0)
                gl.glUniform1i(gl.glGetUniformLocation(program, b"vpAlphaFunc"), 8)
                # The game's exact 32-byte declaration: FLOAT3 position,
                # D3DCOLOR normal, SHORT2 UV0/UV1, D3DCOLOR tangent0/tangent1.
                color = bytes([64, 64, 64, 255]) if label == "world" else bytes([255] * 4)
                vertices = b"".join(struct.pack("<3f", *pos) + bytes([32, 128, 255, 255]) +
                                    struct.pack("<4h", *uv, 0, 0) + color + color
                                    for pos, uv in [((-1, 1, 0), (0, 0)), ((3, 1, 0), (2 * scale, 0)),
                                                    ((-1, -3, 0), (0, 2 * scale))])
                buffer = C.c_uint()
                gl.glGenBuffers(1, C.byref(buffer))
                gl.glBindBuffer(0x8892, buffer)
                gl.glBufferData(0x8892, len(vertices), vertices, 0x88E4)
                for slot in range(16):
                    gl.glDisableVertexAttribArray(slot)
                for slot, size, kind, norm, offset in [(0, 3, 0x1406, 0, 0), (1, 4, 0x1401, 1, 12),
                                                      (2, 2, 0x1402, 0, 16), (3, 4, 0x1401, 1, 24),
                                                      (4, 4, 0x1401, 1, 28), (5, 2, 0x1402, 0, 20)]:
                    gl.glVertexAttribPointer(slot, size, kind, norm, 32, C.c_void_p(offset))
                    gl.glEnableVertexAttribArray(slot)
                texture = C.c_uint()
                gl.glGenTextures(1, C.byref(texture))
                gl.glActiveTexture(0x84C0)
                gl.glBindTexture(0x0DE1, texture)
                for key, value in [(0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)]:
                    gl.glTexParameteri(0x0DE1, key, value)
                colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 255, 255)]
                pixels = bytes(value for color in colors for value in color)
                gl.glTexImage2D(0x0DE1, 0, 0x8058, 2, 2, 0, 0x1908, 0x1401, pixels)
                gl.glUniform1i(gl.glGetUniformLocation(program, b"ps_s0"), 0)
                gl.glDrawArrays(4, 0, 3)
                rendered = (C.c_ubyte * 256)()
                gl.glReadPixels(0, 0, 8, 8, 0x1908, 0x1401, rendered)
                self.assertEqual(gl.glGetError(), 0)
                for y in range(8):
                    for x in range(8):
                        expected = colors[(y >= 4) * 2 + (x >= 4)]
                        actual = tuple(rendered[4 * (y * 8 + x):4 * (y * 8 + x) + 4])
                        self.assertEqual(actual, expected, (label, x, y, actual, expected))
                gl.glDeleteProgram(program)
                for shader in shaders:
                    gl.glDeleteShader(shader)
        print("PASS actual world/UI BGRA variants: 128 checker pixels from packed SHORT2 vertices")


if __name__ == "__main__":
    unittest.main()
