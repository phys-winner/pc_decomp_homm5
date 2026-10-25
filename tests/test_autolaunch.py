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
    File base, game;
    File selected;
    boolean permission=true, exited;
    int launches;
    static class Intent {
        boolean exited;
        boolean getBooleanExtra(String key, boolean fallback) { assert key.equals("game_exited"); return exited; }
    }
    Intent intent=new Intent();
    Intent getIntent() { return intent; }
    boolean storage() { return permission; }
    static class Unpacker { static Object current; }
    static class Textures { static Object current; }
    static class Assets { static boolean images=true; static boolean carriesImages(Context c) { return images; } }
    static File chosenGame(Context c, Intent i) { return ((AutoLaunchCheck)c).selected; }
    void play() { assert game!=null && permission; ++launches; }
    /* ACTUAL */
    public static void main(String[] args) throws Exception {
        AutoLaunchCheck c=new AutoLaunchCheck(); c.files=new File(args[0]); c.base=c.files;
        c.files.mkdirs(); c.selected=new File(c.base,"game");
        File marker=startupMarker(c); if(marker.exists()) assert marker.delete();
        assert !c.autoLaunch() && c.launches==0;
        assert marker.createNewFile();
        assert c.autoLaunch() && c.launches==1;
        c.intent.exited=true; assert !c.autoLaunch(); c.intent.exited=false;
        c.permission=false; assert !c.autoLaunch(); c.permission=true;
        c.selected=null; assert !c.autoLaunch(); c.selected=new File(c.base,"game");
        Assets.images=false; assert !c.autoLaunch(); Assets.images=true;
        Unpacker.current=new Object(); assert !c.autoLaunch(); Unpacker.current=null;
        Textures.current=new Object(); assert !c.autoLaunch(); Textures.current=null;
        assert c.launches==1;
        // A new process/context sees the file without a stale SharedPreferences instance.
        AutoLaunchCheck next=new AutoLaunchCheck();next.files=c.files;next.base=c.base;next.selected=c.selected;
        assert next.autoLaunch() && next.launches==1;
        assert marker.delete(); assert !next.autoLaunch();
        System.out.println("PASS actual autolaunch: first start, persistent success, explicit launcher return, permissions, files and active jobs");
    }
}
'''


class AutoLaunchTest(unittest.TestCase):
    def test_actual_launcher_routing(self):
        source = (ROOT / "android/app/src/org/homm5/port/Launcher.java").read_text(encoding="utf8")
        methods = function(source, "static File startupMarker(") + function(source, "private boolean autoLaunch(")
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
        self.assertIn("Launcher.startupMarker(GameActivity.this).createNewFile();", ready)
        self.assertIn("catch (java.io.IOException", ready)


if __name__ == "__main__":
    unittest.main()
