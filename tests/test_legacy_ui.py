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
                    'static uint32_t scale_screen_root(', 'static int scale_is_root(', 'void void_touch_legacy_root_rect(',
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
