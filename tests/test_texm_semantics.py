"""Direct3D 9 semantics of the SM1 texture-matrix opcodes in the vendored MojoShader.

The adventure-map water (PS 0x00F63A08: texm3x2pad/texm3x2tex with t0_bx2) and the
texm3x3vspec reflection (PS 0x00F63868) are rendered from the licensed local EXE with
local ANGLE. Every edition switches the semantics on (android/host/shader_semantics.c):
1.6 and 2.1 embed both shaders and the water's vertex shader byte for byte. Without the
switch MojoShader's former output must stay byte for byte.
"""
import ctypes as C
import hashlib
import re
import sys
import unittest

import test_legacy_shaders as shaders
from test_legacy_shaders import ROOT

sys.path.insert(0, str(ROOT / "tools"))
from editions import generated_root
from port_patches import legacy_ui_branch

WATER = 0x00F63A08
VSPEC = 0x00F63868
WATER_VS = 0x00F55DC8
# The same shaders in the legacy EXEs: water PS, vspec PS, water VS.
LEGACY = {"vanilla": (0x00F4D078, 0x00F4CED8, 0x00F3F430), "hof": (0x00F14C48, 0x00F14AA8, 0x00F07008)}


def legacy_exe(edition):
    return generated_root(edition) / "input/H5_Game.exe"


def texm_opcodes(code):
    """The SM1 texture-matrix opcodes (texm3x2pad 0x47 .. texm3x3vspec 0x4D) of a ps_1_x token stream."""
    import struct
    found, p = set(), 4
    while p + 4 <= len(code):
        token = struct.unpack_from("<I", code, p)[0]
        if token == 0xFFFF:
            break
        if token & 0xFFFF == 0xFFFE:                      # comment
            p += 4 * (1 + ((token >> 16) & 0x7FFF))
            continue
        opcode = token & 0xFFFF
        if 0x47 <= opcode <= 0x4D:
            found.add(opcode)
        p += 4
        while p + 4 <= len(code) and struct.unpack_from("<I", code, p)[0] & 0x80000000:
            p += 4                                         # parameter tokens
        if opcode == 0x51:                                 # def: four raw values
            p += 16
    return found
RED, GREEN, BLUE, YELLOW, WHITE, CYAN = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
                                         (255, 255, 255), (0, 255, 255))


class TexmSemanticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = shaders.build_mojo()
        cls.code = {address: code for address, code in shaders.embedded_shaders() if address in (WATER, VSPEC)}

    def tearDown(self):
        self.lib.probe_set_texm(0)

    def translate(self, address, semantics):
        self.lib.probe_set_texm(semantics)
        return shaders.translate_host(self.lib, self.code[address], pixel=True)[0]

    def test_former_output_is_kept_without_the_switch(self):
        water, vspec = self.translate(WATER, 0), self.translate(VSPEC, 0)
        self.assertIn(b"vec2(dot(ps_t0.xyz, ps_t1.xyz), dot(ps_t0.xyz, ps_t2.xyz))", water)
        self.assertIn(b"return (2.0 * ((normal * eyeray) / (normal * normal)) * normal) - eyeray;", vspec)
        self.assertIn(b"vec3(dot(ps_t1.xyz, ps_t0.xyz), dot(ps_t2.xyz, ps_t0.xyz), dot(ps_t3.xyz, ps_t0.xyz))", vspec)

    def test_switch_applies_bx2_and_the_reflection(self):
        water, vspec = self.translate(WATER, 1), self.translate(VSPEC, 1)
        bx2 = b"((ps_t0.xyz - 0.5) * 2.0)"
        self.assertIn(b"vec2(dot(%s, ps_t1.xyz), dot(%s, ps_t2.xyz))" % (bx2, bx2), water)
        self.assertIn(b"return (2.0 * (dot(normal, eyeray) / dot(normal, normal)) * normal) - eyeray;", vspec)
        self.assertEqual(vspec.count(bx2), 3)

    def test_all_embedded_pixel_shaders_compile_with_the_switch(self):
        angle = shaders.Angle()
        self.lib.probe_set_texm(1)
        for edition, path in (("toe", None), ("vanilla", legacy_exe("vanilla")), ("hof", legacy_exe("hof"))):
            count = 0
            for address, code in shaders.embedded_shaders(path=path):
                with self.subTest(edition=edition, address=f"{address:08X}"):
                    source = shaders.translate_host(self.lib, code, pixel=True)[0]
                    angle.gl.glDeleteShader(angle.compile(source))
                    count += 1
            self.assertGreaterEqual(count, 55, edition)

    def test_legacy_exes_embed_the_same_water_shaders(self):
        def digest(code):
            return hashlib.sha256(code).hexdigest()
        toe_vs = {address: digest(code) for address, code in shaders.embedded_shaders(vertex=True)}
        for edition, (water, vspec, water_vs) in LEGACY.items():
            with self.subTest(edition=edition):
                pixel = {address: digest(code) for address, code in shaders.embedded_shaders(path=legacy_exe(edition))}
                vertex = {address: digest(code) for address, code in
                          shaders.embedded_shaders(vertex=True, path=legacy_exe(edition))}
                self.assertEqual(pixel[water], digest(self.code[WATER]))
                self.assertEqual(pixel[vspec], digest(self.code[VSPEC]))
                self.assertEqual(vertex[water_vs], toe_vs[WATER_VS])
                # No other texm shader: only these two take the new semantics.
                texm = [address for address, code in shaders.embedded_shaders(path=legacy_exe(edition))
                        if texm_opcodes(code)]
                self.assertEqual(sorted(texm), sorted((water, vspec)))
        self.assertEqual(sorted(address for address, code in shaders.embedded_shaders() if texm_opcodes(code)),
                         sorted((WATER, VSPEC)))

    def render(self, angle, source, coordinates, textures):
        """One pixel of `source` with constant varyings and NEAREST/CLAMP textures."""
        names = re.findall(rb"in highp vec4 (io_\d+_\d+);", source)
        vertex = b"#version 310 es\nprecision highp float;\n" + b"".join(b"out highp vec4 " + n + b";\n" for n in names)
        vertex += b"void main() { vec2 p[3] = vec2[3](vec2(-1,-1), vec2(3,-1), vec2(-1,3)); gl_Position = vec4(p[gl_VertexID],0,1);\n"
        for name in names:
            values = coordinates.get(name.decode(), (0, 0, 0, 1))
            vertex += name + b" = vec4(" + ",".join(repr(float(v)) for v in values).encode() + b");\n"
        vertex += b"}\n"
        gl = angle.gl
        vs, ps = angle.compile(vertex, 0x8B31), angle.compile(source)
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, ps)
        gl.glLinkProgram(program)
        status = C.c_int()
        gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        self.assertTrue(status.value)
        gl.glUseProgram(program)
        for stage, (target, images) in textures.items():
            texture = C.c_uint()
            gl.glGenTextures(1, C.byref(texture))
            gl.glActiveTexture(0x84C0 + stage)
            gl.glBindTexture(target, texture)
            for key, value in ((0x2801, 0x2600), (0x2800, 0x2600), (0x2802, 0x812F), (0x2803, 0x812F)):
                gl.glTexParameteri(target, key, value)
            for face, (width, pixels) in enumerate(images):
                image_target = target if target == 0x0DE1 else 0x8515 + face
                data = bytes(c for rgb in pixels for c in (*rgb, 255))
                gl.glTexImage2D(image_target, 0, 0x8058, width, 1, 0, 0x1908, 0x1401, data)
            gl.glUniform1i(gl.glGetUniformLocation(program, b"ps_s%d" % stage), stage)
        gl.glDrawArrays(4, 0, 3)
        pixel = (C.c_ubyte * 4)()
        gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, pixel)
        self.assertEqual(gl.glGetError(), 0)
        gl.glDeleteProgram(program)
        gl.glDeleteShader(vs)
        gl.glDeleteShader(ps)
        return tuple(pixel)[:3]

    def test_water_reads_the_screen_texture_where_the_normal_points(self):
        # VS 0x00F55DC8 rows at screen (0.49, 0.25): (0.1 sx, 0, sx) and (0, 0.1 sy, sy).
        # A flat normal map texel reads u = 0.49, the left (red) half; the dropped _bx2
        # scaled it to 0.515, the right (green) half.
        angle = shaders.Angle()
        coordinates = {"io_5_0": (0.5, 0.5, 0, 1), "io_5_1": (0.049, 0, 0.49, 1),
                       "io_5_2": (0, 0.025, 0.25, 1), "io_5_3": (0.5, 0.5, 0, 1),
                       "io_10_0": (0, 0, 0, 1), "io_10_1": (0, 0, 0, 1)}
        textures = {0: (0x0DE1, [(1, [(128, 128, 255)])]), 2: (0x0DE1, [(2, [RED, GREEN])]),
                    3: (0x0DE1, [(1, [(0, 0, 0)])])}
        self.assertEqual(self.render(angle, self.translate(WATER, 1), coordinates, textures), RED)
        self.assertEqual(self.render(angle, self.translate(WATER, 0), coordinates, textures), GREEN)

    def test_vspec_reflects_the_eye_ray_about_the_normal(self):
        # Identity rows, flat normal (0, 0, 1), eye (1, 0, 0.3): R = (-1, 0, 0.3) reads -X;
        # the component-wise helper returned the eye ray itself (+X).
        angle = shaders.Angle()
        coordinates = {"io_5_0": (0.5, 0.5, 0, 1), "io_5_1": (1, 0, 0, 1), "io_5_2": (0, 1, 0, 0),
                       "io_5_3": (0, 0, 1, 0.3), "io_10_0": (0, 0, 0, 1)}
        cube = [(1, [colour]) for colour in (RED, GREEN, BLUE, YELLOW, WHITE, CYAN)]
        textures = {0: (0x0DE1, [(1, [(128, 128, 255)])]), 3: (0x8513, cube)}
        self.assertEqual(self.render(angle, self.translate(VSPEC, 1), coordinates, textures), GREEN)
        self.assertEqual(self.render(angle, self.translate(VSPEC, 0), coordinates, textures), RED)

    def test_engine_switch_is_on_in_every_edition(self):
        text = (ROOT / "android/host/shader_semantics.c").read_text(encoding="utf-8")
        for legacy in (True, False):
            branch = legacy_ui_branch(text.encode(), legacy).decode()
            body = branch[branch.index("int void_mojoshader_texm_semantics(void)"):]
            self.assertIn("return 1;", body)
            self.assertNotIn("return 0;", body)


if __name__ == "__main__":
    unittest.main()
