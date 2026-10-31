"""Updating from the port's own launcher: its SharedPreferences become the launcher base's choices
(LauncherHooks, Launch.adopt) under the names the base reads (Install.key, options, intro, last),
with the base's real state files in Java."""
from pathlib import Path
import re
import shutil
import unittest

from test_launcher_base import APP, LAUNCHER, PLATFORM_JAR, ROOT, java, javac, prepare
from test_d3d_lifecycle import function

CHECK = r'''
package org.homm5.port.launcher;
import java.io.File;
import java.util.*;
import org.homm5.port.LauncherHooks;

public class MigrationCheck {
    static Spec.Distribution edition(String id) {
        Spec.Distribution d = new Spec.Distribution();
        d.id = id;
        Spec.Part p = new Spec.Part();
        p.id = "game";
        d.parts.add(p);
        return d;
    }

    public static void main(String[] args) throws Exception {
        File dir = new File(args[0]);
        /* The old launcher's preferences of a player who used all three editions. */
        Map<String, Object> old = new HashMap<>();
        old.put("game", "/storage/emulated/0/Games/Tribes");
        old.put("game-vanilla", "/storage/emulated/0/Games/Gold");
        old.put("game-hof", "/storage/emulated/0/Games/Gold");
        old.put("edition", "hof");
        old.put("skip_intro", false);
        old.put("new_creature_framework", true);
        old.put("lan_peers", " 192.0.2.2, peer.example \n");
        old.put("tex_info", true);
        old.put("unpacking", "/storage/emulated/0/HeroesV");
        Map<String, String> choices = LauncherHooks.choices(old);
        Map<String, String> expected = new LinkedHashMap<>();
        for (String id : new String[] {"vanilla", "hof", "toe"})
            expected.put(Install.key(edition(id), edition(id).parts.get(0)), (String) old.get(id.equals("toe") ? "game" : "game-" + id));
        expected.put("last", "hof");
        for (String id : new String[] {"vanilla", "hof", "toe"}) expected.put("intro." + id, "0");
        expected.put("option.new_creature_framework", "1");
        expected.put("option.lan_peers", "192.0.2.2, peer.example");
        assert choices.equals(expected) : choices;
        assert Install.key(edition("toe"), edition("toe").parts.get(0)).equals("part.toe.game");

        /* The base takes what the player has not chosen in it yet. */
        State.update(dir, State.CHOICES, values -> values.setProperty("option.lan_peers", "192.0.2.9"));
        List<String> taken = Launch.adopt(dir, choices);
        Properties state = State.read(dir, State.CHOICES);
        assert "/storage/emulated/0/Games/Tribes".equals(state.getProperty("part.toe.game"));
        assert "/storage/emulated/0/Games/Gold".equals(state.getProperty("part.hof.game"))
            && "/storage/emulated/0/Games/Gold".equals(state.getProperty("part.vanilla.game")) : "one folder for both editions";
        assert "0".equals(state.getProperty("intro.toe")) && "1".equals(state.getProperty("option.new_creature_framework"));
        assert "hof".equals(state.getProperty("last"));
        assert "192.0.2.9".equals(state.getProperty("option.lan_peers")) : "a choice made in the new launcher stays";
        assert !taken.contains("option.lan_peers") && taken.size() == choices.size() - 1 : taken;
        assert Launch.adopt(dir, choices).isEmpty() : "a second migration changes nothing";

        /* Defaults the old launcher never wrote stay the base's defaults; odd values are left out. */
        Map<String, Object> fresh = new HashMap<>();
        fresh.put("new_creature_framework", false);
        fresh.put("lan_peers", "   ");
        fresh.put("edition", "unknown");
        fresh.put("game", 42);
        assert LauncherHooks.choices(fresh).isEmpty() : LauncherHooks.choices(fresh);
        assert LauncherHooks.choices(new HashMap<>()).isEmpty();
        Map<String, Object> skip = new HashMap<>();
        skip.put("skip_intro", true);
        assert LauncherHooks.choices(skip).equals(new LinkedHashMap<String, String>() {{
            put("intro.vanilla", "1"); put("intro.hof", "1"); put("intro.toe", "1"); }}) : LauncherHooks.choices(skip);
        System.out.println("PASS migration: per-edition folders, shared Gold folder, options, videos, selection; the player's new choices win");
    }
}
'''


@unittest.skipUnless(LAUNCHER is not None and PLATFORM_JAR.is_file(), "the launcher base and android-37.0 are required")
class LauncherMigrationTest(unittest.TestCase):
    def test_old_preferences_become_base_choices(self):
        out = ROOT / "build/tests/launcher-migration"
        prepared = prepare(out / "prepared")
        source = out / "src/org/homm5/port/launcher/MigrationCheck.java"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(CHECK, encoding="utf-8")
        classes = out / "classes"
        if classes.exists():
            shutil.rmtree(classes)
        javac(classes, [*map(Path, prepared["sources"]), APP / "LauncherHooks.java", APP / "Games.java", source])
        state = out / "state"
        if state.exists():
            shutil.rmtree(state)
        state.mkdir(parents=True)
        self.assertIn("PASS migration", java(classes, "org.homm5.port.launcher.MigrationCheck", state))

    def test_migration_runs_before_choices_are_read_and_keeps_player_data(self):
        hooks = (APP / "LauncherHooks.java").read_text(encoding="utf-8")
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", hooks, flags=re.S)
        migrate = function(hooks, "    @Override public void migrate(Context context)")
        self.assertIn('getSharedPreferences(OLD_PREFERENCES, Context.MODE_PRIVATE)', migrate)
        self.assertIn("Launch.adopt(context, choices(values))", migrate)
        self.assertIn("old.edit().putBoolean(MIGRATED, true).commit();", migrate)
        for kept in ("userdata", "port_settings", "Games.preferences", "Games.userdata"):
            self.assertNotIn(kept, code)   # player data in /sdcard/HeroesV and the games' own preferences stay put
        self.assertEqual(LauncherHooks_OLD_PREFERENCES(hooks), "launcher")
        # The base runs PortHooks.migrate once per process before the launcher or the game reads choices.
        base = LAUNCHER / "android/src/port/launcher"
        activity = (base / "LauncherActivity.java").read_text(encoding="utf-8")
        create = function(activity, "    @Override protected void onCreate(Bundle state)")
        self.assertLess(create.index("Launch.migrate(this, hooks);"), create.index('State.get(this, State.CHOICES, "last", "")'))
        launch = (base / "Launch.java").read_text(encoding="utf-8")
        attach = function(launch, "    public static Launch attach(Activity activity)")
        self.assertLess(attach.index("migrate(activity, PortHooks.of(activity));"), attach.index("launch.environment();"))


def LauncherHooks_OLD_PREFERENCES(text):
    start = text.index('OLD_PREFERENCES = "') + len('OLD_PREFERENCES = "')
    return text[start:text.index('"', start)]


if __name__ == "__main__":
    unittest.main()
