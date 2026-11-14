"""Execute the original strike-and-return eligibility branches in all editions."""
import re
import tempfile
import unittest

from test_d3d_lifecycle import function
from test_fmod_latency import COMPILER, FLAGS
from test_fmod_stream import HARNESS as STREAM
from test_static_tls import ROOT, compile_probe
from port_patches import adapt_host_source


# Bounded original decision blocks: route length, live ability query, then Ctrl.
# The surrounding damage/animation transaction remains the original engine's job.
GATES = {
    "toe": ("generated/game-x86/game_0494.c", "00A658D1", "00A65912", "00A6598E", 0x28C, 0x88, 0),
    "vanilla": ("generated/vanilla/game-x86/game_0403.c", "008F2DCA", "008F2E03", "008F2E46", 0x250, 0x70, 0x64),
    "hof": ("generated/hof/game-x86/game_0323.c", "007EB894", "007EB8CD", "007EB91B", 0x244, 0x7C, 0x70),
}

PROBE = r'''
static unsigned ability, queries;
static void has_ability(void) {
 assert(g_ecx==0x18000 && MEM32(g_esp+4)==55);
 g_eax=0xA5A50000|ability;g_esp+=8;++queries;
}
recomp_func_t void_resolve(uint32_t address) {assert(address==0x70000);return has_ability;}
static int original_gate(void) {
 uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
 RECOMP_REGS_LOCALS
 /* GATE */
 RECOMP_REGS_OUT();return 1;
 DISABLED:
 RECOMP_REGS_OUT();return 0;
}
int main(void) {
 const unsigned values[]={0,1,255};
 for(unsigned nodes=0;nodes<5;++nodes)for(unsigned a=0;a<3;++a)for(unsigned c=0;c<3;++c) {
  ability=values[a];queries=0;
  g_eax=g_ecx=g_edx=g_ebx=g_edi=0;g_esi=0x18000;g_ebp=0x20000;g_esp=0x51000;
  MEM32(0x18000)=0x19000;MEM32(0x19000+ABILITY_SLOT)=0x70000;
  MEM32(0x20000)=0x24000;MEM32(0x20004)=0x24000+12*nodes;
  if(PATH_STACK)MEM32(g_esp+PATH_STACK)=0x20000;
  MEM8(g_esp+CTRL_STACK)=(uint8_t)values[c];
  int result=original_gate();
  assert(result==(nodes>1 && ability && !values[c]));
  assert(queries==(nodes>1));assert(g_esp==0x51000);
 }
 puts("PASS original return gate: path length, ability 55, Ctrl cancellation, low-byte ABI, query count and stack");
 return 0;
}
'''

HELPER = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x10000];
#define MEM32(a) (*(uint32_t *)(memory+(a)))
#define MEM8(a) memory[(a)]
static unsigned can_shoot,returns,shoot_queries,return_queries;
static int available=1;
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100 && (uint64_t)a+n<=sizeof memory;}
static int void_dispatch_find(uint32_t method) {return available && (method==0x7000 || method==0x7010);}
static uint32_t void_call_guest_this(uint32_t method,uint32_t actor,int n,const uint32_t *args) {
 assert(actor==0x1000);
 if(method==0x7000) {assert(!n && !args);++shoot_queries;return 0xAA000000u|can_shoot;}
 assert(method==0x7010 && n==1 && args[0]==55);++return_queries;return 0xAA000000u|returns;
}
/* HELPERS */
int main(void) {
 MEM32(0x1000)=0x2000;MEM32(0x1004)=0x3000;MEM32(0x3004)=0xFC;
 MEM32(0x2000+SHOOT_SLOT)=0x7000;MEM32(0x2000+ABILITY_SLOT)=0x7010;
 const unsigned values[]={0,1,255};
 for(unsigned a=0;a<3;++a)for(unsigned b=0;b<3;++b) {
  can_shoot=values[a];returns=values[b];shoot_queries=return_queries=0;
  assert(combat_alternative(0x1000)==((a?1:0)|(b?2:0)));
  assert(shoot_queries==1 && return_queries==1);
 }
 can_shoot=returns=1;shoot_queries=return_queries=0;
 assert(!combat_alternative(0));assert(!combat_alternative(0xFFFF));
 MEM8(0x1107)=0x80;assert(!combat_alternative(0x1000));MEM8(0x1107)=0;
 MEM32(0x1004)=0xFFFF;assert(!combat_alternative(0x1000));MEM32(0x1004)=0x3000;
 assert(!shoot_queries && !return_queries);
 available=0;assert(!combat_alternative(0x1000));available=1;
 MEM32(0x2000+SHOOT_SLOT)=0;assert(combat_alternative(0x1000)==2);
 MEM32(0x2000+SHOOT_SLOT)=0x7000;MEM32(0x2000+ABILITY_SLOT)=0;
 assert(combat_alternative(0x1000)==1);
 puts("PASS alternative attack: edition slots, native ability55, low-byte bool, invalid/dead refs and missing methods");
 return 0;
}
'''


class AttackAlternativeTest(unittest.TestCase):
    def test_production_capability_query_all_editions(self):
        for edition, shoot, ability in (("toe", 0x1E0, 0x28C), ("vanilla", 0x1AC, 0x250), ("hof", 0x19C, 0x244)):
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                path, _ = adapt_host_source(ROOT / "android/host/touch_engine.c", tmp, edition)
                source = path.read_text()
                helpers = "\n".join(function(source, declaration) for declaration in (
                    "static uint32_t read32(", "static uint32_t virtual_base(",
                    "static uint32_t object_method(uint32_t object, unsigned offset)\n{",
                    "static int combat_alternative(uint32_t actor)\n{"))
                constants = f"#define SHOOT_SLOT {shoot}\n#define ABILITY_SLOT {ability}\n"
                compile_probe("attack-alternative-" + edition, constants + HELPER.replace("/* HELPERS */", helpers), {})

    def test_original_return_gates_all_editions(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text()
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM[:STREAM.index("static uint64_t clock_ns")]
        for edition, (path, start, end, disabled, slot, ctrl, route) in GATES.items():
            with self.subTest(edition=edition):
                source = (ROOT / path).read_text()
                gate = source[source.index("L_" + start + ":"):source.index("L_" + end + ":")]
                self.assertIn("PUSH32(esp, 0x37u)", gate)
                self.assertIn("RECOMP_ICALL(MEM32(edx + " + hex(slot).upper().replace("0X", "0x") + "))", gate)
                gate = gate.replace("L_" + disabled, "DISABLED")
                self.assertEqual(set(re.findall(r"goto (\w+)", gate)), {"DISABLED"})
                constants = f"#define ABILITY_SLOT {slot}\n#define CTRL_STACK {ctrl}\n#define PATH_STACK {route}\n"
                harness = prefix + constants + PROBE.replace("/* GATE */", gate)
                compile_probe("attack-return-" + edition, harness, {"runtime.h": runtime},
                              extra_flags=FLAGS, compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
