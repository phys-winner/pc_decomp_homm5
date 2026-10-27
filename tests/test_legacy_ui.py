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
                harness = '#define HOMM5_LEGACY_UI 1\n' + harness
                compile_probe('legacy-cutscene-' + edition, harness, {'cutscene_impl.h': text})

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
