"""Small synthetic checks of host and PE symbol matching without running a game."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from import_audit import audit, parse_aliases, parse_registrations


def module(name, base, imports=(), exports=None, packed=False):
    return {"file": name, "base": base, "size": 0x10000, "packed": packed, "tls": False,
            "imports": [{"dll": dll, "symbol": symbol, "delay": False} for dll, symbol in imports],
            "exports": exports or {}}


class ImportAuditTest(unittest.TestCase):
    def test_crt_aliases(self):
        self.assertEqual(parse_aliases('if (name_matches(name, "msvcrt.dll") || name_matches(name, "crtdll.dll")) name = "msvcr71.dll";'),
                         {"msvcrt.dll": "msvcr71.dll", "crtdll.dll": "msvcr71.dll"})

    def test_preprocessed_registrations(self):
        text = '''
        static const void_shim First_shim __attribute__((used, section("void_shims"), aligned(8))) = { "KERNEL32.dll", "Sleep", 0, First_entry };
        static const void_shim Other_shim __attribute__((used, section("void_shims"), aligned(8))) = { "ws2_32.dll", "socket", 23, Other_entry };
        static const void_shim Ordinal_shim __attribute__((used)) = { "example.dll", ((void *)0), 0xA, Ordinal_entry };
        '''
        self.assertEqual(parse_registrations(text), {("kernel32.dll", "Sleep"), ("ws2_32.dll", "socket"), ("ws2_32.dll", "#23"), ("example.dll", "#10")})

    def test_aliases_ordinals_forwarders_and_gaps(self):
        modules = {
            "game.exe": module("Game.exe", 0x400000, [("msvcrt.dll", "_iob"), ("api.dll", "#17"), ("kernel32.dll", "Sleep"), ("kernel32.dll", "sleep"), ("api.dll", "Forwarded"), ("absent.dll", "Missing")]),
            "msvcr71.dll": module("msvcr71.dll", 0x13000000, exports={"_iob": None}),
            "api.dll": module("api.dll", 0x14000000, exports={"#17": None, "Forwarded": "other.Real"}),
        }
        result = audit(modules, {("kernel32.dll", "Sleep")}, {"msvcrt.dll": "msvcr71.dll"})
        self.assertEqual(result["counts"], {"lifted_export": 2, "host_registration": 1, "missing": 3})
        self.assertEqual(result["missing"]["kernel32.dll"], {"sleep": ["Game.exe"]})
        self.assertIn("Forwarded", result["missing"]["api.dll"])
        self.assertFalse(result["base_collisions"])

    def test_packing_and_overlapping_images(self):
        result = audit({"a.dll": module("a.dll", 0x10000000), "b.dll": module("b.dll", 0x10001000, packed=True)}, set(), {})
        self.assertEqual(result["packed_modules"], ["b.dll"])
        self.assertEqual(result["base_collisions"], [["a.dll", "b.dll"]])


if __name__ == "__main__":
    unittest.main()
