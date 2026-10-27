"""Run the real legacy archive builder, CString/vector ABI and optional FS open."""
import json
from pathlib import Path
import sys
import unittest

from test_legacy_ui import generated_body
from test_static_tls import compile_probe

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import build_windows
import port_patches
import prepare_windows_runtime

SPECS = {
    'vanilla': dict(builder=0xAF03F0, concat=0x401FA0, append=0x77DA50, pattern=0xA62700, compare=0xA614C0,
        insert=0xA61CE0, record=0xA61460, attributes=0x4CE300, entry_size=0x4CE2F0, entry_time=0x4CE310,
        zip_constructor=0x4CE560, FILE_OPEN=0xAD0640, FILE_SIZE=0xAD05A0, FILE_MAP_ENABLE=0xAD05E0,
        ZIP_MAP=0x4CE790, ZIP_MAP_FREE=0x4CE810, ZIP_VECTOR=0x4B1400, VERSION_IAT=0xDE316C,
        GET_ATTACHED=0xBD5200, CAST=0xC0D69E, GET_DEFAULT=0xBD5230, ALLOC=0xC00310, FREE=0xC00360,
        COPY_FS=0xB36BC0, STRING=0x401D60, APPEND_BYTES=0x401E10, COPY_RECORDS=0xAF10F0,
        CONSTRUCT_RECORD=0x77B2E0, DESTROY_VECTOR=0x84E480, FACTORY=0xA63090,
        FIND=0x98B8D0, FIND_PATH=0x98B7C0, FIND_NEXT=0x98ACE0, FIND_FREE=0x98AC10, ADD_PAK=0xA61CE0,
        NEW=0xC000D0, WRAPPER=0x7EAB30, ARCHIVE_SLOT=0xA63930, ENTRY_NAME=0x4CE720,
        MAP_FIND=0xA6E970, MAP_CREATE=0xA63A20,
        CONSTANTS=0xE51F00, NATIVE_COUNT=8, VECTOR_OFFSET=0x3C, FRAME=0xC4),
    'hof': dict(builder=0x7B09B0, concat=0x4229B0, append=0x7B1A40, pattern=0x92B2D0, compare=0x92A070,
        insert=0x92A8B0, record=0x92A010, attributes=0xC01B00, entry_size=0xC01AF0, entry_time=0xC01B10,
        zip_constructor=0xC01D60, FILE_OPEN=0xB9B2E0, FILE_SIZE=0xB9B240, FILE_MAP_ENABLE=0xB9B280,
        ZIP_MAP=0xC01F90, ZIP_MAP_FREE=0xC02000, ZIP_VECTOR=0xA806D0, VERSION_IAT=0xDBA0F4,
        GET_ATTACHED=0x9BC670, CAST=0xC09BCE, GET_DEFAULT=0x9BC6A0, ALLOC=0xA99BC0, FREE=0xA99C10,
        COPY_FS=0xAC9C80, STRING=0x403300, APPEND_BYTES=0x4220E0, COPY_RECORDS=0x7742D0,
        CONSTRUCT_RECORD=0x7B1800, DESTROY_VECTOR=0x774870, FACTORY=0x92B970,
        FIND=0x4FAEC0, FIND_PATH=0x4FAF50, FIND_NEXT=0x8220C0, FIND_FREE=0x821FF0, ADD_PAK=0x92A8B0,
        NEW=0xA999A0, WRAPPER=0xAFCD80, ARCHIVE_SLOT=0x92C1A0, ENTRY_NAME=0xC01F20,
        MAP_FIND=0xAD6330, MAP_CREATE=0x92C290,
        CONSTANTS=0xDFA900, NATIVE_COUNT=15, VECTOR_OFFSET=0x30, FRAME=0x11C),
}
INSERT_ALIASES = {
    'vanilla': (0xA61D30, 0xA61DA6, 0xA61EBE, 0xA61EC5, 0xA61EDB, 0xA627F0),
    'hof': (0x92A900, 0x92A976, 0x92AA8E, 0x92AA95, 0x92AAAB, 0x92B3C0),
}


class LegacyTextureMountTest(unittest.TestCase):
    def test_actual_native_bank_builder_and_optional_open(self):
        state = (ROOT / 'android/host/core.c').read_text()
        state = state[state.index('VOID_HIDDEN uint32_t g_eax'):state.index('#define VOID_ENTER_RING')]
        runtime = prepare_windows_runtime.platform_header((ROOT / 'android/runtime/recomp_types.h').read_text())
        compiler, _, _ = build_windows.compiler_environment()
        import pefile
        for edition, spec in SPECS.items():
            with self.subTest(edition=edition):
                functions = []
                for name in ('builder', 'concat', 'append', 'pattern', 'compare', 'insert', 'record', 'attributes', 'entry_size', 'entry_time', 'zip_constructor'):
                    address = spec[name]
                    body = port_patches.adapt_generated_source(generated_body(edition, address).encode(), 'game', edition).decode()
                    functions.append(body.replace(f'void sub_{address:08X}(', 'void ' + name + '('))
                # The static catalog also exposes overlapping native entry points.
                # Every patched copy must compile with its own original labels.
                for address in INSERT_ALIASES[edition]:
                    functions.append(port_patches.adapt_generated_source(
                        generated_body(edition, address).encode(), 'game', edition).decode())
                image = pefile.PE(str(ROOT / 'generated' / edition / 'input/H5_Game.exe'), fast_load=True)
                constants = image.get_data(spec['CONSTANTS'] - image.OPTIONAL_HEADER.ImageBase, 0x300)
                defines = ''.join(f'#define {key.upper()} 0x{value:X}u\n' for key, value in spec.items())
                fixture = (ROOT / 'tests/fixtures/legacy_texture_mount_probe.c').read_text()
                fixture = fixture.replace('/* STATE */', state).replace('/* ACTUAL */', '\n'.join(functions))
                fixture = fixture.replace('/* CONSTANTS */', ','.join(str(byte) for byte in constants))
                compile_probe('legacy-texture-mount-' + edition, defines + fixture, {'runtime.h': runtime},
                              extra_flags=['/clang:-Wno-unused-variable', '/clang:-Wno-unused-label',
                                           '/clang:-Wno-unused-function'], compiler_override=compiler)


if __name__ == '__main__':
    unittest.main()
