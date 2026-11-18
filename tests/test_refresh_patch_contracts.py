"""Refreshing a source pin must not silently approve a changed edition-specific ABI seam."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from refresh_patch_contracts import refresh_identity_anchors


class ContractRefreshTest(unittest.TestCase):
    def test_identity_body_and_sequential_masking(self):
        old = "static void update(void)\n{\n    read32(screen + 0xA0);\n}\n"
        new = old.replace("read32", "consume")
        patches = [dict(old=old, new=old, count=1), dict(old="screen + 0xA0", new="screen + 0x98", count=1)]
        source = new + "read32(screen + 0xA0);\n"
        result = refresh_identity_anchors(source.encode(), patches)
        self.assertEqual(result[0]["old"], new)
        self.assertEqual(result[0]["new"], new)
        self.assertEqual(result[1], patches[1])
        self.assertEqual(patches[0]["old"], old)  # no mutation on partial failure

    def test_real_abi_partial_and_ambiguous_changes_fail(self):
        original = "static void update(void)\n{\n    read32(screen + 0xA0);\n}\n"
        for patch, source in (
            (dict(old=original, new=original.replace("0xA0", "0x98"), count=1), original.replace("read32", "consume")),
            (dict(old="screen + 0xA0", new="screen + 0xA0", count=1), "changed();"),
            (dict(old=original, new=original, count=1), (original + original).replace("read32", "consume")),
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                refresh_identity_anchors(source.encode(), [patch])

    def test_only_active_legacy_branch(self):
        original = "static void update(void)\n{\n    old();\n}\n"
        changed = original.replace("old", "new")
        source = "#ifndef HOMM5_LEGACY_UI\n" + original + "#else\n" + changed + "#endif\n"
        result = refresh_identity_anchors(source.encode(), [dict(old=original, new=original, count=1)])
        self.assertEqual(result[0]["old"], changed)


if __name__ == "__main__":
    unittest.main()
