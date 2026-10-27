"""Execute the shared touch camera against verified 1.6/2.1 native layouts."""
import re
from pathlib import Path
import sys
import unittest

from test_static_tls import compile_probe
from test_touch_camera import HARNESS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import port_patches


def engine_harness(edition, addresses):
    # Fixture object memory is constructed independently of production layout
    # patches. These fields are pinned by native Home/ResetCamera/TownManualInit.
    fields = {
        0xA0: 0x98, 0xA4: 0x9C, 0x14C: 0x144,
        0x220: 0x218 if edition == 'vanilla' else 0x214,
        0x294: 0x28C if edition == 'vanilla' else 0x288,
        0x29C: 0x294 if edition == 'vanilla' else 0x290,
        0x478: 0x470 if edition == 'vanilla' else 0x46C,
        0x374: 0x36C if edition == 'vanilla' else 0x368,
        0x3B8: 0x38C if edition == 'vanilla' else 0x3A4,
        0x5E4: 0x55C if edition == 'vanilla' else 0x568,
        0x2E0: 0x2D8 if edition == 'vanilla' else 0x2F0,
    }
    harness = re.sub(r'0x[0-9a-fA-F]+', lambda m:
        hex(0x10000 + fields[int(m[0], 16) - 0x10000])
        if int(m[0], 16) - 0x10000 in fields else m[0], HARNESS)
    harness = re.sub(r'self\+0x([0-9a-fA-F]+)', lambda m:
        'self+' + hex(fields.get(int(m[1], 16), int(m[1], 16))), harness)
    # Hammers' native town input queries the roster directly (614200 absent).
    # Keep the same missing/busy/modal/owner-change scenarios of the ToE oracle.
    if edition == 'hof':
        harness = harness.replace('if(va==0x614200||va==0x6146C0) {',
            'if(va==0x410040) {assert(self==0x24000&&!n&&!args);return town_busy?0:0x25000;}\n'
            '    if(va==0x614200||va==0x6146C0) {')
    mapping = dict(addresses)
    # This table is in the fixture only; production only checks the town class.
    mapping['00E4493C'] = '00E21444' if edition == 'vanilla' else '00DF63A4'
    harness = re.sub(r'0x([0-9a-fA-F]+)(?![0-9a-fA-F])', lambda m:
        '0x' + mapping.get(f'{int(m[1], 16):08X}', m[1]), harness)
    return harness


class LegacyCameraTest(unittest.TestCase):
    def source(self, edition):
        source, _ = port_patches.adapt_host_source(ROOT / 'android/host/touch_camera.c',
            ROOT / 'build/tests' / ('legacy-camera-' + edition), edition)
        text = source.read_text()
        for header in ('host.h', 'input.h', 'touch.h'):
            text = text.replace('#include "' + header + '"\n', '')
        return text

    def test_actual_camera_pan_pinch_orbit_tilt_town_frame_and_edge_abi(self):
        for edition in ('vanilla', 'hof'):
            with self.subTest(edition=edition):
                addresses = port_patches.load_contract(edition)['addresses']
                source = self.source(edition)
                self.assertNotIn('screen + 0xA4', source)
                self.assertIn('hand + 0x14C', source)  # Native operator pitch did not move.
                if edition == 'hof':
                    self.assertNotIn('0x00614200u', source)
                    self.assertIn('!void_call_guest_this(roster, controller, 0, NULL)', source)
                compile_probe('legacy-camera-' + edition, engine_harness(edition, addresses),
                              {'touch_camera_impl.h': source})

    def test_native_bounds_entry_is_not_adjacent_orientation_routine(self):
        for edition, bounds, orientation in (('vanilla', '00767FB0', '007615E0'),
                                              ('hof', '00762E80', '0075C270')):
            with self.subTest(edition=edition):
                addresses = port_patches.load_contract(edition)['addresses']
                self.assertEqual(addresses['007D4720'], bounds)
                source = self.source(edition).replace('0x' + bounds + 'u', '0x' + orientation + 'u')
                with self.assertRaises(AssertionError):
                    compile_probe('legacy-camera-wrong-bounds-' + edition,
                                  engine_harness(edition, addresses), {'touch_camera_impl.h': source})

    def test_old_toe_screen_layout_is_rejected_by_original_edition_fixture(self):
        for edition in ('vanilla', 'hof'):
            with self.subTest(edition=edition):
                addresses = port_patches.load_contract(edition)['addresses']
                source = self.source(edition).replace('screen + 0x9C', 'screen + 0xA4')
                with self.assertRaises(AssertionError):
                    compile_probe('legacy-camera-wrong-layout-' + edition,
                                  engine_harness(edition, addresses), {'touch_camera_impl.h': source})


if __name__ == '__main__':
    unittest.main()
