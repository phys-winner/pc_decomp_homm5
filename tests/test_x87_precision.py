"""x87 precision control: Direct3D's single precision on the device thread.

H5 creates its device without D3DCREATE_FPU_PRESERVE, so the original runs its
x87 arithmetic with 24-bit significands; its game data checksum (LAN) and its
simulation carry those bits. tools/build_android.py rounds every generated
x87 add, subtract, multiply, divide and square root through fp_pc, and
android/host/d3d9_device.c sets the precision field as Direct3D does.
"""
import random
import struct
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import build_android
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

CLANG = str(TOOLCHAIN / 'bin/clang-cl.exe')


def float_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


class TransformTest(unittest.TestCase):
    def test_each_generated_form_rounds_its_destination(self):
        lines = {
            b"    _st[0] *= (double)*(float*)ADDR(0xE0AB70); /* 0x0050F82F: fmul dword ptr [0xe0ab70] */":
                b"    _st[0] *= (double)*(float*)ADDR(0xE0AB70); _st[0] = fp_pc(_st[0]); /* 0x0050F82F: fmul dword ptr [0xe0ab70] */",
            b"    { double _v = fp_pop(); _st[1] += _v; } /* 0x005115CD: faddp st(2) */":
                b"    { double _v = fp_pop(); _st[1] += _v; } _st[1] = fp_pc(_st[1]); /* 0x005115CD: faddp st(2) */",
            b"    { double _v = fp_pop(); _st[0] = _v == 0.0 ? _st[0] : _st[0] / _v; } /* 0x00400001: fdivp st(1) */":
                b"    { double _v = fp_pop(); _st[0] = _v == 0.0 ? _st[0] : _st[0] / _v; } _st[0] = fp_pc(_st[0]); /* 0x00400001: fdivp st(1) */",
            b"    _h5_fp.st[0] *= _h5_fp.st[1]; /* 0x00400002: fmul st(1) */":
                b"    _h5_fp.st[0] *= _h5_fp.st[1]; _h5_fp.st[0] = fp_pc(_h5_fp.st[0]); /* 0x00400002: fmul st(1) */",
            b"    _st[0] = sqrt(_st[0]); /* 0x00400003: fsqrt  */":
                b"    _st[0] = sqrt(_st[0]); _st[0] = fp_pc(_st[0]); /* 0x00400003: fsqrt  */",
            b"    _st[0] = _st[0] * (double)(int32_t)MEM32(esp + 0x8); /* 0x00400004: fimul dword ptr [esp + 8] */":
                b"    _st[0] = _st[0] * (double)(int32_t)MEM32(esp + 0x8); _st[0] = fp_pc(_st[0]); /* 0x00400004: fimul dword ptr [esp + 8] */",
            b"    _st[7] /= _st[0]; /* 0x00400005: fdiv st(7), st(0) */":
                b"    _st[7] /= _st[0]; _st[7] = fp_pc(_st[7]); /* 0x00400005: fdiv st(7), st(0) */",
        }
        for before, after in lines.items():
            self.assertEqual(build_android.round_x87_precision(before), after)
        # A store to a float rounds by the rounding field.
        self.assertEqual(build_android.round_x87_precision(
            b"    { float _v = (float)fp_pop(); *(float*)ADDR(esp + 0x8) = _v; } /* 0x00400010: fstp dword ptr [esp + 8] */"),
            b"    { float _v = fp_f32(fp_pop()); *(float*)ADDR(esp + 0x8) = _v; } /* 0x00400010: fstp dword ptr [esp + 8] */")
        self.assertEqual(build_android.round_x87_precision(
            b"    { float _v = (float)_h5_fp.st[0]; *(float*)ADDR(eax) = _v; } /* 0x00400011: fst dword ptr [eax] */"),
            b"    { float _v = fp_f32(_h5_fp.st[0]); *(float*)ADDR(eax) = _v; } /* 0x00400011: fst dword ptr [eax] */")
        # A control word load recomputes the roundings.
        self.assertEqual(build_android.round_x87_precision(
            b"    _fpu_cw = MEM16(esp + 0x18); /* 0x0067069F: fldcw word ptr [esp + 0x18] */"),
            b"    fp_set_cw(MEM16(esp + 0x18)); /* 0x0067069F: fldcw word ptr [esp + 0x18] */")
        # Loads, double stores, compares and the other x87 instructions keep their bits.
        for line in (b"    fp_push((double)*(float*)ADDR(eax)); /* 0x00400006: fld dword ptr [eax] */",
                     b"    { double _v = fp_pop(); *(double*)ADDR(eax) = _v; } /* 0x00400007: fstp qword ptr [eax] */",
                     b"    _st[0] = -_st[0]; /* 0x00400008: fchs  */",
                     b"    _st[0] = sin(_st[0]); /* 0x00400009: fsin  */"):
            self.assertEqual(build_android.round_x87_precision(line), line)

    def test_a_form_without_destination_stops_the_build(self):
        with self.assertRaisesRegex(ValueError, "without a destination"):
            build_android.round_x87_precision(b"    h5_add(); /* 0x0040000A: fadd st(0), st(1) */")
        with self.assertRaisesRegex(ValueError, "float store of an unknown form"):
            build_android.round_x87_precision(b"    h5_store(); /* 0x0040000B: fstp dword ptr [eax] */")

    def test_generated_sources_all_have_known_forms(self):
        # A sample of the game's own x87-heavy sources (the build checks all).
        for name in ("game_0100.c", "game_0200.c"):
            text = (ROOT / "generated/game-x86" / name).read_bytes()
            rounded = build_android.round_x87_precision(build_android.guard_fpu_memory(text))
            self.assertGreater(rounded.count(b" = fp_pc("), 0)

    def test_direct3d_sets_single_precision_unless_preserved(self):
        source = (ROOT / "android/host/d3d9_device.c").read_text(encoding="utf-8")
        definition = "uint32_t d3d_device_create(uint32_t d3d9, uint32_t window, uint32_t behavior, uint32_t pp, uint32_t *out)\n{"
        create = source[source.index(definition):]
        create = create[:create.index("\n}\n")]
        self.assertIn("if (!(behavior & 2u)) { g_fpu_cw &= (uint16_t)~0x0F00u; fp_cw_masks(g_fpu_cw); }", create)


def chop_bits(value):
    """The float toward zero from a double (the x87 store under chop)."""
    bits = float_bits(value)
    if abs(struct.unpack("<f", struct.pack("<I", bits))[0]) > abs(value):
        bits -= 1
    return bits


class RoundingTest(unittest.TestCase):
    def test_round24_by_rounding_field_with_the_x87_exponent(self):
        header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
        helpers = "\n".join(function(header, "static inline " + kind) for kind in
                            ("double fp_round24(", "void fp_cw_masks(", "double fp_bits_and(",
                             "double fp_pc_round(", "float fp_f32_round("))
        rng = random.Random(5)
        cases = [0.759, 0.685, 2.396, 0.291, 1.0, -1.5, 0.0, -0.0, 3.4028234663852886e38, 1.1754943508222875e-38, -0.1]
        # Random doubles across the float range (float subnormals excepted: the
        # x87's wide exponent keeps all 24 bits there, a float would not).
        cases += [struct.unpack("<d", struct.pack("<Q", rng.getrandbits(64) & 0xC7DFFFFFFFFFFFFF | 0x3810000000000000))[0]
                  for _ in range(2000)]
        # Exact ties: a float's significand plus half an ulp, even and odd.
        cases += [struct.unpack("<d", struct.pack("<Q", 0x3FF0000010000000))[0],
                  struct.unpack("<d", struct.pack("<Q", 0x3FF0000030000000))[0],
                  struct.unpack("<d", struct.pack("<Q", 0x3FFFFFFFF0000000))[0]]
        rows = ",\n".join("{%r, 0x%08Xu, 0x%08Xu}" % (v, float_bits(v), chop_bits(v)) for v in cases
                          if abs(v) <= 3.4028234663852886e38)
        # The original's own decimal parser under its control word 0x0C7F
        # (single precision, chop): the bits read from its memory.
        parsed = {"1.2": 0x3F999999, "0.759": 0x3F424DD1, "0.685": 0x3F2F5C28, "2.396": 0x4019580F,
                  "0.291": 0x3E94FDF3, "5.7": 0x40B66666, "5.98345": 0x40BF7869}
        parse_rows = ",\n".join('{"%s", 0x%08Xu}' % item for item in parsed.items())
        harness = f"""
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define __builtin_expect(x, y) (x)
static uint16_t g_fpu_cw;
#define _fpu_cw g_fpu_cw
static uint64_t g_fp_round_mask, g_fp_store_mask;
{helpers}
static double pc(double v, uint16_t cw) {{ _fpu_cw = cw; fp_cw_masks(cw); return fp_pc_round(v); }}
static float f32(double v, uint16_t cw) {{ _fpu_cw = cw; fp_cw_masks(cw); return fp_f32_round(v); }}
static const struct {{ double v; uint32_t nearest, chop; }} cases[] = {{
{rows}
}};
static const struct {{ const char *text; uint32_t bits; }} parsed[] = {{
{parse_rows}
}};
static uint32_t bits_of(float f) {{ uint32_t b; memcpy(&b, &f, 4); return b; }}
/* Digits accumulated as H5 does: the fraction digit by digit, its scale by 0.1f. */
static float parse(const char *s, uint16_t cw) {{
    double v = 0, scale = 1;
    int fraction = 0;
    for (; *s; ++s) {{
        if (*s == '.') {{ fraction = 1; continue; }}
        int d = *s - '0';
        if (!fraction) v = pc(pc(v * 10, cw) + d, cw);
        else {{ scale = pc(scale * (double)0.1f, cw); v = pc(v + pc(d * scale, cw), cw); }}
    }}
    return f32(v, cw);
}}
int main(void) {{
    for (size_t i = 0; i < sizeof cases / sizeof *cases; ++i) {{
        double n = fp_round24(cases[i].v, 0), c = fp_round24(cases[i].v, 3);
        /* Exact in a float: the nearest one (ties to even), and the one toward zero. */
        if ((double)(float)n != n || bits_of((float)n) != cases[i].nearest) {{ printf("nearest %zu: %.17g -> %.17g\\n", i, cases[i].v, n); return 1; }}
        if ((double)(float)c != c || bits_of((float)c) != cases[i].chop) {{ printf("chop %zu: %.17g -> %.17g\\n", i, cases[i].v, c); return 1; }}
        if (bits_of(f32(cases[i].v, 0x0C7F)) != cases[i].chop || bits_of(f32(cases[i].v, 0x027F)) != cases[i].nearest) {{ printf("store %zu\\n", i); return 1; }}
        /* The masked fast path (0x0C7F) and the exact one (0x007F) agree with fp_round24. */
        if (pc(cases[i].v, 0x0C7F) != c || pc(cases[i].v, 0x007F) != n) {{ printf("modes %zu\\n", i); return 1; }}
        /* Up and down bracket the value. */
        double up = fp_round24(cases[i].v, 2), down = fp_round24(cases[i].v, 1);
        if (!(down <= cases[i].v && cases[i].v <= up)) {{ printf("direction %zu\\n", i); return 1; }}
    }}
    /* The 53-bit modes keep the double. */
    if (pc(0.1, 0x027F) != 0.1 || pc(0.1, 0x0E7F) != 0.1) {{ printf("53-bit\\n"); return 1; }}
    for (size_t i = 0; i < sizeof parsed / sizeof *parsed; ++i)
        if (bits_of(parse(parsed[i].text, 0x0C7F)) != parsed[i].bits) {{ printf("parse %s: %08X\\n", parsed[i].text, bits_of(parse(parsed[i].text, 0x0C7F))); return 1; }}
    /* Past a float's range the x87 keeps the magnitude; infinities and NaNs pass. */
    double big = fp_round24(1e300, 0), inf = fp_round24(INFINITY, 3), nan = fp_round24(NAN, 0);
    if (!(big > 9.9e299 && big < 1.1e300) || !isinf(inf) || !isnan(nan)) {{ printf("range\\n"); return 1; }}
    puts("round24 ok");
    return 0;
}}
"""
        compile_probe("x87_round24", harness, {}, extra_flags=("/O2", "/clang:-ffp-contract=off"), compiler_override=CLANG)


if __name__ == "__main__":
    unittest.main()
