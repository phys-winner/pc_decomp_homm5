"""Current index reduction versus its original exact body, including protected tails."""
import hashlib
import subprocess
import unittest

from test_d3d_lifecycle import function
from test_mmx_packed import CLANG, ROOT, environment


class BufferBoundsTest(unittest.TestCase):
    def test_original_exact_oracle(self):
        out = ROOT / "build/tests/buffer_bounds"
        out.mkdir(parents=True, exist_ok=True)
        fixture = ROOT / "tests/fixtures"
        prefix = '''#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <limits.h>
typedef struct void_com_class void_com_class;
typedef struct d3d_device d3d_device;
typedef uint32_t GLuint;
#define GPTR(va) ((void *)(uintptr_t)(UINT64_C(0x2000000000)+(uint32_t)(va)))
#define NOINLINE __declspec(noinline)
'''
        prefix += function((ROOT / "android/host/com.h").read_text(), "typedef struct void_com_object {") + " void_com_object;\n"
        prefix += function((ROOT / "android/host/d3d9_internal.h").read_text(), "typedef struct d3d_buffer {") + " d3d_buffer;\n"
        source = (ROOT / "android/host/d3d9_gl.c").read_text()
        current = function(source, "static int draw_vertex_bounds(")
        current = current.replace("static int draw_vertex_bounds(", "NOINLINE int bounds_candidate(", 1)
        original = (fixture / "buffer_bounds_original.c").read_text()
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(),
                         "7c3df83748b5a3e90b1750f5b655a662b724f35710ff873b11e957330b46afa2")
        files = {"prefix.h": prefix, "candidate.c": '#include "prefix.h"\n' + current,
                 "baseline.c": original, "probe.c": (fixture / "buffer_bounds_probe.c").read_text()}
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
        env, linker = environment("x64")
        flags = [CLANG, "/nologo", "/W0", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                 "/clang:--target=x86_64-pc-windows-msvc", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"]

        def run(args):
            return subprocess.run(list(map(str, args)), cwd=out, env=env, capture_output=True,
                                  text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)

        for name in ("baseline", "candidate", "probe"):
            built = run([*flags, "/c", name + ".c", "/Fo" + name + ".obj"])
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        linked = run([linker, "/nologo", "baseline.obj", "candidate.obj", "probe.obj", "/OUT:probe.exe"])
        self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
        tested = run([out / "probe.exe"])
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
        self.assertIn('"cases":69236', tested.stdout)
        self.assertIn('"guard_page_tails":"PASS","cases":192', tested.stdout)
        # This negative control must compile and then fail at runtime, not at the compiler.
        self.assertIn("(int32_t)base", current)
        (out / "mutant.c").write_text('#include "prefix.h"\n' + current.replace("(int32_t)base", "(uint32_t)base"), encoding="utf-8")
        built = run([*flags, "/c", "mutant.c", "/Fomutant.obj"])
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        linked = run([linker, "/nologo", "baseline.obj", "mutant.obj", "probe.obj", "/OUT:mutant.exe"])
        self.assertEqual(linked.returncode, 0, linked.stdout + linked.stderr)
        tested = run([out / "mutant.exe"])
        self.assertEqual(tested.returncode, 3, tested.stdout + tested.stderr)
        self.assertIn("oracle mismatch", tested.stderr)


if __name__ == "__main__":
    unittest.main()
