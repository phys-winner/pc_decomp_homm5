import importlib.util
from pathlib import Path
import sys
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))   # build_android.py imports its sibling transforms
spec = importlib.util.spec_from_file_location("build_android", ROOT / "tools/build_android.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuildGuards(unittest.TestCase):
    def test_native_target_matches_apk_minimum(self):
        manifest = ET.parse(ROOT / "android/app/AndroidManifest.xml").getroot()
        minimum = int(manifest.find("uses-sdk").get("{http://schemas.android.com/apk/res/android}minSdkVersion"))
        self.assertEqual(builder.API, minimum)
        self.assertEqual(builder.TARGET, f"aarch64-linux-android{minimum}")

    def test_window_rejects_pointer_escape_and_unsequenced_pop(self):
        for source in (b"double *saved = _st;", b"sink(&_st[0]);", b"_st[0] = fp_pop();",
                       b"fp_push(fp_pop());", b"g_st_i64[1] += fp_pop();"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                builder.guard_fpu_memory(source)
        source = b"fp_push(_st[2]);\n{ double value = fp_pop(); _st[0] += value; }\nmemcpy(out, g_st, sizeof g_st);"
        self.assertEqual(builder.guard_fpu_memory(source), source)

    def test_silent_fpu_memory_operations_trap_at_the_original_address(self):
        source = (ROOT / "generated/msvcr71-x86/msvcr71_0003.c").read_bytes()
        self.assertIn(b'void_lift_trap(0x130041DBu,', builder.guard_fpu_memory(source))
        self.assertIn(b'void_lift_trap(0x130041E7u,', builder.guard_fpu_memory(source))
        legacy = b'/* fnsave: FPU state is not a memory image here */ /* 0x130041DB: fnsave dword ptr [ecx + 8] */'
        self.assertIn(b'void_lift_trap(0x130041DBu, "unsupported x87 fnsave memory image");', builder.guard_fpu_memory(legacy))
        self.assertEqual(builder.guard_fpu_memory(b"fp_push(1.0);"), b"fp_push(1.0);")


if __name__ == "__main__":
    unittest.main()
