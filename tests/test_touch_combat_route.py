"""Capture original MoveAttack world points and the camera for worker-side projection."""
import re
import sys
import tempfile
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(ROOT / "tools"))
from port_patches import adapt_host_source


# Original command constructors C54390/8FF290/ABB9F0: actor+10, float3 vector+14.
# size(this)->unsigned, arena.position(this,outWorld3,cell2)->outWorld3.
LAYOUTS = {
    "toe": (0xA4, 0x2A0, 0x44, 0x6C, 0x33C, 0xE8DFE4, 0x40, 0x190),
    "vanilla": (0x9C, 0x280, 0x40, 0x78, 0x334, 0xE39424, 0x3C, 0x164),
    "hof": (0x9C, 0x294, 0x6C, 0x6C, 0x34C, 0xE268A4, 0x70, 0x14C),
}

HARNESS = r"""
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x10000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
static uint32_t camera_scratch;
static unsigned size_calls,cell_calls,allocations;
static int void_verbose=1,mock_flying;
static unsigned position_calls,flying_calls,logs;
static char diagnostic[2048];
#define VLOG(...) probe_log(__VA_ARGS__)
static void probe_log(const char *format,...) {
 va_list args;va_start(args,format);vsnprintf(diagnostic,sizeof diagnostic,format,args);va_end(args);++logs;
}
static unsigned unit_size=1;
static int allocation_fails,scratch_readonly,bad_cell,bad_world;
static int visited[128][2];
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100 && (uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n) {return !scratch_readonly&&void_vm_readable(a,n);}
static uint32_t void_galloc(uint32_t n) {assert(n==0x800);++allocations;return allocation_fails?0:0x8000;}
static int void_dispatch_find(uint32_t method) {return method>=0x7010&&method<=0x7040&&method%16==0;}
static void world_cell(int x,int y,float output[3]) {
 output[0]=2.0f*x+1;output[1]=2.0f*y+2;output[2]=.1f*x+.2f*y+.3f;
}
static uint32_t void_call_guest_this(uint32_t method,uint32_t actor,int n,const uint32_t *args) {
 if(method==0x7010) {assert(actor>=0x2000&&actor<=0x3F00&&n==0&&!args);++size_calls;return unit_size;}
 if(method==0x7030) {assert(actor>=0x2000&&actor<=0x3F00&&n==1&&args&&args[0]==camera_scratch+0x780);
  ++position_calls;MEM32(args[0])=3+(actor-0x2000)/256;MEM32(args[0]+4)=4;return args[0];}
 if(method==0x7040) {assert((actor==0x2000||actor==0x2100)&&n==0&&!args);++flying_calls;return 0xCAFE00u|(unsigned)mock_flying;}
 assert(method==0x7020&&actor==0x3000&&n==2&&args&&args[0]==camera_scratch+0x790&&args[1]==camera_scratch+0x780);
 int x=(int32_t)MEM32(args[1]),y=(int32_t)MEM32(args[1]+4);
 assert(cell_calls<128);visited[cell_calls][0]=x;visited[cell_calls][1]=y;++cell_calls;
 float world[3];world_cell(x,y,world);if(bad_world)world[1]=NAN;
 memcpy(GPTR(args[0]),world,sizeof world);
 return bad_cell?args[0]+4:args[0];
}
/* PRODUCTION */
static float buffer[COMBAT_ROUTE_FLOATS+2],native_path[256][3];
static const int route_cells[6][2]={{3,4},{4,4},{4,5},{5,5},{6,5},{7,5}};
static void close_to(float a,float b) {assert(isfinite(a)&&fabsf(a-b)<.00001f);}
static void matrix(void) {
 memset(combat_projection.matrix,0,sizeof combat_projection.matrix);
 combat_projection.matrix[0]=.025f;combat_projection.matrix[1]=.01f;
 combat_projection.matrix[2]=.03f;combat_projection.matrix[3]=-.2f;
 combat_projection.matrix[4]=-.01f;combat_projection.matrix[5]=.04f;
 combat_projection.matrix[6]=.02f;combat_projection.matrix[7]=.3f;
 combat_projection.matrix[12]=.002f;combat_projection.matrix[13]=.003f;
 combat_projection.matrix[14]=.004f;combat_projection.matrix[15]=1;
}
static void expect_point(unsigned index,float x,float y,float z) {
 close_to(buffer[21+3*index],x);close_to(buffer[22+3*index],y);close_to(buffer[23+3*index],z);
}
static void path_count(unsigned n) {
 MEM32(0x9014)=0xA000;MEM32(0x9018)=MEM32(0x901C)=0xA000+12*n;
}
static void reset(void) {
 memset(memory,0,sizeof memory);memset(&combat_route,0,sizeof combat_route);
 memset(&combat_projection,0,sizeof combat_projection);
 for(unsigned i=0;i<COMBAT_ROUTE_FLOATS+2;++i)buffer[i]=12345;
 camera_scratch=0;size_calls=cell_calls=allocations=0;unit_size=1;
 void_verbose=1;mock_flying=0;position_calls=flying_calls=logs=0;diagnostic[0]=0;
 allocation_fails=scratch_readonly=bad_cell=bad_world=0;
 MEM32(0x1000+CAMERA)=0x6000;MEM32(0x1000+ARENA)=0x3000;MEM32(0x1000+COMMAND)=0x9000;
 MEM32(0x2000)=MEM32(0x2100)=0x4000;MEM32(0x3000)=0x5000;
 MEM32(0x4000+SIZE)=0x7010;MEM32(0x5000+CELL)=0x7020;
 MEM32(0x4000+POSITION)=0x7030;MEM32(0x4000+FLYING)=0x7040;
 MEM32(0x9000)=COMMAND_VTABLE;MEM32(0x9010)=0x2000;path_count(6);
 for(unsigned i=0;i<256;++i)world_cell(1+(int)(i%30),1+(int)((i/30)%30),native_path[i]);
 for(unsigned i=0;i<6;++i)world_cell(route_cells[i][0],route_cells[i][1],native_path[i]);
 memcpy(GPTR(0xA000),native_path,sizeof native_path);
 combat_projection.valid=1;combat_projection.screen=0x1000;combat_projection.camera=0x6000;matrix();
}
static unsigned run(uint32_t generation,int returning) {
 unsigned count=void_touch_combat_route(0x1000,0x2000,7,5,generation,returning,2,0,buffer+1);
 assert(buffer[0]==12345&&buffer[COMBAT_ROUTE_FLOATS+1]==12345);return count;
}
static void check_path(unsigned n) {
 assert(buffer[2]==(float)n);
 assert(!memcmp(buffer+5,combat_projection.matrix,sizeof combat_projection.matrix));
 for(unsigned i=0;i<n;++i)expect_point(i,native_path[i][0]-(unit_size-1),
  native_path[i][1]-(unit_size-1),native_path[i][2]+.08f);
}
static void check_footprint(unsigned n) {
 const int cells[4][2]={{7,5},{7,4},{6,5},{6,4}};
 const float corners[4][2]={{-1.09f,-1.09f},{1.09f,-1.09f},{1.09f,1.09f},{-1.09f,1.09f}};
 for(unsigned c=0;c<unit_size*unit_size;++c) {
  int x=cells[c][0],y=cells[c][1];float world[3];world_cell(x,y,world);
  assert(visited[c][0]==x&&visited[c][1]==y);
  for(unsigned corner=0;corner<4;++corner)
   expect_point(n+4*c+corner,world[0]+corners[corner][0],world[1]+corners[corner][1],world[2]+.05f);
 }
}
int main(void) {
 assert(COMBAT_ROUTE_MAX_POINTS==256&&COMBAT_ROUTE_FLOATS==935);
 reset();assert(run(1,0)==50&&buffer[1]==1);
 assert(size_calls==1&&cell_calls==1&&allocations==1);check_path(6);check_footprint(6);
 assert(buffer[51]==12345); /* Header, six world points and one destination quad. */
 assert(position_calls==1&&flying_calls==1&&logs==1);
 assert(strstr(diagnostic,"source=3,4 destination=7,5 flying=0 points=6 shown=6"));
 assert(strstr(diagnostic,"last=(15.000,12.000,2.000) ground=(15.000,12.000,2.000) delta_z=0.000"));
 assert(strstr(diagnostic,"path=(7.000,10.000,1.400);(9.000,10.000,1.500)"));
 /* The bends come from the command, not interpolation between its first/last point. */
 assert(native_path[1][1]==native_path[0][1]&&native_path[2][0]==native_path[1][0]);
 /* Only the camera header changes; projection and perspective division belong to the worker. */
 float old_matrix=buffer[8];combat_projection.matrix[3]+=.2f;
 memset(GPTR(0xA000),0,sizeof native_path); /* Native command may be rebuilt after cache capture. */
 for(unsigned i=0;i<50;++i)assert(run(1,1)==50&&buffer[1]==2);
 assert(buffer[8]>old_matrix&&size_calls==1&&cell_calls==1&&allocations==1);check_path(6);
 assert(position_calls==1&&flying_calls==1&&logs==1);
 memcpy(GPTR(0xA000),native_path,sizeof native_path);
 ((float *)GPTR(0xA000))[3]+=.5f;native_path[1][0]+=.5f;cell_calls=0;
 assert(run(2,0)==50&&size_calls==2&&cell_calls==1);check_path(6);
 /* A size2 footprint biases every path XY equally; each native terrain Z stays distinct. */
 reset();unit_size=2;assert(run(2,1)==86&&buffer[1]==2);
 assert(size_calls==1&&cell_calls==4&&allocations==1);check_path(6);check_footprint(6);
 cell_calls=0;assert(run(3,0)==86&&size_calls==2&&cell_calls==4&&allocations==1);
 cell_calls=0;MEM32(0x9010)=0x2100;
 assert(void_touch_combat_route(0x1000,0x2100,7,5,3,0,2,0,buffer+1)==86);
 assert(size_calls==3&&cell_calls==4&&allocations==1);
 /* Adjacent melee has one native point; a flying route legitimately has only two. */
 reset();memcpy(native_path[0],native_path[5],12);memcpy(GPTR(0xA000),native_path[0],12);path_count(1);
 assert(run(1,1)==35);check_path(1);check_footprint(1);
 reset();mock_flying=1;memcpy(native_path[1],native_path[5],12);memcpy(GPTR(0xA000),native_path,24);path_count(2);
 assert(run(1,0)==38&&cell_calls==1);check_path(2);check_footprint(2);
 assert(strstr(diagnostic,"flying=1 points=2 shown=2"));
 reset();native_path[5][2]+=2.5f;memcpy(GPTR(0xA000),native_path,sizeof native_path);
 assert(run(1,0)==50&&cell_calls==1);check_path(6);check_footprint(6);
 assert(strstr(diagnostic,"last=(15.000,12.000,4.500) ground=(15.000,12.000,2.000) delta_z=2.500"));
 reset();unit_size=2;path_count(256);assert(run(1,1)==20+3*(256+16));
 check_path(256);check_footprint(256);
 assert(logs==1&&strstr(diagnostic,"points=256 shown=32"));
 reset();void_verbose=0;assert(run(1,0)==50&&!logs&&!position_calls&&!flying_calls);
 reset();path_count(257);assert(!run(1,0)&&!size_calls&&!cell_calls&&!allocations);
 /* Invalid generation/projection/owner never queries the guest. */
 reset();assert(!run(0,0));combat_projection.valid=0;assert(!run(1,0));combat_projection.valid=1;
 combat_projection.screen=0x1100;assert(!run(1,0));combat_projection.screen=0x1000;
 MEM32(0x1000+CAMERA)=0x6100;assert(!run(1,0));MEM32(0x1000+CAMERA)=0x6000;
 combat_projection.screen=0xFFF0;
 assert(!void_touch_combat_route(0xFFF0,0x2000,7,5,1,0,2,0,buffer+1));
 assert(!size_calls&&!cell_calls&&!allocations);
 /* Wrong command class/actor, malformed or unreadable vectors never invoke native methods. */
 for(int bad=0;bad<12;++bad) {
  reset();
  switch(bad) {
   case 0:MEM32(0x1000+COMMAND)=0;break;
   case 1:MEM32(0x1000+COMMAND)=0xFFF0;break;
   case 2:++MEM32(0x9000);break;
   case 3:MEM32(0x9010)=0x2100;break;
   case 4:MEM32(0x9014)=0;break;
   case 5:MEM32(0x9018)=0x9FF4;break;
   case 6:MEM32(0x901C)=0xA000;break;
   case 7:MEM32(0x9018)=0xA00D;break;
   case 8:++MEM32(0x901C);break;
   case 9:path_count(0);break;
   case 10:MEM32(0x9014)=0xFFF0;MEM32(0x9018)=MEM32(0x901C)=0x10008;break;
   case 11:MEM32(0x9014)=0xFFFFFFF0;MEM32(0x9018)=MEM32(0x901C)=8;break;
  }
  assert(!run(1,0)&&!size_calls&&!cell_calls&&!allocations);
 }
 for(unsigned axis=0;axis<3;++axis)for(unsigned bad=0;bad<3;++bad) {
  reset();((float *)GPTR(0xA000))[3*2+axis]=bad==0?NAN:bad==1?INFINITY:-INFINITY;
  assert(!run(1,0)&&!size_calls&&!cell_calls&&!allocations);
 }
 /* Bad object methods and native footprint failures are bounded. */
 reset();MEM32(0x2000)=0xFFF0;assert(!run(1,0));MEM32(0x2000)=0x4000;
 MEM32(0x1000+ARENA)=0;assert(!run(1,0));MEM32(0x1000+ARENA)=0x3000;
 MEM32(0x5000+CELL)=0x9999;assert(!run(1,0));assert(!size_calls&&!cell_calls&&!allocations);
 reset();unit_size=0;assert(!run(1,0));unit_size=3;assert(!run(1,0));
 unit_size=2;assert(!void_touch_combat_route(0x1000,0x2000,0,5,1,0,2,0,buffer+1));
 assert(!void_touch_combat_route(0x1000,0x2000,7,0,1,0,2,0,buffer+1));
 unit_size=1;assert(!void_touch_combat_route(0x1000,0x2000,-1,5,1,0,2,0,buffer+1));
 assert(!void_touch_combat_route(0x1000,0x2000,64,5,1,0,2,0,buffer+1));assert(!cell_calls&&!allocations);
 reset();allocation_fails=1;assert(!run(1,0)&&!cell_calls);
 reset();scratch_readonly=1;assert(!run(1,0)&&!cell_calls);
 reset();bad_cell=1;assert(!run(1,0)&&cell_calls==1);
 reset();bad_world=1;assert(!run(1,0)&&cell_calls==1);
 /* Nonfinite headers are rejected; finite clipping decisions are deferred to the render worker. */
 reset();assert(run(1,0)==50);combat_projection.matrix[0]=NAN;assert(!run(1,0));
 matrix();combat_projection.matrix[15]=-2;assert(run(1,0)==50);check_path(6);
 matrix();combat_projection.matrix[12]=combat_projection.matrix[13]=combat_projection.matrix[14]=combat_projection.matrix[15]=0;
 assert(run(1,0)==50);matrix();assert(run(1,0)==50);
 assert(size_calls==1&&cell_calls==1&&allocations==1);
 puts("PASS native command route: all-edition world snapshot, 1/2/256 native points, bounds/NaN guards, footprint/original Z, immutable points with current matrix, bounded atomic diagnostics");
 return 0;
}
"""


class CombatRouteTest(unittest.TestCase):
    def test_native_melee_victims_and_single_ranged_target(self):
        header = (ROOT / "android/host/touch.h").read_text()
        packet = re.search(r"enum \{ COMBAT_ROUTE_MAX_POINTS =[^;]+;", header)[0]
        for edition, values in LAYOUTS.items():
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                path, _ = adapt_host_source(ROOT / "android/host/touch_camera.c", tmp, edition)
                source = path.read_text()
                start = source.index("static struct { uint32_t screen, camera; float matrix[16]; int valid; } combat_projection;")
                end = source.index("\nstatic struct {\n    uint32_t camera, screen, phase;", start)
                production = function(source, "static uint32_t camera_method(") + source[start:end]
                constants = "".join(f"#define {name} {value}\n" for name, value in zip(
                    ("CAMERA", "ARENA", "SIZE", "CELL", "COMMAND", "COMMAND_VTABLE", "POSITION", "FLYING"), values))
                victims = {"toe": 0x358, "vanilla": 0x350, "hof": 0x368}[edition]
                constants += f"#define VICTIMS {victims}\n"
                main = r'''
int main(void) {
 reset();void_verbose=0;
 MEM32(0x2200)=MEM32(0x2300)=0x4000;
 MEM32(0x1000+VICTIMS)=0xB000;MEM32(0x1004+VICTIMS)=MEM32(0x1008+VICTIMS)=0xB014;
 MEM32(0xB000)=0x2100;MEM32(0xB004)=0x2200;MEM32(0xB008)=0x2300;
 MEM32(0xB00C)=0x2200;MEM32(0xB010)=0x2000;
 /* A cerberus-like native forecast: one primary and two extra victims; no duplicate or self arrow. */
 unsigned n=void_touch_combat_route(0x1000,0x2000,7,5,1,0,3,0x2100,buffer+1);
 assert(n==62&&buffer[2]==6&&buffer[3]==1&&buffer[4]==3);
 expect_point(10,native_path[5][0],native_path[5][1],native_path[5][2]+.08f);
 for(unsigned i=0;i<3;++i){float world[3];world_cell(4+i,4,world);expect_point(11+i,world[0],world[1],world[2]+.12f);}
 unsigned calls=cell_calls;
 for(unsigned i=0;i<1000;++i)assert(void_touch_combat_route(0x1000,0x2000,7,5,1,0,3,0x2100,buffer+1)==n);
 assert(cell_calls==calls);
 /* A hydra-like surround keeps every distinct victim, including large footprints. */
 cell_calls=0;MEM32(0x1004+VICTIMS)=MEM32(0x1008+VICTIMS)=0xB020;
 for(unsigned i=0;i<8;++i){MEM32(0xB000+4*i)=0x2100+0x100*i;MEM32(0x2100+0x100*i)=0x4000;}
 assert(void_touch_combat_route(0x1000,0x2000,7,5,2,1,3,0x2100,buffer+1)==77&&buffer[4]==8);
 /* Ranged AoE and hero attacks ignore the fan: exactly one arrow, no movement dashes or footprint. */
 for(unsigned action=4;action<=9;++action) {
  cell_calls=0;
  n=void_touch_combat_route(0x1000,0x2000,7,5,action,0,action,0x2100,buffer+1);
  assert(n==26&&buffer[1]==0&&buffer[2]==0&&buffer[3]==0&&buffer[4]==1);
  assert(cell_calls==4);
 }
 /* Invalid victim vectors do not invent directions; the selected target still has its arrow. */
 cell_calls=0;MEM32(0x1004+VICTIMS)=0xB003;
 assert(void_touch_combat_route(0x1000,0x2000,7,5,11,0,3,0x2100,buffer+1)==56&&buffer[4]==1);
 cell_calls=0;assert(!void_touch_combat_route(0x1000,0x2000,7,5,12,0,4,0,buffer+1));
 assert(!cell_calls);
 puts("PASS native forecast targets: multi-hit melee, deduplication, single ranged/hero direction, unchanged-cache cost, invalid vector bounds");
 return 0;
}
'''
                harness = packet + "\n" + constants + HARNESS[:HARNESS.index("int main(void)")].replace("/* PRODUCTION */", production) + main
                compile_probe("combat-targets-" + edition, harness, {}, extra_flags=["/wd4505"])

    def test_route_native_abi_geometry_cache_and_guards_all_editions(self):
        header = (ROOT / "android/host/touch.h").read_text()
        packet = re.search(r"enum \{ COMBAT_ROUTE_MAX_POINTS =[^;]+;", header)[0]
        for edition, values in LAYOUTS.items():
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                path, _ = adapt_host_source(ROOT / "android/host/touch_camera.c", tmp, edition)
                source = path.read_text()
                start = source.index("static struct { uint32_t screen, camera; float matrix[16]; int valid; } combat_projection;")
                end = source.index("\nstatic struct {\n    uint32_t camera, screen, phase;", start)
                production = function(source, "static uint32_t camera_method(") + source[start:end]
                constants = "".join(f"#define {name} {value}\n" for name, value in
                                    zip(("CAMERA", "ARENA", "SIZE", "CELL", "COMMAND", "COMMAND_VTABLE", "POSITION", "FLYING"), values))
                harness = packet + "\n" + constants + HARNESS.replace("/* PRODUCTION */", production)
                compile_probe("touch-combat-route-" + edition, harness, {})
                # Regression control: a valid-looking straight path drops native intermediate turns.
                old = "unsigned path_count = (end - begin) / 12;"
                self.assertEqual(harness.count(old), 1)
                with self.assertRaisesRegex(AssertionError, "Assertion failed"):
                    compile_probe("touch-combat-route-" + edition + "-straight",
                                  harness.replace(old, "unsigned path_count = 2;"), {})


if __name__ == "__main__":
    unittest.main()
