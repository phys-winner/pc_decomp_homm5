package org.homm5.port;

import android.content.Context;
import android.content.res.AssetManager;
import java.io.*;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** XZ-packed engines are installed once per build in the app's private files. An engine
 *  linked against libhomm5_common.so (tools/common_lib.py) names it in its index row: the
 *  library is installed beside the engine, whose DT_RUNPATH ($ORIGIN) finds it when
 *  System.load maps the two as one group. */
final class NativeLibrary {
    private static native long nativeUnpack(AssetManager assets, String name, String path,
                                            long total, int chunk, int[] sizes);
    private NativeLibrary() { }

    static boolean available(Context context, String library) {
        try {
            String[] row = entry(context.getAssets(), System.mapLibraryName(library));
            if (row == null)
                return new File(context.getApplicationInfo().nativeLibraryDir, System.mapLibraryName(library)).isFile();
            for (String needed : needed(row)) dependency(context.getAssets(), needed);
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    static synchronized void load(Context context, String library) throws IOException {
        String file = System.mapLibraryName(library);
        String[] row = entry(context.getAssets(), file);
        if (row == null) {
            System.loadLibrary(library);
            return;
        }
        File dir = new File(context.getFilesDir(), "native");
        for (String needed : needed(row)) install(context, dir, needed, dependency(context.getAssets(), needed));
        System.load(install(context, dir, file, row).getAbsolutePath());
    }

    /** Whether this APK packs the library (a row of assets/native/index.txt). */
    static boolean packed(Context context, String file) {
        try {
            return entry(context.getAssets(), file) != null;
        } catch (IOException e) {
            return false;
        }
    }

    /** Packed libraries installed together in dir (each unpacked and verified unless this build's
     *  copy is there; DxvkRuntime). Returns dir. */
    static synchronized File installAll(Context context, File dir, String... files) throws IOException {
        for (String file : files) {
            String[] row = entry(context.getAssets(), file);
            if (row == null) throw new IOException("native library is not packed: " + file);
            install(context, dir, file, row);
        }
        return dir;
    }

    /** Whether dir already holds this build's copy of every library (nothing is unpacked). */
    static boolean installed(Context context, File dir, String... files) {
        try {
            for (String file : files) {
                String[] row = entry(context.getAssets(), file);
                File target = new File(dir, file);
                if (row == null || target.length() != Long.parseLong(row[1])
                        || !row[2].equals(readStamp(new File(dir, file + ".sha256")))) return false;
            }
            return true;
        } catch (IOException | NumberFormatException e) {
            return false;
        }
    }

    /** One packaged library in dir, unpacked and verified unless this build's copy is there. */
    private static File install(Context context, File dir, String file, String[] row) throws IOException {
        long size = Long.parseLong(row[1]);
        File target = new File(dir, file), stamp = new File(dir, file + ".sha256");
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        /* The engines run in separate processes and share libhomm5_common.so: one unpacks at a time. */
        try (RandomAccessFile lockFile = new RandomAccessFile(new File(dir, ".lock"), "rw");
             FileLock lock = lockFile.getChannel().lock()) {
            /* shortcut: reuse by size/build stamp; rehash on reuse if private cache edits must be detected. */
            if (target.length() != size || !row[2].equals(readStamp(stamp))) {
                if (stamp.exists() && !stamp.delete()) throw new IOException("cannot remove " + stamp);
                File part = new File(dir, file + ".part");
                if (part.exists() && !part.delete()) throw new IOException("cannot remove " + part);
                if (dir.getUsableSpace() < size + (1 << 20)) throw new IOException("not enough space to unpack " + file);
                String[] packed = row[4].split(",");
                int[] sizes = new int[packed.length];
                for (int i = 0; i < sizes.length; ++i) sizes[i] = Integer.parseInt(packed[i]);
                System.loadLibrary("homm5xz");
                long started = android.os.SystemClock.elapsedRealtime();
                try {
                    long written = nativeUnpack(context.getAssets(), "native/" + file + ".xz", part.getAbsolutePath(),
                                                size, Integer.parseInt(row[3]), sizes);
                    if (written != size || !row[2].equals(sha256(part)))
                        throw new IOException("invalid unpacked library: " + file + " (" + written + " of " + size + ")");
                    Files.move(part.toPath(), target.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
                    try (FileOutputStream out = new FileOutputStream(stamp)) {
                        out.write((row[2] + "\n").getBytes(StandardCharsets.US_ASCII));
                        out.getFD().sync();
                    }
                } finally {
                    if (part.exists()) part.delete();
                }
                android.util.Log.i("HeroesV", "native: " + file + " unpacked and verified in "
                    + (android.os.SystemClock.elapsedRealtime() - started) + " ms");
            }
            /* Android 17 rejects writable code; repair engines cached by earlier APKs too. */
            if (!target.setReadOnly()) throw new IOException("cannot make native library read-only: " + file);
        }
        return target;
    }

    private static String readStamp(File stamp) throws IOException {
        if (!stamp.isFile()) return "";
        try (BufferedReader in = new BufferedReader(new FileReader(stamp))) {
            return in.readLine();
        }
    }

    static String sha256(File file) throws IOException {
        try {
            MessageDigest hash = MessageDigest.getInstance("SHA-256");
            try (InputStream in = new FileInputStream(file)) {
                byte[] buffer = new byte[1 << 16];
                for (int n; (n = in.read(buffer)) != -1;) hash.update(buffer, 0, n);
            }
            StringBuilder text = new StringBuilder(64);
            for (byte value : hash.digest()) text.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return text.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
    }

    /** The libraries an index row names in its sixth field (comma-separated). */
    private static String[] needed(String[] row) {
        return row.length == 6 ? row[5].split(",") : new String[0];
    }

    /** A packaged library another one needs; it needs nothing itself. */
    private static String[] dependency(AssetManager assets, String file) throws IOException {
        String[] row = entry(assets, file);
        if (row == null || needed(row).length != 0) throw new IOException("invalid native dependency: " + file);
        return row;
    }

    /** name, unpacked size, SHA-256, chunk size, comma-separated packed sizes[, needed libraries]. */
    private static String[] entry(AssetManager assets, String file) throws IOException {
        InputStream stream;
        try { stream = assets.open("native/index.txt"); }
        catch (FileNotFoundException e) { return null; }
        try (BufferedReader in = new BufferedReader(new InputStreamReader(stream, StandardCharsets.US_ASCII))) {
            for (String line; (line = in.readLine()) != null;) {
                String[] row = line.trim().split(" ");
                if (!row[0].equals(file)) continue;
                try {
                    if ((row.length != 5 && row.length != 6) || !row[2].matches("[0-9a-f]{64}")) throw new IllegalArgumentException();
                    long size = Long.parseLong(row[1]);
                    int chunk = Integer.parseInt(row[3]);
                    String[] sizes = row[4].split(",", -1);
                    if (size <= 0 || size > Integer.MAX_VALUE || chunk <= 0 || sizes.length > 256
                            || sizes.length != (size + chunk - 1) / chunk) throw new IllegalArgumentException();
                    for (String packed : sizes) if (Integer.parseInt(packed) <= 0) throw new IllegalArgumentException();
                    if (row.length == 6)
                        for (String needed : row[5].split(",", -1))
                            if (!needed.matches("lib[A-Za-z0-9_]+\\.so") || needed.equals(file)) throw new IllegalArgumentException();
                    return row;
                } catch (IllegalArgumentException e) {
                    throw new IOException("invalid native index entry: " + file, e);
                }
            }
        }
        throw new IOException("native library is missing from index: " + file);
    }
}
