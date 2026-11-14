"""Keep FMOD's original ring headroom; shortened rings replay PCM after a worker delay."""
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
/* ORIGINAL */
static void setup(uint32_t argument,int busy) {
    memset(memory+0x10000,0,0x42000);
    MEM32(0x110472D0)=0x10000;MEM8(0x10020)=(uint8_t)busy;
    MEM32(0x1003C)=777;MEM32(0x11065C18)=999;
    g_esp=0x51000;g_esi=0x12345678;
    MEM32(g_esp)=0xBAD11111;MEM32(g_esp+4)=argument;
}
int main(void) {
    const uint32_t requests[]={0,24,25,26,50,75,100,101,150,UINT32_MAX,INT32_MAX};
    for(unsigned i=0;i<sizeof requests/sizeof requests[0];++i)
        for(int busy=0;busy<2;++busy) {
            uint32_t request=requests[i];setup(request,busy);sub_11021F16();
            uint32_t expected=(int32_t)request<25?25:request/25*25;
            assert(MEM32(0x1003C)==(busy?777:expected));
            assert(MEM32(0x11065C18)==(uint32_t)busy && LO8(g_eax)==!busy);
            assert(g_esp==0x51008 && g_esi==0x12345678 && MEM32(0x51004)==request);
        }
    puts("PASS original FMOD setting: default100ms and explicit requests preserved, rounding, busy error and stdcall ABI");
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
static uint32_t ring(uint32_t rate,uint32_t request) {
    setup(request,0);sub_11021F16();
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
    const uint32_t rates[]={4000,8000,11025,22050,44100,48000,65535};
    for(unsigned i=0;i<sizeof rates/sizeof rates[0];++i) {
        uint32_t shortened=ring(rates[i],50),original=ring(rates[i],100);
        assert(shortened<=original);
        if(rates[i]>=11025)assert(original*1000/rates[i]<=200);
        if(rates[i]==44100)assert(original==8192 && shortened==4096);
    }
    puts("PASS actual FMOD ring allocator: all rates, whole DSP blocks, minimum two blocks, original200ms headroom, 44.1kHz8192frames (shortened4096 aliases after93ms)");
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
    /* A 100 ms worker gap wraps the shortened ring to the same modulo block.
       The original ring still exposes all four consumed blocks to its worker. */
    const unsigned rings[]={ring(44100,50),ring(44100,100)},expected[]={0,4};
    assert(rings[0]==4096 && rings[1]==8192);
    for(unsigned i=0;i<2;++i) {
        setup(100,0);MEM32(0x10030)=0x20000;MEM32(0x114AC)=0x30000;
        MEM32(0x3005C)=0x40000;MEM32(0x4010C)=rings[i];MEM32(0x10048)=1024;
        observed_cursor=4410;refills=0;
        sub_11012A68();assert(g_esp==0x51004 && MEM8(0x1006E)==1);
        assert(refills==expected[i]);
    }
    puts("PASS actual FMOD mixer: 100ms advance aliases shortened4096 ring; original8192 ring refills all four blocks");
    return 0;
}
'''


class FmodLatencyTest(unittest.TestCase):
    def test_port_keeps_original_buffer_setting(self):
        source = (ROOT / "android/host/main.c").read_text(encoding="utf-8")
        self.assertNotIn("void_fmod_latency_init", source)
        self.assertNotIn("fmod_buffer_size", NATIVE.read_text(encoding="utf-8"))

    def test_actual_buffer_api_all_editions(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8")
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM_HARNESS[:STREAM_HARNESS.index("static uint64_t clock_ns")]
        prefix += "#define ARG(i) MEM32(g_esp+4u+4u*(i))\n"
        for edition,base in (("toe",ROOT/"generated"),("vanilla",ROOT/"generated/vanilla"),("hof",ROOT/"generated/hof")):
            with self.subTest(edition=edition):
                source = (base/"fmod-x86/fmod_0011.c").read_text(encoding="utf-8")
                original = function(source,"void sub_11021F16(")
                dispatch = (base/"fmod-x86/recomp_dispatch.c").read_text(encoding="utf-8")
                self.assertIn("{0x11021F16u, sub_11021F16}",dispatch)
                harness = prefix+HARNESS.replace("/* ORIGINAL */",original)
                compile_probe("fmod_latency_"+edition,harness,{"runtime.h":runtime},extra_flags=FLAGS,compiler_override=COMPILER)
                shortened = harness.replace("void sub_11021F16(void) {",
                    "void sub_11021F16(void) { if (ARG(0)==100) MEM32(g_esp+4)=50;")
                self.assertNotEqual(shortened, harness)
                with self.assertRaisesRegex(AssertionError, "0x1003C"):
                    compile_probe("fmod_latency_shortened_"+edition,shortened,{"runtime.h":runtime},extra_flags=FLAGS,compiler_override=COMPILER)
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
