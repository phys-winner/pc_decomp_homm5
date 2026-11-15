"""Engine graphics options the GLES bridge implements: gamma ramp, swap chain MSAA, smooth transition.

Production code of android/host/d3d9_gl.c is extracted by anchor and executed;
the gamma present shader is rendered with local ANGLE.
"""
import ctypes as C
import math
import re
import unittest

import test_legacy_shaders as shaders
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function

GL = (ROOT / "android/host/d3d9_gl.c").read_text(encoding="utf-8")
DEVICE = (ROOT / "android/host/d3d9_device.c").read_text(encoding="utf-8")


def engine_ramp(gamma):
    """0x00A40440: x^(1/gamma) * 65535 at x = i / 256, truncated."""
    return [int((i / 256.0) ** (1.0 / gamma) * 65535.0) for i in range(256)]


class GfxEffectsTest(unittest.TestCase):
    def test_gamma_ramp_lut(self):
        ramps = {"identity": [i * 257 for i in range(256)], "engine10": engine_ramp(1.0),
                 "engine20": engine_ramp(2.0), "engine05": engine_ramp(0.5)}
        rows = "\n".join("static const unsigned short ramp_%s[256] = {%s};" % (name, ",".join(map(str, values)))
                         for name, values in ramps.items())
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static void void_log(const char *f, ...) { (void)f; }
static uint8_t gamma_lut_data[256 * 4];
static int gamma_identity = 1, gamma_dirty;
#include "gamma.h"
RAMPS
static void run(const unsigned short *r) { static uint16_t full[768];
 for (int c = 0; c < 3; ++c) memcpy(full + 256 * c, r, 512); run_set_gamma(full); }
int main(void) {
 run(ramp_identity); assert(gamma_identity && gamma_dirty);
 for (int i = 0; i < 256; ++i) assert(gamma_lut_data[4 * i] == i && gamma_lut_data[4 * i + 3] == 255);
 run(ramp_engine10); assert(gamma_identity);          /* the game's gamma 1.0: no present pass */
 run(ramp_engine20); assert(!gamma_identity);         /* brighter: x^(1/2), 0.25 -> 32767/65535 */
 assert(gamma_lut_data[4 * 64] == 127 && gamma_lut_data[4 * 255] == 254 && gamma_lut_data[0] == 0);
 run(ramp_engine05); assert(!gamma_identity && gamma_lut_data[4 * 128] == 64);
 run(ramp_identity); assert(gamma_identity);
 puts("PASS gamma ramp: identity and the game's gamma 1.0 keep the blit; 0.5/2.0 build the LUT");
 return 0;
}
'''.replace("RAMPS", rows)
        compile_probe("gfx_gamma", harness, {"gamma.h": function(GL, "static void run_set_gamma(")})

    def test_gamma_present_shader(self):
        body = function(GL, "static int gamma_ready(")
        vertex = re.search(r'const char \*vertex = (.*?);\n', body, re.S).group(1)
        fragment = re.search(r'const char \*fragment = (.*?);\n', body, re.S).group(1)
        unquote = lambda text: "".join(bytes(s, "utf-8").decode("unicode_escape") for s in re.findall(r'"((?:[^"\\]|\\.)*)"', text))
        angle = shaders.Angle()
        gl = angle.gl
        vs, fs = angle.compile(unquote(vertex).encode(), 0x8B31), angle.compile(unquote(fragment).encode())
        program = gl.glCreateProgram()
        gl.glAttachShader(program, vs)
        gl.glAttachShader(program, fs)
        gl.glLinkProgram(program)
        status = C.c_int()
        gl.glGetProgramiv(program, 0x8B82, C.byref(status))
        self.assertTrue(status.value)
        gl.glUseProgram(program)
        # The image: one colour; the LUT: v -> 255 - v (red), v / 2 (green), v (blue).
        textures = (C.c_uint * 2)()
        gl.glGenTextures(2, textures)
        gl.glActiveTexture(0x84C0 + 1)
        gl.glBindTexture(0x0DE1, textures[0])
        for key in (0x2801, 0x2800):
            gl.glTexParameteri(0x0DE1, key, 0x2600)
        gl.glTexImage2D(0x0DE1, 0, 0x8058, 1, 1, 0, 0x1908, 0x1401, bytes((200, 100, 30, 255)))
        gl.glActiveTexture(0x84C0 + 2)
        gl.glBindTexture(0x0DE1, textures[1])
        for key in (0x2801, 0x2800):
            gl.glTexParameteri(0x0DE1, key, 0x2600)
        lut = bytes(c for i in range(256) for c in (255 - i, i // 2, i, 255))
        gl.glTexImage2D(0x0DE1, 0, 0x8058, 256, 1, 0, 0x1908, 0x1401, lut)
        gl.glUniform1i(gl.glGetUniformLocation(program, b"image"), 1)
        gl.glUniform1i(gl.glGetUniformLocation(program, b"lut"), 2)
        gl.glDrawArrays(4, 0, 3)
        pixel = (C.c_ubyte * 4)()
        gl.glReadPixels(4, 4, 1, 1, 0x1908, 0x1401, pixel)
        self.assertEqual(gl.glGetError(), 0)
        self.assertEqual(tuple(pixel), (55, 50, 30, 255))

    def test_multisample_levels_follow_the_game_option(self):
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
static uint32_t d3d_gl_msaa_counts;
#include "msaa.h"
/* 0x00A3F980: quality = min(levels, gfx_fsaa) - 1 for gfx_fsaa 2 and 4. */
static int option(int fsaa) { uint32_t q = d3d_gl_msaa_levels(); if (q >= (uint32_t)fsaa) q = (uint32_t)fsaa; return d3d_gl_msaa_count(1, q ? q - 1 : 0); }
int main(void) {
 assert(d3d_gl_msaa_levels() == 0 && d3d_gl_msaa_count(1, 0) == 0 && d3d_gl_msaa_count(4, 0) == 0);
 d3d_gl_msaa_counts = 1u << 2;
 assert(d3d_gl_msaa_levels() == 2 && option(2) == 2 && option(4) == 2);
 assert(d3d_gl_msaa_count(1, 2) == 0 && d3d_gl_msaa_count(2, 0) == 2 && d3d_gl_msaa_count(4, 0) == 0);
 d3d_gl_msaa_counts = 1u << 2 | 1u << 4;
 assert(d3d_gl_msaa_levels() == 4 && option(2) == 2 && option(4) == 4);
 assert(d3d_gl_msaa_count(1, 0) == 2 && d3d_gl_msaa_count(1, 4) == 0 && d3d_gl_msaa_count(4, 0) == 4);
 assert(d3d_gl_msaa_count(0, 0) == 0 && d3d_gl_msaa_count(8, 0) == 0);
 puts("PASS swap chain MSAA: NONMASKABLE levels 2/4, game options 2 and 4 draw 2x and 4x");
 return 0;
}
'''
        compile_probe("gfx_msaa", harness, {"msaa.h": function(GL, "uint32_t d3d_gl_msaa_levels(") +
                                                      function(GL, "int d3d_gl_msaa_count(")})
        # The capability answers what the swap chain can draw.
        check = function(DEVICE, "COM_METHOD(d3d9, CheckDeviceMultiSampleType")
        self.assertIn("d3d_gl_msaa_levels()", check)
        self.assertIn("d3d_gl_msaa_count(dev->pp[4], dev->pp[5])", DEVICE)

    def test_transition_capture_mip_level(self):
        harness = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef int GLint;
#include "level.h"
int main(void) {
 assert(aa_level_for(2400, 1080, 256, 256) == 2);   /* 600x270: still >= 256x256 */
 assert(aa_level_for(1024, 768, 256, 256) == 1);    /* 512x384 */
 assert(aa_level_for(606, 270, 256, 256) == 0);     /* 25% render scale: less than 2x tall */
 assert(aa_level_for(512, 512, 256, 256) == 1 && aa_level_for(511, 512, 256, 256) == 0);
 assert(aa_level_for(4096, 4096, 1, 1) == 12 && aa_level_for(100, 100, 0, 0) == 0);
 puts("PASS transition capture: box-filtered level for 2x-or-more downscales only");
 return 0;
}
'''
        compile_probe("gfx_capture", harness, {"level.h": function(GL, "static GLint aa_level_for(")})
        # Off (the default) leaves every draw and blit unchanged.
        self.assertIn("int smooth = g_d3d_device && src == g_d3d_device->backbuffer && void_port_battle_blur();", GL)
        self.assertIn("render_rt_smooth = render_ui && render_blur", GL)
        self.assertIn("return render_xt_blur ? 4 : render_rt_smooth ? 2 : render_filter[1];", GL)


if __name__ == "__main__":
    unittest.main()
