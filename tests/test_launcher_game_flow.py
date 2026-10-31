"""The game's side of the launcher base: GameActivity's actual switch dialog, native exit routing
and back key run in Java against a recording Launch, and the order of its Launch calls."""
import re
import subprocess
import unittest

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT

SOURCE = ROOT / "android/app/src/org/homm5/port"

LAUNCH = r'''
package org.homm5.port.launcher;
import java.util.*;
/* Records what the game asks of the launcher base (org.homm5.port.launcher.Launch). */
public final class Launch {
    public static List<String> ready = new ArrayList<>();
    public static List<String> opened = new ArrayList<>();
    public static boolean readyFails;
    public final List<String> calls = new ArrayList<>();
    public static List<String> ready(Object context) {
        if (readyFails) throw new IllegalStateException("no port.json");
        return new ArrayList<>(ready);
    }
    public static void openLauncher(Object activity, String distribution) { opened.add("open " + distribution); }
    public static void openLauncher(Object activity, String distribution, boolean play) { opened.add("open " + distribution + (play ? " play" : "")); }
    public void exiting(int code, String next) { calls.add("exiting " + code + " " + next); openLauncher(null, next != null ? next : "current", next != null); }
    public void failed(String reason) { calls.add("failed " + reason); }
}
'''

SWITCH = r'''
package org.homm5.port;
import java.io.*;
import java.lang.ref.WeakReference;
import java.util.*;
import org.homm5.port.launcher.Launch;
class Assets {static Set<String> available=new HashSet<>();static boolean runtimeAvailable(Object c,File base,String id){return available.contains(id);}}
class VanillaGameActivity extends GameActivity {}class HofGameActivity extends GameActivity {}
class android {
 static class util {static class Log {static int w(String tag,String text){return 0;}}}
 static class R {static class style {static final int Theme_Material_Dialog_Alert=16974374;}}
 static class app {static class AlertDialog {
 interface Click {void run(AlertDialog d,int which);}interface Dismiss {void run(AlertDialog d);}
 String[] titles;Click item,neutral;Dismiss dismissed;boolean visible;int theme;
 static class Builder {
  AlertDialog d=new AlertDialog();Builder(Object c,int theme){d.theme=theme;}Builder setTitle(String t){return this;}
  Builder setItems(String[] t,Click c){d.titles=t;d.item=c;return this;}
  Builder setNeutralButton(String t,Click c){d.neutral=c;return this;}
  Builder setNegativeButton(String t,Click c){return this;}AlertDialog create(){return d;}
 }
 void setOnDismissListener(Dismiss d){dismissed=d;}void show(){visible=true;}
 void dismiss(){visible=false;if(dismissed!=null)dismissed.run(this);}
 void select(int i){item.run(this,i);dismiss();}void launcher(){neutral.run(this,0);dismiss();}
}}}
public class GameActivity {
 private static volatile WeakReference<GameActivity> currentActivity=new WeakReference<>(null);
 private android.app.AlertDialog gameSwitchDialog;
 private volatile boolean switchRequested;private volatile String pendingSwitch;
 private Launch launch=new Launch();private boolean nativeReady=true,finished;
 private String edition="toe";private String gameEdition(){return edition;}
 private static final int T_CURRENT_GAME=1,T_SWITCH_GAME=2,T_OPEN_LAUNCHER=3,T_CANCEL=4,ESC=1;
 private static String text(int n){return Integer.toString(n);}
 private static int requests;private int uiPosts,releases,escapes;
 private static void nativeRequestGameSwitch(){requests++;}
 private static File baseDir(){return new File("HeroesV");}
 private boolean isFinishing(){return false;}private boolean isDestroyed(){return false;}
 private void releaseAll(){releases++;}private void hideSystemUi(){}private void finish(){finished=true;}
 private void pulseKey(int code){assert code==ESC;escapes++;}
 private static class Touch {void requestFocus(){}}private Touch touch=new Touch();
 private void runOnUiThread(Runnable r){uiPosts++;r.run();}
 /* ACTUAL */
 static GameActivity fresh(String id){GameActivity a=new GameActivity();a.edition=id;currentActivity=new WeakReference<>(a);return a;}
 public static void main(String[] args)throws Exception{
  Launch.ready.addAll(Arrays.asList("toe","hof","vanilla"));Assets.available.addAll(Launch.ready);
  GameActivity a=fresh("toe");onSwitchGame();assert a.gameSwitchDialog.titles.length==3&&a.releases==1;
  assert a.gameSwitchDialog.theme==android.R.style.Theme_Material_Dialog_Alert : "a coherent dark dialog";
  assert a.gameSwitchDialog.titles[0].endsWith(text(T_CURRENT_GAME)) : "the running edition is marked";
  a.gameSwitchDialog.dismiss();assert requests==0&&!a.switchRequested&&Launch.opened.isEmpty() : "cancel changes nothing";
  onSwitchGame();a.gameSwitchDialog.select(0);assert requests==0&&!a.switchRequested : "the current edition is no switch";
  onSwitchGame();Assets.available.remove("hof");a.gameSwitchDialog.select(1);assert requests==0 : "its engine left the build meanwhile";
  Assets.available.add("hof");
  Launch.ready.remove("hof");assert a.readyGames().equals(Arrays.asList("toe","vanilla")) : "only editions with their files";
  Launch.ready.add(1,"hof");
  Launch.readyFails=true;assert a.readyGames().isEmpty();Launch.readyFails=false;
  onSwitchGame();a.gameSwitchDialog.select(1);
  assert requests==1&&a.switchRequested&&"hof".equals(a.pendingSwitch)&&Launch.opened.isEmpty() : "the engine saves and exits first";
  int posts=a.uiPosts;onSwitchGame();assert a.gameSwitchDialog==null : "no second dialog while the switch runs";
  onGameExit();assert a.uiPosts==posts+1 : "the exit callback itself is synchronous";
  assert a.launch.calls.equals(Arrays.asList("exiting 0 hof"))&&Launch.opened.equals(Arrays.asList("open hof play")) : Launch.opened;
  Launch.opened.clear();a=fresh("vanilla");onSwitchGame();a.gameSwitchDialog.launcher();assert requests==2&&a.switchRequested&&a.pendingSwitch==null;
  onGameExit();assert a.launch.calls.equals(Arrays.asList("exiting 0 null"))&&Launch.opened.equals(Arrays.asList("open current")) : Launch.opened;
  Launch.opened.clear();a=fresh("hof");onGameExit();assert a.launch.calls.equals(Arrays.asList("exiting 0 null")) : "the options' Launcher item";
  Launch.opened.clear();a=fresh("hof");a.launch=null;a.switchRequested=true;a.pendingSwitch="toe";onGameExit();
  assert Launch.opened.equals(Arrays.asList("open toe play")) : "without the launcher's record the switch still opens it";
  Launch.opened.clear();a=fresh("toe");a.back();assert a.escapes==1&&a.releases==1&&!a.finished : "back is the game's Escape";
  a.nativeReady=false;a.back();assert a.finished&&Launch.opened.equals(Arrays.asList("open toe")) : "before the engine runs back leads to the launcher";
  Launch.opened.clear();a=fresh("vanilla");a.refuse("files missing");
  assert a.launch.calls.equals(Arrays.asList("failed files missing"))&&a.finished&&Launch.opened.equals(Arrays.asList("open vanilla"));
  System.out.println("PASS game flow: switch list from the launcher's ready editions and this build, cancel/current/no-runtime, deferred switch through Launch.exiting, launcher item, back, refusal");
 }
}
'''


class LauncherGameFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.activity = (SOURCE / "GameActivity.java").read_text(encoding="utf-8")

    def test_actual_switch_exit_and_back_routing(self):
        methods = "\n".join(function(self.activity, signature) for signature in (
            "    private static void onGameExit()", "    private static void onSwitchGame()",
            "    private java.util.List<String> readyGames()", "    private void showGameSwitch()",
            "    private void switchToGame(String edition)", "    private void back()", "    private void toLauncher()",
            "    private void refuse(String reason)"))
        out = ROOT / "build/tests/launcher-game-flow"
        (out / "src/org/homm5/port/launcher").mkdir(parents=True, exist_ok=True)
        (out / "src/org/homm5/port/launcher/Launch.java").write_text(LAUNCH, encoding="utf-8")
        (out / "src/org/homm5/port/GameActivity.java").write_text(SWITCH.replace("/* ACTUAL */", methods), encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out / "classes"),
                        str(SOURCE / "Games.java"), str(out / "src/org/homm5/port/launcher/Launch.java"),
                        str(out / "src/org/homm5/port/GameActivity.java")], check=True)
        result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out / "classes"), "org.homm5.port.GameActivity"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS game flow", result.stdout)

    def test_launch_is_attached_first_and_told_how_the_start_went(self):
        create = function(self.activity, "    @Override protected void onCreate(Bundle state)")
        body = re.sub(r"/\*.*?\*/", "", create[create.index("super.onCreate(state);") + len("super.onCreate(state);"):], flags=re.S)
        first = next(line.strip() for line in body.splitlines() if line.strip())
        self.assertEqual(first, "launch = attachLauncher();")       # before the native library and its thread
        self.assertLess(create.index("attachLauncher()"), create.index("NativeLibrary.load("))
        self.assertIn("getOnBackInvokedDispatcher().registerOnBackInvokedCallback(", create)   # target SDK 36+
        self.assertIn("launch.failed(reason)", create)               # the engine could not be loaded
        self.assertIn("Launch.attach(this)", function(self.activity, "    private Launch attachLauncher()"))
        start = function(self.activity, "    private void startGame()")
        for refusal in ("refuse(String.format(", "refuse(text(T_RUNTIME_MISSING))"):
            self.assertLess(start.index(refusal), start.index("launch.starting()"))
        self.assertLess(start.index("launch.starting()"), start.index('SessionLog.begin(this, data)'))
        self.assertLess(start.index("launch.starting()"), start.index("nativeStart(gameDir"))
        self.assertIn("File gameDir = gameFolder();", start)
        self.assertIn("Games.installed(gameDir, gameEdition())", start)
        self.assertIn('if ("toe".equals(gameEdition())) nativeNewCreatureFramework(optionOn("new_creature_framework"));', start)
        self.assertIn('        nativeLanPeers(option("lan_peers"));', start)     # every engine exports it
        self.assertIn('        nativeRefreshRates(displayRefreshRates());', start)
        self.assertIn("        SessionLog.begin(this, data);", start)    # every edition, its own userdata folder
        self.assertNotIn('"toe".equals(gameEdition())) SessionLog', start)
        self.assertIn("Assets.overlay(this, skipIntro(), gameEdition())", start)
        folder = function(self.activity, "    private File gameFolder()")
        self.assertIn("launch.folder(PART_GAME)", folder)
        self.assertIn("getStringExtra(EXTRA_GAME)", folder)        # tools keep their own folder
        ready = self.activity[self.activity.index("            if (ready) {"):self.activity.index("                View done = loading;")]
        self.assertIn("launch.firstFrame(game);", ready)          # where the old start marker was written
        exit_ = function(self.activity, "    private static void onGameExit()")
        self.assertIn("activity.launch.exiting(0, next);", exit_)   # the engine's own exit() follows
        self.assertNotIn("killProcess", self.activity)
        renew = function(self.activity, "    @Override protected void onNewIntent(Intent intent)")
        self.assertIn("launch.firstFrame(null);", renew)
        destroy = function(self.activity, "    @Override protected void onDestroy()")
        self.assertIn("unregisterOnBackInvokedCallback(", destroy)
        for old in ("Launcher.", "RendererPolicy", "Renderers.", "markStarted", "startupMarker"):
            self.assertNotIn(old, re.sub(r"/\*.*?\*/", "", self.activity, flags=re.S))

    def test_only_opengl_es_while_dxvk_stays_disabled(self):
        choose = function(self.activity, "    private void chooseRenderer()")
        self.assertIn('new File(getApplicationInfo().nativeLibraryDir, "libh5dxvk.so").isFile()', choose)
        self.assertIn('"toe".equals(gameEdition())', choose)
        start = function(self.activity, "    private void startGame()")
        self.assertIn("if (!GLES.equals(renderer)) {", start)
        self.assertLess(start.index("nativeRenderer(nativeMode(renderer)"), start.index("nativeStart("))
        # The engine's bridge needs HOMM5_DXVK, whose define stays inside a comment.
        bridge = (ROOT / "android/host/d3d9_dxvk.c").read_text(encoding="utf-8")
        guard = "#if defined(VOID_ANDROID_APP) && defined(HOMM5_DXVK)"
        self.assertEqual(bridge.count(guard), 1)
        head = bridge[:bridge.index(guard)]
        self.assertIn("#define HOMM5_DXVK\n */", head)
        self.assertNotIn("HOMM5_DXVK", re.sub(r"/\*.*?\*/", "", head, flags=re.S))
        # port.json offers no Vulkan mode, so the launcher has no renderer card and no driver check.
        spec = (ROOT / "android/port.json").read_text(encoding="utf-8")
        self.assertNotIn('"kind": "vulkan"', spec)
        self.assertNotIn('"kind": "turnip"', spec)


if __name__ == "__main__":
    unittest.main()
