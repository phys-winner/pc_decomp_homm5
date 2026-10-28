package org.homm5.port;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;
import java.io.File;

/** The driver check behind the renderer choice (RendererPolicy), in a process of its own (:probe):
 *  loading a GPU driver can crash, and only this process goes down with it. It asks the system
 *  Vulkan driver and, on Adreno 6xx/7xx, the app-local Turnip (android/dxvk/probe.cpp in
 *  libh5dxvk.so) what DXVK would refuse, writes the report for this build and system
 *  (Renderers.report) and ends its process, which unloads the drivers again. Before each driver it
 *  notes the stage: a report missing after Renderers.PROBE_TIMEOUT_MS names the stage that crashed. */
public final class RendererProbe extends Service {
    private static native String nativeProbe(String libraryDir, boolean turnip);
    private static boolean started;

    @Override public int onStartCommand(Intent intent, int flags, int id) {
        synchronized (RendererProbe.class) {
            if (started) return START_NOT_STICKY;
            started = true;
        }
        new Thread(this::check, "renderer-probe").start();
        return START_NOT_STICKY;
    }

    @Override public IBinder onBind(Intent intent) { return null; }

    private void check() {
        File files = getFilesDir();
        String key = Renderers.reportKey(this), dir = getApplicationInfo().nativeLibraryDir;
        String stock, turnip = "turnip.status=skipped\n";
        Renderers.write(new File(files, Renderers.STAGE), key + "\nstock\n");
        try {
            System.loadLibrary("h5dxvk");
            stock = nativeProbe(dir, false);
        } catch (UnsatisfiedLinkError e) {
            stock = "stock.status=error\nstock.error=" + String.valueOf(e.getMessage()).replace('\n', ' ') + "\n";
        }
        java.util.Map<String, String> found = RendererPolicy.parse(stock);
        int adreno = RendererPolicy.adreno(found);
        if (adreno >= 600 && adreno < 800 && Renderers.libraries(this).containsAll(java.util.Arrays.asList(RendererPolicy.TURNIP_LIBRARIES))) {
            Renderers.write(new File(files, Renderers.PARTIAL), key + "\n" + stock);
            Renderers.write(new File(files, Renderers.STAGE), key + "\nturnip\n");
            turnip = nativeProbe(dir, true);
        }
        Renderers.write(new File(files, Renderers.REPORT), key + "\n" + stock + turnip);
        new File(files, Renderers.STAGE).delete();
        new File(files, Renderers.PARTIAL).delete();
        android.util.Log.i("HeroesV", "renderer check:\n" + stock + turnip);
        stopSelf();
        android.os.Process.killProcess(android.os.Process.myPid());
    }
}
