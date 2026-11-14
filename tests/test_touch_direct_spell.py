"""Defer the native targetless spell commit, including the book's closing interval."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(ROOT / "tools"))
from port_patches import adapt_host_source


LAYOUTS = {
    "toe": (0xA0, 0x2B4, 0x2AC, 0x2E0, 0x2D4, 0x394, 0x388, 0x38C, 0x31C, 0x324, 0x32C, 0x330),
    "vanilla": (0x98, 0x294, 0x28C, 0x2D8, 0x2CC, 0x380, 0x374, 0x378, 0x314, 0x31C, 0x324, 0x328),
    "hof": (0x98, 0x2A8, 0x2A0, 0x2F0, 0x2E4, 0x398, 0x38C, 0x390, 0x32C, 0x334, 0x33C, 0x340),
}


def native_armed_phase(edition):
    """Execute the original next-frame armed-state branch, including native RET."""
    filename, begin, end = {
        "toe": ("game_0116.c", "00544882", "005448B0"),
        "vanilla": ("game_0101.c", "00516B52", "00516B80"),
        "hof": ("game_0102.c", "0052C3C5", "0052C3F1"),
    }[edition]
    generated = ROOT / "generated" / ("" if edition == "toe" else edition) / "game-x86" / filename
    text = generated.read_text()
    start = text.index("\nL_" + begin + ":")
    finish = text.index("\nL_" + end + ":", start)
    return r'''
#ifdef _MSC_VER
#pragma warning(push)
#pragma warning(disable:4102) /* Native fall-through labels have other callers outside this slice. */
#endif
#define FK_CMP 1
#define CMP_B(a,b) ((uint32_t)(a)<(uint32_t)(b))
#define CMP_EQ(a,b) ((a)==(b))
#define POP32_VAL(sp) ((sp)+=4,MEM32((sp)-4))
#define RECOMP_FLAGS_OUT() ((void)0)
#define RECOMP_REGS_OUT() ((void)0)
static void native_armed_frame(void) {
 uint32_t esi=0x7000,edi=0,ebp=0,esp=0x6000;
 uint32_t _flag_a=0,_flag_b=0,_flag_k=0,_cf=0;
''' + text[start:finish] + "\nL_" + end + ": assert(!\"expected armed spell\");\n}\n#ifdef _MSC_VER\n#pragma warning(pop)\n#endif\n"


PHASE_SCENARIOS = r'''
 /* Hardware regression: the hook captured phase128, then the ORIGINAL frame
    updater switched to phase8 without changing actor/caster/spell. */
 for(int book=0;book<=2;++book) for(int second=0;second<=1;++second) {
  reset();book_type=book?book:1;ui_top=book?0x9000:0x7000;
  MEM32(0x7000+SECOND)=second?0x3000:0;
  invoke();assert(!commits&&combat_pending.phase==0x80&&combat_pending.generation);
  native_armed_frame();
  uint32_t armed=second?0x100:8;
  assert(MEM32(0x7000+PHASE)==armed);
  assert(combat_direct_pending_state()==(book?0:1));
  ui_top=0x7000;assert(combat_direct_pending_state()==1);
  combat_pending.source_book=0;now+=UINT64_C(10000000000);
  assert(combat_direct_pending_state()==1); /* It remains confirmable after book grace expires. */
  const uint32_t invalid[]={0,1,2,4,0x10,0x200,0x400,0x1000};
  for(unsigned i=0;i<sizeof invalid/sizeof invalid[0];++i) {
   MEM32(0x7000+PHASE)=invalid[i];assert(combat_direct_pending_state()==-1);
  }
  MEM32(0x7000+PHASE)=second?8:0x100;assert(combat_direct_pending_state()==-1);
  MEM32(0x7000+PHASE)=armed;
  const unsigned refs[]={ACTOR,SPELL,CASTER,SECOND};
  for(unsigned i=0;i<sizeof refs/sizeof refs[0];++i) {
   ++MEM32(0x7000+refs[i]);assert(combat_direct_pending_state()==-1);--MEM32(0x7000+refs[i]);
  }
  assert(combat_direct_pending_state()==1&&!commits);
  combat_direct_allowed=1;invoke();assert(commits==1); /* Only explicit confirmation executes it. */
 }
'''

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x10000];
#define MEM32(a) (*(uint32_t *)(memory+(uint32_t)(a)))
#define MEM8(a) memory[(uint32_t)(a)]
enum {SCREEN_COMBAT=2};
typedef void (*void_fn)(void);
static uint32_t g_eax,g_ecx,g_edx,g_esp;
typedef struct {uint32_t eax,ecx,edx,esp;} void_regs;
static unsigned saves,loads,commits;
static int enabled=1,touch_mode=1,ctrl_held=1,book_type=1;
static uint32_t ui_top=0x7000;
static uint64_t now=1000;
static void_fn original_combat_direct;
static int combat_direct_allowed;
static uint32_t combat_generation;
/* PENDING */
static void void_regs_save(void_regs *s) {++saves;s->eax=g_eax;s->ecx=g_ecx;s->edx=g_edx;s->esp=g_esp;}
static void void_regs_load(const void_regs *s) {++loads;g_eax=s->eax;g_ecx=s->ecx;g_edx=s->edx;g_esp=s->esp;}
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100&&(uint64_t)a+n<=sizeof memory;}
static int void_port_combat_confirm(void) {return enabled;}
static uint64_t void_perf_now_ns(void) {return now;}
static uint32_t current_screen(void) {g_eax=7;g_ecx=8;g_edx=9;return ui_top;}
static int screen_kind(uint32_t s) {return void_vm_readable(s,4)&&MEM32(s)==77?SCREEN_COMBAT:0;}
static int spellbook_kind(uint32_t s) {return s==0x9000?book_type:0;}
static void native_commit(void) {
 assert(g_ecx==0x7000&&g_edx==0xABCD&&g_eax==0x12345678&&g_esp==0x6000);
 ++commits;g_eax=0xDEAD;g_esp+=4;
}
/* HELPERS */
/* NATIVE_FRAME */
static void invoke(void) {
 g_eax=0x12345678;g_ecx=0x7000;g_edx=0xABCD;g_esp=0x6000;
 combat_direct_commit();
 assert(g_ecx==0x7000&&g_edx==0xABCD&&g_esp==0x6004);
 assert(saves==loads);
}
static void reset(void) {
 memset(memory,0,sizeof memory);memset(&combat_pending,0,sizeof combat_pending);
 saves=loads=commits=combat_generation=0;enabled=touch_mode=1;ctrl_held=1;
 book_type=1;ui_top=0x7000;now=1000;combat_direct_allowed=0;original_combat_direct=native_commit;
 MEM32(0x7000)=77;MEM32(0x7000+ROOT_FIELD)=0x5000;MEM32(0x7000+CONTROLLER)=0x5100;
 MEM32(0x7000+ACTOR)=0x1000;MEM32(0x7000+PHASE)=0x80;MEM32(0x7000+SPELL)=123;
 MEM32(0x7000+CASTER)=0x2000;MEM32(0x7000+SECOND)=0x3000;
 MEM32(0x7000+ACTION)=7;MEM32(0x7000+TARGET)=0x4000;
 MEM32(0x7000+CELL_X)=4;MEM32(0x7000+CELL_Y)=5;
 MEM32(0x1004)=0x1800;MEM32(0x1804)=0xFC;
 MEM32(0x2004)=0x2800;MEM32(0x2804)=0xFC;
}
int main(void) {
 unsigned char before[sizeof memory];
 reset();memcpy(before,memory,sizeof memory);invoke();
 assert(!commits&&g_eax==0&&combat_pending.generation==1);
 assert(!memcmp(before,memory,sizeof memory)); /* Native references stay owned by their screen. */
 assert(combat_pending.screen==0x7000&&combat_pending.root==0x5000&&combat_pending.controller==0x5100);
 assert(combat_pending.actor==0x1000&&combat_pending.caster==0x2000&&combat_pending.second==0x3000);
 assert(combat_pending.direct_spell==123&&combat_pending.spell==123&&combat_pending.phase==0x80);
 assert(!combat_pending.action&&!combat_pending.ctrl&&!combat_pending.source_book);
 assert(combat_pending.x==-1&&combat_pending.y==-1&&combat_direct_pending_state()==1);
 /* Confirm's bypass delegates exactly once with native registers and zero stack arguments. */
 combat_direct_allowed=1;invoke();assert(commits==1&&g_eax==0xDEAD&&combat_pending.generation==1);
 reset();enabled=0;invoke();assert(commits==1&&!combat_pending.generation&&!saves);
 reset();touch_mode=0;invoke();assert(commits==1&&!combat_pending.generation&&!saves);
 /* The book callback can return success and close normally while the spell remains armed. */
 for(int variant=1;variant<=2;++variant) {
  reset();book_type=variant;ui_top=0x9000;MEM32(0x7000+UI)=1;MEM32(0x5008)=0x9200;
  memcpy(before,memory,sizeof memory);invoke();assert(!commits&&!memcmp(before,memory,sizeof memory));
  assert(combat_pending.source_book==0x9000&&combat_direct_pending_state()==0);
  ui_top=0x7000;assert(combat_direct_pending_state()==0); /* Closing UI still owns the arena. */
  MEM32(0x7000+UI)=0;MEM32(0x5008)=0;assert(combat_direct_pending_state()==1);
  combat_pending.source_book=0;now+=UINT64_C(10000000000);assert(combat_direct_pending_state()==1);
 }
 reset();ui_top=0x9000;invoke();now=combat_pending.direct_wait_until;assert(combat_direct_pending_state()==-1);
 reset();ui_top=0x9000;invoke();ui_top=0x9100;assert(combat_direct_pending_state()==-1);
 reset();invoke();enabled=0;assert(combat_direct_pending_state()==-1);
 reset();invoke();MEM8(0x1107)=0x80;assert(combat_direct_pending_state()==-1);
 reset();invoke();MEM8(0x2107)=0x80;assert(combat_direct_pending_state()==-1);
 const unsigned owners[]={ROOT_FIELD,CONTROLLER,ACTOR,PHASE,SPELL,CASTER,SECOND};
 for(unsigned i=0;i<sizeof owners/sizeof owners[0];++i) {
  reset();invoke();++MEM32(0x7000+owners[i]);assert(combat_direct_pending_state()==-1);
 }
 /* Outside the original battle/spell context the hook leaves native behavior intact. */
 reset();ui_top=0x9100;invoke();assert(commits==1&&!combat_pending.generation);
 reset();MEM32(0x7000+SPELL)=0;invoke();assert(commits==1&&!combat_pending.generation);
 reset();MEM32(0x7000+PHASE)=0x200;invoke();assert(commits==1&&!combat_pending.generation);
 reset();MEM32(0x7000+CASTER)=0;invoke();assert(commits==1&&!combat_pending.generation);
 reset();MEM32(0x1004)=0xFFFF;invoke();assert(commits==1&&!combat_pending.generation);
 reset();MEM32(0x7000+ROOT_FIELD)=0;invoke();assert(commits==1&&!combat_pending.generation);
 /* PHASE_SCENARIOS */
 puts("PASS native targetless spell: all-edition screen fields, no-argument RET and register preservation, no early commit, unchanged owned refs, both spellbooks and bounded closing interval");
 return 0;
}
'''


class DirectSpellTest(unittest.TestCase):
    def test_actual_generated_book_and_ability_callers_use_installed_hook_all_editions(self):
        import build_android
        from native_routes import apply_native_routes
        original = {
            "toe": ("00542420", ("00543047", "0054514E"), ("game_0116.c", "game_0117.c")),
            "vanilla": ("00514870", ("00515440", "005173D4"), ("game_0101.c",)),
            "hof": ("00529AB0", ("0052A63A", "0052CE50"), ("game_0102.c",)),
        }
        for edition, (address, sites, filenames) in original.items():
            with self.subTest(edition=edition), tempfile.TemporaryDirectory(dir=ROOT / "build/tests") as tmp:
                build_android.configure_edition(edition)
                try:
                    calls = []
                    with patch.object(build_android, "OUT", Path(tmp)):
                        for filename in filenames:
                            path = build_android.GENERATED / "game-x86" / filename
                            prepared, _ = build_android.override_source(path, local_xmm=True)
                            text = prepared.read_text()
                            self.assertNotRegex(text, r"RECOMP_(?:CALL_P|CALL|TAIL_P)\(sub_" + address + r"[,)]")
                            calls += re.findall(r"RECOMP_CALL_P\(void_touch_combat_direct_dispatch,[^\n;]+\);", text)
                            if "void sub_" + address + "(void) {" in path.read_text():
                                self.assertIn("void sub_" + address + "(void) {", text)
                    self.assertTrue(calls)
                    self.assertEqual({re.search(r"0x([0-9A-F]{8})u\);$", line)[1] for line in calls}, set(sites))
                    dispatch = ("const entry table[]={{0x" + address + "u,sub_" + address + "}};").encode()
                    routed, _, count = apply_native_routes(dispatch, edition, module="game", dispatch=True, groups=())
                    self.assertEqual((routed, count), (dispatch, 0))
                    path, _ = adapt_host_source(ROOT / "android/host/touch_engine.c", tmp, edition)
                    source = path.read_text()
                    start = source.index("static struct {\n    uint32_t generation, screen, root, controller, actor, phase, spell, caster, second;")
                    end = source.index("} combat_pending;", start) + len("} combat_pending;")
                    helpers = "\n".join(function(source, declaration) for declaration in (
                        "static uint32_t read32(", "static uint32_t virtual_base(",
                        "static void combat_pending_stage(uint32_t screen, float x, float y)\n{",
                        "static void combat_direct_commit(void)\n{",
                        "static int combat_direct_pending_state(void)\n{"))
                    helpers += "\nstatic void_fn void_resolve(uint32_t va) {assert(va==0x" + address + "u);return combat_direct_commit;}\n"
                    helpers += function(source, "void void_touch_combat_direct_dispatch(void)\n{")
                    helpers += "\n#define RECOMP_CALL_P(fn,pub,rel,fl,site) do {assert(((pub)&0x17)==0x17&&((rel)&0x17)==0x17);g_esp-=4;MEM32(g_esp)=0xDEAD0000u;fn();} while(0)\n"
                    helpers += "\n".join("static void caller_" + str(i) + "(void) {" + line + "}" for i, line in enumerate(calls))
                    helpers += "\nstatic unsigned route_index;\nstatic void_fn callers[]={" + ",".join("caller_" + str(i) for i in range(len(calls))) + "};\n"
                    constants = "".join(f"#define {name} {value}\n" for name, value in zip(
                        ("ROOT_FIELD", "CONTROLLER", "ACTOR", "PHASE", "UI", "SPELL", "CASTER", "SECOND", "ACTION", "TARGET", "CELL_X", "CELL_Y"), LAYOUTS[edition]))
                    harness = HARNESS.replace("/* PENDING */", source[start:end]).replace("/* HELPERS */", helpers)
                    harness = harness.replace("/* NATIVE_FRAME */", native_armed_phase(edition)).replace("/* PHASE_SCENARIOS */", PHASE_SCENARIOS)
                    harness = harness.replace("g_esp=0x6000;\n combat_direct_commit();", "g_esp=0x6004;\n callers[route_index]();")
                    harness = harness.replace("int main(void) {", "static int scenarios(void) {")
                    # The caller necessarily pushes the native return address before entering the hook.
                    harness = harness.replace("memcpy(before,memory,sizeof memory);invoke();", "MEM32(0x6000)=0xDEAD0000u;memcpy(before,memory,sizeof memory);invoke();")
                    harness += "\nint main(void) {for(route_index=0;route_index<sizeof callers/sizeof callers[0];++route_index)scenarios();return 0;}\n"
                    compile_probe("touch-direct-callers-" + edition, constants + harness, {})
                finally:
                    build_android.configure_edition("toe")

    def test_native_commit_hook_and_closing_book_lifetime_all_editions(self):
        for edition, values in LAYOUTS.items():
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                path, _ = adapt_host_source(ROOT / "android/host/touch_engine.c", tmp, edition)
                source = path.read_text()
                start = source.index("static struct {\n    uint32_t generation, screen, root, controller, actor, phase, spell, caster, second;")
                end = source.index("} combat_pending;", start) + len("} combat_pending;")
                helpers = "\n".join(function(source, declaration) for declaration in (
                    "static uint32_t read32(", "static uint32_t virtual_base(",
                    "static void combat_pending_stage(uint32_t screen, float x, float y)\n{",
                    "static void combat_direct_commit(void)\n{",
                    "static int combat_direct_pending_state(void)\n{"))
                constants = "".join(f"#define {name} {value}\n" for name, value in zip(
                    ("ROOT_FIELD", "CONTROLLER", "ACTOR", "PHASE", "UI", "SPELL", "CASTER", "SECOND", "ACTION", "TARGET", "CELL_X", "CELL_Y"), values))
                harness = HARNESS.replace("/* PENDING */", source[start:end]).replace("/* HELPERS */", helpers)
                harness = harness.replace("/* NATIVE_FRAME */", native_armed_phase(edition)).replace("/* PHASE_SCENARIOS */", PHASE_SCENARIOS)
                compile_probe("touch-direct-spell-" + edition, constants + harness, {})


if __name__ == "__main__":
    unittest.main()
