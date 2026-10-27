"""Differentially execute the real sampled particle block and scoped FPU cache."""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body
sys.path.insert(0,str(ROOT/"tools"))
from fpu_cache import (BASELINE_SHA256, BEGIN, END, HELPERS, SYMBOL,
                       baseline_region, cached_region, cache_particle_math_source,
                       GRANNY_BASELINE_SHA256, GRANNY_BEGIN, GRANNY_END,
                       GRANNY_SYMBOL, granny_baseline_region, granny_cached_region)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import NDK

HARNESS = r'''
#include <assert.h>
#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t memory[0x1100000];
#define GPTR(va) (memory+(uint32_t)(va))
#define ADDR(va) GPTR(va)
#define MEM32(va) (*(uint32_t *)GPTR(va))
#define PUSH32(sp,val) do { (sp)-=4; MEM32(sp)=(uint32_t)(val); } while(0)
static uint32_t eax,ecx,edx,ebx,esp,ebp,esi,edi;
static uint32_t _cf,_flag_k,_flag_a,_flag_b;
static double g_st[8];
static int64_t g_st_i64[8];
static int g_fp_top,void_fpu_cmp;
static uint16_t g_fpu_cw;
#define _st g_st
#define _fp_top g_fp_top
#define _fpu_cw g_fpu_cw
/* ACTUAL_FLAG_ENUM */
#define RECOMP_EFLAGS_FIXED 0x00000202u
/* ACTUAL_FPU_HELPERS */
#define fp_push(v) fp_push_impl(_st,&_fp_top,(v))
#define fp_pop() fp_pop_impl(_st,&_fp_top)
#define fp_to_int(v) fp_round_i32((v),_fpu_cw)
#define fp_xch(i) do { double _t=_st[0]; _st[0]=_st[i]; _st[i]=_t; \
    int64_t _ti=g_st_i64[0];g_st_i64[0]=g_st_i64[i];g_st_i64[i]=_ti; } while(0)
/* LOCAL_HELPERS */
static void original(void) {
/* ORIGINAL */
}
static void cached(void) {
/* CACHED */
}
typedef struct {
    uint64_t st[8];int64_t shadow[8];int top,cmp;uint16_t cw;
    uint32_t regs[8],flags[4];uint8_t memory[0x20000];
} snapshot;
static snapshot entry,expected,actual;
static void take(snapshot *s) {
    memset(s,0,sizeof *s);memcpy(s->st,g_st,sizeof g_st);memcpy(s->shadow,g_st_i64,sizeof g_st_i64);
    s->top=g_fp_top;s->cmp=void_fpu_cmp;s->cw=g_fpu_cw;
    const uint32_t regs[]={eax,ecx,edx,ebx,esp,ebp,esi,edi};memcpy(s->regs,regs,sizeof regs);
    const uint32_t flags[]={_cf,_flag_k,_flag_a,_flag_b};memcpy(s->flags,flags,sizeof flags);
    memcpy(s->memory,GPTR(0x10000),sizeof s->memory);
}
static void restore(const snapshot *s) {
    memcpy(g_st,s->st,sizeof g_st);memcpy(g_st_i64,s->shadow,sizeof g_st_i64);
    g_fp_top=s->top;void_fpu_cmp=s->cmp;g_fpu_cw=s->cw;
    eax=s->regs[0];ecx=s->regs[1];edx=s->regs[2];ebx=s->regs[3];
    esp=s->regs[4];ebp=s->regs[5];esi=s->regs[6];edi=s->regs[7];
    _cf=s->flags[0];_flag_k=s->flags[1];_flag_a=s->flags[2];_flag_b=s->flags[3];
    memcpy(GPTR(0x10000),s->memory,sizeof s->memory);
}
static uint64_t random_state=0xC4A53871DE46B209ull;
static int input_family;
static uint64_t random64(void) {
    random_state^=random_state<<13;random_state^=random_state>>7;random_state^=random_state<<17;return random_state;
}
static uint32_t float_bits(unsigned i) {
    static const uint32_t edge[]={0,0x80000000,0x3F800000,0xBF800000,0x7F800000,0xFF800000,
        0x7FC12345,0xFFC54321,0x7FA12345,1,0x80000001,0x7F7FFFFF,0xFF7FFFFF,0x00800000,0x3F000000};
    if(input_family==0) {
        uint32_t r=(uint32_t)random64();
        return (r&0x807FFFFFu)|((110u+(r>>24)%31u)<<23);
    }
    if(input_family==1) {
        uint32_t r=(uint32_t)random64();
        if((r&0x7F800000u)==0x7F800000u) r^=0x00800000u;
        return r;
    }
    return (i&1)?(uint32_t)random64():edge[(i/2)%(sizeof edge/sizeof *edge)];
}
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
    esp=0x18000;ebp=0x14000;esi=(uint32_t)random64();edi=(uint32_t)random64();
    _cf=(uint32_t)random64();_flag_k=(uint32_t)random64();_flag_a=(uint32_t)random64();_flag_b=(uint32_t)random64();
    MEM32(esp+0x34)=12u*(1u+test%32);MEM32(esp+0x108)=0x16000;MEM32(0x16000)=0x16400;
    MEM32(esp+0xBC)=0x17000;MEM32(0x10C4C68)=0x20000;
    for(unsigned i=0;i<768;++i) {MEM32(0x10C3A58+4*i)=float_bits(test+i);MEM32(0x10C3C58+4*i)=float_bits(test+i+17);}
    for(unsigned i=0;i<8;++i) MEM32(0xF78BD4+4*i)=float_bits(test+i);
    /* ORIGINAL_CONSTANTS */
}
static unsigned nan_payload_differences;
static int computed_float_store(uint32_t address) {
    static const int offsets[]={/* COMPUTED_FLOAT_STORE_OFFSETS */};
    for(unsigned i=0;i<sizeof offsets/sizeof *offsets;++i)
        if(address==(uint32_t)(0x18000+offsets[i])) return 1;
    return 0;
}
static int nan32(uint32_t bits) {
    return (bits&0x7F800000u)==0x7F800000u && (bits&0x007FFFFFu)!=0;
}
static int same_snapshot(const snapshot *a,const snapshot *b,int count) {
    /* Only arithmetic float32 stores can choose a computed NaN payload.
       All FPU cells, shadows, integers and raw-copy memory stay bitwise. */
    if(memcmp(a,b,offsetof(snapshot,memory))) return 0;
    unsigned variants=0;
    for(unsigned i=0;i<sizeof a->memory;i+=4) {
        uint32_t x,y;memcpy(&x,a->memory+i,4);memcpy(&y,b->memory+i,4);
        if(x==y) continue;
        if(computed_float_store(0x10000+i) && nan32(x) && nan32(y)) ++variants;
        else return 0;
    }
    if(count) nan_payload_differences+=variants;
    return 1;
}
static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;
    uint32_t a=0x7FC12345u,b=0xFFC54321u;
    memcpy(expected.memory+0x8010,&a,4);memcpy(actual.memory+0x8010,&b,4);
    assert(same_snapshot(&expected,&actual,0));
    for(unsigned check=0;check<7;++check) {
        memset(&expected,0,sizeof expected);actual=expected;
        if(check==0) { /* The position copy at +4C remains raw bits. */
            memcpy(expected.memory+0x804C,&a,4);memcpy(actual.memory+0x804C,&b,4);
        } else if(check==1) {expected.st[0]=0x7FF8123456789ABCull;actual.st[0]=0xFFF876543210ABCDull;}
        else if(check==2) {a=0x7F800000u;b=0xFF800000u;}
        else if(check==3) {a=0;b=0x80000000u;}
        else if(check==4) {a=0x3F800000u;b=0x3F800001u;}
        else if(check==5) {expected.shadow[0]=1;}
        else {expected.flags[2]=1;}
        if(check>=2 && check<=4) {memcpy(expected.memory+0x8010,&a,4);memcpy(actual.memory+0x8010,&b,4);}
        assert(!same_snapshot(&expected,&actual,0));
    }
}
int main(void) {
    assert(fesetround(FE_TONEAREST)==0);
    comparison_contract();
    unsigned cases=0;
    for(unsigned rc=0;rc<4;++rc) for(unsigned test=0;test<512;++test) {
        initialize(test,rc);take(&entry);original();take(&expected);
        restore(&entry);cached();take(&actual);
        if(!same_snapshot(&expected,&actual,1)) {
            const uint8_t *a=(const uint8_t *)&expected,*b=(const uint8_t *)&actual;
            for(size_t i=0;i<sizeof expected;++i) if(a[i]!=b[i]) {
                fprintf(stderr,"Mismatch case=%u rc=%u snapshot_byte=%zu expected=%02X actual=%02X\n",test,rc,i,a[i],b[i]);break;
            }
            for(unsigned i=0;i<sizeof expected.memory;i+=4) {
                uint32_t x,y;memcpy(&x,expected.memory+i,4);memcpy(&y,actual.memory+i,4);
                if(x!=y) fprintf(stderr,"memory[%05X] expected=%08X actual=%08X\n",0x10000+i,x,y);
            }
            return 1;
        }
        ++cases;
    }
    printf("PASS %u particle comparisons: all FPU/shadow/depth/CW/compare/GPR/flags/raw-memory bits exact; computed float32 results exact except %u NaN payload/sign variants; all4RC, bounded/large finite/NaN/Inf/signedzero/subnormals\n",cases,nan_payload_differences);
    return 0;
}
'''


class FPUCacheTest(unittest.TestCase):
    def source(self):
        return (ROOT/"generated/game-x86/game_0622.c").read_text(encoding="utf-8")

    def test_pinned_region_and_idempotent_scope(self):
        source=self.source();base=baseline_region(source)
        self.assertEqual(hashlib.sha256(base.encode()).hexdigest(),BASELINE_SHA256)
        self.assertEqual(base.count("fp_push("),56);self.assertEqual(base.count("fp_pop()"),56)
        changed=cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(changed),changed)
        self.assertEqual(baseline_region(changed),base)
        start=changed.index(SYMBOL);end=changed.find("\nvoid sub_",start+1)
        self.assertEqual(changed[start:end].count(BEGIN),1)
        self.assertEqual(changed.count(BEGIN),1) # Overlapping alias bodies are untouched.

    def test_changed_baseline_rejected(self):
        base=baseline_region(self.source())
        with self.assertRaises(ValueError): cached_region(base.replace("0xC8","0xC4",1))

    def test_actual_optimized_full_state(self):
        import pefile
        source=self.source();base=baseline_region(source)
        header=(ROOT/"android/runtime/recomp_types.h").read_text(encoding="utf-8")
        enum=header[header.index("enum {\n    FK_NONE"):header.index("};",header.index("enum {\n    FK_NONE"))+2]
        helpers="\n".join(body(header,"static inline "+signature) for signature in
            ["void fp_push_impl(","double fp_pop_impl(","double fp_round_cw(","double fp_round_i32(",
             "uint32_t recomp_parity8(uint8_t v) {","uint32_t recomp_flags_pack("])
        p=pefile.PE(str(ROOT/"generated/input/H5_Game.exe"));image=p.OPTIONAL_HEADER.ImageBase
        constants="\n".join("MEM32(0x%X)=0x%Xu;"%(a,int.from_bytes(p.get_data(a-image,4),"little"))
                            for a in [0xE87918,0xE0AB70,0xE87914])
        fixture=HARNESS.replace("/* ACTUAL_FLAG_ENUM */",enum).replace("/* ACTUAL_FPU_HELPERS */",helpers)
        fixture=fixture.replace("/* LOCAL_HELPERS */",HELPERS).replace("/* ORIGINAL */",base).replace("/* CACHED */",cached_region(base))
        fixture=fixture.replace("/* ORIGINAL_CONSTANTS */",constants)
        # Recover exact float-store addresses, accounting for the three PUSHes.
        delta=0;stores=set()
        for line in base.splitlines():
            if "PUSH32(esp," in line: delta-=4
            match=re.search(r"\*\(float\*\)ADDR\(esp(?: \+ (0x[0-9A-F]+))?\) = _v",line)
            if match: stores.add(delta+int(match[1] or "0",0))
        self.assertEqual(stores,{-4,0x10,0x1C,0x20,0x24,0x2C,0x44,0x60,*range(0xD4,0x104,4)})
        fixture=fixture.replace("/* COMPUTED_FLOAT_STORE_OFFSETS */",",".join(str(i) for i in sorted(stores)))
        ndk=NDK
        for mode in ("precise","strict"):
            with self.subTest(fp=mode):
                compile_probe("fpu_cache",fixture,{},extra_flags=("/O2","/fp:"+mode,"/clang:-ffp-contract=off",
                              "/clang:-fno-strict-aliasing","/clang:-fwrapv"),
                              compiler_override=ndk/"toolchains/llvm/prebuilt/windows-x86_64/bin/clang-cl.exe")


GRANNY_HARNESS = r'''
#include <assert.h>
#include <fenv.h>
#include <math.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[0x20000],constants[0x500];
static void *guest(uint32_t va) {
    if(va>=0x10000 && va<0x30000) return memory+va-0x10000;
    assert(va>=0x5004C000 && va<0x5004C500);return constants+va-0x5004C000;
}
#define ADDR(va) guest((uint32_t)(va))
#define MEM32(va) (*(uint32_t *)ADDR(va))
#define PUSH32(sp,val) do {(sp)-=4;MEM32(sp)=(uint32_t)(val);} while(0)
#define POP32_VAL(sp) ((sp)+=4,MEM32((sp)-4))
static uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
static uint32_t g_flag_cf,g_flag_k,g_flag_a,g_flag_b,g_cur_func;
static double g_st[8];static int64_t g_st_i64[8];
static int g_fp_top,void_fpu_cmp;static uint16_t g_fpu_cw;
#define _st g_st
#define _fp_top g_fp_top
/* ACTUAL_REGISTER_MACROS */
/* ACTUAL_FPU_HELPERS */
#define fp_push(v) fp_push_impl(_st,&_fp_top,(v))
#define fp_pop() fp_pop_impl(_st,&_fp_top)
#define fp_xch(i) do {double t=_st[0];_st[0]=_st[i];_st[i]=t; \
    int64_t ti=g_st_i64[0];g_st_i64[0]=g_st_i64[i];g_st_i64[i]=ti;} while(0)
/* LOCAL_HELPERS */
/* ORIGINAL_FUNCTION */
/* CACHED_FUNCTION */
typedef struct {
    uint64_t st[8];int64_t shadow[8];int top,cmp;uint16_t cw;
    uint32_t regs[8],flags[4],current;uint8_t bytes[sizeof memory],constant_bytes[sizeof constants];
} snapshot;
static snapshot entry,expected,actual;
static uint32_t output;
static void take(snapshot *s) {
    memset(s,0,sizeof *s);memcpy(s->st,g_st,sizeof g_st);memcpy(s->shadow,g_st_i64,sizeof g_st_i64);
    s->top=g_fp_top;s->cmp=void_fpu_cmp;s->cw=g_fpu_cw;s->current=g_cur_func;
    const uint32_t r[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};memcpy(s->regs,r,sizeof r);
    const uint32_t f[]={g_flag_cf,g_flag_k,g_flag_a,g_flag_b};memcpy(s->flags,f,sizeof f);
    memcpy(s->bytes,memory,sizeof memory);memcpy(s->constant_bytes,constants,sizeof constants);
}
static void restore(const snapshot *s) {
    memcpy(g_st,s->st,sizeof g_st);memcpy(g_st_i64,s->shadow,sizeof g_st_i64);
    g_fp_top=s->top;void_fpu_cmp=s->cmp;g_fpu_cw=s->cw;g_cur_func=s->current;
    g_eax=s->regs[0];g_ecx=s->regs[1];g_edx=s->regs[2];g_ebx=s->regs[3];
    g_esp=s->regs[4];g_ebp=s->regs[5];g_esi=s->regs[6];g_edi=s->regs[7];
    g_flag_cf=s->flags[0];g_flag_k=s->flags[1];g_flag_a=s->flags[2];g_flag_b=s->flags[3];
    memcpy(memory,s->bytes,sizeof memory);memcpy(constants,s->constant_bytes,sizeof constants);
}
static uint64_t random_state=0x598ADD7F023E1C41ull;
static uint64_t random64(void) {
    random_state^=random_state<<13;random_state^=random_state>>7;random_state^=random_state<<17;return random_state;
}
static unsigned nan_variants;
static int nan32(uint32_t v) {return (v&0x7F800000u)==0x7F800000u && (v&0x7FFFFFu)!=0;}
static int same(const snapshot *a,const snapshot *b) {
    if(memcmp(a,b,offsetof(snapshot,bytes)) || memcmp(a->constant_bytes,b->constant_bytes,sizeof constants)) return 0;
    for(uint32_t i=0;i<sizeof memory;i+=4) {
        uint32_t x,y;memcpy(&x,a->bytes+i,4);memcpy(&y,b->bytes+i,4);if(x==y) continue;
        uint32_t va=0x10000+i;
        int computed=(va>=output && va<output+16) || va==0x17FFC || va==0x18004 || va==0x1800C;
        if(computed && nan32(x) && nan32(y)) ++nan_variants;else return 0;
    }
    return 1;
}
static void comparison_contract(void) {
    memset(&expected,0,sizeof expected);actual=expected;output=0x14000;
    uint32_t x=0x7FC12345u,y=0xFFC54321u;
    memcpy(expected.bytes+0x4000,&x,4);memcpy(actual.bytes+0x4000,&y,4);assert(same(&expected,&actual));
    for(unsigned i=0;i<10;++i) {
        memset(&expected,0,sizeof expected);actual=expected;
        if(i==0) {memcpy(expected.bytes+0x3000,&x,4);memcpy(actual.bytes+0x3000,&y,4);}
        if(i==1) {expected.st[0]=0x7FF8123456789ABCull;actual.st[0]=0xFFF8123456789ABCull;}
        if(i==2) expected.shadow[7]=1;
        if(i==3) expected.top=1;
        if(i==4) expected.cmp=1;
        if(i==5) expected.cw=1;
        if(i==6) expected.regs[7]=1;
        if(i==7) expected.flags[3]=1;
        if(i==8) {uint32_t z=0x80000000u;memcpy(expected.bytes+0x4000,&z,4);}
        if(i==9) expected.constant_bytes[0]=1;
        assert(!same(&expected,&actual));
    }
    nan_variants=0;
}
static void initialize(unsigned test,unsigned rc) {
    for(unsigned i=0;i<sizeof memory;i+=4) MEM32(0x10000+i)=(uint32_t)random64();
    for(unsigned i=0;i<8;++i) {uint64_t raw=random64();memcpy(&g_st[i],&raw,8);g_st_i64[i]=(int64_t)random64();}
    g_fp_top=(int)(test%33)-16;void_fpu_cmp=(int)random64();g_fpu_cw=(uint16_t)(0x037F|(rc<<10));
    g_eax=(uint32_t)random64();g_ecx=(uint32_t)random64();g_edx=(uint32_t)random64();g_ebx=(uint32_t)random64();
    g_esp=0x18000;g_ebp=(uint32_t)random64();g_esi=(uint32_t)random64();g_edi=(uint32_t)random64();
    g_flag_cf=(uint32_t)random64();g_flag_k=(uint32_t)random64();g_flag_a=(uint32_t)random64();g_flag_b=(uint32_t)random64();g_cur_func=0x12345678;
    static const uint32_t aliases[]={0x14000,0x13000,0x13004,0x13010,0x13020,0x12008,0x1200C,0x12010,0x18000};
    output=aliases[(test/16)%(sizeof aliases/sizeof *aliases)];
    MEM32(0x18004)=0x12010;MEM32(0x18008)=0x13020;MEM32(0x18010)=output;
    /* Random strictly ordered knot times and bounded coefficients represent valid animation input. */
    float start=(float)((int)(random64()%2048)-1024)/8.0f;
    float step=(float)(1+random64()%128)/16.0f;
    const float t[]={start,start+step,start+2*step,start+3*step};
    memcpy(ADDR(0x12008),t,sizeof t);float time=start+(float)(test%49)*step/16.0f;memcpy(ADDR(0x1800C),&time,4);
    for(unsigned i=0;i<12;++i) {float f=(float)((int)(random64()%8192)-4096)/1024.0f;memcpy(ADDR(0x13000+4*i),&f,4);}
    static const uint32_t edges[]={0,0x80000000u,0x3F000000u,0x3FC00000u,0x40200000u,0x7F800000u,0xFF800000u,
        0x7FC12345u,0xFFC54321u,0x7FA12345u,1,0x80000001u,0x7F7FFFFFu,0x00800000u};
    if(test>=256) {
        for(unsigned i=0;i<12;++i) MEM32(0x13000+4*i)=edges[(test+i)%(sizeof edges/sizeof *edges)];
        MEM32(0x1800C)=edges[test%(sizeof edges/sizeof *edges)];
        if(test&1) for(unsigned i=0;i<4;++i) MEM32(0x12008+4*i)=edges[(test+i)%(sizeof edges/sizeof *edges)];
        else { /* Equal knots exercise every existing zero-denominator branch. */
            uint32_t tie=edges[test%(sizeof edges/sizeof *edges)];
            for(unsigned i=0;i<4;++i) MEM32(0x12008+4*i)=tie;
        }
    }
    /* ORIGINAL_CONSTANTS */
}
int main(void) {
    comparison_contract();unsigned count=0;
    const int rounds[]={FE_TONEAREST,FE_DOWNWARD,FE_UPWARD,FE_TOWARDZERO};
    for(unsigned host_rc=0;host_rc<4;++host_rc) {
        assert(fesetround(rounds[host_rc])==0);
        for(unsigned rc=0;rc<4;++rc) for(unsigned test=0;test<512;++test) {
            initialize(test,rc);take(&entry);original();take(&expected);restore(&entry);cached();take(&actual);
            if(!same(&expected,&actual)) {
                const uint8_t *a=(const uint8_t *)&expected,*b=(const uint8_t *)&actual;
                for(size_t i=0;i<sizeof expected;++i) if(a[i]!=b[i]) {
                    fprintf(stderr,"Granny mismatch test=%u guestRC=%u hostRC=%u byte=%zu expected=%02X actual=%02X\n",test,rc,host_rc,i,a[i],b[i]);break;
                }
                return 1;
            }
            ++count;
        }
    }
    printf("PASS %u Granny full-function comparisons: exact GPR/flags/x878/shadows8/depth/CW/compare/raw writes, aliases, valid knots/ties/zero/NaN/Inf/subnormal, 4guestRC x4hostRC; computed float32 NaN variants=%u\n",count,nan_variants);
    return 0;
}
'''


class GrannyFPUCacheTest(unittest.TestCase):
    def source(self):
        return (ROOT/"generated/granny2-x86/granny2_0003.c").read_text(encoding="utf-8")

    def test_pinned_idempotent_and_finalizer_scope(self):
        source=self.source();base=granny_baseline_region(source)
        self.assertEqual(hashlib.sha256(base.encode()).hexdigest(),GRANNY_BASELINE_SHA256)
        self.assertEqual(base.count("fp_push("),29);self.assertEqual(base.count("fp_pop()"),29)
        changed=cache_particle_math_source(source)
        self.assertEqual(cache_particle_math_source(changed),changed)
        self.assertEqual(granny_baseline_region(changed),base)
        self.assertEqual(changed.count(GRANNY_BEGIN),1)
        self.assertEqual(changed.count(GRANNY_END),1)
        self.assertEqual(changed.replace(HELPERS, "").replace(granny_cached_region(base),base),
                         source.replace(HELPERS, "").replace(granny_cached_region(base),base))
        # The existing finalizer calls the backwards-compatible transform for every module.
        finalizer=(ROOT/"tools/lift_homm5.py").read_text(encoding="utf-8")
        self.assertIn("fixed = cache_particle_math_source(fixed)",finalizer)
        dispatch=(ROOT/"generated/zlibwapi-x86/recomp_dispatch.c").read_text(encoding="utf-8")
        addresses=[int(x,16) for x in re.findall(r"\{0x([0-9A-F]+)u,",dispatch)]
        self.assertEqual([a for a in addresses if 0x50011890<=a<=0x500119A1],[0x50011890])
        with self.assertRaises(ValueError):
            cache_particle_math_source(changed.replace("g_fp_top = _h5_fp.top;","g_fp_top = 0;",1))

    def test_changed_or_unreviewed_baseline_rejected(self):
        base=granny_baseline_region(self.source())
        with self.assertRaises(ValueError): granny_cached_region(base.replace("_st[2] / _v","_st[1] / _v",1))
        with self.assertRaises(ValueError): granny_cached_region(base+"    RECOMP_CALL(sub_50000000);\n")

    def test_actual_lift_finalizer_reapplies_all_modules(self):
        import fpu_cache as cache
        text=(ROOT/"tools/lift_homm5.py").read_text(encoding="utf-8")
        namespace={"re":re,"json":json,"cache_particle_math_source":cache_particle_math_source,"EDITION":"toe"}
        function=next(node for node in ast.parse(text).body if isinstance(node,ast.FunctionDef) and node.name=="finalize_sources")
        exec(ast.get_source_segment(text,function),namespace)
        cases=[("granny2-x86/granny2_0003.c",[(granny_baseline_region,granny_cached_region)]),
               ("game-x86/game_0308.c",[(cache.matrix_baseline_region,cache.matrix_cached_region)]),
               ("game-x86/game_0700.c",[(cache.inverse_baseline_region,cache.inverse_cached_region),
                                        (cache.norm_guard_baseline_region,cache.norm_guard_cached_region),
                                        (cache.plane_baseline_region,cache.plane_cached_region)]),
               ("game-x86/game_0041.c",[(cache.affine_baseline_region,cache.affine_cached_region)]),
               ("game-x86/game_0595.c",[(cache.guarded_vector_baseline_region,cache.guarded_vector_cached_region)]),
               ("granny2-x86/granny2_0008.c",[(cache.pose_accum_baseline_region,cache.pose_accum_cached_region),
                                              (cache.pose_cfg_baseline_region,cache.pose_cfg_cached_region)]),
               ("granny2-x86/granny2_0004.c",[(lambda s:cache.scoped_baseline_region(s,"search127c1"),
                                              lambda r:cache.scoped_cached_region(r,"search127c1"))]),
               ("game-x86/game_0664.c",[(lambda s,n=n:cache.scoped_baseline_region(s,n),
                                        lambda r,n=n:cache.scoped_cached_region(r,n))
                                       for n in ("projectc866f7","edgec867e9")])]
        with tempfile.TemporaryDirectory(prefix="homm5-fpu-finalizer-") as directory:
            directory=Path(directory);expected={}
            for relative,regions in cases:
                raw=(ROOT/"generated"/relative).read_text(encoding="utf-8")
                for baseline,transform in regions:
                    region=baseline(raw);raw=raw.replace(transform(region),region)
                raw=raw.replace(HELPERS,"").replace(cache.NORM_GUARD_HELPER,"")
                path=directory/Path(relative).name;path.write_text(raw,encoding="utf-8")
                expected[path.name]=cache_particle_math_source(raw)
            for _ in range(2):
                namespace["finalize_sources"](directory,list(expected))
                for name,result in expected.items():
                    self.assertEqual((directory/name).read_text(encoding="utf-8"),result)
                    self.assertEqual(result.count(HELPERS),1)
                    self.assertLess(result.index(HELPERS),result.index("H5_FPU_CACHE_BEGIN"))

    def test_actual_full_function_and_abi(self):
        import pefile
        source=self.source();base=granny_baseline_region(source)
        function=source[source.index(GRANNY_SYMBOL):source.index("\nvoid sub_",source.index(GRANNY_SYMBOL)+1)]
        if GRANNY_BEGIN in function: function=function.replace(granny_cached_region(base),base)
        original=function.replace("sub_50011890", "original",1)
        cached=function.replace(base,granny_cached_region(base),1).replace("sub_50011890", "cached",1)
        header=(ROOT/"android/runtime/recomp_types.h").read_text(encoding="utf-8")
        macros=[]
        for name in ("RECOMP_FLAGS_OUT()","RECOMP_FLAGS_IN()","RECOMP_REGS_LOCALS","RECOMP_REGS_OUT()","RECOMP_BACKEDGE_OUT()"):
            macros.append(next(line for line in header.splitlines() if line.startswith("#define "+name+" ")))
        for register in ("eax","ecx","edx","ebx","esp","ebp","esi","edi"):
            macros.append("#define %s l_%s"%(register,register))
        macros += ["#define RECOMP_XMM_OUT() ((void)0)","#define RECOMP_ENTER(va) (g_cur_func=(va),RECOMP_FLAGS_IN())"]
        enum=header[header.index("enum {\n    FK_NONE"):header.index("};",header.index("enum {\n    FK_NONE"))+2]
        helpers="\n".join(body(header,"static inline "+s) for s in ("void fp_push_impl(","double fp_pop_impl("))
        pe=pefile.PE(str(ROOT/"generated/input/granny2.dll"));image=pe.OPTIONAL_HEADER.ImageBase
        constants="\n".join("MEM32(0x%X)=0x%Xu;"%(a,int.from_bytes(pe.get_data(a-image,4),"little"))
                            for a in (0x5004C0D0,0x5004C478,0x5004C1D0))
        fixture=GRANNY_HARNESS.replace("/* ACTUAL_REGISTER_MACROS */",enum+"\n"+"\n".join(macros))
        fixture=fixture.replace("/* ACTUAL_FPU_HELPERS */",helpers).replace("/* LOCAL_HELPERS */",HELPERS)
        fixture=fixture.replace("/* ORIGINAL_FUNCTION */",original).replace("/* CACHED_FUNCTION */",cached)
        fixture=fixture.replace("/* ORIGINAL_CONSTANTS */",constants)
        ndk=NDK
        for mode in ("precise","strict"):
            with self.subTest(fp=mode):
                compile_probe("granny_fpu_cache",fixture,{},extra_flags=("/O2","/fp:"+mode,"/clang:-ffp-contract=off",
                              "/clang:-fno-strict-aliasing","/clang:-fwrapv","/clang:-Wno-unused-variable","/clang:-Wno-unused-label"),
                              compiler_override=ndk/"toolchains/llvm/prebuilt/windows-x86_64/bin/clang-cl.exe")
        # Prove the differential oracle rejects a real changed arithmetic result,
        # rather than merely executing two bodies that never reach their stores.
        needle="_h5_fp.st[0] *= (double)*(float*)ADDR(eax + 0xC);"
        self.assertEqual(fixture.count(needle),1)
        mutant=fixture.replace(needle,"_h5_fp.st[0] = 0.0;",1)
        with self.assertRaisesRegex(AssertionError,"Granny mismatch"):
            compile_probe("granny_fpu_cache_mutant",mutant,{},extra_flags=("/O2","/fp:strict","/clang:-ffp-contract=off",
                          "/clang:-fno-strict-aliasing","/clang:-fwrapv","/clang:-Wno-unused-variable","/clang:-Wno-unused-label"),
                          compiler_override=ndk/"toolchains/llvm/prebuilt/windows-x86_64/bin/clang-cl.exe")


if __name__=="__main__":
    unittest.main()
