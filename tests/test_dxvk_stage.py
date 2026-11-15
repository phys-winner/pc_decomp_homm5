"""tools/build_dxvk.py's check of the staged libraries: AArch64 shared objects whose PT_LOAD segments
are aligned to at least 16 KiB and placed in the file at their addresses modulo that alignment. llvm-strip
broke the second rule for the Turnip driver (2026-11-15): Android refused the library and adrenotools fell
back to the system driver, so the Turnip mode started with OpenGL ES. strip_keep_layout strips it without
breaking the rule."""
import importlib.util
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))   # android_tools
spec = importlib.util.spec_from_file_location("build_dxvk_under_test", ROOT / "tools/build_dxvk.py")
build_dxvk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_dxvk)


def elf(*loads):
    """A minimal ELF64 AArch64 shared object header with the given (offset, address, align) PT_LOADs."""
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    struct.pack_into("<HH", header, 16, 3, 183)              # ET_DYN, EM_AARCH64
    struct.pack_into("<Q", header, 32, 64)                   # e_phoff
    struct.pack_into("<HH", header, 54, 56, len(loads))      # e_phentsize, e_phnum
    table = b"".join(struct.pack("<IIQQQQQQ", 1, 5, offset, address, address, 0x100, 0x100, align)
                     for offset, address, align in loads)
    return bytes(header) + table


class DxvkStageTest(unittest.TestCase):
    def check(self, data):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "libprobe.so"
            path.write_bytes(data)
            build_dxvk.check_elf(path)

    def test_segments_must_be_16k_aligned_and_congruent(self):
        self.check(elf((0, 0, 0x4000), (0x813ff0, 0x817ff0, 0x4000), (0x1040000, 0xd00000, 0x10000)))
        with self.assertRaisesRegex(ValueError, "alignment below 16 KiB"):
            self.check(elf((0, 0, 0x1000)))
        # The stripped Turnip driver's last segment (llvm-strip output of 2026-11-15).
        with self.assertRaisesRegex(ValueError, "does not match its address"):
            self.check(elf((0, 0, 0x4000), (0xcead14, 0xd00000, 0x10000)))
        with self.assertRaisesRegex(ValueError, "not an AArch64"):
            self.check(b"\x7fELF\x01" + bytes(59))

    def test_the_turnip_driver_is_stripped_with_its_layout_kept(self):
        # Not through llvm-strip, which broke the patchelf-style last segment's file offset.
        self.assertNotIn("libh5turnip.so", build_dxvk.STRIPPED)
        self.assertIn("libh5turnip.so", build_dxvk.TURNIP_DRIVER)
        names = b"\0.text\0.debug_info\0.shstrtab\0.dynstr\0"
        text, debug, dynstr = b"\xc0\x03\x5f\xd6" * 16, bytes(range(256)) * 300, b"\0libc.so\0vk_icd\0"
        # Layout: header, 2 PT_LOADs, .text | .debug_info | .shstrtab | headers | .dynstr at 64 KiB.
        text_at = 64 + 2 * 56
        debug_at = text_at + len(text)
        names_at = debug_at + len(debug)
        table_at = (names_at + len(names) + 7) & ~7
        dynstr_at = 0x30000
        header = bytearray(64)
        header[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<HH", header, 16, 3, 183)
        struct.pack_into("<QQ", header, 32, 64, table_at)
        struct.pack_into("<HHHHHH", header, 52, 64, 56, 2, 64, 5, 3)
        loads = struct.pack("<IIQQQQQQ", 1, 5, 0, 0, 0, debug_at, debug_at, 0x4000)
        loads += struct.pack("<IIQQQQQQ", 1, 4, dynstr_at, 0x10000, 0x10000, len(dynstr), len(dynstr), 0x10000)
        sections = [(0, 0, 0, 0, 0, 0), (1, 1, 6, text_at, text_at, len(text)), (7, 1, 0, 0, debug_at, len(debug)),
                    (19, 3, 0, 0, names_at, len(names)), (29, 3, 2, 0x10000, dynstr_at, len(dynstr))]
        table = b"".join(struct.pack("<IIQQQQIIQQ", n, t, f, a, o, s, 0, 0, 1, 0) for n, t, f, a, o, s in sections)
        image = bytearray(bytes(header) + loads + text + debug + names)
        image += bytes(table_at - len(image)) + table
        image += bytes(dynstr_at - len(image)) + dynstr
        stripped = build_dxvk.strip_keep_layout(bytes(image))
        self.assertLess(len(stripped), len(image) - len(debug))
        self.check(stripped)
        second = struct.unpack_from("<IIQQQQQQ", stripped, 64 + 56)
        self.assertEqual((second[2] % 0x10000, second[3]), (0, 0x10000))
        shoff, = struct.unpack_from("<Q", stripped, 40)
        rows = [struct.unpack_from("<IIQQQQIIQQ", stripped, shoff + i * 64) for i in range(5)]
        self.assertEqual(rows[2][1], 0)                                   # .debug_info: SHT_NULL now
        self.assertEqual(stripped[rows[1][4]:rows[1][4] + len(text)], text)
        self.assertEqual(stripped[rows[4][4]:rows[4][4] + len(dynstr)], dynstr)
        self.assertEqual(stripped[rows[3][4]:rows[3][4] + len(names)], names)
        self.assertEqual(rows[4][4], second[2])                           # .dynstr moved with its segment

    def test_legacy_editions_render_in_system_memory_unless_told_otherwise(self):
        # With Turnip's tiled (GMEM) passes the Heroes V 1.6 battle entry and Hammers of Fate's loading
        # never signalled their frame event (2026-11-15); their engines run in the ":vanilla" and ":hof"
        # processes. Tribes of the East keeps GMEM; dxvk.env's TU_DEBUG still wins (no overwrite).
        bridge = (ROOT / "android/dxvk/bridge.cpp").read_text(encoding="utf-8")
        create = bridge[bridge.index("uint32_t op_create9("):bridge.index("uint32_t op_call(")]
        self.assertIn('if (legacy_process() && setenv("TU_DEBUG", "sysmem", 0) == 0)', create)
        self.assertLess(create.index('setenv("TU_DEBUG"'), create.index("homm5_open_turnip("))
        legacy = bridge[bridge.index("bool legacy_process() {"):bridge.index("uint32_t op_create9(")]
        self.assertIn('"/proc/self/cmdline"', legacy)
        self.assertIn('!strcmp(colon, ":vanilla") || !strcmp(colon, ":hof")', legacy)
        manifest = (ROOT / "android/app/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertIn('android:process=":vanilla"', manifest)
        self.assertIn('android:process=":hof"', manifest)

    def test_staged_runtime_passes(self):
        runtime = ROOT / "build/dxvk/runtime"
        libraries = sorted(runtime.glob("*.so")) if runtime.is_dir() else []
        if not libraries:
            self.skipTest("no staged DXVK runtime")
        for library in libraries:
            with self.subTest(library=library.name):
                build_dxvk.check_elf(library)


if __name__ == "__main__":
    unittest.main()
