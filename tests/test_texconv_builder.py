"""A newer cached converter must never bypass the current texture patches."""
from contextlib import contextmanager, redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


class TexconvBuilderTest(unittest.TestCase):
    @contextmanager
    def fixture(self, failure=None):
        spec = importlib.util.spec_from_file_location("texconv_builder_fixture", ROOT / "tools/build_texconv.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="homm5-texconv-builder-") as temporary:
            root = Path(temporary)
            out = root / "build/arm64-texconv"
            library = out / "libtexconv.so"
            calls = {"compile": [], "link": []}
            with patch.multiple(module, ROOT=root, OUT=out, LIBRARY=library, CXX=root / "clang++.exe"):
                # The actual source enumerator must include both port units and
                # every dependency unit. Keep just one ASTC unit in this fixture.
                astc = root / "reference/astcenc/astcenc_fixture.cpp"
                astc.parent.mkdir(parents=True)
                astc.write_bytes(b"current ASTC unit")
                for relative in ("android/texconv/texconv.h", "tools/build_android.py"):
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"current build input")
                units = module.units()
                for source, _ in units:
                    source.parent.mkdir(parents=True, exist_ok=True)
                    source.write_bytes(b"current source: " + source.name.encode())
                    obj = out / "obj" / (source.parent.name + "_" + source.stem + ".o")
                    obj.parent.mkdir(parents=True, exist_ok=True)
                    obj.write_bytes(b"stale object")
                    future = time.time() + 86400
                    os.utime(obj, (future, future))
                library.write_bytes(b"stale library without required texture patches")
                os.utime(library, (future + 1, future + 1))

                def run(command, **kwargs):
                    command = list(map(str, command))
                    self.assertEqual(command[0], str(root / "clang++.exe"))
                    self.assertTrue(kwargs.get("capture_output"))
                    self.assertTrue(kwargs.get("text"))
                    destination = Path(command[command.index("-o") + 1])
                    self.assertTrue(destination.is_relative_to(out))
                    if "-c" in command:
                        source = Path(command[command.index("-c") + 1])
                        calls["compile"].append(command)
                        if failure == "compile" and source.name == "texconv_jni.cpp":
                            return subprocess.CompletedProcess(command, 1, "", "compiler failure")
                        destination.write_bytes(b"compiled: " + source.read_bytes())
                    else:
                        calls["link"].append(command)
                        if failure == "link":
                            return subprocess.CompletedProcess(command, 1, "", "linker failure")
                        objects = [Path(arg) for arg in command if arg.endswith(".o")]
                        self.assertEqual(set(objects), {
                            out / "obj" / (source.parent.name + "_" + source.stem + ".o")
                            for source, _ in units})
                        self.assertTrue(all(obj.read_bytes().startswith(b"compiled: ") for obj in objects))
                        destination.write_bytes(b"current library: " + b"|".join(obj.read_bytes() for obj in objects))
                    return subprocess.CompletedProcess(command, 0, "", "")

                with patch.object(module.subprocess, "run", side_effect=run), redirect_stdout(io.StringIO()):
                    yield module, library, units, calls

    def test_future_objects_and_library_are_recompiled_and_relinked_on_every_invocation(self):
        with self.fixture() as (module, library, units, calls):
            self.assertEqual(len(units), 7)
            for invocation in range(1, 3):
                module.main()
                self.assertEqual(len(calls["compile"]), invocation * len(units))
                self.assertEqual(len(calls["link"]), invocation)
                self.assertTrue(library.read_bytes().startswith(b"current library: "))
            link = calls["link"][-1]
            for flag in ("-shared", "-static-libstdc++", "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384"):
                self.assertIn(flag, link)

    def test_compile_failure_stops_before_link_and_preserves_previous_library(self):
        with self.fixture(failure="compile") as (module, library, _, calls):
            before = library.read_bytes()
            with self.assertRaisesRegex(SystemExit, "texconv_jni.cpp: compiler failure"):
                module.main()
            self.assertFalse(calls["link"])
            self.assertEqual(library.read_bytes(), before)

    def test_link_failure_is_not_reported_as_success(self):
        with self.fixture(failure="link") as (module, _, units, calls):
            with self.assertRaisesRegex(SystemExit, "link: linker failure"):
                module.main()
            self.assertEqual(len(calls["compile"]), len(units))
            self.assertEqual(len(calls["link"]), 1)


if __name__ == "__main__":
    unittest.main()
