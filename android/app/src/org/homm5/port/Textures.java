package org.homm5.port;

import android.content.Context;
import android.content.Intent;
import android.opengl.EGL14;
import android.opengl.EGLConfig;
import android.opengl.EGLContext;
import android.opengl.EGLDisplay;
import android.opengl.EGLExt;
import android.opengl.EGLSurface;
import android.opengl.GLES20;

import java.io.File;

/** The launcher's texture conversion (android/texconv, libtexconv.so): the
 *  game's DXT textures, which some GPUs cannot sample, re-encoded once into
 *  ETC2 or ASTC (data/zz_port_textures.pak), and later, if wanted, the
 *  originals removed from the game's archives. One operation at a time:
 *  {@link #current}, kept alive by {@link TextureService}. */
final class Textures {
    static final int ETC2 = 1, ASTC = 2;
    static final int IDLE = 0, SCANNING = 1, CONVERTING = 2, FINISHING = 3, REMOVING = 4, DONE = 5, FAILED = 6, CANCELLED = 7;
    static final int CONVERT = 0, REMOVE_ORIGINALS = 1, REMOVE_CONVERTED = 2;

    private static native long[] nativeScan(String game);
    private static native int nativeConvert(String game, int format, int threads);
    private static native int nativeRemoveOriginals(String game);
    private static native int nativeRemoveConverted(String game);
    private static native void nativeCancel();
    private static native long[] nativeProgress();
    private static native String nativeMessage();

    private static Boolean loaded;

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

    /* -------------------------------------------------------------- the GPU */

    /** What the GPU samples natively, probed once with an off-screen GLES 3 context. */
    static final class Gpu {
        boolean probed, s3tc, astc;
        String renderer = "";
    }

    private static Gpu gpu;

    static synchronized Gpu gpu() {
        if (gpu != null) return gpu;
        Gpu g = new Gpu();
        EGLDisplay display = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY);
        EGLContext context = EGL14.EGL_NO_CONTEXT;
        EGLSurface surface = EGL14.EGL_NO_SURFACE;
        try {
            int[] version = new int[2];
            if (display != EGL14.EGL_NO_DISPLAY && EGL14.eglInitialize(display, version, 0, version, 1)) {
                int[] attributes = {EGL14.EGL_RENDERABLE_TYPE, EGLExt.EGL_OPENGL_ES3_BIT_KHR,
                    EGL14.EGL_SURFACE_TYPE, EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE};
                EGLConfig[] configs = new EGLConfig[1];
                int[] count = new int[1];
                if (EGL14.eglChooseConfig(display, attributes, 0, configs, 0, 1, count, 0) && count[0] > 0) {
                    context = EGL14.eglCreateContext(display, configs[0], EGL14.EGL_NO_CONTEXT,
                        new int[] {EGL14.EGL_CONTEXT_CLIENT_VERSION, 3, EGL14.EGL_NONE}, 0);
                    surface = EGL14.eglCreatePbufferSurface(display, configs[0],
                        new int[] {EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE}, 0);
                    if (context != EGL14.EGL_NO_CONTEXT && surface != EGL14.EGL_NO_SURFACE
                            && EGL14.eglMakeCurrent(display, surface, surface, context)) {
                        String extensions = GLES20.glGetString(GLES20.GL_EXTENSIONS);
                        String renderer = GLES20.glGetString(GLES20.GL_RENDERER);
                        if (extensions != null) {
                            g.probed = true;
                            g.s3tc = extensions.contains("GL_EXT_texture_compression_s3tc")
                                || (extensions.contains("GL_ANGLE_texture_compression_dxt3")
                                    && extensions.contains("GL_ANGLE_texture_compression_dxt5"));
                            g.astc = extensions.contains("GL_KHR_texture_compression_astc_ldr");
                        }
                        if (renderer != null) g.renderer = renderer;
                    }
                }
            }
        } catch (Throwable e) {
            android.util.Log.w("HeroesV", "textures: GPU probe: " + e);
        } finally {
            if (display != EGL14.EGL_NO_DISPLAY) {
                EGL14.eglMakeCurrent(display, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT);
                if (surface != EGL14.EGL_NO_SURFACE) EGL14.eglDestroySurface(display, surface);
                if (context != EGL14.EGL_NO_CONTEXT) EGL14.eglDestroyContext(display, context);
                EGL14.eglTerminate(display);
            }
        }
        android.util.Log.i("HeroesV", "textures: GPU " + g.renderer + " s3tc " + g.s3tc + " astc " + g.astc);
        gpu = g;
        return g;
    }

    /* ----------------------------------------------------------- the state */

    /** What a game folder holds: the convertible originals and any conversion. */
    static final class Status {
        File game;
        long textures, bytes;
        int converted;                  /* 0, ETC2 or ASTC */
        long convertedTextures, convertedBytes, removable;
        boolean originalsRemoved;
        String failure;                 /* the scan could not read the archives */
    }

    /** Blocking: reads the archives' directories and the textures' headers. */
    static Status scan(File game) {
        Status s = new Status();
        s.game = game;
        long[] v = available() ? nativeScan(game.getAbsolutePath()) : null;
        if (v == null) {
            s.failure = available() ? nativeMessage() : "libtexconv.so";
            return s;
        }
        s.textures = v[0];
        s.bytes = v[1];
        s.converted = (int) v[4];
        s.convertedTextures = v[5];
        s.convertedBytes = v[6];
        s.originalsRemoved = v[7] != 0;
        s.removable = v[8];
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

        Job(File game, int kind, int format) {
            this.game = game;
            this.kind = kind;
            this.format = format;
        }

        @Override public void run() {
            int result;
            String path = game.getAbsolutePath();
            try {
                if (kind == CONVERT) result = nativeConvert(path, format, Runtime.getRuntime().availableProcessors());
                else if (kind == REMOVE_ORIGINALS) result = nativeRemoveOriginals(path);
                else result = nativeRemoveConverted(path);
                if (result != 0 && progress()[0] != CANCELLED) failure = nativeMessage();
            } catch (Throwable e) {
                failure = e.toString();
            }
            last = nativeProgress();
            finished = true;
        }

        /** {state, done, total, bytesDone, bytesTotal} */
        long[] progress() {
            if (!finished) {
                long[] p = nativeProgress();
                if (p != null) last = p;
            }
            return last;
        }

        void cancel() {
            cancelled = true;
            nativeCancel();
        }
    }

    static Job start(Context c, File game, int kind, int format) {
        if (current != null && !current.finished) return null;
        Job job = new Job(game, kind, format);
        current = job;
        new Thread(job, "textures").start();
        c.startForegroundService(new Intent(c, TextureService.class));
        return job;
    }
}
