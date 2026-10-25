import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from test_town_music import music_inputs


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
spec = importlib.util.spec_from_file_location("deploy", Path(__file__).resolve().parents[1] / "tools/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class Deployment(unittest.TestCase):
    def test_asset_override_follows_original_video_and_preserves_inputs(self):
        override = deploy.ROOT / "config/video/intro_a1.xml"
        playlist = ET.fromstring(override.read_bytes())
        self.assertEqual(playlist.tag, "Base")
        self.assertEqual([child.tag for child in playlist], ["Movies"])
        self.assertEqual(list(playlist.find("Movies")), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / "original-game"
            (game / "video").mkdir(parents=True)
            (game / "video/intro_a1.xml").write_bytes(b"licensed original intro playlist")
            (game / "video/outro_a1.xml").write_bytes(b"licensed original outro playlist")
            (game / "profiles").mkdir()
            (game / "profiles/start.cfg").write_text("mainmenu\n")
            (game / "data").mkdir()
            (root / "config/profiles/default_profile").mkdir(parents=True)
            (root / "config/profiles/autoexec_a2.cfg").write_text("exec profiles\\start.cfg\n")
            (root / "config/profiles/default_profile/user_a2.cfg").write_text("test profile\n")
            (root / "config/video").mkdir()
            (root / "config/video/intro_a1.xml").write_bytes(override.read_bytes())
            (root / "config/modules.json").write_text("[]")
            music_inputs(root)
            original_data = (game / "data/data.pak").read_bytes()
            music_path, music_receipt = deploy.build_town_music_override(root)
            with patch.object(deploy, "ROOT", root), patch.object(deploy, "PORT", {"game_directory": "original-game"}), \
                    patch("sys.argv", ["deploy.py", "--data", "--serial", "TEST_DEVICE"]), patch.object(deploy.subprocess, "run") as run, \
                    patch.object(deploy.subprocess, "check_output", return_value=music_receipt["sha256"] + " file\n"):
                deploy.main()
            commands = [call.args[0][3:] for call in run.call_args_list]
            video_copy = ["push", "--sync", str(game / "video"), deploy.DEVICE_ROOT + "/game/"]
            override_copy = ["push", str(root / "config/video/intro_a1.xml"), deploy.DEVICE_ROOT + "/game/video/intro_a1.xml"]
            self.assertEqual(commands.count(override_copy), 1)
            self.assertGreater(commands.index(override_copy), commands.index(video_copy))
            self.assertEqual((game / "video/intro_a1.xml").read_bytes(), b"licensed original intro playlist")
            self.assertEqual((game / "video/outro_a1.xml").read_bytes(), b"licensed original outro playlist")
            self.assertEqual((game / "profiles/start.cfg").read_text(), "mainmenu\n")
            music_copy = ["push", str(music_path), deploy.DEVICE_ROOT + "/game/data/" + music_path.name]
            self.assertGreater(commands.index(music_copy), commands.index(override_copy))
            self.assertGreater(commands.index(music_copy), commands.index(["push", "--sync", str(game / "data"), deploy.DEVICE_ROOT + "/game/"]))
            self.assertEqual((game / "data/data.pak").read_bytes(), original_data)
            receipt = json.loads((root / "build/deploy-receipt.json").read_text())
            self.assertEqual(receipt["verified_sha256"][music_copy[-1]], music_receipt["sha256"])
            self.assertTrue(receipt["town_music_override"]["runtime_verification"].startswith("pending:"))

    def test_bad_music_input_stops_before_any_device_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music_inputs(root)
            manifest_path = root / "config/music/manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["Haven.(Music).xdb"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))
            with patch.object(deploy, "ROOT", root), patch.object(deploy, "PORT", {"game_directory": "original-game"}), \
                    patch("sys.argv", ["deploy.py", "--data", "--serial", "TEST_DEVICE"]), \
                    patch.object(deploy.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "canonical input changed"):
                    deploy.main()
                run.assert_not_called()

    def test_checks_real_device_bytes_and_records_success_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "generated/input").mkdir(parents=True)
            (root / "config/modules.json").write_text('[{"file":"game.exe"}]')
            data = b"a private mapped PE image"
            (root / "generated/input/game.exe").write_bytes(data)
            with patch.object(deploy, "ROOT", root), patch("sys.argv", ["deploy.py", "--serial", "TEST_DEVICE"]), \
                    patch.object(deploy.subprocess, "run") as run, \
                    patch.object(deploy.subprocess, "check_output", return_value="0" * 64 + " file\n") as checksum:
                with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                    deploy.main()
                self.assertFalse((root / "build/deploy-receipt.json").exists())
                checksum.return_value = hashlib.sha256(data).hexdigest() + " file\n"
                deploy.main()
                self.assertIn(hashlib.sha256(data).hexdigest(), (root / "build/deploy-receipt.json").read_text())
                self.assertTrue(all(call.args[0][1:3] == ["-s", "TEST_DEVICE"] for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
