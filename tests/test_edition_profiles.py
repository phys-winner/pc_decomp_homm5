from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from profile_defaults import bootstrap_profiles


class EditionProfiles(unittest.TestCase):
    def test_each_original_bootstrap_and_unrelated_values_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            registry = json.loads((ROOT / "config/editions.json").read_text())
            (root / "config/editions.json").write_text(json.dumps(registry))
            (root / "port.json").write_text(json.dumps({"editions": {e: {"game_directory": "original"} for e in ("vanilla", "hof")}}))
            for edition in ("vanilla", "hof"):
                suffix = registry[edition]["profile_suffix"]
                folder = root / "original/profiles/default_profile"
                folder.mkdir(parents=True, exist_ok=True)
                auto = root / ("original/profiles/autoexec" + suffix + ".cfg")
                auto.write_bytes(b"native_only_command 42\r\nsetvar ubi_tracking_tool_enabled = 1\r\n")
                user = folder / ("user" + suffix + ".cfg")
                values = b"setvar Options.Tooltips.HoverTimeout = 1.0\r\nsetvar app_always_active = 0\r\nsetvar gfx_dynamic_lights = 1\r\nsetvar gfx_noshadows = 0\r\nsetvar gfx_resolution = 1024x768\r\nsetvar gfx_water_reflection = 1\r\nsetvar native_only_variable = 73\r\n"
                user.write_bytes(values)
                original_auto = auto.read_bytes()
                result = bootstrap_profiles(root, edition)
                self.assertEqual(result["profiles/autoexec" + suffix + ".cfg"],
                    b"setvar ubi_tracking_tool_enabled = 0\r\nnative_only_command 42\r\n")
                patched = result["profiles/default_profile/user" + suffix + ".cfg"]
                self.assertIn(b"native_only_variable = 73\r\n", patched)
                self.assertIn(b"gfx_resolution = 1280x800\r\n", patched)
                self.assertNotIn(b"_a2", patched)
                self.assertEqual(auto.read_bytes(), original_auto)
                self.assertEqual(user.read_bytes(), values)
                missing_flag = b"native_only_command 42\r\nmainmenu\r\n"
                auto.write_bytes(missing_flag)
                result = bootstrap_profiles(root, edition)
                self.assertEqual(result["profiles/autoexec" + suffix + ".cfg"],
                    b"setvar ubi_tracking_tool_enabled = 0\r\n" + missing_flag)
                self.assertEqual(auto.read_bytes(), missing_flag)
                user.write_bytes(values.replace(b"setvar gfx_resolution = 1024x768\r\n", b""))
                with self.assertRaisesRegex(ValueError, "gfx_resolution"):
                    bootstrap_profiles(root, edition)

    def test_toe_also_disables_tracking_before_boot_and_in_saved_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config/profiles/default_profile").mkdir(parents=True)
            (root / "config/editions.json").write_bytes((ROOT / "config/editions.json").read_bytes())
            auto = root / "config/profiles/autoexec_a2.cfg"
            original = b"native_bootstrap 42\r\nsetvar ubi_tracking_tool_enabled = 1\r\nmainmenu\r\n"
            auto.write_bytes(original)
            user = root / "config/profiles/default_profile/user_a2.cfg"
            user.write_bytes(b"setvar native_only_variable = 73\nsetvar ubi_tracking_tool_enabled = 1\n")
            result = bootstrap_profiles(root, "toe")
            self.assertEqual(result["profiles/autoexec_a2.cfg"],
                b"setvar ubi_tracking_tool_enabled = 0\r\nnative_bootstrap 42\r\nmainmenu\r\n")
            self.assertIn(b"setvar ubi_tracking_tool_enabled = 0\n", result["profiles/default_profile/user_a2.cfg"])
            self.assertEqual(auto.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
