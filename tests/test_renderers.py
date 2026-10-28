"""Run the actual renderer policy (RendererPolicy.java) on reports shaped like the test devices'."""
from pathlib import Path
import subprocess
import re
import unittest

from test_touch_controls import JAVA, ROOT

CHECK = r'''
package org.homm5.port;
import java.util.*;
public class RendererPolicyCheck {
    static final Set<String> ALL = new HashSet<>();
    static { ALL.addAll(Arrays.asList(RendererPolicy.DXVK_LIBRARIES)); ALL.addAll(Arrays.asList(RendererPolicy.TURNIP_LIBRARIES)); }
    static Map<String, String> report(String text) { return RendererPolicy.parse(text); }
    static RendererPolicy.Status[] eval(int sdk, Set<String> libs, Map<String, String> r) { return RendererPolicy.evaluate(sdk, libs, r, false); }
    static RendererPolicy.Status get(RendererPolicy.Status[] s, String mode) { return RendererPolicy.status(s, mode); }
    public static void main(String[] args) {
        /* The Adreno 650 test phone as the ut3 port found it: system Vulkan 1.1, Turnip Vulkan 1.3. */
        Map<String, String> adreno650 = report("stock.status=missing\nstock.device=Adreno (TM) 650\nstock.vendor=5143\n"
            + "stock.api=1.1.128\nstock.missing=vulkan13,robustness2\nturnip.status=ok\nturnip.device=Turnip Adreno (TM) 650\n"
            + "turnip.vendor=5143\nturnip.api=1.3.335\nturnip.missing=\n");
        RendererPolicy.Status[] s = eval(30, ALL, adreno650);
        assert get(s, "gles").available && !get(s, "dxvk").available && get(s, "turnip").available;
        assert get(s, "dxvk").reason.contains("Vulkan 1.1.128") && get(s, "dxvk").reason.contains("robustness2") : get(s, "dxvk").reason;
        assert RendererPolicy.best(s, adreno650).equals(RendererPolicy.DXVK_VERIFIED ? "turnip" : "gles");
        /* Adreno 735 with a complete system driver: Turnip still first, the system driver second. */
        Map<String, String> adreno735 = report("stock.status=ok\nstock.device=Adreno (TM) 735\nstock.vendor=5143\nstock.api=1.3.128\n"
            + "turnip.status=crash\n");
        s = eval(35, ALL, adreno735);
        assert get(s, "dxvk").available && !get(s, "turnip").available && get(s, "turnip").reason.contains("crashed");
        assert RendererPolicy.best(s, adreno735).equals(RendererPolicy.DXVK_VERIFIED ? "dxvk" : "gles");
        /* A Mali GPU: Vulkan 1.3 without BC formats; no Turnip. */
        Map<String, String> mali = report("stock.status=missing\nstock.device=Mali-G715\nstock.vendor=13b5\nstock.api=1.3.278\n"
            + "stock.missing=bcTextures,geometryShader\nturnip.status=skipped\n");
        s = eval(36, ALL, mali);
        assert !get(s, "dxvk").available && get(s, "dxvk").reason.contains("BC (DXT)") && get(s, "dxvk").reason.contains("geometryShader");
        assert !get(s, "turnip").available && get(s, "turnip").reason.contains("Adreno") && get(s, "turnip").reason.contains("Mali-G715");
        assert RendererPolicy.best(s, mali).equals("gles");
        /* PowerVR with everything DXVK asks for: selectable by hand, never picked by itself. */
        Map<String, String> powervr = report("stock.status=ok\nstock.device=PowerVR D-Series DXT-48-1536\nstock.vendor=1010\nstock.api=1.3.277\n");
        s = eval(36, ALL, powervr);
        assert get(s, "dxvk").available && RendererPolicy.best(s, powervr).equals("gles");
        /* An Adreno 8xx is beyond the bundled Turnip; an Adreno 5xx before it. */
        for (String model : new String[] {"830", "540"}) {
            Map<String, String> r = report("stock.status=missing\nstock.device=Adreno (TM) " + model + "\nstock.vendor=5143\nstock.api=1.1.0\nstock.missing=vulkan13\n");
            RendererPolicy.Status t = get(eval(33, ALL, r), "turnip");
            assert !t.available && t.reason.contains("6xx and 7xx") && t.reason.contains(model) : t.reason;
        }
        /* Android 10, missing libraries, an unfinished check. */
        assert get(eval(29, ALL, adreno650), "turnip").reason.contains("Android 11");
        Set<String> noTurnip = new HashSet<>(Arrays.asList(RendererPolicy.DXVK_LIBRARIES));
        s = eval(30, noTurnip, adreno650);
        assert !get(s, "turnip").available && get(s, "turnip").reason.contains("libh5turnip.so") && get(s, "dxvk").reason.contains("1.1.128");
        s = eval(30, ALL, null);
        assert !get(s, "dxvk").available && get(s, "dxvk").reason.contains("checking") && RendererPolicy.best(s, null).equals("gles");
        /* A chosen mode that cannot run here starts on OpenGL ES; unknown names too. */
        assert RendererPolicy.effective("dxvk", eval(30, ALL, adreno650)).equals("gles");
        assert RendererPolicy.effective("turnip", eval(30, ALL, adreno650)).equals("turnip");
        assert RendererPolicy.effective("vulkan", eval(30, ALL, adreno650)).equals("gles");
        /* The native mode numbers of android/dxvk/bridge_abi.h. */
        assert RendererPolicy.nativeMode("gles") == 0 && RendererPolicy.nativeMode("dxvk") == 1 && RendererPolicy.nativeMode("turnip") == 2;
        /* Russian texts exist for every mode and reason. */
        for (String mode : RendererPolicy.MODES) assert !RendererPolicy.description(mode, true).isEmpty();
        assert RendererPolicy.evaluate(29, ALL, null, true)[1].reason.contains("Android 11");
        assert RendererPolicy.reasons("vulkan13,bcTextures", "1.1.128", true).contains("Vulkan 1.1.128");
        System.out.println("PASS renderer policy: Adreno 650 Turnip, Adreno 735 system DXVK, Mali BC, PowerVR manual only, Adreno 5xx/8xx, Android 10, libraries, unfinished check, fallback");
    }
}
'''


class RendererPolicyTest(unittest.TestCase):
    def test_actual_policy(self):
        out = ROOT / "build/tests/renderer-policy"
        out.mkdir(parents=True, exist_ok=True)
        check = out / "RendererPolicyCheck.java"
        check.write_text(CHECK, encoding="utf-8")
        policy = ROOT / "android/app/src/org/homm5/port/RendererPolicy.java"
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(policy), str(check)], check=True)
        result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "org.homm5.port.RendererPolicyCheck"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_game_offers_once_and_hands_the_mode_over_before_the_engine(self):
        game = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf-8")
        start = game[game.index("    private void startGame() {"):game.index("    private float savedFloat(")]
        # The mode reaches the engine before nativeStart, for Tribes of the East only.
        self.assertLess(start.index("nativeRenderer(RendererPolicy.nativeMode(renderer)"), start.index("nativeStart("))
        self.assertIn('if (RendererPolicy.ENABLED && "toe".equals(gameEdition())) {\n            nativeRenderer(', start)
        prepare = game[game.index("    private void prepareRenderer() {"):game.index("    private void offerRenderer(")]
        self.assertIn('if (!RendererPolicy.ENABLED || !"toe".equals(gameEdition())) { startGame(); return; }', prepare)
        self.assertIn("Renderers.offered(this)", prepare)
        offer = game[game.index("    private void offerRenderer("):game.index("    private void startRenderer(")]
        self.assertEqual(offer.count("Renderers.markOffered(this);"), 2)   # both answers are final
        launcher = (ROOT / "android/app/src/org/homm5/port/Launcher.java").read_text(encoding="utf-8")
        self.assertIn("Renderers.choose(this, chosen, Renderers.AUTO);", launcher)

    def test_dxvk_support_is_commented_out(self):
        # One switch keeps the launcher card, the driver check and the offer away; the engine's bridge
        # needs HOMM5_DXVK, whose define stays inside a comment.
        policy = (ROOT / "android/app/src/org/homm5/port/RendererPolicy.java").read_text(encoding="utf-8")
        self.assertIn("static final boolean ENABLED = false;", policy)
        launcher = (ROOT / "android/app/src/org/homm5/port/Launcher.java").read_text(encoding="utf-8")
        self.assertIn("if (RendererPolicy.ENABLED) buildRenderer(column);", launcher)
        probe = launcher.index("Renderers.probe(this);")
        self.assertIn("if (RendererPolicy.ENABLED) {", launcher[probe - 160:probe])
        bridge = (ROOT / "android/host/d3d9_dxvk.c").read_text(encoding="utf-8")
        guard = "#if defined(VOID_ANDROID_APP) && defined(HOMM5_DXVK)"
        self.assertEqual(bridge.count(guard), 1)
        head = bridge[:bridge.index(guard)]
        self.assertIn("#define HOMM5_DXVK\n */", head)   # kept, inside a comment
        self.assertNotIn("HOMM5_DXVK", re.sub(r"/\*.*?\*/", "", head, flags=re.S))


if __name__ == "__main__":
    unittest.main()
