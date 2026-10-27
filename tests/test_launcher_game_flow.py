"""Execute the launcher's actual selection and Android switch callbacks in Java."""
from pathlib import Path
import subprocess
import sys
import unittest

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT

SOURCE = ROOT / 'android/app/src/org/homm5/port'


SELECTION = r'''
package org.homm5.port;
import java.io.*;
import java.nio.file.*;
import java.util.*;
public class LauncherSelectionCheck {
 static class SharedPreferences {
  Map<String,String> values=new HashMap<>();
  class Editor { Editor putString(String k,String v){values.put(k,v);return this;} void apply(){} }
  Editor edit(){return new Editor();}
 }
 static class Uri {File path;Uri(File p){path=p;}}
 static class Handler {volatile boolean done;void post(Runnable r){r.run();done=true;}}
 private SharedPreferences prefs=new SharedPreferences();private String edition="toe";private File game;
 private Handler handler=new Handler();private String busy,error;private int refreshes;
 private static final int T_SEARCHING=1,E_NO_PATH=2,E_FOLDER=3;
 private static String text(int n){return Integer.toString(n);}
 private static File treePath(Uri tree){return tree.path;}
 private void setBusy(String s){busy=s;}private void error(String s){error=s;}
 private void note(String s,boolean e){}private void refresh(){refreshes++;}
 /* ACTUAL */
 static void install(Path folder,String edition)throws Exception{
  for(String name:Games.required(edition)){Path p=folder.resolve(name);Files.createDirectories(p.getParent());Files.write(p,new byte[]{1,2,3});}
 }
 static Map<Path,byte[]> snapshot(Path root)throws Exception{
  Map<Path,byte[]> out=new HashMap<>();
  try(java.util.stream.Stream<Path> paths=Files.walk(root)){
   for(Path p:(Iterable<Path>)paths.filter(Files::isRegularFile)::iterator)out.put(p,Files.readAllBytes(p));
  }return out;
 }
 void choose(File folder)throws Exception{
  handler.done=false;chooseFolder(new Uri(folder));long until=System.nanoTime()+3_000_000_000L;
  while(!handler.done&&System.nanoTime()<until)Thread.sleep(1);
  assert handler.done&&error==null : error;
 }
 public static void main(String[] args)throws Exception{
  Path root=Files.createTempDirectory("heroes-launcher-flow-");
  try{
   Path common=root.resolve("Games"),gold=common.resolve("Gold"),toe=common.resolve("Tribes");
   install(gold,"vanilla");install(gold,"hof");install(toe,"toe");
   Map<Path,byte[]> before=snapshot(root);LauncherSelectionCheck ui=new LauncherSelectionCheck();
   ui.prefs.values.put(Games.pathKey("toe"),toe.toString());
   ui.choose(gold.resolve("DataLS").toFile());
   assert ui.edition.equals("vanilla")&&ui.game.equals(gold.toFile());
   assert ui.prefs.values.get(Games.pathKey("vanilla")).equals(gold.toString());
   assert ui.prefs.values.get(Games.pathKey("hof")).equals(gold.toString());
   assert ui.prefs.values.get(Games.pathKey("toe")).equals(toe.toString());
   ui.edition="toe";ui.choose(common.toFile());
   assert ui.edition.equals("toe")&&ui.game.equals(toe.toFile());
   assert ui.prefs.values.get(Games.pathKey("vanilla")).equals(gold.toString());
   assert ui.prefs.values.get(Games.pathKey("hof")).equals(gold.toString());
   int refreshes=ui.refreshes;Map<String,String> saved=new HashMap<>(ui.prefs.values);
   ui.select(root.resolve("incomplete").toFile());assert ui.refreshes==refreshes&&ui.prefs.values.equals(saved);
   Map<Path,byte[]> after=snapshot(root);assert before.keySet().equals(after.keySet());
   for(Path p:before.keySet())assert Arrays.equals(before.get(p),after.get(p));
   System.out.println("PASS actual folder flow: inner DataLS, combined Vanilla/HoF, parent discovery, retained ToE path, incomplete root, original bytes");
  }finally{Unpacker.delete(root.toFile());}
 }
}
'''


SWITCH = r'''
package org.homm5.port;
import java.io.*;
import java.nio.file.*;
import java.lang.ref.WeakReference;
import java.util.*;
class Context {
 static final int MODE_PRIVATE=0;final Prefs prefs=new Prefs();
 Prefs getSharedPreferences(String s,int mode){return prefs;}
 static class Prefs {Map<String,String> values=new HashMap<>();Editor edit(){return new Editor();}
  class Editor {Editor putString(String k,String v){values.put(k,v);return this;}void apply(){}}}
}
class Intent {
 static final int FLAG_ACTIVITY_NEW_TASK=1,FLAG_ACTIVITY_CLEAR_TASK=2;
 Class<?> target;int flags;Map<String,Object> extras=new HashMap<>();
 Intent(Context c,Class<?> t){target=t;}Intent putExtra(String k,Object v){extras.put(k,v);return this;}
 Intent addFlags(int f){flags|=f;return this;}
}
class Assets {static Set<String> available=new HashSet<>();static boolean runtimeAvailable(Context c,File base,String id){return available.contains(id);}}
class Launcher {
 static final String PREFS="launcher",EXTRA_GAME="game";static File base;static Map<String,File> folders=new HashMap<>();
 static File baseDir(){return base;}
 static File chosenGame(Context c,Intent i,String id){File f=folders.get(id);return Games.installed(f,id)?f:null;}
 /* READY */
 /* CLASSES */
}
class VanillaGameActivity extends GameActivity {}class HofGameActivity extends GameActivity {}
class android {
 static class R {static class style {static final int Theme_Material_Dialog_Alert=16974374;}}
 static class app {static class AlertDialog {
 interface Click {void run(AlertDialog d,int which);}interface Dismiss {void run(AlertDialog d);}
 String[] titles;Click item,neutral;Dismiss dismissed;boolean visible;int theme;
 static class Builder {
  AlertDialog d=new AlertDialog();Builder(Context c){}Builder(Context c,int theme){d.theme=theme;}Builder setTitle(String t){return this;}
  Builder setItems(String[] t,Click c){d.titles=t;d.item=c;return this;}
  Builder setNeutralButton(String t,Click c){d.neutral=c;return this;}
  Builder setNegativeButton(String t,Click c){return this;}AlertDialog create(){return d;}
 }
 void setOnDismissListener(Dismiss d){dismissed=d;}void show(){visible=true;}
 void dismiss(){visible=false;if(dismissed!=null)dismissed.run(this);}
 void select(int i){item.run(this,i);dismiss();}void launcher(){neutral.run(this,0);dismiss();}
}}}
public class GameActivity extends Context {
 private static volatile WeakReference<GameActivity> currentActivity=new WeakReference<>(null);
 private android.app.AlertDialog gameSwitchDialog;private volatile Intent pendingGameLaunch;
 private String edition="toe";private String gameEdition(){return edition;}
 private static final int T_CURRENT_GAME=1,T_SWITCH_GAME=2,T_OPEN_LAUNCHER=3,T_CANCEL=4;
 private static String text(int n){return Integer.toString(n);}
 private static int requests;private int uiPosts,releases;private List<Intent> started=new ArrayList<>();
 private static void nativeRequestGameSwitch(){requests++;}
 private boolean isFinishing(){return false;}private boolean isDestroyed(){return false;}
 private void releaseAll(){releases++;}private void hideSystemUi(){}
 private static class Touch {void requestFocus(){}}private Touch touch=new Touch();
 private void runOnUiThread(Runnable r){uiPosts++;r.run();}
 private void startActivity(Intent i){started.add(i);}
 /* ACTUAL */
 static void install(Path root,String id)throws Exception{
  for(String name:Games.required(id)){Path p=root.resolve(name);Files.createDirectories(p.getParent());Files.write(p,new byte[]{1});}
 }
 static GameActivity fresh(){GameActivity a=new GameActivity();currentActivity=new WeakReference<>(a);return a;}
 public static void main(String[] args)throws Exception{
  Path root=Files.createTempDirectory("heroes-switch-flow-");
  try{
   Launcher.base=root.toFile();for(String id:Games.IDS){Path p=root.resolve(id);install(p,id);Launcher.folders.put(id,p.toFile());Assets.available.add(id);}
   GameActivity a=fresh();onSwitchGame();assert a.gameSwitchDialog.titles.length==3&&a.releases==1;
   assert a.gameSwitchDialog.theme==android.R.style.Theme_Material_Dialog_Alert : "Switch list and buttons must use a coherent dark dialog theme";
   a.gameSwitchDialog.dismiss();assert requests==0&&a.pendingGameLaunch==null&&a.started.isEmpty();
   onSwitchGame();a.gameSwitchDialog.select(2);assert requests==0&&a.pendingGameLaunch==null;
   onSwitchGame();Assets.available.remove("hof");a.gameSwitchDialog.select(1);assert requests==0;Assets.available.add("hof");
   File hof=Launcher.folders.remove("hof");assert Launcher.readyGames(a).equals(Arrays.asList("vanilla","toe"));Launcher.folders.put("hof",hof);
   onSwitchGame();a.gameSwitchDialog.select(0);
   assert requests==1&&a.started.isEmpty()&&a.pendingGameLaunch.target==Launcher.class;
   assert a.pendingGameLaunch.extras.get(Launcher.EXTRA_GAME).equals(Launcher.folders.get("vanilla").getAbsolutePath());
   assert a.pendingGameLaunch.extras.get("launch_edition").equals("vanilla");
   assert a.prefs.values.isEmpty();int posts=a.uiPosts;
   onGameExit();assert a.started.size()==1&&a.started.get(0).target==Launcher.class&&a.uiPosts==posts;
   a=fresh();onSwitchGame();a.gameSwitchDialog.launcher();assert requests==2&&a.started.isEmpty();
   onGameExit();Intent next=a.started.get(0);assert next.target==Launcher.class;
   assert Boolean.TRUE.equals(next.extras.get("show_launcher"))&&Boolean.TRUE.equals(next.extras.get("game_exited"));
   a=fresh();onGameExit();assert a.started.size()==1&&a.started.get(0).target==Launcher.class;
   assert (a.started.get(0).flags&Intent.FLAG_ACTIVITY_CLEAR_TASK)!=0;
   System.out.println("PASS actual Android switch flow: installed/runtime filtering, cancel/current no exit, missing runtime race, deferred target launch, synchronous JNI exit callback, launcher escape");
  }finally{Unpacker.delete(root.toFile());}
 }
}
'''


class LauncherGameFlowTest(unittest.TestCase):
    def java(self, name, source):
        out = ROOT / 'build/tests/launcher-game-flow' / name
        out.mkdir(parents=True, exist_ok=True)
        path = out / (name + '.java')
        path.write_text(source, encoding='utf8')
        files = [SOURCE / (n + '.java') for n in ('Games', 'Zip', 'Deflate64', 'Unpacker')]
        subprocess.run([str(JAVA / 'javac.exe'), '--release', '8', '-encoding', 'UTF-8', '-d', str(out), *map(str, files), str(path)], check=True)
        subprocess.run([str(JAVA / 'java.exe'), '-ea', '-cp', str(out), 'org.homm5.port.' + name], check=True)

    def test_actual_global_folder_selection_registers_all_detected_editions(self):
        source = (SOURCE / 'Launcher.java').read_text(encoding='utf8')
        methods = '\n'.join(function(source, signature) for signature in ('private void select(File root)', 'private void chooseFolder(Uri tree)'))
        self.java('LauncherSelectionCheck', SELECTION.replace('/* ACTUAL */', methods))

    def test_actual_game_switch_dialog_and_native_exit_routing(self):
        source = (SOURCE / 'GameActivity.java').read_text(encoding='utf8')
        launcher = (SOURCE / 'Launcher.java').read_text(encoding='utf8')
        methods = '\n'.join(function(source, signature) for signature in (
            'private static void onGameExit()', 'private static void onSwitchGame()',
            'private void showGameSwitch()', 'private void switchToGame(String edition)'))
        fixture = SWITCH.replace('/* ACTUAL */', methods)
        fixture = fixture.replace('/* READY */', function(launcher, 'static List<String> readyGames('))
        fixture = fixture.replace('/* CLASSES */', function(launcher, 'static Class<? extends GameActivity> gameClass('))
        self.java('GameActivity', fixture)

    def test_global_picker_precedes_launch_cards_without_per_card_choose_buttons(self):
        source = (SOURCE / 'Launcher.java').read_text(encoding='utf8')
        build = function(source, 'private void build()')
        cards = function(source, 'private void refreshEditions(')
        self.assertLess(build.index('archiveButton = button('), build.index('column.addView(editionCards)'))
        self.assertLess(build.index('folderButton = button('), build.index('column.addView(editionCards)'))
        self.assertNotIn('T_SELECT_GAME', cards)
        self.assertIn('playEdition(id)', cards)


if __name__ == '__main__':
    unittest.main()
