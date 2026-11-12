"""Exercise the mixer setting hook against each edition's actual FMOD code."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_d3d_lifecycle import function
from test_fmod_stream import COMPILER, HARNESS as STREAM_HARNESS
from test_static_tls import compile_probe

NATIVE = ROOT / "android/host/fmod_stream.c"
FLAGS = ("/O2", "/DVOID_ANDROID_APP", "/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS", "/DRECOMP_TRACE",
         "/clang:-Wno-unused-label", "/clang:-Wno-unused-variable", "/clang:-Wno-unused-function",
         "/clang:-Wno-ignored-attributes", "/clang:-ffp-contract=off")

HARNESS = r'''
typedef void (*void_fn)(void);
static void_fn dispatch;
static unsigned bindings,original_calls;
static int available;
void sub_11021F16(void);
static void original(void) { ++original_calls; sub_11021F16(); }
static void_fn void_dispatch_find(uint32_t address) {
    assert(address==0x11021F16);return available?dispatch:NULL;
}
static void void_dispatch_add(uint32_t address,void_fn fn) {
    assert(address==0x11021F16 && fn);dispatch=fn;++bindings;
}
/* NATIVE */
/* ORIGINAL */
/* SNAPSHOT */
static void setup(uint32_t argument,int busy) {
    memset(memory+0x10000,0,0x42000);
    MEM32(0x110472D0)=0x10000;MEM8(0x10020)=(uint8_t)busy;
    MEM32(0x1003C)=777;MEM32(0x11065C18)=999;read_only=0;
    g_eax=0x12345678;g_ecx=0x9ABCDEF0;g_edx=0x89ABCDEF;g_ebx=0x11223344;
    g_esi=0x55667788;g_edi=0xDEAD1234;g_ebp=0x1234DEAD;g_esp=0x51000;
    MEM32(g_esp)=0xBAD11111;MEM32(g_esp+4)=argument;
    for(unsigned i=0;i<8;++i) {
        uint64_t bits=UINT64_C(0x7FF8123456700000)+i;memcpy(g_st+i,&bits,8);
        g_st_i64[i]=INT64_C(0x123456789ABCDE)+i;g_mm[i]=bits;
        memset(&g_xmm[i],(int)(0xA0+i),sizeof g_xmm[i]);
    }
    g_fp_top=3;void_fpu_cmp=0x123456;g_fpu_cw=0xF7F;g_mxcsr=0x1FA0;
    g_flag_k=FK_CMP;g_flag_a=0x1234;g_flag_b=0x89AB;g_flag_cf=1;
    g_enter_idx=1023;g_icall_trace_idx=ICALL_TRACE_SIZE-1;
    memset(g_enter_trace,0xA5,sizeof g_enter_trace);
    memset(g_icall_trace,0xA6,sizeof g_icall_trace);
    memset(g_icall_from,0xA7,sizeof g_icall_from);
}
static void equivalent(uint32_t request,int busy,int readonly) {
    setup(request==100 && !readonly?50:request,busy);sub_11021F16();take(&expected);
    setup(request,busy);read_only=(uint32_t)readonly;unsigned before=original_calls;
    dispatch();take(&actual);
    assert(original_calls==before+1 && g_esp==0x51008);
    assert(!memcmp(&expected,&actual,sizeof expected));
    assert(LO8(g_eax)==(busy?0:1));
    assert(MEM32(0x11065C18)==(busy?1:0));
}
int main(void) {
    dispatch=original;available=0;void_fmod_latency_init();assert(!bindings);
    available=1;void_fmod_latency_init();assert(bindings==1 && dispatch==fmod_buffer_size);
    void_fmod_latency_init();assert(bindings==1);
    const uint32_t requests[]={100,0,24,25,26,50,75,101,150,UINT32_MAX,INT32_MAX};
    for(unsigned i=0;i<sizeof requests/sizeof requests[0];++i)
        for(int busy=0;busy<2;++busy)for(int readonly=0;readonly<2;++readonly)
            equivalent(requests[i],busy,readonly);
    setup(100,0);dispatch();assert(MEM32(0x1003C)==50);
    setup(100,0);sub_11021F16();assert(MEM32(0x1003C)==100);
    puts("PASS mixer latency: actual original stdcall, default100->50, all registers/flags/FPU/memory, explicit settings, initialization errors, readonly and binding guards");
    return 0;
}
'''

ALLOCATOR = r'''
static uint32_t allocated_size,dsp_next;
void sub_110347E0(void) {g_eax=0;g_esp+=4;}
void sub_1103480F(void) {g_eax=0;g_esp+=4;}
void sub_1103483C(void) {g_eax=0;g_esp+=4;}
void sub_11010FED(void) {allocated_size=ARG(1);g_eax=0x60000;g_esp+=4;}
void sub_11012420(void) {g_eax=0;g_esp+=4;}
void sub_110285E4(void) {g_eax=dsp_next;dsp_next+=0x40;g_esp+=16;}
void sub_110287FF(void) {g_esp+=12;}
recomp_func_t void_resolve(uint32_t address) {(void)address;assert(0);return NULL;}
/* ALLOCATOR */
static uint32_t ring(uint32_t rate,int native) {
    setup(100,0);if(native)dispatch();else sub_11021F16();
    MEM32(0x10038)=rate;MEM32(0x114D8)=32;MEM32(0x10034)=1;
    MEM32(0x11041020+52+24)=16;MEM32(0x11041020+52+28)=2;
    dsp_next=0x20000;g_esp=0x51000;
    /* INIT_MIXER */
    sub_11012B52();assert(LO8(g_eax)==1 && g_esp==0x51004);
    uint32_t frames=MEM32(0x10040),block=MEM32(0x10048);
    assert(block>=256 && frames>=2*block && frames%block==0);
    assert(allocated_size==frames*4+256);
    return frames;
}
int main(void) {
    available=1;dispatch=original;void_fmod_latency_init();
    const uint32_t rates[]={4000,8000,11025,22050,44100,48000,65535};
    for(unsigned i=0;i<sizeof rates/sizeof rates[0];++i) {
        uint32_t before=ring(rates[i],0),after=ring(rates[i],1);
        assert(after<=before);
        if(rates[i]>=11025)assert(after*1000/rates[i]<=100);
        if(rates[i]==44100)assert(before==8192 && after==4096);
    }
    puts("PASS actual FMOD ring allocator: all rates, whole DSP blocks, minimum two blocks, original200ms -> bounded100ms, 44.1kHz8192->4096frames");
    return 0;
}
'''

WORKER = r'''
static unsigned refills;static uint32_t observed_cursor;
void sub_110124F4(void) {g_esp+=4;}
void sub_11012500(void) {fp_push(0);g_esp+=4;}
void sub_110125E8(void) {assert(ARG(0)==10);MEM8(0x1006C)=1;g_esp+=4;}
void sub_110129F2(void) {assert(ARG(1)==1024);++refills;g_esp+=4;}
void sub_11027BD5(void) {g_eax=observed_cursor;g_esp+=8;}
/* WORKER */
int main(void) {
    available=1;dispatch=original;void_fmod_latency_init();
    /* A 50 ms scheduling gap laps a two-block ring. The original worker
       only compares modulo block indices and cannot detect that full lap. */
    const unsigned rings[]={2048,ring(44100,1),8192},expected[]={0,2,2};
    assert(rings[1]==4096);
    for(unsigned i=0;i<3;++i) {
        setup(100,0);MEM32(0x10030)=0x20000;MEM32(0x114AC)=0x30000;
        MEM32(0x3005C)=0x40000;MEM32(0x4010C)=rings[i];MEM32(0x10048)=1024;
        observed_cursor=2205;refills=0;
        sub_11012A68();assert(g_esp==0x51004 && MEM8(0x1006E)==1);
        assert(refills==expected[i]);
    }
    puts("PASS actual FMOD mixer: 50ms advance loses the two-block ring; calibrated four-block ring refills two blocks");
    return 0;
}
'''


class FmodLatencyTest(unittest.TestCase):
    def test_hook_is_installed_after_dll_init_before_game_entry(self):
        source = (ROOT / "android/host/main.c").read_text(encoding="utf-8")
        start = function(source,"int void_game_main(")
        self.assertLess(start.index("void_modules_start()"),start.index("void_fmod_latency_init();"))
        self.assertLess(start.index("void_fmod_latency_init();"),start.index("void_call_guest(entry"))

    def test_actual_buffer_api_all_editions(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM_HARNESS[:STREAM_HARNESS.index("static uint64_t clock_ns")]
        prefix += "static uint32_t read_only;\n#define ARG(i) MEM32(g_esp+4u+4u*(i))\n"
        prefix += "static int void_vm_writable(uint32_t a,uint32_t n) {return !read_only && a>=0x10000 && (uint64_t)a+n<=sizeof memory;}\n"
        snapshot = STREAM_HARNESS[STREAM_HARNESS.index("typedef struct {\n    uint32_t registers[8]"):STREAM_HARNESS.index("static void restore(")]
        native = NATIVE.read_text(encoding="utf-8")
        native = native[native.index("static void_fn original_buffer_size;"):]
        for edition,base in (("toe",ROOT/"generated"),("vanilla",ROOT/"generated/vanilla"),("hof",ROOT/"generated/hof")):
            with self.subTest(edition=edition):
                source = (base/"fmod-x86/fmod_0011.c").read_text(encoding="utf-8")
                original = function(source,"void sub_11021F16(")
                dispatch = (base/"fmod-x86/recomp_dispatch.c").read_text(encoding="utf-8")
                self.assertIn("{0x11021F16u, sub_11021F16}",dispatch)
                harness = prefix+HARNESS.replace("/* NATIVE */",native).replace("/* ORIGINAL */",original).replace("/* SNAPSHOT */",snapshot)
                compile_probe("fmod_latency_"+edition,harness,{"runtime.h":runtime},extra_flags=FLAGS,compiler_override=COMPILER)
                broken=harness.replace("MEM32(g_esp + 4) = 50;","MEM32(g_esp + 4) = 100;")
                self.assertNotEqual(broken,harness)
                with self.assertRaisesRegex(AssertionError,"Assertion failed"):
                    compile_probe("fmod_latency_bad_"+edition,broken,{"runtime.h":runtime},extra_flags=FLAGS,compiler_override=COMPILER)
                allocator = function((base/"fmod-x86/fmod_0007.c").read_text(encoding="utf-8"),"void sub_11012B52(")
                # Execute the original Init block which doubles the setting, then
                # its complete original allocator; only host/DSP boundaries are spies.
                init = source[source.index("L_110222BB:"):source.index("    RECOMP_CALL(sub_11012B52);",source.index("L_110222BB:"))]
                init = "g_eax=MEM32(0x110472D0);\n"+init
                init = re.sub(r"\b(eax|ecx)\b",r"g_\1",init)
                init = "\n".join(line for line in init.splitlines() if "_cf" not in line and "_flag_" not in line)
                allocator_harness = harness[:harness.index("int main(void) {")]
                allocator_harness += ALLOCATOR.replace("/* ALLOCATOR */",allocator).replace("/* INIT_MIXER */",init)
                compile_probe("fmod_latency_ring_"+edition,allocator_harness,{"runtime.h":runtime},extra_flags=FLAGS,compiler_override=COMPILER)
                worker = function((base/"fmod-x86/fmod_0007.c").read_text(encoding="utf-8"),"void sub_11012A68(")
                worker_harness = allocator_harness[:allocator_harness.index("int main(void) {")]
                worker_harness += WORKER.replace("/* WORKER */",worker)
                compile_probe("fmod_latency_scheduling_"+edition,worker_harness,{"runtime.h":runtime},extra_flags=FLAGS,compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
