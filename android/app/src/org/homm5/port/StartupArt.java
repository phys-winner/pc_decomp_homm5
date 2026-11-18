package org.homm5.port;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Reads the player's artwork, never a bundled copy of the game's pictures. Library thread only. */
final class StartupArt {
    private static final int MAX_BYTES = 17 * 1024 * 1024;

    static String splashName(String edition) {
        return "toe".equals(edition) ? "splasha2.bmp" : "hof".equals(edition) ? "splasha1.bmp" : "splash.bmp";
    }

    static Bitmap load(File game, String edition) {
        if (game == null) return null;
        try {
            File splash = Games.child(game, splashName(edition));
            if (splash != null && splash.isFile() && splash.length() <= MAX_BYTES) {
                BitmapFactory.Options size = new BitmapFactory.Options();
                size.inJustDecodeBounds = true;
                BitmapFactory.decodeFile(splash.getPath(), size);
                if (size.outWidth > 0 && size.outHeight > 0 && size.outWidth <= 4096 && size.outHeight <= 4096) {
                    Bitmap bitmap = BitmapFactory.decodeFile(splash.getPath());
                    if (bitmap != null) return bitmap;
                }
            }
            // Imports before this option omitted the loose BMP. Use the original loading illustration.
            String suffix = "toe".equals(edition) ? "A2" : "hof".equals(edition) ? "A1" : "";
            String name = "UI/pwlscreen/Front" + suffix + ".(Texture).dds";
            String[] banks = "toe".equals(edition) ? new String[]{"data/a2p1-data.pak", "data/data.pak"}
                : "hof".equals(edition) ? new String[]{"dataa1/a1p1-data.pak", "dataa1/a1-data.pak", "data/data.pak"}
                : new String[]{"DataLS/p6-data.pak", "data/p3c-data.pak", "data/data.pak"};
            for (String bank : banks) {
                File file = Games.child(game, bank);
                if (file == null || !file.isFile()) continue;
                try (ZipFile zip = new ZipFile(file)) {
                    ZipEntry entry = zip.getEntry(name);
                    if (entry == null) {
                        Enumeration<? extends ZipEntry> entries = zip.entries();
                        while (entries.hasMoreElements()) {
                            ZipEntry candidate = entries.nextElement();
                            if (candidate.getName().equalsIgnoreCase(name)) { entry = candidate; break; }
                        }
                    }
                    if (entry == null || entry.getSize() > MAX_BYTES) continue;
                    try (InputStream in = zip.getInputStream(entry)) {
                        byte[] data = read(in);
                        int[] pixels = decodeDds(data);
                        if (pixels == null) continue;
                        int width = le32(data, 16), height = le32(data, 12);
                        // The expansion pictures have a 1024x768 content rectangle in a square texture.
                        if (width == 1024 && height == 1024) height = 768;
                        return Bitmap.createBitmap(pixels, 0, width, width, height, Bitmap.Config.ARGB_8888);
                    }
                } catch (IOException error) {
                    // A damaged optional/patch bank must not hide valid artwork in the base bank.
                    android.util.Log.w("HeroesV", "startup artwork bank unavailable", error);
                }
            }
        } catch (RuntimeException error) {
            android.util.Log.w("HeroesV", "startup artwork unavailable", error);
        }
        return null; // Missing/unsupported artwork must never block starting the game.
    }

    private static byte[] read(InputStream in) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] block = new byte[16384];
        int n;
        while ((n = in.read(block)) != -1) {
            if (out.size() + n > MAX_BYTES) throw new IOException("Startup artwork is too large");
            out.write(block, 0, n);
        }
        return out.toByteArray();
    }

    private static int le16(byte[] b, int p) { return (b[p] & 255) | (b[p + 1] & 255) << 8; }
    private static int le32(byte[] b, int p) { return le16(b, p) | le16(b, p + 2) << 16; }
    private static int rgb565(int c) {
        int r = c >> 11, g = (c >> 5) & 63, b = c & 31;
        return ((r << 3 | r >> 2) << 16) | ((g << 2 | g >> 4) << 8) | (b << 3 | b >> 2);
    }
    private static int mix(int a, int b) {
        return (((2 * (a >> 16 & 255) + (b >> 16 & 255)) / 3) << 16)
            | (((2 * (a >> 8 & 255) + (b >> 8 & 255)) / 3) << 8)
            | ((2 * (a & 255) + (b & 255)) / 3);
    }

    /** Only the original loading textures' BGRA8888 and DXT3 formats. No native engine/GL context. */
    static int[] decodeDds(byte[] data) {
        if (data == null || data.length < 128 || le32(data, 0) != 0x20534444 || le32(data, 4) != 124
                || le32(data, 76) != 32) return null;
        int width = le32(data, 16), height = le32(data, 12);
        if (width < 1 || height < 1 || width > 2048 || height > 2048) return null;
        int format = le32(data, 84);
        int[] pixels;
        if (format == 0 && le32(data, 88) == 32 && le32(data, 92) == 0x00ff0000
                && le32(data, 96) == 0x0000ff00 && le32(data, 100) == 0xff) {
            int stride = (le32(data, 8) & 8) != 0 ? le32(data, 20) : width * 4;
            if (stride < width * 4 || (long)stride * height > data.length - 128) return null;
            pixels = new int[width * height];
            boolean alpha = le32(data, 104) == 0xff000000;
            for (int y = 0; y < height; ++y) for (int x = 0; x < width; ++x) {
                int color = le32(data, 128 + y * stride + x * 4);
                pixels[y * width + x] = alpha ? color : color | 0xff000000;
            }
        } else if (format == 0x33545844) { // DXT3 / explicit 4-bit alpha, always four colors.
            int columns = (width + 3) / 4, rows = (height + 3) / 4;
            if ((long)columns * rows * 16 > data.length - 128) return null;
            pixels = new int[width * height];
            int[] colors = new int[4];
            for (int by = 0; by < rows; ++by) for (int bx = 0; bx < columns; ++bx) {
                int p = 128 + (by * columns + bx) * 16;
                colors[0] = rgb565(le16(data, p + 8)); colors[1] = rgb565(le16(data, p + 10));
                colors[2] = mix(colors[0], colors[1]); colors[3] = mix(colors[1], colors[0]);
                int indices = le32(data, p + 12);
                for (int i = 0; i < 16; ++i) {
                    int x = bx * 4 + i % 4, y = by * 4 + i / 4;
                    int a = ((data[p + i / 2] & 255) >> (4 * (i % 2))) & 15;
                    if (x < width && y < height) pixels[y * width + x] = a * 17 << 24 | colors[(indices >>> (2 * i)) & 3];
                }
            }
        } else return null;
        return pixels;
    }

    private StartupArt() { }
}
