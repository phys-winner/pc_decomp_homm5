package org.homm5.port;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** What the APK carries beside the library (tools/build_game_apk.py):
 *  assets/lifted, the PE images the lifted code runs on (the game's own
 *  H5_Game.exe and DLLs as they were lifted, FMOD unpacked), and
 *  assets/overlay, the port's files that shadow the installation for reading
 *  (android/host/files.c): profiles, the options pages' additions, the town
 *  music pauses and, when the intro is skipped, an empty intro playlist.
 *  Each is copied into the app's own files once per APK (its index). */
final class Assets {
    private Assets() { }

    /** The folder the game reads its images from (nativeStart's images). */
    static File images(Context c, File base) {
        return images(c, base, "toe");
    }

    static File images(Context c, File base, String edition) {
        String name = Games.images(edition);
        File own = new File(c.getFilesDir(), name);
        try {
            if (install(c, name, own)) return own;
        } catch (IOException e) {
            android.util.Log.w("HeroesV", "images: " + e);
        }
        /* A development install keeps them in /sdcard/HeroesV/lifted (tools/deploy.py). */
        return new File(base, name);
    }

    /** The overlay folder, with the intro playlist present only when skipped. */
    static File overlay(Context c, boolean skipIntro) {
        return overlay(c, skipIntro, "toe");
    }

    static File overlay(Context c, boolean skipIntro, String edition) {
        String name = Games.overlay(edition);
        File own = new File(c.getFilesDir(), name);
        try {
            if (!install(c, name, own)) return null;
            String playlist = Games.intro(edition);
            File intro = new File(own, "video/" + playlist);
            if (skipIntro) {
                intro.getParentFile().mkdirs();
                copy(c, "overlay-intro" + Games.suffix(edition) + "/" + playlist, intro);
            } else if (intro.exists() && !intro.delete()) {
                android.util.Log.w("HeroesV", "overlay: cannot remove " + intro);
            }
        } catch (IOException e) {
            android.util.Log.w("HeroesV", "overlay: " + e);
            return null;
        }
        return own;
    }

    /** Whether the APK carries the game's images (the launcher asks before it starts). */
    static boolean carriesImages(Context c) {
        return carriesImages(c, "toe");
    }

    static boolean carriesImages(Context c, String edition) {
        return carries(c, Games.images(edition) + "/index.txt");
    }

    private static boolean carries(Context c, String path) {
        try (InputStream in = c.getAssets().open(path)) {
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    static boolean runtimeAvailable(Context c, File base, String edition) {
        if (!NativeLibrary.available(c, Games.library(edition))) return false;
        if (carriesImages(c, edition)) return carries(c, Games.overlay(edition) + "/index.txt");
        return "toe".equals(edition) && new File(base, "lifted/H5_Game.exe").isFile();
    }

    /* assets/<name>/index.txt: "path size sha256" a line; the copy notes the
     * index it was made from. false when the APK has no such assets. */
    private static boolean install(Context c, String name, File dir) throws IOException {
        String index;
        try {
            index = new String(read(c, name + "/index.txt"), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return false;
        }
        File noted = new File(dir, ".apk-index");
        if (noted.isFile() && new String(readFile(noted), StandardCharsets.UTF_8).equals(index)) return true;
        delete(dir);
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        int copied = 0;
        for (String line : index.split("\n")) {
            String path = line.trim().split(" ")[0];
            if (path.isEmpty() || path.contains("..")) continue;
            File out = new File(dir, path);
            File parent = out.getParentFile();
            if (parent != null && !parent.isDirectory() && !parent.mkdirs()) throw new IOException("cannot create " + parent);
            copy(c, name + "/" + path, out);
            ++copied;
        }
        try (FileOutputStream o = new FileOutputStream(noted)) { o.write(index.getBytes(StandardCharsets.UTF_8)); }
        android.util.Log.i("HeroesV", name + ": " + copied + " files copied from the APK to " + dir);
        return true;
    }

    /** f and everything in it, without following links out of it. */
    private static void delete(File f) {
        if (f.isDirectory() && !java.nio.file.Files.isSymbolicLink(f.toPath())) {
            File[] items = f.listFiles();
            if (items != null) for (File item : items) delete(item);
        }
        f.delete();
    }

    private static void copy(Context c, String asset, File out) throws IOException {
        File part = new File(out.getPath() + ".part");
        try (InputStream in = c.getAssets().open(asset); FileOutputStream o = new FileOutputStream(part)) {
            byte[] buffer = new byte[1 << 16];
            for (int n; (n = in.read(buffer)) > 0;) o.write(buffer, 0, n);
        }
        if (!part.renameTo(out)) throw new IOException("cannot write " + out);
    }

    private static byte[] read(Context c, String asset) throws IOException {
        try (InputStream in = c.getAssets().open(asset)) {
            return drain(in);
        }
    }

    private static byte[] readFile(File f) throws IOException {
        try (InputStream in = new java.io.FileInputStream(f)) {
            return drain(in);
        }
    }

    private static byte[] drain(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
        byte[] buffer = new byte[16384];
        for (int n; (n = in.read(buffer)) > 0;) out.write(buffer, 0, n);
        return out.toByteArray();
    }
}
