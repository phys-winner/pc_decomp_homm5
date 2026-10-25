"""Full-function/forward-CFG oracle for the sampled CF60A0 matrix inverse."""
import hashlib
from pathlib import Path
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_fpu_cache_matrices import matrix_fixture
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

sys.path.insert(0, str(ROOT / "tools"))
from fpu_cache import (HELPERS, INVERSE_BASELINE_SHA256, INVERSE_BEGIN, INVERSE_END, INVERSE_SYMBOL,
                       cache_particle_math_source, inverse_baseline_region, inverse_cached_region)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN


def inverse_fixture(source):
    import pefile
    # Reuse the tested full-state/ABI harness; replace only its two leaf bodies
    # and matrix-input setup with the production inverse function.
    fixture = matrix_fixture((ROOT / "generated/game-x86/game_0308.c").read_text(encoding="utf-8"))
    base = inverse_baseline_region(source)
    cached = function(cache_particle_math_source(source), INVERSE_SYMBOL)
    original = cached.replace(inverse_cached_region(base), base)
    assert original != cached
    fixture = fixture.replace(function(fixture, "static void original("),
                              original.replace("void sub_00CF60A0(void)", "static void original(void)"))
    fixture = fixture.replace(function(fixture, "static void cached("),
                              cached.replace("void sub_00CF60A0(void)", "static void cached(void)"))
    fixture = fixture.replace("goto L_007CC7C0;", "goto L_00CF60A0; if(0) goto L_00CF63A5;")
    header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
    names = ("_fpu_cmp", "SET_LO8", "HI8", "LO8", "CMP_B", "FK_NARROW", "FPU_CMP", "RECOMP_PF")
    helpers = "\n".join(line for line in header.splitlines() if any(
        line.startswith("#define " + name + "(") or line.startswith("#define " + name + " ") for name in names))
    helpers += "\n" + body(header, "static inline uint32_t recomp_parity8(uint8_t v) {")
    helpers += "\n" + function(header, "static inline uint32_t _pop32(")
    helpers += "\n#define POP32_VAL(sp) _pop32(&(sp))\n"
    helpers += function(HELPERS, "static inline void h5_fpu_cache_xch(")
    fixture = fixture.replace("#define eax l_eax", helpers + "\n#define eax l_eax", 1)
    pe = pefile.PE(str(ROOT / "generated/input/H5_Game.exe"))
    constants = "".join("MEM32(0x%X)=0x%Xu;" % (address, int.from_bytes(
        pe.get_data(address - pe.OPTIONAL_HEADER.ImageBase, 4), "little")) for address in (0xE0BE10, 0xE0A7E4))
    fixture = fixture.replace("    output_address=g_ecx;MEM32(g_esp+4)=left;", r'''    g_edx=left;
    if(test%8==2)g_ecx=left+8;
    if(test%8==4)g_ecx=left+12;
    if(test%8==5)g_ecx=left+16;
    if(test%8==6)g_ecx=g_esp-0x20;
    if(test==0)for(unsigned i=0;i<16;++i)MEM32(left+4*i)=(i%5==0)?0x3F800000u:0;
    if(test==1)for(unsigned i=0;i<16;++i)MEM32(left+4*i)=0;
    output_address=g_ecx;
''' + constants)
    fixture = fixture.replace("return address>=output_address && address<output_address+64 && !(address&3u);",
                              "return !(address&3u) && ((address>=output_address && address<output_address+64) || (address>=0x17FC8 && address<0x18000));")
    fixture = fixture.replace("static unsigned nan_payload_differences;", "static unsigned zero_path,nonzero_path;\nstatic unsigned nan_payload_differences;")
    fixture = fixture.replace("original();take(&expected);", "original();take(&expected);if(expected.regs[0]&255u)++nonzero_path;else ++zero_path;")
    fixture = fixture.replace("assert(expected.regs[0]==0x10000 && expected.regs[4]==entry.regs[4]+8);",
                              "assert((expected.regs[0]&255u)<=1 && expected.regs[4]==entry.regs[4]+4);")
    fixture = fixture.replace("assert(!memcmp(expected.flags,entry.flags,sizeof entry.flags));", r'''assert(expected.flags[0]==0 && expected.flags[1]==FK_ADD);
        assert(expected.flags[2]==entry.regs[4]-0x38 && expected.flags[3]==0x38);''')
    fixture = fixture.replace('    printf("PASS %u', '    assert(zero_path && nonzero_path);\n    printf("PASS %u')
    fixture = fixture.replace("complete 7CC7C0 ABI/alias comparisons", "complete CF60A0 CFG/ABI/alias comparisons")
    fixture = fixture.replace("8alias layouts, ret4", "both AL paths, 8alias layouts, ret0")
    return fixture


class InverseFPUCacheTest(unittest.TestCase):
    def source(self):
        return (ROOT / "generated/game-x86/game_0700.c").read_text(encoding="utf-8")

    def test_pinned_forward_cfg_and_idempotence(self):
        source = self.source()
        base = inverse_baseline_region(source)
        self.assertEqual(hashlib.sha256(base.encode()).hexdigest(), INVERSE_BASELINE_SHA256)
        self.assertEqual(base.count("fp_push("), 101)
        self.assertEqual(base.count("fp_pop()"), 101)
        self.assertEqual(re.findall(r"^(L_[0-9A-F]+):", base, re.M), ["L_00CF63A5", "L_00CF63A9", "L_00CF63AF"])
        self.assertEqual(re.findall(r"goto (L_[0-9A-F]+);", base), ["L_00CF63A9", "L_00CF63AF"])
        self.assertIsNone(re.search(r"\breturn\b|RECOMP_(?!PF\b)\w+", base))
        changed = cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(changed), changed)
        self.assertEqual(inverse_baseline_region(changed), base)
        self.assertEqual(changed.count(INVERSE_BEGIN), 1)
        self.assertEqual(changed.count(INVERSE_END), 1)
        func = function(changed, INVERSE_SYMBOL)
        self.assertLess(func.index(INVERSE_END), func.index("RECOMP_FLAGS_OUT();"))
        dispatch = (ROOT / "generated/game-x86/recomp_dispatch.c").read_text()
        entries = [int(v, 16) for v in re.findall(r"\{0x([0-9A-F]+)u,", dispatch)]
        self.assertEqual([v for v in entries if 0xCF60A0 <= v <= 0xCF6431], [0xCF60A0])

    def test_reject_math_calls_backedges_and_extra_entries(self):
        base = inverse_baseline_region(self.source())
        for broken in (base.replace("0x28", "0x24", 1), base + "L_00CF63AB:\n",
                       base.replace("goto L_00CF63AF;", "goto L_00CF63A5;"),
                       base + "RECOMP_CALL(sub_00CF63AF);\n", base + "return;\n"):
            with self.subTest(change=broken[-60:]):
                with self.assertRaises(ValueError):
                    inverse_cached_region(broken)

    def test_complete_function_abi_and_state(self):
        fixture = inverse_fixture(self.source())
        compiler = (TOOLCHAIN / 'bin/clang-cl.exe')
        for mode in ("precise", "strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache_inverse_" + mode, fixture, {},
                              extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing",
                                           "/clang:-fwrapv"), compiler_override=compiler)


if __name__ == "__main__":
    unittest.main()
