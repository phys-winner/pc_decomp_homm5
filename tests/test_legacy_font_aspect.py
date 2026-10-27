"""Execute the real font scalar resolver against independent bitmap line metrics."""
import json
from pathlib import Path
import sys
import unittest

from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_android
import build_windows
from editions import generated_root
import port_patches
import prepare_windows_runtime

SPECS = {
    'toe': dict(resolver=0xCBF650, coords=0xB294C0, virtual_size=0xB29070, float_min=0x465610,
                COORDS=0xB294C0, VIRTUAL_SIZE=0xB29070, MIN_FLOAT=0x465610,
                SERVICE=0xA4AA50, STRING=0x401B20, FONT_BANK=0x474830, UNWRAP=0x578A90,
                FREE=0x879240, SIZE_SLOT=0x24, CANVAS_X=0xF74BE0, CANVAS_Y=0xF74BE4,
                PHYSICAL_X=0xF74BF0, PHYSICAL_Y=0xF74BF4, RECIP_X=0xE12F00, RECIP_Y=0xE30FC0,
                ASPECT=0xE7BEDC, ONE=0xE12F10),
    'vanilla': dict(resolver=0x9C13B0, coords=0x410F90, COORDS=0x410F90,
                    SERVICE=0x9CD400, STRING=0x401D60, FONT_BANK=0xAC6AD0, UNWRAP=0x7DC020,
                    FREE=0xC00360, SIZE_SLOT=0x20, CANVAS_X=0xF07D4C, CANVAS_Y=0xF07D50,
                    PHYSICAL_X=0xF07D54, PHYSICAL_Y=0xF07D58, RECIP_X=0xDE4EFC, RECIP_Y=0xDE4F00,
                    ASPECT=0xE25AB8, ONE=0xDE73F0),
    'hof': dict(resolver=0x8C1570, coords=0xB04700, COORDS=0xB04700,
                SERVICE=0x9B5270, STRING=0x403300, FONT_BANK=0x9AD280, UNWRAP=0x8C4740,
                FREE=0xA99C10, SIZE_SLOT=0x20, CANVAS_X=0xF24178, CANVAS_Y=0xF2417C,
                PHYSICAL_X=0xF24180, PHYSICAL_Y=0xF24184, RECIP_X=0xDC6804, RECIP_Y=0xDC6800,
                ASPECT=0xDFA050, ONE=0xDBC09C),
}


def body(edition, address):
    folder = generated_root(edition) / 'game-x86'
    report = json.loads((folder / 'report.json').read_text())
    entries = [int(value, 0) for value in report['dispatch_entries']]
    source = folder / report['sources'][entries.index(address) // 100]
    text = build_android.round_x87_precision(build_android.guard_fpu_memory(source.read_bytes())).decode()
    start = text.index(f'void sub_{address:08X}(void) {{')
    return text[start:text.index('\n}', start) + 2] + '\n'


class LegacyFontAspectTest(unittest.TestCase):
    def test_actual_resolver_preserves_font_choice_and_uses_toe_equal_axis_scaling(self):
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        compiler, _, _ = build_windows.compiler_environment()
        for edition, spec in SPECS.items():
            with self.subTest(edition=edition):
                sources = []
                for name in ('resolver', 'coords', 'virtual_size', 'float_min'):
                    if name not in spec:
                        continue
                    address = spec[name]
                    original = body(edition, address)
                    patched = port_patches.adapt_generated_source(original.encode(), 'game', edition).decode()
                    sources.append(patched.replace(f'void sub_{address:08X}(', 'void ' + name + '('))
                    if name == 'resolver' and edition != 'toe':
                        sources.append(original.replace(f'void sub_{address:08X}(', 'void old_resolver('))
                defines = ('#define TOE 1\n' if edition == 'toe' else '')
                defines += '#define CONTROLLER 0xDEAD1000u\n#define PHYSICAL_SIZE 0xDEAD1004u\n#define FONT_REQUEST 0xDEAD1008u\n'
                defines += ''.join(f'#define {key} 0x{value:X}u\n' for key, value in spec.items() if key.isupper())
                fixture = (ROOT / 'tests/fixtures/legacy_font_aspect_probe.c').read_text()
                fixture = fixture.replace('/* STATE */', state).replace('/* ACTUAL */', '\n'.join(sources))
                compile_probe('legacy-font-aspect-' + edition, defines + fixture, {'runtime.h': runtime},
                              extra_flags=['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label',
                                           '/clang:-Wno-unused-function'], compiler_override=compiler)


if __name__ == '__main__':
    unittest.main()
