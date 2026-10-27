"""Run original-edition minimap draw/click/drag against their resolved window origins."""
from pathlib import Path
import sys
import unittest

from test_d3d_lifecycle import function
from test_legacy_ui import generated_body
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android
import build_windows
import port_patches
import prepare_windows_runtime

# Execute the public CAdvMinimap IWindow vtable entries, including their this
# adjustors. The native converter and public rectangle entry stay unmodified.
SPECS = {
    'vanilla': dict(draw=0x57E6E0, click=0x57E6A0, drag=0x57E6B0, converter=0x57B9A0,
                    public_rect=0x57E560, rect_body=0xA74D30, RECT_BODY=0xA74D30,
                    CONVERT=0x57B9A0, QUAD=0x412060, GET_MAP=0x41FD10, CONVERT_QUADS=0x4110C0,
                    BASE_DRAW=0xA756D0, BASE_CLICK=0xA78540, BASE_DRAG=0xA779F0,
                    STRING=0x401D60, EMIT=0x8BFCD0, FREE=0xC00360,
                    UPDATE0=0x57C080, UPDATE1=0x57C890, UPDATE2=0x57C450,
                    BASE_OFFSET=0x194, RESOURCE_OFFSET=0xAC, TEXTURE_OFFSET=0x98, OBJECT_OFFSET=0x1A4,
                    OPAQUE_CONST=0xDE73F0,
                    PADDING=0xE0164C, EDGE=0xE01648, RECIP=0xE01644,
                    MAP_BORDER=0x1D0, MAP_WIDTH=0x50, MAP_HEIGHT=0x54),
    'hof': dict(draw=0x5954F0, click=0x5954B0, drag=0x5954C0, converter=0x593410,
                public_rect=0x595370, rect_body=0xBDF780, RECT_BODY=0xBDF780,
                CONVERT=0x593410, QUAD=0x4A1690, GET_MAP=0x4DFF30, CONVERT_QUADS=0xB04830,
                BASE_DRAW=0xBE0150, BASE_CLICK=0xBE2F30, BASE_DRAG=0xBE23D0,
                STRING=0x403300, EMIT=0x9FFD30, FREE=0xA99C10,
                UPDATE0=0x5937F0, UPDATE1=0x5939C0, UPDATE2=0x5930F0,
                BASE_OFFSET=0x1A0, RESOURCE_OFFSET=0xB4, TEXTURE_OFFSET=0xA0, OBJECT_OFFSET=0x1B0,
                OPAQUE_CONST=0xDD8A24,
                PADDING=0xDD8A78, EDGE=0xDD8A74, RECIP=0xDD8A70,
                MAP_BORDER=0x1CC, MAP_WIDTH=0x4C, MAP_HEIGHT=0x50),
}


class LegacyMinimapTest(unittest.TestCase):
    def test_actual_draw_and_input_follow_the_same_frame_at_ui50_100_200(self):
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        source = (ROOT / 'android/host/touch_scale.c').read_text()
        scale = '\n'.join(function(source, name) for name in (
            'static float scale_native_position(', 'static float scale_size(',
            'static int scale_near(', 'static float scale_anchor_shift('))
        compiler, _, _ = build_windows.compiler_environment()
        for edition, spec in SPECS.items():
            with self.subTest(edition=edition):
                bodies = []
                for key in ('draw', 'click', 'drag', 'converter', 'public_rect', 'rect_body'):
                    address = spec[key]
                    raw = generated_body(edition, address)
                    adapted = port_patches.adapt_generated_source(raw.encode(), 'game', edition).decode()
                    bodies.append(adapted.replace(f'void sub_{address:08X}(', 'void ' + key + '('))
                    if key in ('draw', 'click'):
                        bodies.append(raw.replace(f'void sub_{address:08X}(', 'void old_' + key + '('))
                defines = '#define VISIBLE 0xDEAD1000u\n#define RENDER 0xDEAD1004u\n#define PLACEMENT 0xDEAD1008u\n'
                defines += ''.join(f'#define {key} 0x{value:X}u\n' for key, value in spec.items() if key.isupper())
                fixture = (ROOT / 'tests/fixtures/legacy_minimap_probe.c').read_text()
                fixture = fixture.replace('/* STATE */', state).replace('/* SCALE_HELPERS */', scale)
                fixture = fixture.replace('/* ACTUAL */', '\n'.join(bodies))
                compile_probe('legacy-minimap-' + edition, defines + fixture, {'runtime.h': runtime},
                              extra_flags=['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label',
                                           '/clang:-Wno-unused-function'], compiler_override=compiler)

    def test_all_native_draw_click_and_drag_instruction_aliases_are_adapted(self):
        # Vtable adjustors embed copies of their targets. Patching only the
        # standalone function would leave the real virtual entry uncorrected.
        instructions = {
            'vanilla': ([0x57CF5E, 0x57CFC5, 0x57D039, 0x57BBBE, 0x57BCCB],
                        [0x57CF8A, 0x57CFED, 0x57D061, 0x57BBD4, 0x57BCE1]),
            'hof': ([0x5940BF, 0x59411E, 0x594192, 0x59362E, 0x59373B],
                    [0x5940E7, 0x594146, 0x5941B7, 0x593644, 0x593751]),
        }
        for edition, (x_reads, y_reads) in instructions.items():
            with self.subTest(edition=edition):
                x_offset, y_offset = ('0x140', '0x13C') if edition == 'vanilla' else ('0x14C', '0x148')
                targets = {address: x_offset for address in x_reads}
                targets.update({address: y_offset for address in y_reads})
                markers = {f'0x{address:08X}:'.encode(): offset for address, offset in targets.items()}
                seen = set()
                for path in (ROOT / 'generated' / edition / 'game-x86').glob('*.c'):
                    raw = path.read_bytes().replace(b'\r\n', b'\n')
                    if not any(marker in raw for marker in markers):
                        continue
                    raw = build_android.round_x87_precision(build_android.guard_fpu_memory(raw))
                    adapted = port_patches.adapt_generated_source(raw, 'game', edition)
                    for line in adapted.splitlines():
                        for marker, offset in markers.items():
                            if marker in line:
                                seen.add(marker)
                                self.assertIn(('esi + (-' + offset + ')').encode(), line.split(b' /* ', 1)[0])
                self.assertEqual(seen, set(markers))


if __name__ == '__main__':
    unittest.main()
