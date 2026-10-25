"""Differentially execute the measured 465940 affine leaf and its production cache."""
import hashlib
from pathlib import Path
import re
import sys
import unittest
from test_d3d_lifecycle import function
from test_fpu_cache import HARNESS
from test_static_tls import ROOT,compile_probe
from test_user32_startup import body
sys.path.insert(0,str(ROOT/'tools'))
from fpu_cache import (HELPERS,AFFINE_SYMBOL,AFFINE_BEGIN,AFFINE_END,AFFINE_BASELINE_SHA256,
                       affine_baseline_region,affine_cached_region,cache_particle_math_source)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN
SOURCE=ROOT/'generated/game-x86/game_0041.c'


def affine_fixture():
    name='465940'
    source=SOURCE.read_text(encoding='utf-8')
    region=affine_baseline_region(source)
    cached=affine_cached_region(region)
    header=(ROOT/'android/runtime/recomp_types.h').read_text(encoding='utf-8')
    start=header.index('enum {\n    FK_NONE')
    enum=header[start:header.index('};',start)+2]
    helpers='\n'.join(body(header,'static inline '+s) for s in ('void fp_push_impl(','double fp_pop_impl('))
    fixture=HARNESS.replace('/* ACTUAL_FLAG_ENUM */',enum).replace('/* ACTUAL_FPU_HELPERS */',helpers).replace('/* LOCAL_HELPERS */',HELPERS).replace('/* ORIGINAL */',region).replace('/* CACHED */',cached)
    fixture=fixture.replace('static uint8_t memory[','static uint32_t output_address,input_address;\nstatic uint8_t memory[',1)
    fixture=fixture.replace(function(fixture,'static void initialize('),r'''static void initialize(unsigned test,unsigned rounding) {
    input_family=test<256?0:test<384?1:2;
    for(unsigned i=0;i<0x20000;i+=4) MEM32(0x10000+i)=float_bits(test+i);
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=random64();
        if(i<4) bits=(uint64_t[]){0,0x8000000000000000ull,0x7FF0000000000000ull,0x7FF8123456789ABCull}[(test+i)%4];
        memcpy(&g_st[i],&bits,8);g_st_i64[i]=(int64_t)random64();
    }
    g_fp_top=(int)(test%33)-16;void_fpu_cmp=(int)(random64()&0x7FFFFu);g_fpu_cw=(uint16_t)(0x037F|(rounding<<10));
    eax=(uint32_t)random64();ecx=0x14000;edx=(uint32_t)random64();ebx=(uint32_t)random64();
    esp=0x18000;ebp=(uint32_t)random64();esi=(uint32_t)random64();edi=(uint32_t)random64();
    input_address=0x11000;output_address=0x12000;
    switch(test%8) {
    case 1:output_address=input_address;break;
    case 2:output_address=ecx;break;
    case 3:output_address=input_address+4;break;
    case 4:output_address=ecx+12;break;
    case 5:input_address=ecx+16;break;
    case 6:output_address=esp+4;break;
    case 7:output_address=esp+8;break;
    }
    MEM32(esp+4)=output_address;MEM32(esp+8)=input_address;
    _cf=(uint32_t)random64();_flag_k=(uint32_t)random64();_flag_a=(uint32_t)random64();_flag_b=(uint32_t)random64();
}
''')
    allowed=r'''static int computed_float_store(uint32_t address) {
    return address==output_address || address==output_address+4 || address==output_address+8 CHECKPOINT;
}
'''.replace(' CHECKPOINT',' || address==esp+8' if name=='BA2270' else '')
    fixture=fixture.replace(function(fixture,'static int computed_float_store('),allowed)
    fixture=fixture.replace(function(fixture,'static void comparison_contract('),r'''static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;output_address=0x12000;esp=0x18000;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);
    assert(same_snapshot(&expected,&actual,0));
    actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
    actual.st[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[0]=0;
    a=0;b=0x80000000u;memcpy(expected.memory+0x2000,&a,4);memcpy(actual.memory+0x2000,&b,4);
    assert(!same_snapshot(&expected,&actual,0));
    a=0x7FC12345u;b=0xFFC54321u;
    memset(&expected,0,sizeof expected);actual=expected;
    memcpy(expected.memory+0x200C,&a,4);memcpy(actual.memory+0x200C,&b,4);
    assert(!same_snapshot(&expected,&actual,0));
}
''')
    fixture=fixture.replace('particle comparisons',name+' whole-leaf comparisons (8 pointer layouts)')
    return fixture


class AffineCacheTest(unittest.TestCase):
    def test_pinned_whole_leaf_and_exact_scope(self):
        source=SOURCE.read_text(encoding='utf-8')
        region=affine_baseline_region(source)
        self.assertEqual(AFFINE_BASELINE_SHA256,'822cfd41165c13a61906aa3e538df6025ca34f5d2653c8ed1131b717b40d5866')
        self.assertEqual(hashlib.sha256(region.encode()).hexdigest(),AFFINE_BASELINE_SHA256)
        self.assertEqual(region.count('fp_push('),9)
        self.assertEqual(region.count('fp_pop()'),9)
        self.assertEqual(region.count('fp_xch('),1)
        self.assertNotRegex(region,r'\b(goto|return|RECOMP_\w+)\b|^L_')
        transformed=cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(transformed),transformed)
        self.assertEqual(affine_baseline_region(transformed),region)
        self.assertEqual(transformed.count(AFFINE_BEGIN),1)
        self.assertEqual(transformed.count(AFFINE_END),1)
        cached=affine_cached_region(region)
        raw=transformed.replace(cached,region,1)
        self.assertEqual(cache_particle_math_source(raw),transformed)
        self.assertEqual(function(transformed,AFFINE_SYMBOL).replace(cached,region,1),function(raw,AFFINE_SYMBOL))
        self.assertIn('esp += 12;',function(transformed,AFFINE_SYMBOL))

    def test_changed_operations_and_applied_cache_rejected(self):
        source=SOURCE.read_text(encoding='utf-8')
        region=affine_baseline_region(source)
        with self.assertRaises(ValueError):
            affine_cached_region(region.replace('fp_push(','fp_push(0 + ',1))
        transformed=cache_particle_math_source(source)
        cached=affine_cached_region(region)
        poisoned=cached.replace('g_fp_top','g_fp_top_BAD',1)
        self.assertNotEqual(cached,poisoned)
        with self.assertRaises(ValueError):
            cache_particle_math_source(transformed.replace(cached,poisoned,1))

    def test_actual_leaf_complete_state_and_pointer_aliases(self):
        compiler=(TOOLCHAIN / 'bin/clang-cl.exe')
        fixture=affine_fixture()
        for mode in ('precise','strict'):
            with self.subTest(fp=mode):
                compile_probe('affine_'+mode,fixture,{},extra_flags=('/O2','/fp:'+mode,
                    '/clang:-ffp-contract=off','/clang:-fno-strict-aliasing','/clang:-fwrapv'),compiler_override=compiler)


if __name__=='__main__':
    unittest.main()
