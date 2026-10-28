"""Exercise the real APK entry point with fake SDK tools and distinct libraries."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import lzma
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
EDITIONS = json.loads((ROOT / "config/editions.json").read_text(encoding="utf-8"))
# The overlay's data archives come from their own builders (tests/test_town_music.py and
# tools/port_ui.py, which needs the installed game); here they are distinct stand-ins.
OVERRIDES = {"town_music": ("build_town_music_override", "z_homm5_android_town_music.pak", b"music-override"),
             "port_ui": ("build_port_ui_override", "z_homm5_android_ui.pak", b"ui-override")}
# Tribes of the East's DXVK renderer as tools/build_dxvk.py stages it (build/dxvk and its receipt).
DXVK_RUNTIME = {"libdxvk_d3d9.so": b"dxvk-d3d9", "libh5dxvk.so": b"dxvk-bridge", "libh5turnip.so": b"turnip-driver"}
DXVK_LICENSES = {"dxvk.txt": b"dxvk zlib notice", "turnip-mesa.txt": b"mesa note"}
DXVK_SOURCE = b"bridge source"


def dxvk_receipt():
    digest = lambda data: hashlib.sha256(data).hexdigest()
    return json.dumps({"sources": {"android/dxvk/bridge.cpp": digest(DXVK_SOURCE)},
                       "runtime": [{"name": n, "sha256": digest(d)} for n, d in DXVK_RUNTIME.items()],
                       "licenses": [{"name": n, "sha256": digest(d)} for n, d in DXVK_LICENSES.items()]}).encode()


def resource_name(name):
    return ('UI/' if name.endswith('_ui.pak') else 'Sounds/') + 'fixture.xdb'


def override_payload(name, payload, edition):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        archive.writestr(zipfile.ZipInfo(resource_name(name), (2026, 1, 1, 0, 0, 0)),
                         payload + (b'' if edition == 'toe' else edition.encode()))
    return data.getvalue()


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
                "config/editions.json": (ROOT / "config/editions.json").read_bytes(),
                "config/modules.json": json.dumps([{"name": "game", "file": "game.exe"}]).encode(),
                "generated/game-x86/report.json": b'{"status":"GENERATED"}',
                "generated/input/game.exe": LIFTED,
                "config/profiles/autoexec_a2.cfg": b"exec profiles\\start.cfg\n",
                "config/profiles/default_profile/user_a2.cfg": b"setvar port = 1\n",
                "config/video/intro_a1.xml": b"<Base><Movies/></Base>",
                "android/app/src/Example.java": b"class Example {}",
                "build/android/debug.keystore": b"fake-debug-key",
                "android/dxvk/bridge.cpp": DXVK_SOURCE,
                "build/dxvk/build-receipt.json": dxvk_receipt(),
                **{"build/dxvk/runtime/" + name: data for name, data in DXVK_RUNTIME.items()},
                **{"build/dxvk/licenses/" + name: data for name, data in DXVK_LICENSES.items()},
            }
            for edition, row in EDITIONS.items():
                if edition == "toe":
                    continue
                inputs[row["modules"]] = json.dumps([{"name": "game", "file": "game.exe"}]).encode()
                inputs[row["generated"] + "/game-x86/report.json"] = b'{"status":"GENERATED"}'
                inputs[row["generated"] + "/input/game.exe"] = LIFTED + edition.encode()
                suffix = row["profile_suffix"]
                inputs["original/profiles/autoexec" + suffix + ".cfg"] = b"exec profiles\\start.cfg\n"
                inputs["original/profiles/default_profile/user" + suffix + ".cfg"] = b"".join(
                    ("setvar " + name + " = 1\n").encode() for name in (
                        "Options.Tooltips.HoverTimeout", "app_always_active", "gfx_dynamic_lights",
                        "gfx_noshadows", "gfx_resolution", "gfx_water_reflection"))
            inputs["port.json"] = json.dumps({"game_directory": str(root / "original"),
                "editions": {edition: {"game_directory": str(root / "original")}
                             for edition in EDITIONS if edition != "toe"}}).encode()
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
                self.assertNotIn(Path(argv[0]).name.lower(), ("adb", "adb.exe"))
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
                if target != out.resolve():
                    self.assertEqual(target.parent, out.parent)
                    self.assertTrue(target.name.startswith("apk-assets-"))
                else:
                    removed.append(target)
                return real_rmtree(path, *args, **kwargs)

            def override(name, payload):
                def build(base, edition="toe"):
                    self.assertEqual(Path(base), root)
                    path = root / ("build/data-overrides" + EDITIONS[edition]["assets_suffix"]) / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(override_payload(name, payload, edition))
                    return path, {"pak": name}
                return build

            builders = {}
            for module_name, (function, name, payload) in OVERRIDES.items():
                builders[module_name] = types.ModuleType(module_name)
                setattr(builders[module_name], function, override(name, payload))
            patches = types.ModuleType("port_patches")

            def validate_native(edition, library, root):
                try:
                    receipt = json.loads(library.with_suffix(".patches.json").read_text())
                except (OSError, ValueError) as failure:
                    raise ValueError("Missing patch receipt") from failure
                if receipt != {"edition": edition, "native_sha256": hashlib.sha256(library.read_bytes()).hexdigest(), "mandatory": True}:
                    raise ValueError("Stale native patch receipt")
                return receipt

            def validate_overlay(edition, overlay, root):
                for _, name, payload in OVERRIDES.values():
                    expected = override_payload(name, payload, edition)
                    if (overlay / "data" / name).read_bytes() != expected:
                        raise ValueError("Missing resource patches")
                    if edition != 'toe':
                        self.assertEqual((overlay / 'data' / resource_name(name)).read_bytes(), payload + edition.encode())
                return {"edition": edition, "mandatory": True}

            patches.validate_packaged_native = validate_native
            patches.validate_overlay = validate_overlay
            builders["port_patches"] = patches

            with ExitStack() as stack:
                unpacker = root / "unpacker.so"
                unpacker.write_bytes(b"native-xz-decoder")
                stack.enter_context(patch.object(module, "build_unpacker", return_value=unpacker))
                def compress(library):
                    data = library.read_bytes()
                    packed = library.with_suffix(".xz")
                    packed.write_bytes(lzma.compress(data))
                    return packed, f"{library.name} {len(data)} {hashlib.sha256(data).hexdigest()} {module.CHUNK} {packed.stat().st_size}\n"
                stack.enter_context(patch.object(module, "compress_library", side_effect=compress))
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
        result = None
        for edition, row in EDITIONS.items():
            suffix = "" if edition == "toe" else "-" + edition
            directory = "arm64" + suffix + mode.removeprefix("arm64")
            path = root / "build" / directory / ("lib" + row["library"] + ".so")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload + (b"" if edition == "toe" else edition.encode()))
            path.with_suffix(".patches.json").write_text(json.dumps({"edition": edition, "native_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mandatory": True}))
            if edition == "toe":
                result = path
        return result

    def native_commands(self, root, flags=()):
        commands = []
        for edition in EDITIONS:
            selected = list(flags)
            if edition != "toe" and "--pgo-use" in selected:
                index = selected.index("--pgo-use")
                del selected[index:index + 2]
            commands.append([sys.executable, str(root / "tools/build_android.py"), "--shared", "--jobs", "12",
                             "--edition", edition, *selected])
        return commands

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
            self.assertEqual(archive.read("lib/arm64-v8a/libhomm5xz.so"), b"native-xz-decoder")
            # DXVK/Turnip support is commented out: its libraries come only with --dxvk.
            self.assertFalse([name for name in archive.namelist() if name.endswith(tuple(DXVK_RUNTIME))])
            original = lzma.decompress(archive.read("assets/native/libhomm5.so.xz"))
            for edition in ("vanilla", "hof"):
                self.assertEqual(lzma.decompress(archive.read("assets/native/lib" + EDITIONS[edition]["library"] + ".so.xz")), original + edition.encode())
            self.assertFalse(any(name.startswith("lib/") and "/libhomm5" in name and not name.endswith("libhomm5xz.so") for name in archive.namelist()))
            for row in archive.read("assets/native/index.txt").decode().splitlines():
                name, size, digest, chunk, packed = row.split()
                entry = archive.getinfo("assets/native/" + name + ".xz")
                data = lzma.decompress(archive.read(entry))
                self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                self.assertEqual((len(data), hashlib.sha256(data).hexdigest(), entry.file_size), (int(size), digest, int(packed)))
            return original

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
                files = {name: archive.read(name) for name in archive.namelist() if name.startswith("assets/") and not name.startswith("assets/native/")}

            def index(entries):
                # "path size sha256" a line, sorted (Assets.java copies by path; newline style is the host's).
                return [f"{name} {len(data)} {hashlib.sha256(data).hexdigest()}" for name, data in sorted(entries.items())]

            expected = {"assets/licenses/" + name: (ROOT / relative).read_bytes() for name, relative in module.LICENSE_FILES.items()}
            receipts = json.loads(files.pop("assets/edition-patches.json"))
            self.assertEqual(set(receipts), set(EDITIONS))
            for edition, row in EDITIONS.items():
                suffix = row["assets_suffix"]
                distinct = b"" if edition == "toe" else edition.encode()
                user = b"setvar port = 1\n" if edition == "toe" else (
                    b"setvar Options.Tooltips.HoverTimeout = 0\nsetvar app_always_active = 1\n"
                    b"setvar gfx_dynamic_lights = 0\nsetvar gfx_noshadows = 1\n"
                    b"setvar gfx_resolution = 1280x800\nsetvar gfx_water_reflection = 0\n")
                auto = b"setvar ubi_tracking_tool_enabled = 0\nexec profiles\\start.cfg\n"
                overlay = {"profiles/autoexec" + row["profile_suffix"] + ".cfg": auto,
                           "profiles/default_profile/user" + row["profile_suffix"] + ".cfg": user,
                           **{"data/" + name: override_payload(name, payload, edition) for _, name, payload in OVERRIDES.values()}}
                if edition != 'toe':
                    overlay.update({'data/' + resource_name(name): payload + distinct for _, name, payload in OVERRIDES.values()})
                self.assertEqual(files.pop("assets/lifted" + suffix + "/index.txt").decode().splitlines(), index({"game.exe": LIFTED + distinct}))
                self.assertEqual(files.pop("assets/overlay" + suffix + "/index.txt").decode().splitlines(), index(overlay))
                expected.update({"assets/lifted" + suffix + "/game.exe": LIFTED + distinct,
                                 **{"assets/overlay" + suffix + "/" + name: data for name, data in overlay.items()},
                                 "assets/overlay-intro" + suffix + "/" + ("intro.xml" if edition == "vanilla" else "intro_a1.xml"): b"<Base><Movies/></Base>"})
                self.assertEqual(receipts[edition]["overlay"], {"edition": edition, "mandatory": True})
            self.assertEqual(files, expected)

    def test_dxvk_is_packaged_only_on_request(self):
        with self.fixture() as (module, root, out, native, sdk, removed):
            self.library(root, "arm64", b"ordinary-library")
            self.invoke(module, ["--skip-native", "--dxvk"])
            with zipfile.ZipFile(out / "heroes-v.apk") as archive:
                # DXVK's libraries are extracted by the installer like the converter's.
                for name, data in DXVK_RUNTIME.items():
                    self.assertEqual(archive.read("lib/arm64-v8a/" + name), data)
                for name, data in DXVK_LICENSES.items():
                    self.assertEqual(archive.read("assets/licenses/" + name), data)
        with self.fixture() as (module, root, out, native, sdk, removed):
            self.library(root, "arm64", b"ordinary-library")
            (root / "build/dxvk/build-receipt.json").unlink()
            with self.assertRaises(SystemExit) as failure:
                self.invoke(module, ["--skip-native", "--dxvk"])
            self.assertIn("tools/build_dxvk.py", str(failure.exception))
            self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
            self.assertEqual((native, sdk, removed), ([], [], []))
            for args in (["--skip-native"], ["--skip-native", "--no-dxvk"]):
                self.invoke(module, args)
                with zipfile.ZipFile(out / "heroes-v.apk") as archive:
                    names = archive.namelist()
                self.assertFalse([name for name in names if name.endswith(tuple(DXVK_RUNTIME)) or name.endswith(tuple(DXVK_LICENSES))])
                self.assertIn("lib/arm64-v8a/libtexconv.so", names)

    def test_stale_or_changed_dxvk_stage_stops_packaging(self):
        for defect in ("source", "library", "license"):
            with self.subTest(defect=defect), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"ordinary-library")
                changed = {"source": "android/dxvk/bridge.cpp", "library": "build/dxvk/runtime/libh5dxvk.so",
                           "license": "build/dxvk/licenses/dxvk.txt"}[defect]
                (root / changed).write_bytes(b"edited after tools/build_dxvk.py")
                with self.assertRaises(SystemExit) as failure:
                    self.invoke(module, ["--skip-native", "--dxvk"])
                self.assertIn("DXVK", str(failure.exception))
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual((native, sdk, removed), ([], [], []))

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
                self.assertEqual(len(native), 1 if skip else 4)
                self.assertEqual(native[-1], self.texconv_call(root))
                if not skip:
                    self.assertEqual(native[:-1], self.native_commands(root, ["--pgo-generate"]))
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
                self.assertEqual(native, [*self.native_commands(root, options), self.texconv_call(root)])

    def test_upstream_suffix_order_matches_native_builder(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, _, _):
                self.library(root, "arm64", b"wrong-ordinary")
                self.library(root, "arm64-pgogen", b"wrong-partial-mode")
                self.library(root, "arm64-globalregs-volatilemem-pgogen", b"combined-instrumented")
                flags = ["--global-regs", "--volatile-memory", "--pgo-generate"]
                self.invoke(module, [*flags, *(["--skip-native"] if skip else [])])
                self.assertEqual(self.packaged_library(out), b"combined-instrumented")
                self.assertEqual(len(native), 1 if skip else 4)
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
                self.assertEqual(len(native), 0 if skip else 3)   # no texture converter build either
                self.assertEqual((sdk, removed), ([], []))

    def test_each_edition_library_and_fresh_mandatory_receipt_are_required(self):
        for edition, row in EDITIONS.items():
            for defect in ("missing-library", "missing-receipt", "stale-library", "missing-feature"):
                with self.subTest(edition=edition, defect=defect), self.fixture() as (module, root, out, native, sdk, removed):
                    self.library(root, "arm64", b"library")
                    directory = "arm64" + ("" if edition == "toe" else "-" + edition)
                    library = root / "build" / directory / ("lib" + row["library"] + ".so")
                    receipt = library.with_suffix(".patches.json")
                    if defect == "missing-library":
                        library.unlink()
                    elif defect == "missing-receipt":
                        receipt.unlink()
                    elif defect == "stale-library":
                        library.write_bytes(b"changed library without corresponding patch receipt")
                    else:
                        proof = json.loads(receipt.read_text())
                        proof["mandatory"] = False
                        receipt.write_text(json.dumps(proof))
                    with self.assertRaises(SystemExit):
                        self.invoke(module, ["--skip-native"])
                    self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                    self.assertEqual((native, sdk, removed), ([], [], []))

    def test_resource_patch_failure_preserves_previous_apk_for_every_edition(self):
        for edition in EDITIONS:
            with self.subTest(edition=edition), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"library")
                original = sys.modules["port_patches"].validate_overlay

                def validate(selected, overlay, root):
                    if selected == edition:
                        raise ValueError("mandatory army/control UI patch is missing")
                    return original(selected, overlay, root)

                with patch.object(sys.modules["port_patches"], "validate_overlay", side_effect=validate):
                    with self.assertRaises(SystemExit) as failure:
                        self.invoke(module, ["--skip-native"])
                self.assertIn("Mandatory resource patches", str(failure.exception))
                self.assertEqual(native, [self.texconv_call(root)])
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual((sdk, removed), ([], []))

    def test_missing_generation_for_later_edition_preserves_previous_apk(self):
        with self.fixture() as (module, root, out, native, sdk, removed):
            (root / EDITIONS["hof"]["generated"] / "game-x86/report.json").unlink()
            with self.assertRaises(SystemExit) as failure:
                self.invoke(module, ["--skip-native"])
            self.assertIn("hof/game", str(failure.exception))
            self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
            self.assertEqual((native, sdk, removed), ([], [], []))

    def test_library_changed_after_preflight_cannot_be_signed(self):
        with self.fixture() as (module, root, out, native, sdk, removed):
            self.library(root, "arm64", b"library")
            real_run = module.run

            def change_library(*argv, **kwargs):
                result = real_run(*argv, **kwargs)
                if Path(argv[0]).name == "d8.bat":
                    (root / "build/arm64-hof/libhomm5_hof.so").write_bytes(b"unvalidated replacement")
                return result

            with patch.object(module, "run", side_effect=change_library):
                with self.assertRaises(SystemExit) as failure:
                    self.invoke(module, ["--skip-native"])
            self.assertIn("native patches changed during packaging", str(failure.exception))
            self.assertFalse((out / "heroes-v.apk").exists())
            self.assertFalse(any(Path(call[0]).name == "apksigner.bat" for call in sdk))


if __name__ == "__main__":
    unittest.main()
