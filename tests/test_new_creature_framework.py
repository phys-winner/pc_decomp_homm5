"""MMH5.5's New Creature Framework (NewCreatureFramework.yml, group Original) on the lifted 3.1 engine."""
import struct
import sys
import unittest

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import build_android

EXE = ROOT / "generated/input/H5_Game.exe"
GAME = ROOT / "generated/game-x86"
# The YAML's file offsets (check, the two limits, the jump and its cave) and the lifted instruction each
# one lands in: the limit's imm32 follows the opcode, the jump replaces the first instruction itself.
CHECK = (0x400, bytes.fromhex("8D4134C3CCCCCCCC"))
SEAMS = ((0x006CA781, b"\xB4\x00\x00\x00", 0x00ACB380, b"\xB8"),
         (0x006E1A20, b"\xB4\x00\x00\x00", 0x00AE261F, b"\x68"),
         (0x0000E076, b"\x8B\xF1", 0x0040EC76, b""))
CAVE = (0x0000E0B3, b"\xCC" * 9)
CONTROL = (b" if ", b"goto", b"?", b"==", b"!=", b"<=", b">=", b"&&", b"||", b"while", b"for ", b"switch", b"return")


class NewCreatureFrameworkTest(unittest.TestCase):
    def test_yaml_offsets_are_the_lifted_seams(self):
        if not EXE.is_file():
            self.skipTest("the lifted 3.1 image is not present")
        data = EXE.read_bytes()
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        count, optional = struct.unpack_from("<H", data, pe + 6)[0], struct.unpack_from("<H", data, pe + 20)[0]
        base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
        sections = [struct.unpack_from("<8sIIII", data, pe + 24 + optional + 40 * k) for k in range(count)]

        def address(offset):
            for _, _, virtual, size, raw in sections:
                if raw <= offset < raw + size:
                    return base + virtual + offset - raw
            raise AssertionError(hex(offset))

        self.assertEqual(data[CHECK[0]:CHECK[0] + len(CHECK[1])], CHECK[1])
        self.assertEqual(data[CAVE[0]:CAVE[0] + len(CAVE[1])], CAVE[1])
        for offset, original, instruction, opcode in SEAMS:
            self.assertEqual(data[offset:offset + len(original)], original)
            self.assertEqual(address(offset), instruction + len(opcode))
            start = offset - len(opcode)
            self.assertEqual(data[start:offset], opcode)

    def test_transform_changes_one_data_line_per_seam(self):
        if not (GAME / "game_0005.c").is_file():
            self.skipTest("generated ToE sources are not present")
        seen = 0
        for path in sorted(GAME.glob("game_*.c")):
            original = path.read_bytes()
            patched = build_android.new_creature_framework(original)
            if patched == original:
                continue
            removed = set(original.splitlines()) - set(patched.splitlines())
            added = [line for line in patched.splitlines() if line not in set(original.splitlines())]
            self.assertEqual(len(removed), 1, path.name)
            changed = [line for line in added if b"NCF" in line]
            self.assertEqual(len(changed), 1, path.name)
            code = changed[0].split(b"/*", 1)[0]
            # The PGO hash covers control flow only: a call in place of a constant keeps it.
            self.assertFalse([token for token in CONTROL if token in code], code)
            seen += 1
        self.assertEqual(seen, 3)

    def test_changed_anchor_fails_closed(self):
        function, original, _ = build_android.NEW_CREATURE_FRAMEWORK[1]
        text = function + b"\n    eax = 0xB5u; /* 0x00ACB380: mov eax, 0xb5 */\n}\n"
        with self.assertRaises(ValueError):
            build_android.new_creature_framework(text)
        self.assertEqual(build_android.new_creature_framework(b"void sub_00401000(void) {\n}\n"),
                         b"void sub_00401000(void) {\n}\n")

    def test_host_values(self):
        source = (ROOT / "android/host/ncf.c").read_text(encoding="utf-8")
        compile_probe("new-creature-framework", source.replace('#include "host.h"', '#include "stub.h"') + r'''
#include <assert.h>
#include <stdio.h>
int main(void) {
    assert(void_ncf_source(0x0C, 0x5000) == 0x0C && logs == 0);
    assert(void_ncf_creatures() == 180 && logs == 1 && void_ncf_creatures() == 180 && logs == 1);
    void_ncf_enable(1);
    assert(void_ncf_creatures() == 1000 && logs == 1);
    assert(void_ncf_source(0x0C, 0x5000) == 0x5000 && void_ncf_source(0x6000, 0x5000) == 0x6000);
    assert(void_ncf_source(0, 0x5000) == 0 && void_ncf_source(0x0D, 0x5000) == 0x0D);
    void_ncf_enable(0);
    assert(void_ncf_creatures() == 180 && void_ncf_source(0x0C, 0x5000) == 0x0C);
    puts("PASS New Creature Framework host values: limit 180/1000, map visual guard only when enabled");
    return 0;
}
''', {"stub.h": "#include <stdint.h>\nstatic int logs;\n"
                 "static void void_log(const char *fmt, ...) { (void)fmt; ++logs; }\n"})


if __name__ == "__main__":
    unittest.main()
