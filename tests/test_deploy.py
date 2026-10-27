import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import tempfile
import sys
import unittest
import xml.etree.ElementTree as ET
import zipfile
from unittest.mock import patch
from test_town_music import music_inputs


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
spec = importlib.util.spec_from_file_location("deploy", Path(__file__).resolve().parents[1] / "tools/deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class Deployment(unittest.TestCase):
    def registry(self, root):
        (root / "config").mkdir(parents=True, exist_ok=True)
        (root / "config/editions.json").write_bytes((deploy.ROOT / "config/editions.json").read_bytes())
        self.runtime(root)

    def runtime(self, root, edition="toe"):
        spec = deploy.edition_spec(edition, root)
        binary = deploy.build_root(edition, root=root) / (spec["library"].replace("_", "-") + "-arm64")
        binary.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray(64)
        data[:6], data[18:20] = b"\x7fELF\x02\x01", b"\xb7\x00"
        binary.write_bytes(data)
        return binary

    def ui_override(self, root, game=None, edition="toe"):
        path = root / ("build/ui-fixture-" + edition) / "z_homm5_android_ui.pak"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("UI/uiconsts.(UIGameConstsH5).xdb", ("checked UI fixture " + edition).encode())
            archive.writestr("UI/Consts/GameOptions/PortAdditional.txt", "Дополнительные".encode("utf16"))
        return path, {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def device_checksum(self, run):
        def checksum(command, **unused):
            destination = shlex.split(command[-1])[1]
            for call in reversed(run.call_args_list):
                args = call.args[0]
                if args[3] == "push" and args[-1] in (destination, destination + ".new"):
                    return hashlib.sha256(Path(args[-2]).read_bytes()).hexdigest() + " file\n"
            self.fail("No uploaded file: " + destination)
        return checksum

    def test_asset_override_follows_original_video_and_preserves_inputs(self):
        override = deploy.ROOT / "config/video/intro_a1.xml"
        playlist = ET.fromstring(override.read_bytes())
        self.assertEqual(playlist.tag, "Base")
        self.assertEqual([child.tag for child in playlist], ["Movies"])
        self.assertEqual(list(playlist.find("Movies")), [])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.registry(root)
            game = root / "original-game"
            (game / "bin").mkdir(parents=True)
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
                    patch.object(deploy.subprocess, "check_output", side_effect=self.device_checksum(run)), \
                    patch.object(deploy, "validate_packaged_native", return_value={}), \
                    patch.object(deploy, "validate_overlay", return_value={}), \
                    patch.object(deploy, "build_port_ui_override", side_effect=self.ui_override):
                deploy.main()
            commands = [call.args[0][3:] for call in run.call_args_list]
            video_copy = ["push", "--sync", str(game / "video"), deploy.DEVICE_ROOT + "/game/"]
            override_copy = ["push", str(root / "config/video/intro_a1.xml"), deploy.DEVICE_ROOT + "/game/video/intro_a1.xml"]
            self.assertEqual(commands.count(override_copy), 1)
            self.assertGreater(commands.index(override_copy), commands.index(video_copy))
            self.assertEqual((game / "video/intro_a1.xml").read_bytes(), b"licensed original intro playlist")
            self.assertEqual((game / "video/outro_a1.xml").read_bytes(), b"licensed original outro playlist")
            self.assertEqual((game / "profiles/start.cfg").read_text(), "mainmenu\n")
            music_copy = ["push", str(root / "build/deploy/data" / music_path.name), deploy.DEVICE_ROOT + "/game/data/" + music_path.name]
            self.assertGreater(commands.index(music_copy), commands.index(override_copy))
            self.assertGreater(commands.index(music_copy), commands.index(["push", "--sync", str(game / "data"), deploy.DEVICE_ROOT + "/game/"]))
            self.assertEqual((game / "data/data.pak").read_bytes(), original_data)
            receipt = json.loads((root / "build/deploy-receipt.json").read_text())
            self.assertEqual(receipt["verified_sha256"][music_copy[-1]], music_receipt["sha256"])
            self.assertTrue(receipt["town_music_override"]["runtime_verification"].startswith("pending:"))

    def test_bad_music_input_stops_before_any_device_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.registry(root)
            music_inputs(root)
            manifest_path = root / "config/music/manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["Haven.(Music).xdb"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest))
            with patch.object(deploy, "ROOT", root), patch.object(deploy, "PORT", {"game_directory": "original-game"}), \
                    patch("sys.argv", ["deploy.py", "--data", "--serial", "TEST_DEVICE"]), \
                    patch.object(deploy.subprocess, "run") as run, \
                    patch.object(deploy, "validate_packaged_native", return_value={}):
                with self.assertRaisesRegex(ValueError, "canonical input changed"):
                    deploy.main()
                run.assert_not_called()

    def test_checks_real_device_bytes_and_records_success_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.registry(root)
            (root / "generated/input").mkdir(parents=True)
            (root / "config/modules.json").write_text('[{"file":"game.exe"}]')
            data = b"a private mapped PE image"
            (root / "generated/input/game.exe").write_bytes(data)
            with patch.object(deploy, "ROOT", root), patch("sys.argv", ["deploy.py", "--serial", "TEST_DEVICE"]), \
                    patch.object(deploy.subprocess, "run") as run, \
                    patch.object(deploy.subprocess, "check_output", return_value="0" * 64 + " file\n") as checksum, \
                    patch.object(deploy, "validate_packaged_native", return_value={}):
                with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                    deploy.main()
                self.assertFalse((root / "build/deploy-receipt.json").exists())
                checksum.side_effect = self.device_checksum(run)
                deploy.main()
                self.assertIn(hashlib.sha256(data).hexdigest(), (root / "build/deploy-receipt.json").read_text())
                self.assertTrue(all(call.args[0][1:3] == ["-s", "TEST_DEVICE"] for call in run.call_args_list))

    def test_three_editions_select_matching_banks_images_profiles_and_isolated_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.registry(root)
            settings = {"game_directory": "original-toe", "editions": {
                edition: {"game_directory": "original-combined"} for edition in ("vanilla", "hof")}}
            (root / "port.json").write_text(json.dumps(settings))
            (root / "config/video").mkdir()
            (root / "config/video/intro_a1.xml").write_bytes(b"<Base><Movies/></Base>")
            for edition in deploy.EDITION_IDS:
                spec = deploy.edition_spec(edition, root)
                game = deploy.game_directory(edition, root)
                for name in [spec["bin"], *spec["data"], "video", "profiles/default_profile", "music"]:
                    folder = game / name
                    folder.mkdir(parents=True, exist_ok=True)
                    (folder / "licensed-original").write_bytes((edition + name).encode())
                suffix = spec["profile_suffix"]
                (game / ("profiles/autoexec" + suffix + ".cfg")).write_bytes(b"native_bootstrap 73\r\n")
                values = b"".join(("setvar " + name + " = 1\r\n").encode() for name in (
                    "Options.Tooltips.HoverTimeout", "app_always_active", "gfx_dynamic_lights", "gfx_noshadows",
                    "gfx_resolution", "gfx_water_reflection"))
                (game / ("profiles/default_profile/user" + suffix + ".cfg")).write_bytes(values)
                if edition == "toe":
                    for relative in ("profiles/autoexec_a2.cfg", "profiles/default_profile/user_a2.cfg"):
                        (root / "config" / relative).parent.mkdir(parents=True, exist_ok=True)
                        (root / "config" / relative).write_bytes((game / relative).read_bytes())
                manifest = root / spec["modules"]
                manifest.write_text(json.dumps([{"file": edition + ".exe"}]))
                image = deploy.generated_root(edition, root) / "input" / (edition + ".exe")
                image.parent.mkdir(parents=True, exist_ok=True)
                image.write_bytes(("private prepared image " + edition).encode())
                self.runtime(root, edition)
            original = {path: path.read_bytes() for folder in (root / "original-toe", root / "original-combined")
                        for path in folder.rglob("*") if path.is_file()}
            def music_override(project, game=None, edition="toe"):
                path = project / ("build/music-fixture-" + edition) / "z_homm5_town_music.pak"
                path.parent.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("Sounds/_(Music)/Towns/Haven.(Music).xdb", ("patched town music " + edition).encode())
                return path, {"edition": edition, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            receipts = {}
            for edition in deploy.EDITION_IDS:
                with self.subTest(edition=edition), patch.object(deploy, "ROOT", root), \
                        patch("sys.argv", ["deploy.py", "--edition", edition, "--data", "--serial", "TEST_DEVICE"]), \
                        patch.object(deploy, "build_town_music_override", side_effect=music_override), \
                        patch.object(deploy, "build_port_ui_override", side_effect=self.ui_override), \
                        patch.object(deploy, "validate_packaged_native", return_value={"edition": edition}) as native, \
                        patch.object(deploy, "validate_overlay", return_value={"edition": edition}) as overlay, \
                        patch.object(deploy.subprocess, "run") as run, \
                        patch.object(deploy.subprocess, "check_output", side_effect=self.device_checksum(run)) as checksum:
                    deploy.main()
                spec = deploy.edition_spec(edition, root)
                suffix = spec["assets_suffix"]
                game = deploy.game_directory(edition, root)
                commands = [call.args[0][3:] for call in run.call_args_list]
                banks = [Path(command[2]).name for command in commands if command[:2] == ["push", "--sync"]
                         and Path(command[2]).parent == game]
                self.assertIn(spec["bin"], banks)
                self.assertTrue(all(name in banks for name in spec["data"]))
                self.assertEqual("DataLS" in banks, edition == "vanilla")
                self.assertEqual("dataa1" in banks, edition == "hof")
                binary = deploy.build_root(edition, root=root) / (spec["library"].replace("_", "-") + "-arm64")
                native.assert_any_call(edition, binary, root=root)
                self.assertEqual(native.call_count, 2)
                overlay.assert_called_once_with(edition, root / ("build/deploy" + suffix), root=root)
                receipt = json.loads((root / ("build/deploy-receipt" + suffix + ".json")).read_text())
                self.assertEqual(receipt["overlay_patches"], {"edition": edition})
                self.assertEqual(receipt["edition"], edition)
                self.assertEqual(receipt["userdata"], deploy.DEVICE_ROOT + "/" + spec["userdata"])
                self.assertEqual(receipt["images"], deploy.DEVICE_ROOT + "/lifted" + suffix)
                self.assertEqual(receipt["command"][2:], [receipt["game"], "--data", receipt["userdata"], "--images", receipt["images"]])
                self.assertTrue(any(command[-1] == receipt["game"] + "/video/" + ("intro.xml" if edition == "vanilla" else "intro_a1.xml") for command in commands))
                # Inspect the actual ZIP payload independently: both legacy
                # engines need every loose member, while ToE keeps PAK-only.
                for folder in ("music-fixture-", "ui-fixture-"):
                    archive = next((root / ("build/" + folder + edition)).glob("*.pak"))
                    expected = {"data/" + archive.name: archive.read_bytes()}
                    if edition != "toe":
                        with zipfile.ZipFile(archive) as packed:
                            expected.update({"data/" + name: packed.read(name) for name in packed.namelist()})
                    for relative, contents in expected.items():
                        staged = root / ("build/deploy" + suffix) / relative
                        destination = receipt["game"] + "/" + relative
                        self.assertEqual(staged.read_bytes(), contents)
                        self.assertIn(["push", str(staged), destination], commands)
                        self.assertEqual(receipt["verified_sha256"][destination], hashlib.sha256(contents).hexdigest())
                        self.assertIn(["adb", "-s", "TEST_DEVICE", "shell", "sha256sum " + shlex.quote(destination)],
                                      [call.args[0] for call in checksum.call_args_list])
                ui_loose = receipt["game"] + "/data/UI/uiconsts.(UIGameConstsH5).xdb"
                self.assertEqual(ui_loose in receipt["verified_sha256"], edition != "toe")
                for path, contents in original.items():
                    self.assertEqual(path.read_bytes(), contents)
                for prior, contents in receipts.items():
                    self.assertEqual(prior.read_bytes(), contents)
                path = root / ("build/deploy-receipt" + suffix + ".json")
                receipts[path] = path.read_bytes()

    def test_real_overlay_gate_rejects_missing_or_changed_loose_resources_before_adb(self):
        import test_port_patch_contract
        import port_ui
        real_validator = deploy.validate_overlay
        for edition in ("vanilla", "hof"):
            for defect in (None, "missing", "stale"):
                with self.subTest(edition=edition, defect=defect), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.registry(root)
                    self.runtime(root, edition)
                    fixture, music, _ = test_port_patch_contract.OverlayContractTest().fixture(edition, root)
                    expected = real_validator(edition, fixture, root=root)
                    spec = deploy.edition_spec(edition, root)
                    game = root / "original"
                    for bank in (spec["bin"], *spec["data"]):
                        (game / bank).mkdir(parents=True)
                    (root / "port.json").write_text(json.dumps({"editions": {edition: {"game_directory": "original"}}}))
                    (root / spec["modules"]).write_text("[]")
                    (root / "config/video").mkdir()
                    (root / "config/video/intro_a1.xml").write_bytes(b"<Base><Movies/></Base>")
                    profiles = {path.relative_to(fixture).as_posix(): path.read_bytes()
                                for path in (fixture / "profiles").rglob("*.cfg")}

                    def validate_stage(selected, folder, root):
                        target = folder / "data" / port_ui.UICONSTS
                        if defect == "missing": target.unlink()
                        elif defect == "stale": target.write_bytes(b"unpatched original bank resource")
                        return real_validator(selected, folder, root=root)

                    with patch.object(deploy, "ROOT", root), \
                            patch("sys.argv", ["deploy.py", "--edition", edition, "--data", "--serial", "TEST_DEVICE"]), \
                            patch.object(deploy, "validate_packaged_native", return_value={}), \
                            patch.object(deploy, "build_town_music_override", return_value=(music, {})), \
                            patch.object(deploy, "build_port_ui_override", return_value=(fixture / "data" / port_ui.PAK_NAME, {})), \
                            patch.object(deploy, "bootstrap_profiles", return_value=profiles), \
                            patch.object(deploy, "validate_overlay", side_effect=validate_stage), \
                            patch.object(deploy.subprocess, "run") as run, \
                            patch.object(deploy.subprocess, "check_output", side_effect=self.device_checksum(run)) as checksum:
                        if defect:
                            with self.assertRaisesRegex(ValueError, "loose override"):
                                deploy.main()
                            run.assert_not_called()
                            checksum.assert_not_called()
                            self.assertFalse(list((root / "build").glob("deploy-receipt*.json")))
                        else:
                            deploy.main()
                            receipt = json.loads((root / ("build/deploy-receipt" + spec["assets_suffix"] + ".json")).read_text())
                            self.assertEqual(receipt["overlay_patches"], expected)

    def test_hostile_legacy_override_stops_before_any_device_operation(self):
        for edition in ("vanilla", "hof"):
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.registry(root)
                self.runtime(root, edition)
                (root / "port.json").write_text(json.dumps({"editions": {edition: {"game_directory": "original"}}}))
                music, _ = self.ui_override(root, edition=edition)
                hostile = root / "hostile.pak"
                with zipfile.ZipFile(hostile, "w") as archive:
                    archive.writestr("UI/valid.xdb", b"valid resource")
                    archive.writestr("../../profiles/default_profile/user.cfg", b"must not escape")
                with patch.object(deploy, "ROOT", root), \
                        patch("sys.argv", ["deploy.py", "--edition", edition, "--data"]), \
                        patch.object(deploy, "validate_packaged_native", return_value={}), \
                        patch.object(deploy, "build_town_music_override", return_value=(music, {})), \
                        patch.object(deploy, "build_port_ui_override", return_value=(hostile, {})), \
                        patch.object(deploy.subprocess, "run") as run, \
                        patch.object(deploy.subprocess, "check_output") as checksum:
                    with self.assertRaisesRegex(ValueError, "Invalid override resource path"):
                        deploy.main()
                    run.assert_not_called()
                    checksum.assert_not_called()
                    self.assertFalse(list((root / "build").glob("deploy-receipt*.json")))

    def test_invalid_native_receipt_stops_before_any_device_operation(self):
        for edition in deploy.EDITION_IDS:
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.registry(root)
                with patch.object(deploy, "ROOT", root), \
                        patch("sys.argv", ["deploy.py", "--edition", edition, "--data"]), \
                        patch.object(deploy, "validate_packaged_native", side_effect=ValueError("stale mandatory patches")) as native, \
                        patch.object(deploy.subprocess, "run") as run:
                    with self.assertRaisesRegex(ValueError, "stale mandatory patches"):
                        deploy.main()
                    self.assertEqual(native.call_args.args[0], edition)
                    run.assert_not_called()
                    self.assertFalse(list((root / "build").glob("deploy-receipt*.json")))

    def test_failed_ui_override_stops_before_any_device_operation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.registry(root)
            (root / "port.json").write_text('{"game_directory":"original"}')
            with patch.object(deploy, "ROOT", root), patch("sys.argv", ["deploy.py", "--data"]), \
                    patch.object(deploy, "validate_packaged_native", return_value={}), \
                    patch.object(deploy, "build_town_music_override", return_value=(Path("unused"), {})), \
                    patch.object(deploy, "build_port_ui_override", side_effect=ValueError("missing required UI input")), \
                    patch.object(deploy.subprocess, "run") as run:
                with self.assertRaisesRegex(ValueError, "missing required UI input"):
                    deploy.main()
                run.assert_not_called()

    def test_native_receipt_changed_during_copy_prevents_executable_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.registry(root)
            (root / "config/modules.json").write_text('[{"file":"game.exe"}]')
            image = root / "generated/input/game.exe"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"prepared image")
            receipt = root / "build/deploy-receipt.json"
            receipt.write_bytes(b"previous successful deployment")
            binary = deploy.build_root("toe", root=root) / "homm5-arm64"
            with patch.object(deploy, "ROOT", root), patch("sys.argv", ["deploy.py", "--serial", "TEST_DEVICE"]), \
                    patch.object(deploy, "validate_packaged_native", side_effect=[{}, ValueError("changed native receipt")]), \
                    patch.object(deploy.subprocess, "run") as run, \
                    patch.object(deploy.subprocess, "check_output", side_effect=self.device_checksum(run)):
                with self.assertRaisesRegex(ValueError, "changed native receipt"):
                    deploy.main()
                self.assertFalse(any(str(binary) in call.args[0] for call in run.call_args_list))
                self.assertEqual(receipt.read_bytes(), b"previous successful deployment")


if __name__ == "__main__":
    unittest.main()
