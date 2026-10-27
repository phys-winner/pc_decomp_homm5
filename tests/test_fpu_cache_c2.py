"""Execute production C2 x87 scopes with exact live state and raw-copy checks."""
import hashlib
from pathlib import Path
import re
import sys
import unittest

from test_d3d_lifecycle import function
from test_fpu_cache import HARNESS
from test_fpu_cache_matrices import matrix_fixture
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

sys.path.insert(0, str(ROOT / "tools"))
from fpu_cache import (HELPERS, THREE_BLOCK_SPECS, scoped_baseline_region, scoped_cached_region,
                       POSE_ACCUM_SYMBOL, POSE_ACCUM_BEGIN, POSE_ACCUM_END, POSE_ACCUM_BASELINE_SHA256,
                       pose_accum_baseline_region, pose_accum_cached_region, cache_particle_math_source,
                       GUARDED_VECTOR_SYMBOL, GUARDED_VECTOR_BEGIN, GUARDED_VECTOR_END, GUARDED_VECTOR_BASELINE_SHA256,
                       guarded_vector_baseline_region, guarded_vector_cached_region)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

COMPILER = (TOOLCHAIN / 'bin/clang-cl.exe')
BLOCK_COUNTS = {"search127c1": (1, 1), "search127ea": (1, 1), "projectc866f7": (9, 9), "edgec867e9": (3, 3)}
BLOCK_INITIALIZE = r'''static uint32_t output_address;
static unsigned computed_count;
static void initialize(unsigned test,unsigned rounding) {
    input_family=test<256?0:test<384?1:2;
    for(unsigned i=0;i<0x20000;i+=4) MEM32(0x10000+i)=float_bits(test+i);
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=random64();
        if(i<4) bits=(uint64_t[]){0,0x8000000000000000ull,0x7FF0000000000000ull,0x7FF8123456789ABCull}[(test+i)%4];
        memcpy(&g_st[i],&bits,8);g_st_i64[i]=(int64_t)random64();
    }
    g_fp_top=(int)(test%33)-16;void_fpu_cmp=(int)(random64()&0x7FFFFu);g_fpu_cw=(uint16_t)(0x037F|(rounding<<10));
    eax=(uint32_t)random64();ecx=(uint32_t)random64();edx=(uint32_t)random64();ebx=0x12000;
    esp=0x18000;ebp=0x14000;esi=0x14000;edi=(uint32_t)random64();
    _cf=(uint32_t)random64();_flag_k=(uint32_t)random64();_flag_a=(uint32_t)random64();_flag_b=(uint32_t)random64();
    output_address=0x12000;computed_count=0;
    /* CASE_INPUTS */
    /* CONSTANTS */
}
'''
BLOCK_INPUTS = {
    "search127c1": r'''ecx=2u+test%127u;esi=(test%3==0)?esp-0x100:0x14000;
    MEM32(esp+0x14)=float_bits(test);
    MEM32(esi+((ecx-((int32_t)ecx<0?UINT32_MAX:0u))>>1)*4)=float_bits(test+2);''',
    "search127ea": r'''ecx=test%127u;esi=(test%3==0)?esp-0x100:0x14000;
    MEM32(esp+0x14)=float_bits(test);
    MEM32(esi+ecx*4+4)=float_bits(test+2);''',
    "projectc866f7": r'''ecx=12u*(test%4);edi=test%4;
    const uint32_t targets[]={0x12000,0x14000,0x14004,0x14008,0x1801C,0x18020,0x18024,0x18028,0x18040,0x18044,0x18048,0x18050};
    output_address=targets[test%12];computed_count=2;
    MEM32(esp+0x28)=output_address-edi*8;
    if(test%12==1)output_address+=ecx,MEM32(esp+0x28)=output_address-edi*8;''',
    "edgec867e9": r'''eax=test%8;edx=(test/8)%8;edi=0x14000;ecx=test%4;
    const uint32_t targets[]={0x12000,0x14000,0x14004,0x14008,0x1801C,0x18020,0x18024,0x18028,0x18040,0x18044,0x18048,0x18050};
    output_address=targets[test%12];computed_count=1;ebx=output_address-ecx*4;
    if(test%12==1)output_address=edi+eax*8,ebx=output_address-ecx*4;
    if(test%12==2)output_address=edi+edx*8+4,ebx=output_address-ecx*4;''',
}


def c2_block_fixture(name, source):
    """Use the actual pinned transform, with production runtime FPU helpers."""
    import pefile
    region = scoped_baseline_region(source, name)
    changed = cache_particle_math_source(source)
    optimized = scoped_cached_region(region, name)
    assert optimized in changed
    header = (ROOT / "android/runtime/recomp_types.h").read_text()
    enum_start = header.index("enum {\n    FK_NONE")
    flag_enum = header[enum_start:header.index("};", enum_start) + 2]
    signatures = ["void fp_push_impl(", "double fp_pop_impl("]
    if "recomp_flags_pack(" in region:
        signatures += ["uint32_t recomp_parity8(uint8_t v) {", "uint32_t recomp_flags_pack("]
    helpers = "\n".join(body(header, "static inline " + sig) for sig in signatures)
    names = ("_fpu_cmp", "HI8", "LO8", "CMP_B", "FK_NARROW", "FPU_CMP")
    macros = "\n".join(line for line in header.splitlines() if any(
        line.startswith("#define " + n + "(") or line.startswith("#define " + n + " ") for n in names))
    fixture = HARNESS.replace("/* ACTUAL_FLAG_ENUM */", flag_enum).replace("/* ACTUAL_FPU_HELPERS */", helpers + "\n" + macros)
    local_helpers = HELPERS
    if "fp_xch(" not in region:
        local_helpers = local_helpers.replace(function(local_helpers, "static inline void h5_fpu_cache_xch("), "")
    fixture = fixture.replace("/* LOCAL_HELPERS */", local_helpers)
    fixture = fixture.replace("/* ORIGINAL */", region).replace("/* CACHED */", optimized)
    fixture = fixture.replace(function(fixture, "static void initialize("), BLOCK_INITIALIZE.replace("/* CASE_INPUTS */", BLOCK_INPUTS[name]))
    fixture = fixture.replace(function(fixture, "static int computed_float_store("), r'''static int computed_float_store(uint32_t address) {
    return !(address&3u) && address>=output_address && address<output_address+4*computed_count;
}''')
    fixture = fixture.replace(function(fixture, "static void comparison_contract("), r'''static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;output_address=0x12000;computed_count=1;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);assert(same_snapshot(&expected,&actual,0));
    actual.st[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[0]=0;
    actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
    actual.flags[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.flags[0]=0;
    a=0;b=0x80000000u;memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);assert(!same_snapshot(&expected,&actual,0));
    a=0x7FC12345u;b=0xFFC54321u;memset(&expected,0,sizeof expected);actual=expected;
    memcpy(expected.memory+0x2004,&a,4);memcpy(actual.memory+0x2004,&b,4);assert(!same_snapshot(&expected,&actual,0));
}''')
    pe = pefile.PE(str(ROOT / "generated/input/H5_Game.exe"))
    constants = "".join("MEM32(0x%X)=0x%08Xu;" % (a, int.from_bytes(pe.get_data(a-pe.OPTIONAL_HEADER.ImageBase,4), "little"))
                        for a in (0xE652E0, 0xE652E4, 0xE0BE10))
    fixture = fixture.replace("/* CONSTANTS */", constants)
    layout = "3 input layouts" if name.startswith("search") else "12 alias layouts"
    return fixture.replace("particle comparisons", name + " production comparisons (" + layout + ")")


def c2_pose_fixture(source):
    """Execute both production return/commit paths and strictly check rep movsd."""
    import pefile
    base = pose_accum_baseline_region(source)
    cached = function(cache_particle_math_source(source), POSE_ACCUM_SYMBOL)
    original = cached.replace(pose_accum_cached_region(base), base)
    assert original != cached
    fixture = matrix_fixture((ROOT / "generated/game-x86/game_0308.c").read_text())
    fixture = fixture.replace(function(fixture, "static void original("), original.replace("void sub_50028950(void)", "static void original(void)"))
    fixture = fixture.replace(function(fixture, "static void cached("), cached.replace("void sub_50028950(void)", "static void cached(void)"))
    labels = re.findall(r"^(L_[0-9A-F]+):", original, re.M)
    fixture = fixture.replace("goto L_007CC7C0;", " ".join("if(0)goto " + label + ";" for label in labels))
    header = (ROOT / "android/runtime/recomp_types.h").read_text()
    names = ("_fpu_cmp", "HI8", "LO8", "CMP_B", "CMP_EQ", "CMP_NE", "TEST_Z", "FK_NARROW", "FPU_CMP", "RECOMP_PF")
    helpers = "\n".join(line for line in header.splitlines() if any(
        line.startswith("#define " + n + "(") or line.startswith("#define " + n + " ") for n in names))
    helpers += "\n" + body(header, "static inline uint32_t recomp_parity8(uint8_t v) {")
    helpers += "\n" + body(header, "static inline uint32_t recomp_flags_pack(")
    helpers += "\n" + function(header, "static inline uint32_t _pop32(")
    helpers += "\n#define POP32_VAL(sp) _pop32(&(sp))\n"
    fixture = fixture.replace("#define eax l_eax", helpers + r'''
static uint32_t computed[64],computed_used,path_seen[16],raw_nan_copies;
static void note_raw(uint32_t address) {
    for(unsigned i=0;i<computed_used;++i)if(computed[i]==address)computed[i]=0;
}
#define eax l_eax''', 1)
    reference = function(fixture, "static void original(")
    reference = re.sub(r"^(L_[0-9A-F]+):", lambda m: m[0] + "\n    ++path_seen[" + str(labels.index(m[1])) + "];", reference, flags=re.M)
    reference = re.sub(r"^(.*\*\(float\*\)ADDR\(([^;]+)\) = _v;.*)$", r"    computed[computed_used++]=(uint32_t)(\2);\n\1", reference, flags=re.M)
    reference = re.sub(r"^(\s*MEM32\(([^;]+)\) = [^;]+;[^\n]*)$", r"    note_raw((uint32_t)(\2));\n\1", reference, flags=re.M)
    reference = re.sub(r"^(\s*PUSH32\(esp,[^\n]+)$", r"    note_raw(esp-4);\n\1", reference, flags=re.M)
    reference = reference.replace("while (ecx) { MEM32(edi) = MEM32(esi);",
        "while (ecx) { uint32_t bits=MEM32(esi); if((bits&0x7F800000u)==0x7F800000u && (bits&0x007FFFFFu))++raw_nan_copies; note_raw(edi); MEM32(edi) = MEM32(esi);")
    fixture = fixture.replace(function(fixture, "static void original("), reference)
    initialize = function(fixture, "static void initialize(")
    common = initialize[:initialize.index("    uint32_t left=")]
    pe = pefile.PE(str(ROOT / "generated/input/granny2.dll"))
    constants = "".join("MEM32(0x%X)=0x%08Xu;" % (a, int.from_bytes(pe.get_data(a-pe.OPTIONAL_HEADER.ImageBase, 4), "little"))
                        for a in (0x5004C0CC, 0x5004C0D0))
    extra = r'''    uint32_t provider=0x10000,index=test%4,destination=0x12000+index*80,input=0x14000;
    switch((test/4)%10) {
    case 1: input=destination;break;
    case 2: input=destination+8;break;
    case 3: input=destination+12;break;
    case 4: input=destination-8;break;
    case 5: destination=0x17FC0;break;
    case 6: destination=0x17FD0;break;
    case 7: destination=0x18000;break;
    case 8: input=0x18008;break;
    case 9: input=provider;break;
    }
    computed_used=0;output_address=destination;
    MEM32(g_esp+4)=provider;MEM32(g_esp+8)=index;
    MEM32(g_esp+12)=(test%8<2)?0x3F800000u:float_bits(test);
    MEM32(g_esp+16)=0x16000;MEM32(0x16008)=0x16400;
    MEM32(g_esp+20)=(test/8)%4;MEM32(g_esp+24)=input;
    MEM32(provider+4)=destination-index*80;MEM32(provider+12)=0x13579BDF;
    MEM32(destination+0x4C)=(test&4)?0x13579BDF:0x2468ACE0;
    /* CONSTANTS */
}
'''
    fixture = fixture.replace(initialize, common + extra.replace("/* CONSTANTS */", constants))
    fixture = fixture.replace("static uint8_t memory[0x1100000];", "static uint8_t memory[0x1100000];\nstatic uint32_t granny_constants[2];")
    fixture = fixture.replace("#define GPTR(va) (memory+(uint32_t)(va))", "#define GPTR(va) ((uint32_t)(va)>=0x5004C0CCu && (uint32_t)(va)<=0x5004C0D3u ? (uint8_t*)granny_constants+((uint32_t)(va)-0x5004C0CCu) : memory+(uint32_t)(va))")
    fixture = fixture.replace(function(fixture, "static int computed_float_store("), r'''static int computed_float_store(uint32_t address) {
    for(unsigned i=0;i<computed_used;++i)if(computed[i]==address)return 1;
    return 0;
}''')
    fixture = fixture.replace(function(fixture, "static void comparison_contract("), r'''static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;computed[0]=0x12000;computed_used=1;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);assert(same_snapshot(&expected,&actual,0));
    note_raw(0x12000);assert(!same_snapshot(&expected,&actual,0));computed[0]=0x12000;
    actual.st[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[0]=0;
    actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
    memset(&expected,0,sizeof expected);actual=expected;
    memcpy(expected.memory+0x2004,&a,4);memcpy(actual.memory+0x2004,&b,4);assert(!same_snapshot(&expected,&actual,0));
}''')
    start = fixture.index("assert(expected.regs[0]==0x10000")
    stop = fixture.index("restore(&entry);cached();", start)
    fixture = fixture[:start] + "assert(expected.regs[4]==entry.regs[4]+4);\n        for(unsigned i=3;i<8;++i)if(i!=4)assert(expected.regs[i]==entry.regs[i] || output_address>=0x17FC0);\n        " + fixture[stop:]
    fixture = fixture.replace('    printf("PASS %u', '    assert(raw_nan_copies);\n    for(unsigned i=0;i<' + str(len(labels)) + ';++i)assert(path_seen[i]);\n    printf("PASS %u')
    fixture = fixture.replace("complete 7CC7C0 ABI/alias comparisons", "complete 50028950 production CFG/ABI/rawcopy comparisons")
    return fixture.replace("8alias layouts, ret4", "10alias layouts, all branch sentinels, ret0")


def c2_guarded_vector_fixture(source):
    """Exercise actual duplicated fallback under the same flags as the fast path."""
    base = guarded_vector_baseline_region(source)
    cached = function(cache_particle_math_source(source), GUARDED_VECTOR_SYMBOL)
    original = cached.replace(guarded_vector_cached_region(base), base)
    assert original != cached
    fixture = matrix_fixture((ROOT / "generated/game-x86/game_0308.c").read_text())
    fixture = fixture.replace(function(fixture, "static void original("), original.replace("void sub_00BA2270(void)", "static void original(void)"))
    fixture = fixture.replace(function(fixture, "static void cached("), cached.replace("void sub_00BA2270(void)", "static void cached(void)"))
    fixture = fixture.replace("goto L_007CC7C0;", "goto L_00BA2270;")
    fixture = fixture.replace("#define eax l_eax", "static unsigned fast_calls,total_calls,want_fast;\n#define eax l_eax", 1)
    cached = function(fixture, "static void cached(")
    instrumented = cached.replace("static void cached(void) {", "static void cached(void) {\n++total_calls;")
    instrumented = instrumented.replace("h5_fpu_cache _h5_fp;", "++fast_calls; h5_fpu_cache _h5_fp;")
    assert instrumented.count("++fast_calls;") == 1
    fixture = fixture.replace(cached, instrumented)
    fixture = fixture.replace("#define eax l_eax", function(HELPERS, "static inline void h5_fpu_cache_xch(") + "\n#define eax l_eax", 1)
    initialize = function(fixture, "static void initialize(")
    common = initialize[:initialize.index("    uint32_t left=")]
    extra = r'''    uint32_t input=0x11000;g_ecx=0x14000;output_address=0x12000;
    switch(test%8) {
    case 1:output_address=input;break;
    case 2:output_address=g_ecx;break;
    case 3:output_address=input+4;break;
    case 4:output_address=g_ecx+12;break;
    case 5:input=g_ecx+16;break;
    case 6:output_address=g_esp+4;break;
    case 7:output_address=g_esp+8;break;
    }
    MEM32(g_esp+4)=output_address;MEM32(g_esp+8)=input;
    uint32_t guarded[]={g_ecx+0x30,g_ecx+0x34,g_ecx+0x38,g_ecx+0x3C,input,input+4,input+8};
    if(test>=512) {
        for(unsigned i=0;i<16;++i)MEM32(g_ecx+i*4)=0x3F800000u;
        for(unsigned i=0;i<3;++i)MEM32(input+i*4)=0x3F800000u;
        if(test<540)MEM32(guarded[(test-512)%7])=(test&1)?0x7FA12345u:0xFFC54321u;
        else if(test<560)MEM32(guarded[(test-540)%7])=(test&1)?0x7F800000u:0xFF800000u;
        else if(test<568)for(unsigned i=0;i<7;++i)MEM32(guarded[i])=0x7F7FFFFFu;
        else if(test<576) {
            MEM32(guarded[0])=0x80000000u;MEM32(guarded[1])=0;MEM32(guarded[2])=1;MEM32(guarded[3])=0x80000001u;
            MEM32(input)=0x80000000u;MEM32(input+4)=0x7F7FFFFFu;MEM32(input+8)=0xFF7FFFFFu;
        } else if(test<592) {
            MEM32(g_ecx)=0x7FC12345u;MEM32(g_ecx+0x10)=0xFFC54321u;
        }
    }
    want_fast=1;
    for(unsigned i=0;i<7;++i)if((MEM32(guarded[i])&0x7F800000u)==0x7F800000u)want_fast=0;
}
'''
    fixture = fixture.replace(initialize, common + extra)
    fixture = fixture.replace(function(fixture, "static int computed_float_store("), r'''static int computed_float_store(uint32_t address) {
    return address==output_address || address==output_address+4 || address==output_address+8 || address==0x18008;
}''')
    fixture = fixture.replace(function(fixture, "static void comparison_contract("), r'''static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;output_address=0x12000;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);assert(same_snapshot(&expected,&actual,0));
    actual.st[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[0]=0;
    actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
    memset(&expected,0,sizeof expected);actual=expected;
    memcpy(expected.memory+0x200C,&a,4);memcpy(actual.memory+0x200C,&b,4);assert(!same_snapshot(&expected,&actual,0));
    memset(&expected,0,sizeof expected);actual=expected;
    expected.regs[1]=a;actual.regs[1]=b;assert(!same_snapshot(&expected,&actual,0));
}''')
    start = fixture.index("assert(expected.regs[0]==0x10000")
    stop = fixture.index("restore(&entry);cached();take(&actual);", start)
    fixture = fixture[:start] + r'''assert(expected.regs[0]==output_address && expected.regs[4]==entry.regs[4]+12);
        for(unsigned i=2;i<8;++i)if(i!=4)assert(expected.regs[i]==entry.regs[i]);
        assert(!memcmp(expected.flags,entry.flags,sizeof entry.flags));
        unsigned before=fast_calls;
        ''' + fixture[stop:]
    fixture = fixture.replace("cached();take(&actual);", "cached();take(&actual);assert((fast_calls-before)==want_fast);")
    fixture = fixture.replace("test<512", "test<640")
    fixture = fixture.replace('    printf("PASS %u', '    assert(fast_calls && fast_calls<total_calls);\n    printf("PASS %u')
    fixture = fixture.replace("complete 7CC7C0 ABI/alias comparisons", "complete BA2270 production guard/fallback ABI comparisons")
    return fixture.replace("8alias layouts, ret4", "8aliases, all7guard operands, NaN/Inf/finite overflow, ret8")


class C2FPUCacheTest(unittest.TestCase):
    def block_source(self, key):
        return (ROOT / THREE_BLOCK_SPECS[key]["source"]).read_text()

    def test_pinned_scopes_and_idempotence(self):
        for key, spec in THREE_BLOCK_SPECS.items():
            with self.subTest(scope=key):
                source = self.block_source(key)
                region = scoped_baseline_region(source, key)
                self.assertEqual(hashlib.sha256(region.encode()).hexdigest(), spec["digest"])
                self.assertEqual((region.count("fp_push("), region.count("fp_pop()")), BLOCK_COUNTS[key])
                self.assertIsNone(re.search(r"\b(?:goto|return|RECOMP_\w+)\b|^L_", region, re.M))
                transformed = cache_particle_math_source(source)
                self.assertEqual(cache_particle_math_source(transformed), transformed)
                self.assertEqual(scoped_baseline_region(transformed, key), region)
                self.assertEqual(transformed.count(spec["begin"]), 1)
                self.assertEqual(transformed.count(spec["end"]), 1)

    def test_changed_scopes_and_transfers_rejected(self):
        for key in THREE_BLOCK_SPECS:
            region = scoped_baseline_region(self.block_source(key), key)
            for broken in (region + "L_00000001:\n", region + "goto L_00000001;\n", region + "RECOMP_BACKEDGE();\n",
                           region + "RECOMP_CALL(sub_500127B0);\n", region.replace("fp_push(", "fp_pop(0*", 1)):
                with self.subTest(scope=key, change=broken[-60:]):
                    with self.assertRaises(ValueError):
                        scoped_cached_region(broken, key)

    def test_production_scopes_full_state(self):
        for key in THREE_BLOCK_SPECS:
            fixture = c2_block_fixture(key, self.block_source(key))
            for mode in ("precise", "strict"):
                with self.subTest(scope=key, fp=mode):
                    compile_probe("fpu_cache_c2_" + key + "_" + mode, fixture, {},
                                  extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"),
                                  compiler_override=COMPILER)

    def test_whole_pose_cfg_pins_and_dispatch(self):
        source = (ROOT / "generated/granny2-x86/granny2_0008.c").read_text()
        region = pose_accum_baseline_region(source)
        self.assertEqual(hashlib.sha256(region.encode()).hexdigest(), POSE_ACCUM_BASELINE_SHA256)
        self.assertEqual((region.count("fp_push("), region.count("fp_pop()")), (38, 38))
        self.assertEqual(region.count("RECOMP_FLAGS_OUT();"), 2)
        self.assertIsNone(re.search(r"RECOMP_(?:CALL|ICALL|BACKEDGE)", region))
        self.assertIn("ecx = 0x11u;", region)
        self.assertIn("while (ecx)", region)
        labels = {m[1]: m.start() for m in re.finditer(r"^(L_[0-9A-F]+):", region, re.M)}
        jumps = list(re.finditer(r"goto (L_[0-9A-F]+);", region))
        self.assertEqual(len(jumps), 8)
        self.assertTrue(all(labels[m[1]] > m.start() for m in jumps))
        transformed = cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(transformed), transformed)
        self.assertEqual(pose_accum_baseline_region(transformed), region)
        self.assertEqual(transformed.count(POSE_ACCUM_BEGIN), 1)
        self.assertEqual(transformed.count(POSE_ACCUM_END), 1)
        dispatch = (ROOT / "generated/granny2-x86/recomp_dispatch.c").read_text()
        entries = [int(v, 16) for v in re.findall(r"\{0x([0-9A-F]+)u,", dispatch)]
        self.assertEqual([v for v in entries if 0x50028950 <= v <= 0x50028B86], [0x50028950])
        for broken in (region + "RECOMP_CALL(sub_50028B90);\n", region + "L_50028970:\n",
                       region.replace("goto L_50028B52;", "goto L_500289B1;"), region.replace("0x11u", "0x12u", 1)):
            with self.assertRaises(ValueError):
                pose_accum_cached_region(broken)

    def test_whole_production_pose_state_and_executed_stores(self):
        fixture = c2_pose_fixture((ROOT / "generated/granny2-x86/granny2_0008.c").read_text())
        for mode in ("precise", "strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache_c2_pose_" + mode, fixture, {},
                              extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"),
                              compiler_override=COMPILER)

    def test_guarded_vector_pin_fallback_and_dispatch(self):
        source = (ROOT / "generated/game-x86/game_0595.c").read_text()
        region = guarded_vector_baseline_region(source)
        self.assertEqual(hashlib.sha256(region.encode()).hexdigest(), GUARDED_VECTOR_BASELINE_SHA256)
        self.assertIsNone(re.search(r"\b(?:goto|return|RECOMP_\w+)\b|^L_", region, re.M))
        transformed = cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(transformed), transformed)
        self.assertEqual(guarded_vector_baseline_region(transformed), region)
        self.assertEqual(transformed.count(GUARDED_VECTOR_BEGIN), 1)
        self.assertEqual(transformed.count(GUARDED_VECTOR_END), 1)
        dispatch = (ROOT / "generated/game-x86/recomp_dispatch.c").read_text()
        entries = [int(v, 16) for v in re.findall(r"\{0x([0-9A-F]+)u,", dispatch)]
        self.assertEqual([v for v in entries if 0xBA2270 <= v <= 0xBA22EC], [0xBA2270])
        for broken in (region + "RECOMP_CALL(sub_00BA22F0);\n", region.replace("0x38", "0x34", 1), region + "L_00BA22A0:\n"):
            with self.assertRaises(ValueError):
                guarded_vector_cached_region(broken)

    def test_guarded_vector_actual_production_fallback(self):
        fixture = c2_guarded_vector_fixture((ROOT / "generated/game-x86/game_0595.c").read_text())
        for mode in ("precise", "strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache_c2_guard_" + mode, fixture, {},
                              extra_flags=("/O2", "/fp:" + mode, "/clang:-ffp-contract=off", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"),
                              compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
