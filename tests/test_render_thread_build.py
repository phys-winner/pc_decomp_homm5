"""The render-thread includes must invalidate their host objects, including legacy builds."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from build_android import included_digest
from profile_cpu import validate_target, PACKAGE


class RenderThreadBuildTest(unittest.TestCase):
    def test_recursive_includes_and_unrelated_files(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "build") as directory:
            root = Path(directory)
            source = root / "d3d9_gl.c"
            source.write_text('#include "thread.inc"\n')
            (root / "thread.inc").write_text('#include "check.inc"\n')
            check = root / "check.inc"
            check.write_text("first\n")
            before = included_digest(source)
            (root / "unrelated.inc").write_text("not included\n")
            self.assertEqual(included_digest(source), before)
            check.write_text("second\n")
            self.assertNotEqual(included_digest(source), before)
            # Real legacy host sources are copied elsewhere after this digest is taken.
            self.assertTrue(included_digest(ROOT / "android/host/d3d9_gl.c"))

    def test_profiler_rejects_other_processes_and_uids(self):
        status = "Uid:\t1234\t1234\t1234\t1234\n"
        validate_target(PACKAGE.encode() + b"\0", status, 1234)
        for command, ids in ((b"another.app\0", status),
                             (PACKAGE.encode() + b"\0", "Uid:\t1234\t5678\t1234\t1234\n")):
            with self.assertRaises(ValueError):
                validate_target(command, ids, 1234)


if __name__ == "__main__":
    unittest.main()
