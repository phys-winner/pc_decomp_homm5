"""A matching VA never authorizes another engine's source optimization."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android as builder
import lift_homm5 as lift
import pefile


class EngineBuildIsolation(unittest.TestCase):
    def test_shared_dll_runtime_identity_authorizes_existing_hooks_and_crt_tables(self):
        from editions import module_manifest
        for edition in ('vanilla', 'hof'):
            modules = {row['name']: row for row in module_manifest(edition)}
            self.assertEqual(modules['msvcr71']['jump_tables'], 'config/msvcr71.jump-tables.json')
            for name in ('granny2', 'fmod', 'msvcr71', 'msvcp71', 'zlib1', 'libcurl', 'zlibwapi'):
                with self.subTest(edition=edition, module=name):
                    filename = modules[name]['file']
                    old = pefile.PE(str(ROOT / 'generated/input' / filename), fast_load=True)
                    actual = pefile.PE(str(ROOT / 'generated' / edition / 'input' / filename), fast_load=True)
                    self.assertEqual(actual.OPTIONAL_HEADER.ImageBase, old.OPTIONAL_HEADER.ImageBase)
                    self.assertEqual(actual.OPTIONAL_HEADER.AddressOfEntryPoint, old.OPTIONAL_HEADER.AddressOfEntryPoint)
                    self.assertEqual(actual.OPTIONAL_HEADER.SizeOfImage, old.OPTIONAL_HEADER.SizeOfImage)
                    self.assertEqual(len(actual.sections), len(old.sections))
                    for before, after in zip(old.sections, actual.sections):
                        self.assertEqual((after.Name, after.VirtualAddress, after.Misc_VirtualSize, after.Characteristics),
                                         (before.Name, before.VirtualAddress, before.Misc_VirtualSize, before.Characteristics))
                        self.assertEqual(after.get_data(), before.get_data())

    def test_new_engine_retains_full_protocol_at_colliding_toe_addresses(self):
        (ROOT / "build/tests").mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "build/tests") as temporary:
            directory = Path(temporary)
            source = directory / "game-x86/game_0000.c"
            source.parent.mkdir()
            body = (b"void sub_008800B0(void) {\n"
                    b"    RECOMP_BACKEDGE(); RECOMP_CALL(sub_00C362E0);\n"
                    b"    _st[0] += _st[1]; /* 0x008800BA: fadd st(0), st(1) */\n"
                    b"}\n")
            source.write_bytes(body)
            for edition in ("vanilla", "hof"):
                with self.subTest(edition=edition), ExitStack() as stack:
                    stack.enter_context(patch.multiple(builder, EDITION=edition, OUT=directory / edition,
                                                      ACTIVE_NATIVE_OVERRIDES=()))
                    adapter = stack.enter_context(patch("port_patches.adapt_generated_source",
                                                         side_effect=lambda text, *_: text))
                    for name in ("index_region", "localize_backedges", "separate_guest_state", "apply_protocol",
                                 "call_protocol", "apply_x87", "x87_plan", "mark_frame_begin_scene", "cutscene_projection"):
                        stack.enter_context(patch.object(builder, name, side_effect=AssertionError("ToE pass: " + name)))
                    prepared, _ = builder.override_source(source, local_xmm=True)
                    result = prepared.read_bytes()
                    self.assertIn(b"RECOMP_BACKEDGE(); RECOMP_CALL(sub_00C362E0);", result)
                    self.assertIn(b"_st[0] = fp_pc(_st[0]);", result)
                    adapter.assert_called_once_with(builder.round_x87_precision(body), "game", edition)

    def test_selecting_an_engine_clears_all_address_caches(self):
        try:
            for edition in ("vanilla", "hof", "toe"):
                builder._images["game"] = object()
                builder._protocol = builder._x87_plan = object()
                builder.configure_edition(edition)
                self.assertEqual(builder._images, {})
                self.assertIsNone(builder._protocol)
                self.assertIsNone(builder._x87_plan)
                expected = ROOT / "generated" / (edition if edition != "toe" else "")
                self.assertEqual(builder.GENERATED, expected)
                self.assertEqual(builder.MODULE_IMAGES["game"], expected / "input/H5_Game.exe")
        finally:
            builder.configure_edition("toe")

    def test_lift_keeps_catalogs_and_inputs_inside_selected_engine(self):
        # Exercise prepare on a real original PE, without disassembling it.
        from editions import game_directory, module_manifest
        original_hashes = {}
        for edition in ("vanilla", "hof"):
            spec = next(row for row in module_manifest(edition) if row["name"] == "ubistats")
            game = game_directory(edition)
            original_hashes[edition] = lift.digest((game / spec["source"]).read_bytes())
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                with patch.multiple(lift, ROOT=directory, GENERATED=directory / "generated" / edition, EDITION=edition):
                    binary, proof = lift.prepare(spec, game, None)
                    self.assertEqual(binary, directory / "generated" / edition / "input/UbiStats.dll")
                    self.assertEqual(proof["binary_sha256"], spec["sha256"])
                    catalog = directory / "generated" / edition / "catalog/ubistats.catalog.json"
                    catalog.parent.mkdir(parents=True)
                    catalog.write_text(json.dumps({"functions": [{"address": 0x12001000, "size": 10}]}))
                    catalog.with_suffix(".sha256").write_text(proof["rebased_sha256"])
                    self.assertEqual(lift.catalog(binary, "ubistats", proof["rebased_sha256"]),
                                     [{"address": 0x12001000, "size": 10}])
                    self.assertFalse((directory / "config").exists())
            self.assertEqual(lift.digest((game / spec["source"]).read_bytes()), original_hashes[edition])


if __name__ == "__main__":
    unittest.main()
