"""Run native melee-availability queries with bounded memory and ABI spies."""
import sys
import tempfile
import unittest

from test_d3d_lifecycle import function
from test_fmod_latency import COMPILER, FLAGS
from test_fmod_stream import HARNESS as STREAM
from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(ROOT / "tools"))
from port_patches import adapt_host_source


# Original combat resolver + MoveAttack validator, not inferred class properties.
LAYOUTS = {
    "toe": (0x2A0, 0x40, 0x44, 0x48, 0x50, 0x74, 0xAF4450, 0x4E5790, 0xB3F2F0, 0xC53F60, 0x879240),
    "vanilla": (0x280, 0x3C, 0x40, 0x44, 0x48, 0x6C, 0x8275A0, 0xA04080, 0x83DB90, 0x8FEE00, 0xC00360),
    "hof": (0x294, 0x70, 0x6C, 0x168, 0x90, 0x8, 0xBC3680, 0xB2C220, 0xA71540, 0xABB610, 0xA99C10),
}

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x40000];
#include "touch_combat.h"
static void_touch_battle_grid test_grid;
static unsigned capture_mode,capture_fault,initializer_calls,stale_grid;
#define ADDR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)ADDR(a))
#define MEM8(a) (*(uint8_t *)ADDR(a))
typedef struct {uint32_t values[12];} void_regs;
static void_regs regs;
#define g_eax regs.values[0]
#define g_ebx regs.values[1]
#define g_ecx regs.values[2]
#define g_edx regs.values[3]
#define g_esi regs.values[4]
#define g_edi regs.values[5]
#define g_esp regs.values[6]
static void void_regs_save(void_regs *out) {*out=regs;}
static void void_regs_load(const void_regs *in) {regs=*in;}
static uint32_t unreadable_address;
static int void_vm_readable(uint32_t p,uint32_t n) {return p>=0x100&&p!=unreadable_address&&(uint64_t)p+n<=sizeof memory;}
static int allocation_fail,readonly_workspace;
static int void_vm_writable(uint32_t p,uint32_t n) {return !readonly_workspace&&void_vm_readable(p,n);}
static unsigned allocations,host_frees,unit_queries,path_queries,perimeter_queries,enemy_queries,visible_queries;
static unsigned native_frees[3],unit_count,perimeter_count,path_result,bad_units,bad_perimeter,bad_path;
static unsigned actor_size,mock_target_size,actor_speed,hero,mock_visible,enemy,flank_result;
static int mock_origin[2],destination[2],perimeter_cells[16][2];
static uint32_t void_galloc(uint32_t n) {assert(n==(capture_mode?32u:88u+4u*test_grid.height+8u*test_grid.width*test_grid.height));++allocations;return allocation_fail?0:0x8000;}
static void void_gfree(uint32_t p) {assert(p==0x8000);++host_frees;}
static int void_dispatch_find(uint32_t p) {return p>=0x7000&&p<0x7080;}
static void vector(uint32_t descriptor,uint32_t data,unsigned bytes) {
 MEM32(descriptor)=data;MEM32(descriptor+4)=MEM32(descriptor+8)=data+bytes;
}
static uint32_t void_call_guest(uint32_t address,int count,const uint32_t *args,int pops) {
 if(address==FREE) {
  assert(count==1&&pops==0&&args);
  assert(args[0]==0x9000||args[0]==0xA000||args[0]==0xB000);
  ++native_frees[(args[0]-0x9000)/0x1000];return 0;
 }
 assert(address==VALIDATOR&&count==7&&pops==1&&args);
 assert(g_esi==0x2000&&(g_edi==0x2200||g_edi==0x2400));
 assert(args[0]==0x8018&&args[1]==0&&args[2]==0x8024&&args[3]==0x3000);
 assert(args[4]==0&&args[5]==0&&args[6]==0x8040); /* Precomputed pathfinder; no native search. */
 assert(MEM32(0x8040)==0x8098&&MEM32(0x8044)==0x8058&&MEM32(0x8048)==16&&MEM32(0x804C)==16);
 assert(MEM32(0x8050)==test_grid.mode&&MEM32(0x8054)==test_grid.max_cost);
 for(unsigned row=0;row<16;++row)assert(MEM32(0x8058+4*row)==0x8098+128*row);
 assert(!memcmp(ADDR(0x8098),test_grid.cells,16*16*8));
 ++path_queries;
 unsigned result=path_result;
 if(g_ebx!=0x8030) {
  assert(g_ebx>=0xA000&&g_ebx<0xA000+128);
  result=flank_result&&MEM32(g_ebx)==(unsigned)perimeter_cells[perimeter_count-1][0]&&
      MEM32(g_ebx+4)==(unsigned)perimeter_cells[perimeter_count-1][1]?2:0;
 }
 if(result) {
  vector(args[0],0xB000,12*result);
  if(bad_path==1)MEM32(args[0]+4)=0xAFFC;
  if(bad_path==2)MEM32(args[0]+8)=0xB000;
  if(bad_path==3)MEM32(args[0]+4)=0xB001;
  if(bad_path==4)MEM32(args[0]+4)=MEM32(args[0]+8)=0xB000+12*4097;
  if(bad_path==5)unreadable_address=0xB000;
 }
 /* Real bridge may clobber all volatile registers. Full outer save must win. */
 g_eax=0xAA000000u|(result?255:0);g_ecx=123;g_edx=456;return g_eax;
}
static uint32_t void_call_guest_this(uint32_t address,uint32_t object,int count,const uint32_t *args) {
 if(address==INITIALIZER) {
  assert(capture_mode&&object==0x8000&&g_edx==0x2000&&count==INITIALIZER_ARGS&&args&&args[0]==0);
  if(count==2)assert(args[1]==0);
  ++initializer_calls;MEM32(object)=0x9000;MEM32(object+4)=0xA000;
  MEM32(object+8)=MEM32(object+12)=16;MEM32(object+16)=2;MEM32(object+20)=12;
  for(unsigned y=0;y<16;++y){MEM32(0xA000+4*y)=0x9000+128*y;for(unsigned x=0;x<16;++x) {
   MEM32(0x9000+8*(y*16+x))=0;MEM32(0x9004+8*(y*16+x))=(y<<6)|x|((x==0||y==0||x==15||y==15)?0x800000:0);
  }}
  if(capture_fault==1)MEM32(object+8)=65;
  if(capture_fault==2)MEM32(object+12)=65;
  if(capture_fault==3)MEM32(object+16)=3;
  if(capture_fault==4)unreadable_address=0xA000;
  if(capture_fault==5)MEM32(0xA004)=sizeof memory;
  return 0;
 }
 if(address==0x7000) {assert(object==0x3108&&!count&&!args);return 0x12345678;}
 if(address==0x7010) {
  assert(count==1&&args);const int *p=object==0x2000?mock_origin:destination;
  MEM32(args[0])=(uint32_t)p[0];MEM32(args[0]+4)=(uint32_t)p[1];return capture_fault==6?0:args[0];
 }
 if(address==0x7020) {assert(!count&&!args);return object==0x2000?actor_size:mock_target_size;}
 if(address==0x7030) {assert(object==0x2000&&!count&&!args);return actor_speed;}
 if(address==0x7040) {
  assert((object==0x2200||object==0x2400)&&count==1&&args[0]==0x12345678);
  ++visible_queries;return 0xBB000000u|mock_visible;
 }
 if(address==0x7050) {assert(!count&&!args);return hero;}
 if(address==ALL_UNITS) {
  assert(object==0x3000&&g_edx==0x8000&&!count&&!args);++unit_queries;
  vector(g_edx,0x9000,4*unit_count);
  if(bad_units==1)MEM32(g_edx+4)=0x8FFC;
  if(bad_units==2)MEM32(g_edx+8)=0x9000;
  if(bad_units==3)MEM32(g_edx+4)=0x9001;
  if(bad_units==4)MEM32(g_edx+4)=MEM32(g_edx+8)=0x9000+4*4097;
  if(bad_units==5)unreadable_address=0x9000;
  return 0;
 }
 if(address==ENEMY) {
  assert(object==0x2000&&!count&&!args&&g_edx==g_esi&&(g_esi==0x2200||g_esi==0x2400));
  ++enemy_queries;return 0xCC000000u|enemy;
 }
 assert(address==PERIMETER&&object==0x800C&&g_edx==0x2000&&count==1&&args);
 assert(args[0]==0x2200||args[0]==0x2400);++perimeter_queries;
 vector(object,0xA000,8*perimeter_count);memcpy(ADDR(0xA000),perimeter_cells,sizeof perimeter_cells);
 if(bad_perimeter==1)MEM32(object+4)=0x9FFC;
 if(bad_perimeter==2)MEM32(object+8)=0xA000;
 if(bad_perimeter==3)MEM32(object+4)=0xA001;
 if(bad_perimeter==4)MEM32(object+4)=MEM32(object+8)=0xA000+8*17;
 if(bad_perimeter==5)unreadable_address=0xA000;
 return 0;
}
/* PRODUCTION */
static void reset(void) {
 memset(memory,0,sizeof memory);memset(native_frees,0,sizeof native_frees);
 memset(&test_grid,0,sizeof test_grid);test_grid.width=test_grid.height=16;test_grid.mode=1;
 test_grid.max_cost=12;test_grid.start_x=test_grid.start_y=5;
 for(unsigned i=0;i<256;++i){test_grid.cells[i][0]=i;test_grid.cells[i][1]=(i%16)|((i/16)<<6);}
 capture_mode=capture_fault=initializer_calls=stale_grid=0;
 allocations=host_frees=unit_queries=path_queries=perimeter_queries=enemy_queries=visible_queries=0;
 allocation_fail=readonly_workspace=bad_units=bad_perimeter=bad_path=0;unreadable_address=0;
 actor_size=mock_target_size=mock_visible=enemy=1;actor_speed=6;hero=0;path_result=3;flank_result=0;
 unit_count=2;perimeter_count=3;mock_origin[0]=mock_origin[1]=5;destination[0]=8;destination[1]=5;
 perimeter_cells[0][0]=perimeter_cells[0][1]=5;perimeter_cells[1][0]=6;perimeter_cells[1][1]=4;perimeter_cells[2][0]=6;perimeter_cells[2][1]=6;
 MEM32(0x1000+ARENA)=0x3000;
 for(uint32_t actor=0x2000;actor<=0x2400;actor+=0x200) {
  MEM32(actor)=0x4000;MEM32(actor+4)=0x5000;
 }
 MEM32(0x5004)=0xFC;MEM32(0x3004)=0x5100;MEM32(0x5108)=0x104;
 MEM32(0x3108)=0x5200;MEM32(0x5240)=0x7000;
 MEM32(0x4000+POSITION)=0x7010;MEM32(0x4000+SIZE)=0x7020;
 MEM32(0x4000+SPEED)=0x7030;MEM32(0x4000+VISIBLE)=0x7040;MEM32(0x4000+HERO)=0x7050;
 MEM32(0x9000)=0x2000;MEM32(0x9004)=0x2200;
 for(unsigned i=0;i<12;++i)regs.values[i]=100+i;
}
static int run(int cap) {
 if(!stale_grid)test_grid.max_cost=actor_speed*2;
 void_regs saved=regs;int result=combat_alternative_available_grid(0x1000,0x2000,cap,&test_grid);
 assert(!memcmp(&saved,&regs,sizeof regs));
 assert(host_frees==(allocations&&!allocation_fail?1u:0u));return result;
}
static int capture(void) {
 capture_mode=1;void_regs saved=regs;int result=combat_grid_capture(0x1000,0x2000,&test_grid);
 assert(!memcmp(&saved,&regs,sizeof regs));
 assert(host_frees==(allocations&&!allocation_fail?1u:0u));return result;
}
int main(void) {
 reset();assert(capture()==1&&initializer_calls==1&&test_grid.width==16&&test_grid.height==16&&test_grid.mode==2&&test_grid.max_cost==12);
 assert(test_grid.start_x==5&&test_grid.start_y==5&&native_frees[0]==1&&native_frees[1]==1);
 for(unsigned y=0;y<16;++y)for(unsigned x=0;x<16;++x)
  assert(test_grid.cells[y*16+x][1]==((y<<6)|x|((x==0||y==0||x==15||y==15)?0x800000u:0)));
 for(unsigned fault=1;fault<=6;++fault){reset();capture_fault=fault;assert(!capture()&&!test_grid.width&&native_frees[0]==1&&native_frees[1]==1);}
 reset();allocation_fail=1;assert(!capture()&&!initializer_calls&&!host_frees);
 reset();readonly_workspace=1;assert(!capture()&&!initializer_calls&&host_frees==1);
 reset();MEM8(0x2107)=0x80;assert(!capture()&&!initializer_calls&&!allocations);
 reset();mock_origin[0]=16;assert(!capture()&&!test_grid.width&&native_frees[0]==1&&native_frees[1]==1);
 reset();stale_grid=1;test_grid.start_x=4;assert(!run(3)&&!unit_queries);
 reset();stale_grid=1;test_grid.max_cost=10;assert(!run(3)&&!unit_queries);
 reset();test_grid.width=65;assert(!run(3)&&!allocations);
 reset();assert(run(0)==0&&!allocations&&!unit_queries);
 for(int cap=1;cap<=3;++cap) {
  reset();assert(run(cap)==cap&&path_queries==1&&!perimeter_queries&&unit_queries==1);
  assert(native_frees[0]==1&&!native_frees[1]&&native_frees[2]==1);
 }
 reset();path_result=0;assert(!run(3)&&path_queries==1&&!perimeter_queries);
 reset();path_result=1;assert(run(1)==1&&path_queries==1&&!perimeter_queries);
 reset();path_result=1;assert(!run(2)&&path_queries==3&&perimeter_queries==1);
 assert(native_frees[0]==1&&native_frees[1]==1&&native_frees[2]==1);
 reset();path_result=1;flank_result=1;assert(run(3)==3&&path_queries==3&&perimeter_queries==1);
 reset();path_result=1;flank_result=1;perimeter_count=16;
 for(unsigned i=0;i<16;++i){perimeter_cells[i][0]=6+(i%4);perimeter_cells[i][1]=3+(i/4);}
 assert(run(2)==2&&path_queries==17&&perimeter_queries==1);
 reset();unit_count=3;MEM32(0x9008)=0x2400;assert(run(3)==3&&path_queries==1); /* Early exit. */
 reset();unit_count=0;assert(!run(3)&&!path_queries&&native_frees[0]==1);
 reset();MEM32(0x9004)=0;assert(!run(3)&&!path_queries);
 reset();MEM32(0x4000+VISIBLE)=0;assert(!run(3)&&!path_queries);
 reset();mock_visible=0;assert(!run(3)&&!path_queries&&!enemy_queries);
 reset();enemy=0;assert(!run(3)&&!path_queries&&enemy_queries==1);
 reset();hero=0x7777;assert(!run(3)&&!path_queries&&!visible_queries);
 reset();MEM8(0x2307)=0x80;assert(!run(3)&&!path_queries&&!visible_queries);
 reset();MEM8(0x2107)=0x80;assert(!run(3)&&!allocations);
 reset();MEM32(0x3004)=0;assert(!run(3)&&!allocations);
 reset();MEM32(0x4000+SPEED)=0;assert(!run(3)&&!allocations);
 reset();allocation_fail=1;assert(!run(3)&&allocations==1&&!host_frees&&!unit_queries);
 reset();readonly_workspace=1;assert(!run(3)&&host_frees==1&&!native_frees[0]);
 reset();actor_speed=(unsigned)-1;assert(!run(3)&&!unit_queries);
 reset();actor_speed=0x7FFFFFFF;assert(run(3)==3); /* No range arithmetic overflow. */
 reset();actor_speed=2;destination[0]=9;assert(!run(3)&&!path_queries);
 reset();actor_speed=2;destination[0]=8;assert(run(3)==3&&path_queries==1); /* Boundary reachable. */
 reset();actor_speed=2;actor_size=mock_target_size=2;destination[0]=9;assert(run(3)==3);
 reset();actor_speed=2;actor_size=2;destination[0]=1;assert(run(3)==3); /* Negative direction. */
 reset();destination[0]=64;assert(!run(3)&&!path_queries);
 reset();mock_origin[1]=-1;assert(!run(3)&&!unit_queries);
 reset();actor_size=3;assert(!run(3)&&!unit_queries);
 reset();mock_target_size=3;assert(!run(3)&&!path_queries);
 for(unsigned fault=1;fault<=5;++fault) {
  reset();bad_units=fault;assert(!run(3)&&!path_queries&&native_frees[0]==1);
  reset();bad_path=fault;assert(!run(3)&&path_queries==1&&native_frees[2]==1);
  reset();bad_perimeter=fault;path_result=1;assert(run(3)==1&&path_queries==1&&perimeter_queries==1);
 }
 /* A native validator returning false must not reuse the previous successful vector. */
 reset();path_result=1;flank_result=0;assert(run(3)==1&&path_queries==3);
 puts("PASS native availability: reachable target, flank movement, guards, all ABIs, bounded calls, register and allocation cleanup");
 return 0;
}
'''


ORIGINAL = r'''
static unsigned type=1,dead,attackable=1,path_success=255,path_calls,precomputed;
static void kind(void) {assert(g_ecx==0x20000);g_eax=type;g_esp+=4;}
static void dying(void) {assert(g_ecx==0x22000);g_eax=0xAA000000u|dead;g_esp+=4;}
static void legal(void) {assert(g_ecx==0x22000);g_eax=0xAA000000u|attackable;g_esp+=4;}
static void ability(void) {
 assert(g_ecx==0x20000&&(MEM32(g_esp+4)==119||MEM32(g_esp+4)==123));
 g_eax=0xAA000000;g_esp+=8;
}
static void speed(void) {assert(g_ecx==0x20000);g_eax=6;g_esp+=4;}
static void position(void) {
 assert(g_ecx==0x20000);uint32_t cell=MEM32(g_esp+4);
 MEM32(cell)=5;MEM32(cell+4)=5;g_eax=cell;g_esp+=8;
}
recomp_func_t void_resolve(uint32_t address) {
 switch(address) {
 case 0x70000:return kind;case 0x70010:return dying;case 0x70020:return legal;
 case 0x70030:return ability;case 0x70040:return speed;case 0x70050:return position;
 default:assert(0);return kind;
 }
}
void sub_00A6AFD0(void) {
 assert(g_ecx==0x22000&&g_edx==0x20000&&MEM32(g_esp+4)==0);
 g_eax=0xBB000000u|attackable;g_esp+=8;
}
static void path_builder(void) {
 assert(g_ecx==0x60000&&g_edx==0x6000C);
 assert(MEM32(g_esp+4)==0x30000&&MEM32(g_esp+8)==0x20000);
 uint32_t start=MEM32(g_esp+12);assert(MEM32(start)==5&&MEM32(start+4)==5);
 assert(MEM32(g_esp+16)==0x22000&&MEM32(g_esp+20)==0x60100);
 assert(MEM32(g_esp+24)==0&&MEM32(g_esp+28)==precomputed);
 ++path_calls;g_eax=0xCC000000u|path_success;g_esp+=32;
}
static void damage_forbidden(void) {assert(!"read-only query reached native damage prediction");}
/* ORIGINAL BODY */
static void reset(void) {
 memset(memory,0,0x80000);type=1;dead=0;attackable=1;path_success=255;path_calls=0;precomputed=0;
 g_eax=g_ecx=g_edx=0;g_esi=0x20000;g_edi=0x22000;g_ebx=0x60100;g_ebp=0x77777;g_esp=0x50000;
 MEM32(g_esp)=0x12345678;
 const uint32_t args[]={0x60000,0,0x6000C,0x30000,0,0,0};
 for(unsigned i=0;i<7;++i)MEM32(g_esp+4+4*i)=args[i];
 MEM32(0x20000)=MEM32(0x22000)=0x40000;
 MEM32(0x20004)=MEM32(0x22004)=0x41000;MEM32(0x41004)=0xFC;
 MEM32(0x40000+TYPE_SLOT)=0x70000;MEM32(0x40000+DEAD_SLOT)=0x70010;
 MEM32(0x40000+LEGAL_SLOT)=0x70020;MEM32(0x40000+0x28C)=0x70030;
 MEM32(0x40000+SPEED_SLOT)=0x70040;MEM32(0x40000+POSITION_SLOT)=0x70050;
 MEM32(0x60100)=8;MEM32(0x60104)=5;
}
static unsigned run(void) {
 ORIGINAL_FUNCTION();assert(g_esp==0x50020&&g_esi==0x20000&&g_edi==0x22000&&g_ebx==0x60100&&g_ebp==0x77777);
 return g_eax&255;
}
int main(void) {
 reset();assert(run()==1&&path_calls==1);
 reset();precomputed=0x60200;MEM32(0x5001C)=precomputed;assert(run()==1&&path_calls==1);
 reset();path_success=0;assert(run()==0&&path_calls==1);
 reset();type=2;assert(run()==0&&!path_calls);
 reset();dead=255;assert(run()==0&&!path_calls);
 reset();attackable=0;assert(run()==0&&!path_calls);
 reset();MEM32(0x5000C)=0;assert(run()==0&&!path_calls); /* Required cost output. */
 puts("PASS original validator: full body, ESI/EDI/EBX, seven stack arguments, exact cleanup, legality gates and no damage");
 return 0;
}
'''


class AttackAvailableTest(unittest.TestCase):
    def test_production_queries_all_editions(self):
        names = ("ARENA", "POSITION", "SIZE", "SPEED", "VISIBLE", "HERO", "ALL_UNITS", "ENEMY", "PERIMETER", "VALIDATOR", "FREE")
        for edition, layout in LAYOUTS.items():
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                path, _ = adapt_host_source(ROOT / "android/host/touch_engine.c", tmp, edition)
                source = path.read_text().replace('#include "touch_combat_query.inc"', (ROOT / "android/host/touch_combat_query.inc").read_text())
                declarations = (
                    "static uint32_t read32(", "static uint32_t virtual_base(",
                    "static uint32_t object_method(uint32_t object, unsigned offset)\n{",
                    "static uint32_t object_query(", "static int combat_grid_capture(",
                    "static unsigned combat_alternative_path(", "static int combat_alternative_available_grid(")
                helpers = "\n".join(function(source, declaration) for declaration in declarations)
                constants = "\n".join(f"#define {name} 0x{value:X}u" for name, value in zip(names, layout))
                initializer, initializer_args = {"toe": (0xC52CC0, 2), "vanilla": (0x8FDBB0, 1), "hof": (0xABA2F0, 1)}[edition]
                constants += f"\n#define INITIALIZER 0x{initializer:X}u\n#define INITIALIZER_ARGS {initializer_args}\n"
                compile_probe("attack-available-" + edition, constants + "\n" + HARNESS.replace("/* PRODUCTION */", helpers), {"touch_combat.h": (ROOT / "android/host/touch_combat.h").read_text()})

    def test_original_validator_abi_all_editions(self):
        runtime = (ROOT / "android/runtime/recomp_types.h").read_text()
        runtime = runtime.replace('#error "This header is the ARM64 runtime model; x86 builds use native/recomp_types.h"', "")
        runtime = runtime.replace(function(runtime, "static inline uint64_t __rdtsc("), "")
        prefix = STREAM[:STREAM.index("static uint64_t clock_ns")].replace("memory[0x11070000]", "memory[0x100000]")
        bodies = {
            "toe": ("generated/game-x86/game_0650.c", 0xC53F60, 0xC536F0, 0xA63020, 0, 0x5C, 0xCC, 0x48, 0x40),
            "vanilla": ("generated/vanilla/game-x86/game_0406.c", 0x8FEE00, 0x8FE650, 0x8EFC70, 0, 0x54, 0xCC, 0x44, 0x3C),
            "hof": ("generated/hof/game-x86/game_0548.c", 0xABB610, 0xABAE60, 0x7E66F0, 0x28, 0x148, 0xA0, 0x168, 0x70),
        }
        for edition, (path, validator, builder, damage, kind, dead, legal, speed, position) in bodies.items():
            with self.subTest(edition=edition):
                body = function((ROOT / path).read_text(), f"void sub_{validator:08X}(void)")
                constants = (f"#define ORIGINAL_FUNCTION sub_{validator:08X}\n"
                             f"#define sub_{builder:08X} path_builder\n#define sub_{damage:08X} damage_forbidden\n"
                             f"#define TYPE_SLOT {kind}\n#define DEAD_SLOT {dead}\n#define LEGAL_SLOT {legal}\n"
                             f"#define SPEED_SLOT {speed}\n#define POSITION_SLOT {position}\n")
                compile_probe("attack-validator-original-" + edition,
                              prefix + constants + ORIGINAL.replace("/* ORIGINAL BODY */", body),
                              {"runtime.h": runtime}, extra_flags=FLAGS, compiler_override=COMPILER)


if __name__ == "__main__":
    unittest.main()
