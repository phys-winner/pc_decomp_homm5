package org.homm5.port;

import java.io.File;
import java.util.ArrayList;
import java.util.Locale;

/** The texture conversion (android/texconv, libtexconv.so): the game's DXT
 *  textures, which some GPUs cannot sample, re-encoded once into ETC2 or ASTC
 *  (each installed data bank's own zz_port_textures*.pak), and later, if wanted, the
 *  originals removed from the game's archives. One operation at a time
 *  ({@link #current}); the launcher base runs it through TexconvBackend on its
 *  background work and decides with its own GPU probe whether the card shows. */
final class Textures {
    static final int ETC2 = 1, ASTC = 2;
    static final int IDLE = 0, SCANNING = 1, CONVERTING = 2, FINISHING = 3, REMOVING = 4, DONE = 5, FAILED = 6, CANCELLED = 7;
    static final int CONVERT = 0, REMOVE_ORIGINALS = 1, REMOVE_CONVERTED = 2;

    private static native long[] nativeScan(String game);
    private static native int nativeConvert(String game, int format, int threads);
    private static native int nativeRemoveOriginals(String game);
    private static native int nativeRemoveConverted(String game);
    private static native long[] nativeScanBank(String game, String bank);
    private static native int nativeConvertBank(String game, String bank, int format, int threads);
    private static native int nativeRemoveOriginalsBank(String game, String bank);
    private static native int nativeRemoveConvertedBank(String game, String bank);
    private static native void nativeCancel();
    private static native long[] nativeProgress();
    private static native String nativeMessage();

    private static Boolean loaded;
    private static final Object nativeOperation = new Object();

    static synchronized boolean available() {
        if (loaded == null) {
            try {
                System.loadLibrary("texconv");
                loaded = true;
            } catch (Throwable e) {
                android.util.Log.w("HeroesV", "textures: no converter: " + e);
                loaded = false;
            }
        }
        return loaded;
    }

    /* ----------------------------------------------------------- the state */

    /** What a game folder holds: the convertible originals and any conversion. */
    static final class Status {
        File game;
        long textures, bytes;
        int converted;                  /* 0, ETC2 or ASTC */
        long convertedTextures, convertedBytes, removable;
        boolean originalsRemoved;       /* any bank is, or may be, missing originals */
        boolean partial, mixedFormats, removalPending, originalsPartiallyRemoved;
        String failure;                 /* the scan could not read the archives */
    }

    /** Blocking: reads the archives' directories and the textures' headers. */
    static Status scan(File game) {
        synchronized (nativeOperation) { return scanLocked(game); }
    }

    /** Installed archives stay in their own engine bank, including case. */
    static File[] banks(File game) {
        File[] children = game.listFiles();
        if (children == null) throw new IllegalStateException("Cannot read the game folder");
        ArrayList<File> found = new ArrayList<>();
        for (String id : new String[] {"data", "datals", "dataa1"}) {
            File match = null;
            for (File child : children) if (child.isDirectory() && child.getName().toLowerCase(Locale.ROOT).equals(id)) {
                if (match != null) throw new IllegalStateException("Ambiguous texture data bank: " + id);
                match = child;
            }
            if (match != null) found.add(match);
        }
        if (found.isEmpty() || !found.get(0).getName().equalsIgnoreCase("data"))
            throw new IllegalStateException("The data folder is missing");
        return found.toArray(new File[0]);
    }

    private static Status scanLocked(File game) {
        Status s = new Status();
        s.game = game;
        if (!available()) {
            s.failure = "libtexconv.so";
            return s;
        }
        boolean complete = true, anyConverted = false;
        int format = 0;
        try {
            for (File bank : banks(game)) {
                long[] v = nativeScanBank(game.getAbsolutePath(), bank.getName());
                if (v == null || v.length < 9) {
                    s.failure = bank.getName() + ": " + nativeMessage();
                    s.converted = 0;
                    return s;
                }
                s.textures += v[0]; s.bytes += v[1];
                s.convertedTextures += v[5]; s.convertedBytes += v[6]; s.removable += v[8];
                s.originalsRemoved |= v[7] != 0;
                s.removalPending |= v[4] != 0 && v[8] > 0;
                if (v[4] != 0) {
                    anyConverted = true;
                    if (format == 0) format = (int) v[4];
                    else if (format != (int) v[4]) s.mixedFormats = true;
                } else if (v[0] != 0) complete = false;
            }
        } catch (Throwable e) { s.failure = e.toString(); return s; }
        s.partial = anyConverted && (!complete || s.mixedFormats);
        s.originalsPartiallyRemoved = s.originalsRemoved && s.removalPending;
        s.converted = complete && !s.mixedFormats ? format : 0;
        return s;
    }

    static volatile Job current;

    static final class Job implements Runnable {
        final File game;
        final int kind, format;
        final long started = System.currentTimeMillis();
        volatile boolean finished, cancelled;
        volatile String failure;        /* null: done or stopped (see cancelled) */
        volatile long[] last = new long[5];
        volatile int bankDone, bankTotal;
        volatile boolean bankActive;
        volatile int phase = SCANNING;

        Job(File game, int kind, int format) {
            this.game = game;
            this.kind = kind;
            this.format = format;
        }

        @Override public void run() {
            try {
                synchronized (nativeOperation) { runBanks(); }
            } catch (Throwable e) {
                failure = e.toString();
                last = new long[] {FAILED, bankDone, bankTotal, bankDone * 1000L, bankTotal * 1000L};
            } finally {
                finished = true;
            }
        }

        private void runBanks() {
            if (kind < CONVERT || kind > REMOVE_CONVERTED || (kind == CONVERT && format != ETC2 && format != ASTC))
                throw new IllegalArgumentException("Unknown texture operation or format");
            File[] installed = banks(game);
            String path = game.getAbsolutePath();
            long[][] states = new long[installed.length][];
            bankTotal = installed.length;
            // Validate every bank before deleting anything or changing formats.
            for (int i = 0; i < installed.length; ++i) {
                if (cancelled) { finishCancelled(); return; }
                long[] v = states[i] = nativeScanBank(path, installed[i].getName());
                if (cancelled) { finishCancelled(); return; }
                if (v == null || v.length < 9) { failure = installed[i].getName() + ": " + nativeMessage(); break; }
                if (kind == REMOVE_CONVERTED && v[7] != 0)
                    failure = "The original textures were removed: the converted ones are the only copy";
                if (kind == CONVERT && v[7] != 0 && v[4] != format)
                    failure = "Restore the original textures before changing their format";
                if (kind == REMOVE_ORIGINALS && v[0] != 0 && v[4] == 0)
                    failure = "Convert every installed data bank before removing original textures";
                if (failure != null) break;
            }
            if (failure != null) { last = new long[] {FAILED, 0, bankTotal, 0, bankTotal * 1000L}; return; }
            for (int i = 0; i < installed.length; ++i) {
                if (cancelled) { finishCancelled(); return; }
                long[] v = states[i];
                int result = 0;
                boolean work = kind == CONVERT ? v[0] != 0 && v[7] == 0
                             : kind == REMOVE_ORIGINALS ? v[4] != 0 && v[8] > 0 : v[4] != 0;
                if (work) {
                    String bank = installed[i].getName();
                    phase = kind == CONVERT ? CONVERTING : kind == REMOVE_ORIGINALS ? REMOVING : FINISHING;
                    bankActive = true;
                    if (kind == CONVERT) result = nativeConvertBank(path, bank, format, Runtime.getRuntime().availableProcessors());
                    else if (kind == REMOVE_ORIGINALS) result = nativeRemoveOriginalsBank(path, bank);
                    else result = nativeRemoveConvertedBank(path, bank);
                    long[] nativeState = nativeProgress();
                    bankActive = false;
                    if (cancelled || (nativeState != null && nativeState[0] == CANCELLED)) { finishCancelled(); return; }
                    if (result != 0) {
                        failure = bank + ": " + nativeMessage();
                        last = new long[] {FAILED, bankDone, bankTotal, bankDone * 1000L, bankTotal * 1000L};
                        return;
                    }
                }
                bankDone = i + 1;
            }
            last = bankTotal == 1 ? nativeProgress() : new long[] {DONE, bankTotal, bankTotal, bankTotal * 1000L, bankTotal * 1000L};
            if (last == null) last = new long[] {DONE, 0, 0, 0, 0};
            last[0] = DONE;
        }

        private void finishCancelled() {
            cancelled = true;
            last = new long[] {CANCELLED, bankDone, bankTotal, bankDone * 1000L, bankTotal * 1000L};
        }

        /** {state, done, total, bytesDone, bytesTotal} */
        long[] progress() {
            if (!finished) {
                long[] p = nativeProgress();
                if (p != null && bankTotal > 1) {
                    long fraction = bankActive && p[4] > 0 ? Math.min(1000, p[3] * 1000 / p[4]) : 0;
                    p = new long[] {bankActive && p[0] != DONE ? p[0] : phase,
                        bankDone, bankTotal, Math.min(bankTotal * 1000L, bankDone * 1000L + fraction), bankTotal * 1000L};
                }
                if (p != null) last = p;
            }
            return last;
        }

        void cancel() {
            cancelled = true;
            nativeCancel();
        }
    }
}
