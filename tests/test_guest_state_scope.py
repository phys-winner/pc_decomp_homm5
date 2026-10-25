"""Guest-state alias promises stay within the selected generated functions."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android as builder


class GuestStateScopeTest(unittest.TestCase):
    def test_exact_scope_body_preservation_and_idempotence(self):
        for newline in (b"\n", b"\r\n"):
            cold = b"void sub_00401000(void) {\n    MEM32(eax) = ecx;\n}\n".replace(b"\n", newline)
            hot = b"void sub_00C68210(void) {\n    MEM32(esp) = edi;\n}\n".replace(b"\n", newline)
            source = cold + hot + cold
            result = builder.separate_guest_state(source)
            self.assertEqual(result, cold + builder.GUEST_STATE_SEPARATE + hot + builder.GUEST_STATE_DEFAULT + cold)
            self.assertEqual(builder.separate_guest_state(result), result)
            self.assertEqual(builder.separate_guest_state(source, ()), source)
            self.assertEqual(builder.separate_guest_state(cold), cold)
        with self.assertRaisesRegex(ValueError, "Missing hot function boundary"):
            builder.separate_guest_state(b"void sub_00C68210(void) {\n    MEM32(eax) = 1;\n")

    def test_actual_corpus_scope_does_not_rewrite_bodies(self):
        seen = []
        changed = []
        for path in builder.generated_sources():
            source = path.read_bytes()
            result = builder.separate_guest_state(source)
            if result != source:
                changed.append(path)
            self.assertEqual(result.replace(builder.GUEST_STATE_SEPARATE, b"").replace(builder.GUEST_STATE_DEFAULT, b""), source)
            self.assertEqual(builder.separate_guest_state(result), result)
            for match in builder.FUNCTION_START.finditer(source):
                name = match[0].split(b"(", 1)[0][5:]
                if name in builder.GUEST_STATE_HOT_FUNCTIONS:
                    seen.append(name)
        self.assertEqual(len(changed), 37)
        self.assertEqual(len(seen), 59)
        self.assertEqual(sorted(seen), sorted(builder.GUEST_STATE_HOT_FUNCTIONS))


if __name__ == "__main__":
    unittest.main()
