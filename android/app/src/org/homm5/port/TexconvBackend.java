package org.homm5.port;

import java.io.File;
import org.homm5.port.launcher.TextureBackend;

/** The launcher base's texture card (port.json "textures.backend") over the port's converter
 *  (Textures, libtexconv.so): every installed data bank's DXT textures re-encoded once into ETC2 or
 *  ASTC in the bank's own zz_port_textures pak, that conversion undone, or, after it, the originals
 *  removed from the game's archives for space. The base shows the card, runs these on its
 *  background work (a foreground service) and polls progress(); one operation at a time. Runs in the
 *  launcher's process. */
public final class TexconvBackend implements TextureBackend {
    private volatile Textures.Job job;
    private volatile String message = "";

    @Override public Scan scan(File game) {
        Textures.Status status = Textures.scan(game);
        Scan scan = new Scan();
        scan.failure = status.failure;
        if (status.failure != null) return scan;
        scan.textures = status.textures;
        scan.bytes = status.bytes;
        /* 0 while the banks are converted partly or into different formats: converting again
           finishes the conversion (Textures.Job skips nothing it still needs). */
        scan.converted = status.converted;
        scan.convertedTextures = status.convertedTextures;
        scan.convertedBytes = status.convertedBytes;
        scan.originalsRemoved = status.originalsRemoved;
        scan.removable = status.converted != 0 && status.removalPending ? status.removable : 0;
        return scan;
    }

    @Override public int convert(File game, int format, int threads) {
        return run(game, Textures.CONVERT, format == ASTC ? Textures.ASTC : Textures.ETC2);
    }

    @Override public int undo(File game) { return run(game, Textures.REMOVE_CONVERTED, 0); }

    @Override public int removeOriginals(File game) { return run(game, Textures.REMOVE_ORIGINALS, 0); }

    /** Blocking, on the base's work thread: 0 done, 1 failed (message() says why), 2 stopped. */
    private int run(File game, int kind, int format) {
        message = "";
        if (!Textures.available()) {
            message = "libtexconv.so";
            return 1;
        }
        Textures.Job running = new Textures.Job(game, kind, format);
        job = running;
        Textures.current = running;
        running.run();
        if (running.cancelled) return 2;
        if (running.failure != null) {
            message = running.failure;
            return 1;
        }
        return 0;
    }

    @Override public void cancel() {
        Textures.Job running = job;
        if (running != null) running.cancel();
    }

    /** {done, total, bytesDone, bytesTotal}: Textures.Job reports {state, done, total, bytesDone, bytesTotal}. */
    @Override public long[] progress() {
        Textures.Job running = job;
        long[] p = running != null ? running.progress() : null;
        return p == null || p.length < 5 ? null : new long[] {p[1], p[2], p[3], p[4]};
    }

    @Override public String message() { return message; }
}
