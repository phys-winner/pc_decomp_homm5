"""Run actual production CF norm/plane scopes without relaxing live NaN bits."""
import hashlib
from pathlib import Path
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_fpu_cache import HARNESS
from test_fpu_cache_matrices import matrix_fixture, INITIALIZE
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

sys.path.insert(0, str(ROOT / "tools"))
from fpu_cache import (HELPERS, CF_NORM_SYMBOL, CF_NORM_ENTRY, CF_NORM_BEGIN, CF_NORM_END,
                       CF_NORM_BASELINE_SHA256, NORM_GUARD_HELPER, norm_guard_baseline_region, norm_guard_cached_region,
                       PLANE_SYMBOL, PLANE_ENTRY, PLANE_STOP, PLANE_BEGIN, PLANE_END, PLANE_BASELINE_SHA256,
                       plane_baseline_region, plane_cached_region, cache_particle_math_source)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

COMPILER = (TOOLCHAIN / 'bin/clang-cl.exe')


def norm_fixture(source):
    import pefile
    region = norm_guard_baseline_region(source)
    cached = function(cache_particle_math_source(source), CF_NORM_SYMBOL)
    original = cached.replace(norm_guard_cached_region(region), region)
    assert original != cached
    result = matrix_fixture((ROOT / "generated/game-x86/game_0308.c").read_text())
    result = result.replace(function(result, "static void original("), original.replace("void sub_00CF6E50(void)", "static void original(void)"))
    result = result.replace(function(result, "static void cached("), cached.replace("void sub_00CF6E50(void)", "static void cached(void)"))
    all_labels = set(re.findall(r"^(L_[A-Za-z0-9_]+):", original + cached, re.M))
    result = result.replace("goto L_007CC7C0;", " ".join("if(0)goto " + label + ";" for label in sorted(all_labels)))
    # Only fallback labels occur in cached(); its entry macro must not refer
    # to labels in the other function. Keep those dummy references local.
    prelude = re.search(r"#define RECOMP_ENTER\(va\)[^\n]+", result)[0]
    result = result.replace(prelude, re.sub(r"if\(0\)goto L_H5_NORM_BASE_[^;]+;", "", prelude))
    fn = function(result, "static void cached(")
    fallback_labels = re.findall(r"^(L_H5_NORM_BASE_[A-Za-z0-9_]+):", fn, re.M)
    fn = fn.replace("static void cached(void) {", "static void cached(void) {\n++total_calls;\n" +
                    " ".join("if(0)goto " + label + ";" for label in fallback_labels) + "\n")
    fn = fn.replace("h5_fpu_cache _h5_fp;", "++fast_calls; h5_fpu_cache _h5_fp;")
    assert fn.count("++fast_calls;") == 1
    result = result.replace(function(result, "static void cached("), fn)
    header = (ROOT / "android/runtime/recomp_types.h").read_text()
    names = ("_fpu_cmp", "HI8", "CMP_B", "FK_NARROW", "FPU_CMP", "RECOMP_PF")
    helpers = "\n".join(line for line in header.splitlines() if any(
        line.startswith("#define " + n + "(") or line.startswith("#define " + n + " ") for n in names))
    helpers += "\n" + body(header, "static inline uint32_t recomp_parity8(uint8_t v) {")
    helpers += "\n" + function(HELPERS, "static inline void h5_fpu_cache_xch(")
    helpers += "\nstatic unsigned fast_calls,total_calls,want_fast,path_seen[5];\n" + NORM_GUARD_HELPER
    result = result.replace("#define eax l_eax", helpers + "\n#define eax l_eax", 1)
    reference = function(result, "static void original(")
    labels = re.findall(r"^(L_[0-9A-F]+):", reference, re.M)
    reference = re.sub(r"^(L_[0-9A-F]+):", lambda m: m[0] + "\n++path_seen[" + str(labels.index(m[1])) + "];", reference, flags=re.M)
    result = result.replace(function(result, "static void original("), reference)
    init = function(result, "static void initialize(")
    common = init[:init.index("    uint32_t left=")]
    extra = r'''    g_ecx=0x14000;g_edx=0x12000;
    switch(test%12) {
    case 1:g_ecx=g_edx;break;
    case 2:g_ecx=g_edx+4;break;
    case 3:g_edx=g_ecx+0x10;break;
    case 4:g_ecx=g_esp-0x2C;break;
    case 5:g_edx=g_esp-0x1C;break;
    case 6:g_edx=g_esp-0x28;break;
    case 7:g_ecx=g_esp-0x20;break;
    case 8:g_edx=g_esp-0x2C;break;
    case 9:g_ecx=g_esp;break;
    case 10:g_edx=g_esp;break;
    case 11:g_ecx=g_edx-0x10;break;
    }
    if(test>=512) {
        for(unsigned i=0;i<3;++i)MEM32(g_ecx+0x10+i*4)=0x3F800000u;
        for(unsigned row=0;row<3;++row)for(unsigned i=0;i<3;++i)MEM32(g_edx+row*0x10+i*4)=0x3F800000u;
        const uint32_t values[]={0x5F000000u,0xDF000000u,0x5F000001u,0xDF000001u,0x7F7FFFFFu,0xFF7FFFFFu,
            0x7FC12345u,0xFFC54321u,0x7FA12345u,0x7F800000u,0xFF800000u,0,0x80000000u,1,0x80000001u};
        uint32_t address[12]={g_ecx+0x10,g_ecx+0x14,g_ecx+0x18,g_edx,g_edx+4,g_edx+8,
            g_edx+0x10,g_edx+0x14,g_edx+0x18,g_edx+0x20,g_edx+0x24,g_edx+0x28};
        MEM32(address[(test-512)%12])=values[((test-512)/12)%15];
        if(test>=692)for(unsigned i=0;i<12;++i)MEM32(address[i])=((i+test)&1)?0x5F000000u:0xDF000000u;
    }
    output_address=g_esp;want_fast=(unsigned)h5_bounded_norm_inputs(g_ecx,g_edx,g_esp);
    /* CONSTANT */
}
'''
    pe = pefile.PE(str(ROOT / "generated/input/H5_Game.exe"))
    zero = int.from_bytes(pe.get_data(0xE0BE10-pe.OPTIONAL_HEADER.ImageBase,4), "little")
    result = result.replace(init, common + extra.replace("/* CONSTANT */", "MEM32(0xE0BE10)=0x%08Xu;" % zero))
    result = result.replace(function(result, "static int computed_float_store("), r'''static int computed_float_store(uint32_t address) {
    return address==0x17FE8 || address==0x17FEC || address==0x17FF0 || address==0x17FF8 || address==0x17FFC;
}''')
    result = result.replace(function(result, "static void comparison_contract("), r'''static void comparison_contract(void) {
    assert(!h5_bounded_norm_inputs(UINT32_MAX-0x1B,0x12000,0x18000));
    assert(!h5_bounded_norm_inputs(0x14000,UINT32_MAX-0x2B,0x18000));
    assert(!h5_bounded_norm_inputs(0x14000,0x12000,0x1B));
    assert(!h5_bounded_norm_inputs(0x17FD4,0x12000,0x18000));
    assert(!h5_bounded_norm_inputs(0x14000,0x17FE4,0x18000));
    uint32_t address[12]={0x14010,0x14014,0x14018,0x12000,0x12004,0x12008,0x12010,0x12014,0x12018,0x12020,0x12024,0x12028};
    for(unsigned i=0;i<12;++i)MEM32(address[i])=0x5F000000u;
    assert(h5_bounded_norm_inputs(0x14000,0x12000,0x18000));
    for(unsigned i=0;i<12;++i) {
        MEM32(address[i])=0x5F000001u;assert(!h5_bounded_norm_inputs(0x14000,0x12000,0x18000));
        MEM32(address[i])=0xDF000000u;assert(h5_bounded_norm_inputs(0x14000,0x12000,0x18000));
    }
    memset(&expected,0,sizeof expected);actual=expected;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x7FE8,&a,4);memcpy(actual.memory+0x7FE8,&b,4);assert(same_snapshot(&expected,&actual,0));
    actual.st[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[0]=0;
    actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
    memset(&expected,0,sizeof expected);actual=expected;
    memcpy(expected.memory+0x7FE4,&a,4);memcpy(actual.memory+0x7FE4,&b,4);assert(!same_snapshot(&expected,&actual,0));
}''')
    start = result.index("assert(expected.regs[0]==0x10000")
    stop = result.index("restore(&entry);cached();take(&actual);", start)
    result = result[:start] + r'''assert(expected.regs[4]==entry.regs[4]+4 && expected.top==entry.top+1);
        for(unsigned i=1;i<8;++i)if(i!=4)assert(expected.regs[i]==entry.regs[i]);
        assert(expected.flags[0]==0 && expected.flags[1]==FK_ADD && expected.flags[2]==entry.regs[4]-0x1C && expected.flags[3]==0x1C);
        unsigned before=fast_calls;
        ''' + result[stop:]
    result = result.replace("cached();take(&actual);", r'''cached();take(&actual);assert(fast_calls-before==want_fast);
        if(want_fast) {double norm;memcpy(&norm,&actual.st[0],sizeof norm);assert(isfinite(norm));}''')
    result = result.replace("test<512", "test<704")
    result = result.replace("            return 1;", '            for(unsigned j=0;j<8;++j)fprintf(stderr,"ST%u expected=%016llX actual=%016llX\\n",j,(unsigned long long)expected.st[j],(unsigned long long)actual.st[j]);\n            return 1;')
    result = result.replace('    printf("PASS %u', '    assert(fast_calls && fast_calls<total_calls);\n    for(unsigned i=0;i<5;++i)assert(path_seen[i]);\n    printf("PASS %u')
    result = result.replace("complete 7CC7C0 ABI/alias comparisons", "production CF6E50 guard/fallback CFG/live-norm ABI comparisons")
    return result.replace("8alias layouts, ret4", "12aliases, allbranches, liveST0 exact, bound/wrap/overlap checks, ret0")


def plane_fixture(source):
    region = plane_baseline_region(source)
    optimized = plane_cached_region(region)
    assert optimized in cache_particle_math_source(source)
    header = (ROOT / "android/runtime/recomp_types.h").read_text()
    start = header.index("enum {\n    FK_NONE")
    flag_enum = header[start:header.index("};", start) + 2]
    helpers = "\n".join(body(header, "static inline " + sig) for sig in ("void fp_push_impl(", "double fp_pop_impl("))
    names = ("_fpu_cmp", "HI8", "FK_NARROW", "FPU_CMP")
    helpers += "\n" + "\n".join(line for line in header.splitlines() if any(
        line.startswith("#define " + n + "(") or line.startswith("#define " + n + " ") for n in names))
    local_helpers = HELPERS.replace(function(HELPERS, "static inline void h5_fpu_cache_xch("), "")
    result = HARNESS.replace("/* ACTUAL_FLAG_ENUM */", flag_enum).replace("/* ACTUAL_FPU_HELPERS */", helpers)
    result = result.replace("/* LOCAL_HELPERS */", local_helpers).replace("/* ORIGINAL */", region).replace("/* CACHED */", optimized)
    init = INITIALIZE[:INITIALIZE.index("    uint32_t left=")]
    result = result.replace(function(result, "static void initialize("), init + r'''    ecx=0x14008;
    uint32_t radius=0x12000;
    switch(test%8) {
    case 1:ecx=esp+0x10;break;
    case 2:radius=ecx;break;
    case 3:radius=esp;break;
    case 4:radius=esp+0x18;break;
    case 5:ecx=esp+0x20;break;
    case 6:ecx=radius+4;break;
    case 7:radius=ecx-8;break;
    }
    MEM32(esp+0x24)=radius;
}''')
    # The scope has no float32 stores: all bytes, including NaN memory and all
    # FPU slots, are strictly equal. No arithmetic-store exception is needed.
    result = result.replace(function(result, "static int computed_float_store("), "")
    result = result.replace(function(result, "static int nan32("), "")
    result = result.replace(function(result, "static int same_snapshot("), r'''static int same_snapshot(const snapshot *a,const snapshot *b,int count) {
    (void)count;return !memcmp(a,b,sizeof *a);
}
''')
    result = result.replace(function(result, "static void comparison_contract("), r'''static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;assert(same_snapshot(&expected,&actual,0));
    expected.st[0]=0x7FF8123456789ABCull;actual.st[0]=0xFFF876543210ABCDull;assert(!same_snapshot(&expected,&actual,0));
    memset(&expected,0,sizeof expected);actual=expected;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory,&a,4);memcpy(actual.memory,&b,4);assert(!same_snapshot(&expected,&actual,0));
}''')
    return result.replace("particle comparisons", "production CF74AA plane comparisons (8aliases, no NaN tolerance)")


class CFFPUCacheTest(unittest.TestCase):
    def source(self):
        return (ROOT / "generated/game-x86/game_0700.c").read_text()

    def test_pins_idempotence_sibling_and_dispatch(self):
        source = self.source()
        norm = norm_guard_baseline_region(source)
        plane = plane_baseline_region(source)
        self.assertEqual(hashlib.sha256(norm.encode()).hexdigest(), CF_NORM_BASELINE_SHA256)
        self.assertEqual(hashlib.sha256(plane.encode()).hexdigest(), PLANE_BASELINE_SHA256)
        self.assertEqual((norm.count("fp_push("), norm.count("fp_pop()")), (21, 20))
        self.assertEqual((plane.count("fp_push("), plane.count("fp_pop()")), (5, 5))
        transformed = cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(transformed), transformed)
        self.assertEqual(norm_guard_baseline_region(transformed), norm)
        self.assertEqual(plane_baseline_region(transformed), plane)
        for marker in (CF_NORM_BEGIN, CF_NORM_END, PLANE_BEGIN, PLANE_END, NORM_GUARD_HELPER):
            self.assertEqual(transformed.count(marker), 1)
        self.assertEqual(function(source, "void sub_00CF6F50(void)"), function(transformed, "void sub_00CF6F50(void)"))
        dispatch = (ROOT / "generated/game-x86/recomp_dispatch.c").read_text()
        entries = [int(v, 16) for v in re.findall(r"\{0x([0-9A-F]+)u,", dispatch)]
        self.assertEqual([v for v in entries if 0xCF6E50 <= v <= 0xCF6F4D], [0xCF6E50])
        self.assertEqual([v for v in entries if 0xCF74AA <= v <= 0xCF74DB], [])
        raw = source.replace(norm_guard_cached_region(norm), norm).replace(plane_cached_region(plane), plane)
        # The ordinary game path and its existing yield remain outside the scope.
        self.assertIn("RECOMP_CALL(sub_00BA2270);", function(raw, PLANE_SYMBOL))
        self.assertIn("RECOMP_BACKEDGE();", function(raw, PLANE_SYMBOL))
        self.assertIsNone(re.search(r"\b(?:goto|return|RECOMP_\w+)\b|^L_", plane, re.M))
        self.assertTrue(CF_NORM_ENTRY.endswith(":\n") and PLANE_ENTRY.endswith(":\n"))
        self.assertEqual(PLANE_STOP, "/* 0x00CF74DB:")

    def test_changed_math_transfers_and_guard_rejected(self):
        source = self.source()
        norm = norm_guard_baseline_region(source)
        plane = plane_baseline_region(source)
        for region, transform in ((norm, norm_guard_cached_region), (plane, plane_cached_region)):
            for broken in (region + "RECOMP_CALL(sub_00CF6F50);\n", region + "RECOMP_BACKEDGE();\n",
                           region + "L_00CF6EA0:\n", region.replace("0x14", "0x10", 1)):
                with self.assertRaises(ValueError):
                    transform(broken)
        for mutation in (source.replace("0x5F000000u", "0x7F7FFFFFu", 1),
                         source.replace("shape > UINT32_MAX - 0x1Cu", "shape > UINT32_MAX - 0x1Bu", 1)):
            self.assertNotEqual(mutation, source)
            with self.assertRaises(ValueError):
                cache_particle_math_source(mutation)

    def test_production_norm_full_state_and_live_nan(self):
        fixture = norm_fixture(self.source())
        for mode in ("precise", "strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache_cf_norm_" + mode, fixture, {},
                              extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"),
                              compiler_override=COMPILER)

    def test_production_plane_full_state(self):
        fixture = plane_fixture(self.source())
        for mode in ("precise", "strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache_cf_plane_" + mode, fixture, {},
                              extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"),
                              compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
