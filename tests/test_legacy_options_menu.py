"""Execute original category spacing with actual legacy menu resources.

Vanilla places categories above CombatReplay, while HoF uses Template. Moving
Back alone increased Vanilla's row spacing and clipped Game and Video above the
panel. Keep both the resource regression and the native positioning oracle.
"""
import sys
import unittest
import xml.etree.ElementTree as ET

from test_legacy_ui import generated_body
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import build_windows
from editions import game_directory
import port_ui
import prepare_windows_runtime


ENGINES = {
    "vanilla": {"function": 0x70C000, "registry": 0x9CD400, "cast": 0xC0D69E,
                "builder": 0x70BD30, "ANCHOR": 0x1D0, "BACK": 0x188,
                "resource": "CombatReplay"},
    "hof": {"function": 0x707DF0, "registry": 0x9B5270, "cast": 0xC09BCE,
            "builder": 0x707B20, "ANCHOR": 0x180, "BACK": 0x184,
            "resource": "Template"},
}


class LegacyOptionsMenuTest(unittest.TestCase):
    def run_native_spacing(self, edition):
        native = ENGINES[edition]
        game = game_directory(edition)
        patched = port_ui.launcher_buttons(game, edition)
        positions = {}
        for label, name in (("ANCHOR", native["resource"]), ("BACK", "Back")):
            path = "UI/GameOptions/" + name + ".(WindowMSButton).xdb"
            original, _ = port_ui.source_resource(game, path, edition)
            for state, data in (("ORIGINAL", original), ("PATCHED", patched[path])):
                placement = ET.fromstring(data).find("Placement")
                self.assertEqual(placement.findtext("Position/Second"), "true")
                self.assertEqual(placement.findtext("VerAllign/First"), "EPA_LOW_END")
                positions[state + "_" + label + "_Y"] = int(placement.findtext("Position/First/y"))
        body = generated_body(edition, native["function"])
        for key in ("registry", "cast", "builder"):
            body = body.replace("sub_%08X" % native[key], key)
        state = (ROOT / "android/host/core.c").read_text(encoding="utf-8")
        state = state[state.index("VOID_HIDDEN uint32_t g_eax"):
                      state.index("#define VOID_ENTER_RING")]
        harness = (ROOT / "tests/fixtures/legacy_options_menu_probe.c").read_text(encoding="utf-8")
        harness = (harness.replace("/* STATE */", state).replace("/* GENERATED */", body)
                   .replace("ORIGINAL()", "sub_%08X()" % native["function"]))
        values = dict(positions, ANCHOR=native["ANCHOR"], BACK=native["BACK"])
        defines = "\n".join("#define %s %d" % item for item in values.items()) + "\n"
        if edition == "vanilla":
            defines += "#define VANILLA 1\n"
        compiler, _, _ = build_windows.compiler_environment()
        header = prepare_windows_runtime.platform_header(
            (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf-8"))
        compile_probe("legacy_options_menu_" + edition, defines + harness,
                      {"runtime.h": header}, compiler_override=compiler,
                      extra_flags=["/clang:-Wno-unused-variable",
                                   "/clang:-Wno-unused-label",
                                   "/clang:-Wno-unused-function"])

    def test_vanilla_combat_replay_anchor_keeps_three_categories_visible(self):
        self.run_native_spacing("vanilla")

    def test_hof_template_anchor_keeps_three_categories_visible(self):
        self.run_native_spacing("hof")


if __name__ == "__main__":
    unittest.main()
