"""Execute patched original 1.6/2.1 x87 input and visible-pixel conversions."""
import json
import re
from pathlib import Path
import sys
import unittest

from test_static_tls import compile_probe
from test_d3d_lifecycle import function
from test_cutscene_horplus import HARNESS as CUTSCENE_HARNESS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android
import build_windows
import port_patches
import prepare_windows_runtime


BOOK_MAIN = r'''
static double vertical(double fov, double width, double height) {
 return 2*atan(tan(fov*3.141592653589793/360)*height/width)*180/3.141592653589793;
}
int main(void) {
 for(unsigned i=0;i<sizeof machine;++i)((uint8_t *)&machine)[i]=(uint8_t)(i*17+3);
 void_regs before=machine;
 const float widths[]={1664,2400,1366,1024};
 const float heights[]={768,1080,768,768};
 for(unsigned i=0;i<4;++i){
  MEMF(0x4000)=widths[i];MEMF(0x4004)=heights[i];
  float fov=value(void_book_fov(0x4000,bits(50)));
  /* Hor+: the 4:3 view's vertical extent stays, the width grows with the screen. */
  assert(fabs(vertical(fov,widths[i],heights[i])-vertical(50,4,3))<1e-3);
  assert(fov>=50-1e-4&&memcmp(&before,&machine,sizeof before)==0);
 }
 MEMF(0x4000)=1664;MEMF(0x4004)=768;
 assert(value(void_book_fov(0x4000,bits(50)))>74.2f&&value(void_book_fov(0x4000,bits(50)))<74.4f);
 /* Taller than 4:3: ToE's other branch, tan(half)*ratio*4/3. */
 MEMF(0x4000)=1024;MEMF(0x4004)=1280;
 double tall=2*atan(tan(50*3.141592653589793/360)*1.25*1.3333334)*180/3.141592653589793;
 assert(fabs(value(void_book_fov(0x4000,bits(50)))-tall)<1e-3);
 MEMF(0x4000)=0;assert(fabs(value(void_book_fov(0x4000,bits(50)))-50)<1e-4);
 MEMF(0x4000)=1664;MEMF(0x4004)=0;assert(fabs(value(void_book_fov(0x4000,bits(50)))-50)<1e-4);
 MEMF(0x4004)=NAN;assert(void_book_fov(0x4000,bits(50))==bits(50));
 MEMF(0x4004)=-768;assert(void_book_fov(0x4000,bits(50))==bits(50));
 MEMF(0x4004)=768;assert(void_book_fov(0x10,bits(50))==bits(50));
 assert(void_book_fov(0x4000,bits(NAN))==bits(NAN));
 /* Spell rects are 4:3 frame units: the pick point moves into the frame, the tooltip anchor back out. */
 MEMF(CANVAS)=1664;MEMF(CANVAS+4)=768;
 MEMF(0x5000)=657;MEMF(0x5004)=405;
 uint32_t p=void_book_point(0x5000);
 assert(p!=0x5000&&fabs(MEMF(p)-337)<1e-4&&fabs(MEMF(p+4)-405)<1e-4&&MEMF(0x5000)==657);
 MEM32(0x6000)=346;MEM32(0x6004)=405;MEM32(0x6008)=51;MEM32(0x600C)=47;MEM32(0x6010)=0;
 void_book_anchor(0x6000);
 assert(MEM32(0x6000)==666&&MEM32(0x6004)==405&&MEM32(0x6008)==51&&MEM32(0x600C)==47&&MEM32(0x6010)==0);
 MEMF(CANVAS)=2400;MEMF(CANVAS+4)=1080;
 MEMF(0x5000)=480+1.40625f*300;MEMF(0x5004)=1.40625f*200;p=void_book_point(0x5000);
 assert(fabs(MEMF(p)-300)<1e-3&&fabs(MEMF(p+4)-200)<1e-3);
 MEM32(0x6000)=300;MEM32(0x6004)=200;MEM32(0x6008)=40;MEM32(0x600C)=(uint32_t)-8;void_book_anchor(0x6000);
 assert(MEM32(0x6000)==902&&MEM32(0x6004)==281&&MEM32(0x6008)==56&&MEM32(0x600C)==(uint32_t)-11);
 /* Taller than 4:3: the frame spans the width and is centred vertically. */
 MEMF(CANVAS)=1024;MEMF(CANVAS+4)=1280;
 MEMF(0x5000)=100;MEMF(0x5004)=500;p=void_book_point(0x5000);
 assert(fabs(MEMF(p)-100)<1e-4&&fabs(MEMF(p+4)-244)<1e-4);
 MEMF(CANVAS)=0;assert(void_book_point(0x5000)==0x5000);
 MEMF(CANVAS)=NAN;assert(void_book_point(0x5000)==0x5000);
 MEMF(CANVAS)=1664;MEMF(CANVAS+4)=-768;assert(void_book_point(0x5000)==0x5000);
 MEMF(CANVAS+4)=768;assert(void_book_point(0x10)==0x10);
 MEM32(0x6000)=346;MEMF(CANVAS)=0;void_book_anchor(0x6000);assert(MEM32(0x6000)==346);
 MEMF(CANVAS)=1664;void_book_anchor(0x10);
 assert(memcmp(&before,&machine,sizeof before)==0);
 puts("PASS legacy spellbook Hor+: 4:3 vertical extent kept, taller branch, spell rect point/anchor frame mapping, guards");
}
'''

# cutscene.c's legacy block allocates one guest scratch point and writes tooltip anchors.
LEGACY_STUBS = r'''
static uint32_t galloc_next=0x00800000;
static uint32_t void_galloc(uint32_t n) { uint32_t a=galloc_next; galloc_next+=(n+15)&~15u; return a; }
static int void_vm_writable(uint32_t a,uint32_t n) { return void_vm_readable(a,n); }
'''


def generated_body(edition, address):
    directory = ROOT / 'generated' / edition / 'game-x86'
    report = json.loads((directory / 'report.json').read_text())
    entries = [int(value, 0) for value in report['dispatch_entries']]
    path = directory / report['sources'][entries.index(address) // 100]
    text = build_android.round_x87_precision(build_android.guard_fpu_memory(path.read_bytes())).decode()
    declaration = f'void sub_{address:08X}(void) {{'
    start = text.index(declaration)
    end = text.index('\n}', start) + 2
    return text[start:end] + '\n'


class LegacyUiTest(unittest.TestCase):
    def test_real_original_frame_markers_reach_register_protected_pump(self):
        from test_render_frame_boundary import boundary_fixture, FRAME_BODY
        for edition in ('vanilla', 'hof'):
            with self.subTest(edition=edition):
                contract = port_patches.load_contract(edition)
                owner = contract['addresses']['00A3FB70']
                frame = generated_body(edition, int(owner, 16)).encode()
                adapted = port_patches.adapt_generated_source(frame, 'game', edition).decode()
                marker = next(line for line in adapted.splitlines() if 'g_cur_func = 0x' + owner in line)
                self.assertEqual(adapted.count('g_cur_func = '), 2)
                fixture, headers = boundary_fixture()
                native, _ = port_patches.adapt_host_source(ROOT / 'android/host/d3d9_device.c',
                                                         ROOT / 'build/tests' / ('legacy-frame-' + edition), edition)
                headers['begin_scene.h'] = function(native.read_text(), 'COM_METHOD(dev, BeginScene,')
                headers['frame_boundary.h'] = (FRAME_BODY % (marker + '\n')).replace('00A3FB70', owner)
                fixture = fixture.replace('00A3FB70', owner).replace('0xA3FB70', '0x' + owner)
                compile_probe('legacy-frame-' + edition, fixture, headers,
                              extra_flags=('/DRECOMP_GENERATED_CODE', '/DRECOMP_LOCAL_REGS'))

    def test_actual_legacy_cutscene_adapter_for_both_camera_layouts(self):
        for edition in ('vanilla', 'hof'):
            with self.subTest(edition=edition):
                out = ROOT / 'build/tests' / ('legacy-cutscene-' + edition)
                source, _ = port_patches.adapt_host_source(ROOT / 'android/host/cutscene.c', out, edition)
                text = source.read_text().replace('#include "host.h"', '')
                harness = CUTSCENE_HARNESS
                harness = harness.replace(function(harness, 'static uint32_t void_call_guest_this('), '')
                harness = harness.replace('adjustments==9', 'adjustments==0')
                harness = harness.replace('MEM32(0x218C)', 'MEM32(' + ('0x2184' if edition == 'vanilla' else '0x2180') + ')')
                addresses = port_patches.load_contract(edition)['addresses']
                harness = re.sub(r'0x([0-9A-Fa-f]{8})(?![0-9A-Fa-f])',
                                 lambda match: '0x' + addresses.get(match[1].upper(), match[1]), harness)
                # The fixture's unpadded global is also a real engine address.
                harness = harness.replace('0xFE719C', '0x' + addresses['00FE719C'])
                harness = harness.replace('#include "cutscene_impl.h"', LEGACY_STUBS + '#include "cutscene_impl.h"')
                harness = '#define HOMM5_LEGACY_UI 1\n' + harness
                compile_probe('legacy-cutscene-' + edition, harness, {'cutscene_impl.h': text})

    def test_owned_dialog_runs_through_exact_original_projection_seam(self):
        import pefile
        from test_combat_projection import PROBE
        core = (ROOT / 'android/host/core.c').read_text()
        state = core[core.index('VOID_HIDDEN uint32_t g_eax'):core.index('#define VOID_ENTER_RING')]
        host = (ROOT / 'android/host/host.h').read_text()
        registers = host[host.index('typedef struct void_regs {'):host.index('} void_regs;') + len('} void_regs;')]
        registers += '\nstatic recomp_ehframe_t *g_eh_frames;\nstatic uint32_t g_eh_obj,g_eh_info;\n'
        registers += function(core, 'void void_regs_save(') + function(core, 'void void_regs_load(')
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        compiler, _, _ = build_windows.compiler_environment()
        originals = {
            'vanilla': ('00760E50', '00760E72', '004ABC20', '004ABAC0', '00E1C644'),
            'hof': ('0075BAE0', '0075BB02', '009F3C00', '009F3AA0', '00DF14B0'),
        }
        for edition, (camera, load, perspective, context, dialog) in originals.items():
            with self.subTest(edition=edition):
                original = generated_body(edition, int(camera, 16))
                old = f'    ecx = MEM32(esi + 0x80); /* 0x{load}: mov ecx, dword ptr [esi + 0x80] */'
                self.assertEqual(original.count(old), 1)
                adapted = port_patches.adapt_generated_source(original.encode(), 'game', edition).decode()
                self.assertNotIn(old, adapted)
                self.assertEqual(adapted.count('ecx = void_cutscene_fov(esi, MEM32(esp + 0x5C), MEM32(esi + 0x80), esp)'), 1)
                native = (original.replace('void sub_' + camera, 'static void original_projection', 1) +
                          adapted.replace('void sub_' + camera, 'static void sub_' + camera, 1) +
                          generated_body(edition, int(perspective, 16)).replace('void sub_', 'static void sub_') +
                          generated_body(edition, int(context, 16)).replace('void sub_', 'static void sub_'))
                probe = PROBE[:PROBE.index('static int void_vm_readable(')]
                begin = probe.index('typedef struct { unsigned unused; } void_regs;')
                end = probe.index('static float observed_rod;', begin)
                probe = probe[:begin] + registers + '\nstatic float observed_fov;\n' + probe[end:]
                probe = probe.replace('if(target==0xCF7D90){sub_00CF7D90();return;}',
                    'if(target==0xCF7D90){observed_fov=MEMF(g_esp+8);sub_00CF7D90();return;}')
                # Actual renderer perspective code is executed; only view/context consumers are stubs.
                callbacks = r'''
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static void dummy(void){}
static void_fn void_dispatch_find(uint32_t p){(void)p;return dummy;}
static uint32_t void_call_guest(uint32_t target,int n,const uint32_t *args,int pops){
 assert(g_esp==0x70000-0x54&&MEM32(g_esp+0x5C)==0x66000);
 /* Every field changed by these callbacks must be restored before the native caller resumes. */
 g_eax=g_ecx=g_edx=g_ebx=g_esi=g_edi=g_ebp=0xCCCCCCCC;
 g_flag_k=FK_CMP;g_flag_a=0xBAD;g_flag_b=0xACE;g_flag_cf=1;
 g_fp_top=3;g_st[0]=123.75;g_st_i64[0]=0x12345678;memset(g_xmm,0xCD,sizeof g_xmm);
 if(target==0x8385A0){assert(!n&&!args&&pops);return 0x18000;}
 assert(target==0xD119FC&&n==5&&!pops&&args[0]==0x18104&&args[2]==0xF272C0&&args[3]==0xF323A8);
 return 0x10000;
}
static void void_lift_trap(uint32_t p,const char *why){(void)p;fprintf(stderr,"%s",why);abort();}
/* ACTUAL_HELPER */
static void capture(float w,float h,float fov,int kind,int patched,float matrix[16],void_regs *result){
 MEM32(0xFE719C)=0x18000;MEM32(0x18004)=0x19000;MEM32(0x19004)=0x100;
 MEM32(0x10000)=kind<2?0xE3DD4C:kind==2?0xE1DA84:0xE3D1EC;
 MEM32(0x1009C)=kind==1?0x20004:0x20000;
 MEM32(0x20000)=0xE44224;MEM32(0xE44224+0x2C)=0x7CD040;
 MEMF(0x2005C)=MEMF(0x20060)=0;MEMF(0x20070)=42;
 MEMF(0x20080)=fov;MEMF(0x20084)=1;MEMF(0x20088)=1000;
 MEMF(0x66000)=w;MEMF(0x66004)=h;
 g_esp=0x70000;g_ecx=0x20000;MEM32(g_esp)=RECOMP_RETADDR;
 MEM32(g_esp+4)=0x30000;MEM32(g_esp+8)=0x66000;
 g_eax=g_edx=0;g_flag_k=FK_NONE;g_flag_a=g_flag_b=g_flag_cf=0;
 g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;
 fp_set_cw(0x007F);g_fp_sp=128;g_fp_top=0;
 unsigned char camera[0x200];memcpy(camera,GPTR(0x20000),sizeof camera);
 if(patched)sub_007CD0C0();else original_projection();
 assert(g_esp==0x7000C&&g_ebx==0x11223344&&g_esi==0x22334455&&g_edi==0x33445566&&g_ebp==0x44556677);
 assert(g_fp_top==0&&g_fp_sp==128&&observed_rod==42);
 assert(!memcmp(camera,GPTR(0x20000),sizeof camera));
 memcpy(matrix,GPTR(0x30000),64);memset(result,0,sizeof *result);void_regs_save(result);
}
int main(void){
 /* CONSTANTS */
 const float fovs[]={35,54.43f,90},views[][2]={{1024,768},{1920,1080},{2400,1080}};
 for(unsigned f=0;f<3;++f){
  float pc[16];void_regs unused;capture(1024,768,fovs[f],0,0,pc,&unused);
  for(unsigned v=0;v<3;++v)for(int kind=0;kind<4;++kind){
   float raw[16],actual[16];void_regs before,after;
   float w=views[v][0],h=views[v][1];
   capture(w,h,fovs[f],kind,0,raw,&before);assert(observed_fov==fovs[f]);
   capture(w,h,fovs[f],kind,1,actual,&after);
   assert(!memcmp(&before,&after,offsetof(void_regs,st)));
   if(kind||v==0){assert(observed_fov==fovs[f]&&!memcmp(raw,actual,64));continue;}
   /* The original PC4:3 projection itself is the oracle for vertical framing. */
   assert(observed_fov>fovs[f]&&fabsf(actual[5]-pc[5])<.00001f);
   assert(fabsf(actual[0]*w/h-pc[0]*(4.f/3.f))<.00001f);
   assert(fabsf(actual[5]-raw[5])>.1f);
   for(unsigned i=1;i<16;++i)if(i!=5)assert(fabsf(actual[i]-raw[i])<.00001f);
   /* Independently executed original PE golden, FOV35 at2400x1080. */
   if(f==0&&v==2){
    assert(fabsf(observed_fov-55.443671f)<.0001f);
    assert(fabs(2*atan(1/actual[5])*180/3.141592653589793-26.609127)<.0001);
   }
  }
 }
 puts("PASS actual legacy Dialog projection: exact original load/viewport seam, original renderer PC4:3 oracle, owned-only Hor+, raw FOV/camera bytes, poisoned callbacks, full RET8/callee state");
}
'''
                addresses = dict(port_patches.load_contract(edition)['addresses'])
                self.assertEqual(addresses['00E3DD4C'], dialog)
                addresses.update(zip(('007CD0C0', '00CF7D90', '00CF7C30'), (camera, perspective, context)))
                addresses.update(zip(('00CF60A0', '00CF7AC0', '00CF7000'),
                    ('004AA110', '004AB950', '004AAE60') if edition == 'vanilla' else ('009F20F0', '009F3930', '009F2E40')))
                def mapped(text):
                    return re.sub(r'(0x|sub_)([0-9A-Fa-f]+)',
                        lambda m: m[1] + addresses.get(f'{int(m[2],16):08X}', m[2]), text)
                source, _ = port_patches.adapt_host_source(ROOT / 'android/host/cutscene.c',
                    ROOT / 'build/tests' / ('dialog-projection-' + edition), edition)
                helper = source.read_text()
                helper = function(helper, 'static uint32_t cutscene_read32(') + function(helper, 'uint32_t void_cutscene_fov(')
                # Map only fixture addresses; actual adapted helper/lifted bodies keep their original VAs.
                bridge, capture = callbacks.split('static void capture(', 1)
                fixture = mapped(probe).replace('/* NATIVE */',
                    mapped(bridge).replace('/* ACTUAL_HELPER */', helper) + native)
                fixture += mapped('static void capture(' + capture)
                image = pefile.PE(str(ROOT / 'generated' / edition / 'input/H5_Game.exe'))
                constants = []
                for address in sorted(set(int(n,16) for n in re.findall(r'ADDR\(0x([0-9A-F]+)\)', native))):
                    data = image.get_data(address-image.OPTIONAL_HEADER.ImageBase,8)
                    self.assertEqual(len(data),8)
                    constants.append(f'memcpy(GPTR(0x{address:X}),(unsigned char[]){{' + ','.join(map(str,data)) + '},8);')
                image.close()
                fixture = fixture.replace('/* STATE */', state).replace('/* CONSTANTS */', '\n'.join(constants))
                compile_probe('dialog-projection-' + edition, fixture, {'runtime.h': runtime},
                    extra_flags=['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label', '/clang:-Wno-unused-function'],
                    compiler_override=compiler)

    def test_legacy_spellbook_camera_gets_toe_horplus(self):
        # (camera, viewport getter, projection, FOV push) of the 1.6/2.1 spellbook camera; ToE's is 0x006832D0.
        cameras = {'vanilla': (0x0063CFD0, '00410B60', '004ABC20', '0x0063CFF4'),
                   'hof': (0x00641F10, '00B042D0', '009F3C00', '0x00641F34')}
        # (picker, its MB_CastSpell rect test, tooltip anchor function, anchor store) of each edition.
        spells = {'vanilla': (0x0063D130, '0x0063D2F5', '00641340', 0x0063D930, '0x0063D9AB'),
                  'hof': (0x00642070, '0x00642235', '006462D0', 0x00642870, '0x006428EB')}
        for edition, (camera, getter, projection, push) in cameras.items():
            with self.subTest(edition=edition):
                picker, test, rect, anchor, store = spells[edition]
                lines = port_patches.adapt_generated_source(generated_body(edition, picker).encode(), 'game',
                                                            edition).decode().splitlines()
                hook = next(i for i, line in enumerate(lines) if 'void_book_point(' in line)
                self.assertIn(test + ': mov ecx, dword ptr [esp + 0x6fc]', lines[hook])
                self.assertEqual(sum('void_book_point(' in line for line in lines), 1)
                self.assertTrue(lines[hook + 2].lstrip().startswith('PUSH32(esp, ecx);'))
                self.assertIn(f'RECOMP_CALL(sub_{rect});', lines[hook + 4])
                # The rect test reads the 4:3 slot rect at descriptor +0x14 against [point].
                checker = generated_body(edition, int(rect, 16))
                self.assertIn('fild dword ptr [ecx]', checker)
                self.assertIn('fcomp dword ptr [edx]', checker)
                lines = port_patches.adapt_generated_source(generated_body(edition, anchor).encode(), 'game',
                                                            edition).decode().splitlines()
                hook = next(i for i, line in enumerate(lines) if 'void_book_anchor(' in line)
                self.assertIn(store + ': mov dword ptr [eax + 0x10], 0', lines[hook - 1])
                self.assertEqual(sum('void_book_anchor(eax)' in line for line in lines), 1)
                body = generated_body(edition, camera)
                original = f'    PUSH32(esp, 0x42480000u); /* {push}: push 0x42480000 */'
                self.assertEqual(body.count(original), 1)
                adapted = port_patches.adapt_generated_source(body.encode(), 'game', edition).decode()
                self.assertNotIn(original, adapted)
                self.assertEqual(adapted.count('void_book_fov(esp + 0x24, 0x42480000u)'), 1)
                # The getter fills [esp+0x18]; three pushes later that is esp+0x24, and the projection
                # receives the same struct as esp+0x28 after the FOV push.
                lines = adapted.splitlines()
                hook = next(i for i, line in enumerate(lines) if 'void_book_fov(' in line)
                before = '\n'.join(lines[:hook])
                self.assertIn(f'ecx = esp + 0x18;', before)
                self.assertIn(f'RECOMP_CALL(sub_{getter});', before)
                self.assertEqual(sum(line.lstrip().startswith('PUSH32(esp,') for line in
                                     lines[next(i for i, line in enumerate(lines) if f'sub_{getter}' in line):hook]), 3)
                self.assertTrue(lines[hook + 1].lstrip().startswith('ecx = esp + 0x28;'))
                self.assertIn(f'RECOMP_CALL(sub_{projection});', '\n'.join(lines[hook:hook + 8]))
                out = ROOT / 'build/tests' / ('legacy-book-' + edition)
                source, _ = port_patches.adapt_host_source(ROOT / 'android/host/cutscene.c', out, edition)
                text = source.read_text().replace('#include "host.h"', '')
                harness = CUTSCENE_HARNESS
                harness = harness.replace(function(harness, 'static uint32_t void_call_guest_this('), '')
                harness = harness.replace('#include "cutscene_impl.h"', LEGACY_STUBS + '#include "cutscene_impl.h"')
                harness = harness[:harness.index('int main(void) {')] + BOOK_MAIN
                canvas = '#define CANVAS 0x' + port_patches.load_contract(edition)['addresses']['00F74BE0'] + 'u\n'
                self.assertIn('0x' + port_patches.load_contract(edition)['addresses']['00F74BE0'] + 'u', text)
                compile_probe('legacy-book-' + edition, '#define HOMM5_LEGACY_UI 1\n' + canvas + harness,
                              {'cutscene_impl.h': text})

    def test_actual_native_root_layout_and_resize(self):
        for edition in ('vanilla', 'hof'):
            with self.subTest(edition=edition):
                out = ROOT / 'build/tests' / ('legacy-root-' + edition)
                source, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_scale.c', out, edition)
                text = source.read_text()
                helpers = '\n'.join(function(text, signature) for signature in (
                    'static uint32_t scale_read32(', 'static uint32_t scale_virtual_base(',
                    'static uint32_t scale_root(', 'static uint32_t scale_screen_root(',
                    'static int scale_is_root(', 'void void_touch_legacy_root_rect(',
                    'void void_touch_legacy_relayout(', 'void void_touch_legacy_resize('))
                contract = port_patches.load_contract(edition)
                addresses = contract['addresses']
                harness = (ROOT / 'tests/fixtures/legacy_ui_root_probe.c').read_text().replace('/* ACTUAL */', helpers)
                for name, address in {'GET_SCREEN': '008385A0', 'DYNAMIC_CAST': '00D119FC',
                        'LAYOUT': '00487990', 'INVALIDATE': '00A504B0', 'CHILDREN': '00488220',
                        'NEXT_SCREEN': '008384D0', 'CANVAS_X': '00F74BE0', 'CANVAS_Y': '00F74BE4',
                        'PHYSICAL_X': '00F74BF0', 'PHYSICAL_Y': '00F74BF4'}.items():
                    harness = harness.replace(name, '0x' + addresses[address])
                compile_probe('legacy-root-' + edition, harness, {})

    def test_actual_generated_coordinate_roundtrip_and_original_negative_control(self):
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        header = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        cc, _, _ = build_windows.compiler_environment()
        for edition in ('vanilla', 'hof'):
            functions = [(0x410BA0, 0x410C20), (0x410BE0, 0x410C60)] if edition == 'vanilla' else [(0xB04310, 0xB04390), (0xB04350, 0xB043D0)]
            for axis, (forward, inverse) in enumerate(functions):
                with self.subTest(edition=edition, axis=axis):
                    bodies = []
                    for address, name in ((forward, 'forward'), (inverse, 'inverse')):
                        body = generated_body(edition, address).encode()
                        if name == 'inverse':
                            bodies.append(body.decode().replace(f'sub_{address:08X}', 'original_inverse'))
                        body = port_patches.adapt_generated_source(body, 'game', edition)
                        bodies.append(body.decode().replace(f'sub_{address:08X}', name))
                    text = (ROOT / 'tests/fixtures/legacy_ui_probe.c').read_text()
                    if axis:
                        text = text.replace('float base=aspect>(double)1.3333334f?(float)floor(768*aspect+(double).99f):1024;',
                                            'float base=aspect>(double)1.3333334f?768:(float)floor(1024/aspect+(double).99f);')
                        text = text.replace('physical=(float)surfaces[s][0]', 'physical=(float)surfaces[s][1]')
                        text = text.replace('canvas!=1024', 'canvas!=768')
                    text = text.replace('/* STATE */', state).replace('/* ACTUAL */', '\n'.join(bodies))
                    values = [0xF07D4C, 0xF07D50, 0xF07D54, 0xF07D58, 0xDE4F04, 0xDE4F08, 0xDE4EFC, 0xDE4F00] if edition == 'vanilla' else [0xF24178, 0xF2417C, 0xF24180, 0xF24184, 0xE2B33C, 0xE2B340, 0xDC6804, 0xDC6800]
                    if axis:
                        # The same oracle runs the vertical originals, with each
                        # logical X/Y fixture address exchanged before execution.
                        values = [values[i] for i in (1, 0, 3, 2, 4, 5, 6, 7)]
                    for key, value in zip(('CANVAS_X', 'CANVAS_Y', 'PHYSICAL_X', 'PHYSICAL_Y', 'CONST_X', 'CONST_Y', 'RECIP_X', 'RECIP_Y'), values):
                        text = text.replace(key, f'0x{value:X}')
                    compile_probe('legacy-ui-' + edition + '-' + str(axis), text, {'runtime.h': header},
                                  extra_flags=['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label', '/clang:-Wno-unused-function'], compiler_override=cc)


if __name__ == '__main__':
    unittest.main()
