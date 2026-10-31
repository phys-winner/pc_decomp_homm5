"""Run the original town-name window layout with the actual migrated resources."""
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest

from test_d3d_lifecycle import function
from test_legacy_ui import generated_body
from test_legacy_widescreen import Resources
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_windows
from editions import game_directory
import port_ui
import prepare_windows_runtime

SPECS = {
    'vanilla': dict(LAYOUT=0xA77300, AXIS=0xA74370, INVALIDATE=0xA76410,
                    JUMP=0xA74430, HALF=0xDE3820, LOW=0xA74380, CENTER=0xA74391, HIGH=0xA743E6, MARGIN=0xA743FD),
    'hof': dict(LAYOUT=0xBE1CE0, AXIS=0xB95920, INVALIDATE=0xBE0E90,
                JUMP=0xB959E0, HALF=0xDBA7E8, LOW=0xB95930, CENTER=0xB95941, HIGH=0xB95996, MARGIN=0xB959AD),
}


class TownTitleLayoutTest(unittest.TestCase):
    def test_actual_native_layout_keeps_original_geometry_and_centers_the_title(self):
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        source = (ROOT / 'android/host/touch_scale.c').read_text()
        scale = function(source, 'static float scale_clamp(') + function(source, 'static float scale_anchor_shift(')
        compiler, _, _ = build_windows.compiler_environment()
        name = 'UI/TownScreen/BuildingDesc.(WindowStaticText).xdb'
        try:
            reference = game_directory('toe')
        except (FileNotFoundError, ValueError):
            self.skipTest('Original resource configuration unavailable')
        self.assertEqual(port_ui.legacy_widescreen(reference, reference, 'toe', {}), {})
        for edition, spec in SPECS.items():
            with self.subTest(edition=edition), ExitStack() as stack:
                game = game_directory(edition)
                if not game.is_dir() or not reference.is_dir():
                    self.skipTest('Original game resources unavailable')
                changes = port_ui.legacy_widescreen(game, reference, edition, {})
                original = Resources(stack, game, edition)
                patched = Resources(stack, game, edition, changes)
                self.assertIn(name, changes)
                before, after = original.row(name), patched.row(name)
                self.assertEqual(before[:6], [0, 0, 271, 58, 512, 51])
                self.assertEqual(after[:6], [1, 0, 15, 58, 512, 51])
                self.assertEqual(original.node(name).find('TextString').attrib,
                                 patched.node(name).find('TextString').attrib)
                bodies = []
                for key, label in (('LAYOUT', 'window_layout'), ('AXIS', 'axis_layout')):
                    address = spec[key]
                    bodies.append(generated_body(edition, address).replace(f'void sub_{address:08X}(', 'void ' + label + '('))
                defines = ''.join(f'#define {key} 0x{value:X}u\n' for key, value in spec.items())
                defines += '#define VISIBLE 0xDEAD1000u\n#define PLACEMENT 0xDEAD1004u\n'
                fixture = (ROOT / 'tests/fixtures/town_title_layout_probe.c').read_text()
                fixture = fixture.replace('/* STATE */', state).replace('/* SCALE */', scale)
                fixture = fixture.replace('/* ACTUAL */', '\n'.join(bodies))
                original_row = ','.join(str(float(value)) + 'f' for value in before)
                centered_row = ','.join(str(float(value)) + 'f' for value in after)
                fixture = fixture.replace('/* ORIGINAL */', original_row).replace('/* CENTERED */', centered_row)
                flags = ['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label', '/clang:-Wno-unused-function']
                compile_probe('town-title-layout-' + edition, defines + fixture, {'runtime.h': runtime},
                              extra_flags=flags, compiler_override=compiler)
                negative = fixture.replace('static const float centered[10]={' + centered_row + '}',
                                           'static const float centered[10]={' + original_row + '}')
                with self.assertRaisesRegex(AssertionError, 'fabsf'):
                    compile_probe('town-title-old-low-' + edition, defines + negative, {'runtime.h': runtime},
                                  extra_flags=flags, compiler_override=compiler)


if __name__ == '__main__':
    unittest.main()
