"""libhomm5_common.so selection and ABI checks (tools/common_lib.py) without a device."""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import common_lib as cl  # noqa: E402


def tiny_elf(needed=(), soname=None, runpath=None, symbols=()):
    """A minimal little-endian ELF64 file with .dynsym/.dynstr/.dynamic/.gnu.version."""
    strings = bytearray(b"\0")

    def text(value):
        at = len(strings)
        strings.extend(value.encode() + b"\0")
        return at

    dyn = [(1, text(name)) for name in needed]
    if soname:
        dyn.append((14, text(soname)))
    if runpath:
        dyn.append((29, text(runpath)))
    dyn.append((0, 0))
    syms = [b"\0" * 24]
    versions = [0]
    for name, defined, versioned in symbols:
        syms.append(struct.pack("<IBBHQQ", text(name), (1 << 4) | 2, 0, 7 if defined else 0, 0x1000 if defined else 0, 0))
        versions.append(2 if versioned else 1)
    blobs = [bytes(strings), b"".join(syms), b"".join(struct.pack("<qQ", *row) for row in dyn),
             struct.pack("<%dH" % len(versions), *versions)]
    offset, offsets = 64, []
    for blob in blobs:
        offsets.append(offset)
        offset += len(blob) + (-len(blob) % 8)
    shoff = offset
    header = bytearray(64)
    header[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", header, 0x28, shoff)
    struct.pack_into("<HH", header, 0x3A, 64, 5)
    body = b"".join(blob + b"\0" * (-len(blob) % 8) for blob in blobs)
    sections = [bytes(64)]
    for kind, index, entsize, link in ((3, 0, 0, 0), (11, 1, 24, 1), (6, 2, 16, 1), (0x6FFFFFFF, 3, 2, 2)):
        sections.append(struct.pack("<IIQQQQIIQQ", 0, kind, 0, 0, offsets[index], len(blobs[index]), link, 0, 8, entsize))
    return bytes(header) + body + b"".join(sections)


class CommonLibraryTest(unittest.TestCase):
    def test_elf_reader_and_pair_check(self):
        with tempfile.TemporaryDirectory() as directory:
            engine, common = Path(directory) / "engine.so", Path(directory) / "common.so"
            engine.write_bytes(tiny_elf(needed=("libhomm5_common.so", "libc.so"), runpath="$ORIGIN",
                                        symbols=(("sub_11001000", False, False), ("memcpy", False, True),
                                                 ("h5x_g_eax", True, False))))
            common.write_bytes(tiny_elf(needed=("libc.so",), soname="libhomm5_common.so",
                                        symbols=(("sub_11001000", True, False), ("h5x_g_eax", False, False))))
            info = cl.elf_dynamic(engine)
            self.assertEqual((info["needed"], info["runpath"]), (["libhomm5_common.so", "libc.so"], "$ORIGIN"))
            self.assertEqual(cl.imported(info), {"sub_11001000"})   # versioned memcpy comes from libc
            common_info = cl.elf_dynamic(common)
            self.assertEqual((common_info["soname"], cl.exported(common_info)), ("libhomm5_common.so", {"sub_11001000"}))
            cl.check_pair(engine, info, common_info, ["h5x_g_eax"])
            with self.assertRaisesRegex(ValueError, "does not export h5x_g_ecx"):
                cl.check_pair(engine, info, common_info, ["h5x_g_eax", "h5x_g_ecx"])
            engine.write_bytes(tiny_elf(needed=("libc.so",), symbols=(("sub_11001004", False, False),)))
            with self.assertRaisesRegex(ValueError, "no DT_NEEDED.*RUNPATH.*not exported"):
                cl.check_pair(engine, cl.elf_dynamic(engine), common_info, [])

    def test_header_view_ignores_only_unreferenced_prototypes(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / "a", Path(directory) / "b"
            for folder, extra in ((a, b"void sub_00401000(void);\n"), (b, b"void sub_00402000(void);\n")):
                folder.mkdir()
                (folder / "m_funcs.h").write_bytes(b"#pragma once\n#include \"recomp_types.h\"\n" + extra +
                                                   b"void sub_11001000(void);\n")
            used = {b"sub_11001000"}
            self.assertEqual(cl.header_view(a, used), cl.header_view(b, used))
            self.assertNotEqual(cl.header_view(a, used | {b"sub_00401000"}), cl.header_view(b, used | {b"sub_00401000"}))
            (b / "m_funcs.h").write_bytes((b / "m_funcs.h").read_bytes().replace(b"#pragma once", b"#pragma once\n#define X 1"))
            self.assertNotEqual(cl.header_view(a, used), cl.header_view(b, used))
            self.assertEqual(set(cl.REFERENCE.findall(b"RECOMP_CALL(sub_1102BC0B); sub_1102BC0B_lifted();")), {b"sub_1102BC0B"})

    def test_runtime_header_exports_declarations_and_maps_imports(self):
        header = cl.runtime_header(ROOT)
        original = (ROOT / "android/runtime/recomp_types.h").read_bytes()
        self.assertEqual(original.count(cl.VISIBILITY_ANCHOR), 1)
        self.assertNotIn(cl.VISIBILITY_ANCHOR, header)
        prefix, suffix = original.split(cl.VISIBILITY_ANCHOR)   # only the anchor line is replaced
        self.assertTrue(header.startswith(prefix) and header.endswith(suffix))
        middle = header[len(prefix):len(header) - len(suffix)]
        self.assertIn(b'#define VOID_HIDDEN __attribute__((visibility("default")))', middle)
        self.assertTrue(middle.endswith(b'#include "h5_common_imports.h"'))
        imports = cl.imports_header(["sub_1102BC0B"], ["fmod"])
        for name in ("g_eax", "void_resolve", "recomp_yield_hook", "sub_1102BC0B"):
            self.assertIn(f"#define {name} h5x_{name}\n", imports)
        self.assertIn("extern const uint32_t h5x_yield_fmod;", imports)
        self.assertNotIn("#define g_st ", imports)        # the header's own x87 window macros stay
        self.assertNotIn("g_guest_mem", imports)          # an absolute symbol the library defines itself

    def test_engine_build_accepts_only_its_exact_transformed_sources(self):
        import types
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, data in {"tools/build_android.py": b"builder", "tools/common_lib.py": b"selector",
                                   "android/runtime/recomp_types.h": b"runtime", "clang.exe": b"compiler",
                                   "generated/fmod-x86/fmod_funcs.h": b"#pragma once\nvoid sub_11001000(void);\nvoid sub_00401000(void);\n",
                                   "generated/fmod-x86/fmod_0000.c": b"original",
                                   "build/arm64-thinlto/patched/fmod-x86/fmod_0000.c": b"void sub_11001000(void) {}\n",
                                   "build/arm64-common-thinlto/libhomm5_common.so": b"library"}.items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(data)
            ba = types.SimpleNamespace(EDITION="vanilla", ROOT=root, CLANG=root / "clang.exe", GENERATED=root / "generated",
                                       __file__=str(root / "tools/build_android.py"))
            args = types.SimpleNamespace(no_pgo=True, jobs=1, thinlto_jobs=None)
            original = root / "generated/fmod-x86/fmod_0000.c"
            patched = root / "build/arm64-thinlto/patched/fmod-x86/fmod_0000.c"
            prepared = [(original, patched, []), (root / "generated/fmod-x86/recomp_dispatch.c", root / "x.c", [])]
            view = cl.header_view(root / "generated/fmod-x86", {b"sub_11001000"})
            receipt = dict(library_sha256=cl.sha_file(root / "build/arm64-common-thinlto/libhomm5_common.so"),
                           config=cl.config(ba.CLANG, ["thinlto"], False, root), modules=["fmod"],
                           sources={"fmod-x86/fmod_0000.c": cl.sha_file(patched)}, headers={"fmod": view}, imports=[])
            (root / "build/arm64-common-thinlto" / cl.RECEIPT).write_text(json.dumps(receipt))
            plan = cl.engine_plan(ba, args, ["thinlto"], prepared, rebuild=False)
            self.assertEqual(plan.shared, {original})
            # Another engine's header may declare other functions; only the ones the sources name count.
            (root / "generated/fmod-x86/fmod_funcs.h").write_bytes(b"#pragma once\nvoid sub_11001000(void);\nvoid sub_00402000(void);\n")
            cl.engine_plan(ba, args, ["thinlto"], prepared, rebuild=False)
            patched.write_bytes(b"void sub_11001000(void) { /* other transform */ }\n")
            with self.assertRaisesRegex(SystemExit, "vanilla transforms fmod-x86/fmod_0000.c differently"):
                cl.engine_plan(ba, args, ["thinlto"], prepared, rebuild=False)
            patched.write_bytes(b"void sub_11001000(void) {}\n")
            (root / "generated/fmod-x86/fmod_funcs.h").write_bytes(b"#pragma once\n#define EXTRA 1\nvoid sub_11001000(void);\n")
            with self.assertRaisesRegex(SystemExit, "headers differ"):
                cl.engine_plan(ba, args, ["thinlto"], prepared, rebuild=False)
            (root / "tools/common_lib.py").write_bytes(b"another selector")
            with self.assertRaisesRegex(SystemExit, "another compiler, builder"):
                cl.engine_plan(ba, args, ["thinlto"], prepared, rebuild=False)

    def test_built_library_receipt_matches_file_and_exports_only_lifted_functions(self):
        receipt_path = ROOT / "build/arm64-common-thinlto" / cl.RECEIPT
        if not receipt_path.is_file():
            self.skipTest("libhomm5_common.so is not built")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        library = receipt_path.parent / cl.LIBRARY
        if cl.sha_file(library) != receipt["library_sha256"]:
            self.skipTest("the library is being rebuilt")
        info = cl.elf_dynamic(library)
        self.assertEqual(info["soname"], cl.LIBRARY)
        self.assertFalse(set(info["needed"]) - cl.SYSTEM_LIBRARIES)
        self.assertTrue(all(name.startswith("sub_") for name in cl.exported(info)))
        self.assertEqual(sorted(cl.imported(info)), receipt["imports"])
        self.assertTrue(all(name.startswith(cl.PREFIX) for name in receipt["imports"]))
        self.assertEqual(receipt["yields"].get("fmod"), {"toe": 16384, "vanilla": 16384, "hof": 32768})


if __name__ == "__main__":
    unittest.main()
