"""Run the real 7CC7C0 matrix function before/after its pinned x87 transform."""
import hashlib
from pathlib import Path
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_fpu_cache import HARNESS
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

sys.path.insert(0, str(ROOT / "tools"))
from fpu_cache import (HELPERS, MATRIX_BASELINE_SHA256, MATRIX_BEGIN, MATRIX_END, MATRIX_SYMBOL,
                       cache_particle_math_source, matrix_baseline_region, matrix_cached_region)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN


INITIALIZE = r'''static void initialize(unsigned test,unsigned rounding) {
    input_family=test<256?0:test<384?1:2;
    for(unsigned i=0;i<0x20000;i+=4) MEM32(0x10000+i)=float_bits(test+i);
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=random64();
        if(i<4) bits=(uint64_t[]){0,0x8000000000000000ull,0x7FF0000000000000ull,0x7FF8123456789ABCull}[(test+i)%4];
        memcpy(&g_st[i],&bits,8);g_st_i64[i]=(int64_t)random64();
    }
    g_fp_top=(int)(test%33)-16;void_fpu_cmp=(int)(random64()&0x7FFFFu);g_fpu_cw=(uint16_t)(0x037F|(rounding<<10));
    eax=(uint32_t)random64();ecx=0x12000;edx=0x11000;ebx=(uint32_t)random64();
    esp=0x18000;ebp=(uint32_t)random64();esi=(uint32_t)random64();edi=(uint32_t)random64();
    _cf=(uint32_t)random64();_flag_k=(uint32_t)random64();_flag_a=(uint32_t)random64();_flag_b=(uint32_t)random64();
    uint32_t left=0x10000;
    switch(test%8) {
    case 1:ecx=left;break;
    case 2:ecx=edx;break;
    case 3:ecx=left+4;break;
    case 4:ecx=edx+12;break;
    case 5:edx=left;break;
    case 6:ecx=esp+0x20;break;
    case 7:ecx=esp;break;
    }
    output_address=ecx;MEM32(esp+4)=left;
}
'''

COMPARE_CONTRACT = r'''static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;output_address=0x12000;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);
    assert(same_snapshot(&expected,&actual,0));
    actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
    actual.regs[1]=1;assert(!same_snapshot(&expected,&actual,0));actual.regs[1]=0;
    actual.st[7]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[7]=0;
    actual.flags[2]=1;assert(!same_snapshot(&expected,&actual,0));actual.flags[2]=0;
    a=0;b=0x80000000u;memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);
    assert(!same_snapshot(&expected,&actual,0));
    a=0x7FC12345u;b=0xFFC54321u;
    memset(&expected,0,sizeof expected);actual=expected;
    memcpy(expected.memory+0x2040,&a,4);memcpy(actual.memory+0x2040,&b,4);
    assert(!same_snapshot(&expected,&actual,0));
}
'''


def matrix_fixture(source):
    transformed = cache_particle_math_source(source)
    base = matrix_baseline_region(source)
    changed = function(transformed, MATRIX_SYMBOL)
    original = changed.replace(matrix_cached_region(base), base)
    assert original != changed
    header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
    start = header.index("enum {\n    FK_NONE")
    flag_enum = header[start:header.index("};", start) + 2]
    fp_helpers = "\n".join(body(header, "static inline " + signature) for signature in
                           ("void fp_push_impl(", "double fp_pop_impl("))
    local_helpers = HELPERS.replace(function(HELPERS, "static inline void h5_fpu_cache_xch("), "")
    fixture = HARNESS.replace("/* ACTUAL_FLAG_ENUM */", flag_enum).replace("/* ACTUAL_FPU_HELPERS */", fp_helpers)
    fixture = fixture.replace("/* LOCAL_HELPERS */", local_helpers)
    fixture = fixture.replace("static void initialize(", "static uint32_t output_address;\nstatic void initialize(", 1)
    fixture = fixture.replace(function(fixture, "static void initialize("), INITIALIZE)
    fixture = fixture.replace(function(fixture, "static int computed_float_store("), r'''static int computed_float_store(uint32_t address) {
    return address>=output_address && address<output_address+64 && !(address&3u);
}
''')
    fixture = fixture.replace(function(fixture, "static void comparison_contract("), COMPARE_CONTRACT)
    # Use the production local-GPR and flag transfer macros around the complete
    # functions, including RECOMP_ENTER and the ret4 stack adjustment.
    names = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")
    for name in names:
        fixture = re.sub(r"\b" + name + r"\b", "g_" + name, fixture)
    for old, new in (("_cf", "g_flag_cf"), ("_flag_k", "g_flag_k"), ("_flag_a", "g_flag_a"), ("_flag_b", "g_flag_b")):
        fixture = re.sub(r"\b" + old + r"\b", new, fixture)
    macro_names = (*names, "RECOMP_REGS_LOCALS", "RECOMP_REGS_OUT", "RECOMP_XMM_OUT", "RECOMP_BACKEDGE_OUT", "RECOMP_FLAGS_IN", "RECOMP_FLAGS_OUT")
    macros = []
    for name in macro_names:
        macros.append(next(line for line in header.splitlines() if line.startswith("#define " + name + " ") or
                           line.startswith("#define " + name + "(")))
    prelude = "\n".join(macros) + "\n#define RECOMP_ENTER(va) do { (void)(va); (void)_df; (void)_itail_tgt; RECOMP_FLAGS_IN(); if(0) goto L_007CC7C0; } while(0)\n"
    suffix = "\n" + "\n".join("#undef " + name for name in (*macro_names, "RECOMP_ENTER")) + "\n"
    original = original.replace("void sub_007CC7C0(void)", "static void original(void)")
    changed = changed.replace("void sub_007CC7C0(void)", "static void cached(void)")
    fixture = fixture.replace("static void original(void) {\n/* ORIGINAL */\n}\nstatic void cached(void) {\n/* CACHED */\n}",
                              prelude + original + "\n" + changed + suffix)
    fixture = fixture.replace("restore(&entry);cached();take(&actual);", r'''assert(expected.regs[0]==0x10000 && expected.regs[4]==entry.regs[4]+8);
        for(unsigned i=1;i<8;++i) if(i!=4) assert(expected.regs[i]==entry.regs[i]);
        assert(!memcmp(expected.flags,entry.flags,sizeof entry.flags));
        restore(&entry);cached();take(&actual);''')
    fixture = fixture.replace("particle comparisons", "complete 7CC7C0 ABI/alias comparisons")
    fixture = fixture.replace("all4RC, bounded/large finite/NaN/Inf/signedzero/subnormals",
                              "8alias layouts, ret4, all4CW RC, bounded/large finite/NaN/Inf/signedzero/subnormals")
    return fixture


class MatrixFPUCacheTest(unittest.TestCase):
    def source(self):
        return (ROOT / "generated/game-x86/game_0308.c").read_text(encoding="utf-8")

    def test_pinned_scope_and_idempotence(self):
        source = self.source()
        base = matrix_baseline_region(source)
        self.assertEqual(hashlib.sha256(base.encode()).hexdigest(), MATRIX_BASELINE_SHA256)
        self.assertEqual(base.count("fp_push("), 64)
        self.assertEqual(base.count("fp_pop()"), 64)
        self.assertIsNone(re.search(r"\b(goto|return|RECOMP_\w+)\b|^L_", base, re.M))
        changed = cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(changed), changed)
        self.assertEqual(matrix_baseline_region(changed), base)
        self.assertEqual(changed.count(MATRIX_BEGIN), 1)
        self.assertEqual(changed.count(MATRIX_END), 1)
        func = function(changed, MATRIX_SYMBOL)
        self.assertLess(func.index(MATRIX_END), func.index("RECOMP_FLAGS_OUT();"))
        self.assertEqual(function(source, "void sub_007CC9D0("), function(changed, "void sub_007CC9D0("))

    def test_reject_changed_math_and_interior_dispatch(self):
        base = matrix_baseline_region(self.source())
        for broken in (base.replace("0x20", "0x24", 1), base + "L_007CC800:\n",
                       base + "goto L_007CC800;\n", base + "RECOMP_CALL(sub_007CC800);\n"):
            with self.subTest(change=broken[-60:]):
                with self.assertRaises(ValueError):
                    matrix_cached_region(broken)

    def test_complete_function_abi_and_state(self):
        fixture = matrix_fixture(self.source())
        compiler = (TOOLCHAIN / 'bin/clang-cl.exe')
        for mode in ("precise", "strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache_matrices_" + mode, fixture, {},
                              extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing",
                                           "/clang:-fwrapv"),
                              compiler_override=compiler)


if __name__ == "__main__":
    unittest.main()
