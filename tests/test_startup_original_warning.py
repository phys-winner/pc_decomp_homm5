"""Execute the startup worker and its actual consent callbacks without loading a native engine."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT

ACTIVITY = ROOT / "android/app/src/org/homm5/port/GameActivity.java"

HARNESS = r'''
package org.homm5.port;
import java.io.*;
import java.util.*;
import java.nio.file.*;
import java.security.*;
import android.content.Context;
class android {
 static class R {static class style {static final int Theme_Material_Dialog_Alert=1;}
  static class string {static final int ok=1;}}
 static class util {static class Log {
  static int w(String tag,String value){return 0;}static int e(String tag,String value){return 0;}
  static int i(String tag,String value){return 0;}}}
 static class app {static class AlertDialog {
  interface Click {void run(AlertDialog dialog,int which);}interface Cancel {void run(AlertDialog dialog);}
  String message,positiveText,negativeText;Click positive,negative;Cancel canceled;boolean visible;
  static class Builder {
   final AlertDialog d=new AlertDialog();Builder(Object activity,int theme){}
   Builder setMessage(String message){d.message=message;return this;}
   Builder setPositiveButton(String text,Click click){d.positiveText=text;d.positive=click;return this;}
   Builder setPositiveButton(int text,Click click){return setPositiveButton(Integer.toString(text),click);}
   Builder setNegativeButton(String text,Click click){d.negativeText=text;d.negative=click;return this;}
   Builder setOnCancelListener(Cancel cancel){d.canceled=cancel;return this;}
   AlertDialog show(){d.visible=true;return d;}
  }
  void dismiss(){visible=false;}
  void yes(){positive.run(this,0);dismiss();}void no(){negative.run(this,0);dismiss();}
  void cancel(){canceled.run(this);dismiss();}
 }}
}
class NativeLibrary {
 static int loads;static boolean fail;
 static boolean available(Context c,String library){return true;}
 /* ACTUAL HASH */
 static void load(Object c,String library){loads++;if(fail)throw new UnsatisfiedLinkError("bad library");}
}
class Launch {final List<String> failed=new ArrayList<>();void failed(String reason){failed.add(reason);}}
public class GameActivity extends Context {
 static class Thread {
  static final Deque<Runnable> work=new ArrayDeque<>();final Runnable body;
  Thread(Runnable body,String name){assert name.equals("native-library");this.body=body;}
  void start(){work.add(body);}
 }
 private static String language;
 private final List<Runnable> ui=new ArrayList<>();private final List<String> dimEnds=new ArrayList<>();
 private final Launch launch=new Launch();private android.app.AlertDialog startupDialog;
 private boolean destroyed,finishing,nativeReady;private int started,openedLauncher;private String edition="toe";
 private File folder,executable;private static File root;
 private GameActivity(File assets,File own){super(assets,own);}
 private String gameEdition(){return edition;}private File gameFolder(){return folder;}
 private boolean isFinishing(){return finishing;}private boolean isDestroyed(){return destroyed;}
 private void runOnUiThread(Runnable body){ui.add(body);}private void chooseRenderer(){}
 private void launchTiming(String event){}
 private void startGame(){started++;}private void finishLaunchDimming(String reason){dimEnds.add(reason);}
 private void toLauncher(){openedLauncher++;finishing=true;}
 /* ACTUAL */
 private void runWorker(){assert !Thread.work.isEmpty();Thread.work.remove().run();}
 private void drainUi(){while(!ui.isEmpty())ui.remove(0).run();}
 private static void write(File file,String value)throws Exception {
  file.getParentFile().mkdirs();Files.write(file.toPath(),value.getBytes("UTF-8"));
 }
 private static GameActivity fresh(String edition,String lang)throws Exception {
  Thread.work.clear();NativeLibrary.loads=0;NativeLibrary.fail=false;language=lang;
  File dir=Files.createTempDirectory(root.toPath(),"case-").toFile(),assets=new File(dir,"assets");
  GameActivity a=new GameActivity(assets,new File(dir,"private"));a.edition=edition;a.folder=new File(dir,"game");
  for(String path:Games.required(edition))write(new File(a.folder,path),"original");
  String bin=edition.equals("hof")?"bina1/":"bin/";a.executable=Games.child(a.folder,bin+"H5_Game.exe");
  File granny=new File(a.folder,bin+"granny2.dll");write(granny,"original");
  String manifest=bin+"H5_Game.exe "+a.executable.length()+" "+NativeLibrary.sha256(a.executable)+"\n"
   +bin+"granny2.dll "+granny.length()+" "+NativeLibrary.sha256(granny)+"\n";
  write(new File(assets,Games.images(edition)+"/originals.txt"),manifest);
  write(new File(assets,Games.images(edition)+"/index.txt"),"originals.txt\n");
  write(a.executable,"another build");assert Games.installed(a.folder,edition);return a;
 }
 private void warning(){startLibrary(false);assert !Thread.work.isEmpty();runWorker();assert NativeLibrary.loads==0;
  assert startupDialog==null;drainUi();assert startupDialog.visible&&startupDialog.negative!=null;
  assert started==0&&!nativeReady&&launch.failed.isEmpty();assert dimEnds.equals(Arrays.asList("warning"));}
 public static void main(String[] args)throws Exception {
  root=new File(args[0]);assert root.mkdirs();
  for(String edition:new String[]{"toe","vanilla","hof"})for(String lang:new String[]{"ru","en"}) {
   GameActivity a=fresh(edition,lang);a.warning();
   assert a.startupDialog.message.contains(edition.equals("hof")?"bina1/H5_Game.exe":"bin/H5_Game.exe");
   assert a.startupDialog.message.contains(Games.title(edition));
   assert a.startupDialog.message.contains(lang.equals("ru")?"стабильность не гарантируется":"stability is not guaranteed");
   assert a.startupDialog.positiveText.equals(lang.equals("ru")?"Всё равно запустить":"Launch anyway");
   a.startupDialog.yes();assert NativeLibrary.loads==0&&Thread.work.size()==1;
   a.runWorker();a.drainUi();
   assert NativeLibrary.loads==1&&a.started==1&&a.nativeReady&&a.launch.failed.isEmpty();

   a=fresh(edition,lang);a.warning();a.startupDialog.no();
   assert a.openedLauncher==1&&Thread.work.isEmpty()&&NativeLibrary.loads==0;
   a=fresh(edition,lang);a.warning();a.startupDialog.cancel();
   assert a.openedLauncher==1&&Thread.work.isEmpty()&&NativeLibrary.loads==0;

   a=fresh(edition,lang);write(a.executable,"original");a.startLibrary(false);a.runWorker();a.drainUi();
   assert a.startupDialog==null&&NativeLibrary.loads==1&&a.started==1&&a.nativeReady;
   a=fresh(edition,lang);assert a.executable.delete();assert !Games.installed(a.folder,edition);
   a.startLibrary(false);a.runWorker();a.drainUi();
   assert a.startupDialog.negative==null&&NativeLibrary.loads==0&&a.started==0&&a.launch.failed.size()==1;
   a.startupDialog.yes();assert a.openedLauncher==1&&Thread.work.isEmpty();

   a=fresh(edition,lang);a.warning();assert a.executable.delete();assert !Games.installed(a.folder,edition);
   a.startupDialog.yes();a.runWorker();a.drainUi();
   assert a.startupDialog.negative==null&&NativeLibrary.loads==0&&a.started==0&&a.launch.failed.size()==1;
   a=fresh(edition,lang);write(a.executable,"original");NativeLibrary.fail=true;a.startLibrary(false);a.runWorker();a.drainUi();
   assert a.startupDialog.negative==null&&a.started==0&&a.launch.failed.size()==1;

   a=fresh(edition,lang);a.destroyed=true;a.startLibrary(false);assert Thread.work.isEmpty();
   a=fresh(edition,lang);a.startLibrary(false);a.runWorker();a.destroyed=true;a.drainUi();
   assert a.startupDialog==null&&NativeLibrary.loads==0&&a.started==0;
   a=fresh(edition,lang);a.warning();a.finishing=true;a.startupDialog.yes();assert Thread.work.isEmpty();
  }
  System.out.println("PASS startup: explicit per-start consent, cancel/back, hard failures, all editions/languages and destroyed activity");
 }
}
'''


class StartupOriginalWarningTest(unittest.TestCase):
    def test_actual_worker_and_consent_callbacks(self):
        source = ACTIVITY.read_text(encoding="utf-8")
        constants = re.search(r"    private static final int T_LOADING =.*?;", source, re.S).group()
        actual = constants + "\n" + function(source, "    private static String text(int id)")
        actual += "\n" + function(source, "    private void startLibrary(boolean allowUnsupported)")
        with tempfile.TemporaryDirectory(prefix="homm5-start-warning-") as folder:
            out = Path(folder)
            src = out / "GameActivity.java"
            app = ROOT / "android/app/src/org/homm5/port"
            files = {"GameActivity.java": HARNESS.replace("/* ACTUAL */", actual).replace("/* ACTUAL HASH */",
                        function((app / "NativeLibrary.java").read_text(), "    static String sha256(File file)")),
                     "Assets.java": (app / "Assets.java").read_text(), "Games.java": (app / "Games.java").read_text(),
                     "android/content/Context.java": '''package android.content;
                        import java.io.*;public class Context {
                         private final File assets,files;
                         public Context(File assets,File files){this.assets=assets;this.files=files;}
                         public Context getAssets(){return this;}public File getFilesDir(){return files;}
                         public InputStream open(String path)throws IOException{return new FileInputStream(new File(assets,path));}
                        }'''}
            for name, body in files.items():
                path = out / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
            subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out),
                            *[str(out / name) for name in files]], check=True)
            result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "org.homm5.port.GameActivity",
                                     str(out / "data")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("PASS startup:", result.stdout)
        self.assertIn("startLibrary(false);", function(source, "    @Override protected void onCreate(Bundle state)"))
        self.assertIn("if (startupDialog != null) startupDialog.dismiss();", function(source, "    @Override protected void onDestroy()"))
        self.assertNotIn("startupDialog", function(source, "    @Override protected void onPause()"))


if __name__ == "__main__":
    unittest.main()
