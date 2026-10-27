"""Run the native builder's real main/cache against a tiny fake toolchain."""
from contextlib import contextmanager, ExitStack, redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
PROPOSED = PROJECT / "tools/build_android.py"
sys.path.insert(0, str(PROJECT / "tools"))   # build_android.py imports its sibling transforms


def load_proposal():
    # The copy deliberately retains the production ROOT expression, so the
    # reviewable diff has no disposable-worktree plumbing. Only tests set __file__.
    module = types.ModuleType("thinlto_builder_proposal")
    module.__file__ = str(PROJECT / "tools/build_android.py")
    exec(compile(PROPOSED.read_text(encoding="utf-8"), module.__file__, "exec"), module.__dict__)
    return module


class ThinLTOBuilderTest(unittest.TestCase):
    @contextmanager
    def fixture(self):
        with tempfile.TemporaryDirectory(prefix="homm5-thinlto-") as directory:
            root = Path(directory).resolve()
            files = {
                "config/editions.json": (PROJECT / "config/editions.json").read_text(encoding="utf-8"),
                "config/modules.json": json.dumps([{"name": "fmod", "file": "fmod.dll", "base": 0}]),
                "generated/fmod-x86/report.json": json.dumps({"status": "GENERATED", "sources": ["fmod_0000.c"]}),
                "generated/fmod-x86/fmod_0000.c": "void sub_30000000(void) {}\n",
                "generated/fmod-x86/recomp_dispatch.c": "void (*dispatch)(void) = sub_30000000;\n",
                "generated/fmod-x86/recomp.h": "void sub_30000000(void);\n",
                "android/runtime/recomp_types.h": "typedef unsigned guest_t;\n",
                "android/host/host.h": "void host(void);\n",
                "android/host/host.c": "void host(void) {}\n",
                "reference/dlmalloc/malloc.c": "/* included by host */\n",
                "reference/mojoshader/mini.h": "void mini(void);\n",
                "reference/mojoshader/mini.c": "void mini(void) {}\n",
                "fake-clang.exe": "NDK clang 18 fixture\n",
            }
            for edition in ("vanilla", "hof"):
                files["config/" + edition + ".modules.json"] = files["config/modules.json"]
                for relative, content in list(files.items()):
                    if relative.startswith("generated/fmod-x86/"):
                        files[relative.replace("generated/", "generated/" + edition + "/", 1)] = content
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            records = {"compiles": [], "links": []}
            original_cwd = Path.cwd()

            def fake_run(argv, **kwargs):
                argv = [str(a) for a in argv]
                self.assertEqual(kwargs.get("cwd"), root)
                self.assertEqual(argv[0], str(root / "fake-clang.exe"))
                output = Path(argv[argv.index("-o") + 1])
                self.assertTrue(output.resolve().is_relative_to(root))
                if "-c" in argv:
                    source = Path(argv[argv.index("-c") + 1])
                    records["compiles"].append(argv)
                    # Real compile_one validates this object's hash on the next run.
                    output.write_bytes(json.dumps(argv).encode() + source.read_bytes())
                else:
                    records["links"].append(argv)
                    output.write_bytes(b"fake-linked-ELF")
                return subprocess.CompletedProcess(argv, 0, "", "")

            def invoke(options, generated_patch=None):
                module = load_proposal()
                def transformed(source, **unused):
                    if generated_patch is None:
                        return source, []
                    patched = module.OUT / "patched" / source.parent.name / source.name
                    patched.parent.mkdir(parents=True, exist_ok=True)
                    patched.write_bytes(source.read_bytes() + generated_patch)
                    return patched, []
                with ExitStack() as stack:
                    stack.enter_context(patch.multiple(module, ROOT=root, OUT=root / "build/arm64",
                        MODULES=("fmod",), MANIFEST=[{"name": "fmod", "file": "fmod.dll", "base": 0}],
                        CLANG=root / "fake-clang.exe", MOJO_SOURCES=["mini.c"]))
                    stack.enter_context(patch.object(module, "override_source", side_effect=transformed))
                    # The tiny fixture exercises compiler/cache behavior. The
                    # mandatory real-engine patch contract has separate tests.
                    stack.enter_context(patch("port_patches.validate_native_inputs", return_value={}))
                    stack.enter_context(patch("port_patches.finalize_native_receipt", return_value={}))
                    stack.enter_context(patch("port_patches.native_overrides", return_value=()))
                    stack.enter_context(patch("port_patches.adapt_host_source", side_effect=lambda source, *_: (source, [])))
                    stack.enter_context(patch.object(module.subprocess, "run", side_effect=fake_run))
                    stack.enter_context(patch.object(sys, "argv", ["build_android.py", "--jobs", "2", *options]))
                    stack.enter_context(redirect_stdout(io.StringIO()))
                    stack.enter_context(redirect_stderr(io.StringIO()))
                    try:
                        module.main()
                        return module.OUT
                    finally:
                        os.chdir(original_cwd)

            try:
                yield root, records, invoke
            finally:
                os.chdir(original_cwd)

    def test_all_translation_units_bitcode_with_original_semantics_and_bounded_link(self):
        with self.fixture() as (root, records, invoke):
            out = invoke(["--shared", "--thinlto", "--no-pgo"])
            self.assertEqual(out, root / "build/arm64-thinlto")
            self.assertEqual(len(records["compiles"]), 4)
            for command in records["compiles"]:
                for flag in ("-flto=thin", "-O2", "-fno-strict-aliasing", "-fwrapv", "-ffp-contract=off",
                             "-fno-math-errno", "-fvisibility=hidden", "-fPIC", "--target=aarch64-linux-android26"):
                    self.assertIn(flag, command)
                self.assertFalse(any("fast-math" in a or "whole-program-vtables" in a for a in command))
            generated = [c for c in records["compiles"] if "generated" in c[c.index("-c") + 1]]
            self.assertEqual(len(generated), 2)
            for command in generated:
                for flag in ("-DRECOMP_LOCAL_REGS", "-DRECOMP_PLAIN_MEMORY", "-DRECOMP_YIELD_EVERY=16384u",
                             "-DRECOMP_GUEST_STATE_SEPARATE", "-basic-aa-separate-storage", "-DRECOMP_GUEST_PROVENANCE"):
                    self.assertIn(flag, command)
                # Production generated code carries no per-entry trace (g_cur_func) stores.
                self.assertNotIn("-DRECOMP_TRACE", command)
                self.assertIn("-w", command)
                self.assertFalse(any(flag.startswith("-Werror=profile-instr-") for flag in command))
            host = next(c for c in records["compiles"] if "host.c" in c[c.index("-c") + 1])
            self.assertIn("-DVOID_ANDROID_APP", host)
            self.assertIn("-DRECOMP_TRACE", host)
            for command in records["compiles"]:
                if command not in generated:
                    self.assertNotIn("-DRECOMP_GUEST_STATE_SEPARATE", command)
                    self.assertNotIn("-basic-aa-separate-storage", command)
            link = records["links"][0]
            for flag in ("-flto=thin", "-Wl,--lto-O2", "-Wl,-mllvm,-basic-aa-separate-storage", "-Wl,--thinlto-jobs=4", "-Wl,--no-undefined",
                         "-Wl,--gc-sections", "-Wl,-z,nostart-stop-gc", "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1"):
                self.assertIn(flag, link)
            self.assertIn("-Wl,--thinlto-cache-dir=" + (out / "thin-cache").as_posix(), link)
            self.assertIn("-Wl,--thinlto-cache-policy=cache_size=0%:cache_size_bytes=4g:prune_interval=0s", link)
            self.assertTrue((out / "objects.json").is_file())
            self.assertTrue((out / "libhomm5.so").is_file())

    def test_combined_pgo_global_volatile_and_thinlto_directory_and_flags(self):
        with self.fixture() as (root, records, invoke):
            out = invoke(["--shared", "--global-regs", "--volatile-memory", "--pgo-generate", "--thinlto", "--thinlto-jobs", "2"])
            self.assertEqual(out, root / "build/arm64-globalregs-volatilemem-pgogen-thinlto")
            for command in records["compiles"]:
                self.assertIn("-flto=thin", command)
                self.assertNotIn("-DRECOMP_LOCAL_REGS", command)
                self.assertNotIn("-DRECOMP_PLAIN_MEMORY", command)
                generated = "generated" in command[command.index("-c") + 1]
                self.assertEqual("-fprofile-instr-generate" in command, generated)
                if generated:
                    self.assertIn("-w", command)
            self.assertIn("-fprofile-instr-generate", records["links"][0])
            self.assertIn("-Wl,--thinlto-jobs=2", records["links"][0])

    def test_real_object_cache_reuses_flags_and_backend_jobs_but_rejects_changed_profile(self):
        with self.fixture() as (root, records, invoke):
            profile = root / "profile with space.profdata"
            profile.write_bytes(b"training-v1")
            options = ["--shared", "--thinlto", "--pgo-use", str(profile)]
            out = invoke(options)
            self.assertEqual(len(records["compiles"]), 4)
            digest1 = hashlib.sha256(profile.read_bytes()).hexdigest()[:16]
            generated = [c for c in records["compiles"] if "generated" in c[c.index("-c") + 1]]
            for command in generated:
                self.assertIn("-DVOID_PGO_PROFILE_" + digest1, command)
                self.assertIn("-fprofile-instr-use=" + profile.as_posix(), command)
                self.assertNotIn("-w", command)
                self.assertIn("-Werror=profile-instr-out-of-date", command)
                self.assertIn("-Werror=profile-instr-unprofiled", command)
            for command in records["compiles"]:
                if command not in generated:
                    self.assertFalse(any(flag.startswith("-Werror=profile-instr-") for flag in command))
            invoke([*options, "--thinlto-jobs", "1"])
            self.assertEqual(len(records["compiles"]), 4, "changing only linker concurrency must reuse bitcode objects")
            self.assertIn("-Wl,--thinlto-jobs=1", records["links"][-1])
            profile.write_bytes(b"training-v2")
            invoke(options)
            self.assertEqual(len(records["compiles"]), 6, "profile digest invalidates generated objects, retaining host/Mojo policy")
            self.assertEqual(len(records["links"]), 3)
            self.assertEqual(out, root / "build/arm64-thinlto")

    def test_native_and_bitcode_outputs_isolated_and_tampered_object_not_reused(self):
        with self.fixture() as (root, records, invoke):
            native = invoke(["--shared", "--no-pgo"])
            original = {p.relative_to(native): p.read_bytes() for p in native.rglob("*.o")}
            self.assertEqual(native, root / "build/arm64")
            for command in records["compiles"]:
                self.assertNotIn("-flto=thin", command)
            thin = invoke(["--shared", "--thinlto", "--no-pgo"])
            self.assertEqual(len(records["compiles"]), 8)
            self.assertEqual({p.relative_to(native): p.read_bytes() for p in native.rglob("*.o")}, original)
            object_path = thin / "obj/fmod-x86/fmod_0000.o"
            object_path.write_bytes(b"wrong-native-or-corrupt-object")
            invoke(["--shared", "--thinlto", "--no-pgo"])
            self.assertEqual(len(records["compiles"]), 9)
            self.assertTrue(records["compiles"][-1][records["compiles"][-1].index("-c") + 1].endswith("fmod_0000.c"))

    def test_host_only_preserves_same_modes_generated_bitcode_objects(self):
        with self.fixture() as (_, records, invoke):
            options = ["--shared", "--thinlto", "--no-pgo"]
            out = invoke(options)
            before = (out / "obj/fmod-x86/fmod_0000.o").read_bytes()
            invoke([*options, "--host-only"])
            self.assertEqual(len(records["compiles"]), 4)
            self.assertEqual((out / "obj/fmod-x86/fmod_0000.o").read_bytes(), before)
            response = (out / "link.rsp").read_text()
            self.assertIn("obj/fmod-x86/fmod_0000.o", response)
            self.assertIn("obj/host-app/host.o", response)

    def test_host_only_rejects_stale_generated_inputs_or_objects_before_compiling_or_linking(self):
        for change in ("source", "module-header", "runtime-header", "compiler", "object", "cache", "dispatch", "profile"):
            with self.subTest(change=change), self.fixture() as (root, records, invoke):
                profile = root / "profile.profdata"
                profile.write_bytes(b"profile-v1")
                options = ["--shared", "--thinlto", "--pgo-use", str(profile)]
                out = invoke(options)
                library = out / "libhomm5.so"
                previous = library.read_bytes()
                files = {
                    "source": root / "generated/fmod-x86/fmod_0000.c",
                    "module-header": root / "generated/fmod-x86/recomp.h",
                    "runtime-header": root / "android/runtime/recomp_types.h",
                    "compiler": root / "fake-clang.exe",
                    "object": out / "obj/fmod-x86/fmod_0000.o",
                    "profile": profile,
                }
                if change in files:
                    path = files[change]
                    path.write_bytes(path.read_bytes() + b"\nchanged\n")
                elif change == "cache":
                    (out / "objects.json").unlink()
                else:
                    (out / "obj/fmod-x86/recomp_dispatch.o").unlink()
                with self.assertRaisesRegex(SystemExit, "run a full build without --host-only"):
                    invoke([*options, "--host-only"])
                self.assertEqual(len(records["compiles"]), 4)
                self.assertEqual(len(records["links"]), 1)
                self.assertEqual(library.read_bytes(), previous)

    def test_host_only_checks_current_generated_patch_output_and_excludes_orphan_objects(self):
        with self.fixture() as (_, records, invoke):
            options = ["--shared", "--thinlto", "--no-pgo"]
            out = invoke(options, generated_patch=b"\n/* native patch v1 */\n")
            orphan = out / "obj/fmod-x86/deleted_generated_function.o"
            orphan.write_bytes(b"old generated unit")
            invoke([*options, "--host-only"], generated_patch=b"\n/* native patch v1 */\n")
            self.assertNotIn(str(orphan).replace("\\", "/"), (out / "link.rsp").read_text())
            self.assertEqual(len(records["compiles"]), 4)
            self.assertEqual(len(records["links"]), 2)
            with self.assertRaisesRegex(SystemExit, "run a full build without --host-only"):
                invoke([*options, "--host-only"], generated_patch=b"\n/* native patch v2 */\n")
            self.assertEqual(len(records["compiles"]), 4)
            self.assertEqual(len(records["links"]), 2)

    def test_invalid_or_unenabled_backend_limits_fail_before_outputs(self):
        for options in (["--thinlto-jobs", "2"], ["--thinlto", "--thinlto-jobs", "0"],
                        ["--thinlto", "--thinlto-jobs", "-1"]):
            with self.subTest(options=options), self.fixture() as (root, records, invoke):
                with self.assertRaises(SystemExit) as error:
                    invoke(options)
                self.assertEqual(error.exception.code, 2)
                self.assertFalse((root / "build").exists())
                self.assertEqual(records, {"compiles": [], "links": []})

    def test_engines_have_private_descriptors_objects_and_libraries(self):
        with self.fixture() as (root, records, invoke):
            for edition, library, bin_dir, suffix in (("toe", "homm5", "bin", "_a2"),
                    ("vanilla", "homm5_vanilla", "bin", ""), ("hof", "homm5_hof", "bina1", "_a1")):
                with self.subTest(edition=edition):
                    out = invoke(["--shared", "--thinlto", "--no-pgo", "--edition", edition])
                    expected = "build/arm64" + ("-" + edition if edition != "toe" else "") + "-thinlto"
                    self.assertEqual(out, root / expected)
                    self.assertTrue((out / ("lib" + library + ".so")).is_file())
                    header = (out / "edition.h").read_text()
                    for name, value in (("HOMM5_EDITION", edition), ("HOMM5_BIN", bin_dir),
                            ("HOMM5_PROFILE_SUFFIX", suffix), ("HOMM5_MODULES_INCLUDE", (out / "modules.inc").as_posix())):
                        self.assertIn("#define " + name + " " + json.dumps(value), header)
                    # Source-size ordering can put host anywhere in the batch.
                    host = next(c for c in records["compiles"] if str(out / "obj/host-app/host.o") in c)
                    self.assertEqual(host[host.index("-include") + 1], str(out / "edition.h"))
            self.assertEqual(len(records["compiles"]), 12, "identical VAs must not reuse another engine's objects")
            self.assertFalse((root / "android/host/modules.inc").exists())

    def test_new_engine_rejects_toe_pgo_before_compiling(self):
        with self.fixture() as (root, records, invoke):
            profile = root / "build/pgo/homm5.profdata"
            profile.parent.mkdir(parents=True)
            profile.write_bytes(b"ToE training")
            for edition in ("vanilla", "hof"):
                with self.subTest(edition=edition), self.assertRaises(SystemExit):
                    invoke(["--edition", edition, "--pgo-use", str(profile)])
            self.assertEqual(records, {"compiles": [], "links": []})


if __name__ == "__main__":
    unittest.main()
