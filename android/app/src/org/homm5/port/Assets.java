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
        File own = new File(c.getFilesDir(), "lifted");
        try {
            if (install(c, "lifted", own)) return own;
        } catch (IOException e) {
            android.util.Log.w("HeroesV", "images: " + e);
        }
        /* A development install keeps them in /sdcard/HeroesV/lifted (tools/deploy.py). */
        return new File(base, "lifted");
    }

    /** The overlay folder, with the intro playlist present only when skipped. */
    static File overlay(Context c, boolean skipIntro) {
        File own = new File(c.getFilesDir(), "overlay");
        try {
            if (!install(c, "overlay", own)) return null;
            File intro = new File(own, "video/intro_a1.xml");
            if (skipIntro) {
                intro.getParentFile().mkdirs();
                copy(c, "overlay-intro/intro_a1.xml", intro);
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
        try (InputStream in = c.getAssets().open("lifted/index.txt")) {
            return true;
        } catch (IOException e) {
            return false;
        }
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
        Unpacker.delete(dir);
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
