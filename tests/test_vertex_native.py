"""Vertex kernels (android/host/vertex_native.c) versus each edition's production bodies.

The oracles are the exact bodies tools/build_android.py compiles (override_source:
x87 precision rounding and locals, packed SSE with x86 NaN rules, the masked call
protocol). Oracle and native run on the same restored state; the fixture compares
all GPRs, flags, the backward-branch counter, x87 window and compare state, MMX,
SSE, MXCSR, the trace ring, every callee/hand-over snapshot and the guest memory.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from test_mmx_packed import CLANG, command, environment, pc_header
from test_static_tls import ROOT

sys.path.insert(0, str(ROOT / "tools"))
from editions import generated_root

HERE = ROOT / "build/tests/vertex-native"
SOURCE = ROOT / "android/host/vertex_native.c"

# Matched by normalized original bytes (relocations and rel32 calls masked) and
# by the absolute operands of the matched bodies; see build/hot-native-20261114/map.
ADDRESSES = {
    "toe": {"00CF8D80": "00CF8D80", "00CF8F30": "00CF8F30", "00C687C0": "00C687C0", "00CF92C0": "00CF92C0",
            "00738840": "00738840", "00CF8AC0": "00CF8AC0", "00CF88F0": "00CF88F0",
            "00E12F24": "00E12F24", "00E951A0": "00E951A0", "010C5990": "010C5990"},
    "vanilla": {"00CF8D80": "00BE3F50", "00CF8F30": "00BE4100", "00C687C0": "008C5860", "00CF92C0": "00BE4490",
                "00738840": "00452670", "00CF8AC0": "00BE3C90", "00CF88F0": "00BE3AC0",
                "00E12F24": "00E17508", "00E951A0": "00E2899C", "010C5990": "00F715E8"},
    "hof": {"00CF8D80": "008FDD90", "00CF8F30": "008FDF40", "00C687C0": "00A46140", "00CF92C0": "008FE2D0",
            "00738840": "004584E0", "00CF8AC0": "008FDAD0", "00CF88F0": "008FD900",
            "00E12F24": "00DECF84", "00E951A0": "00E0E61C", "010C5990": "00F93800"},
}
UNITS = {
    "toe": {"00CF8D80": "game_0701.c", "00CF8F30": "game_0701.c", "00CF92C0": "game_0701.c", "00C687C0": "game_0657.c"},
    "vanilla": {"00BE3F50": "game_0642.c", "00BE4100": "game_0642.c", "00BE4490": "game_0642.c", "008C5860": "game_0392.c"},
    "hof": {"008FDD90": "game_0411.c", "008FDF40": "game_0411.c", "008FE2D0": "game_0411.c", "00A46140": "game_0512.c"},
}
ROLES = {"00CF8D80": "point", "00CF8F30": "curve", "00C687C0": "blend", "00CF92C0": "light"}

EXTRACT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tools"))
import build_android as builder
from editions import generated_root
spec = json.load(sys.stdin)
result = {}
for edition, units in spec["units"].items():
    builder.configure_edition(edition)
    builder.PGO_USE = True
    builder.OUT = Path(spec["output"]) / edition
    for address, unit in units.items():
        prepared, _ = builder.override_source(generated_root(edition) / "game-x86" / unit, local_xmm=True)
        text = prepared.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        name = "sub_" + address
        start = text.index("void " + name + "(void) {")
        previous = text.rfind("\n}\n", 0, start)
        head = text[previous + 3:start] if previous >= 0 else ""
        end = text.index("\n}\n", start) + 3
        tail = end
        while text.startswith("#", tail):
            tail = text.index("\n", tail) + 1
        result[edition + ":" + address] = head + text[start:tail]
print(json.dumps(result))
'''


def production_bodies():
    cache = HERE / "production.json"
    spec = {"units": UNITS, "output": str(HERE / "prepared")}
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    if cache.is_file():
        stored = json.loads(cache.read_text(encoding="utf-8"))
        if stored.get("key") == key and stored.get("generated") == generated_digest():
            return stored["bodies"]
    HERE.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", EXTRACT], cwd=ROOT, input=json.dumps(spec),
                          capture_output=True, text=True, encoding="utf-8", timeout=1800)
    if done.returncode:
        raise AssertionError(done.stdout + done.stderr)
    bodies = json.loads(done.stdout)
    cache.write_text(json.dumps({"key": key, "generated": generated_digest(), "bodies": bodies}), encoding="utf-8")
    return bodies


def generated_digest():
    digest = hashlib.sha256()
    for edition, units in UNITS.items():
        for unit in sorted(set(units.values())):
            digest.update((generated_root(edition) / "game-x86" / unit).read_bytes())
    for path in (ROOT / "tools/build_android.py", ROOT / "tools/protocol_transform.py", ROOT / "tools/x87_locals.py",
                 ROOT / "android/runtime/recomp_types.h"):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def adapt(source, edition):
    mapping = ADDRESSES[edition]
    return re.sub(r"(0x|sub_)([0-9A-F]{8})(?![0-9A-F])",
                  lambda m: m[1] + mapping.get(m[2], m[2]), source)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
enum { MEMORY_BYTES = 0x1100000, LOW_BYTES = 0x200000, MAX_EVENTS = 4096 };
uint8_t memory[MEMORY_BYTES];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#define RECOMP_PLAIN_MEMORY
#define RECOMP_X87_WINDOW
#define RECOMP_YIELD_EVERY 64u
#include "recomp_types.h"
#include "names.h"
#ifndef RECOMP_ENTER_SIZE
#define RECOMP_ENTER_SIZE 1024
#endif
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_backedges,g_cur_func;
uint32_t g_enter_trace[RECOMP_ENTER_SIZE],g_enter_idx;
uint64_t g_mm[8];
xmm_t g_xmm[8];uint32_t g_mxcsr;
double g_st_win[RECOMP_X87_SLOTS];
int64_t g_st_i64_win[RECOMP_X87_SLOTS];int g_fp_sp;
int g_fp_top,void_fpu_cmp;
uint16_t g_fpu_cw;uint64_t g_fp_round_mask,g_fp_store_mask;
void (*recomp_yield_hook)(void);
int logs,oracle_calls,yield_policy,callee_policy;
const char *void_data_dir(void) {return ".";}
void void_log(const char *format,...) {(void)format;++logs;}
static uint64_t fake_now;
uint64_t void_perf_now_ns(void) {return fake_now;}
void void_fatal(const char *format,...) {fprintf(stderr,"FATAL %s\n",format);exit(3);}
static uint32_t random_state;
static uint32_t rnd(void) {random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
typedef struct state {
    uint32_t regs[8],flags[4],backedges,cur,trace_index;
    uint32_t trace[RECOMP_ENTER_SIZE];
    double fp[RECOMP_X87_SLOTS];int64_t fp_integer[RECOMP_X87_SLOTS];
    uint64_t mm[8];xmm_t xmm[8];uint32_t mxcsr;
    int fp_top,fp_cmp,fp_sp;uint16_t fp_cw;uint64_t round_mask,store_mask;
    uint8_t memory_digest[32];
} state;
static uint64_t fnv(const uint8_t *p,size_t n){uint64_t h=1469598103934665603ull;for(size_t i=0;i<n;i++){h^=p[i];h*=1099511628211ull;}return h;}
static state capture(int with_memory) {
    state s;memset(&s,0,sizeof s);
    const uint32_t regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    const uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs,regs,sizeof regs);memcpy(s.flags,flags,sizeof flags);
    s.backedges=g_backedges;s.cur=g_cur_func;s.trace_index=g_enter_idx;
    memcpy(s.trace,g_enter_trace,sizeof s.trace);memcpy(s.fp,g_st_win,sizeof s.fp);
    memcpy(s.fp_integer,g_st_i64_win,sizeof s.fp_integer);memcpy(s.mm,g_mm,sizeof s.mm);
    memcpy(s.xmm,g_xmm,sizeof s.xmm);s.mxcsr=g_mxcsr;
    s.fp_top=g_fp_top;s.fp_cmp=void_fpu_cmp;s.fp_sp=g_fp_sp;s.fp_cw=g_fpu_cw;
    s.round_mask=g_fp_round_mask;s.store_mask=g_fp_store_mask;
    if(with_memory){uint64_t h=fnv(memory,LOW_BYTES);memcpy(s.memory_digest,&h,8);}
    return s;
}
typedef struct event {unsigned kind;state cpu;} event;
static event log_events[MAX_EVENTS];static unsigned events;static int benchmarking;
static void record(unsigned kind) {
    if(benchmarking)return;
    if(events>=MAX_EVENTS){fprintf(stderr,"DIFFERENTIAL FAIL runaway events\n");exit(2);}
    log_events[events].kind=kind;log_events[events++].cpu=capture(1);
}
void recomp_protocol_violation(uint32_t site,uint32_t target,uint32_t regs){fprintf(stderr,"protocol violation %08x %08x %x\n",site,target,regs);abort();}
void recomp_x87_violation(uint32_t va,int found,int expected){fprintf(stderr,"x87 violation %08x %d %d\n",va,found,expected);abort();}
/* Hand-over: snapshot, then perturb what a real hand-over restores (the
 * kernels must follow the reloaded registers) and some unrelated memory. */
static void test_yield(void) {
    record(9);
    if(yield_policy&1){g_flag_k=FK_ADD;g_flag_a=17;g_flag_b=19;g_flag_cf=0;}
    if(yield_policy&2){g_st[2]+=0.5;g_st_i64[1]^=0x1010101010101010ll;((uint32_t*)g_xmm)[9]^=0xAFFEBCCDu;}
    if(yield_policy&4){MEM32(0x1F0000)^=0x5A5A5A5Au;}
}
/* 00738840: thiscall vector resize, RET 4 (shrink sets end; grow may move). */
void RESIZE(void) {
    record(1);
    uint32_t self=g_ecx,count=MEM32(g_esp+4),begin=MEM32(self),end=MEM32(self+4);
    uint32_t have=(end-begin)>>2;
    g_eax=end;
    if(callee_policy&1 && count>=have){uint32_t moved=0x1C0000u+((self*2654435761u+count*40503u)&0xFFF0u);MEM32(self)=moved;begin=moved;}
    MEM32(self+4)=begin+4u*count;
    g_ecx^=0x13579BDFu;g_edx=0xC0DE0000u|count;
    g_esp+=8;
}
/* 00CF8AC0: EAX = EDX*ECX component-wise (3 floats), RET. */
void SCALE3(void) {
    record(2);
    for(unsigned i=0;i<3;i++)MEMF(g_eax+4*i)=MEMF(g_edx+4*i)*MEMF(g_ecx+4*i);
    g_ecx=0x2468ACE0u;g_edx^=0x11111111u;g_esp+=4;
}
/* 00CF88F0: EAX = int16(ECX[2]*16384), [1], [0], 0; RET. */
void PACK3(void) {
    record(3);
    for(unsigned i=0;i<3;i++)MEM16(g_eax+2*i)=(uint16_t)(int16_t)(int32_t)(MEMF(g_ecx+8-4*i)*16384.0f);
    MEM16(g_eax+6)=0;g_edx=0x0BADF00Du;g_esp+=4;
}
#include "oracle.h"
void POINT_ENTRY(void){++oracle_calls;oracle_point();}
void CURVE_ENTRY(void){++oracle_calls;oracle_curve();}
void BLEND_ENTRY(void){++oracle_calls;oracle_blend();}
void LIGHT_ENTRY(void){++oracle_calls;oracle_light();}
void void_vertex_point(void),void_vertex_curve(void),void_vertex_blend(void),void_vertex_light(void);
void void_vertex_point_dispatch(void),void_vertex_curve_dispatch(void),void_vertex_blend_dispatch(void),void_vertex_light_dispatch(void);

/* Everything a case writes lies below LOW_BYTES; the constants are read-only
 * but compared too, so a stray store there still fails. */
static const uint32_t region_start[]={0,POINT_MIN&~0xFFFFu,POINT_SCALE&~0xFFFFu,CURVE_TABLE&~0xFFFFu};
static const uint32_t region_size[]={LOW_BYTES,0x10000,0x10000,0x10000};
enum {REGIONS=4,SAVED_BYTES=LOW_BYTES+3*0x10000};
static void save_regions(uint8_t *to){size_t at=0;for(unsigned r=0;r<REGIONS;r++){memcpy(to+at,memory+region_start[r],region_size[r]);at+=region_size[r];}}
static void load_regions(const uint8_t *from){size_t at=0;for(unsigned r=0;r<REGIONS;r++){memcpy(memory+region_start[r],from+at,region_size[r]);at+=region_size[r];}}
static uint8_t input_memory[SAVED_BYTES];
static state input_cpu;
static void restore(void) {
    load_regions(input_memory);
    const state *s=&input_cpu;
    g_eax=s->regs[0];g_ecx=s->regs[1];g_edx=s->regs[2];g_ebx=s->regs[3];
    g_esp=s->regs[4];g_ebp=s->regs[5];g_esi=s->regs[6];g_edi=s->regs[7];
    g_flag_k=s->flags[0];g_flag_a=s->flags[1];g_flag_b=s->flags[2];g_flag_cf=s->flags[3];
    g_backedges=s->backedges;g_cur_func=s->cur;g_enter_idx=s->trace_index;
    memcpy(g_enter_trace,s->trace,sizeof s->trace);memcpy(g_st_win,s->fp,sizeof s->fp);
    memcpy(g_st_i64_win,s->fp_integer,sizeof s->fp_integer);memcpy(g_mm,s->mm,sizeof s->mm);
    memcpy(g_xmm,s->xmm,sizeof s->xmm);g_mxcsr=s->mxcsr;
    g_fp_top=s->fp_top;void_fpu_cmp=s->fp_cmp;g_fp_sp=s->fp_sp;g_fpu_cw=s->fp_cw;
    g_fp_round_mask=s->round_mask;g_fp_store_mask=s->store_mask;
}
static unsigned bench_n;   /* bench mode: fixed vertex count per call */
#define LIMIT (bench_n>64u?bench_n:64u)
static float special_float(void) {
    static const uint32_t bits[]={0x00000000u,0x80000000u,0x3F800000u,0xBF800000u,0x7F800000u,0xFF800000u,
        0x7FC00000u,0xFFC00001u,0x7F800001u,0x7FA00000u,0x00000001u,0x80400000u,0x7F7FFFFFu,0x3F7FFFFFu,0x46FFFE00u,0x477FFF00u};
    uint32_t r=rnd(),b;
    if(bench_n){float f=(float)((int32_t)(r%4001u)-2000)/1000.0f;return f;}   /* bench: finite, as in the game */
    if((r&7)==0)b=bits[(r>>3)&15];
    else if((r&7)==1)b=rnd();
    else {float f=(float)((int32_t)(rnd()%4001u)-2000)/1000.0f;memcpy(&b,&f,4);}
    float f;memcpy(&f,&b,4);return f;
}
static uint16_t special_word(void) {
    static const uint16_t words[]={0,1,0x7FFF,0x8000,0x8001,0xFFFF,0x4000,0xC000};
    uint32_t r=rnd();return (r&3)==0?words[(r>>2)&7]:(uint16_t)rnd();
}
static const uint16_t control_words[]={0x0C7F,0x027F,0x007F,0x0E7F,0x047F,0x037F,0x087F,0x0F7F};
static void common_setup(uint32_t seed) {
    random_state=seed?seed:1;
    memset(memory,0xCD,LOW_BYTES);
    for(uint32_t i=0;i<0x4000;i+=4)MEM32(0x1E0000+i)=rnd();
    g_eax=rnd();g_ecx=rnd();g_edx=rnd();g_ebx=rnd();g_esp=0x80000;g_ebp=rnd();g_esi=rnd();g_edi=rnd();
    g_flag_k=FK_CMP;g_flag_a=rnd();g_flag_b=rnd();g_flag_cf=rnd()&1;
    g_backedges=rnd()%80u;g_cur_func=0x11998877;g_enter_idx=rnd()%7u;memset(g_enter_trace,0,sizeof g_enter_trace);
    g_fp_sp=120;
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){g_st_win[i]=(double)i+0.125;g_st_i64_win[i]=0x7000000000000000ll+i;}
    for(unsigned i=0;i<8;i++)g_mm[i]=((uint64_t)rnd()<<32)|rnd();
    for(unsigned i=0;i<32;i++)((uint32_t*)g_xmm)[i]=rnd();
    g_mxcsr=0x1F80;g_fp_top=(int)(seed%9)-1;void_fpu_cmp=0x41;
    uint16_t cw=control_words[rnd()&7];g_fpu_cw=cw;fp_cw_masks(cw);
    if((seed%23)==7){g_fp_round_mask=((uint64_t)rnd()<<32)|rnd();g_fp_store_mask=((uint64_t)rnd()<<32)|rnd();}
    unsigned hooks=rnd()%4u;recomp_yield_hook=hooks?test_yield:NULL;yield_policy=(int)(rnd()%8u);callee_policy=(int)(rnd()%2u);
    events=0;
}
/* ---- 00CF8D80 ---- */
enum {DIR=0x10000,COLOR=0x10100,VECTOR=0x10200,NORMALS=0x20000,ACC=0x30000};
static void setup_point(uint32_t seed,unsigned alias) {
    common_setup(seed);
    int32_t counts[]={-3,0,1,2,3,5,9,17,40,63};int32_t n=counts[rnd()%10u];if(bench_n)n=(int32_t)bench_n;
    for(unsigned i=0;i<4;i++)MEM16(DIR+2*i)=special_word();
    if(rnd()%5u==0){MEM16(DIR)=0;MEM16(DIR+2)=0;MEM16(DIR+4)=(uint16_t)(rnd()&3u);}
    for(unsigned i=0;i<3;i++)MEMF(COLOR+4*i)=special_float();
    MEMF(POINT_MIN)=(rnd()&1)?1.0f:special_float();MEMF(POINT_SCALE)=(rnd()&3)?32767.0f:special_float();
    uint32_t e=0x80000u-4u*(rnd()%8u);
    uint32_t normals=NORMALS,acc=ACC;
    uint32_t previous=0;
    for(unsigned i=0;i<LIMIT;i++){uint32_t v=(rnd()%3u==0)?previous:((rnd()%9u==0)?0:rnd());MEM32(normals+8+20*i)=v;previous=v;}
    for(unsigned i=0;i<LIMIT;i++)for(unsigned k=0;k<4;k++)MEM16(acc+8*i+2*k)=special_word();
    if(bench_n){MEM16(DIR)=12000;MEM16(DIR+2)=(uint16_t)-9000;MEM16(DIR+4)=15000;MEM16(DIR+6)=0;
        MEMF(COLOR)=0.8f;MEMF(COLOR+4)=0.5f;MEMF(COLOR+8)=0.3f;MEMF(POINT_MIN)=1.0f;MEMF(POINT_SCALE)=32767.0f;}
    switch(alias%9){
    case 1:acc=NORMALS+16;break;               /* accumulators over the normals */
    case 2:acc=((e-4u)&~7u)-0x28u;n=1;break;  /* over the saved EDI/ESI (one vertex) */
    case 3:normals=e-0x40;break;               /* normals reach the frame */
    case 4:g_edx=0;break;
    default:break;
    }
    MEM32(VECTOR)=acc;MEM32(VECTOR+4)=acc+8u*(uint32_t)(n>0?n:0);
    g_esp=e;MEM32(e)=RECOMP_RETADDR;MEM32(e+4)=VECTOR;MEM32(e+8)=normals;
    if(alias%9!=4)g_edx=DIR;
    if(alias%9==5)g_edx=e-0x30;                /* the light inside the frame */
    g_ecx=COLOR;if(alias%9==6)g_ecx=e-0x10;
    g_ebx=(uint32_t)n;
}
/* ---- 00CF8F30 ---- */
enum {CURVE_ACC_VECTOR=0x11000,CURVE_OUT_VECTOR=0x11010,CURVE_IN_VECTOR=0x11020,CURVE_ACC=0x40000,CURVE_IN=0x50000};
static void setup_curve(uint32_t seed,unsigned alias) {
    common_setup(seed);
    int32_t counts[]={-2,0,1,2,3,7,16,40,63};int32_t n=counts[rnd()%9u];if(bench_n)n=(int32_t)bench_n;
    for(unsigned i=0;i<0x8000;i+=4)MEM32(CURVE_TABLE+i)=rnd();
    for(unsigned i=0;i<LIMIT;i++){MEM32(CURVE_IN+4*i)=rnd();for(unsigned k=0;k<4;k++)MEM16(CURVE_ACC+8*i+2*k)=special_word();}
    uint32_t in=CURVE_IN,out=CURVE_IN,acc=CURVE_ACC;
    switch(alias%10){
    case 1:out=CURVE_IN+0x400;break;           /* separate output */
    case 2:out=CURVE_IN+4;break;               /* output one ahead */
    case 3:out=CURVE_IN-4;break;               /* output one behind */
    case 4:out=CURVE_ACC+12;break;             /* output over the accumulators */
    case 5:out=CURVE_TABLE+0x100;break;        /* output over the table */
    case 6:out=0x80000-20;n=1;break;           /* output over the saved EBX (one vertex) */
    case 7:in=0x80000-0x8;break;               /* input from the frame */
    default:break;
    }
    MEM32(CURVE_ACC_VECTOR)=acc;MEM32(CURVE_ACC_VECTOR+4)=acc+8u*(uint32_t)n;
    MEM32(CURVE_OUT_VECTOR)=out;MEM32(CURVE_IN_VECTOR)=in;
    g_esp=0x80000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=CURVE_IN_VECTOR;
    g_eax=CURVE_ACC_VECTOR;g_edx=CURVE_OUT_VECTOR;
}
/* ---- 00C687C0 ---- */
enum {MATRIX_POINTER=0x12000,MATRICES=0x60000,POSITIONS=0x70000,WEIGHTS=0x74000};
static void setup_blend(uint32_t seed,unsigned alias) {
    common_setup(seed);
    int32_t counts[]={-1,0,1,2,3,7,12,33};int32_t n=counts[rnd()%8u];if(bench_n)n=(int32_t)bench_n;
    for(unsigned i=0;i<0x4000;i+=4)MEMF(MATRICES+i)=special_float();
    for(unsigned i=0;i<LIMIT*3;i++)MEMF(POSITIONS+4*i)=special_float();
    for(unsigned i=0;i<LIMIT;i++){
        uint32_t w=WEIGHTS+0x18*i;
        for(unsigned k=0;k<4;k++)MEMF(w+4*k)=special_float();
        MEM8(w+0x10)=(uint8_t)rnd();
        for(unsigned k=1;k<4;k++)MEM8(w+0x10+k)=(rnd()%3u)?1:0;
        for(unsigned k=0;k<4;k++)MEM8(w+0x14+k)=(uint8_t)((rnd()%5u)?rnd()%12u:rnd());
    }
    uint32_t in=POSITIONS,out=bench_n?0x7C000u:POSITIONS+0x1000,weights=WEIGHTS;
    switch(alias%8){
    case 1:out=in;break;                       /* in place */
    case 2:out=in+12;break;
    case 3:out=WEIGHTS+0x18;break;             /* output over later weights */
    case 4:out=MATRICES+0x40;break;            /* output over matrices */
    case 5:out=0x80000-20;n=1;break;           /* over the saved EDI/ESI/EBX (one vertex) */
    case 6:weights=0x80000-0x20;break;
    default:break;
    }
    MEM32(MATRIX_POINTER)=MATRICES;
    g_esp=0x80000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=in;MEM32(g_esp+8)=out;MEM32(g_esp+12)=weights;
    g_eax=(uint32_t)n;g_ecx=MATRIX_POINTER;
}
/* ---- 00CF92C0 ---- */
enum {LIGHT=0x13000,INDEX_VECTOR=0x13100,NORMAL_VECTOR=0x13110,DIFFUSE_VECTOR=0x13120,SPECULAR_VECTOR=0x13130,
      BACK_SOURCE=0x13140,LIGHT_NORMALS=0x90000,DIFFUSE=0xA0000,SPECULAR=0xA8000};
static void setup_light(uint32_t seed,unsigned alias) {
    common_setup(seed);
    int32_t counts[]={-3,0,1,2,3,5,8,17,40,61};int32_t n=counts[rnd()%10u];if(bench_n)n=(int32_t)bench_n;
    for(unsigned i=0;i<0x30;i+=2)MEM16(LIGHT+i)=special_word();
    for(unsigned i=0;i<0x90;i+=4)MEM32(LIGHT+0x30+i)=rnd();
    for(unsigned i=0;i<3;i++)MEMF(BACK_SOURCE+4*i)=special_float();
    uint32_t previous=0;
    for(unsigned i=0;i<LIMIT;i++){uint32_t v=(rnd()%3u==0)?previous:((rnd()%9u==0)?0:rnd());MEM32(LIGHT_NORMALS+4*i)=v;previous=v;}
    uint32_t extra=bench_n?0:rnd()%3u;   /* odd/even byte lengths of the 16-bit index vector */
    MEM32(INDEX_VECTOR)=0x14000;MEM32(INDEX_VECTOR+4)=0x14000+(uint32_t)(2*n)+(extra==2?1:0);
    MEM32(NORMAL_VECTOR)=LIGHT_NORMALS;
    MEM32(DIFFUSE_VECTOR)=DIFFUSE;MEM32(DIFFUSE_VECTOR+4)=DIFFUSE+4u*(rnd()%70u);
    MEM32(SPECULAR_VECTOR)=SPECULAR;MEM32(SPECULAR_VECTOR+4)=SPECULAR+4u*(rnd()%70u);
    uint32_t diffuse_vector=DIFFUSE_VECTOR,specular_vector=SPECULAR_VECTOR,light_record=LIGHT;
    switch(alias%8){
    case 1:MEM32(DIFFUSE_VECTOR)=LIGHT_NORMALS+8;MEM32(DIFFUSE_VECTOR+4)=LIGHT_NORMALS+8;break; /* streams over normals */
    case 2:MEM32(SPECULAR_VECTOR)=DIFFUSE;MEM32(SPECULAR_VECTOR+4)=DIFFUSE;break;              /* both streams equal */
    case 3:MEM32(DIFFUSE_VECTOR)=LIGHT;MEM32(DIFFUSE_VECTOR+4)=LIGHT;break;                    /* over the light */
    case 4:MEM32(SPECULAR_VECTOR)=0x80000-0x28;MEM32(SPECULAR_VECTOR+4)=0x80000-0x28;            /* over the saved ESI */
        MEM32(INDEX_VECTOR+4)=0x14000+2;break;
    case 5:MEM32(SPECULAR_VECTOR)=0x80000-0x38;MEM32(SPECULAR_VECTOR+4)=0x80000-0x38;            /* dead slots below ESP */
        MEM32(INDEX_VECTOR+4)=0x14000+4;break;
    case 6:light_record=0x80000-0x30;break;  /* the light record over the colour spills (below the arguments) */
    default:break;
    }
    g_esp=0x80000;MEM32(g_esp)=RECOMP_RETADDR;
    MEM32(g_esp+4)=NORMAL_VECTOR;MEM32(g_esp+8)=(rnd()&1)?(rnd()|1u):0;
    MEM32(g_esp+0xC)=BACK_SOURCE;MEM32(g_esp+0x10)=diffuse_vector;MEM32(g_esp+0x14)=specular_vector;
    if(light_record!=LIGHT)for(unsigned i=0;i<0x30;i+=4)MEM32(light_record+i)=MEM32(LIGHT+i);
    g_ebx=light_record;g_edi=INDEX_VECTOR;
}
static int case_number;
static state oracle_final;static unsigned oracle_events;static event oracle_log[MAX_EVENTS];
static uint8_t oracle_memory[SAVED_BYTES],actual_memory[SAVED_BYTES];
static int compare(void (*setup)(uint32_t,unsigned),void (*original)(void),void (*native)(void),uint32_t seed,unsigned alias,const char *name) {
    setup(seed,alias);
    input_cpu=capture(0);save_regions(input_memory);
    original();oracle_final=capture(0);oracle_events=events;memcpy(oracle_log,log_events,events*sizeof(event));
    save_regions(oracle_memory);
    restore();events=0;native();state actual=capture(0);save_regions(actual_memory);
    int bad=memcmp(&oracle_final,&actual,sizeof actual)||oracle_events!=events||memcmp(oracle_log,log_events,events*sizeof(event))||
            memcmp(oracle_memory,actual_memory,sizeof actual_memory);
    if(bad){
        fprintf(stderr,"DIFFERENTIAL FAIL %s case%d seed%u alias%u events%u/%u\n",name,case_number,seed,alias,oracle_events,events);
        for(unsigned i=0;i<8;i++)if(oracle_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,oracle_final.regs[i],actual.regs[i]);
        for(unsigned i=0;i<8;i++)if(oracle_final.mm[i]!=actual.mm[i])fprintf(stderr,"mm%u %016llx/%016llx\n",i,(unsigned long long)oracle_final.mm[i],(unsigned long long)actual.mm[i]);
        for(unsigned i=0;i<8;i++)if(memcmp(&oracle_final.xmm[i],&actual.xmm[i],16))fprintf(stderr,"xmm%u differs\n",i);
        if(oracle_final.backedges!=actual.backedges)fprintf(stderr,"backedges %u/%u\n",oracle_final.backedges,actual.backedges);
        if(oracle_final.fp_cmp!=actual.fp_cmp)fprintf(stderr,"fpcmp %d/%d\n",oracle_final.fp_cmp,actual.fp_cmp);
        if(oracle_final.trace_index!=actual.trace_index)fprintf(stderr,"trace %u/%u\n",oracle_final.trace_index,actual.trace_index);
        for(unsigned i=0;i<4;i++)if(oracle_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,oracle_final.flags[i],actual.flags[i]);
        for(unsigned i=0;i<events&&i<oracle_events;i++)if(memcmp(&oracle_log[i],&log_events[i],sizeof(event))){fprintf(stderr,"first event %u kinds %u/%u\n",i,oracle_log[i].kind,log_events[i].kind);break;}
        for(unsigned i=0;i<SAVED_BYTES;i++)if(oracle_memory[i]!=actual_memory[i]){fprintf(stderr,"saved byte %08x %02x/%02x\n",i,oracle_memory[i],actual_memory[i]);break;}
        return 1;
    }
    return 0;
}
static double seconds(void){struct timespec t;timespec_get(&t,TIME_UTC);return (double)t.tv_sec+t.tv_nsec*1e-9;}
/* Per call: restore the registers, the stack window and the vector headers the
 * kernels rewrite (their own argument slots included), then time the call only. */
static uint8_t bench_stack[0x100],bench_headers[0x4300],bench_streams[0x10000];
static void bench(void (*setup)(uint32_t,unsigned),void (*fn)(void),const char *name,int native_side,unsigned rounds) {
    double total=0;unsigned calls=0;
    for(unsigned r=0;r<rounds;r++){
        setup(0x1234u+r*7919u,0);recomp_yield_hook=NULL;callee_policy=0;benchmarking=1;
        input_cpu=capture(0);
        memcpy(bench_stack,memory+0x80000-0x80,sizeof bench_stack);
        memcpy(bench_headers,memory+0x10000,sizeof bench_headers);
        memcpy(bench_streams,memory+0xA0000,sizeof bench_streams);
        for(unsigned k=0;k<200;k++){
            memcpy(memory+0x80000-0x80,bench_stack,sizeof bench_stack);
            memcpy(memory+0x10000,bench_headers,sizeof bench_headers);
            memcpy(memory+0xA0000,bench_streams,sizeof bench_streams);
            g_eax=input_cpu.regs[0];g_ecx=input_cpu.regs[1];g_edx=input_cpu.regs[2];g_ebx=input_cpu.regs[3];
            g_esp=input_cpu.regs[4];g_ebp=input_cpu.regs[5];g_esi=input_cpu.regs[6];g_edi=input_cpu.regs[7];
            g_backedges=0;events=0;
            double t0=seconds();fn();total+=seconds()-t0;++calls;
        }
        benchmarking=0;
    }
    printf("BENCH %s %s %.3f us/call\n",name,native_side?"native":"original",1e6*total/calls);
}
int main(int argc,char **argv) {
    struct {void (*setup)(uint32_t,unsigned);void (*original)(void);void (*native)(void);const char *name;unsigned aliases;} kernels[]={
        {setup_point,POINT_ENTRY,void_vertex_point,"point",9},{setup_curve,CURVE_ENTRY,void_vertex_curve,"curve",10},
        {setup_blend,BLEND_ENTRY,void_vertex_blend,"blend",8},{setup_light,LIGHT_ENTRY,void_vertex_light,"light",8}};
    if(argc>1&&!strcmp(argv[1],"bench")){
        unsigned rounds=argc>2?(unsigned)atoi(argv[2]):20;bench_n=argc>3?(unsigned)atoi(argv[3]):400;
        for(unsigned k=0;k<4;k++){bench(kernels[k].setup,kernels[k].original,kernels[k].name,0,rounds);bench(kernels[k].setup,kernels[k].native,kernels[k].name,1,rounds);}
        return 0;
    }
    if(argc>1&&!strcmp(argv[1],"live")){
        /* native-vertex-live present at the first call: re-read at most once a second. */
        remove("native-vertex-original");
        FILE *f=fopen("native-vertex-live","wb");assert(f);fputs("1",f);fclose(f);
        int seen[5];fake_now=1000;logs=0;recomp_yield_hook=NULL;
        setup_point(3,0);oracle_calls=0;void_vertex_point_dispatch();seen[0]=oracle_calls;
        f=fopen("native-vertex-live","wb");assert(f);fputs("0",f);fclose(f);
        fake_now+=500000000ull;setup_point(3,0);oracle_calls=0;void_vertex_point_dispatch();seen[1]=oracle_calls;
        fake_now+=600000000ull;setup_point(3,0);oracle_calls=0;void_vertex_point_dispatch();seen[2]=oracle_calls;
        remove("native-vertex-live");
        fake_now+=2000000000ull;setup_point(3,0);oracle_calls=0;void_vertex_point_dispatch();seen[3]=oracle_calls;
        f=fopen("native-vertex-live","wb");assert(f);fclose(f);   /* empty: the kernels */
        fake_now+=2000000000ull;setup_point(3,0);oracle_calls=0;void_vertex_point_dispatch();seen[4]=oracle_calls;
        remove("native-vertex-live");
        printf("live switch: %d %d %d %d %d, logs %d\n",seen[0],seen[1],seen[2],seen[3],seen[4],logs);
        return 0;
    }
    remove("native-vertex-live");
    unsigned cases=argc>1&&!strncmp(argv[1],"cases=",6)?(unsigned)atoi(argv[1]+6):CASES;
    unsigned native_runs[4]={0};
    for(unsigned k=0;k<4;k++)for(unsigned i=0;i<cases;i++){
        ++case_number;oracle_calls=0;
        if(compare(kernels[k].setup,kernels[k].original,kernels[k].native,i*0x9E3779B9u+17u+k,i%kernels[k].aliases,kernels[k].name))return 1;
        if(oracle_calls==1)native_runs[k]++;   /* the oracle side ran once: the native side ran natively */
    }
    /* Routers: native-vertex-original = 1 runs the originals; no file or anything else the kernels. */
    int mode=argc>1&&!strncmp(argv[1],"mode=",5)?argv[1][5]:'d';
    remove("native-vertex-original");
    if(mode!='d'){FILE *f=fopen("native-vertex-original","wb");assert(f);fputs(argv[1]+5,f);fclose(f);}
    setup_point(3,0);recomp_yield_hook=NULL;oracle_calls=0;logs=0;void_vertex_point_dispatch();
    printf("router mode %c: oracle calls %d, logs %d\n",mode,oracle_calls,logs);
    assert(logs==1);
    setup_curve(5,1);recomp_yield_hook=NULL;void_vertex_curve_dispatch();
    setup_blend(7,0);recomp_yield_hook=NULL;void_vertex_blend_dispatch();
    setup_light(9,0);recomp_yield_hook=NULL;void_vertex_light_dispatch();
    assert(logs==1);
    remove("native-vertex-original");
    printf("PASS %d cases (native runs point %u curve %u blend %u light %u): full guest memory/GPR/flags/x87/MMX/SSE/TRACE/callee/hand-over state; router oracle calls %d\n",
           case_number,native_runs[0],native_runs[1],native_runs[2],native_runs[3],oracle_calls);
    return 0;
}
'''

NATIVE_HOST = r'''
#include <stdint.h>
extern uint8_t memory[];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_YIELD_EVERY 64u
#include "recomp_types.h"
const char *void_data_dir(void);
void void_log(const char *fmt, ...);
uint64_t void_perf_now_ns(void);
_Noreturn void void_fatal(const char *fmt, ...);
'''


class VertexNativeTest(unittest.TestCase):
    bodies = None

    @classmethod
    def setUpClass(cls):
        cls.bodies = production_bodies()

    def probe(self, edition, label, source=None, trace=True, cases=600, arch="x64", default=1):
        out = HERE / ("probe-" + label)
        out.mkdir(parents=True, exist_ok=True)
        mapping = ADDRESSES[edition]
        oracle, names = [], ""
        for toe_address, role in ROLES.items():
            address = mapping[toe_address]
            body = self.bodies[edition + ":" + address]
            oracle.append(body.replace("void sub_" + address + "(void) {", "void oracle_" + role + "(void) {", 1))
            names += "#define %s_ENTRY sub_%s\n" % (role.upper(), address)
        names += ("#define RESIZE sub_%s\n#define SCALE3 sub_%s\n#define PACK3 sub_%s\n" %
                  (mapping["00738840"], mapping["00CF8AC0"], mapping["00CF88F0"]))
        names += ("#define POINT_MIN 0x%su\n#define POINT_SCALE 0x%su\n#define CURVE_TABLE 0x%su\n" %
                  (mapping["00E12F24"], mapping["00E951A0"], mapping["010C5990"]))
        names += "#define CASES %du\n#define VERTEX_DEFAULT_EXPECTED %d\n" % (cases, default)
        prefix = HARNESS if trace else HARNESS.replace("#define RECOMP_X87_WINDOW", "#define RECOMP_X87_WINDOW\n#undef RECOMP_TRACE")
        if trace:
            prefix = prefix.replace("#define RECOMP_X87_WINDOW", "#define RECOMP_X87_WINDOW\n#define RECOMP_TRACE", 1)
        native = adapt((source if source is not None else SOURCE.read_text(encoding="utf-8")), edition)
        header = (ROOT / "android/runtime/recomp_types.h").read_text()
        files = {"probe.c": prefix, "oracle.h": "\n".join(oracle), "names.h": names,
                 "native.c": native, "native_mode.h": (ROOT / "android/host/native_mode.h").read_text(encoding="utf-8"),
                 "host.h": NATIVE_HOST.replace("#define RECOMP_X87_WINDOW", "#define RECOMP_X87_WINDOW\n#define RECOMP_TRACE" if trace else "#define RECOMP_X87_WINDOW"),
                 "recomp_types.h": pc_header(header) if arch == "x64" else header}
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
        return out

    def run_probe(self, out, args=(), check=True):
        env, linker = environment("x64")
        flags = [CLANG, "/nologo", "/W0", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                 "/clang:--target=x86_64-pc-windows-msvc", "/clang:-fno-strict-aliasing", "/clang:-fwrapv",
                 "/clang:-ffp-contract=off"]
        if not (out / "probe.exe").is_file() or (out / "stamp").read_text() != self.stamp(out):
            command([*flags, "/c", "probe.c", "/Foprobe.obj"], out, env)
            command([*flags, "/c", "native.c", "/Fonative.obj"], out, env)
            command([linker, "/nologo", "probe.obj", "native.obj", "/OUT:probe.exe", "/STACK:4194304"], out, env)
            (out / "stamp").write_text(self.stamp(out))
        result = subprocess.run([str(out / "probe.exe"), *args], cwd=out, env=env, text=True, capture_output=True,
                                timeout=600, creationflags=subprocess.CREATE_NO_WINDOW)
        if check:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    @staticmethod
    def stamp(out):
        return hashlib.sha256(b"".join((out / n).read_bytes() for n in ("probe.c", "oracle.h", "names.h", "native.c", "native_mode.h", "host.h", "recomp_types.h"))).hexdigest()

    def test_all_editions_full_state(self):
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                out = self.probe(edition, edition)
                result = self.run_probe(out)
                self.assertIn("PASS", result.stdout)
                counts = [int(v) for v in re.findall(r"(?:point|curve|blend|light) (\d+)", result.stdout)]
                self.assertEqual(len(counts), 4)
                self.assertTrue(all(c > 100 for c in counts), result.stdout)   # most cases took the native path
                print(edition + ": " + result.stdout.strip().splitlines()[-1])
                (out / "receipt.json").write_text(json.dumps({
                    "edition": edition, "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                    "oracle_sha256": hashlib.sha256((out / "oracle.h").read_bytes()).hexdigest(),
                    "result": result.stdout}, indent=2) + "\n", encoding="utf-8")

    def test_without_trace(self):
        out = self.probe("toe", "toe-notrace", trace=False, cases=200)
        self.assertIn("PASS", self.run_probe(out).stdout)

    def test_router_mode_file(self):
        out = self.probe("toe", "toe-modes", cases=4)
        for mode, oracle in (("d", 0), ("1", 1), ("0", 0), ("x", 0)):
            result = self.run_probe(out, () if mode == "d" else ("mode=" + mode,))
            self.assertIn("router mode %s: oracle calls %d" % (mode, oracle), result.stdout)

    def test_live_switch(self):
        # 1: originals from the first call; 0.5 s later still originals; 1.1 s later the kernels;
        # a removed file keeps the kernels; an empty file runs the kernels. Logs: the cached
        # mode, live original=1, live original=0.
        out = self.probe("toe", "toe-live", cases=4)
        result = self.run_probe(out, ("live",))
        self.assertIn("live switch: 1 1 0 0 0, logs 3", result.stdout)
        self.assertFalse((out / "native-vertex-live").exists())

    def mutant(self, label, old, new):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(source.count(old), 1, old)
        out = self.probe("toe", "mutant-" + label, source=source.replace(old, new), cases=300)
        result = self.run_probe(out, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("DIFFERENTIAL FAIL", result.stderr)

    def test_reject_unsaturated_accumulation(self):
        self.mutant("paddw", "mm2 = mmx_paddsw(contribution, old);", "mm2 = mmx_paddw(contribution, old);")

    def test_reject_lost_stack_bias_word(self):
        self.mutant("bias", "const uint64_t bias = ld64(S + 0x18u), light = ld64(dir);",
                    "const uint64_t bias = 0x8000800080008000ull, light = ld64(dir);")

    def test_reject_curve_without_zero_case(self):
        self.mutant("curve", "m3 = (~m3 & m0) | m2;", "m3 = m0;")

    def test_reject_native_nan_rule(self):
        # Swapped NaN priority (source before destination): visible on x86 and ARM hosts.
        self.mutant("nan", "static inline vertex_f4 mulps(vertex_f4 d, vertex_f4 s) { return sse_nan_rule(d * s, d, s); }",
                    "static inline vertex_f4 mulps(vertex_f4 d, vertex_f4 s) { return sse_nan_rule(d * s, s, d); }")

    def test_reject_ignored_handover(self):
        self.mutant("handover", "return !recomp_yield_hook || (uint64_t)g_backedges + edges < RECOMP_YIELD_EVERY;",
                    "return 1;")

    def test_reject_light_back_colour(self):
        self.mutant("back", "behind = facing < 0 ? (int16_t)~facing : (int16_t)-1;", "behind = facing < 0 ? (int16_t)~facing : 0;")

    def test_reject_point_unsaturated_contribution(self):
        # (The mm5 rounding dwords are always 0x1000 after the prologue: a lane swap is not observable.)
        self.mutant("clamp", "packed |= (uint64_t)(uint16_t)(value > 32767 ? 32767 : value < -32768 ? -32768 : value) << (16 * k);",
                    "packed |= (uint64_t)(uint16_t)value << (16 * k);")

    def test_reject_light_saturated_facing(self):
        self.mutant("facing", "const int16_t facing = (int16_t)(uint16_t)(uint32_t)((int32_t)dot >> 15);",
                    "const int32_t wide = (int32_t)dot >> 15; const int16_t facing = (int16_t)(wide > 32767 ? 32767 : wide < -32768 ? -32768 : wide);")


if __name__ == "__main__":
    unittest.main()
