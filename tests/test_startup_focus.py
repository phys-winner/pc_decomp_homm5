"""Execute actual loading-ready callback/focus return with modeled Android boundaries.

The model checks the one-shot focus policy, not Android/IME event dispatch itself.
Candidate5 ART/device evidence and new-APK first-key controls remain separate gates.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT

HARNESS = r'''
package org.homm5.port;
import java.util.*;
class ActivityBase {
 boolean window=true,finishing,destroyed;
 public void onWindowFocusChanged(boolean value){window=value;}
 boolean hasWindowFocus(){return window;}
 boolean isFinishing(){return finishing;}boolean isDestroyed(){return destroyed;}
}
public class GameActivity extends ActivityBase {
 static class Animator {}
 static class AnimatorListenerAdapter {public void onAnimationEnd(Animator animation){}}
 static class Animation {
  AnimatorListenerAdapter listener;
  Animation alpha(float f){assert f==0;return this;}Animation setDuration(int n){assert n==350;return this;}
  Animation setListener(AnimatorListenerAdapter value){listener=value;return this;}
  void end(){assert listener!=null;listener.onAnimationEnd(new Animator());}
 }
 static class View {final Animation animation=new Animation();Animation animate(){return animation;}}
 static class FrameLayout {View removed;void removeView(View view){removed=view;}}
 class Touch {
  int requests;boolean succeeds=true,focused;
  boolean requestFocus(){assert game.removed==done : "focus requested before overlay removal";
   requests++;focused=succeeds;return succeeds;}
 }
 static class Image {Object drawable=new Object();void setImageDrawable(Object value){drawable=value;}}
 static class Label {void setText(String value){assert value!=null;}}
 static class Preferences {
  int writes;Preferences edit(){return this;}Preferences putInt(String key,int value){assert key.equals("startup_work");return this;}
  void apply(){writes++;}
 }
 static class Handler {int posts;void postDelayed(Runnable r,int delay){assert delay==100;posts++;}}
 static class Launch {int ready;void firstFrame(FrameLayout game){assert game!=null;ready++;}}
 class ArmyActions {int offers;boolean popup;void offerForMouse(){offers++;if(popup)touch.focused=false;}}
 boolean ready,firstFrameShown,startupFocusPending;
 long loadingStart=System.currentTimeMillis();int loadingExpected=2600;
 float loadingShown;int work=500;final int T_LOADING=0;
 View loading=new View(),done=loading;FrameLayout game=new FrameLayout();Touch touch=new Touch();
 Image loadingImage=new Image();Object startupArtwork=new Object();Label loadingText=new Label();
 Preferences preferences=new Preferences();Handler handler=new Handler();Launch launch=new Launch();ArmyActions armyActions=new ArmyActions();
 int hideCalls,refreshCalls,releases;
 boolean nativeLoadReady(){return ready;}int nativeLoadWork(){return work;}
 static String text(int n){assert n==0;return "Loading";}
 void hideSystemUi(){hideCalls++;}void requestHighRefresh(){refreshCalls++;}void releaseAll(){releases++;}
 /* ACTUAL */
 void runReady(boolean focused){
  window=focused;loadingTick.run();assert loading!=null&&!firstFrameShown&&touch.requests==0&&handler.posts==1;
  ready=true;loadingTick.run();assert loading==null&&firstFrameShown&&launch.ready==1&&preferences.writes==1;
  assert touch.requests==0 : "focus moved before loading fade ended";
  onWindowFocusChanged(focused);assert touch.requests==0 : "focus moved while overlay fading";
  done.animation.end();assert game.removed==done&&loadingImage.drawable==null&&startupArtwork==null&&armyActions.offers==1;
 }
 void firstGrave(){assert touch.focused : "First keyboard event lacks game focus";}
 static void foreground(){
  GameActivity a=new GameActivity();a.runReady(true);a.firstGrave();assert a.touch.requests==1&&!a.startupFocusPending;
  // Returning ordinary focus must not re-arm the startup request or steal focus from an Android control.
  a.touch.focused=false;a.onWindowFocusChanged(false);a.onWindowFocusChanged(true);
  assert a.touch.requests==1&&!a.touch.focused&&!a.startupFocusPending : "Startup focus request repeated";
  assert a.hideCalls==2&&a.refreshCalls==2&&a.releases==1;
  a.loadingTick.run();assert a.touch.requests==1;
 }
 static void deferred(){
  GameActivity a=new GameActivity();a.runReady(false);
  assert a.touch.requests==0&&a.startupFocusPending : "Background startup stole focus or dropped pending focus";
  a.onWindowFocusChanged(true);a.firstGrave();assert a.touch.requests==1&&!a.startupFocusPending;
 }
 static void dead(){
  for(int mode=0;mode<2;mode++){
   GameActivity a=new GameActivity();a.finishing=mode==0;a.destroyed=mode==1;a.runReady(true);
   assert a.touch.requests==0&&a.startupFocusPending : "Closing activity requested focus";
   a.onWindowFocusChanged(true);assert a.touch.requests==0;
  }
 }
 static void retry(){
  GameActivity a=new GameActivity();a.touch.succeeds=false;a.runReady(true);
  assert a.touch.requests==1&&a.startupFocusPending : "Failed request lost pending focus";
  a.touch.succeeds=true;a.onWindowFocusChanged(true);a.firstGrave();assert a.touch.requests==2&&!a.startupFocusPending;
 }
 static void popup(){
  GameActivity a=new GameActivity();a.armyActions.popup=true;a.runReady(true);
  assert a.touch.requests==1&&!a.touch.focused&&!a.startupFocusPending;
  a.onWindowFocusChanged(false);a.onWindowFocusChanged(true);
  assert a.touch.requests==1&&!a.touch.focused : "Focus stolen after mouse suggestion/control";
 }
 public static void main(String[] args){foreground();deferred();dead();retry();popup();
  System.out.println("PASS actual ready/fade/window callbacks: one-shot game focus, foreground/deferred/retry/closing/control guards; Android dispatch modeled separately");}
}
'''


class StartupFocusTest(unittest.TestCase):
    def actual(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        tick = function(source, "private final Runnable loadingTick = new Runnable()") + ";"
        window = function(source, "public void onWindowFocusChanged(")
        # The old body must compile and fail at runtime before this correction exists.
        restore = (function(source, "private void restoreStartupFocus(")
                   if "private void restoreStartupFocus(" in source else "private void restoreStartupFocus() {}")
        return tick + "\n" + window + "\n" + restore

    def run_focus(self, actual):
        with tempfile.TemporaryDirectory(prefix="startup-focus-", dir=ROOT / "build/tests") as directory:
            out = Path(directory)
            source = out / "GameActivity.java"
            source.write_text(HARNESS.replace("/* ACTUAL */", actual), encoding="utf8")
            compiled = subprocess.run([str(JAVA / "javac.exe"), "-encoding", "UTF-8", "-d", str(out), str(source)],
                                      capture_output=True, text=True)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            return subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "org.homm5.port.GameActivity"],
                                  capture_output=True, text=True, timeout=15)

    def test_actual_ready_focus_policy(self):
        result = self.run_focus(self.actual())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_runtime_negative_controls(self):
        actual = self.actual()
        variants = {
            "no_startup_focus": ("startupFocusPending = true;", "startupFocusPending = false;", "First keyboard event lacks game focus"),
            "background_steal": ("!hasWindowFocus() || ", "", "Background startup stole focus"),
            "repeat_ordinary_focus": ("hideSystemUi(); requestHighRefresh(); restoreStartupFocus();",
                                      "hideSystemUi(); requestHighRefresh(); startupFocusPending = true; restoreStartupFocus();",
                                      "focus requested before overlay removal"),
            "drop_failed_request": ("if (touch.requestFocus()) startupFocusPending = false;",
                                    "touch.requestFocus(); startupFocusPending = false;", "Failed request lost pending focus"),
        }
        for name, (old, new, expected) in variants.items():
            with self.subTest(name=name):
                self.assertEqual(actual.count(old), 1)
                result = self.run_focus(actual.replace(old, new))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)


if __name__ == "__main__":
    unittest.main()
