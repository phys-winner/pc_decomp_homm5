"""Run the actual cleanup of legacy edition tasks; manifest routing is checked by the APK tests."""
import subprocess
import unittest

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT


class RecentsTest(unittest.TestCase):
    def test_legacy_tasks_are_removed_without_removing_the_current_task(self):
        source = (ROOT / "android/app/src/org/homm5/port/LauncherHooks.java").read_text(encoding="utf-8")
        self.assertIn("keepCurrentTask(context);", function(source, "    @Override public void migrate(Context context)"))
        method = function(source, "    private static void keepCurrentTask(Context context)")
        program = r'''
import java.util.*;
class Context {
    static final String ACTIVITY_SERVICE="activity";
    Object getSystemService(String name){throw new AssertionError("not an activity");}
}
class Activity extends Context {
    ActivityManager manager=new ActivityManager();boolean finishing,destroyed;
    boolean isFinishing(){return finishing;}boolean isDestroyed(){return destroyed;}
    int getTaskId(){return 7;}
    Object getSystemService(String name){return manager;}
}
class ActivityManager {
    List<AppTask> tasks=new ArrayList<>();
    List<AppTask> getAppTasks(){return tasks;}
    static class RecentTaskInfo {int persistentId;RecentTaskInfo(int id){persistentId=id;}}
    static class AppTask {
        final int id;boolean gone,removed;
        AppTask(int id){this.id=id;}
        RecentTaskInfo getTaskInfo(){if(gone)throw new IllegalArgumentException();return new RecentTaskInfo(id);}
        void finishAndRemoveTask(){assert id!=7;removed=true;}
    }
}
class android {static class util {static class Log {static void w(String tag,String text,Throwable error){}}}}
public class RecentsCheck {
/* ACTUAL */
    public static void main(String[] args){
        Activity current=new Activity();
        ActivityManager.AppTask old=new ActivityManager.AppTask(3),same=new ActivityManager.AppTask(7),
            gone=new ActivityManager.AppTask(9),other=new ActivityManager.AppTask(11);
        gone.gone=true;current.manager.tasks.addAll(Arrays.asList(old,same,gone,other));
        keepCurrentTask(current);
        assert old.removed&&other.removed&&!same.removed;
        old.removed=false;current.finishing=true;keepCurrentTask(current);assert !old.removed;
        current.finishing=false;current.destroyed=true;keepCurrentTask(current);assert !old.removed;
        keepCurrentTask(new Context());
        System.out.println("PASS recents: keep current task, remove old edition tasks, tolerate removed tasks and obsolete owners");
    }
}
'''.replace("/* ACTUAL */", method)
        out = ROOT / "build/tests/recents"
        out.mkdir(parents=True, exist_ok=True)
        java = out / "RecentsCheck.java"
        java.write_text(program, encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-Xlint:-options", "-d", str(out), str(java)], check=True)
        result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "RecentsCheck"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS recents", result.stdout)


if __name__ == "__main__":
    unittest.main()
