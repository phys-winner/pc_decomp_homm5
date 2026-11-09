"""Execute the Activity's compositor fade with a deterministic UI queue, without an Android device."""
import subprocess
import unittest
import xml.etree.ElementTree as ET

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT

ACTIVITY = ROOT / "android/app/src/org/homm5/port/GameActivity.java"
ANDROID = "{http://schemas.android.com/apk/res/android}"

HARNESS = r'''
import java.util.*;
public class LaunchDimmingCheck {
 static class Build {static class VERSION {static int SDK_INT=27;}}
 static class SystemClock {static long now=1000;static long uptimeMillis(){return now;}}
 static class WindowManager {static class LayoutParams {
  static final int FLAG_DIM_BEHIND=2;float alpha=1,dimAmount;int flags=1024;
 }}
 static class Window {WindowManager.LayoutParams p=new WindowManager.LayoutParams();int changes;
  WindowManager.LayoutParams getAttributes(){return p;}void setAttributes(WindowManager.LayoutParams p){this.p=p;changes++;}}
 static class Handler {Map<Runnable,Long> queue=new HashMap<>();
  void post(Runnable r){postAtTime(r,SystemClock.now);}
  void postAtTime(Runnable r,long time){queue.put(r,time);}void removeCallbacks(Runnable r){queue.remove(r);}}
 static class Color {static final int BLACK=0xFF000000;}
 static class View {View(Object c){}int color;boolean clickable;void setBackgroundColor(int c){color=c;}
  void setClickable(boolean c){clickable=c;}}
 static class FrameLayout {static class LayoutParams {LayoutParams(int w,int h){assert w==-1&&h==-1;}}
  List<View> children=new ArrayList<>();void addView(View v,LayoutParams p){children.add(v);}void removeView(View v){children.remove(v);}}
 static class android {static class util {static class Log {
  static List<String> lines=new ArrayList<>();static int i(String tag,String s){lines.add(s);return 0;}}}}
 final Handler handler=new Handler();final Window window=new Window();FrameLayout game=new FrameLayout();
 private long launchStarted=SystemClock.now,launchDimStarted;private boolean launchDimming;private View launchCurtain;
 int opaqueCalls;boolean setTranslucent(boolean translucent){assert !translucent;opaqueCalls++;return true;}
 Window getWindow(){return window;}String gameEdition(){return "toe";}
 /* ACTUAL */
 void advance(long time) {
  SystemClock.now=time;
  List<Runnable> due=new ArrayList<>();for(Map.Entry<Runnable,Long> e:handler.queue.entrySet())if(e.getValue()<=time)due.add(e.getKey());
  for(Runnable r:due){handler.queue.remove(r);r.run();}
 }
 static void same(float a,float b){assert Math.abs(a-b)<0.000001f:a+" != "+b;}
 public static void main(String[] args) {
  for(int sdk:new int[]{26,27,37}) {
   Build.VERSION.SDK_INT=sdk;SystemClock.now=1000;LaunchDimmingCheck a=new LaunchDimmingCheck();
   a.beginLaunchDimming();a.coverLaunchDimming();assert a.launchDimming&&a.handler.queue.size()==1;
   assert a.game.children.size()==1&&a.launchCurtain.color==Color.BLACK&&a.launchCurtain.clickable;
   same(a.window.p.alpha,sdk>=27?.01f:1f);same(a.window.p.dimAmount,0);
   assert ((a.window.p.flags&2)!=0)==(sdk>=27);a.advance(1000);
   for(int tick=1;tick<=28;tick++) {
    a.advance(1000+tick*10);assert a.launchDimming;
    same(a.window.p.dimAmount,sdk>=27?tick*9/255f:0);
    if(tick==4) { // Native startup replaces the initial preparing root during the fade.
     a.game=new FrameLayout();a.coverLaunchDimming();assert a.game.children.size()==1;
    }
   }
   a.advance(1289);assert a.launchDimming;a.advance(1290);
   assert !a.launchDimming&&a.handler.queue.isEmpty()&&a.game.children.isEmpty()&&a.launchCurtain==null;
   same(a.window.p.alpha,1);same(a.window.p.dimAmount,0);assert a.window.p.flags==1024;
   assert a.opaqueCalls==(sdk>=30?1:0);
   int changes=a.window.changes;a.advance(5000);a.finishLaunchDimming("duplicate");assert a.window.changes==changes;
   for(String reason:new String[]{"pause","destroy","back","failure","launcher"}) {
    SystemClock.now=1000;a=new LaunchDimmingCheck();a.beginLaunchDimming();a.coverLaunchDimming();a.advance(1140);
    a.finishLaunchDimming(reason);assert !a.launchDimming&&a.handler.queue.isEmpty()&&a.game.children.isEmpty();
    same(a.window.p.alpha,1);same(a.window.p.dimAmount,0);assert a.window.p.flags==1024;
   }
   // A delayed UI callback catches up to the clock; no long tail or accumulated startup sleep.
   SystemClock.now=1000;a=new LaunchDimmingCheck();a.beginLaunchDimming();a.coverLaunchDimming();
   a.advance(1217);same(a.window.p.dimAmount,sdk>=27?189/255f:0);a.advance(2000);assert !a.launchDimming;
  }
  assert android.util.Log.lines.stream().anyMatch(s->s.contains("dim-end-complete"));
  System.out.println("PASS compositor timing, original alpha steps, root replacement, clock catch-up and all cancellations");
 }
}
'''


class LaunchDimmingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ACTIVITY.read_text(encoding="utf-8")

    def test_actual_compositor_timeline_and_lifecycle_cleanup(self):
        methods = "\n".join(function(self.source, signature) for signature in (
            "    private void beginLaunchDimming()", "    private void coverLaunchDimming()",
            "    private void finishLaunchDimming(String reason)", "    private void launchTiming(String event)"))
        methods += function(self.source, "    private final Runnable launchDimTick = new Runnable()") + ";\n"
        out = ROOT / "build/tests/launch-dimming"
        out.mkdir(parents=True, exist_ok=True)
        src = out / "LaunchDimmingCheck.java"
        src.write_text(HARNESS.replace("/* ACTUAL */", methods), encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(src)], check=True)
        result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "LaunchDimmingCheck"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS compositor timing", result.stdout)

    def test_startup_and_ready_overlay_are_independent_of_fade(self):
        create = function(self.source, "    @Override protected void onCreate(Bundle state)")
        worker = function(self.source, "    private void startLibrary(boolean allowUnsupported)")
        start = function(self.source, "    private void startGame()")
        dim = self.source[self.source.index("    private void beginLaunchDimming()"):
                          self.source.index("    /* ------------------------------------------------------------ loading */")]
        self.assertLess(create.index("beginLaunchDimming();"), create.index("startLibrary(false);"))
        self.assertIn('}, "native-library").start();', worker)
        self.assertNotRegex(create + worker, r"(?:sleep|await|join|postDelayed)\s*\(")
        self.assertIn("NativeLibrary.load(this, Games.library(gameEdition()));", worker)
        self.assertIn("                    startGame();", worker)
        self.assertNotIn("nativeStart", dim)
        self.assertNotIn("NativeLibrary", dim)
        self.assertNotIn("startGame()", dim)
        self.assertNotIn("launchDimming", start.replace("coverLaunchDimming();", ""))
        self.assertIn('launchTiming("library-begin");', worker)
        self.assertIn('launchTiming("library-ready");', worker)
        self.assertLess(start.index('launchTiming("native-start");'), start.index("nativeStart(gameDir"))
        self.assertGreater(start.index('launchTiming("native-start-return");'), start.index("nativeStart(gameDir"))
        self.assertIn("done.animate().alpha(0f).setDuration(350)", self.source)
        for signature, reason in (("    private void back()", "back"), ("    private void toLauncher()", "launcher"),
                                  ("    @Override protected void onPause()", "pause"), ("    @Override protected void onDestroy()", "destroy")):
            self.assertIn(f'finishLaunchDimming("{reason}");', function(self.source, signature))
        self.assertIn('finishLaunchDimming("failure");', worker)
        self.assertNotIn("beginLaunchDimming", function(self.source, "    @Override protected void onResume()"))
        self.assertNotIn("beginLaunchDimming", function(self.source, "    @Override protected void onNewIntent(Intent intent)"))

    def test_orientation_safe_themes_and_all_three_entries(self):
        app = ROOT / "android/app"
        base = ET.parse(app / "res/values/game_launch.xml").getroot()
        newer = ET.parse(app / "res/values-v27/game_launch.xml").getroot()
        items = lambda tree: {n.attrib["name"]: n.text for n in tree.find("style[@name='GameLaunch']")}
        old, new = items(base), items(newer)
        self.assertNotIn("android:windowIsTranslucent", old)
        self.assertEqual(new["android:windowIsTranslucent"], "true")
        self.assertEqual(old["android:windowDisablePreview"], "true")
        self.assertEqual(new["android:windowDisablePreview"], "true")
        self.assertEqual(new["android:windowBackground"], "@android:color/transparent")
        alpha = ET.parse(app / "res/anim/game_launch_dim.xml").getroot()
        self.assertEqual((alpha.get(ANDROID+"fromAlpha"), alpha.get(ANDROID+"toAlpha"), alpha.get(ANDROID+"duration")), ("0", "1", "290"))
        manifest = ET.parse(app / "AndroidManifest.xml").getroot()
        for name in (".GameActivity", ".VanillaGameActivity", ".HofGameActivity"):
            activity = manifest.find(f"application/activity[@{ANDROID}name='{name}']")
            self.assertEqual(activity.get(ANDROID+"theme"), "@style/GameLaunch")
            self.assertEqual(activity.get(ANDROID+"screenOrientation"), "sensorLandscape")


if __name__ == "__main__":
    unittest.main()
