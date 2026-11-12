"""Run the Activity's contextual hints and the shared skip action without Android."""
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import posixpath

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT


HARNESS = r'''
import java.io.*;
import java.lang.ref.WeakReference;
import java.util.*;
public class TouchHintsCheck {
 static WeakReference<TouchHintsCheck> currentActivity = new WeakReference<>(null);
 static String language="en";
 static File files;
 static class Handler {
  final ArrayDeque<Runnable> tasks=new ArrayDeque<>();
  void postDelayed(Runnable task,long delay){assert delay==8000;tasks.add(task);}
  void next(){tasks.remove().run();}
 }
 static class View {static final int ACCESSIBILITY_LIVE_REGION_POLITE=1;}
 static class Color {static final int WHITE=-1;}
 static class Gravity {static final int TOP=48;}
 static class TextView {
  String text;boolean clickable;int liveRegion;
  TextView(Object context){} void setText(String text){this.text=text;}
  void setTextColor(int color){assert color==Color.WHITE;} void setTextSize(int size){assert size==16;}
  void setPadding(int a,int b,int c,int d){assert a==16&&b==12&&c==16&&d==12;}
  void setBackgroundColor(int color){assert color==0xE0202020;}
  void setAccessibilityLiveRegion(int mode){liveRegion=mode;}
 }
 static class FrameLayout {
  static class LayoutParams {
   LayoutParams(int w,int h,int gravity){assert w==-1&&h==-2&&gravity==Gravity.TOP;}
   void setMargins(int a,int b,int c,int d){assert a==24&&b==24&&c==24&&d==0;}
  }
  final List<TextView> children=new ArrayList<>();
  void addView(TextView view,LayoutParams layout){children.add(view);}
  void removeView(TextView view){children.remove(view);}
 }
 static class android {static class util {static class Log {
  static int errors;static void w(String tag,String message,Throwable error){errors++;}
 }}static class widget {static class Toast {
  static final int LENGTH_LONG=1;static int errors;
  static Toast makeText(Object activity,String text,int duration){assert !text.isEmpty();errors++;return new Toast();}
  void show(){}
 }}}
 int pendingTouchHints;boolean showingTouchHint,resumed=true,nativeReady=true,finishing,destroyed,deferUi;
 TextView touchHintView;FrameLayout touchHintHost;
 FrameLayout game=new FrameLayout();Handler handler=new Handler();ArrayDeque<Runnable> ui=new ArrayDeque<>();
 TouchHintsCheck(String edition){currentActivity=new WeakReference<>(this);}
 File getFilesDir(){return files;} boolean isFinishing(){return finishing;} boolean isDestroyed(){return destroyed;}
 void runOnUiThread(Runnable task){if(deferUi)ui.add(task);else task.run();}
 int dp(int value){return value;}
 static int shown(){int count=0;for(int id=1;id<=4;id++)if(new File(files,"touch-hint-"+id+"-shown").isFile())count++;return count;}
 static void resetShown(){for(int id=1;id<=4;id++)new File(files,"touch-hint-"+id+"-shown").delete();}
 /* ACTUAL */
 public static void main(String[] args) throws Exception {
  files=new File(args[0]);assert files.isDirectory();
  for(String lang:new String[]{"ru","uk","be","en"}) {
   language=lang;
   assert touchHintText(1).contains(lang.equals("en")?"two fingers":"двумя пальцами");
   assert touchHintText(2).contains("~");
   assert touchHintText(2).contains(lang.equals("en")?"scenario information":"информации о сценарии");
   assert touchHintText(3).contains(lang.equals("en")?"moving hero":"движущегося героя");
   assert touchHintText(4).contains(lang.equals("en")?"three fingers":"тремя пальцами");
  }
  language="en";assert touchHintText(-1).isEmpty()&&touchHintText(9).isEmpty();
  TouchHintsCheck a=new TouchHintsCheck("toe");
  showTouchHint(-1);showTouchHint(5);assert a.game.children.isEmpty()&&a.pendingTouchHints==0;
  showTouchHint(2);showTouchHint(4);showTouchHint(1);showTouchHint(3);showTouchHint(2);showTouchHint(4);
  assert a.game.children.size()==1&&a.handler.tasks.size()==1&&shown()==1;
  assert a.touchHintView.text.equals(touchHintText(2))&&!a.touchHintView.clickable;
  assert a.touchHintView.liveRegion==View.ACCESSIBILITY_LIVE_REGION_POLITE;
  for(int id:new int[]{1,3,4}) {
   a.handler.next();assert a.game.children.size()==1&&a.touchHintView.text.equals(touchHintText(id));
  }
  a.handler.next();assert a.game.children.isEmpty()&&!a.showingTouchHint&&a.pendingTouchHints==0;
  for(int id=1;id<=4;id++)showTouchHint(id);
  assert a.game.children.isEmpty()&&a.handler.tasks.isEmpty()&&shown()==4;
  TouchHintsCheck restart=new TouchHintsCheck("toe");showTouchHint(1);assert restart.game.children.isEmpty();
  // Showing a type in one edition consumes it for every other edition and process too.
  for(String edition:new String[]{"toe","vanilla","hof"}) {
   TouchHintsCheck editionActivity=new TouchHintsCheck(edition);
   for(int id=1;id<=4;id++)showTouchHint(id);
   assert editionActivity.game.children.isEmpty()&&editionActivity.pendingTouchHints==0;
  }
  resetShown();
  TouchHintsCheck legacy=new TouchHintsCheck("vanilla");legacy.resumed=false;
  showTouchHint(1);showTouchHint(3);assert shown()==0&&legacy.game.children.isEmpty();
  legacy.resumed=true;legacy.showNextTouchHint();assert shown()==1;
  legacy.handler.next();assert legacy.touchHintView.text.equals(touchHintText(3));legacy.handler.next();
  legacy.nativeReady=false;showTouchHint(4);assert legacy.game.children.isEmpty();
  legacy.nativeReady=true;legacy.showNextTouchHint();assert legacy.touchHintView.text.equals(touchHintText(4));
  legacy.handler.next();
  TouchHintsCheck pending=new TouchHintsCheck("hof");pending.deferUi=true;showTouchHint(2);
  resetShown();
  TouchHintsCheck other=new TouchHintsCheck("other");pending.ui.remove().run();assert pending.pendingTouchHints==0;
  other.finishing=true;showTouchHint(1);assert other.pendingTouchHints==0;
  other.finishing=false;other.destroyed=true;showTouchHint(1);assert other.pendingTouchHints==0;
  other.destroyed=false;showTouchHint(1);showTouchHint(4);assert other.showingTouchHint;
  showTouchHint(0);assert new File(files,"touch-hints-skipped").isFile();
  assert other.pendingTouchHints==0&&other.game.children.isEmpty()&&!other.showingTouchHint;
  other.handler.next();showTouchHint(2);assert other.game.children.isEmpty();
  // Each engine process consults the common marker even with its own cached preferences.
  for(String edition:new String[]{"toe","vanilla","hof"}) {
   TouchHintsCheck editionActivity=new TouchHintsCheck(edition);
   for(int id=1;id<=4;id++)showTouchHint(id);
   assert editionActivity.pendingTouchHints==0&&editionActivity.game.children.isEmpty();
   showTouchHint(0);assert android.widget.Toast.errors==0;
  }
  File marker=new File(files,"touch-hints-skipped");assert marker.delete()&&marker.mkdir();
  TouchHintsCheck failure=new TouchHintsCheck("failure");showTouchHint(0);
  assert android.widget.Toast.errors==1&&!marker.isFile();
  resetShown();
  showTouchHint(1);assert failure.showingTouchHint; // A failed save must not silently disable hints.
  failure.handler.next();
  assert marker.delete();
  File occupied=new File(files,"touch-hint-2-shown");assert occupied.mkdir();showTouchHint(2);
  assert failure.game.children.isEmpty()&&!failure.showingTouchHint;
  assert occupied.delete();showTouchHint(2);assert failure.showingTouchHint;
  System.out.println("PASS actual localized one-time hints, queued nonmodal views, lifecycle, persistence, all-edition skip and I/O failure");
 }
}
'''


def button_background_regions(members, game, edition, button_name="UI/PortSkipHints.(WindowMSButton).xdb"):
    import port_ui

    def resource(href, parent=""):
        path = href.split("#", 1)[0]
        path = path.lstrip("/") if path.startswith("/") else posixpath.normpath(posixpath.join(posixpath.dirname(parent), path))
        data = members[path] if path in members else port_ui.source_resource(game, path, edition)[0]
        return path, ET.fromstring(data)

    path, button = resource("/" + button_name)
    path, shared = resource(button.find("Shared").get("href"), path)
    placement = button if button.findtext("Placement/Size/Second") == "true" else shared
    window_size = tuple(int(placement.findtext("Placement/Size/First/" + axis)) for axis in ("x", "y"))
    regions = []
    for layer in shared.findall("VisualStates/Item/*/Background") + shared.findall("VisualStates/Item/*/Foreground"):
        if not layer.get("href"):
            continue
        background_path, background = resource(layer.get("href"), path)
        _, texture = resource(background.find("Texture").get("href"), background_path)
        texture_size = tuple(int(texture.findtext(axis)) for axis in ("Width", "Height"))
        if background.tag == "BackgroundSimpleScallingTexture":
            assert background.findtext("ClassTypeID") == "285694784"
            source_size = tuple(int(background.findtext("Size/" + axis)) for axis in ("x", "y"))
            regions.append((texture_size, source_size, window_size))
        else:
            assert background.tag == "BackgroundSimpleTexture"
            regions.append((texture_size, texture_size, texture_size))
    return regions


class TouchHintsTest(unittest.TestCase):
    def test_actual_activity_hints(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf-8")
        methods = "\n".join(function(source, signature) for signature in (
            "    private static String cheatText(String english, String russian)",
            "    private static String touchHintText(int id)",
            "    private static void showTouchHint(int id)",
            "    private void showNextTouchHint()"))
        methods = methods.replace("GameActivity", "TouchHintsCheck")
        out = ROOT / "build/tests/touch-hints"
        out.mkdir(parents=True, exist_ok=True)
        src = out / "TouchHintsCheck.java"
        src.write_text(HARNESS.replace("/* ACTUAL */", methods), encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(src)], check=True)
        with tempfile.TemporaryDirectory(dir=out) as files:
            result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "TouchHintsCheck", files],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS actual localized", result.stdout)
        self.assertIn("showNextTouchHint();", function(source, "    @Override protected void onResume()"))

    def test_skip_button_is_wired_and_fits_all_editions(self):
        import port_ui
        from editions import game_directory
        parent = "UI/GameOptions/CategoryPanel.(WindowSimpleShared).xdb"
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                members = port_ui.launcher_buttons(game_directory(edition), edition)
                children = ET.fromstring(members[parent]).find("Children")
                self.assertEqual(sum("PortOptionsLauncher." in item.get("href", "") for item in children), 1)
                self.assertEqual(sum("PortSkipHints." in item.get("href", "") for item in children), 1)
                button = ET.fromstring(members["UI/PortSkipHints.(WindowMSButton).xdb"])
                self.assertEqual(button.findtext("Visible"), "false")
                self.assertEqual(button.findtext("Placement/Position/First/y"), "472")
                x = int(button.findtext("Placement/Position/First/x"))
                width = int(button.findtext("Placement/Size/First/x"))
                self.assertEqual(width, 234)
                regions = button_background_regions(members, game_directory(edition), edition)
                self.assertEqual(len(regions), 5)
                self.assertEqual(set(regions), {((122, 34), (122, 34), (width, 34))})
                shared = ET.fromstring(members["UI/PortSkipHints.(WindowMSButtonShared).xdb"])
                self.assertEqual(shared.findtext("Placement/Size/First/x"), str(width))
                self.assertEqual(shared.findtext("Placement/Size/Second"), "true")
                panel = ET.fromstring(port_ui.source_resource(game_directory(edition),
                    "UI/GameOptions/CategoryPanel.(WindowSimple).xdb", edition)[0])
                self.assertLessEqual(x + width, int(panel.findtext("Placement/Size/First/x")))
                reaction = ET.fromstring(members["UI/PortSkipHints.(ARSendGameMessage).xdb"])
                self.assertEqual(reaction.findtext("EventName"), "port_skip_hints")
                self.assertIn("Пропустить все", port_ui.texts(edition)["UI/PortSkipHints.txt"].decode("utf16"))

    def test_original_fixed_texture_rejects_a_wider_button(self):
        import port_ui
        from editions import game_directory
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                game = game_directory(edition)
                members = port_ui.launcher_buttons(game, edition)
                name = "UI/PortSkipHints.(WindowMSButton).xdb"
                button = ET.fromstring(members[name])
                button.find("Shared").set("href", "/UI/Common/DlgButtons/Button_122_34.(WindowMSButtonShared).xdb#xpointer(/WindowMSButtonShared)")
                members[name] = ET.tostring(button)
                regions = button_background_regions(members, game, edition)
                self.assertEqual(set(regions), {((122, 34), (122, 34), (122, 34))})
                self.assertNotEqual(set(regions), {((122, 34), (122, 34), (234, 34))})

    def test_scaling_background_size_is_source_not_destination(self):
        import port_ui
        from editions import game_directory
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                game = game_directory(edition)
                members = port_ui.launcher_buttons(game, edition)
                for name in list(members):
                    if name.startswith("UI/PortSkipHints_") and "BackgroundSimpleScallingTexture" in name:
                        background = ET.fromstring(members[name])
                        background.find("Size/x").text = "234"
                        members[name] = ET.tostring(background)
                regions = button_background_regions(members, game, edition)
                self.assertEqual(set(regions), {((122, 34), (234, 34), (234, 34))})
                self.assertTrue(all(source[0] > texture[0] for texture, source, destination in regions))

    def test_custom_row_clears_native_apply_background_and_hitbox(self):
        import port_ui
        from editions import game_directory
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                game = game_directory(edition)
                members = port_ui.launcher_buttons(game, edition)
                main = ET.fromstring(port_ui.source_resource(game, "UI/GameOptions/GameOptionsPanel.(WindowSimple).xdb", edition)[0])
                category = ET.fromstring(port_ui.source_resource(game, "UI/GameOptions/CategoryPanel.(WindowSimple).xdb", edition)[0])
                accept_name = "UI/GameOptions/Accept.(WindowMSButton).xdb"
                accept = ET.fromstring(port_ui.source_resource(game, accept_name, edition)[0])
                self.assertEqual(accept.findtext("Placement/VerAllign/First"), "EPA_HIGH_END")
                regions = button_background_regions(members, game, edition, accept_name)
                self.assertEqual({destination for texture, source, destination in regions}, {(122, 34)})
                accept_top = int(main.findtext("Placement/Size/First/y")) + int(accept.findtext("Placement/Position/First/y")) - 34
                accept_left = int(main.findtext("Placement/Size/First/x")) + int(accept.findtext("Placement/Position/First/x")) - 122
                accept_bounds = (accept_left, accept_top, accept_left + 122, accept_top + 34)
                category_x = int(category.findtext("Placement/Position/First/x"))
                category_y = int(category.findtext("Placement/Position/First/y"))
                previous_right = None
                for name in ("PortOptionsLauncher", "PortSkipHints"):
                    path = "UI/" + name + ".(WindowMSButton).xdb"
                    button = ET.fromstring(members[path])
                    height = int(button.findtext("Placement/Size/First/y"))
                    self.assertEqual({destination for texture, source, destination in button_background_regions(members, game, edition, path)},
                                     {(int(button.findtext("Placement/Size/First/x")), height)})
                    bottom = category_y + int(button.findtext("Placement/Position/First/y")) + height
                    left = category_x + int(button.findtext("Placement/Position/First/x"))
                    right = left + int(button.findtext("Placement/Size/First/x"))
                    self.assertLessEqual(right, category_x + int(category.findtext("Placement/Size/First/x")))
                    if previous_right is not None:
                        self.assertGreaterEqual(left - previous_right, 16)
                    previous_right = right
                    bounds = (left, bottom - height, right, bottom)
                    self.assertFalse(bounds[0] < accept_bounds[2] and bounds[2] > accept_bounds[0]
                                     and bounds[1] < accept_bounds[3] and bounds[3] > accept_bounds[1])
                    self.assertLessEqual(bottom + 8, accept_top)
                    for scale in (.5, 1, 1.5, 2):
                        self.assertLessEqual((bottom + 8) * scale, accept_top * scale)
                # Negative control: the old custom row intersects the real native Apply row by 10 units.
                self.assertEqual(category_y + 490 + 34 - accept_top, 10)


if __name__ == "__main__":
    unittest.main()
