"""The 2026-10-30 crash batch: long switch tables (all editions), their stale ToE PGO records and the
ToE crash log."""
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))   # build_android.py imports its sibling transforms
spec = importlib.util.spec_from_file_location("build_android", ROOT / "tools/build_android.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def body(text, name):
    start = text.index(b"\nvoid %s(void) {" % name.encode())
    return text[start:builder.FUNCTION_END.search(text, start).end()]   # generated files use CRLF


class LongSwitchTables(unittest.TestCase):
    def test_toe_declares_its_long_tables(self):
        game = next(m for m in json.loads((ROOT / "config/modules.json").read_text()) if m["name"] == "game")
        self.assertEqual(game["jump_tables"], "config/game.jump-tables.json")
        rows = json.loads((ROOT / game["jump_tables"]).read_text())
        self.assertIn({"address": "0x009F2438", "first_index": 0, "count": 353}, rows)
        self.assertTrue(all(row["count"] > 256 for row in rows))

    def test_spell_name_switch_has_every_arm(self):
        """Spell ids 256..352 (Fortress runes, Stronghold war cries and abilities) reached
        0x009F1E06 and later arms as unresolved dispatches: the hire window crashed."""
        source = (ROOT / "generated/game-x86/game_0462.c").read_bytes()
        switch = body(source, "sub_009F0DF0")
        image = builder.Image(ROOT / "generated/input/H5_Game.exe")
        arms = [image.u32(0x009F2438 + 4 * index) for index in range(353)]
        self.assertEqual(arms[256], 0x009F1E06)
        # The dispatch goes through the body's `_ljump` switch, which must name every arm.
        self.assertIn(b"{ _itail_tgt = (uint32_t)(MEM32(edx * 4 + 0x9F2438)); goto _ljump; }", switch)
        for target in set(arms):
            self.assertIn(b"case 0x%08Xu: goto L_%08X;" % (target, target), switch)

    def test_every_edition_lifts_every_arm_of_its_long_tables(self):
        """1.6 and 2.1 had the same 256-entry cut: HoF's spell names (0x00A645A8, ids 256..289)
        crashed its hire window for the Fortress at 0x00A64366, and all three engines lost arms of
        DXGetErrorString. Each engine declares its own tables; no address crosses engines."""
        from editions import generated_root, module_manifest
        expected = {
            "toe": {"sub_009F0DF0": ["0x009F2438"], "sub_00D3E3F6": ["0x00D4B358", "0x00D4C509", "0x00D4E40B"]},
            "vanilla": {"sub_00C0DD72": ["0x00C1ACD4", "0x00C1BE85", "0x00C1DD87"]},
            "hof": {"sub_00A63350": ["0x00A645A8"], "sub_00C0A284": ["0x00C171E6", "0x00C18397", "0x00C1A299"],
                    "sub_00C0CF94": ["0x00C18397"]},
        }
        tables = set()
        for edition, functions in expected.items():
            game = next(m for m in module_manifest(edition) if m["name"] == "game")
            rows = {row["address"]: row for row in json.loads((ROOT / game["jump_tables"]).read_text())}
            self.assertFalse(tables & set(rows), edition)   # one engine's addresses are not another's
            tables |= set(rows)
            image = builder.Image(generated_root(edition, ROOT) / "input" / game["file"])
            directory = generated_root(edition, ROOT) / "game-x86"
            for name, addresses in functions.items():
                path = next(p for p in directory.glob("game_*.c") if b"\nvoid %s(void) {" % name.encode() in p.read_bytes())
                switch = body(path.read_bytes(), name)
                for address in addresses:
                    with self.subTest(edition=edition, function=name, table=address):
                        row = rows[address]
                        self.assertGreater(row["count"], 256)
                        arms = {image.u32(int(address, 16) + 4 * i) for i in range(row["count"])}
                        for target in arms:
                            self.assertIn(b"case 0x%08Xu: goto L_%08X;" % (target, target), switch)

    def test_regenerated_bodies_skip_only_their_stale_profile(self):
        source = b"\nvoid sub_009F0DF0(void) {\n}\n\nvoid sub_00D3E3F6(void) {\n}\n\nvoid sub_00415AC0(void) {\n}\n"
        marked = builder.skip_stale_profile(source)
        for name in builder.PGO_RETRAIN:
            self.assertIn(b"__attribute__((no_profile_instrument_function))\nvoid %s(void) {" % name, marked)
        self.assertIn(b"\nvoid sub_00415AC0(void) {", marked)
        self.assertEqual(marked.count(b"no_profile_instrument_function"), len(builder.PGO_RETRAIN))
        for name in builder.PGO_RETRAIN:
            files = [path for path in (ROOT / "generated/game-x86").glob("game_*.c")
                     if b"\nvoid %s(void) {" % name in path.read_bytes()]
            self.assertEqual(len(files), 1, name)

    def test_profile_skip_is_toe_and_profile_use_only(self):
        text = (ROOT / "tools/build_android.py").read_text(encoding="utf-8")
        self.assertRegex(text, r'if EDITION == "toe":\s+text = mark_frame_begin_scene\(text\)\s+if PGO_USE:\s+'
                               r'text = skip_stale_profile\(text\)')
        self.assertIn("PGO_USE = bool(args.pgo_use)", text)


class CrashLog(unittest.TestCase):
    def test_engine_appends_to_the_session_log_in_the_toe_app(self):
        core = (ROOT / "android/host/core.c").read_text(encoding="utf-8")
        opening = core[core.index("void void_log_open("):core.index("static void log_va(")]
        self.assertRegex(opening, r'#if defined\(VOID_ANDROID_APP\) && !defined\(HOMM5_LEGACY_UI\)[^#]*fopen\(path, "a"\)'
                                  r'[^#]*#else[^#]*fopen\(path, "w"\)')

    def test_signal_handler_chains_to_the_previous_handler(self):
        core = (ROOT / "android/host/core.c").read_text(encoding="utf-8")
        handler = core[core.index("static void on_signal("):core.index("void void_install_fault_handlers(")]
        self.assertIn("atomic_store(&log_in_signal, 1);", handler)
        self.assertIn("sigaction(signo, previous, NULL);", handler)
        install = core[core.index("void void_install_fault_handlers("):]
        self.assertIn("sigaction(signals[i], &sa, &previous_actions[signals[i]]);", install)

    def test_session_log_starts_before_the_engine_for_toe_only(self):
        activity = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf-8")
        begin = activity.index('if ("toe".equals(gameEdition())) SessionLog.begin(this, data);')
        self.assertEqual(activity.count("nativeStart(gameDir"), 1)
        self.assertLess(begin, activity.index("nativeStart(gameDir"))   # the log is begun before the engine
        session = (ROOT / "android/app/src/org/homm5/port/SessionLog.java").read_text(encoding="utf-8")
        for needle in ('"homm5.1.log"', '"homm5.2.log"', "getHistoricalProcessExitReasons",
                       "setDefaultUncaughtExceptionHandler", "Application.getProcessName()"):
            self.assertIn(needle, session)

    def test_legacy_copies_keep_the_old_log_behaviour(self):
        from port_patches import legacy_ui_branch
        core = (ROOT / "android/host/core.c").read_bytes().replace(b"\r\n", b"\n")
        legacy = legacy_ui_branch(core, True)
        self.assertNotIn(b"log_in_signal", legacy)
        self.assertNotIn(b"previous_actions", legacy)
        self.assertNotIn(b"log_guest_stack", legacy)
        self.assertIn(b'fopen(path, "w")', legacy)


if __name__ == "__main__":
    unittest.main()
