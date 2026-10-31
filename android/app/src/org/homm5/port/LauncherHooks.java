package org.homm5.port;

import android.content.Context;
import android.content.SharedPreferences;
import java.io.File;
import java.util.LinkedHashMap;
import java.util.Map;
import org.homm5.port.launcher.Launch;
import org.homm5.port.launcher.PortHooks;

/** What the launcher base (port.json "app.hooks") needs from Heroes V: the settings of the port's own
 *  launcher before 0.4, taken over once so that an updated install starts without importing the games
 *  again. That launcher kept, in the SharedPreferences "launcher": each edition's game folder
 *  (Games.pathKey: "game", "game-vanilla", "game-hof"), the selected edition, the opening videos
 *  (one switch for all editions), Tribes of the East's New Creature Framework and its LAN peers.
 *  Player data in /sdcard/HeroesV/userdata* stays where it is; the games' own preferences
 *  (port_settings*: scales, startup work) belong to GameActivity and are not touched. Runs in the
 *  launcher's process and in the game's (Launch.attach), so it never touches the game's activity
 *  or native library. */
public final class LauncherHooks implements PortHooks {
    static final String OLD_PREFERENCES = "launcher", MIGRATED = "moved_to_launcher_base";
    /** The old launcher's files in the app's private files: start markers and the DXVK renderer's state. */
    static final String[] OLD_FILES = {"game-started", "game-started-vanilla", "game-started-hof", "renderer.properties",
        "renderer.properties.tmp", "renderer-probe.txt", "renderer-probe.part", "renderer-probe.stage"};

    @Override public void migrate(Context context) {
        SharedPreferences old = context.getSharedPreferences(OLD_PREFERENCES, Context.MODE_PRIVATE);
        if (!old.getBoolean(MIGRATED, false)) {
            Map<String, ?> values = old.getAll();
            if (!values.isEmpty()) {
                java.util.List<String> taken = Launch.adopt(context, choices(values));
                android.util.Log.i("HeroesV", "launcher settings taken over: " + taken);
            }
            for (String name : OLD_FILES) {
                File file = new File(context.getFilesDir(), name);
                if (file.exists() && !file.delete()) android.util.Log.w("HeroesV", "cannot remove " + file);
            }
            old.edit().putBoolean(MIGRATED, true).commit();
        }
        if (storage(context)) removeInterruptedUnpacking(old);
    }

    /** Whether the shared storage's files can be changed by path (as the launcher base asks for it). */
    static boolean storage(Context context) {
        if (android.os.Build.VERSION.SDK_INT >= 30) return android.os.Environment.isExternalStorageManager();
        return context.checkSelfPermission("android.permission.WRITE_EXTERNAL_STORAGE") == android.content.pm.PackageManager.PERMISSION_GRANTED;
    }

    /** The old launcher's settings as the base names them (Launch.adopt takes only what the player
     *  has not chosen in the new launcher yet). A saved folder is taken as it is: the old launcher
     *  saved only folders that held the edition, and without storage access yet (Android 11+ asks
     *  for All files access after the update) it could not be checked here anyway. */
    public static Map<String, String> choices(Map<String, ?> old) {
        Map<String, String> choices = new LinkedHashMap<>();
        for (String id : Games.IDS) {
            Object folder = old.get(Games.pathKey(id));
            if (folder instanceof String && !((String) folder).trim().isEmpty()) choices.put("part." + id + ".game", ((String) folder).trim());
        }
        Object edition = old.get("edition");
        if (edition instanceof String && Games.valid((String) edition)) choices.put("last", (String) edition);
        Object skip = old.get("skip_intro");
        if (skip instanceof Boolean) for (String id : Games.IDS) choices.put("intro." + id, (Boolean) skip ? "1" : "0");
        if (Boolean.TRUE.equals(old.get("new_creature_framework"))) choices.put("option.new_creature_framework", "1");
        Object peers = old.get("lan_peers");
        if (peers instanceof String && !((String) peers).trim().isEmpty()) choices.put("option.lan_peers", ((String) peers).trim());
        return choices;
    }

    /** An unpacking of the old launcher that the update (or the process) interrupted left its hidden
     *  folder in the target ("<target>/.unpacking", maybe gigabytes) and, if it made the target, an
     *  otherwise empty folder: both go, off the main thread (with storage access: until then the
     *  note stays for a later start). */
    private static void removeInterruptedUnpacking(SharedPreferences old) {
        String stale = old.getString("unpacking", null);
        if (stale == null) return;
        boolean created = old.getBoolean("unpackingCreated", false);
        new Thread(() -> {
            File target = new File(stale), temp = new File(target, ".unpacking");
            delete(temp);
            if (created) {
                String[] left = target.list();
                if (left != null && left.length == 0 && !target.delete()) android.util.Log.w("HeroesV", "cannot remove " + target);
            }
            if (!temp.exists()) old.edit().remove("unpacking").remove("unpackingCreated").apply();
        }, "old-unpacking").start();
    }

    /** f and everything in it, without following links out of it. */
    static void delete(File f) {
        if (f.isDirectory() && !java.nio.file.Files.isSymbolicLink(f.toPath())) {
            File[] items = f.listFiles();
            if (items != null) for (File item : items) delete(item);
        }
        f.delete();
    }
}
