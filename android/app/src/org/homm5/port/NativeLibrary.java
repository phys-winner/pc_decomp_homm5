package org.homm5.port;

import android.content.Context;
import android.content.res.AssetManager;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** XZ-packed engines are installed once per build in the app's private files. */
final class NativeLibrary {
    private static native long nativeUnpack(AssetManager assets, String name, String path,
                                            long total, int chunk, int[] sizes);
    private NativeLibrary() { }

    static boolean available(Context context, String library) {
        try {
            return entry(context.getAssets(), System.mapLibraryName(library)) != null
                || new File(context.getApplicationInfo().nativeLibraryDir, System.mapLibraryName(library)).isFile();
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
        long size = Long.parseLong(row[1]);
        File dir = new File(context.getFilesDir(), "native");
        File target = new File(dir, file), stamp = new File(dir, file + ".sha256");
        /* shortcut: reuse by size/build stamp; rehash on reuse if private cache edits must be detected. */
        if (target.length() != size || !row[2].equals(readStamp(stamp))) {
            if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
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
        System.load(target.getAbsolutePath());
    }

    private static String readStamp(File stamp) throws IOException {
        if (!stamp.isFile()) return "";
        try (BufferedReader in = new BufferedReader(new FileReader(stamp))) {
            return in.readLine();
        }
    }

    private static String sha256(File file) throws IOException {
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

    /** name, unpacked size, SHA-256, chunk size, comma-separated packed sizes. */
    private static String[] entry(AssetManager assets, String file) throws IOException {
        InputStream stream;
        try { stream = assets.open("native/index.txt"); }
        catch (FileNotFoundException e) { return null; }
        try (BufferedReader in = new BufferedReader(new InputStreamReader(stream, StandardCharsets.US_ASCII))) {
            for (String line; (line = in.readLine()) != null;) {
                String[] row = line.trim().split(" ");
                if (!row[0].equals(file)) continue;
                try {
                    if (row.length != 5 || !row[2].matches("[0-9a-f]{64}")) throw new IllegalArgumentException();
                    long size = Long.parseLong(row[1]);
                    int chunk = Integer.parseInt(row[3]);
                    String[] sizes = row[4].split(",", -1);
                    if (size <= 0 || size > Integer.MAX_VALUE || chunk <= 0 || sizes.length > 256
                            || sizes.length != (size + chunk - 1) / chunk) throw new IllegalArgumentException();
                    for (String packed : sizes) if (Integer.parseInt(packed) <= 0) throw new IllegalArgumentException();
                    return row;
                } catch (IllegalArgumentException e) {
                    throw new IOException("invalid native index entry: " + file, e);
                }
            }
        }
        throw new IOException("native library is missing from index: " + file);
    }
}
