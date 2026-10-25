"""Run the native EOF correction around the complete original FMOD worker."""
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN

COMPILER = (TOOLCHAIN / 'bin/clang-cl.exe')
sys.path.insert(0, str(ROOT / "tools"))   # build_android.py imports its sibling transforms
SPEC = importlib.util.spec_from_file_location("audio_builder", ROOT / "tools/build_android.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x11070000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#include "runtime.h"
uint32_t g_eax,g_ecx,g_edx,g_esp,g_ebx,g_esi,g_edi,g_ebp;
double g_st[8];int g_fp_top,void_fpu_cmp;uint16_t g_fpu_cw;int64_t g_st_i64[8];
uint64_t g_mm[8];xmm_t g_xmm[8];uint32_t g_mxcsr;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_cur_func;
uint32_t g_enter_trace[1024],g_enter_idx;
uint32_t g_icall_trace[ICALL_TRACE_SIZE],g_icall_from[ICALL_TRACE_SIZE],g_icall_trace_idx;
uint32_t g_backedges;void (*recomp_yield_hook)(void);
static uint64_t clock_ns,pause_state,lock_wait_ns;
static uint64_t decoder_delay_ns;
static uint32_t thread_id=7, bad_range, read_only;
static unsigned stops,callbacks,decoder_calls,reset_calls,original_calls;
static uint32_t callback_stream,callback_user,seed_q8;
static unsigned decode_epoch,change_pause,remove_stream;
static int void_vm_readable(uint32_t a,uint32_t n) {
    return a>=0x10000 && (uint64_t)a+n<=sizeof memory &&
        (!bad_range || !((uint64_t)a<bad_range+0x100u && (uint64_t)a+n>bad_range));
}
static int void_vm_writable(uint32_t a,uint32_t n) { return !read_only && void_vm_readable(a,n); }
static uint32_t void_thread_id(void) { return thread_id; }
static uint64_t void_monotonic_ns(void) { return clock_ns; }
static uint64_t void_audio_pause_state(void) { return pause_state; }
static uint64_t void_lock_wait_ns(void) { return lock_wait_ns; }
#define ARG(i) MEM32(g_esp+4u+4u*(i))
/* NATIVE */

/* Stubs are the original worker's external host/decoder boundaries.  The
   complete BC0B and D53A bodies, runtime transfers, flags and x87 helpers
   below are production code, not a second implementation of the drain. */
static void return_cdecl(void) { g_esp+=4; }
void sub_11027BD5(void) {g_eax=0;g_esp+=8;}
void sub_11027121(void) {g_eax=44100;g_esp+=8;}
void sub_1102787B(void) {
    uint32_t h=ARG(0),ch=0x30000+(h&0xFFFu)*0x1DCu;
    g_eax=(MEM32(ch+0x3C)>>4)&1;g_esp+=8;
}
void sub_110124F4(void) {return_cdecl();}
void sub_11012500(void) {fp_push(0.25);return_cdecl();}
void sub_1102BAD0(void) {
    ++decoder_calls;
    clock_ns+=decoder_delay_ns;
    uint32_t s=ARG(0);if(seed_q8)MEM32(s+0x374)=seed_q8;
    if(decode_epoch)sub_1102B635();
    if(change_pause)pause_state+=4;
    if(remove_stream)MEM32(0x10000+0x295C)=0x10000+0x295C;
    return_cdecl();
}
void sub_1102E5FE(void) {g_eax=123;g_esp+=4;}
void sub_1102E414(void) {g_eax=456;g_esp+=4;}
void sub_1102AF8C(void) {assert(0);}
void sub_1101239A(void) {g_eax=thread_id;g_esp+=4;}
void sub_11026F36(void) {++stops;g_eax=1;g_esp+=8;}
void sub_110125E8(void) {return_cdecl();}
void sub_1101247D(void) {return_cdecl();}
void sub_1101248F(void) {return_cdecl();}
static void ended(void) {
    ++callbacks;callback_stream=ARG(0);callback_user=ARG(3);
    assert(ARG(1)==0 && ARG(2)==0);g_esp+=20;
}
recomp_func_t void_resolve(uint32_t address) {assert(address==0x70000);return ended;}
/* LIFTED_DECLS */
/* LIFTED */

typedef struct {
    uint32_t registers[8],flags[4],cur,enter_idx,enter[1024];
    uint32_t icall_idx,icall[ICALL_TRACE_SIZE],from[ICALL_TRACE_SIZE];
    uint64_t st[8],mm[8];int64_t shadows[8];xmm_t xmm[8];
    int top,cmp;uint16_t cw;uint32_t mxcsr,backedges;
    unsigned char memory[0x42000];uint32_t error;uint8_t callback_gate;
} saved;
static saved initial,expected,actual;
static void take(saved *s) {
    memset(s,0,sizeof *s);
    const uint32_t regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi};
    const uint32_t flags[]={g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    memcpy(s->registers,regs,sizeof regs);memcpy(s->flags,flags,sizeof flags);
    memcpy(s->st,g_st,sizeof g_st);memcpy(s->shadows,g_st_i64,sizeof g_st_i64);
    memcpy(s->mm,g_mm,sizeof g_mm);memcpy(s->xmm,g_xmm,sizeof g_xmm);
    s->top=g_fp_top;s->cmp=void_fpu_cmp;s->cw=g_fpu_cw;s->mxcsr=g_mxcsr;s->cur=g_cur_func;
    s->backedges=g_backedges;s->callback_gate=MEM8(0x1106BFC8);
    s->enter_idx=g_enter_idx;memcpy(s->enter,g_enter_trace,sizeof s->enter);
    s->icall_idx=g_icall_trace_idx;memcpy(s->icall,g_icall_trace,sizeof s->icall);
    memcpy(s->from,g_icall_from,sizeof s->from);
    memcpy(s->memory,memory+0x10000,sizeof s->memory);s->error=MEM32(0x11065C18);
}
static void restore(const saved *s) {
    g_eax=s->registers[0];g_ecx=s->registers[1];g_edx=s->registers[2];g_ebx=s->registers[3];
    g_esp=s->registers[4];g_ebp=s->registers[5];g_esi=s->registers[6];g_edi=s->registers[7];
    g_flag_k=s->flags[0];g_flag_a=s->flags[1];g_flag_b=s->flags[2];g_flag_cf=s->flags[3];
    memcpy(g_st,s->st,sizeof g_st);memcpy(g_st_i64,s->shadows,sizeof g_st_i64);
    memcpy(g_mm,s->mm,sizeof g_mm);memcpy(g_xmm,s->xmm,sizeof g_xmm);
    g_fp_top=s->top;void_fpu_cmp=s->cmp;g_fpu_cw=s->cw;g_mxcsr=s->mxcsr;g_cur_func=s->cur;
    g_backedges=s->backedges;MEM8(0x1106BFC8)=s->callback_gate;
    g_enter_idx=s->enter_idx;memcpy(g_enter_trace,s->enter,sizeof s->enter);
    g_icall_trace_idx=s->icall_idx;memcpy(g_icall_trace,s->icall,sizeof s->icall);
    memcpy(g_icall_from,s->from,sizeof s->from);
    memcpy(memory+0x10000,s->memory,sizeof s->memory);MEM32(0x11065C18)=s->error;
}
static uint32_t stream_at(unsigned i) {return 0x20000u+i*0x600u;}
static void setup(unsigned count,uint32_t remaining) {
    memset(memory+0x10000,0,0x42000);memset(&previous,0,sizeof previous);
    reset_epoch=0;clock_ns=1000000000u;pause_state=lock_wait_ns=0;thread_id=7;bad_range=read_only=0;
    stops=callbacks=decoder_calls=reset_calls=original_calls=0;
    seed_q8=decode_epoch=change_pause=remove_stream=0;decoder_delay_ns=0;
    MEM32(0x110472D0)=0x10000;MEM32(0x10000+0x298C)=7;
    MEM32(0x10000+0x14A8)=0x30000;MEM32(0x10000+0x14EC)=64;
    MEM32(0x10000+0x14AC)=1;
    MEM32(0x10000+0x295C)=count?stream_at(0):0x1295C;
    for(unsigned i=0;i<count;++i) {
        uint32_t s=stream_at(i),sample=0x40000+i*0x200,ch=0x30000+i*0x1DC;
        MEM32(s)=i+1<count?stream_at(i+1):0x1295C;
        MEM32(s+0x30)=sample;MEM32(s+0x2F0)=0x1000+i;
        MEM32(s+0x2C4)=0x1102B635;MEM32(s+0x2CC)=0x70000;
        MEM32(s+0x334)=0x12345678+i;MEM32(s+0x374)=remaining;
        MEM8(s+0x4D4)=1;MEM8(s+0x4D6)=1;
        MEM32(sample+0x10C)=131072;MEM32(sample+0x128)=44100;
        MEM32(ch+0x14)=0x1000+i;MEM32(ch+0x5C)=sample;
    }
    g_eax=0x11223344;g_ecx=0x55667788;g_edx=0x99AABBCC;g_ebx=0x12345678;
    g_esi=0x9ABCDEF0;g_edi=0x76543210;g_ebp=0xAABBCCDD;g_esp=0x51000;
    MEM32(g_esp)=0xDEAD1111;MEM32(g_esp+4)=10;
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=UINT64_C(0x7FF8123456700000)+i;memcpy(g_st+i,&bits,8);
        g_st_i64[i]=INT64_C(0x123456789ABCDE)+i;g_mm[i]=bits;
        memset(&g_xmm[i],(int)(0xA0+i),sizeof g_xmm[i]);
    }
    g_fp_top=3;void_fpu_cmp=0x123456;g_fpu_cw=0xF7F;g_mxcsr=0x1FA0;
    g_backedges=1234567;MEM8(0x1106BFC8)=0xA5;
    g_flag_k=FK_CMP;g_flag_a=0x1234;g_flag_b=0x89AB;g_flag_cf=1;
    g_enter_idx=1023;g_icall_trace_idx=ICALL_TRACE_SIZE-1;
}
static uint32_t remaining(void) {return MEM32(stream_at(0)+0x374);}
static void tick(unsigned ms,int native) {
    clock_ns+=(uint64_t)ms*1000000u;g_esp=0x51000;MEM32(g_esp+4)=10;
    if(native)sub_1102BC0B();else sub_1102BC0B_lifted();
    assert(g_esp==0x51004);
}
static void equivalent(void) {
    take(&initial);sub_1102BC0B_lifted();take(&expected);
    restore(&initial);sub_1102BC0B();take(&actual);
    assert(!memcmp(&expected,&actual,sizeof expected));
}
int main(void) {
    /* Whole-result ABI/memory/NaN payload/trace equality for original ticks,
       first observation, empty list, callback and conservative fallbacks. */
    for(unsigned i=0;i<48;++i) {
        setup(i%4,1000*256u);g_fp_top=(int)(i%17)-8;
        if(i%4==1)MEM32(stream_at(0)+0x374)=5*256u;
        if(i%4==2)MEM32(0x30000+0x3C)=0x10;
        equivalent();
    }
    setup(1,1000*256);tick(10,1);
    for(unsigned i=0;i<20;++i) {clock_ns+=10000000;g_esp=0x51000;equivalent();}
    /* Late worker loses no EOF wall time; original nominal policy is the
       negative control, needing roughly twice as long for identical calls. */
    setup(1,1000*256);tick(20,1);
    for(unsigned i=0;i<49;++i)tick(20,1);
    assert(remaining()==10*256 && callbacks==0);tick(20,1);
    assert(callbacks==1 && stops==1 && callback_stream==stream_at(0) && callback_user==0x12345678);
    setup(1,1000*256);for(unsigned i=0;i<51;++i)tick(20,0);
    assert(remaining()==490*256 && callbacks==0);
    /* Corrected expiration stays zero until ORIGINAL stop/callback nextpass. */
    setup(1,100*256);tick(20,1);tick(100,1);
    assert(remaining()==0 && callbacks==0 && !MEM8(stream_at(0)+0x4D5));
    tick(1,1);assert(callbacks==1 && stops==1);tick(1,1);assert(callbacks==1);
    /* Never resurrect a stop already performed by the original nominal tick. */
    setup(1,15*256);tick(1,1);tick(1,1);assert(callbacks==1);
    /* First seed inside decoder, even after a long stall, gets original10ms. */
    setup(1,UINT32_MAX);MEM32(stream_at(0)+0x2E8)=1;seed_q8=1000*256;decode_epoch=1;
    tick(200,1);assert(remaining()==990*256);MEM32(stream_at(0)+0x2E8)=0;seed_q8=decode_epoch=0;
    tick(20,1);assert(remaining()==970*256);
    /* Invisible seek/reset ABA and pause/resume ABA invalidate elapsed even
       if all observed pointers, handles and remaining values are identical. */
    setup(1,1000*256);tick(20,1);uint32_t held=remaining();
    sub_1102B103();MEM32(stream_at(0)+0x374)=held;tick(100,1);assert(remaining()==held-10*256);
    held=remaining();sub_110277DD();sub_110277DD();tick(100,1);assert(remaining()==held-10*256);
    held=remaining();pause_state+=4;tick(100,1);assert(remaining()==held-10*256);
    held=remaining();pause_state|=1;tick(100,1);assert(remaining()==held-10*256);
    pause_state+=1;held=remaining();tick(100,1);assert(remaining()==held-10*256);
    tick(20,1);assert(remaining()==held-30*256);
    /* Lifecycle change during decoder and list removal cannot use pre-state. */
    setup(1,1000*256);tick(20,1);held=remaining();MEM32(stream_at(0)+0x2E8)=1;change_pause=1;
    tick(100,1);assert(remaining()==held-10*256 && previous.size==0);
    setup(1,1000*256);tick(20,1);held=remaining();MEM32(stream_at(0)+0x2E8)=1;remove_stream=1;
    tick(100,1);assert(remaining()==held-10*256 && previous.size==0);
    /* 250ms exact bound, backwards clock, worker, arg and malformed list
       all fall back without extra guest mutations. */
    setup(1,1000*256);tick(10,1);held=remaining();tick(251,1);assert(remaining()==held-10*256);
    setup(1,1000*256);tick(10,1);held=remaining();tick(250,1);assert(remaining()==held-250*256);
    /* Channel generation and sample reuse are distinct epochs, even when
       their counters and addresses otherwise look unchanged. */
    setup(1,1000*256);tick(20,1);held=remaining();
    MEM32(stream_at(0)+0x2F0)=MEM32(0x30000+0x14)=0x2000;
    tick(100,1);assert(remaining()==held-10*256);
    held=remaining();MEM32(stream_at(0)+0x30)=0x48000;
    MEM32(0x48000+0x10C)=131072;MEM32(0x48000+0x128)=44100;MEM32(0x30000+0x5C)=0x48000;
    tick(100,1);assert(remaining()==held-10*256);
    setup(1,1000*256);tick(10,1);held=remaining();
    held=remaining();clock_ns-=1000000000u;tick(1,1);assert(remaining()==held-10*256);
    setup(1,1000*256);tick(10,1);thread_id=8;equivalent();
    setup(1,1000*256);tick(10,1);MEM32(0x51004)=11;g_esp=0x51000;equivalent();
    setup(1,1000*256);tick(10,1);bad_range=0x30000;g_esp=0x51000;equivalent();
    setup(1,1000*256);tick(10,1);read_only=1;g_esp=0x51000;equivalent();
    setup(33,1000*256);equivalent();
    /* Invalid metadata is rejected before any guest counter write.  Do not
       run the original on a corrupt cyclic list: its unbounded walk has no
       defined safe fallback; snapshot() alone must terminate here. */
    stream_list invalid;
    setup(1,1000*256);MEM32(stream_at(0))=stream_at(0);assert(!snapshot(&invalid));
    MEM32(stream_at(0))=0x1295C;MEM32(0x10000+0x14A8)=UINT32_MAX-4;assert(!snapshot(&invalid));
    MEM32(0x10000+0x14A8)=0x30000;MEM32(0x10000+0x14EC)=UINT32_MAX;assert(!snapshot(&invalid));
    setup(1,1000*256);MEM32(0x110472D0)=UINT32_MAX-4;assert(!snapshot(&invalid));
    /* An ordinary stale resident stream does not suppress the live stream. */
    setup(2,1000*256);MEM32(stream_at(1)+0x2F0)=UINT32_MAX;
    tick(20,1);tick(20,1);assert(remaining()==970*256);
    /* Different streams do not inherit elapsed time before their own EOF.
       An actual reset hook also conservatively rebases the older stream. */
    setup(2,1000*256);MEM32(stream_at(1)+0x374)=UINT32_MAX;tick(20,1);
    MEM32(stream_at(1)+0x2E8)=1;seed_q8=1000*256;decode_epoch=1;tick(100,1);
    assert(remaining()==980*256 && MEM32(stream_at(1)+0x374)==990*256);
    MEM32(stream_at(1)+0x2E8)=0;seed_q8=decode_epoch=0;tick(20,1);
    assert(remaining()==960*256 && MEM32(stream_at(1)+0x374)==970*256);
    /* Exact sub-ms Q8 accumulation and bounded integer arithmetic. */
    setup(1,INT32_MAX);tick(10,1);held=remaining();
    for(unsigned i=0;i<100;++i){clock_ns+=10390625;g_esp=0x51000;sub_1102BC0B();}
    assert(remaining()==held-266000u);
    assert(q8_time(UINT64_MAX)>q8_time(UINT64_MAX-1000000u));
    /* Diagnostic observation is bounded and cannot change guest behavior.
       Force75 real late-tick skips; circular overwrite is explicit. */
    assert(sizeof(drain_trace_event)==104 && sizeof(drain_trace)==6776);
    assert(void_fmod_drain_trace.magic==0x48354644 && void_fmod_drain_trace.capacity==64);
    setup(1,1000*256);tick(10,1);
    uint64_t total_before=void_fmod_drain_trace.total,long_before=void_fmod_drain_trace.reasons[6];
    for(unsigned i=0;i<75;++i)tick(251,1);
    assert(remaining()==240*256 && callbacks==0);
    assert(void_fmod_drain_trace.total==total_before+75);
    assert(void_fmod_drain_trace.reasons[6]==long_before+75);
    assert(void_fmod_drain_trace.overflow==void_fmod_drain_trace.total-64);
    assert(!(void_fmod_drain_trace.sequence&1) && void_fmod_drain_trace.max_delta_ns>=251000000);
    drain_trace_event last=void_fmod_drain_trace.events[(void_fmod_drain_trace.total-1)%64];
    assert(last.reasons==DRAIN_LONG && last.now_ns-last.previous_ns==251000000);
    assert(last.before_q8==last.expected_q8 && last.after_q8==last.before_q8-10*256);
    assert(last.previous_reset==last.reset_before && last.reset_before==last.reset_after);
    assert(last.entry_ns==last.now_ns);
    setup(1,1000*256);tick(10,1);MEM32(stream_at(0)+0x2E8)=1;decoder_delay_ns=500000000;
    tick(20,1);last=void_fmod_drain_trace.events[(void_fmod_drain_trace.total-1)%64];
    assert(last.reasons==DRAIN_LONG && last.now_ns-last.previous_ns==520000000);
    assert(last.now_ns-last.entry_ns==500000000 && last.before_half==1 && last.after_half==1);
#ifdef _WIN32
    FILE *wire=fopen("/* TRACE_OUTPUT */","wb");assert(wire);
    assert(fwrite((const void*)&void_fmod_drain_trace,1,sizeof(drain_trace),wire)==sizeof(drain_trace));
    assert(!fclose(wire));
#endif
    puts("PASS FMOD EOF: actual whole worker/stop, strict state/trace, real-time drain, fresh seed, pause/seek ABA, bounds and original callback ownership");
    return 0;
}
'''


def fmod_overrides():
    """The native overrides whose lifted bodies are FMOD's (the others are the game's)."""
    sources = [path.read_bytes() for path in (ROOT / "generated/fmod-x86").glob("fmod_*.c")]
    return {name for name in BUILDER.NATIVE_OVERRIDES
            if any(b"\nvoid %s(void) {" % name.encode() in source for source in sources)}


def fixture():
    runtime = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
    # Host compiler gets the same operation/ABI macros; only target guard and
    # unused ARM counter intrinsic are excluded from the portable oracle.
    runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
    runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
    native = (ROOT / "android/host/fmod_stream.c").read_text(encoding="utf-8").replace('#include "host.h"', "")
    source = (ROOT / "generated/fmod-x86/fmod_0014.c").read_text(encoding="utf-8")
    stop_source = (ROOT / "generated/fmod-x86/fmod_0015.c").read_text(encoding="utf-8")
    worker = function(source, "void sub_1102BC0B(").replace("void sub_1102BC0B(", "void sub_1102BC0B_lifted(", 1)
    stop = function(stop_source, "void sub_1102D53A(").replace("void sub_1102D53A(", "void sub_1102D53A_lifted(", 1)
    stubs = []
    for name in BUILDER.NATIVE_OVERRIDES:
        if name not in ("sub_1102BC0B", "sub_1102D53A"):
            stubs.append(f"void {name}_lifted(void) {{++reset_calls;}}")
    harness = HARNESS.replace("/* NATIVE */", native)
    harness = harness.replace("/* TRACE_OUTPUT */", str(ROOT / "build/tests/fmod_stream/fmod-drain-test.bin").replace("\\", "/"))
    harness = harness.replace("/* LIFTED_DECLS */", "\n".join(stubs))
    harness = harness.replace("/* LIFTED */", worker + "\n" + stop)
    return harness, {"runtime.h": runtime}


class FmodStreamTest(unittest.TestCase):
    def test_ordinary_other_stream_refill_preserves_eof_elapsed(self):
        harness, headers = fixture()
        harness = harness.replace("static uint64_t decoder_delay_ns;",
                                  "static uint64_t decoder_delay_ns; static uint32_t inner_seed, inner_sample;")
        harness = harness.replace("void sub_1102B635_lifted(void) {++reset_calls;}", r'''
void sub_1102B635_lifted(void) {
    ++reset_calls;
    if(inner_seed) MEM32(ARG(0)+0x374)=inner_seed;
    if(inner_sample) MEM32(ARG(0)+0x30)=inner_sample;
}
''')
        harness = harness.replace("int main(void) {", "int drain_main(void) {", 1)
        harness += r'''
int main(void) {
    /* The actual worker sees A drain while B continues its ordinary decode.
       B's refill must not turn A's elapsed100ms into nominal10ms. */
    setup(2,1000*256);MEM32(stream_at(1)+0x374)=UINT32_MAX;tick(20,1);
    MEM32(stream_at(1)+0x2E8)=1;decode_epoch=1;tick(100,1);
    assert(remaining()==890*256 && MEM32(stream_at(1)+0x374)==UINT32_MAX);
    assert(reset_epoch==0);
    /* A fresh EOF still conservatively rebases all observed drains. */
    seed_q8=1000*256;tick(100,1);
    assert(remaining()==880*256 && MEM32(stream_at(1)+0x374)==990*256);
    assert(reset_epoch==1);
    /* Every overlapping entry sees the same ESI stream. Ordinary refill is
       harmless; an already-active, equal-valued countdown is an ABA reset. */
    void (*aliases[])(void)={sub_1102B659,sub_1102B6BB,sub_1102B6F8,sub_1102B716,
        sub_1102B7CA,sub_1102B844,sub_1102B8A8,sub_1102B9C5,sub_1102BAB5,sub_1102BABE};
    for(unsigned i=0;i<sizeof aliases/sizeof aliases[0];++i) {
        setup(1,UINT32_MAX);g_esi=stream_at(0);aliases[i]();assert(reset_epoch==0);
        setup(1,1000*256);tick(20,1);uint32_t held=remaining();
        g_esi=stream_at(0);aliases[i]();assert(reset_epoch==1);
        tick(100,1);assert(remaining()==held-10*256);
        g_esi=0;aliases[i]();assert(reset_epoch==2);
    }
    /* A new seed or identity change inside the lifted decoder is observed
       AFTER it returns, without modifying any of its guest ABI output. */
    setup(1,UINT32_MAX);MEM32(g_esp+4)=stream_at(0);inner_seed=1000*256;
    take(&initial);sub_1102B635_lifted();take(&expected);
    restore(&initial);sub_1102B635();take(&actual);
    assert(!memcmp(&expected,&actual,sizeof expected) && reset_epoch==1);
    inner_seed=0;setup(1,UINT32_MAX);MEM32(g_esp+4)=stream_at(0);inner_sample=0x48000;
    sub_1102B635();assert(reset_epoch==1);inner_sample=0;
    setup(1,UINT32_MAX);g_esp=0;sub_1102B635();assert(reset_epoch==1);
    puts("PASS decoder epochs: independent stream EOF clock, new seed, equal-valued ABA, all ESI aliases, invalid identity, exact guest ABI");
    return 0;
}
'''
        flags = ("/O2", "/DVOID_ANDROID_APP", "/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS", "/DRECOMP_TRACE",
                 "/clang:-Wno-unused-label", "/clang:-Wno-unused-variable", "/clang:-Wno-unused-function",
                 "/clang:-Wno-ignored-attributes", "/clang:-ffp-contract=off")
        compile_probe("fmod_decoder_epoch", harness, headers, extra_flags=flags, compiler_override=COMPILER)
        # The previous unconditional epoch policy must fail the real two-stream case.
        broken = harness.replace("if (!epoch.normal) ++reset_epoch;", "++reset_epoch;")
        self.assertNotEqual(broken, harness)
        with self.assertRaisesRegex(AssertionError, "Assertion failed"):
            compile_probe("fmod_decoder_epoch_bad", broken, headers, extra_flags=flags, compiler_override=COMPILER)

    def test_refill_trace_preserves_abi_and_distinguishes_cursor_deadline(self):
        harness, headers = fixture()
        harness = harness.replace("static uint64_t decoder_delay_ns;", "static uint64_t decoder_delay_ns; static uint32_t trace_cursor;")
        harness = harness.replace("void sub_1102B635_lifted(void) {++reset_calls;}", r'''
void sub_1102B635_lifted(void) {
    ++reset_calls;clock_ns+=decoder_delay_ns;
    lock_wait_ns+=decoder_delay_ns/2;
    MEM32(0x30000+0x80)=trace_cursor;
    if(change_pause) pause_state+=4;
    g_eax=0x12345601;g_edx=0x89ABCDEF;g_esp+=4;
}
''')
        harness = harness.replace("int main(void) {", "int drain_main(void) {", 1)
        harness += r'''
static void trace_setup(uint32_t cursor,uint32_t next,unsigned ms) {
    setup(1,UINT32_MAX);
    MEM32(0x40000+0x104)=0x80000;MEM32(0x40000+0x124)=0x50;
    MEM32(0x40000+0x194)=0x1101325D;MEM32(0x40000+0x198)=0x11013488;
    MEM32(0x30000+0x1B0)=0x11013C79;MEM32(0x30000+0x20)=44100;
    MEM32(0x30000+0x80)=cursor;
    MEM32(g_esp+4)=stream_at(0);MEM32(g_esp+8)=0x80000;MEM32(g_esp+12)=262144;
    decoder_delay_ns=(uint64_t)ms*1000000;trace_cursor=next;
}
int main(void) {
    trace_setup(70000,90000,500);
    take(&initial);sub_1102B635_lifted();take(&expected);
    restore(&initial);clock_ns=1000000000;sub_1102B635();take(&actual);
    assert(!memcmp(&expected,&actual,sizeof expected));
    assert(void_fmod_refill_trace.total==1 && !void_fmod_refill_trace.events[0].reasons);
    assert(void_fmod_refill_trace.events[0].result==1 && void_fmod_refill_trace.max_refill_ns==500000000);
    assert(sizeof(refill_event)==104 && void_fmod_refill_trace.version==2);
    assert(void_fmod_refill_trace.events[0].lock_wait_us==250000);
    trace_setup(70000,20000,2000);sub_1102B635();
    assert(void_fmod_refill_trace.events[1].reasons==6);
    assert(void_fmod_refill_trace.cursor_crossings==1 && void_fmod_refill_trace.wall_late==1);
    /* A stopped software cursor is late in wall time, but has not consumed
       the half: do not mislabel it as a measured cursor crossing. */
    trace_setup(70000,70000,2000);sub_1102B635();
    assert(void_fmod_refill_trace.events[2].reasons==4 && void_fmod_refill_trace.cursor_crossings==1);
    trace_setup(10000,12000,100);sub_1102B635();
    assert(void_fmod_refill_trace.events[3].reasons==1 && void_fmod_refill_trace.overlap_starts==1);
    trace_setup(70000,20000,2000);change_pause=1;sub_1102B635();
    assert(void_fmod_refill_trace.events[4].reasons==12 && void_fmod_refill_trace.state_changes==1);
    trace_setup(70000,90000,500);MEM32(0x40000+0x194)=0;sub_1102B635();
    assert(void_fmod_refill_trace.total==5 && reset_calls==1 && g_eax==0x12345601);
    for(unsigned i=0;i<140;++i) {trace_setup(70000,90000,500);sub_1102B635();}
    assert(void_fmod_refill_trace.total==145 && void_fmod_refill_trace.sequence==290);
    assert(void_fmod_refill_trace.events[144%128].end_cursor==90000);
    puts("PASS refill diagnostics: exact guest ABI, write-half cursor crossing, wall-only stall, overlap, pause, rejected backend, bounded ring");
    return 0;
}
'''
        compile_probe("fmod_refill_trace", harness, headers,
                      extra_flags=("/O2", "/DVOID_ANDROID_APP", "/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS", "/DRECOMP_TRACE",
                                   "/clang:-Wno-unused-label", "/clang:-Wno-unused-variable", "/clang:-Wno-unused-function",
                                   "/clang:-Wno-ignored-attributes", "/clang:-ffp-contract=off"), compiler_override=COMPILER)

    def test_actual_lifted_worker_and_native_lifecycle(self):
        harness, headers = fixture()
        compile_probe("fmod_stream", harness, headers,
                      extra_flags=("/O2", "/DVOID_ANDROID_APP", "/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS", "/DRECOMP_TRACE",
                                   "/clang:-Wno-unused-label", "/clang:-Wno-unused-variable", "/clang:-Wno-unused-function",
                                   "/clang:-Wno-ignored-attributes", "/clang:-ffp-contract=off"), compiler_override=COMPILER)

    def test_override_copies_only_definitions_and_preserves_dispatch(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as tmp, patch.object(BUILDER, "OUT", Path(tmp)), \
                patch.object(BUILDER, "direct_jump_tables", side_effect=lambda text, image: text), \
                patch.object(BUILDER, "module_image", return_value=None):
            seen = set()
            for filename in ("fmod_0013.c", "fmod_0014.c", "fmod_0015.c", "recomp_dispatch.c"):
                source = ROOT / "generated/fmod-x86" / filename
                original = source.read_bytes()
                changed_path, _ = BUILDER.override_source(source, False)
                changed = changed_path.read_bytes()
                restored = changed
                for name in BUILDER.NATIVE_OVERRIDES:
                    before = b"\nvoid " + name.encode() + b"(void) {"
                    after = b"\nvoid " + name.encode() + b"_lifted(void) {"
                    if before in original:
                        seen.add(name)
                        self.assertEqual(changed.count(after), 1)
                        restored = restored.replace(after, before, 1)
                # Less the x87 precision rounding (tests/test_x87_precision.py).
                restored = re.sub(rb" ((?:_h5_fp\.st|_st)\[\d\]) = fp_pc\(\1\); (?=/\* 0x)", b" ", restored)
                restored = re.sub(rb"float _v = fp_f32\(([^;]+)\);", rb"float _v = (float)\1;", restored)
                restored = re.sub(rb"fp_set_cw\(([^;]+)\);", rb"_fpu_cw = \1;", restored)
                self.assertEqual(restored, original)
            self.assertEqual(seen, fmod_overrides())

    def test_negative_controls_reject_nominal_clock_and_reset_aba(self):
        harness, headers = fixture()
        for name, old, new in (
            ("nominal", "uint64_t elapsed = now - q8_time(old->time_ns);", "uint64_t elapsed = NOMINAL_Q8;"),
            ("reset_aba", "previous.reset == reset && reset == reset_epoch;", "1;"),
        ):
            self.assertIn(old, harness)
            with self.subTest(broken=name), self.assertRaisesRegex(AssertionError, "Assertion failed"):
                compile_probe("fmod_stream_bad_" + name, harness.replace(old, new), headers,
                              extra_flags=("/O2", "/DVOID_ANDROID_APP", "/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS", "/DRECOMP_TRACE",
                                           "/clang:-Wno-unused-label", "/clang:-Wno-unused-variable", "/clang:-Wno-unused-function",
                                           "/clang:-Wno-ignored-attributes", "/clang:-ffp-contract=off"), compiler_override=COMPILER)

    def test_all_reset_writers_and_pause_entries_are_hooked(self):
        writers = set()
        for path in (ROOT / "generated/fmod-x86").glob("*.c"):
            source = path.read_text(encoding="utf-8")
            for match in re.finditer(r"^void (sub_\w+)\(void\) \{([\s\S]*?)(?=^\})", source, re.M):
                if re.search(r"MEM32\([^\n]*0x374\) =", match[2]):
                    writers.add(match[1])
        fmod = fmod_overrides()
        self.assertEqual(writers | {"sub_110277DD"}, fmod)
        dispatch = (ROOT / "generated/fmod-x86/recomp_dispatch.c").read_text(encoding="utf-8")
        for name in fmod:
            self.assertIn("0x" + name[4:] + "u, " + name, dispatch)
        # Every override, the game's too, stays reachable through the linked (last module's) table.
        canonical = (ROOT / f"generated/{BUILDER.MODULES[-1]}-x86/recomp_dispatch.c").read_text(encoding="utf-8")
        for name in BUILDER.NATIVE_OVERRIDES:
            self.assertIn("0x" + name[4:] + "u, " + name, canonical)


if __name__ == "__main__":
    unittest.main()
