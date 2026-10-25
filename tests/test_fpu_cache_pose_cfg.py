"""Execute the pinned two-entry Granny pose CFG, including original yield state."""
import hashlib
from pathlib import Path
import re
import sys
import unittest
import pefile
from test_d3d_lifecycle import function
from test_fpu_cache import HARNESS
from test_static_tls import ROOT,compile_probe
from test_user32_startup import body
sys.path.insert(0,str(ROOT/'tools'))
from fpu_cache import (HELPERS,POSE_SYMBOL,POSE_CFG_BASELINE_SHA256,POSE_CFG_ENTRY,
                       POSE_CFG_BEGIN,POSE_CFG_END,cache_particle_math_source,
                       pose_cfg_baseline_region,pose_cfg_cached_region)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN
SOURCE=ROOT/'generated/granny2-x86/granny2_0008.c'


def pose_cfg_fixture():
    source=SOURCE.read_text(encoding='utf-8')
    forward=pose_cfg_baseline_region(source)
    start=source.index('L_50028D3A:\n')
    slow=source[start:source.index('L_50028D44:\n',start)]
    entry='    if (external_scale_entry) goto L_50028D1A;\n'
    end='L_50028D61:\n    return;\n'
    original=entry+forward+slow+end
    cached=entry+pose_cfg_cached_region(forward)+slow+end
    header=(ROOT/'android/runtime/recomp_types.h').read_text()
    enum_start=header.index('enum {\n    FK_NONE');enum=header[enum_start:header.index('};',enum_start)+2]
    helpers='\n'.join(body(header,'static inline '+s) for s in ('void fp_push_impl(','double fp_pop_impl(','uint32_t recomp_parity8(uint8_t v) {'))
    helpers+='\n'+ '\n'.join(line for line in header.splitlines() if line.startswith(('#define FPU_CMP','#define HI8','#define FK_NARROW','#define CMP_B(','#define CMP_NE','#define CMP_EQ','#define TEST_Z','#define RECOMP_PF')))
    helpers+='\n#define _fpu_cmp void_fpu_cmp\n#define RECOMP_BACKEDGE() record_edge()\n'
    helpers+='static void record_edge(void);\n'
    local=HELPERS.replace(function(HELPERS,'static inline void h5_fpu_cache_xch('),'')
    fixture=HARNESS.replace('/* ACTUAL_FLAG_ENUM */',enum).replace('/* ACTUAL_FPU_HELPERS */',helpers)
    fixture=fixture.replace('#define GPTR(va) (memory+(uint32_t)(va))','#define GPTR(va) (memory+((uint32_t)(va)>=0x50000000u?(uint32_t)(va)-0x50000000u:(uint32_t)(va)))')
    fixture=fixture.replace('static uint8_t memory[','static int external_scale_entry,edge_calls,actual_mode,mutation,allow_weight;\nstatic uint8_t memory[',1)
    fixture=fixture.replace('/* LOCAL_HELPERS */',local).replace('/* ORIGINAL */',original).replace('/* CACHED */',cached)
    p=pefile.PE(str(ROOT/'generated/input/granny2.dll'));image=p.OPTIONAL_HEADER.ImageBase
    constants='\n'.join('MEM32(0x%X)=0x%Xu;'%(a,int.from_bytes(p.get_data(a-image,4),'little')) for a in (0x5004C0D0,0x5004C6D8,0x5004C6D4,0x5004C478,0x5004C6D0,0x5004C6CC))
    fixture=fixture.replace(function(fixture,'static void initialize('),r'''static void initialize(unsigned test,unsigned rounding) {
        input_family=test<256?0:test<384?1:2;
        for(unsigned i=0;i<0x20000;i+=4) MEM32(0x10000+i)=float_bits(test+i);
        for(unsigned i=0;i<8;++i) {
            uint64_t bits=random64();
            if(i<4) bits=(uint64_t[]){0,0x8000000000000000ull,0x7FF0000000000000ull,0x7FF8123456789ABCull}[(test+i)%4];
            memcpy(&g_st[i],&bits,8);g_st_i64[i]=(int64_t)random64();
        }
        g_fp_top=(int)(test%33)-16;void_fpu_cmp=(int)(random64()&0x7FFFFu);g_fpu_cw=(uint16_t)(0x037F|(rounding<<10));
        eax=(uint32_t)random64();ecx=(uint32_t)random64();edx=(uint32_t)random64();ebx=0x12000;
        esp=0x18000;ebp=ebx-0x14;esi=(uint32_t)random64();edi=(uint32_t)random64();
        switch(test%8) {
        case 1:ebp=ebx-8;break;
        case 2:ebp=ebx+0x34;break;
        case 3:esp=ebx-0x18;break;
        case 4:esp=ebx-0xC;break;
        case 5:ebp=esp+0x1C;break;
        case 6:esp=ebx+0x10;break;
        case 7:ebp=ebx+4;break;
        }
        MEM32(ebx-0x10)=test&1;
        if(test%3==0) MEM32(ebp)=0x3F800000u;
        if(test<384 && test%8!=7) {
            for(unsigned i=1;i<=4;++i) MEM32(ebx+4*i)=0;
            if(test%8==0) MEM32(ebx+4)=0x3F800000u;
            if(test%8==1) for(unsigned i=1;i<=4;++i) MEM32(ebx+4*i)=0x3F000000u;
            if(test%8==2) *(float*)ADDR(ebx+4)=0.95f;
            if(test%8==3) *(float*)ADDR(ebx+4)=1.04f;
            if(test%8==4) *(float*)ADDR(ebx+4)=0.94f;
            if(test%8==5) *(float*)ADDR(ebx+4)=1.05f;
        }
        _cf=(uint32_t)random64();_flag_k=(uint32_t)random64();_flag_a=(uint32_t)random64();_flag_b=(uint32_t)random64();
        external_scale_entry=(test%11==0);edge_calls=0;actual_mode=0;mutation=(test%3);
        allow_weight=!external_scale_entry && (MEM32(ebx-0x10)!=1 || MEM32(ebp)!=0x3F800000u);
        /* ORIGINAL_CONSTANTS */
    }
    '''.replace('/* ORIGINAL_CONSTANTS */',constants))
    fixture=fixture.replace(function(fixture,'static int computed_float_store('),r'''static int computed_float_store(uint32_t address) {
        static const int offsets[]={-8,-4,0,20,24,28,32,36,40,44,48,52};
        if(address==esp+0x1C) return !external_scale_entry;
        if(address==ebx+4 || address==ebx+8 || address==ebx+12 || address==ebx+16) return 1;
        for(unsigned i=0;i<sizeof offsets/sizeof *offsets;++i)
            if(address==(uint32_t)(ebx+offsets[i])) return allow_weight;
        return 0;
    }
    ''')
    fixture=fixture.replace(function(fixture,'static void comparison_contract('),r'''static snapshot expected_edge,actual_edge;
    static void record_edge(void) {
        assert(++edge_calls==1);
        take(actual_mode?&actual_edge:&expected_edge);
        if(mutation==1) { g_st[0]=0.5;g_st_i64[0]=0x123456789ABCDELL; }
        if(mutation==2) { MEM32(ebx+8)=0x3F800000u;g_fpu_cw^=0x0C00u; }
    }
    static void comparison_contract(void) {
        memset(&expected,0,sizeof expected);actual=expected;ebx=0x12000;esp=0x18000;
        uint32_t a=0x7FC12345u,b=0xFFC54321u;
        memcpy(expected.memory+0x2004,&a,4);memcpy(actual.memory+0x2004,&b,4);
        assert(same_snapshot(&expected,&actual,0));
        actual.shadow[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.shadow[0]=0;
        actual.st[0]=1;assert(!same_snapshot(&expected,&actual,0));actual.st[0]=0;
        a=0;b=0x80000000u;memcpy(expected.memory+0x2004,&a,4);memcpy(actual.memory+0x2004,&b,4);
        assert(!same_snapshot(&expected,&actual,0));
        a=0x7FC12345u;b=0xFFC54321u;
        memcpy(expected.memory+0x4000,&a,4);memcpy(actual.memory+0x4000,&b,4);
        assert(!same_snapshot(&expected,&actual,0));
    }
    ''')
    fixture=fixture.replace('restore(&entry);cached();take(&actual);',r'''int expected_calls=edge_calls;edge_calls=0;actual_mode=1;
            restore(&entry);cached();take(&actual);
            if(edge_calls!=expected_calls || (edge_calls && !same_snapshot(&expected_edge,&actual_edge,0))) {
                fprintf(stderr,"Yield boundary mismatch case=%u rc=%u calls=%d/%d\n",test,rc,edge_calls,expected_calls);return 2;
            }
    ''')
    fixture=fixture.replace('unsigned cases=0;', 'unsigned cases=0,slow_cases=0,fast_cases=0,external_cases=0,weight_cases=0;')
    fixture=fixture.replace('original();take(&expected);', 'original();take(&expected);if(external_scale_entry)++external_cases;else if(edge_calls)++slow_cases;else ++fast_cases;if(allow_weight)++weight_cases;')
    fixture=fixture.replace('printf("PASS %u particle', 'printf("Coverage: fast=%u sqrt_yield=%u external_scale=%u weight=%u\\n",fast_cases,slow_cases,external_cases,weight_cases);\n    printf("PASS %u particle')
    fixture=fixture.replace('particle comparisons','Granny28B90 two-entry CFG comparisons (8 alias layouts, yield snapshot/mutation)')
    return fixture


class PoseCFGCacheTest(unittest.TestCase):
    def test_pinned_cfg_and_original_boundary_preservation(self):
        source=SOURCE.read_text(encoding='utf-8')
        region=pose_cfg_baseline_region(source)
        self.assertEqual(POSE_CFG_BASELINE_SHA256,'ce3c977e9857e248842e15eb6a493bd38380aaf4a70e116bbfba8e803ea772e8')
        self.assertEqual(hashlib.sha256(region.encode()).hexdigest(),POSE_CFG_BASELINE_SHA256)
        self.assertEqual(region.count('fp_push('),27)
        self.assertEqual(region.count('fp_pop()'),27)
        self.assertNotRegex(region,r'RECOMP_CALL|RECOMP_ICALL|RECOMP_BACKEDGE|\breturn\b')
        self.assertEqual(set(re.findall(r'goto (L_[^; ]+)',region)),
                         {'L_50028C43','L_50028CA8','L_50028D3A','L_50028D61'})
        transformed=cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(transformed),transformed)
        self.assertEqual(pose_cfg_baseline_region(transformed),region)
        self.assertEqual(transformed.count(POSE_CFG_BEGIN),1)
        self.assertEqual(transformed.count(POSE_CFG_END),1)
        cached=pose_cfg_cached_region(region)
        raw=transformed.replace(cached,region,1)
        self.assertEqual(cache_particle_math_source(raw),transformed)
        before=function(raw,POSE_SYMBOL)
        after=function(transformed,POSE_SYMBOL)
        self.assertEqual(after.replace(cached,region,1),before)
        self.assertEqual(after.count('RECOMP_BACKEDGE();'),2)
        self.assertEqual(after.count('RECOMP_CALL(sub_50028950)'),1)
        self.assertEqual(after.count('RECOMP_CALL(sub_500293E0)'),2)
        a=before.index('L_50028D3A:');b=before.index('L_50028D44:',a)
        self.assertIn(before[a:b],after)
        self.assertIn(POSE_CFG_ENTRY+cached,after)

    def test_original_or_applied_body_mutation_is_rejected(self):
        source=SOURCE.read_text(encoding='utf-8')
        region=pose_cfg_baseline_region(source)
        with self.assertRaises(ValueError):
            pose_cfg_cached_region(region.replace('fp_push(','fp_push(0 + ',1))
        transformed=cache_particle_math_source(source)
        cached=pose_cfg_cached_region(region)
        poisoned=cached.replace('g_fp_top','g_fp_top_BAD',1)
        self.assertNotEqual(cached,poisoned)
        with self.assertRaises(ValueError):
            cache_particle_math_source(transformed.replace(cached,poisoned,1))

    def test_actual_cfg_all_state_aliases_and_yield_reentry(self):
        compiler=(TOOLCHAIN / 'bin/clang-cl.exe')
        fixture=pose_cfg_fixture()
        for mode in ('precise','strict'):
            with self.subTest(fp=mode):
                compile_probe('pose_cfg_'+mode,fixture,{},extra_flags=('/O2','/fp:'+mode,
                    '/clang:-ffp-contract=off','/clang:-fno-strict-aliasing','/clang:-fwrapv',
                    '/clang:-Wno-unused-label'),compiler_override=compiler)


if __name__=='__main__':
    unittest.main()
