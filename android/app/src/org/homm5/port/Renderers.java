package org.homm5.port;

import android.content.Context;
import android.content.Intent;
import android.os.Build;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

/** Tribes of the East's renderer choice (RendererPolicy) on this device. The launcher (process
 *  :launcher) and GameActivity (the main process) share it through small files in the app's
 *  private files, read fresh each time: renderer.properties (mode, who chose it, whether the game
 *  has offered a better one) and the driver check's report, cached per build and system
 *  (RendererProbe, which runs in its own process :probe). */
final class Renderers {
    static final String STORE = "renderer.properties", REPORT = "renderer-probe.txt", PARTIAL = "renderer-probe.part",
        STAGE = "renderer-probe.stage";
    /** A check that has not reported by then has crashed or hung in that driver stage. */
    static final long PROBE_TIMEOUT_MS = 15000;
    /** origin: who chose the mode. */
    static final String AUTO = "auto", USER = "user", OFFER = "offer";

    private Renderers() { }

    static boolean ru() {
        String lang = Locale.getDefault().getLanguage();
        return "ru".equals(lang) || "uk".equals(lang) || "be".equals(lang);
    }

    static Properties load(Context c) {
        Properties p = new Properties();
        File file = new File(c.getFilesDir(), STORE);
        if (file.isFile()) {
            try (FileInputStream in = new FileInputStream(file)) { p.load(in); }
            catch (IOException e) { android.util.Log.w("HeroesV", "renderer: " + e); }
        }
        return p;
    }

    private static void save(Context c, Properties p) {
        File file = new File(c.getFilesDir(), STORE), part = new File(c.getFilesDir(), STORE + ".tmp");
        try (FileOutputStream out = new FileOutputStream(part)) {
            p.store(out, "Heroes V renderer");
            out.getFD().sync();
        } catch (IOException e) {
            android.util.Log.w("HeroesV", "renderer: " + e);
            return;
        }
        if (!part.renameTo(file)) android.util.Log.w("HeroesV", "renderer: cannot replace " + file);
    }

    /** The chosen mode; "" before the first choice (automatic or not). */
    static String chosen(Context c) {
        String mode = load(c).getProperty("mode", "");
        return RendererPolicy.valid(mode) ? mode : "";
    }

    static String origin(Context c) { return load(c).getProperty("origin", ""); }

    static void choose(Context c, String mode, String origin) {
        Properties p = load(c);
        p.setProperty("mode", mode);
        p.setProperty("origin", origin);
        p.remove("fallback");
        save(c, p);
    }

    static boolean offered(Context c) { return "1".equals(load(c).getProperty("offered")); }

    static void markOffered(Context c) {
        Properties p = load(c);
        p.setProperty("offered", "1");
        save(c, p);
    }

    /** GameActivity: the mode this start asks for (the launcher warns when it did not reach the game). */
    static void startedWith(Context c, String mode) {
        Properties p = load(c);
        p.setProperty("started", mode);
        save(c, p);
    }

    static String lastStart(Context c) { return load(c).getProperty("started", RendererPolicy.GLES); }

    /** GameActivity: DXVK could not start this session and OpenGL ES rendered (homm5.log has why). */
    static void fellBack(Context c, String mode) {
        Properties p = load(c);
        p.setProperty("fallback", mode);
        save(c, p);
    }

    static String fallback(Context c) { return load(c).getProperty("fallback", ""); }

    static void clearFallback(Context c) {
        Properties p = load(c);
        if (p.remove("fallback") != null) save(c, p);
    }

    /** The libraries the installer extracted (android:extractNativeLibs) with this APK. */
    static Set<String> libraries(Context c) {
        Set<String> names = new HashSet<>();
        String[] list = new File(c.getApplicationInfo().nativeLibraryDir).list();
        if (list != null) for (String name : list) names.add(name);
        return names;
    }

    /** A report belongs to one build of the app on one build of the system (its GPU driver). */
    static String reportKey(Context c) { return Build.FINGERPRINT + "|" + Launcher.buildStamp(c); }

    /** The cached driver check of this build and system; a crashed or hung check counts as done
     *  (its stage reports "crash") so that it is not repeated on every start. Null while it runs. */
    static Map<String, String> report(Context c) {
        String key = reportKey(c);
        String text = read(new File(c.getFilesDir(), REPORT));
        if (text != null && text.startsWith(key + "\n")) return RendererPolicy.parse(text.substring(key.length() + 1));
        File stage = new File(c.getFilesDir(), STAGE);
        String running = read(stage);
        if (running != null && running.startsWith(key + "\n")
                && System.currentTimeMillis() - stage.lastModified() > PROBE_TIMEOUT_MS) {
            String driver = running.substring(key.length() + 1).trim();
            String partial = read(new File(c.getFilesDir(), PARTIAL));
            String done = partial != null && partial.startsWith(key + "\n") ? partial.substring(key.length() + 1) : "";
            String crashed = key + "\n" + done + driver + ".status=crash\n"
                + ("stock".equals(driver) ? "turnip.status=skipped\n" : "");
            write(new File(c.getFilesDir(), REPORT), crashed);
            stage.delete();
            android.util.Log.w("HeroesV", "renderer: the " + driver + " driver check did not finish");
            return RendererPolicy.parse(crashed.substring(key.length() + 1));
        }
        return null;
    }

    /** Whether the DXVK modes depend on the driver check here: not below Android 11 or without
     *  the DXVK libraries (RendererPolicy then says why without a report). */
    static boolean needsProbe(Context c) {
        if (Build.VERSION.SDK_INT < RendererPolicy.MIN_SDK) return false;
        Set<String> present = libraries(c);
        for (String name : RendererPolicy.DXVK_LIBRARIES) if (!present.contains(name)) return false;
        return true;
    }

    /** Starts the driver check unless this build and system have a report or a check runs now. */
    static void probe(Context c) {
        if (!needsProbe(c) || report(c) != null) return;
        String running = read(new File(c.getFilesDir(), STAGE));
        if (running != null && running.startsWith(reportKey(c) + "\n")) return;
        try {
            c.startService(new Intent(c, RendererProbe.class));
        } catch (RuntimeException e) {
            android.util.Log.w("HeroesV", "renderer: driver check: " + e);
        }
    }

    static RendererPolicy.Status[] statuses(Context c, Map<String, String> report) {
        return RendererPolicy.evaluate(Build.VERSION.SDK_INT, libraries(c), report, ru());
    }

    static String read(File file) {
        if (!file.isFile()) return null;
        try { return new String(Files.readAllBytes(file.toPath()), StandardCharsets.UTF_8); }
        catch (IOException e) { return null; }
    }

    static void write(File file, String text) {
        File part = new File(file.getPath() + ".tmp");
        try (FileOutputStream out = new FileOutputStream(part)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
            out.getFD().sync();
        } catch (IOException e) {
            android.util.Log.w("HeroesV", "renderer: " + e);
            return;
        }
        if (!part.renameTo(file)) android.util.Log.w("HeroesV", "renderer: cannot replace " + file);
    }
}
