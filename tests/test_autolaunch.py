"""Run the launcher's actual routing against a real cross-process marker file."""
from pathlib import Path
import subprocess
import unittest

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT


FIXTURE = r'''
import java.io.File;
class Context { File files; File getFilesDir() { return files; } }
public class AutoLaunchCheck extends Context {
    static final String EXTRA_GAME="game";
    File base, game;
    File selected;
    String edition="toe";
    boolean permission=true, exited;
    int launches;
    static class Intent {
        boolean exited, show;
        String requested, source;
        String getStringExtra(String key) { return key.equals("launch_edition") ? requested : source; }
        boolean getBooleanExtra(String key, boolean fallback) { return key.equals("game_exited") ? exited : show; }
    }
    Intent intent=new Intent();
    Intent getIntent() { return intent; }
    boolean storage() { return permission; }
    static class Unpacker { static Object current; }
    static class Textures { static Object current; }
    static class Games {
        static boolean complete=true;
        static String marker(String id) { return "game-started"+(id.equals("toe") ? "" : "-"+id); }
        static boolean valid(String id) { return "toe".equals(id)||"vanilla".equals(id)||"hof".equals(id); }
        static boolean installed(File root,String id) { return complete; }
    }
    static class Assets { static boolean images=true; static boolean runtimeAvailable(Context c, File base, String id) { return images; } }
    static File chosenGame(Context c, Intent i, String id) { return ((AutoLaunchCheck)c).selected; }
    static String stamp="3:100";
    static String buildStamp(Context c) { return stamp; }
    void play() { assert game!=null && permission; ++launches; }
    /* ACTUAL */
    public static void main(String[] args) throws Exception {
        AutoLaunchCheck c=new AutoLaunchCheck(); c.files=new File(args[0]); c.base=c.files;
        c.files.mkdirs(); c.selected=new File(c.base,"game");
        File marker=startupMarker(c); if(marker.exists()) assert marker.delete();
        assert !c.autoLaunch() && c.launches==0;
        assert marker.createNewFile();
        assert !c.autoLaunch() && c.launches==0;   // a marker without this build's stamp
        markStarted(c, "toe");
        assert c.autoLaunch() && c.launches==1;
        c.intent.exited=true; assert !c.autoLaunch(); c.intent.exited=false;
        c.intent.show=true; assert !c.autoLaunch(); c.intent.show=false;
        c.edition="hof"; assert !c.autoLaunch(); c.edition="toe";
        c.permission=false; assert !c.autoLaunch(); c.permission=true;
        c.selected=null; assert !c.autoLaunch(); c.selected=new File(c.base,"game");
        Assets.images=false; assert !c.autoLaunch(); Assets.images=true;
        Unpacker.current=new Object(); assert !c.autoLaunch(); Unpacker.current=null;
        Textures.current=new Object(); assert !c.autoLaunch(); Textures.current=null;
        assert c.launches==1;
        // A new process/context sees the file without a stale SharedPreferences instance.
        AutoLaunchCheck next=new AutoLaunchCheck();next.files=c.files;next.base=c.base;next.selected=c.selected;
        assert next.autoLaunch() && next.launches==1;
        stamp="3:200"; assert !next.autoLaunch();   // updated since the last successful start
        markStarted(next, "toe"); assert next.autoLaunch() && next.launches==2;
        assert marker.delete(); assert !next.autoLaunch();
        // A switch is explicit and may start an installed game before its first successful boot.
        c.intent.exited=true; c.intent.requested="hof";c.intent.source=c.selected.getAbsolutePath();
        assert c.launchRequestedGame() && c.edition.equals("hof") && c.launches==2;
        c.intent.requested="unknown"; assert !c.launchRequestedGame();
        c.intent.requested="vanilla";c.intent.source=null;assert !c.launchRequestedGame();c.intent.source=c.selected.getAbsolutePath();
        Games.complete=false;assert !c.launchRequestedGame();Games.complete=true;
        Assets.images=false;assert !c.launchRequestedGame();Assets.images=true;
        c.permission=false;assert !c.launchRequestedGame();c.permission=true;
        Unpacker.current=new Object();assert !c.launchRequestedGame();Unpacker.current=null;
        Textures.current=new Object();assert !c.launchRequestedGame();Textures.current=null;
        assert c.launches==2;
        // A rejected explicit request must not silently fall back to the previous autolaunch.
        c.intent.requested="unknown";c.intent.exited=false;c.edition="toe";
        markStarted(c, "toe");assert !c.autoLaunch();assert marker.delete();
        System.out.println("PASS actual autolaunch: first start, persistent success, build stamp, explicit launcher return, permissions, files and active jobs");
    }
}
'''


class AutoLaunchTest(unittest.TestCase):
    def test_actual_launcher_routing(self):
        source = (ROOT / "android/app/src/org/homm5/port/Launcher.java").read_text(encoding="utf8")
        methods = (function(source, "static File startupMarker(") + function(source, "static File startupMarker(Context context, String edition)")
                   + function(source, "static void markStarted(") + function(source, "static boolean startedWithThisBuild(")
                   + function(source, "private boolean autoLaunch(") + function(source, "private boolean launchRequestedGame("))
        out = ROOT / "build/tests/autolaunch"
        out.mkdir(parents=True, exist_ok=True)
        java = out / "AutoLaunchCheck.java"
        java.write_text(FIXTURE.replace("/* ACTUAL */", methods), encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-d", str(out), str(java)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "AutoLaunchCheck", str(out / "files")], check=True)
        create = function(source, "protected void onCreate(")
        self.assertLess(create.index("if (autoLaunch()) return;"), create.index("build();"))
        activity = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        ready = activity[activity.index("            if (ready) {"):activity.index("                View done = loading;")]
        self.assertIn("Launcher.markStarted(GameActivity.this, gameEdition());", ready)
        self.assertIn("catch (java.io.IOException", ready)
        start = function(activity, "private void startGame(")
        self.assertLess(start.index("Launcher.startupMarker(this, gameEdition()).delete()"), start.index("nativeStart("))


if __name__ == "__main__":
    unittest.main()
