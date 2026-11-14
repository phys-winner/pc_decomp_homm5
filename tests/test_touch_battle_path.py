"""Byte-exact copied-grid search comparison against all three original engines."""
import re
import unittest

from test_d3d_lifecycle import function
from test_fmod_latency import COMPILER, FLAGS
from test_fmod_stream import HARNESS as STREAM
from test_static_tls import ROOT, compile_probe


LAYOUTS = {
    "toe": ("generated/game-x86/game_0577.c", 0xB5F0D0, 0xB5F4B0, 0xB5F450, 0xB5F3F0, 0xB5F3A0, 0xB597F0, 0xB5EEE0, 0x879240, 0xF757C8),
    "vanilla": ("generated/vanilla/game-x86/game_0419.c", 0x922E80, 0x923260, 0x923200, 0x9231A0, 0x923150, 0x9947D0, 0x922C90, 0xC00360, 0xF25578),
    "hof": ("generated/hof/game-x86/game_0464.c", 0x9A7F20, 0x9A83A0, 0x9A8340, 0x9A82E0, 0x9A8290, 0x9DB440, 0x9A7D30, 0xA99C10, 0xEFA9A0),
}

HARNESS = r'''
#include <stdlib.h>
#include "touch_combat.h"
static unsigned allocations,frees,fail_allocation;
static void *probe_realloc(void *old,size_t n) {
 if(++allocations==fail_allocation)return NULL;
 return realloc(old,n);
}
static void probe_free(void *p) {if(p)++frees;free(p);}
#define realloc probe_realloc
#define free probe_free
/* SOLVER */
#undef realloc
#undef free
static unsigned native_frees;
/* Only storage boundaries are mocked. Original seed/push/pop/search bodies run. */
static void queue_init(void) {
 assert(MEM32(g_esp+4)==32);uint32_t q=g_ecx;memset(GPTR(q),0,112);
 for(unsigned i=0;i<8;++i) {
  uint32_t begin=0x100000+0x40000*i;
  MEM32(q+4+12*i)=MEM32(q+8+12*i)=begin;MEM32(q+12+12*i)=begin+0x40000;
 }
 MEM32(q+104)=q+4;MEM32(q+108)=MEM32(q+4);g_esp+=8;
}
static void storage_free(void) {
 uint32_t p=MEM32(g_esp+4);assert(p>=0x100000&&p<=0x2C0000&&!((p-0x100000)%0x40000));
 ++native_frees;g_esp+=4;
}
static void forbidden(void) {assert(!"unexpected vector growth or debug branch");}
recomp_func_t void_resolve(uint32_t address) {(void)address;assert(0);return forbidden;}
/* ORIGINAL BODIES */
static uint32_t seed=0x12345678;
static uint32_t random_value(void) {seed=seed*1664525u+1013904223u;return seed;}
static void_touch_battle_grid input,actual;
static void grid(unsigned width,unsigned height,unsigned mode,uint32_t cost,unsigned density) {
 memset(&input,0,sizeof input);input.width=width;input.height=height;input.mode=mode;input.max_cost=cost;
 input.start_x=1+(int32_t)(random_value()%(width-2));input.start_y=1+(int32_t)(random_value()%(height-2));
 for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x) {
  unsigned r=random_value();uint32_t flags=x|(y<<6);
  if(!x||!y||x+1==width||y+1==height||(r%100)<density)flags|=0x800000;
  if((r>>8)%7==0)flags|=0x1000000;
  input.cells[y*width+x][1]=flags;
 }
 input.cells[(unsigned)input.start_y*width+(unsigned)input.start_x][1]&=~0x800000u;
}
static void compare(void) {
 actual=input;allocations=frees=fail_allocation=native_frees=0;
 assert(void_touch_battle_solve(&actual));
 MEM32(0x30000)=0x40000;MEM32(0x30004)=0x38000;
 MEM32(0x30008)=input.width;MEM32(0x3000C)=input.height;
 MEM32(0x30010)=input.mode;MEM32(0x30014)=input.max_cost;
 for(unsigned y=0;y<input.height;++y)MEM32(0x38000+4*y)=0x40000+8*input.width*y;
 memcpy(GPTR(0x40000),input.cells,8*input.width*input.height);
 MEM32(0x39000)=(uint32_t)input.start_x;MEM32(0x39004)=(uint32_t)input.start_y;
 g_ecx=0x30000;g_esp=0x90000;g_ebx=0x1234;g_esi=0x2345;g_edi=0x3456;g_ebp=0x4567;
 MEM32(g_esp)=0x777777;MEM32(g_esp+4)=0x39000;
 ORIGINAL_SEARCH();
 assert(g_esp==0x90008&&g_ebx==0x1234&&g_esi==0x2345&&g_edi==0x3456&&g_ebp==0x4567);
 if(memcmp(GPTR(0x40000),actual.cells,8*input.width*input.height)) {
  for(unsigned i=0;i<input.width*input.height;++i)if(MEM32(0x40000+8*i)!=actual.cells[i][0]||MEM32(0x40004+8*i)!=actual.cells[i][1]) {
   fprintf(stderr,"cell %u: native %08X %08X host %08X %08X (size %ux%u, mode%u, max%u)\n",i,
    MEM32(0x40000+8*i),MEM32(0x40004+8*i),actual.cells[i][0],actual.cells[i][1],input.width,input.height,input.mode,input.max_cost);break;
  }
  assert(0);
 }
 assert(native_frees==0||native_frees==8);
}
int main(void) {
 const int directions[8][2]={{0,-1},{0,1},{-1,0},{1,0},{1,-1},{1,1},{-1,-1},{-1,1}};
 memcpy(GPTR(DIRECTIONS),directions,sizeof directions);
 const uint32_t budgets[]={0,1,2,3,4,9,20,40,UINT32_MAX};
 for(unsigned mode=0;mode<=2;++mode)for(unsigned b=0;b<sizeof budgets/sizeof budgets[0];++b) {
  grid(17,14,mode,budgets[b],0);compare(); /* Equal-cost paths preserve native direction ties. */
  grid(17,14,mode,budgets[b],40);compare();
 }
 for(unsigned i=0;i<384;++i) {
  grid(4+random_value()%61,4+random_value()%61,i%3,budgets[i%9],random_value()%70);compare();
 }
 grid(64,64,1,UINT32_MAX,0);compare();
 grid(64,64,2,UINT32_MAX,0);compare();
 grid(8,8,2,12,0);input.cells[(unsigned)input.start_y*8+(unsigned)input.start_x][1]|=0x1000000;compare();
 grid(8,8,1,12,0);input.cells[(unsigned)input.start_y*8+(unsigned)input.start_x][1]|=0x800000;compare();
 grid(8,8,1,12,0);actual=input;allocations=frees=0;fail_allocation=1;assert(!void_touch_battle_solve(&actual)&&!frees);
 actual=input;allocations=frees=0;fail_allocation=2;assert(!void_touch_battle_solve(&actual)&&frees==1);fail_allocation=0;
 actual=input;actual.width=0;assert(!void_touch_battle_solve(&actual));
 actual=input;actual.width=65;assert(!void_touch_battle_solve(&actual));
 actual=input;actual.height=65;assert(!void_touch_battle_solve(&actual));
 actual=input;actual.mode=3;assert(!void_touch_battle_solve(&actual));
 actual=input;actual.start_x=-1;assert(!void_touch_battle_solve(&actual));
 actual=input;actual.start_y=8;assert(!void_touch_battle_solve(&actual));
 actual=input;actual.cells[3][1]^=1;assert(!void_touch_battle_solve(&actual));
 assert(!void_touch_battle_solve(NULL));
 puts("PASS copied-grid search: 442 complete native comparisons, exact costs/predecessors, all modes, stop cells, budgets,64x64, invalid input and allocation failures");
 return 0;
}
'''


class BattlePathTest(unittest.TestCase):
    def test_solver_matches_complete_original_all_editions(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text()
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM[:STREAM.index("static uint64_t clock_ns")].replace("memory[0x11070000]", "memory[0x1100000]")
        solver = (ROOT / "android/host/touch_combat_path.inc").read_text()
        self.assertNotRegex(solver, r"void_call_guest|MEM(?:8|16|32)|GPTR|ADDR|g_e(?:ax|cx|dx|sp)")
        for edition, (path, search, init, seed, pop, push, append, debug, release, directions) in LAYOUTS.items():
            with self.subTest(edition=edition):
                source = (ROOT / path).read_text()
                bodies = "\n".join(function(source, f"void sub_{address:08X}(void)") for address in (push, seed, pop, search))
                constants = (f"#define ORIGINAL_SEARCH sub_{search:08X}\n#define DIRECTIONS 0x{directions:X}u\n"
                             f"#define sub_{init:08X} queue_init\n#define sub_{append:08X} forbidden\n"
                             f"#define sub_{debug:08X} forbidden\n#define sub_{release:08X} storage_free\n")
                compile_probe("battle-path-original-" + edition,
                              prefix + constants + HARNESS.replace("/* SOLVER */", solver).replace("/* ORIGINAL BODIES */", bodies),
                              {"runtime.h": runtime, "touch_combat.h": (ROOT / "android/host/touch_combat.h").read_text()}, extra_flags=FLAGS, compiler_override=COMPILER)

    def test_original_builder_skips_search_for_precomputed_grid(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text()
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM[:STREAM.index("static uint64_t clock_ns")].replace("memory[0x11070000]", "memory[0x100000]")
        layouts = {
            "toe": ("generated/game-x86/game_0650.c", 0xC536F0, 0xC52CC0, 0xB5F0D0, 0xB5EE10, 0x879240),
            "vanilla": ("generated/vanilla/game-x86/game_0406.c", 0x8FE650, 0x8FDBB0, 0x922E80, 0x922BC0, 0xC00360),
            "hof": ("generated/hof/game-x86/game_0546.c", 0xABAE60, 0xABA2F0, 0x9A7F20, 0x9A7C60, 0xA99C10),
        }
        probe = r'''
static unsigned selections;
static void forbidden(void) {assert(!"precomputed grid repeated native construction/search or freed borrowed data");}
recomp_func_t void_resolve(uint32_t address) {(void)address;assert(0);return forbidden;}
static void select_path(void) {
 assert(g_ecx==0x70000&&MEM32(g_esp+4)==0x50030&&MEM32(g_esp+8)==0x5003C);
 ++selections;g_esp+=12;
}
static void original_branch(void) {
 uint32_t _cf=0,_flag_k=FK_NONE,_flag_a=0,_flag_b=0;
 RECOMP_REGS_LOCALS
 /* BRANCH */
 RECOMP_REGS_OUT();
}
int main(void) {
 g_esp=0x50000;g_ebx=0;MEM32(g_esp+0x94)=0x70000;MEM32(g_esp+0x80)=0x22000;
 original_branch();assert(selections==1&&g_esp==0x50000);
 puts("PASS original pathbuilder uses supplied grid and skips construction/search without freeing it");return 0;
}
'''
        for edition, (path, builder, initialize, search, select, release) in layouts.items():
            with self.subTest(edition=edition):
                body = function((ROOT / path).read_text(), f"void sub_{builder:08X}(void)")
                call = body.index(f"RECOMP_CALL(sub_{initialize:08X})")
                start = body.rfind("\nL_", 0, body.rfind("\nL_", 0, call))
                last_select = body.index(f"RECOMP_CALL(sub_{select:08X})", body.index(f"RECOMP_CALL(sub_{select:08X})", call) + 1)
                end = body.index("\nL_", last_select)
                label_end = body.index(":", end) + 1
                block = body[start:label_end]
                labels = set(re.findall(r"(L_[0-9A-F]+):", block))
                self.assertLessEqual(set(re.findall(r"goto (L_[0-9A-F]+)", block)), labels)
                self.assertIn("MEM32(esp + 0x94)", block)
                constants = (f"#define sub_{initialize:08X} forbidden\n#define sub_{search:08X} forbidden\n"
                             f"#define sub_{release:08X} forbidden\n#define sub_{select:08X} select_path\n")
                compile_probe("battle-path-precomputed-" + edition, prefix + constants + probe.replace("/* BRANCH */", block),
                              {"runtime.h": runtime}, extra_flags=FLAGS, compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
