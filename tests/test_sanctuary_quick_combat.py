"""Execute the Sanctuary quick gate and original eligibility for every edition."""
import re
import sys
import tempfile
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_fmod_stream import HARNESS as STREAM
from test_fmod_latency import HARNESS as FMOD, FLAGS, COMPILER

sys.path.insert(0, str(ROOT / "tools"))
from port_patches import adapt_host_source, legacy_ui_branch

EDITIONS = {
    "toe": ("generated/game-x86/game_0576.c", "00B5AB50",
            "generated/game-x86/game_0634.c", "00C1EF30", 0x22D, 0x1D4, 0xE7E484, 0xE7D6D8, 0xE1A09C, 0x2E0, 0x10D6A84),
    "vanilla": ("generated/vanilla/game-x86/game_0375.c", "00884990",
                "generated/vanilla/game-x86/game_0596.c", "00B53E40", 0x215, 0x1BC, 0xE2F884, 0xE5C0D0, 0xE3B404, 0x2C8, 0x10B8F68),
    "hof": ("generated/hof/game-x86/game_0463.c", "009A52C0",
            "generated/hof/game-x86/game_0481.c", "009DDE70", 0x215, 0x1BC, 0xE15C3C, 0xDCCD50, 0xE0088C, 0x29C, 0xFAC608),
}

HARNESS = r'''
typedef void (*void_fn)(void);
static void_fn dispatch;
static unsigned bindings,original_calls;
static int available=1;
static uint32_t bad_range,read_only;
static int void_vm_readable(uint32_t a,uint32_t n) {
 return a>=0x10000 && (uint64_t)a+n<=sizeof memory &&
   (!bad_range || !((uint64_t)a<bad_range+0x100u && (uint64_t)a+n>bad_range));
}
static void original(void) {++original_calls;ORIGINAL_GETTER();}
static void_fn void_dispatch_find(uint32_t a) {assert(a==GETTER);return available?dispatch:NULL;}
static void void_dispatch_add(uint32_t a,void_fn f) {assert(a==GETTER&&f);dispatch=f;++bindings;}
/* NATIVE */
/* SNAPSHOT */
/* SETUP */
static void live(uint32_t object,uint32_t bases,uint32_t offset) {
 MEM32(object+4)=bases;MEM32(bases+4)=offset-4;MEM32(object+offset+4)=2;
}
static void objects(unsigned flag,unsigned kind,unsigned invalid) {
 setup(flag,0);bad_range=0;
 MEM32(0x18000)=kind==1?PLAYER_TABLE:kind==2?0x12345678:HERO_TABLE;
 MEM8(0x18000+FLAG_OFFSET)=(uint8_t)flag;
 MEM32(0x18000+HOLDER_OFFSET)=0x20000;
 live(0x18000,0x30000,0x300);live(0x20000,0x30100,0x100);
 MEM32(0x20000)=SANCTUARY_TABLE;
 if(invalid==1)MEM32(0x20000)=0x12345678;
 if(invalid==2)MEM32(0x20104)=0x80000002u;
 if(invalid==3)MEM32(0x18000+HOLDER_OFFSET)=0;
 if(invalid==4)MEM32(0x18000+HOLDER_OFFSET)=UINT32_MAX-3;
 if(invalid==5)MEM32(0x18304)=0x80000002u;
 if(invalid==6)MEM32(0x20004)=UINT32_MAX-3;
 if(invalid==7)MEM32(0x30104)=0x7FFF0000;
 if(invalid==8)bad_range=0x20000;
 if(invalid==9)MEM32(0x18004)=UINT32_MAX-3;
 g_ecx=0x18000;
}
static void equivalent(unsigned flag,unsigned kind,unsigned invalid) {
 objects(flag,kind,invalid);ORIGINAL_GETTER();take(&expected);
 objects(flag,kind,invalid);unsigned before=original_calls;dispatch();take(&actual);
 assert(original_calls==before+1&&g_esp==0x51004);
 if(flag&&!kind&&!invalid)expected.registers[0]&=~255u;
 if(memcmp(&expected,&actual,sizeof expected)) {
   const unsigned char *a=(const unsigned char *)&expected,*b=(const unsigned char *)&actual;
   for(unsigned i=0;i<sizeof expected;++i)if(a[i]!=b[i]) {
     fprintf(stderr,"flag=%u kind=%u invalid=%u snapshot byte%u expected%u actual%u\n",flag,kind,invalid,i,a[i],b[i]);break;
   }
   assert(!memcmp(&expected,&actual,sizeof expected));
 }
 assert((g_eax&~255u)==0x12345600);
 assert(MEM8(0x18000+FLAG_OFFSET)==flag);
}
/* Original eligibility executes its real vtable calls; only object getters are spies. */
static void none(void) {g_eax=0;g_esp+=4;}
static void owner(void) {g_eax=MEM32(g_ecx+0x70);g_esp+=4;}
static void descriptor(void) {g_eax=g_ecx+0x88;g_esp+=4;}
static void map_hero(void) {g_eax=0x26000;g_esp+=4;}
static void ihero(void) {g_eax=0x28000;g_esp+=4;}
static void human(void) {g_eax=(g_eax&~255u)|(MEM32(g_ecx+0x74)==0);g_esp+=4;}
recomp_func_t void_resolve(uint32_t a) {
 if(a==GETTER)return dispatch;
 switch(a) {
 case 0x70000:return none;case 0x70010:return owner;case 0x70020:return descriptor;
 case 0x70030:return map_hero;case 0x70040:return ihero;case 0x70050:return human;
 default:assert(!"unexpected guest method");return NULL;
 }
}
/* ELIGIBILITY */
static void table(uint32_t p) {for(unsigned i=0;i<0x400;i+=4)MEM32(p+i)=0x70000;}
static void eligibility(unsigned actor_sheltered,unsigned target_sheltered,unsigned patched) {
 objects(1,0,0);if(!actor_sheltered)MEM32(0x18000+HOLDER_OFFSET)=0;
 table(HERO_TABLE);table(0x40000);table(0x41000);table(0x44000);table(0x45000);table(0x46000);
 MEM32(HERO_TABLE+QUICK_SLOT)=GETTER;MEM32(HERO_TABLE+OWNER_SLOT)=0x70010;
 MEM32(0x18070)=0x34000;MEM32(0x28070)=0x35000;
 MEM32(0x34000)=MEM32(0x35000)=0x44000;
 MEM32(0x34074)=0;MEM32(0x35074)=1;MEM32(0x44000+0x190)=0x70050;
 MEM32(0x36000)=0x45000;MEM32(0x45000+0x14)=0x70020;
 MEM8(0x36088)=0;MEM8(GLOBAL_QUICK)=1;
 MEM32(0x25000)=0x40000;MEM32(0x40000+TARGET_HERO_SLOT)=0x70030;
 MEM32(0x26000)=0x41000;MEM32(0x41000+I_HERO_SLOT)=0x70040;
 live(0x28000,0x30200,0x300);MEM32(0x28000)=HERO_TABLE;MEM8(0x28000+FLAG_OFFSET)=1;
 MEM32(0x28000+HOLDER_OFFSET)=target_sheltered?0x20000:0;
 MEM32(0x26004)=0x30300;MEM32(0x30300+0xC)=0x1FC;
 MEM32(0x26200)=0x46000;MEM32(0x46000)=0x70010;MEM32(0x26270)=0x35000;
 dispatch=patched?hero_quick_combat:original;
 g_ecx=0x18000;g_edx=0x25000;g_esp=0x51000;MEM32(g_esp+4)=0x36000;
 ORIGINAL_ELIGIBILITY();
 assert(g_esp==0x51008);
 assert((g_eax&255u)==!(patched&&(actor_sheltered||target_sheltered)));
 assert(MEM8(GLOBAL_QUICK)==1&&MEM8(0x18000+FLAG_OFFSET)==1&&MEM8(0x28000+FLAG_OFFSET)==1);
}
int main(void) {
 dispatch=original;available=0;sanctuary_quick_combat_init();assert(!bindings);
 available=1;sanctuary_quick_combat_init();assert(bindings==1&&dispatch==hero_quick_combat);
 sanctuary_quick_combat_init();assert(bindings==1);
 const unsigned flags[]={0,1,165};
 for(unsigned i=0;i<3;++i)for(unsigned kind=0;kind<3;++kind)for(unsigned invalid=0;invalid<10;++invalid)
   equivalent(flags[i],kind,invalid);
 for(unsigned actor=0;actor<2;++actor)for(unsigned target=0;target<2;++target)for(unsigned patched=0;patched<2;++patched)
   eligibility(actor,target,patched);
 puts("PASS Sanctuary quick gate: original leaf+eligibility, all GP/flags/FPU/stack, IPlayer alias, invalid refs, either participant, settings unchanged");
 return 0;
}
'''


class SanctuaryQuickCombatTest(unittest.TestCase):
    def test_registered_after_modules_before_guest_entry(self):
        body = function((ROOT / "android/host/main.c").read_text(), "int void_game_main(")
        self.assertLess(body.index("void_modules_start()"), body.index("sanctuary_quick_combat_init();"))
        self.assertLess(body.index("sanctuary_quick_combat_init();"), body.index("void_call_guest(entry"))

    def test_original_leaf_and_eligibility_all_editions(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text()
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM[:STREAM.index("static uint64_t clock_ns")]
        snapshot = STREAM[STREAM.index("typedef struct {\n    uint32_t registers[8]"):STREAM.index("static void restore(")]
        setup = function(FMOD, "static void setup(")
        for edition, spec in EDITIONS.items():
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                leaf_file, leaf, eligibility_file, eligibility, flag, holder, hero, sanctuary, player, slot, global_quick = spec
                path, _ = adapt_host_source(ROOT / "android/host/main.c", tmp, edition)
                source = legacy_ui_branch(path.read_bytes(), False).decode() if edition == "toe" else path.read_text()
                native = source[source.index("static void_fn original_hero_quick_combat;"):source.index("static void enumerate_test_callback(")]
                original = function((ROOT / leaf_file).read_text(), "void sub_" + leaf + "(")
                original += "\n" + function((ROOT / eligibility_file).read_text(), "void sub_" + eligibility + "(")
                if edition == "toe":
                    original += "\n" + function((ROOT / "generated/game-x86/game_0085.c").read_text(), "void sub_004E9280(")
                declares = "\n".join("void " + name + "(void);" for name in sorted(set(re.findall(r"sub_[0-9A-F]{8}", original))))
                constants = {
                    "GETTER": "0x" + leaf, "ORIGINAL_GETTER": "sub_" + leaf,
                    "ORIGINAL_ELIGIBILITY": "sub_" + eligibility, "FLAG_OFFSET": hex(flag),
                    "HOLDER_OFFSET": hex(holder), "HERO_TABLE": hex(hero),
                    "SANCTUARY_TABLE": hex(sanctuary), "PLAYER_TABLE": hex(player),
                    "QUICK_SLOT": hex(slot), "GLOBAL_QUICK": hex(global_quick),
                    "TARGET_HERO_SLOT": "0x28" if edition == "vanilla" else "0x2C",
                    "I_HERO_SLOT": "0x10" if edition == "vanilla" else "0x14",
                    "OWNER_SLOT": "0x10" if edition == "hof" else "0",
                }
                definitions = "\n".join("#define " + k + " " + v for k, v in constants.items()) + "\n"
                harness = prefix + definitions + declares + "\n" + HARNESS.replace("/* NATIVE */", native).replace(
                    "/* SNAPSHOT */", snapshot).replace("/* SETUP */", setup).replace("/* ELIGIBILITY */", original)
                compile_probe("sanctuary_quick_" + edition, harness, {"runtime.h": runtime},
                              extra_flags=FLAGS, compiler_override=COMPILER)
                broken = harness.replace("g_eax &= ~255u;", "g_eax |= 0u;")
                self.assertNotEqual(broken, harness)
                with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                    compile_probe("sanctuary_quick_bad_" + edition, broken, {"runtime.h": runtime},
                                  extra_flags=FLAGS, compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
