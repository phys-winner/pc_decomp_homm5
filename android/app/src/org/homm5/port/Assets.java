package org.homm5.port;

import android.content.Context;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

/** What the APK carries beside the library (tools/build_game_apk.py):
 *  assets/lifted, prepared DLLs (FMOD unpacked) and the original-image manifest;
 *  H5_Game.exe and granny2.dll are read directly from the selected installation;
 *  assets/overlay, the port's files that shadow the installation for reading
 *  (android/host/files.c): profiles, the options pages' additions and, when
 *  the intro is skipped, an empty intro playlist.
 *  Each is copied into the app's own files once per APK (its index). */
final class Assets {
    private Assets() { }

    static final class UnsupportedOriginalException extends IOException {
        final String path;
        UnsupportedOriginalException(String path, String diagnosis) { super(diagnosis); this.path = path; }
    }

    /** Hash on the existing startup worker before the player chooses whether to try another build. */
    static void verifyOriginals(Context c, File game, String edition) throws IOException {
        verifyOriginals(c, game, edition, false);
    }

    static void verifyOriginals(Context c, File game, String edition, boolean allowUnsupported) throws IOException {
        String manifest;
        try {
            manifest = new String(read(c, Games.images(edition) + "/originals.txt"), StandardCharsets.UTF_8);
        } catch (IOException e) {
            if (carriesImages(c, edition)) throw e;
            return; // CLI deployments already validate their original inputs.
        }
        int checked = 0;
        UnsupportedOriginalException unsupported = null;
        String bin = "hof".equals(edition) ? "bina1/" : "bin/";
        for (String line : manifest.split("\n")) {
            if (line.trim().isEmpty()) continue;
            String[] row = line.trim().split(" ");
            int bit = row[0].equals(bin + "H5_Game.exe") ? 1 : row[0].equals(bin + "granny2.dll") ? 2 : 0;
            if (row.length != 3 || bit == 0 || (checked & bit) != 0)
                throw new IOException("Invalid original-image manifest: " + edition);
            File file = Games.child(game, row[0]);
            if (file == null || !file.isFile() || !file.canRead())
                throw new IOException("Required original file is missing: " + filePath(game, row[0])
                    + " (expected " + Games.title(edition) + " " + Games.version(edition) + ")");
            try {
                long expectedSize = Long.parseLong(row[1]), foundSize = file.length();
                if (expectedSize <= 0 || !row[2].matches("[0-9a-f]{64}"))
                    throw new IOException("Invalid original-image manifest: " + edition);
                if (foundSize == 0) throw new IOException("Required original file is empty: " + file.getAbsolutePath());
                String foundHash = NativeLibrary.sha256(file);
                if ((foundSize != expectedSize || !row[2].equals(foundHash)) && unsupported == null)
                    unsupported = new UnsupportedOriginalException(row[0], "Unsupported original file: " + row[0] + " (expected "
                        + Games.title(edition) + " " + Games.version(edition) + ")\n"
                        + file.getAbsolutePath() + "\nExpected: " + expectedSize + " bytes, SHA-256 " + row[2]
                        + "\nFound: " + foundSize + " bytes, SHA-256 " + foundHash
                        + "\nRestore this edition's original file from its installation; do not combine different editions' binaries.");
            } catch (NumberFormatException e) {
                throw new IOException("Invalid original-image size: " + row[0], e);
            }
            checked |= bit;
        }
        if (checked != 3) throw new IOException("Incomplete original-image manifest: " + edition);
        if (unsupported != null && !allowUnsupported) throw unsupported;
    }

    private static String filePath(File root, String relative) { return new File(root, relative).getAbsolutePath(); }

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
        return "toe".equals(edition) && new File(base, "lifted/fmod.dll").isFile();
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
