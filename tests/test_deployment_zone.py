"""Execute actual full-zone helpers and their shared projection integration."""
import re
import sys
import tempfile
import unittest

from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(ROOT / 'tools'))
from port_patches import adapt_host_source, load_contract, source_digest

# Original PE RTTI and independently lifted cell/dimension/layout instructions.
CANONICAL = ('00E1DA84', '00E44224', '007CD0C0', '00F74BE4', '00E202DC', '00E17BCC', '00E79D3C')
PROVEN = {
    'toe': (CANONICAL, (0x488, 0x2A0, 0xA4, 0x2E0), (0x44, 0x6C), ('00AF1450', '00AF14E0')),
    'vanilla': (('00DFB694', '00E20D2C', '00760E50', '00F07D50', '00DFE240', '00DE74CC', '00E2B9C4'),
                (0x45C, 0x280, 0x9C, 0x2D8), (0x40, 0x78), ('008263B0', '008247E0')),
    'hof': (('00DD2B10', '00DF5C94', '0075BAE0', '00F2417C', '00DD52A8', '00E18BAC', '00E38BBC'),
            (0x474, 0x294, 0x9C, 0x2F0), (0x44, 0x6C), ('00BC0820', '00BC08B0')),
}


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t memory[0x1100000],snapshot[0x1100000];
#define GPTR(p) (memory+(uint32_t)(p))
#define MEM32(p) (*(uint32_t *)GPTR(p))
#define MEMF(p) (*(float *)GPTR(p))
typedef struct {uint32_t gp[16],flags[8];double fp[8];uint64_t xmm[16];} void_regs;
static void_regs registers;
#define g_ecx registers.gp[1]
#define g_esp registers.gp[4]
#define ARG(i) MEM32(g_esp+4u+4u*(i))
typedef void (*void_fn)(void);
#define VLOG(...) ((void)0)
static uint32_t camera_scratch;
static unsigned dimensions_calls,position_calls,allocation_calls;
static int fail_allocation,bad_dimensions,bad_return,nonfinite,terrain,bad_context_depth;
static uint32_t unreadable_address;
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory&&
    !(unreadable_address&&p<=unreadable_address&&(uint64_t)p+n>unreadable_address);}
static int void_vm_writable(uint32_t p,uint32_t n){return void_vm_readable(p,n);}
static void void_regs_save(void_regs *out){memcpy(out,&registers,sizeof *out);}
static void void_regs_load(const void_regs *in){memcpy(&registers,in,sizeof *in);}
static uint32_t camera_method(uint32_t object,uint32_t offset){
    assert(object==0x40000);assert(offset==0x44||offset==0x6C);
    return MEM32(MEM32(object)+offset);
}
static uint32_t void_galloc(uint32_t n){assert(n==0x800);++allocation_calls;return fail_allocation?0:0x50000;}
static uint32_t void_call_guest_this(uint32_t method,uint32_t object,int nargs,const uint32_t *args){
    assert(object==0x40000&&nargs==2);
    memset(&registers,0xCC,sizeof registers); /* Volatile GP, flags, FP and vector state all clobbered. */
    if(method==0xAF1450){++dimensions_calls;MEM32(args[0])=bad_dimensions?0:16;MEM32(args[1])=12;return 0;}
    assert(method==0xAF14E0);++position_calls;
    int32_t x=(int32_t)MEM32(args[1]),y=(int32_t)MEM32(args[1]+4);
    float point[3]={(float)(2*x-3),(float)(2*y+1-24),0};
    if(terrain&&x==3&&y==2)point[2]=-20;
    if(nonfinite)point[2]=NAN;
    memcpy(GPTR(args[0]),point,sizeof point);return bad_return?0:args[0];
}
static float fixture_projection_matrix[16];
static void fixture_original_projection(void){
    uint32_t output=ARG(0);float m[16];memcpy(m,fixture_projection_matrix,sizeof m);
    for(unsigned i=0;i<4;i++)m[4+i]-=MEMF(g_ecx+0x60)*m[12+i];
    const float perspective[16]={1,0,0,0,0,2,0,0,0,0,1,-1,0,0,1,0};
    memcpy(GPTR(output),perspective,sizeof perspective);
    memcpy(GPTR(output+0x100),m,sizeof m);MEM32(output+0x400)=(uint32_t)(2+bad_context_depth);
    g_esp+=12;g_ecx=0xDEADBEEF; /* Original thiscall RET8; volatile ECX may change. */
}
static void_fn void_dispatch_find(uint32_t method){return method==0x7CD0C0?fixture_original_projection:NULL;}
static void void_dispatch_add(uint32_t method,void_fn function){assert(method==0x7CD0C0&&function);}
#include "actual.h"
static const uint32_t screen=0x10000,info=0x20000,army=0x30000,combat=0x40000;
static void setup(void){
    memset(memory,0,sizeof memory);memset(&registers,0x57,sizeof registers);
    camera_scratch=0;deployment_zone_reset();dimensions_calls=position_calls=allocation_calls=0;
    fail_allocation=bad_dimensions=bad_return=nonfinite=terrain=bad_context_depth=0;unreadable_address=0;
    MEM32(screen)=0xE1DA84;MEM32(screen+0x2E0)=0x1000;MEM32(screen+0x488)=info;MEM32(screen+0x2A0)=combat;
    MEM32(info)=0xE202DC;MEM32(info+0x24)=army;MEM32(info+104)=combat;
    MEM32(info+136)=2;MEM32(info+140)=1;MEM32(info+144)=3;MEM32(info+148)=10;
    MEM32(army)=0xE17BCC;MEM32(army+8)=combat;MEM32(combat)=0xE79D3C;
    MEM32(0xE79D3C+0x44)=0xAF1450;MEM32(0xE79D3C+0x6C)=0xAF14E0;
}
static void matrix(float out[16]){memset(out,0,16*sizeof *out);out[0]=.05f;out[5]=.02f;out[6]=.03f;out[7]=-.3f;out[10]=1;out[15]=1;}
static int bounds(const float m[16],float center,float *top,float *bottom){
    void_regs before=registers;memcpy(snapshot,memory,sizeof memory);
    int result=deployment_zone_bounds(screen,m,1365.6f,614.4f,center,top,bottom);
    assert(!memcmp(&registers,&before,sizeof before));
    /* Original queries write the designated scratch only; no scene/HUD/camera writes. */
    memcpy(snapshot+0x50780,memory+0x50780,0x28);
    assert(!memcmp(memory,snapshot,sizeof memory));return result;
}
static void capture_projection(uint32_t camera,int valid){
    g_ecx=camera;g_esp=0x70000;MEM32(g_esp)=0x12345678;
    MEM32(g_esp+4)=0x80000;MEM32(g_esp+8)=0x90000;
    MEM32(g_esp+16)=0xDEADBEEF;MEM32(g_esp+20)=0xDEADBEEF;
    MEMF(0x90000)=1365.6f;MEMF(0x90004)=614.4f;
    uint8_t before[0x98];memcpy(before,GPTR(camera),sizeof before);
    camera_projection();
    assert(g_esp==0x7000C&&!memcmp(before,GPTR(camera),sizeof before));
    assert(deployment_projection.valid==(unsigned)valid);
    if(valid){
        assert(deployment_projection.camera==camera&&deployment_projection.screen==screen);
        assert(!memcmp(deployment_projection.matrix,GPTR(0x80100),64));
        assert(memcmp(deployment_projection.matrix,GPTR(0x80000),64));
    }
}
static void integration_probe(void){
    setup();memset(&framing,0,sizeof framing);memset(&deployment_projection,0,sizeof deployment_projection);
    original_projection=NULL;const uint32_t camera=0x60000;
    MEM32(screen+0xA4)=camera;MEM32(camera)=0xE44224;
    MEMF(camera+0x70)=42;MEMF(camera+0x74)=-.785398f;MEMF(camera+0x78)=-1.570796f;
    MEMF(camera+0x80)=54;MEMF(camera+0x60)=0;MEMF(0xF74BE4)=614.4f;
    matrix(fixture_projection_matrix);
    void_touch_combat_frame(screen,1365.6f,614.4f,437,403,427);
    assert(framing.phase==1&&framing.centre==0);
    capture_projection(camera,1);
    assert(deployment_projection.centre==0);
    /* Existing occupied-label calibration may already consider itself fitted. */
    framing.fitted=1;
    void_touch_combat_frame(screen,1365.6f,614.4f,437,403,427);
    float desired=2*(437-614.4f*.015f-534.62016f)/614.4f;
    assert(framing.fitted&&fabsf(framing.centre-desired)<.00001f&&framing.centre<0);
    assert(position_calls==20);
    for(unsigned i=0;i<12;i++){
        capture_projection(camera,1);
        assert(fabsf(deployment_projection.centre-desired)<.00001f);
        void_touch_combat_frame(screen,1365.6f,614.4f,437,403,427);
        assert(fabsf(framing.centre-desired)<.00001f&&position_calls==20);
    }
    bad_context_depth=-2;deployment_projection.valid=1;capture_projection(camera,0);
    bad_context_depth=1;deployment_projection.valid=1;capture_projection(camera,0);
    bad_context_depth=0;unreadable_address=0x80400;deployment_projection.valid=1;capture_projection(camera,0);
    unreadable_address=0;capture_projection(camera,1);
    MEM32(screen+0x2E0)=0x80;void_touch_combat_frame(screen,1365.6f,614.4f,437,403,427);
    assert(!deployment_zone.valid&&!deployment_projection.valid);
    deployment_zone.valid=deployment_projection.valid=1;
    void_touch_combat_frame(0,0,0,0,0,0);
    assert(!deployment_zone.valid&&!deployment_projection.valid&&!framing.camera);
    puts("PASS actual camera integration: output captured across RET8/volatile ECX, unchanged camera fields, full empty cells override already-fitting labels, no feedback or repeated world calls, attack/exit invalidation");
}
int main(void){
    float m[16],shifted[16],top=0,bottom=0;setup();matrix(m);
    assert(bounds(m,0,&top,&bottom));
    assert(fabsf(top-410.63424f)<.001f&&fabsf(bottom-534.62016f)<.001f);
    assert(dimensions_calls==1&&position_calls==20&&allocation_calls==1&&deployment_zone.count==80);
    /* Original 55BB60 quad bits: radius3F8B851F, localZ3D4CCCCD. */
    assert(fabsf(deployment_zone.points[0][0]+.09f)<.00001f);
    assert(fabsf(deployment_zone.points[0][1]+22.09f)<.00001f);
    assert(fabsf(deployment_zone.points[0][2]-.05f)<.00001f);
    /* A top-row occupied label can fit while the lower empty row is hidden. */
    float hud=437,target=hud-614.4f*.015f,label_bottom=427;
    assert(label_bottom<target&&bottom>hud);
    float desired=2*(target-bottom)/614.4f;
    memcpy(shifted,m,sizeof m);for(unsigned i=0;i<4;i++)shifted[4+i]-=desired*m[12+i];
    float visible_top,visible_bottom;
    assert(bounds(shifted,0,&visible_top,&visible_bottom));assert(fabsf(visible_bottom-target)<.001f);
    assert(bounds(shifted,desired,&visible_top,&visible_bottom));
    assert(fabsf(visible_top-top)<.001f&&fabsf(visible_bottom-bottom)<.001f);
    assert(position_calls==20&&dimensions_calls==1); /* Camera-only changes reuse world points. */
    memcpy(shifted,m,sizeof m);shifted[4]=.04f;
    assert(bounds(shifted,0,&visible_top,&visible_bottom)&&fabsf(visible_top-top)>.1f);
    assert(position_calls==20);

    /* A center depression can exceed every boundary cell: all nine cells matter. */
    MEM32(info+144)=4;MEM32(info+148)=3;terrain=1;
    assert(bounds(m,0,&top,&bottom));assert(fabsf(bottom-706.65216f)<.001f);
    assert(position_calls==29&&deployment_zone.count==36);
    terrain=0;assert(bounds(m,0,&top,&bottom)&&fabsf(bottom-706.65216f)<.001f&&position_calls==29);
    deployment_zone_reset(); /* Same addresses/bounds, a different battlefield terrain. */
    assert(bounds(m,0,&top,&bottom)&&fabsf(bottom-534.62016f)<.001f&&position_calls==38);
    MEM32(screen+0x2E0)=0;top=123;bottom=456;assert(!bounds(m,0,&top,&bottom)&&top==123&&bottom==456);
    terrain=1;MEM32(screen+0x2E0)=0x1000;
    assert(bounds(m,0,&top,&bottom)&&fabsf(bottom-706.65216f)<.001f&&position_calls==47);

    setup();matrix(m);MEM32(info+136)=0;MEM32(info+140)=0;MEM32(info+144)=63;MEM32(info+148)=63;
    assert(!bounds(m,0,&top,&bottom)&&!position_calls&&!dimensions_calls);
    setup();matrix(m);bad_dimensions=1;assert(!bounds(m,0,&top,&bottom)&&dimensions_calls==1&&!position_calls);
    setup();matrix(m);bad_return=1;assert(!bounds(m,0,&top,&bottom)&&position_calls==1);
    setup();matrix(m);nonfinite=1;assert(!bounds(m,0,&top,&bottom)&&position_calls==1);
    setup();matrix(m);fail_allocation=1;assert(!bounds(m,0,&top,&bottom)&&!position_calls);
    setup();matrix(m);MEM32(info+104)=0;assert(!bounds(m,0,&top,&bottom)&&!position_calls&&!dimensions_calls);
    setup();matrix(m);MEM32(army)=0;assert(!bounds(m,0,&top,&bottom)&&!position_calls&&!dimensions_calls);
    setup();matrix(m);m[5]=NAN;top=123;bottom=456;assert(!bounds(m,0,&top,&bottom)&&top==123&&bottom==456);
    setup();matrix(m);m[15]=-1;top=123;bottom=456;assert(!bounds(m,0,&top,&bottom)&&top==123&&bottom==456);
    puts("PASS full empty deployment zone, original cell ABI, exact center undo, all-cell interior terrain, cache reuse/lifecycle reset, bounded input/failure fallback, unchanged scene and GP/flags/FP/vector state");
    integration_probe();
    return 0;
}
'''


class DeploymentZoneTests(unittest.TestCase):
    def fixture(self, edition):
        addresses, fields, slots, methods = PROVEN[edition]
        mappings = dict(zip(CANONICAL, addresses))
        mappings.update(zip(('00AF1450', '00AF14E0'), methods))
        contract = load_contract(edition)
        self.assertEqual(contract['sources']['android/host/touch_camera.c'],
                         source_digest(ROOT / 'android/host/touch_camera.c'))
        if edition != 'toe':
            self.assertTrue(set(CANONICAL) <= set(contract['reference_addresses']['android/host/touch_camera.c']))
            self.assertEqual({key: contract['addresses'][key] for key in CANONICAL}, dict(zip(CANONICAL, addresses)))
        with tempfile.TemporaryDirectory() as temporary:
            adapted, _ = adapt_host_source(ROOT / 'android/host/touch_camera.c', temporary, edition)
            source = adapted.read_text()
        begin = source.index("enum { DEPLOY_ZONE_AXIS_LIMIT")
        end = source.index("/* Two fingers moved up together", begin)
        source = source[begin:end]
        field_map = dict(zip((0x488, 0x2A0, 0xA4, 0x2E0), fields))
        harness = re.sub(r'(screen\s*\+\s*)0x([0-9A-Fa-f]+)',
                         lambda match: match[1] + hex(field_map.get(int(match[2], 16), int(match[2], 16))), HARNESS)
        harness = harness.replace('offset==0x44||offset==0x6C', 'offset==DIM_SLOT||offset==CELL_SLOT')
        harness = harness.replace('0xE79D3C+0x44', '0xE79D3C+DIM_SLOT').replace('0xE79D3C+0x6C', '0xE79D3C+CELL_SLOT')
        harness = re.sub(r'0x([0-9A-Fa-f]+)',
                         lambda match: '0x' + mappings.get(f'{int(match[1], 16):08X}', match[1]), harness)
        harness = f'#define DIM_SLOT {slots[0]}u\n#define CELL_SLOT {slots[1]}u\n' + harness
        return harness, source

    def test_toe_actual_zone_and_projection_integration(self):
        harness, source = self.fixture('toe')
        compile_probe('deployment_zone_toe', harness, {'actual.h': source}, extra_flags=('/O2',))

    def test_vanilla_actual_adapted_zone_and_projection_integration(self):
        harness, source = self.fixture('vanilla')
        compile_probe('deployment_zone_vanilla', harness, {'actual.h': source}, extra_flags=('/O2',))

    def test_hof_actual_adapted_zone_and_projection_integration(self):
        harness, source = self.fixture('hof')
        compile_probe('deployment_zone_hof', harness, {'actual.h': source}, extra_flags=('/O2',))

    def test_vanilla_original_method_slots_are_required(self):
        harness, source = self.fixture('vanilla')
        self.assertIn('camera_method(combat, 0x40)', source)
        self.assertIn('camera_method(combat, 0x78)', source)
        wrong = source.replace('camera_method(combat, 0x40)', 'camera_method(combat, 0x44)')
        wrong = wrong.replace('camera_method(combat, 0x78)', 'camera_method(combat, 0x6C)')
        with self.assertRaises(AssertionError):
            compile_probe('deployment_zone_vanilla_wrong_slots', harness, {'actual.h': wrong}, extra_flags=('/O2',))


if __name__ == "__main__":
    unittest.main()
