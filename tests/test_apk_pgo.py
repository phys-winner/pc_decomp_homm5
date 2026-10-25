"""Exercise the real APK entry point with fake SDK tools and distinct libraries."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
TEXCONV = b"texture-converter-library"
LIFTED = b"lifted PE image"
# The overlay's data archives come from their own builders (tests/test_town_music.py and
# tools/port_ui.py, which needs the installed game); here they are distinct stand-ins.
OVERRIDES = {"town_music": ("build_town_music_override", "z_homm5_android_town_music.pak", b"music-override"),
             "port_ui": ("build_port_ui_override", "z_homm5_android_ui.pak", b"ui-override")}


class ApkPGORoutingTest(unittest.TestCase):
    @contextmanager
    def fixture(self):
        spec = importlib.util.spec_from_file_location("apk_pgo_fixture", ROOT / "tools/build_game_apk.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="homm5-apk-pgo-") as directory:
            root = Path(directory).resolve()
            out = root / "build/android-game"
            inputs = {
                "config/modules.json": json.dumps([{"name": "game", "file": "game.exe"}]).encode(),
                "generated/game-x86/report.json": b'{"status":"GENERATED"}',
                "generated/input/game.exe": LIFTED,
                "config/profiles/autoexec_a2.cfg": b"exec profiles\\start.cfg\n",
                "config/profiles/default_profile/user_a2.cfg": b"setvar port = 1\n",
                "config/video/intro_a1.xml": b"<Base><Movies/></Base>",
                "android/app/src/Example.java": b"class Example {}",
                "build/android/debug.keystore": b"fake-debug-key",
            }
            inputs.update({relative: (ROOT / relative).read_bytes() for relative in module.LICENSE_FILES.values()})
            inputs.update({"sdk/" + relative: b"fake SDK tool" for relative in (
                "build-tools/aapt2.exe", "build-tools/d8.bat", "build-tools/zipalign.exe",
                "build-tools/apksigner.bat", "android.jar")})
            inputs.update({"jdk/bin/" + name: b"fake JDK tool" for name in ("javac.exe", "keytool.exe")})
            for relative, data in inputs.items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(data)
            out.mkdir(parents=True)
            (out / "keep-until-valid-library").write_bytes(b"previous-apk")
            native_calls, sdk_calls, removed = [], [], []
            real_rmtree = shutil.rmtree

            def native_run(argv, **kwargs):
                self.assertTrue(kwargs.get("check"))
                native_calls.append([str(a) for a in argv])
                if Path(argv[1]).name == "build_texconv.py":
                    library = root / "build/arm64-texconv/libtexconv.so"
                    library.parent.mkdir(parents=True, exist_ok=True)
                    library.write_bytes(TEXCONV)
                return subprocess.CompletedProcess(argv, 0)

            def sdk_run(*argv, **kwargs):
                self.assertNotIn("adb", str(argv[0]).lower())
                sdk_calls.append(tuple(str(a) for a in argv))
                tool = Path(argv[0]).name
                if tool == "aapt2.exe":
                    with zipfile.ZipFile(argv[argv.index("-o") + 1], "w") as archive:
                        archive.writestr("AndroidManifest.xml", b"fake-manifest")
                        if "-A" in argv:   # aapt2 link stores the asset folder under assets/
                            assets = Path(argv[argv.index("-A") + 1])
                            for path in sorted(p for p in assets.rglob("*") if p.is_file()):
                                archive.write(path, "assets/" + path.relative_to(assets).as_posix())
                elif tool == "javac.exe":
                    (Path(argv[argv.index("-d") + 1]) / "Example.class").write_bytes(b"fake-class")
                elif tool == "d8.bat":
                    self.assertFalse(kwargs.get("shell"))
                    (Path(argv[argv.index("--output") + 1]) / "classes.dex").write_bytes(b"fake-dex")
                elif tool == "zipalign.exe":
                    shutil.copyfile(argv[-2], argv[-1])
                elif tool == "apksigner.bat":
                    shutil.copyfile(argv[-1], argv[argv.index("--out") + 1])
                else:
                    self.fail("Unexpected SDK operation: " + tool)
                return subprocess.CompletedProcess(argv, 0, "", "")

            def safe_rmtree(path, *args, **kwargs):
                target = Path(path).resolve()
                self.assertTrue(target.is_relative_to(root))
                self.assertEqual(target, out.resolve())
                removed.append(target)
                return real_rmtree(path, *args, **kwargs)

            def override(name, payload):
                def build(base):
                    self.assertEqual(Path(base), root)
                    path = root / "build/data-overrides" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(payload)
                    return path, {"pak": name}
                return build

            builders = {}
            for module_name, (function, name, payload) in OVERRIDES.items():
                builders[module_name] = types.ModuleType(module_name)
                setattr(builders[module_name], function, override(name, payload))

            with ExitStack() as stack:
                stack.enter_context(patch.dict(module.os.environ, {"JAVA_HOME": str(root / "jdk")}))
                stack.enter_context(patch.multiple(module, ROOT=root, OUT=out, TOOLS=root / "sdk/build-tools",
                                                   ANDROID_JAR=root / "sdk/android.jar", JAVA_HOME=root / "jdk"))
                stack.enter_context(patch.object(module, "run", side_effect=sdk_run))
                stack.enter_context(patch.object(module.subprocess, "run", side_effect=native_run))
                stack.enter_context(patch.object(module.shutil, "rmtree", side_effect=safe_rmtree))
                stack.enter_context(patch.dict(sys.modules, builders))
                stack.enter_context(patch.object(sys, "path", list(sys.path)))   # stage_assets adds tools/
                yield module, root, out, native_calls, sdk_calls, removed

    def library(self, root, mode, payload):
        path = root / "build" / mode / "libhomm5.so"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path

    def invoke(self, module, args):
        with patch.object(sys, "argv", ["build_game_apk.py", *args]), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            module.main()

    def texconv_call(self, root):
        return [sys.executable, str(root / "tools/build_texconv.py")]

    def packaged_library(self, out):
        with zipfile.ZipFile(out / "heroes-v.apk") as archive:
            self.assertEqual(archive.read("classes.dex"), b"fake-dex")
            # The launcher's texture converter ships beside the game library.
            self.assertEqual(archive.read("lib/arm64-v8a/libtexconv.so"), TEXCONV)
            return archive.read("lib/arm64-v8a/libhomm5.so")

    def test_resources_are_compiled_linked_and_java_is_utf8(self):
        with self.fixture() as (module, root, out, native, sdk, removed):
            resources = root / "android/app/res/values"
            resources.mkdir(parents=True)
            (resources / "colors.xml").write_text('<resources><color name="icon">#142230</color></resources>')
            self.library(root, "arm64", b"ordinary-library")
            self.invoke(module, ["--skip-native"])
            self.assertEqual(native, [self.texconv_call(root)])
            self.assertEqual(len(sdk), 6)
            compile_call, link_call = sdk[:2]
            self.assertEqual(compile_call[1], "compile")
            self.assertEqual(compile_call[compile_call.index("--dir") + 1], str(resources.parent))
            archive = str(out / "resources.zip")
            self.assertEqual(compile_call[compile_call.index("-o") + 1], archive)
            self.assertEqual(link_call[1], "link")
            self.assertIn(archive, link_call)
            self.assertNotIn("-R", link_call)
            self.assertEqual(link_call[link_call.index("-A") + 1], str(out / "assets"))
            javac = next(call for call in sdk if Path(call[0]).name == "javac.exe")
            self.assertEqual(javac[javac.index("-encoding") + 1], "UTF-8")
            self.assertEqual(self.packaged_library(out), b"ordinary-library")

    def test_assets_carry_lifted_images_overlay_and_intro_with_indexes(self):
        with self.fixture() as (module, root, out, native, sdk, removed):
            self.library(root, "arm64", b"ordinary-library")
            self.invoke(module, ["--skip-native"])
            with zipfile.ZipFile(out / "heroes-v.apk") as archive:
                files = {name: archive.read(name) for name in archive.namelist() if name.startswith("assets/")}

            def index(entries):
                # "path size sha256" a line, sorted (Assets.java copies by path; newline style is the host's).
                return [f"{name} {len(data)} {hashlib.sha256(data).hexdigest()}" for name, data in sorted(entries.items())]

            overlay = {"profiles/autoexec_a2.cfg": b"exec profiles\\start.cfg\n",
                       "profiles/default_profile/user_a2.cfg": b"setvar port = 1\n",
                       **{"data/" + name: payload for _, name, payload in OVERRIDES.values()}}
            self.assertEqual(files.pop("assets/lifted/index.txt").decode().splitlines(), index({"game.exe": LIFTED}))
            self.assertEqual(files.pop("assets/overlay/index.txt").decode().splitlines(), index(overlay))
            expected = {"assets/lifted/game.exe": LIFTED,
                        **{"assets/overlay/" + name: data for name, data in overlay.items()},
                        **{"assets/licenses/" + name: (ROOT / relative).read_bytes()
                           for name, relative in module.LICENSE_FILES.items()},
                        "assets/overlay-intro/intro_a1.xml": b"<Base><Movies/></Base>"}
            self.assertEqual(files, expected)

    def test_texture_converter_failure_preserves_previous_apk_directory(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"ordinary-library")

                def failing_run(argv, **kwargs):
                    self.assertTrue(kwargs.get("check"))
                    native.append([str(a) for a in argv])
                    if Path(argv[1]).name == "build_texconv.py":
                        raise subprocess.CalledProcessError(1, argv)
                    return subprocess.CompletedProcess(argv, 0)

                with patch.object(module.subprocess, "run", side_effect=failing_run):
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.invoke(module, ["--skip-native"] if skip else [])
                self.assertEqual(native[-1], self.texconv_call(root))
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual((sdk, removed), ([], []))

    def test_generate_forwards_flag_and_packages_instrumented_library(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"ordinary-library-must-not-be-used")
                self.library(root, "arm64-pgogen", b"instrumented-library")
                self.invoke(module, ["--pgo-generate", *(["--skip-native"] if skip else [])])
                self.assertEqual(self.packaged_library(out), b"instrumented-library")
                self.assertEqual(len(native), 1 if skip else 2)
                self.assertEqual(native[-1], self.texconv_call(root))
                if not skip:
                    self.assertEqual(native[0], [sys.executable, str(root / "tools/build_android.py"),
                                                 "--shared", "--jobs", "12", "--pgo-generate"])
                self.assertEqual(len(sdk), 5)
                self.assertEqual(removed, [out])

    def test_use_and_disabled_pgo_keep_ordinary_library_directory(self):
        for flag in (None, "--pgo-use", "--no-pgo"):
            with self.subTest(flag=flag), self.fixture() as (module, root, out, native, _, _):
                self.library(root, "arm64", b"ordinary-library")
                self.library(root, "arm64-pgogen", b"wrong-instrumented-library")
                profile = root / "trained profile.profdata"
                profile.write_bytes(b"profile")
                options = [flag, str(profile)] if flag == "--pgo-use" else [flag] if flag else []
                self.invoke(module, options)
                self.assertEqual(self.packaged_library(out), b"ordinary-library")
                self.assertEqual(native, [[sys.executable, str(root / "tools/build_android.py"),
                                           "--shared", "--jobs", "12", *options], self.texconv_call(root)])

    def test_upstream_suffix_order_matches_native_builder(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, _, _):
                self.library(root, "arm64", b"wrong-ordinary")
                self.library(root, "arm64-pgogen", b"wrong-partial-mode")
                self.library(root, "arm64-globalregs-volatilemem-pgogen", b"combined-instrumented")
                flags = ["--global-regs", "--volatile-memory", "--pgo-generate"]
                self.invoke(module, [*flags, *(["--skip-native"] if skip else [])])
                self.assertEqual(self.packaged_library(out), b"combined-instrumented")
                self.assertEqual(len(native), 1 if skip else 2)
                if not skip:
                    self.assertEqual(native[0][-3:], flags)

    def test_conflicting_modes_preserve_previous_apk_directory(self):
        for flags in (("--pgo-generate", "--no-pgo"),
                      ("--pgo-generate", "--pgo-use", "unused.profdata"),
                      ("--no-pgo", "--pgo-use", "unused.profdata")):
            with self.subTest(flags=flags), self.fixture() as (module, _, out, native, sdk, removed):
                with self.assertRaises(SystemExit) as error:
                    self.invoke(module, ["--skip-native", *flags])
                self.assertEqual(error.exception.code, 2)
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual((native, sdk, removed), ([], [], []))

    def test_missing_selected_library_never_cleans_previous_apk(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"ordinary-is-not-the-selected-pgo-library")
                with self.assertRaises(SystemExit) as error:
                    self.invoke(module, ["--pgo-generate", *(["--skip-native"] if skip else [])])
                self.assertIn("libhomm5.so", str(error.exception))
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual(len(native), 0 if skip else 1)   # no texture converter build either
                self.assertEqual((sdk, removed), ([], []))


if __name__ == "__main__":
    unittest.main()
