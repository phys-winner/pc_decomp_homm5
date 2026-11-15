"""Grid dilation kernel (android/host/dilate_native.c) versus each edition's production body.

The oracle is the exact body tools/build_android.py compiles (override_source: the masked
call protocol, the backward-branch hand-over). Oracle and kernel run on the same restored
state with the same callee models (the bitmap copy constructor and free); the fixture
compares all GPRs, flags, the backward-branch counter, the trace ring, every callee and
hand-over snapshot (full CPU state and a digest of guest memory) and the guest memory.
The cases cover the shapes the game passes (k = 2, small grids) and every aliasing the
original's memory order makes visible: rows shared, rows over the snapshot, the frame,
the header and the row table, snapshot rows over the frame, and hand-overs (every 64
backward branches here) inside windows, rows and cells.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

from test_mmx_packed import CLANG, command, environment, pc_header
from test_static_tls import ROOT

sys.path.insert(0, str(ROOT / "tools"))
from editions import generated_root

HERE = ROOT / "build/tests/dilate-native"
SOURCE = Path(os.environ.get("DILATE_NATIVE_SOURCE", ROOT / "android/host/dilate_native.c"))

# Matched by normalized original bytes (relocations and rel32 calls masked); the
# callees are the call targets of the matched bodies (build/hot-native-20261114/grid).
ADDRESSES = {
    "toe": {"00B3EFB0": "00B3EFB0", "004F8260": "004F8260", "00879240": "00879240"},
    "vanilla": {"00B3EFB0": "0083D910", "004F8260": "004AECA0", "00879240": "00C00360"},
    "hof": {"00B3EFB0": "00A712C0", "004F8260": "00453C20", "00879240": "00A99C10"},
}
UNITS = {"toe": {"00B3EFB0": "game_0567.c"}, "vanilla": {"0083D910": "game_0351.c"},
         "hof": {"00A712C0": "game_0522.c"}}

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
enum { MEMORY_BYTES = 0x200000, MAX_EVENTS = 8192 };
uint8_t memory[MEMORY_BYTES + 16];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#define RECOMP_PLAIN_MEMORY
#define RECOMP_X87_WINDOW
#define RECOMP_YIELD_EVERY 64u
#include "recomp_types.h"
/* A 2 MiB guest space that wraps, for both sides: any pointer a case builds
 * (snapshot rows in the frame, bits set in a row table) stays inside. */
#undef ADDR
#define ADDR(va) ((uintptr_t)((uint32_t)(va) & (MEMORY_BYTES - 1u)) + (uintptr_t)memory)
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
int logs,oracle_calls,yield_policy;
const char *void_data_dir(void) {return ".";}
void void_log(const char *format,...) {(void)format;++logs;}
static uint64_t fake_now;
uint64_t void_perf_now_ns(void) {return fake_now;}
void void_fatal(const char *format,...) {fprintf(stderr,"FATAL %s\n",format);exit(3);}
void recomp_protocol_violation(uint32_t site,uint32_t target,uint32_t regs){fprintf(stderr,"protocol violation %08x %08x %x\n",site,target,regs);abort();}
void recomp_x87_violation(uint32_t va,int found,int expected){fprintf(stderr,"x87 violation %08x %d %d\n",va,found,expected);abort();}
static uint32_t random_state;
static uint32_t rnd(void) {random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
typedef struct state {
    uint32_t regs[8],flags[4],backedges,cur,trace_index;
    uint32_t trace[RECOMP_ENTER_SIZE];
    uint8_t memory_digest[8];
} state;
static uint64_t fnv(const uint8_t *p,size_t n){uint64_t h=1469598103934665603ull;for(size_t i=0;i<n;i++){h^=p[i];h*=1099511628211ull;}return h;}
/* Snapshots digest the regions a case lives in; the final comparison covers all memory. */
static uint64_t digest(void){return fnv(memory+0x10000,0x12000)^(fnv(memory+0x7F000,0x1100)*31u);}
static state capture(int with_memory) {
    state s;memset(&s,0,sizeof s);
    const uint32_t regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    const uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs,regs,sizeof regs);memcpy(s.flags,flags,sizeof flags);
    s.backedges=g_backedges;s.cur=g_cur_func;s.trace_index=g_enter_idx;
    memcpy(s.trace,g_enter_trace,sizeof s.trace);
    if(with_memory){uint64_t h=digest();memcpy(s.memory_digest,&h,8);}
    return s;
}
typedef struct event {unsigned kind;state cpu;} event;
static event log_events[MAX_EVENTS];static unsigned events;static int benchmarking;
static void record(unsigned kind) {
    if(benchmarking)return;
    if(events>=MAX_EVENTS){fprintf(stderr,"DIFFERENTIAL FAIL runaway events\n");exit(2);}
    log_events[events].kind=kind;log_events[events++].cpu=capture(1);
}
/* Hand-over: snapshot, then change what another guest thread may change: the
 * flags, the registers a hand-over restores (not here: the machine keeps them),
 * and guest memory, including a grid byte the loops read or write next. */
static uint32_t yield_poke;
static void test_yield(void) {
    record(9);
    if(yield_policy&1){g_flag_k=FK_ADD;g_flag_a=17;g_flag_b=19;g_flag_cf=0;}
    if((yield_policy&2)&&yield_poke)MEM8(yield_poke)^=0xA5u;
    if(yield_policy&4){MEM32(0x1F0000)^=0x5A5A5A5Au;}
}
/* 004F8260: thiscall bitmap copy constructor, RET 4. The model allocates the
 * snapshot where the case says (possibly over live memory), like the original
 * copies stride*H bytes and points every row into the copy. */
static uint32_t copy_data_at,copy_rows_at,copy_row0;static int copy_policy;
void COPY(void) {
    record(1);
    uint32_t self=g_ecx,source=MEM32(g_esp+4);
    if(!MEM32(source+4)){MEM32(self+12)=0;MEM32(self+8)=0;MEM32(self)=0;MEM32(self+4)=0;g_eax=0;}
    else{
        uint32_t stride=MEM32(source+8),height=MEM32(source+12);
        MEM32(self+8)=stride;MEM32(self+12)=height;
        MEM32(self)=copy_data_at;MEM32(self+4)=copy_rows_at;
        for(uint32_t i=0;i<height&&i<64;i++)MEM32(copy_rows_at+4*i)=copy_data_at+i*stride;
        if(copy_row0&&height)MEM32(copy_rows_at)=copy_row0;
        int32_t bytes=(int32_t)(stride*height);
        for(int32_t i=0;i<bytes&&i<0x4000;i++)MEM8(copy_data_at+(uint32_t)i)=MEM8(MEM32(source)+(uint32_t)i);
        g_eax=(uint32_t)bytes;
        if(copy_policy==1)MEM32(self+12)=height+1;     /* a snapshot taller than the grid */
        if(copy_policy==2&&height)MEM32(self+12)=height-1;   /* or shorter */
    }
    g_ecx=self^0x13579BDFu;g_edx=0xC0DE0000u|(copy_policy&0xFF);
    g_esp+=8;
}
/* 00879240: cdecl free. */
void FREE(void) {
    record(2);
    g_eax=MEM32(g_esp+4)^0x11110000u;g_ecx=0xF00D0000u|events;g_edx^=0x2222u;
    g_esp+=4;
}
#include "oracle.h"
extern unsigned dilate_fast_runs;
void GRID_ENTRY(void){++oracle_calls;oracle_grid();}
void void_dilate_grid(void),void_dilate_grid_dispatch(void);

static uint8_t input_memory[MEMORY_BYTES];
static state input_cpu;
static void restore(void) {
    memcpy(memory,input_memory,MEMORY_BYTES);
    const state *s=&input_cpu;
    g_eax=s->regs[0];g_ecx=s->regs[1];g_edx=s->regs[2];g_ebx=s->regs[3];
    g_esp=s->regs[4];g_ebp=s->regs[5];g_esi=s->regs[6];g_edi=s->regs[7];
    g_flag_k=s->flags[0];g_flag_a=s->flags[1];g_flag_b=s->flags[2];g_flag_cf=s->flags[3];
    g_backedges=s->backedges;g_cur_func=s->cur;g_enter_idx=s->trace_index;
    memcpy(g_enter_trace,s->trace,sizeof s->trace);
}
enum {GRID=0x10000,ROWS=0x11000,DATA=0x12000,COPY_DATA=0x20000,COPY_ROWS=0x21000,STACK=0x80000};
static unsigned bench_w,bench_h;
static void setup(uint32_t seed,unsigned alias) {
    random_state=seed?seed:1;
    memset(memory,0xCD,MEMORY_BYTES);
    for(uint32_t i=0;i<0x4000;i+=4)MEM32(0x1E0000+i)=rnd();
    int32_t widths[]={-1,0,1,2,3,5,8,9,16,17,23,31,40};
    int32_t heights[]={-1,0,1,2,3,4,6,9,13,20};
    int32_t ks[]={2,2,2,2,3,4,0,-2,1,7,5};
    int32_t w=widths[rnd()%13u],h=heights[rnd()%10u],k=ks[rnd()%11u];
    if(k>4){if(w>12)w=12;if(h>9)h=9;}
    if(alias%12==5){if(w>8)w=8;if(h>6)h=6;if(k>3)k=3;}   /* W or H grow while it runs */
    int table_case=alias%12==7&&(seed%2u)==0;
    if(table_case){w=40;h=6;k=2;}
    if(alias%12==6&&h>2)h=2;                              /* snapshot rows over the saved registers */
    if(bench_w){w=(int32_t)bench_w;h=(int32_t)bench_h;k=2;}
    uint32_t stride=(uint32_t)((w>0?w:1)+7)/8u+(rnd()%3u==0?rnd()%3u:0u);
    uint32_t used=(uint32_t)(h>0?h:1);
    for(uint32_t i=0;i<stride*used+16u;i++){uint32_t v=rnd();MEM8(DATA+i)=(uint8_t)((v&3u)==0?v>>8:((v&3u)==1?0:(v>>8)&(v>>16)&(v>>24)));}
    if(table_case){memset(memory+DATA,0,stride*used+16u);MEM8(DATA+stride+1u)=0xFFu;memset(memory+COPY_DATA+0x100u,0xFF,0x300u);}
    if(bench_w)for(uint32_t i=0;i<stride*used;i++)MEM8(DATA+i)=(uint8_t)((rnd()%7u)==0?1u<<(rnd()%8u):0u);
    for(uint32_t i=0;i<used&&i<64;i++)MEM32(ROWS+4*i)=DATA+i*stride;
    MEM32(GRID)=(uint32_t)w;MEM32(GRID+4)=DATA;MEM32(GRID+8)=ROWS;MEM32(GRID+12)=stride;MEM32(GRID+16)=(uint32_t)h;
    copy_data_at=COPY_DATA;copy_rows_at=COPY_ROWS;copy_policy=(int)(rnd()%4u);
    uint32_t e=STACK-4u*(rnd()%8u);
    yield_poke=0;copy_row0=0;
    /* The heap may put the snapshot's row table below the grid and its rows above. */
    if(alias%12==0&&(rnd()&1))copy_rows_at=GRID+0x800u;
    switch(alias%12){
    case 1:if(used>2)MEM32(ROWS+8)=MEM32(ROWS+4);break;                        /* two rows share bytes */
    case 2:copy_data_at=DATA;copy_rows_at=COPY_ROWS;break;                       /* snapshot over the grid */
    case 3:if(used>1)MEM32(ROWS+4)=e-0x30u-(rnd()%4u)*4u;break;                  /* a row in the frame */
    case 4:if(used>1)MEM32(ROWS+4)=ROWS;break;                                   /* a row over the row table */
    case 5:if(used>1)MEM32(ROWS+4)=GRID+(rnd()&1u?0u:16u);break;                 /* a row over W or H */
    case 6:copy_rows_at=e-0x40u;break;                                           /* snapshot rows in the frame */
    case 7:if(table_case){MEM32(ROWS+4)=COPY_ROWS;copy_data_at=GRID-0x1000u;memset(memory+GRID-0xF00u,0xFF,0x300u);}                                 /* a row over the snapshot row table */
           else if(used>2&&(rnd()&1))MEM32(ROWS+8)=COPY_ROWS+4u;
           else if(used>1)MEM32(ROWS+4)=COPY_ROWS;break;
    case 8:MEM32(GRID+4)=0;MEM32(GRID+8)=0;if(h>0)h=0;MEM32(GRID+16)=(uint32_t)h;break;  /* an empty bitmap */
    case 9:yield_poke=DATA+(rnd()%(stride*used+1u));break;                      /* hand-overs change the grid */
    case 10:yield_poke=e-0x30u-(rnd()%3u)*4u;break;                             /* hand-overs change the frame */
    case 11:copy_row0=e-0x20u-(rnd()%2u)*4u;break;                              /* snapshot row 0 over the window counters */
    default:break;
    }
    g_eax=rnd();g_ecx=GRID;g_edx=(uint32_t)k;g_ebx=rnd()&0x1FFFFFu;g_esp=e;g_ebp=rnd()&0x1FFFFFu;g_esi=rnd()&0x1FFFFFu;g_edi=rnd()&0x1FFFFFu;
    MEM32(e)=RECOMP_RETADDR;
    g_flag_k=FK_CMP;g_flag_a=rnd();g_flag_b=rnd();g_flag_cf=rnd()&1;
    g_backedges=(rnd()%3u==0)?60u+rnd()%8u:rnd()%80u;g_cur_func=0x11998877;g_enter_idx=rnd()%7u;
    memset(g_enter_trace,0,sizeof g_enter_trace);
    unsigned hooks=rnd()%3u==0&&!table_case;recomp_yield_hook=hooks?test_yield:NULL;yield_policy=(int)(rnd()%8u);
    events=0;
}
static int case_number;
static state oracle_final;static unsigned oracle_events;static event oracle_log[MAX_EVENTS];
static uint8_t oracle_memory[MEMORY_BYTES];
static int compare(uint32_t seed,unsigned alias) {
    setup(seed,alias);
    input_cpu=capture(0);memcpy(input_memory,memory,MEMORY_BYTES);
    GRID_ENTRY();oracle_final=capture(0);oracle_events=events;memcpy(oracle_log,log_events,events*sizeof(event));
    memcpy(oracle_memory,memory,MEMORY_BYTES);
    restore();events=0;void_dilate_grid();state actual=capture(0);
    int bad=memcmp(&oracle_final,&actual,sizeof actual)||oracle_events!=events||memcmp(oracle_log,log_events,events*sizeof(event))||
            memcmp(oracle_memory,memory,MEMORY_BYTES);
    if(bad){
        fprintf(stderr,"DIFFERENTIAL FAIL case%d seed%u alias%u events%u/%u\n",case_number,seed,alias,oracle_events,events);
        for(unsigned i=0;i<8;i++)if(oracle_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,oracle_final.regs[i],actual.regs[i]);
        if(oracle_final.backedges!=actual.backedges)fprintf(stderr,"backedges %u/%u\n",oracle_final.backedges,actual.backedges);
        for(unsigned i=0;i<4;i++)if(oracle_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,oracle_final.flags[i],actual.flags[i]);
        if(oracle_final.trace_index!=actual.trace_index)fprintf(stderr,"trace %u/%u\n",oracle_final.trace_index,actual.trace_index);
        for(unsigned i=0;i<events&&i<oracle_events;i++)if(memcmp(&oracle_log[i],&log_events[i],sizeof(event))){
            fprintf(stderr,"first event %u kinds %u/%u\n",i,oracle_log[i].kind,log_events[i].kind);
            for(unsigned r=0;r<8;r++)if(oracle_log[i].cpu.regs[r]!=log_events[i].cpu.regs[r])fprintf(stderr,"  reg%u %08x/%08x\n",r,oracle_log[i].cpu.regs[r],log_events[i].cpu.regs[r]);
            if(oracle_log[i].cpu.backedges!=log_events[i].cpu.backedges)fprintf(stderr,"  backedges %u/%u\n",oracle_log[i].cpu.backedges,log_events[i].cpu.backedges);
            break;}
        for(unsigned i=0;i<MEMORY_BYTES;i++)if(oracle_memory[i]!=memory[i]){fprintf(stderr,"byte %08x %02x/%02x\n",i,oracle_memory[i],memory[i]);break;}
        return 1;
    }
    return 0;
}
static double seconds(void){struct timespec t;timespec_get(&t,TIME_UTC);return (double)t.tv_sec+t.tv_nsec*1e-9;}
static void bench(void (*fn)(void),const char *name,unsigned rounds) {
    double total=0;unsigned calls=0;
    for(unsigned r=0;r<rounds;r++){
        setup(0x1234u+r*7919u,0);recomp_yield_hook=NULL;benchmarking=1;
        input_cpu=capture(0);memcpy(input_memory,memory,0x30000);
        for(unsigned k=0;k<200;k++){
            memcpy(memory,input_memory,0x30000);
            g_eax=input_cpu.regs[0];g_ecx=input_cpu.regs[1];g_edx=input_cpu.regs[2];g_ebx=input_cpu.regs[3];
            g_esp=input_cpu.regs[4];g_ebp=input_cpu.regs[5];g_esi=input_cpu.regs[6];g_edi=input_cpu.regs[7];
            g_backedges=0;events=0;
            double t0=seconds();fn();total+=seconds()-t0;++calls;
        }
        benchmarking=0;
    }
    printf("BENCH dilate %s %.3f us/call (%ux%u, k=2)\n",name,1e6*total/calls,bench_w,bench_h);
}
int main(int argc,char **argv) {
    if(argc>1&&!strcmp(argv[1],"bench")){
        unsigned rounds=argc>2?(unsigned)atoi(argv[2]):20;bench_w=argc>3?(unsigned)atoi(argv[3]):24;bench_h=argc>4?(unsigned)atoi(argv[4]):16;
        bench(GRID_ENTRY,"original",rounds);bench(void_dilate_grid,"native",rounds);
        return 0;
    }
    if(argc>1&&!strcmp(argv[1],"live")){
        remove("native-dilate-original");
        FILE *f=fopen("native-dilate-live","wb");assert(f);fputs("1",f);fclose(f);
        int seen[4];fake_now=1000;logs=0;
        setup(3,0);g_edx=2;recomp_yield_hook=NULL;oracle_calls=0;void_dilate_grid_dispatch();seen[0]=oracle_calls;
        f=fopen("native-dilate-live","wb");assert(f);fputs("0",f);fclose(f);
        fake_now+=500000000ull;setup(3,0);g_edx=2;recomp_yield_hook=NULL;oracle_calls=0;void_dilate_grid_dispatch();seen[1]=oracle_calls;
        fake_now+=600000000ull;setup(3,0);g_edx=2;recomp_yield_hook=NULL;oracle_calls=0;void_dilate_grid_dispatch();seen[2]=oracle_calls;
        remove("native-dilate-live");
        fake_now+=2000000000ull;setup(3,0);g_edx=2;recomp_yield_hook=NULL;oracle_calls=0;void_dilate_grid_dispatch();seen[3]=oracle_calls;
        printf("live switch: %d %d %d %d, logs %d\n",seen[0],seen[1],seen[2],seen[3],logs);
        return 0;
    }
    remove("native-dilate-live");
    unsigned cases=argc>1&&!strncmp(argv[1],"cases=",6)?(unsigned)atoi(argv[1]+6):CASES;
    unsigned native_runs=0,yields=0;
    for(unsigned i=0;i<cases;i++){
        ++case_number;oracle_calls=0;
        if(compare(i*0x9E3779B9u+17u,(i%3u)?0u:(i/3u)%12u))return 1;
        if(oracle_calls==1)native_runs++;
        for(unsigned e=0;e<oracle_events;e++)if(oracle_log[e].kind==9){yields++;break;}
    }
    /* Router: native-dilate-original = 1 runs the original; no file or anything else the kernel. */
    int mode=argc>1&&!strncmp(argv[1],"mode=",5)?argv[1][5]:'d';
    remove("native-dilate-original");
    if(mode!='d'){FILE *f=fopen("native-dilate-original","wb");assert(f);fputs(argv[1]+5,f);fclose(f);}
    setup(3,0);g_edx=2;recomp_yield_hook=NULL;oracle_calls=0;logs=0;void_dilate_grid_dispatch();
    printf("router mode %c: oracle calls %d, logs %d\n",mode,oracle_calls,logs);
    assert(logs==1);
    remove("native-dilate-original");
    printf("PASS %d cases (native runs %u, rows at once %u, cases with hand-overs %u): full guest memory/GPR/flags/backedges/TRACE/callee/hand-over state\n",
           case_number,native_runs,dilate_fast_runs,yields);
    return 0;
}
'''

NATIVE_HOST = r'''
#include <stdint.h>
extern uint8_t memory[];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_YIELD_EVERY 64u
#define DILATE_NATIVE_COUNTERS
#include "recomp_types.h"
#undef ADDR
#define ADDR(va) ((uintptr_t)((uint32_t)(va) & 0x1FFFFFu) + (uintptr_t)memory)
const char *void_data_dir(void);
void void_log(const char *fmt, ...);
uint64_t void_perf_now_ns(void);
_Noreturn void void_fatal(const char *fmt, ...);
'''


class DilateNativeTest(unittest.TestCase):
    bodies = None

    @classmethod
    def setUpClass(cls):
        cls.bodies = production_bodies()

    def probe(self, edition, label, source=None, trace=True, cases=3000, arch="x64"):
        out = HERE / ("probe-" + label)
        out.mkdir(parents=True, exist_ok=True)
        mapping = ADDRESSES[edition]
        address = mapping["00B3EFB0"]
        body = self.bodies[edition + ":" + address]
        oracle = body.replace("void sub_" + address + "(void) {", "void oracle_grid(void) {", 1)
        names = ("#define GRID_ENTRY sub_%s\n#define COPY sub_%s\n#define FREE sub_%s\n#define CASES %du\n" %
                 (address, mapping["004F8260"], mapping["00879240"], cases))
        prefix = HARNESS
        if trace:
            prefix = prefix.replace("#define RECOMP_X87_WINDOW", "#define RECOMP_X87_WINDOW\n#define RECOMP_TRACE", 1)
        native = adapt((source if source is not None else SOURCE.read_text(encoding="utf-8")), edition)
        header = (ROOT / "android/runtime/recomp_types.h").read_text()
        files = {"probe.c": prefix, "oracle.h": oracle, "names.h": names, "native.c": native,
                 "native_mode.h": (ROOT / "android/host/native_mode.h").read_text(encoding="utf-8"),
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
                runs, fast, yields = map(int, re.search(r"native runs (\d+), rows at once (\d+), cases with hand-overs (\d+)",
                                                        result.stdout).groups())
                self.assertGreater(runs, 2000, result.stdout)
                self.assertGreater(fast, 400, result.stdout)
                self.assertGreater(yields, 300, result.stdout)
                print(edition + ": " + result.stdout.strip().splitlines()[-1])

    def test_without_trace(self):
        out = self.probe("toe", "toe-notrace", trace=False, cases=1500)
        self.assertIn("PASS", self.run_probe(out).stdout)

    def test_router_mode_file(self):
        out = self.probe("toe", "toe-modes", cases=4)
        for mode, oracle in (("d", 0), ("1", 1), ("0", 0), ("x", 0)):
            result = self.run_probe(out, () if mode == "d" else ("mode=" + mode,))
            self.assertIn("router mode %s: oracle calls %d" % (mode, oracle), result.stdout)

    def test_live_switch(self):
        out = self.probe("toe", "toe-live", cases=4)
        result = self.run_probe(out, ("live",))
        self.assertIn("live switch: 1 1 0 0, logs 3", result.stdout)
        self.assertFalse((out / "native-dilate-live").exists())

    def mutant(self, label, old, new):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(source.count(old), 1, old)
        out = self.probe("toe", "mutant-" + label, source=source.replace(old, new), cases=1500)
        result = self.run_probe(out, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("DIFFERENTIAL FAIL", result.stderr)

    def test_reject_outside_not_a_hit(self):
        self.mutant("outside", "r->ecx = lo8(r->ecx, 1u);\n        return;", "r->ecx = lo8(r->ecx, 0u);\n        return;")

    def test_reject_early_exit_without_count(self):
        self.mutant("count", "g_backedges += (uint32_t)branches;", "g_backedges += (uint32_t)columns;")

    def test_reject_ignored_handover(self):
        self.mutant("handover", "(!recomp_yield_hook || (uint64_t)g_backedges + branches < RECOMP_YIELD_EVERY)", "1")

    def test_reject_cached_width(self):
        self.mutant("width", "const int more = (int32_t)r->esi < (int32_t)ld32(r->edi);",
                    "const int more = (int32_t)r->esi < (int32_t)ld32(r->esp + 0x2Cu);")

    def test_reject_stale_column_counter(self):
        self.mutant("column", "if (column) st32(s + 0x24u, columns - column);", "(void)0;")

    def test_reject_left_columns_not_hits(self):
        self.mutant("left", "for (int32_t x = 0; x < k - 1 && x < width; ++x) hit[x >> 6] |= 1ull << (x & 63);", "(void)0;")

    def test_reject_short_snapshot_not_hits(self):
        self.mutant("short", "if (y - k + 1 < 0 || y >= copy_height) {", "if (y - k + 1 < 0) {")

    def test_reject_last_cell_registers(self):
        self.mutant("lastcell", "r->ecx = earlier ? 0u : r->ecx & ~0xFFu;", "r->ecx = r->ecx & ~0xFFu;")

    def test_reject_snapshot_overlap_ignored(self):
        self.mutant("overlap", "if (!apart(write0, write1, read0, read1) || !apart(write0, write1, list0, list1) ||",
                    "if (!apart(write0, write1, list0, list1) ||")

    def test_reject_snapshot_table_overlap_ignored(self):
        self.mutant("table", "if (!apart(write0, write1, read0, read1) || !apart(write0, write1, list0, list1) ||",
                    "if (!apart(write0, write1, read0, read1) ||")

    def test_reject_lost_low_byte(self):
        self.mutant("lowbyte", "r->ecx &= ~0xFFu;\n    if ((int32_t)r->ebx > 0) {", "r->ecx = 0;\n    if ((int32_t)r->ebx > 0) {")


if __name__ == "__main__":
    unittest.main()
