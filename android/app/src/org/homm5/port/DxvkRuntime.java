package org.homm5.port;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/** The DXVK/Turnip runtime (tools/build_dxvk.py), packed XZ in assets/native like the engines
 *  (tools/build_game_apk.py): about 19 MB that a player who never chooses DXVK would otherwise carry
 *  installed in nativeLibraryDir. The game installs the whole set in files/dxvk on its first DXVK
 *  start of a build (GameActivity); the launcher's Turnip check (port.launcher.Probe, in ":probe")
 *  gets a folder from LauncherHooks.checkLibraries: the game's copy when it is there, else the
 *  Turnip part unpacked into the cache for the check alone and removed afterwards.
 *
 *  Only files/dxvk and nativeLibraryDir are on no linker path of the app: libh5dxvk.so,
 *  libadrenotools.so and the adrenotools hooks need libc++_shared.so, so it is loaded from the
 *  folder first, and the linker then finds it by its soname. An APK that still carries the
 *  runtime in nativeLibraryDir (built with older tools) keeps working: that folder is used. */
final class DxvkRuntime {
    /** The runtime as android/port.json's DXVK modes name it, libc++_shared first. */
    static final String[] LIBRARIES = {
        "libc++_shared.so", "libadrenotools.so", "libhook_impl.so", "libmain_hook.so", "libfile_redirect_hook.so",
        "libgsl_alloc_hook.so", "libh5turnip.so", "libdxvk_d3d9.so", "libh5dxvk.so",
    };
    /** What the Turnip check loads: adrenotools, its hooks and the driver (not DXVK or the bridge). */
    static final String[] TURNIP_CHECK = {
        "libc++_shared.so", "libadrenotools.so", "libhook_impl.so", "libmain_hook.so", "libfile_redirect_hook.so",
        "libgsl_alloc_hook.so", "libh5turnip.so",
    };
    private static final String FOLDER = "dxvk", CHECK_FOLDER = "dxvk-check";
    private static Set<String> packed;

    private DxvkRuntime() { }

    /** The runtime libraries this APK packs (none when it carries them in nativeLibraryDir). */
    static synchronized Set<String> packed(Context context) {
        if (packed == null) {
            Set<String> names = new LinkedHashSet<>();
            for (String name : LIBRARIES) if (NativeLibrary.packed(context, name)) names.add(name);
            packed = Collections.unmodifiableSet(names);
        }
        return packed;
    }

    /** Whether this APK carries the DXVK bridge at all (packed or extracted). */
    static boolean available(Context context) {
        return packed(context).contains("libh5dxvk.so")
            || new File(context.getApplicationInfo().nativeLibraryDir, "libh5dxvk.so").isFile();
    }

    /** The folder with the whole runtime for a DXVK start, installed once per build; libc++_shared.so
     *  is loaded from it. Runs off the UI thread (the first start of a build unpacks ~19 MB). */
    static File install(Context context) throws IOException {
        if (!packed(context).contains("libh5dxvk.so")) return new File(context.getApplicationInfo().nativeLibraryDir);
        File dir = new File(context.getFilesDir(), FOLDER);
        long started = android.os.SystemClock.elapsedRealtime();
        NativeLibrary.installAll(context, dir, LIBRARIES);
        System.load(new File(dir, "libc++_shared.so").getAbsolutePath());
        android.util.Log.i("HeroesV", "DXVK runtime ready in " + dir + " ("
            + (android.os.SystemClock.elapsedRealtime() - started) + " ms)");
        return dir;
    }

    /** For the launcher's Turnip check (its own process): the game's installed copy when it is
     *  complete, else the check's part unpacked into the cache; null when the APK does not pack it. */
    static File forCheck(Context context, List<String> libraries) throws IOException {
        if (!packed(context).containsAll(java.util.Arrays.asList(TURNIP_CHECK))) return null;
        File game = new File(context.getFilesDir(), FOLDER), dir = game;
        if (!NativeLibrary.installed(context, game, TURNIP_CHECK)) {
            dir = new File(context.getCacheDir(), CHECK_FOLDER);
            remove(dir);                        /* a check that crashed left its copy behind */
            NativeLibrary.installAll(context, dir, TURNIP_CHECK);
        }
        System.load(new File(dir, "libc++_shared.so").getAbsolutePath());
        return dir;
    }

    /** After the check: the cache copy goes; the game's copy stays. */
    static void checked(Context context, File dir) {
        if (dir != null && dir.equals(new File(context.getCacheDir(), CHECK_FOLDER))) remove(dir);
    }

    private static void remove(File dir) {
        File[] files = dir.listFiles();
        if (files != null) for (File file : files) if (!file.delete()) file.deleteOnExit();
        dir.delete();
    }
}
