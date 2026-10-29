"""Check the actual PE inputs, relocation round trips and source protection."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import struct
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pefile
import lift_homm5 as lift
from lift_game import BoundedDisassembler, analyze_pe, build_iat_map, complete_eh_owner, emit_functions, funcinfo
from pe_rebase import rebase_image


class LiftInputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = lift.read_json(lift.ROOT / "config/modules.json")
        cls.game = Path(lift.read_json(lift.ROOT / "port.json")["game_directory"])

    def test_pinned_hashes_and_nonoverlapping_live_images(self):
        ranges = []
        for spec in self.specs:
            raw = (self.game / spec["source"]).read_bytes()
            self.assertEqual(lift.digest(raw), spec["sha256"], spec["file"])
            pe = pefile.PE(data=raw)
            base = int(spec["base"], 0)
            ranges.append((base, base + pe.OPTIONAL_HEADER.SizeOfImage, spec["file"]))
        ranges.sort()
        for first, second in zip(ranges, ranges[1:]):
            self.assertLessEqual(first[1], second[0], (first[2], second[2]))

    def test_relocation_roundtrip_for_all_unpacked_inputs(self):
        for spec in self.specs:
            if spec.get("unpack"):
                continue
            raw = (self.game / spec["source"]).read_bytes()
            original_base = pefile.PE(data=raw, fast_load=True).OPTIONAL_HEADER.ImageBase
            target = int(spec["base"], 0)
            rebased, proof = rebase_image(raw, target)
            self.assertEqual(rebase_image(rebased, original_base)[0], raw, spec["file"])
            self.assertEqual(pefile.PE(data=rebased, fast_load=True).OPTIONAL_HEADER.ImageBase, target)
            self.assertEqual(len(rebased), len(raw))

    def test_hash_mismatch_stops_before_any_generated_write(self):
        spec = copy.copy(self.specs[0])
        spec["sha256"] = "0" * 64
        old_root = lift.ROOT
        with tempfile.TemporaryDirectory() as temporary:
            lift.ROOT = Path(temporary)
            try:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    lift.prepare(spec, self.game, None)
                self.assertEqual(list(Path(temporary).iterdir()), [])
            finally:
                lift.ROOT = old_root

    def test_compact_generation_matches_original_body(self):
        for file, rva in [("granny2.dll", None), ("um.dll", 0x1EC0)]:
            binary = self.game / "bin" / file
            info = analyze_pe(str(binary))
            imports = build_iat_map(info)
            decoder = BoundedDisassembler(binary.read_bytes(), info.image_base, info.sections)
            address = info.image_base + (rva if rva is not None else info.entry_point_rva)
            function = decoder.disassemble_function(address, imports)
            complete_eh_owner(decoder, function, imports)
            if rva is not None:
                self.assertTrue(function.eh_resume, "Include a real cold C++ catch continuation")
            functions = {address: function}
            with tempfile.TemporaryDirectory() as temporary:
                first, compact = Path(temporary) / "first", Path(temporary) / "compact"
                emit_functions(first, imports, decoder, functions)
                function.blocks.clear()
                function.calls_to.clear()
                function.jump_targets.clear()
                emit_functions(compact, imports, decoder, functions)
                self.assertEqual((first / "recomp_0000.c").read_bytes(),
                                 (compact / "recomp_0000.c").read_bytes(), file)

    def test_inherited_x87_noop_becomes_one_unique_trap(self):
        body = ("    /* fnsave: FPU state is not a memory image here */ "
                "/* 0x130041DB: fnsave dword ptr [ecx + 8] */\n")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / "probe.c"
            path.write_text("void sub_13004000(void) {\n" + body + "}\n"
                            "void sub_13004100(void) {\n" + body + "}\n", encoding="utf-8")
            traps, containing = lift.finalize_sources(directory, ["probe.c"])
            self.assertEqual(traps, [{"address": "0x130041DB", "instruction": "fnsave dword ptr [ecx + 8]"}])
            self.assertEqual(containing, ["0x13004000", "0x13004100"])
            fixed = path.read_text(encoding="utf-8")
            self.assertEqual(fixed.count('void_lift_trap(0x130041DBu, "fnsave dword ptr [ecx + 8]");'), 2)
            self.assertNotIn("FPU state is not a memory image here", fixed)
            self.assertEqual(lift.finalize_sources(directory, ["probe.c"]), (traps, containing))

    def test_all_three_real_h5_catch_owners_have_landing_pads(self):
        binary = self.game / "bin/H5_Game.exe"
        info = analyze_pe(str(binary))
        imports = build_iat_map(info)
        decoder = BoundedDisassembler(binary.read_bytes(), info.image_base, info.sections)
        owners = [(0x009ABA90, 0x00D97E10, 0x00F1006C),
                  (0x00C2E850, 0x00D9F020, 0x00F18270),
                  (0x00CCB190, 0x00DA0A30, 0x00F1A098)]
        for owner, handler, metadata in owners:
            self.assertEqual(funcinfo(decoder.read_bytes, handler), metadata)
            self.assertEqual(struct.unpack("<I", decoder.read_bytes(metadata, 4))[0], 0x19930520)
            self.assertEqual(struct.unpack("<I", decoder.read_bytes(metadata + 12, 4))[0], 1)
            function = decoder.disassemble_function(owner, imports)
            complete_eh_owner(decoder, function, imports)
            self.assertTrue(function.eh_resume, hex(owner))
            instruction_addresses = {i.address for b in function.blocks.values() for i in b.instructions}
            self.assertTrue(function.eh_resume <= instruction_addresses)
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                emit_functions(directory, imports, decoder, {owner: function})
                source = (directory / "recomp_0000.c").read_text()
                self.assertIn("RECOMP_EH_ENTER();", source)
                for target in function.eh_resume:
                    self.assertIn(f"L_{target:08X}:", source)

    def test_msvcr71_negative_memmove_tables_stay_inside_owner(self):
        binary = lift.ROOT / "generated/input/msvcr71.dll"
        info = analyze_pe(str(binary))
        rows = lift.read_json(lift.ROOT / "config/msvcr71.jump-tables.json")
        tables = {int(r["address"], 0): (r["first_index"], r["count"]) for r in rows}
        decoder = BoundedDisassembler(binary.read_bytes(), info.image_base, info.sections, jump_tables=tables)
        imports = build_iat_map(info)
        function = decoder.disassemble_function(0x1300298E, imports)
        wanted = {0x13002C20, 0x13002C28, 0x13002C30, 0x13002C38,
                  0x13002C40, 0x13002C48, 0x13002C50, 0x13002C63}
        self.assertTrue(wanted <= function.jump_targets)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            emit_functions(directory, imports, decoder, {function.address: function})
            source = (directory / "recomp_0000.c").read_text()
            for target in wanted:
                self.assertIn(f"L_{target:08X}:", source)
                self.assertIn(f"case 0x{target:08X}u: goto L_{target:08X};", source)
            self.assertNotIn("RECOMP_CALL(", source)

    def test_h5_long_switch_tables_lift_every_arm(self):
        """The vendor scan reads 256 entries; H5's spell-name switch has 353 arms, and spell
        ids past 255 (Fortress runes, ToE abilities) reached an unlifted arm in LAN games."""
        binary = self.game / "bin/H5_Game.exe"
        info = analyze_pe(str(binary))
        imports = build_iat_map(info)
        rows = lift.read_json(lift.ROOT / "config/game.jump-tables.json")
        tables = {int(r["address"], 0): (r["first_index"], r["count"]) for r in rows}
        undeclared = BoundedDisassembler(binary.read_bytes(), info.image_base, info.sections)
        arms = [struct.unpack("<I", undeclared.read_bytes(0x009F2438 + 4 * i, 4))[0] for i in range(353)]
        self.assertEqual(arms[256], 0x009F1E06)
        self.assertNotIn(0x009F1E06, undeclared.disassemble_function(0x009F0DF0, imports).jump_targets)
        decoder = BoundedDisassembler(binary.read_bytes(), info.image_base, info.sections, jump_tables=tables)
        function = decoder.disassemble_function(0x009F0DF0, imports)
        self.assertTrue(set(arms) <= function.jump_targets)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            emit_functions(directory, imports, decoder, {function.address: function})
            source = (directory / "recomp_0000.c").read_text()
        for target in (arms[255], arms[256], arms[352]):
            self.assertIn(f"L_{target:08X}:", source)
            self.assertIn(f"case 0x{target:08X}u: goto L_{target:08X};", source)

    def test_declared_game_tables_match_their_switch_bounds(self):
        """Each declared count is the `cmp index, count - 1; ja default` in front of its dispatch."""
        from capstone import CS_ARCH_X86, CS_MODE_32, Cs
        binary = self.game / "bin/H5_Game.exe"
        info = analyze_pe(str(binary))
        decoder = BoundedDisassembler(binary.read_bytes(), info.image_base, info.sections)
        disassembler = Cs(CS_ARCH_X86, CS_MODE_32)
        text = next(s for s in pefile.PE(str(binary)).sections if s.Name.rstrip(b"\0") == b".text")
        code, start = text.get_data(), info.image_base + text.VirtualAddress
        for row in lift.read_json(lift.ROOT / "config/game.jump-tables.json"):
            table, count = int(row["address"], 0), row["count"]
            self.assertEqual(row["first_index"], 0)
            sites = [start + at for at in range(len(code) - 7) if code[at] == 0xFF and code[at + 1] == 0x24
                     and code[at + 2] & 0xC7 == 0x85 and struct.unpack_from("<I", code, at + 3)[0] == table]
            self.assertEqual(len(sites), 1, hex(table))
            index = ("eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi")[(decoder.read_bytes(sites[0] + 2, 1)[0] >> 3) & 7]
            bounds = set()
            for back in range(6, 24):
                window = list(disassembler.disasm(decoder.read_bytes(sites[0] - back, back), sites[0] - back))
                if sum(i.size for i in window) != back or len(window) < 2 or window[-1].mnemonic != "ja":
                    continue
                for instruction in reversed(window[:-1]):   # flag-neutral moves may sit between
                    if instruction.mnemonic == "cmp" and instruction.op_str.startswith(index + ","):
                        bounds.add(int(instruction.op_str.split(",")[1], 0) + 1)
                    if instruction.mnemonic not in ("push", "pop", "mov", "lea"):
                        break
            self.assertEqual(bounds, {count}, hex(table))

    def test_granny_keeps_the_base_embedded_in_original_animation_data(self):
        spec = next(s for s in self.specs if s["name"] == "granny2")
        original = pefile.PE(str(self.game / spec["source"]))
        preferred = original.OPTIONAL_HEADER.ImageBase
        self.assertEqual(int(spec["base"], 0), preferred)
        self.assertEqual(preferred, 0x50000000)
        with zipfile.ZipFile(self.game / "data/data.pak") as archive:
            wanted = "bin/animations/4d6594c3-a7cd-4828-b5b0-b2d6fdc76a82"
            name = next(n for n in archive.namelist() if n.lower() == wanted)
            asset = archive.read(name)
        self.assertEqual(struct.unpack_from("<I", asset, 53160)[0], 0x13)
        self.assertEqual(struct.unpack_from("<I", asset, 53168)[0], preferred + 0x55080)
        self.assertEqual(struct.unpack("<I", original.get_data(0x5B688 + 8, 4))[0], preferred + 0x55080)


if __name__ == "__main__":
    unittest.main()
