"""Run the APK entry point with fake SDK tools and distinct SO files."""
from contextlib import contextmanager
import importlib.abc
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PROPOSED = ROOT / "tools/build_game_apk.py"
_spec = importlib.util.spec_from_file_location("thinlto_pgo_fixture_base", ROOT / "tests/test_apk_pgo.py")
pgo_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pgo_tests)


class ProposalLoader(importlib.abc.Loader):
    def create_module(self, spec):
        return None

    def exec_module(self, module):
        original = ROOT / "tools/build_game_apk.py"
        module.__file__ = str(original)
        exec(compile(PROPOSED.read_text(encoding="utf-8"), str(original), "exec"), module.__dict__)


class ThinLtoRoutingTest(pgo_tests.ApkPGORoutingTest):
    @contextmanager
    def fixture(self):
        original_spec = importlib.util.spec_from_file_location

        def proposed_spec(name, location, *args, **kwargs):
            if Path(location).resolve() == ROOT / "tools/build_game_apk.py":
                return original_spec(name, location, loader=ProposalLoader())
            return original_spec(name, location, *args, **kwargs)

        with patch.object(pgo_tests.importlib.util, "spec_from_file_location", side_effect=proposed_spec):
            with super().fixture() as values:
                yield values

    def test_thinlto_native_and_skip_select_the_same_distinct_library(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"wrong-ordinary")
                self.library(root, "arm64-pgogen", b"wrong-profile-mode")
                self.library(root, "arm64-thinlto", b"thinlto-library")
                self.invoke(module, ["--thinlto", *(["--skip-native"] if skip else [])])
                self.assertEqual(self.packaged_library(out), b"thinlto-library")
                self.assertEqual(len(native), 1 if skip else 4)
                self.assertEqual(native[-1], self.texconv_call(root))
                if not skip:
                    self.assertEqual(native[:-1], self.native_commands(root, ["--thinlto"]))
                self.assertEqual(len(sdk), 5)
                self.assertEqual(removed, [out])

    def test_combined_generate_suffix_order_and_explicit_thread_limit(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, _, _):
                self.library(root, "arm64-globalregs-volatilemem-pgogen", b"wrong-without-lto")
                self.library(root, "arm64-globalregs-volatilemem-thinlto", b"wrong-without-instrumentation")
                self.library(root, "arm64-globalregs-volatilemem-pgogen-thinlto", b"all-modes")
                flags = ["--global-regs", "--volatile-memory", "--pgo-generate", "--thinlto"]
                self.invoke(module, [*flags, "--thinlto-jobs", "3", *(["--skip-native"] if skip else [])])
                self.assertEqual(self.packaged_library(out), b"all-modes")
                self.assertEqual(len(native), 1 if skip else 4)
                self.assertEqual(native[-1], self.texconv_call(root))
                if not skip:
                    self.assertEqual(native[:-1], self.native_commands(root, [*flags, "--thinlto-jobs", "3"]))

    def test_thinlto_use_and_no_pgo_keep_suffix_and_forward_exact_arguments(self):
        for mode in ("--pgo-use", "--no-pgo"):
            for skip in (False, True):
                with self.subTest(mode=mode, skip_native=skip), self.fixture() as (module, root, out, native, _, _):
                    self.library(root, "arm64", b"wrong-ordinary")
                    self.library(root, "arm64-pgogen-thinlto", b"wrong-instrumentation")
                    self.library(root, "arm64-thinlto", b"profiled-or-unprofiled-lto")
                    profile = root / "trained profile.profdata"
                    profile.write_bytes(b"profile")
                    pgo_flags = [mode, str(profile)] if mode == "--pgo-use" else [mode]
                    self.invoke(module, ["--thinlto", *pgo_flags, "--thinlto-jobs", "2",
                                         *(["--skip-native"] if skip else [])])
                    self.assertEqual(self.packaged_library(out), b"profiled-or-unprofiled-lto")
                    self.assertEqual(len(native), 1 if skip else 4)
                    self.assertEqual(native[-1], self.texconv_call(root))
                    if not skip:
                        self.assertEqual(native[:-1], self.native_commands(root, ["--thinlto", *pgo_flags, "--thinlto-jobs", "2"]))

    def test_invalid_thread_options_preserve_existing_apk_before_any_work(self):
        for flags in (["--thinlto-jobs", "2"], ["--thinlto-jobs", "0"],
                      ["--thinlto", "--thinlto-jobs", "0"],
                      ["--thinlto", "--thinlto-jobs", "-1"],
                      ["--thinlto", "--thinlto-jobs", "not-an-int"]):
            with self.subTest(flags=flags), self.fixture() as (module, _, out, native, sdk, removed):
                with self.assertRaises(SystemExit) as error:
                    self.invoke(module, flags)
                self.assertEqual(error.exception.code, 2)
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual((native, sdk, removed), ([], [], []))

    def test_missing_selected_thin_library_preserves_existing_apk(self):
        for skip in (False, True):
            with self.subTest(skip_native=skip), self.fixture() as (module, root, out, native, sdk, removed):
                self.library(root, "arm64", b"ordinary-is-not-selected")
                self.library(root, "arm64-pgogen-thinlto", b"instrumented-is-not-selected")
                with self.assertRaises(SystemExit) as error:
                    self.invoke(module, ["--thinlto", *(["--skip-native"] if skip else [])])
                self.assertIn("arm64-thinlto", str(error.exception))
                self.assertEqual((out / "keep-until-valid-library").read_bytes(), b"previous-apk")
                self.assertEqual(len(native), 0 if skip else 3)   # no texture converter build either
                self.assertEqual((sdk, removed), ([], []))


if __name__ == "__main__":
    unittest.main()
