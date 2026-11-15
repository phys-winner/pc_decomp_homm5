"""Names-table kernels (android/host/ai_names_native.c) versus each edition's production bodies.

The oracles are the exact bodies tools/build_android.py compiles (override_source: masked call
protocol, local backward-branch counter) for the string-keyed hash map find 00BD1150, the string
assign 00404150 with ToE's push_back 004041C0 (1.6 and 2.1: append 004091D0's counterparts) and the
grow 00404220, and msvcr71's strncmp 13002955; the 1.6 and 2.1 kernels are the legacy branch of the
source (tools/port_patches.legacy_ui_branch) with the contracts' addresses.
Oracle and kernel run on the same restored state with the same models of the game allocator
(008791F0 / 00879240) and of msvcr71's memmove; the fixture compares all GPRs, the lazy flags,
the backward-branch counter, every callee and hand-over snapshot (CPU state and a digest of guest
memory) and the whole guest memory. Cases cover empty and full buckets, equal-length different
keys, keys with NULs and high-bit bytes, a zero or negative bucket count, a foreign strncmp import,
assigns into empty, shorter, equal, full (growing) and longer strings, self-overlapping sources and
hand-overs (every 64 backward branches) inside the loops and inside the growing push_backs.
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

HERE = ROOT / "build/tests/ai-names-native"
SOURCE = Path(os.environ.get("AI_NAMES_NATIVE_SOURCE", ROOT / "android/host/ai_names_native.c"))

# ToE address -> edition address (find/assign/push_back or append/grow/malloc/free and the two IAT
# slots). The kernel's own addresses must match the contracts (test_contract_addresses).
ADDRESSES = {
    "toe": {"00BD1150": "00BD1150", "00404150": "00404150", "004041C0": "004041C0", "00404220": "00404220",
            "008791F0": "008791F0", "00879240": "00879240", "00E0A2B0": "00E0A2B0", "00E0A2A4": "00E0A2A4"},
    "vanilla": {"00BD1150": "0083AC00", "00404150": "00405200", "004091D0": "00401E10", "00404220": "00401CE0",
                "008791F0": "00C00310", "00879240": "00C00360", "00E0A2B0": "00DE32B4", "00E0A2A4": "00DE32A8"},
    "hof": {"00BD1150": "00B79FC0", "00404150": "00403870", "004091D0": "004220E0", "00404220": "00403200",
            "008791F0": "00A99BC0", "00879240": "00A99C10", "00E0A2B0": "00DBA298", "00E0A2A4": "00DBA2A8"},
}
KERNEL_ADDRESSES = ("00BD1150", "00404150", "004091D0", "00404220", "00E0A2B0")


def bodies_of(edition):
    """find, assign, the assign's appending callee, grow."""
    return ("00BD1150", "00404150", "004041C0" if edition == "toe" else "004091D0", "00404220")


STRNCMP = "13002955"

EXTRACT = r'''
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / "tools"))
import build_android as builder
from editions import generated_root
spec = json.load(sys.stdin)
result = {}
for edition, names in spec["names"].items():
    builder.configure_edition(edition)
    builder.PGO_USE = True
    builder.OUT = Path(spec["output"]) / edition
    root = generated_root(edition)
    for module, name in names:
        unit = next(p for p in sorted((root / module).glob("*.c")) if ("void " + name + "(void) {").encode() in p.read_bytes())
        prepared, _ = builder.override_source(unit, local_xmm=True)
        text = prepared.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
        start = text.index("void " + name + "(void) {")
        end = text.index("\n}\n", start) + 3
        result[edition + ":" + name] = text[start:end]
print(json.dumps(result))
'''


def production_bodies():
    names = {edition: [("game-x86", "sub_" + mapping[a]) for a in bodies_of(edition)] + [("msvcr71-x86", "sub_" + STRNCMP)]
             for edition, mapping in ADDRESSES.items()}
    cache = HERE / "production.json"
    spec = {"names": names, "output": str(HERE / "prepared")}
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    digest = generated_digest(names)
    if cache.is_file():
        stored = json.loads(cache.read_text(encoding="utf-8"))
        if stored.get("key") == key and stored.get("generated") == digest:
            return stored["bodies"]
    HERE.mkdir(parents=True, exist_ok=True)
    done = subprocess.run([sys.executable, "-X", "utf8", "-B", "-c", EXTRACT], cwd=ROOT, input=json.dumps(spec),
                          capture_output=True, text=True, encoding="utf-8", timeout=3600)
    if done.returncode:
        raise AssertionError(done.stdout + done.stderr)
    bodies = json.loads(done.stdout)
    cache.write_text(json.dumps({"key": key, "generated": digest, "bodies": bodies}), encoding="utf-8")
    return bodies


def generated_digest(names):
    digest = hashlib.sha256()
    for edition, rows in names.items():
        for module, name in rows:
            for unit in sorted((generated_root(edition) / module).glob("*.c")):
                data = unit.read_bytes()
                if ("void " + name + "(void) {").encode() in data:
                    digest.update(data)
                    break
    for path in (ROOT / "tools/build_android.py", ROOT / "tools/protocol_transform.py", ROOT / "tools/x87_locals.py",
                 ROOT / "android/runtime/recomp_types.h"):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def adapt(source, edition):
    """The source as tools/port_patches.adapt_host_source builds it for the edition."""
    if edition == "toe":
        return source
    from port_patches import legacy_ui_branch
    source = legacy_ui_branch(source.replace("\r\n", "\n").encode("utf-8"), True).decode("utf-8")
    mapping = {a: ADDRESSES[edition][a] for a in KERNEL_ADDRESSES}
    return re.sub(r"(0x|sub_)([0-9A-Fa-f]{8})(?![0-9A-Fa-f])", lambda m: m[1] + mapping.get(m[2].upper(), m[2]), source)


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
enum { MEMORY_BYTES = 0x200000, MAX_EVENTS = 4096 };
uint8_t memory[MEMORY_BYTES + 16];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#define RECOMP_PLAIN_MEMORY
#define RECOMP_X87_WINDOW
#define RECOMP_YIELD_EVERY 64u
#include "recomp_types.h"
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
int logs,oracle_calls,yield_policy,live_choice=-1;
const char *void_data_dir(void) {return ".";}
void void_log(const char *format,...) {(void)format;++logs;}
static uint64_t fake_now;
uint64_t void_perf_now_ns(void) {return fake_now;}
void void_fatal(const char *format,...) {fprintf(stderr,"FATAL %s\n",format);exit(3);}
void recomp_protocol_violation(uint32_t site,uint32_t target,uint32_t regs){fprintf(stderr,"protocol violation %08x %08x %x\n",site,target,regs);abort();}
void recomp_x87_violation(uint32_t va,int found,int expected){fprintf(stderr,"x87 violation %08x %d %d\n",va,found,expected);abort();}
int void_ai_live_original(int cached){return live_choice<0?cached:live_choice;}
static uint32_t random_state;
static uint32_t rnd(void) {random_state^=random_state<<13;random_state^=random_state>>17;random_state^=random_state<<5;return random_state;}
typedef struct state {
    uint32_t regs[8],flags[4],backedges,cur,trace_index;
    uint32_t trace[RECOMP_ENTER_SIZE];
    uint64_t memory_digest;
} state;
static uint64_t fnv(const uint8_t *p,size_t n){uint64_t h=1469598103934665603ull;for(size_t i=0;i<n;i++){h^=p[i];h*=1099511628211ull;}return h;}
static state capture(int with_memory) {
    state s;memset(&s,0,sizeof s);
    const uint32_t regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    const uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s.regs,regs,sizeof regs);memcpy(s.flags,flags,sizeof flags);
    s.backedges=g_backedges;s.cur=g_cur_func;s.trace_index=g_enter_idx;
    memcpy(s.trace,g_enter_trace,sizeof s.trace);
    /* Snapshots digest the regions the cases live in; the final comparison covers all memory. */
    if(with_memory)s.memory_digest=fnv(memory,0x30000)^(fnv(memory+0x70000,0x10000)*31u)^
                                   (fnv(memory+0x100000,0x10000)*131u)^(fnv(memory+0x1E0000,0x20000)*257u);
    return s;
}
typedef struct event {unsigned kind;state cpu;} event;
static event log_events[MAX_EVENTS];static unsigned events;
static void record(unsigned kind) {
    if(events>=MAX_EVENTS){fprintf(stderr,"DIFFERENTIAL FAIL runaway events\n");exit(2);}
    log_events[events].kind=kind;log_events[events++].cpu=capture(1);
}
static uint32_t yield_poke;
static void test_yield(void) {
    record(9);
    if(yield_policy&1){g_flag_k=FK_ADD;g_flag_a=17;g_flag_b=19;g_flag_cf=0;}
    if((yield_policy&2)&&yield_poke)MEM8(yield_poke)^=0x5Au;
    if(yield_policy&4){MEM32(0x1F0000)^=0x5A5A5A5Au;}
}
/* The game allocator models: cdecl, RET; a bump heap; volatile registers changed. */
static uint32_t heap_top;
void MALLOC(void) {
    record(1);
    uint32_t size=MEM32(g_esp+4);
    heap_top=(heap_top+15u)&~15u;
    g_eax=heap_top;heap_top+=size?size:1;
    for(uint32_t i=0;i<size&&i<64;i++)MEM8(g_eax+i)=(uint8_t)(0xA0u+i);
    g_ecx=0xC0FE0000u|size;g_edx=g_eax^0x01010101u;
    g_esp+=4;
}
void FREE(void) {
    record(2);
    uint32_t p=MEM32(g_esp+4);
    if(p)MEM32(p)^=0xDEADBEEFu;
    g_eax=p^0x11110000u;g_ecx=0xF00D0000u|events;g_edx^=0x2222u;
    g_esp+=4;
}
/* msvcr71 memmove model (cdecl): the oracle's tail erase. */
static void memmove_model(void) {
    record(3);
    uint32_t d=MEM32(g_esp+4),s=MEM32(g_esp+8),n=MEM32(g_esp+12);
    for(uint32_t i=0;i<n&&i<4096;i++)MEM8(0x1F8000+i)=MEM8(s+i);
    for(uint32_t i=0;i<n&&i<4096;i++)MEM8(d+i)=MEM8(0x1F8000+i);
    g_eax=d;g_ecx=0x3333u;g_edx=n;
    g_esp+=4;
}
#define MEMMOVE_VA 0x13001234u
void STRNCMP_BODY(void);
/* A foreign strncmp behind the import (another runtime): only the original may call it. */
static void foreign_strncmp(void) {
    record(4);
    uint32_t a=MEM32(g_esp+4),b=MEM32(g_esp+8),n=MEM32(g_esp+12),r=0;
    for(uint32_t i=0;i<n;i++){uint8_t x=MEM8(a+i),y=MEM8(b+i);if(x!=y){r=x<y?0xFFFFFF00u:0x100u;break;}if(!x)break;}
    g_eax=r;g_ecx=0x77u;g_edx=0x99u;
    g_esp+=4;
}
recomp_func_t void_resolve(uint32_t va) {
    if(va==0x13002955u)return STRNCMP_BODY;
    if(va==0x13002954u)return foreign_strncmp;
    if(va==MEMMOVE_VA)return memmove_model;
    fprintf(stderr,"unexpected indirect call %08x\n",va);exit(4);
}
#include "oracle.h"
void void_ai_name_find(void),void_ai_name_find_dispatch(void);
void void_ai_string_assign(void),void_ai_string_assign_dispatch(void);

static uint8_t input_memory[MEMORY_BYTES];
static state input_cpu;
static uint32_t input_heap_top;
static void restore(void) {
    memcpy(memory,input_memory,MEMORY_BYTES);
    heap_top=input_heap_top;
    const state *s=&input_cpu;
    g_eax=s->regs[0];g_ecx=s->regs[1];g_edx=s->regs[2];g_ebx=s->regs[3];
    g_esp=s->regs[4];g_ebp=s->regs[5];g_esi=s->regs[6];g_edi=s->regs[7];
    g_flag_k=s->flags[0];g_flag_a=s->flags[1];g_flag_b=s->flags[2];g_flag_cf=s->flags[3];
    g_backedges=s->backedges;g_cur_func=s->cur;g_enter_idx=s->trace_index;
    memcpy(g_enter_trace,s->trace,sizeof s->trace);
}
enum {MAP=0x10000,BUCKETS=0x10100,NODES=0x11000,TEXT=0x14000,KEY=0x18000,STR=0x20000,BUF=0x21000,SRC=0x22000,STACK=0x80000};
static const char *alphabet="abAB\x01\xFF\x80z0";
static void random_text(uint32_t at,uint32_t len,int nul_inside){
    for(uint32_t i=0;i<len;i++){uint32_t r=rnd();MEM8(at+i)=(uint8_t)alphabet[r%9u];if(nul_inside&&r%17u==0)MEM8(at+i)=0;}
    MEM8(at+len)=0;
}
static unsigned kind_of_case;
static void common_regs(uint32_t e){
    g_eax=rnd();g_edx=rnd();g_ebx=rnd()&0x1FFFFFu;g_esp=e;g_ebp=rnd()&0x1FFFFFu;g_esi=rnd()&0x1FFFFFu;g_edi=rnd()&0x1FFFFFu;
    g_flag_k=FK_CMP;g_flag_a=rnd();g_flag_b=rnd();g_flag_cf=rnd()&1;
    g_backedges=(rnd()%3u==0)?40u+rnd()%24u:rnd()%64u;g_cur_func=0x11998877;g_enter_idx=rnd()%7u;
    memset(g_enter_trace,0,sizeof g_enter_trace);
    unsigned hooks=rnd()%3u==0;recomp_yield_hook=hooks?test_yield:NULL;yield_policy=(int)(rnd()%8u);
    events=0;heap_top=0x100000u+(rnd()%64u)*16u;
}
static void setup_find(uint32_t seed){
    random_state=seed?seed:1;
    memset(memory,0xCD,MEMORY_BYTES);
    for(uint32_t i=0;i<0x4000;i+=4)MEM32(0x1E0000+i)=rnd();
    int32_t counts[]={1,1,2,3,7,13,64,0,5};
    int32_t n=counts[rnd()%9u];
    uint32_t buckets_end=BUCKETS+4u*(uint32_t)n;
    if(rnd()%23u==0)buckets_end=BUCKETS+4u*(uint32_t)n+2u;      /* not a multiple of 4 */
    MEM32(MAP+4)=BUCKETS;MEM32(MAP+8)=buckets_end;
    MEM32(BUCKETS)=0;   /* no buckets: the lifted div gives bucket 0, which must end */
    uint32_t key_len=rnd()%12u;
    random_text(TEXT,key_len,rnd()%5u==0);
    MEM32(KEY)=TEXT;MEM32(KEY+4)=TEXT+key_len+(rnd()%13u==0?1u:0u);
    uint32_t nodes=0,text_at=TEXT+0x100;
    for(int32_t b=0;b<(n>0?n:0)&&b<64;b++){
        uint32_t chain=rnd()%5u,prev=BUCKETS+4u*(uint32_t)b;
        MEM32(prev)=0;
        for(uint32_t c=0;c<chain&&nodes<512;c++){
            uint32_t node=NODES+12u*nodes++;
            uint32_t len=rnd()%3u==0?key_len:rnd()%12u;
            if(rnd()%4u==0){for(uint32_t i=0;i<=key_len;i++)MEM8(text_at+i)=MEM8(TEXT+i);len=key_len;}
            else random_text(text_at,len,rnd()%7u==0);
            if(rnd()%9u==0&&len)MEM8(text_at+len-1u)^=1u;
            MEM32(node+4)=text_at;MEM32(node+8)=text_at+len;MEM32(node)=0;
            MEM32(prev)=node;prev=node;text_at+=len+1u;
        }
    }
    MEM32(0x00E0A2B0)=rnd()%29u==0?0x13002954u:0x13002955u;
    uint32_t e=STACK-4u*(rnd()%8u);
    common_regs(e);
    g_ecx=MAP;
    MEM32(e)=RECOMP_RETADDR;MEM32(e+4)=KEY;
    yield_poke=TEXT+(rnd()%(key_len+1u));
}
static void setup_assign(uint32_t seed){
    random_state=seed?seed:1;
    memset(memory,0xCD,MEMORY_BYTES);
    for(uint32_t i=0;i<0x4000;i+=4)MEM32(0x1E0000+i)=rnd();
    uint32_t cur=rnd()%10u,cap=cur+1u+(rnd()%3u==0?0u:rnd()%8u);
    uint32_t buf=BUF+16u*(rnd()%4u);
    random_text(buf,cur,0);
    MEM32(STR)=buf;MEM32(STR+4)=buf+cur;MEM32(STR+8)=buf+cap;
    uint32_t src_len=rnd()%3u==0?cur:rnd()%40u;
    uint32_t src=SRC+rnd()%8u;
    random_text(src,src_len,rnd()%5u==0);
    if(rnd()%11u==0&&cur){src=buf+rnd()%cur;src_len=rnd()%(cur+4u);}   /* overlaps the current text */
    MEM32(0x00E0A2A4)=MEMMOVE_VA;
    uint32_t e=STACK-4u*(rnd()%8u);
    common_regs(e);
    g_ecx=STR;
    MEM32(e)=RECOMP_RETADDR;MEM32(e+4)=src;MEM32(e+8)=src+src_len;
    yield_poke=src_len?src+rnd()%src_len:0;
}
static int case_number;static unsigned native_runs;
static state oracle_final;static unsigned oracle_events;static event oracle_log[MAX_EVENTS];
static uint8_t oracle_memory[MEMORY_BYTES];
static int compare(uint32_t seed,int assign){
    if(assign)setup_assign(seed);else setup_find(seed);
    input_cpu=capture(0);memcpy(input_memory,memory,MEMORY_BYTES);input_heap_top=heap_top;
    if(assign)ASSIGN_BODY();else FIND_BODY();
    oracle_final=capture(0);oracle_events=events;memcpy(oracle_log,log_events,events*sizeof(event));
    memcpy(oracle_memory,memory,MEMORY_BYTES);
    restore();events=0;
    oracle_calls=0;
    if(assign)void_ai_string_assign();else void_ai_name_find();
    if(!oracle_calls)native_runs++;
    state actual=capture(0);
    int bad=memcmp(&oracle_final,&actual,sizeof actual)||oracle_events!=events||memcmp(oracle_log,log_events,events*sizeof(event))||
            memcmp(oracle_memory,memory,MEMORY_BYTES);
    if(bad){
        fprintf(stderr,"DIFFERENTIAL FAIL case%d seed%u %s events%u/%u\n",case_number,seed,assign?"assign":"find",oracle_events,events);
        for(unsigned i=0;i<8;i++)if(oracle_final.regs[i]!=actual.regs[i])fprintf(stderr,"reg%u %08x/%08x\n",i,oracle_final.regs[i],actual.regs[i]);
        if(oracle_final.backedges!=actual.backedges)fprintf(stderr,"backedges %u/%u\n",oracle_final.backedges,actual.backedges);
        for(unsigned i=0;i<4;i++)if(oracle_final.flags[i]!=actual.flags[i])fprintf(stderr,"flags%u %08x/%08x\n",i,oracle_final.flags[i],actual.flags[i]);
        if(oracle_final.trace_index!=actual.trace_index)fprintf(stderr,"trace %u/%u\n",oracle_final.trace_index,actual.trace_index);
        for(unsigned i=0;i<events&&i<oracle_events;i++)if(memcmp(&oracle_log[i],&log_events[i],sizeof(event))){
            fprintf(stderr,"first event %u kinds %u/%u\n",i,oracle_log[i].kind,log_events[i].kind);
            for(unsigned r=0;r<8;r++)if(oracle_log[i].cpu.regs[r]!=log_events[i].cpu.regs[r])fprintf(stderr,"  reg%u %08x/%08x\n",r,oracle_log[i].cpu.regs[r],log_events[i].cpu.regs[r]);
            if(oracle_log[i].cpu.backedges!=log_events[i].cpu.backedges)fprintf(stderr,"  backedges %u/%u\n",oracle_log[i].cpu.backedges,log_events[i].cpu.backedges);
            if(oracle_log[i].cpu.memory_digest!=log_events[i].cpu.memory_digest)fprintf(stderr,"  memory digest differs\n");
            break;}
        {unsigned shown=0;for(unsigned i=0;i<MEMORY_BYTES&&shown<24;i++)if(oracle_memory[i]!=memory[i]){fprintf(stderr,"byte %08x %02x/%02x\n",i,oracle_memory[i],memory[i]);shown++;}}
        return 1;
    }
    return 0;
}
static double seconds(void){struct timespec t;timespec_get(&t,TIME_UTC);return (double)t.tv_sec+t.tv_nsec*1e-9;}
static void bench(int assign,void (*fn)(void),const char *name,unsigned rounds){
    double total=0;unsigned calls=0;
    for(unsigned r=0;r<rounds;r++){
        if(assign)setup_assign(0x1234u+r*7919u);else setup_find(0x1234u+r*7919u);
        recomp_yield_hook=NULL;
        input_cpu=capture(0);memcpy(input_memory,memory,0x30000);
        for(unsigned k=0;k<200;k++){
            memcpy(memory,input_memory,0x30000);
            g_eax=input_cpu.regs[0];g_ecx=input_cpu.regs[1];g_edx=input_cpu.regs[2];g_ebx=input_cpu.regs[3];
            g_esp=input_cpu.regs[4];g_ebp=input_cpu.regs[5];g_esi=input_cpu.regs[6];g_edi=input_cpu.regs[7];
            g_backedges=0;events=0;heap_top=0x100000u;
            double t0=seconds();fn();total+=seconds()-t0;++calls;
        }
    }
    printf("BENCH %s %s %.3f us/call\n",assign?"assign":"find",name,1e6*total/calls);
}
int main(int argc,char **argv){
    if(argc>1&&!strcmp(argv[1],"bench")){
        unsigned rounds=argc>2?(unsigned)atoi(argv[2]):50;
        bench(0,FIND_BODY,"original",rounds);bench(0,void_ai_name_find,"native",rounds);
        bench(1,ASSIGN_BODY,"original",rounds);bench(1,void_ai_string_assign,"native",rounds);
        return 0;
    }
    unsigned cases=argc>1&&!strncmp(argv[1],"cases=",6)?(unsigned)atoi(argv[1]+6):CASES;
    unsigned find_native=0,assign_native=0,yields=0;
    for(unsigned i=0;i<cases;i++){
        ++case_number;
        unsigned before=native_runs;
        if(compare(i*0x9E3779B9u+17u,0))return 1;
        find_native+=native_runs-before;
        for(unsigned e=0;e<oracle_events;e++)if(oracle_log[e].kind==9){yields++;break;}
        ++case_number;before=native_runs;
        if(compare(i*0x85EBCA6Bu+29u,1))return 1;
        assign_native+=native_runs-before;
        for(unsigned e=0;e<oracle_events;e++)if(oracle_log[e].kind==9){yields++;break;}
    }
    printf("PASS %d cases (find native %u, assign native %u, cases with hand-overs %u): full guest memory/GPR/flags/backedges/TRACE/callee/hand-over state\n",
           case_number,find_native,assign_native,yields);
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
#undef ADDR
#define ADDR(va) ((uintptr_t)((uint32_t)(va) & 0x1FFFFFu) + (uintptr_t)memory)
const char *void_data_dir(void);
void void_log(const char *fmt, ...);
uint64_t void_perf_now_ns(void);
_Noreturn void void_fatal(const char *fmt, ...);
'''


class AiNamesNativeTest(unittest.TestCase):
    bodies = None

    @classmethod
    def setUpClass(cls):
        cls.bodies = production_bodies()

    def probe(self, edition, label, source=None, trace=True, cases=3000):
        out = HERE / ("probe-" + label)
        out.mkdir(parents=True, exist_ok=True)
        mapping = ADDRESSES[edition]
        oracle = "\n".join(self.bodies[edition + ":sub_" + mapping[a]] for a in bodies_of(edition))
        oracle = oracle.replace("void sub_%s(void) {" % mapping["00BD1150"], "void oracle_find(void) {", 1)
        oracle = oracle.replace("void sub_%s(void) {" % mapping["00404150"], "void oracle_assign(void) {", 1)
        oracle += ("\nvoid sub_%s(void){++oracle_calls;oracle_find();}\nvoid sub_%s(void){++oracle_calls;oracle_assign();}\n"
                   % (mapping["00BD1150"], mapping["00404150"]))
        strncmp =self.bodies[edition + ":sub_" + STRNCMP].replace("void sub_" + STRNCMP + "(void) {",
                                                                   "void STRNCMP_BODY(void) {", 1)
        protos = "".join("void sub_%s(void);\n" % mapping[a] for a in bodies_of(edition))
        names = (protos + "void oracle_find(void);\nvoid oracle_assign(void);\n#define FIND_BODY oracle_find\n"
                 "#define ASSIGN_BODY oracle_assign\n#define MALLOC sub_%s\n#define FREE sub_%s\n#define CASES %du\n"
                 % (mapping["008791F0"], mapping["00879240"], cases))
        # The IAT slots the cases fill are ToE's: the harness rewrites them per edition.
        prefix = HARNESS.replace("0x00E0A2B0", "0x" + mapping["00E0A2B0"]).replace("0x00E0A2A4", "0x" + mapping["00E0A2A4"])
        if trace:
            prefix = prefix.replace("#define RECOMP_X87_WINDOW", "#define RECOMP_X87_WINDOW\n#define RECOMP_TRACE", 1)
        native = adapt((source if source is not None else SOURCE.read_text(encoding="utf-8")), edition)
        header = (ROOT / "android/runtime/recomp_types.h").read_text()
        files = {"probe.c": prefix, "oracle.h": strncmp + "\n" + oracle, "names.h": names, "native.c": native,
                 "native_mode.h": (ROOT / "android/host/native_mode.h").read_text(encoding="utf-8"),
                 "host.h": NATIVE_HOST.replace("#define RECOMP_X87_WINDOW", "#define RECOMP_X87_WINDOW\n#define RECOMP_TRACE" if trace else "#define RECOMP_X87_WINDOW"),
                 "recomp_types.h": pc_header(header)}
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
                                timeout=900, creationflags=subprocess.CREATE_NO_WINDOW)
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
                find, assign, yields = map(int, re.search(r"find native (\d+), assign native (\d+), cases with hand-overs (\d+)",
                                                          result.stdout).groups())
                self.assertGreater(find, 1500, result.stdout)
                self.assertGreater(assign, 1200, result.stdout)
                self.assertGreater(yields, 150, result.stdout)
                print(edition + ": " + result.stdout.strip().splitlines()[-1])

    def test_contract_addresses(self):
        source = "android/host/ai_names_native.c"
        for edition in ("vanilla", "hof"):
            with self.subTest(edition=edition):
                contract = json.loads((ROOT / "config" / (edition + ".patches.json")).read_text(encoding="utf-8"))
                self.assertEqual(sorted(contract["reference_addresses"][source]), sorted(KERNEL_ADDRESSES))
                self.assertEqual({a: contract["addresses"][a] for a in KERNEL_ADDRESSES},
                                 {a: ADDRESSES[edition][a] for a in KERNEL_ADDRESSES})

    def test_without_trace(self):
        out = self.probe("toe", "toe-notrace", trace=False, cases=1500)
        self.assertIn("PASS", self.run_probe(out).stdout)

    def mutant(self, label, old, new, edition="toe"):
        source = SOURCE.read_text(encoding="utf-8")
        self.assertEqual(source.count(old), 1, old)
        out = self.probe(edition, "mutant-" + label, source=source.replace(old, new), cases=1500)
        result = self.run_probe(out, check=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("DIFFERENTIAL FAIL", result.stderr)

    def test_reject_unsigned_hash_byte(self):
        self.mutant("hashbyte", "hash = hash * 5u + (uint32_t)(int32_t)(int8_t)c;", "hash = hash * 5u + c;")

    def test_reject_strncmp_order(self):
        self.mutant("order", "if (a > b) return 0xFFFFFFFFu;", "if (a < b) return 0xFFFFFFFFu;")

    def test_reject_missing_call_frame(self):
        self.mutant("frame", "st32(esp0 - 48u, ebx0);", "(void)0;")

    def test_reject_ignored_handover(self):
        self.mutant("handover", "            if (++g_backedges >= RECOMP_YIELD_EVERY && recomp_yield_hook) {",
                    "            if (++g_backedges && 0) {")

    def test_reject_push_back_slot(self):
        self.mutant("pushslot", "st32(p - 12u, g_esi);", "st32(p - 12u, esi);")


    def test_reject_legacy_copy_register(self):
        self.mutant("legacy-dl", "edx = (edx & ~0xFFu) | c;\n        ++eax; ++esi;", "(void)c;\n        ++eax; ++esi;", "vanilla")

    def test_reject_legacy_grow_request(self):
        self.mutant("legacy-grow", "ecx = eax < ebp ? esp + 0x18u : esp + 0x10u;", "ecx = eax < ebp ? esp + 0x10u : esp + 0x18u;", "hof")

    def test_reject_legacy_ignored_handover(self):
        self.mutant("legacy-handover", "before the hand-over */\n        if (++g_backedges >= RECOMP_YIELD_EVERY && recomp_yield_hook) {",
                    "before the hand-over */\n        if (++g_backedges && 0) {", "hof")

    def test_reject_legacy_append_frame(self):
        self.mutant("legacy-frame", "st32(entry - 20u, g_ebp);", "st32(entry - 20u, 1u);", "vanilla")


if __name__ == "__main__":
    unittest.main()
