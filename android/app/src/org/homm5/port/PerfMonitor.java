package org.homm5.port;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.ContentResolver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInfo;
import android.hardware.display.DisplayManager;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.provider.Settings;
import android.view.Choreographer;
import android.view.Display;
import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayDeque;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Every edition (each engine has these natives, android/host/perf_diag.c).
 *  <ul>
 *  <li>The display's actual refresh rate for the frame limiter (perf_diag.h, port_settings.c): a
 *      DisplayListener, and the Choreographer's measured rate when it disagrees with the Display
 *      by more than 10 % (frame-rate overrides, a vendor's own limiter). HyperOS's thermal limit,
 *      power saving or the system setting can drop a 120 Hz panel to 60 Hz under a 120 cap.</li>
 *  <li>The flag files of the performance experiments in /sdcard/HeroesV (research/hyperos-diag.md):
 *      native switches and the existing VOID_BIG_CORES / VOID_RT_CORES environment.</li>
 *  <li>The Java half of the HyperOS diagnostics: display, battery, thermal and lifecycle events and
 *      the process's own vendor log lines, as "[hyperos]" lines in homm5.log.</li>
 *  </ul> */
final class PerfMonitor implements DisplayManager.DisplayListener, Choreographer.FrameCallback {
    static native void nativeConfigure(int options, String info, float displayHz, String injectFile);
    static native boolean nativeDiagOn();
    static native void nativeDisplayRate(float hz);
    static native void nativeState(int key, float value);
    static native void nativeLine(String line);
    static native int nativeLongFrames();

    /* perf_diag.h PERF_OPT_* */
    static final int OPT_DIAG = 1, OPT_NO_DIAG = 1 << 1, OPT_HYPEROS = 1 << 2, OPT_INJECT = 1 << 3,
        OPT_NO_REFRESH_FOLLOW = 1 << 4, OPT_ADPF = 1 << 5, OPT_NO_ADPF = 1 << 6, OPT_PACE_TIMER = 1 << 7,
        OPT_PACE_VSYNC = 1 << 8, OPT_VERBOSE = 1 << 9;
    /* perf_diag.c nativeState keys */
    private static final int STATE_VSYNC50 = 1, STATE_VSYNC95 = 2, STATE_BATT_TEMP = 3, STATE_PLUGGED = 4,
        STATE_THERMAL = 5, STATE_POWER_SAVE = 6, STATE_LIFECYCLE = 7, STATE_MISMATCH = 8, STATE_PAUSE = 9;

    private static final Pattern HYPEROS_VERSION = Pattern.compile("^OS\\d+\\.\\d+.*");
    private static final Pattern VENDOR = Pattern.compile(
        "(?i)fps|frame|dynamic|migui|migl|mivk|meow|glt|joyose|boost|perf|thermal|turbo|fpsgo|xgf|regulate");
    private static final Pattern LOGCAT = Pattern.compile("^\\s*(\\d+\\.\\d+)\\s+(\\d+)\\s+(\\d+)\\s+([VDIWEFA])\\s+(.*?)\\s*:\\s(.*)$");

    private final Activity activity;
    private final File base;
    private final int options;
    private final boolean diag, noPreferredMode;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private DisplayManager displays;
    private int displayId = Display.DEFAULT_DISPLAY;
    private float displayHz, sentHz;
    private boolean choreographing, mismatch;
    private int disagreements, agreements;   /* consecutive 2 s windows, for hysteresis */
    private long lastVsync, statsStart;
    private final long[] intervals = new long[1024];
    private int intervalCount;
    private int requestedMode = -1;
    private float requestedVote;
    private boolean displayLineDone;
    private BroadcastReceiver battery, powerSave, tempState;
    private Object thermalListener;
    private int lastPlugged = -2;
    private volatile boolean stopped;

    private PerfMonitor(Activity activity, File base, int options, boolean diag) {
        this.activity = activity;
        this.base = base;
        this.options = options;
        this.diag = diag;
        this.noPreferredMode = new File(base, "no-preferred-mode").exists();
    }

    /** HyperOS by the public API: an "OSx.y" incremental build on a Xiaomi device. */
    static boolean hyperOs(String manufacturer, String incremental) {
        return manufacturer != null && "xiaomi".equalsIgnoreCase(manufacturer.trim())
            && incremental != null && HYPEROS_VERSION.matcher(incremental).matches();
    }

    private static boolean flag(File base, String name) { return new File(base, name).exists(); }

    private static void setenv(String name, String value) {
        try { android.system.Os.setenv(name, value, true); }
        catch (Exception e) { android.util.Log.w("HeroesV", "setenv " + name + ": " + e); }
    }

    /** Before nativeStart: the switches, the environment and the display rate; then the listeners. */
    static PerfMonitor start(Activity activity, File base, File gameDir, String renderer, boolean verbose) {
        int options = 0;
        if (flag(base, "perf-diag")) options |= OPT_DIAG;
        if (flag(base, "no-perf-diag")) options |= OPT_NO_DIAG;
        if (flag(base, "diag-inject")) options |= OPT_INJECT;
        if (flag(base, "no-refresh-follow")) options |= OPT_NO_REFRESH_FOLLOW;
        if (flag(base, "adpf")) options |= OPT_ADPF;
        if (flag(base, "no-adpf")) options |= OPT_NO_ADPF;
        if (flag(base, "pace-timer")) options |= OPT_PACE_TIMER;
        if (flag(base, "pace-vsync")) options |= OPT_PACE_VSYNC;
        if (verbose) options |= OPT_VERBOSE;
        boolean hyper = hyperOs(Build.MANUFACTURER, Build.VERSION.INCREMENTAL);
        if (hyper) options |= OPT_HYPEROS;
        /* C4 / C5: the existing core selection, switched by flag files. */
        for (String policy : new String[] {"big", "near", "none"})
            if (flag(base, "cores-" + policy)) setenv("VOID_BIG_CORES", "none".equals(policy) ? "0" : policy);
        for (String policy : new String[] {"auto", "big", "next", "any"})
            if (flag(base, "rt-cores-" + policy)) setenv("VOID_RT_CORES", policy);
        if (flag(base, "rt-cores-early")) setenv("VOID_RT_EARLY", "1");
        String inject = null;
        if ((options & OPT_INJECT) != 0) inject = largestArchive(gameDir);
        nativeConfigure(options, info(activity, gameDir, renderer, hyper), currentRate(activity), inject);
        PerfMonitor monitor = new PerfMonitor(activity, base, options, nativeDiagOn());
        monitor.listen();
        return monitor;
    }

    private static String largestArchive(File gameDir) {
        File best = null;
        File[] files = gameDir != null ? new File(gameDir, "data").listFiles() : null;
        if (files != null)
            for (File file : files)
                if (file.isFile() && (best == null || file.length() > best.length())) best = file;
        return best != null ? best.getAbsolutePath() : null;
    }

    /** start line fields from Java: no paths, only the data location's category. */
    private static String info(Activity activity, File gameDir, String renderer, boolean hyper) {
        String version = "?", code = "?";
        try {
            PackageInfo info = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0);
            version = info.versionName;
            code = String.valueOf(Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode);
        } catch (Exception ignored) {}
        return "pkg=" + word(activity.getPackageName()) + " version=" + word(version) + " code=" + code
            + " renderer=" + ("dxvk".equals(renderer) ? "vulkan" : "turnip".equals(renderer) ? "turnip" : "gles")
            + " data=" + dataCategory(activity, gameDir) + " java_hyperos=" + (hyper ? word(Build.VERSION.INCREMENTAL) : "0")
            + " model=" + word(Build.MANUFACTURER + " " + Build.MODEL) + " sdk=" + Build.VERSION.SDK_INT;
    }

    private static String dataCategory(Context context, File gameDir) {
        if (gameDir == null) return "other";
        String path = gameDir.getAbsolutePath();
        File own = context.getExternalFilesDir(null), internal = context.getFilesDir();
        if ((own != null && path.startsWith(own.getParentFile().getAbsolutePath()))
            || (internal != null && path.startsWith(internal.getParentFile().getAbsolutePath()))
            || path.contains("/Android/data/")) return "app-specific";
        if (path.toLowerCase(Locale.ROOT).endsWith(".zip")) return "stored-zip";
        File external = Environment.getExternalStorageDirectory();
        if (path.startsWith(external.getAbsolutePath()) || path.startsWith("/sdcard") || path.startsWith("/storage/"))
            return "fuse-sdcard";
        return "other";
    }

    @SuppressWarnings("deprecation")
    private static float currentRate(Activity activity) {
        Display display = activity.getWindowManager().getDefaultDisplay();
        return display != null ? display.getRefreshRate() : 0f;
    }

    boolean noPreferredMode() { return noPreferredMode; }

    /* ------------------------------------------------------------------ display rate */
    private void listen() {
        displays = (DisplayManager) activity.getSystemService(Context.DISPLAY_SERVICE);
        if (displays != null) displays.registerDisplayListener(this, handler);
        displayHz = currentRate(activity);
        sentHz = displayHz;
        if (!diag) return;
        line("event", "kind=diag_java options=" + options + " hyperos=" + ((options & OPT_HYPEROS) != 0 ? 1 : 0));
        battery = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) { onBattery(intent); }
        };
        Intent sticky = activity.registerReceiver(battery, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if (sticky != null) onBattery(sticky);
        powerSave = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
                boolean on = power != null && power.isPowerSaveMode();
                nativeState(STATE_POWER_SAVE, on ? 1 : 0);
                line("event", "kind=power_save on=" + (on ? 1 : 0));
            }
        };
        activity.registerReceiver(powerSave, new IntentFilter(PowerManager.ACTION_POWER_SAVE_MODE_CHANGED));
        /* HyperOS PowerKeeper's sticky broadcast on a thermal state change, without a permission. */
        tempState = new BroadcastReceiver() {
            @Override public void onReceive(Context context, Intent intent) {
                line("event", "kind=temp_state value=" + intent.getIntExtra("temp_state", -1));
            }
        };
        try {
            IntentFilter filter = new IntentFilter("action_temp_state_change");
            if (Build.VERSION.SDK_INT >= 33) activity.registerReceiver(tempState, filter, Context.RECEIVER_EXPORTED);
            else activity.registerReceiver(tempState, filter);
        } catch (RuntimeException e) {
            line("event", "kind=temp_state value=!" + e.getClass().getSimpleName());
            tempState = null;
        }
        PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
        if (power != null) {
            nativeState(STATE_POWER_SAVE, power.isPowerSaveMode() ? 1 : 0);
            if (Build.VERSION.SDK_INT >= 29) {
                nativeState(STATE_THERMAL, power.getCurrentThermalStatus());
                PowerManager.OnThermalStatusChangedListener listener = status -> {
                    nativeState(STATE_THERMAL, status);
                    line("event", "kind=thermal_status value=" + status);
                };
                power.addThermalStatusListener(activity.getMainExecutor(), listener);
                thermalListener = listener;
            }
        }
        Thread vendor = new Thread(this::vendorLog, "h5-vendorlog");
        vendor.setDaemon(true);
        vendor.setPriority(Thread.MIN_PRIORITY);
        vendor.start();
    }

    private void onBattery(Intent intent) {
        int plugged = intent.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1);
        float temperature = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE) / 10f;
        nativeState(STATE_PLUGGED, plugged);
        if (temperature > -100) nativeState(STATE_BATT_TEMP, temperature);
        if (lastPlugged != -2 && plugged != lastPlugged) line("event", "kind=plugged value=" + plugged);
        lastPlugged = plugged;
    }

    @Override public void onDisplayAdded(int id) {}
    @Override public void onDisplayRemoved(int id) {}

    @Override public void onDisplayChanged(int id) {
        if (id != displayId || displays == null) return;
        Display display = displays.getDisplay(id);
        if (display == null) return;
        float hz = display.getRefreshRate();
        if (Math.abs(hz - displayHz) < .05f) return;
        float old = displayHz;
        displayHz = hz;
        if (diag) line("event", String.format(Locale.ROOT, "kind=display from=%.1f to=%.1f mode=%d", old, hz,
            display.getMode() != null ? display.getMode().getModeId() : -1));
        if (!mismatch) send(hz);
        if (diag) displayLine("change");
    }

    private void send(float hz) {
        if (Math.abs(hz - sentHz) < .05f) return;
        sentHz = hz;
        nativeDisplayRate(hz);
    }

    /** The surface's display (multi-display devices) and the mode/vote GameActivity requested. */
    void requested(Display display, int mode, float vote) {
        if (display != null && display.getDisplayId() != displayId) {
            displayId = display.getDisplayId();
            displayHz = display.getRefreshRate();
            if (!mismatch) send(displayHz);
        }
        boolean changed = mode != requestedMode || vote != requestedVote;
        requestedMode = mode;
        requestedVote = vote;
        if (diag && (changed || !displayLineDone)) displayLine(displayLineDone ? "request" : "start");
    }

    @Override public void doFrame(long frameTimeNanos) {
        if (!choreographing) return;
        if (lastVsync != 0 && frameTimeNanos > lastVsync) {
            long interval = frameTimeNanos - lastVsync;
            if (interval < 200_000_000L && intervalCount < intervals.length) intervals[intervalCount++] = interval;
        }
        lastVsync = frameTimeNanos;
        if (statsStart == 0) statsStart = frameTimeNanos;
        if (frameTimeNanos - statsStart >= 2_000_000_000L && intervalCount >= 30) vsyncStats(frameTimeNanos);
        Choreographer.getInstance().postFrameCallback(this);
    }

    /* Every 2 s: the median vsync interval against the Display's rate (C2), its p50/p95 for win lines. */
    private void vsyncStats(long now) {
        long[] sorted = Arrays.copyOf(intervals, intervalCount);
        Arrays.sort(sorted);
        float p50 = sorted[sorted.length / 2] / 1e6f, p95 = sorted[Math.min(sorted.length - 1, (int) (sorted.length * .95f))] / 1e6f;
        intervalCount = 0;
        statsStart = now;
        if (diag) { nativeState(STATE_VSYNC50, p50); nativeState(STATE_VSYNC95, p95); }
        float measured = 1000f / p50;
        boolean differs = displayHz > 0 && Math.abs(measured - displayHz) > displayHz * .10f;
        /* Two windows in a row either way: a busy UI thread's missed callbacks do not flip the cap. */
        disagreements = differs ? disagreements + 1 : 0;
        agreements = differs ? 0 : agreements + 1;
        if (differs && !mismatch && disagreements >= 2) {
            mismatch = true;
            if (diag) {
                nativeState(STATE_MISMATCH, 1);
                line("event", String.format(Locale.ROOT, "kind=refresh_mismatch display_hz=%.1f vsync_hz=%.1f", displayHz, measured));
            }
        } else if (!differs && mismatch && agreements >= 2) {
            mismatch = false;
            if (diag) {
                nativeState(STATE_MISMATCH, 0);
                line("event", String.format(Locale.ROOT, "kind=refresh_ok display_hz=%.1f vsync_hz=%.1f", displayHz, measured));
            }
        }
        send(mismatch ? measured : displayHz);
    }

    /* ------------------------------------------------------------------ lifecycle */
    void resume() {
        if (diag) { nativeState(STATE_LIFECYCLE, 2); line("event", "kind=resume"); }
        Display display = displays != null ? displays.getDisplay(displayId) : null;
        if (display != null) { displayHz = display.getRefreshRate(); if (!mismatch) send(displayHz); }
        if (!choreographing) {
            choreographing = true;
            lastVsync = statsStart = 0;
            intervalCount = 0;
            Choreographer.getInstance().postFrameCallback(this);
        }
    }

    void pause() {
        choreographing = false;
        Choreographer.getInstance().removeFrameCallback(this);
        if (diag) { nativeState(STATE_PAUSE, 1); line("event", "kind=pause"); }
    }

    void focus(boolean on) { if (diag) { nativeState(STATE_LIFECYCLE, 3); line("event", "kind=focus on=" + (on ? 1 : 0)); } }

    void surface(String state) { if (diag) { nativeState(STATE_LIFECYCLE, 4); line("event", "kind=surface state=" + state); } }

    void trim(int level) { if (diag) line("event", "kind=trim level=" + level); }

    void destroy() {
        stopped = true;
        pause();
        if (displays != null) displays.unregisterDisplayListener(this);
        try {
            if (battery != null) activity.unregisterReceiver(battery);
            if (powerSave != null) activity.unregisterReceiver(powerSave);
            if (tempState != null) activity.unregisterReceiver(tempState);
        } catch (RuntimeException ignored) {}
        if (Build.VERSION.SDK_INT >= 29 && thermalListener != null) {
            PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
            if (power != null) power.removeThermalStatusListener((PowerManager.OnThermalStatusChangedListener) thermalListener);
        }
    }

    /* ------------------------------------------------------------------ lines */
    static String word(String text) {
        if (text == null) return "";
        StringBuilder out = new StringBuilder(text.length());
        for (byte b : text.getBytes(StandardCharsets.UTF_8)) {
            int c = b & 0xFF;
            if (c <= ' ' || c == '%' || c == 0x7F) out.append(String.format(Locale.ROOT, "%%%02X", c));
            else out.append((char) c);
        }
        try { return new String(out.toString().getBytes(StandardCharsets.ISO_8859_1), StandardCharsets.UTF_8); }
        catch (RuntimeException e) { return out.toString(); }
    }

    private static String now() { return String.format(Locale.ROOT, "%.3f", System.nanoTime() / 1e6); }

    private void line(String type, String body) {
        if (!diag) return;
        nativeLine("[hyperos] " + type + " t=" + now() + " diag=1 " + body);
    }

    private String setting(boolean secure, String key) {
        try {
            ContentResolver resolver = activity.getContentResolver();
            String value = secure ? Settings.Secure.getString(resolver, key) : Settings.System.getString(resolver, key);
            return value == null ? "" : word(value);
        } catch (Throwable e) {
            return "!" + e.getClass().getSimpleName();
        }
    }

    @SuppressWarnings("deprecation")
    private void displayLine(String why) {
        displayLineDone = true;
        Display display = displays != null ? displays.getDisplay(displayId) : null;
        StringBuilder modes = new StringBuilder();
        if (display != null)
            for (Display.Mode mode : display.getSupportedModes()) {
                if (modes.length() > 0) modes.append(',');
                modes.append(mode.getModeId()).append(':').append(mode.getPhysicalWidth()).append('x')
                    .append(mode.getPhysicalHeight()).append('@').append(String.format(Locale.ROOT, "%.1f", mode.getRefreshRate()));
            }
        PowerManager power = (PowerManager) activity.getSystemService(Context.POWER_SERVICE);
        String gameMode = "!absent";
        if (Build.VERSION.SDK_INT >= 31) {
            try {
                android.app.GameManager games = (android.app.GameManager) activity.getSystemService(Context.GAME_SERVICE);
                gameMode = games != null ? String.valueOf(games.getGameMode()) : "!absent";
            } catch (Throwable e) { gameMode = "!" + e.getClass().getSimpleName(); }
        }
        Intent batteryNow = activity.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        int level = batteryNow != null ? batteryNow.getIntExtra(BatteryManager.EXTRA_LEVEL, -1) : -1;
        int scale = batteryNow != null ? batteryNow.getIntExtra(BatteryManager.EXTRA_SCALE, 100) : 100;
        line("display", String.format(Locale.ROOT,
            "why=%s modes=%s mode=%d hz=%.1f pref_mode=%d vote=%.1f vote_api=%d power_save=%d sustained=%d thermal_status=%s "
            + "game_mode=%s brightness=%s brightness_mode=%s battery=%d plugged=%d battery_temp=%.1f gb_boosting=%s "
            + "thermal_limit_refresh_rate=%s peak_refresh_rate=%s min_refresh_rate=%s user_refresh_rate=%s miui_refresh_rate=%s",
            why, modes.length() > 0 ? modes : "-", display != null && display.getMode() != null ? display.getMode().getModeId() : -1,
            display != null ? display.getRefreshRate() : 0f, requestedMode, requestedVote, Build.VERSION.SDK_INT >= 31 ? 31 : Build.VERSION.SDK_INT >= 30 ? 30 : 0,
            power != null && power.isPowerSaveMode() ? 1 : 0, power != null && power.isSustainedPerformanceModeSupported() ? 1 : 0,
            Build.VERSION.SDK_INT >= 29 && power != null ? String.valueOf(power.getCurrentThermalStatus()) : "!absent",
            gameMode, setting(false, Settings.System.SCREEN_BRIGHTNESS), setting(false, Settings.System.SCREEN_BRIGHTNESS_MODE),
            scale > 0 && level >= 0 ? level * 100 / scale : -1,
            batteryNow != null ? batteryNow.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) : -1,
            batteryNow != null ? batteryNow.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10f : 0f,
            setting(true, "gb_boosting"), setting(false, "thermal_limit_refresh_rate"), setting(false, "peak_refresh_rate"),
            setting(false, "min_refresh_rate"), setting(false, "user_refresh_rate"), setting(false, "miui_refresh_rate")));
    }

    /* ------------------------------------------------------------------ vendor log */
    /* The process may read its own logcat: vendor lines (DynamicFPS in libmigui, MiGL, meow,
       FPSGO, thermal) 15 s after the start, every 60 s and after 5+ long frames (≥ 10 s apart). */
    private void vendorLog() {
        double seen = 0;
        Set<String> recent = new HashSet<>();
        ArrayDeque<String> order = new ArrayDeque<>();
        long start = System.nanoTime(), lastDump = 0, nextPeriodic = start + 15_000_000_000L;
        int lastLong = 0;
        while (!stopped) {
            try { Thread.sleep(2000); } catch (InterruptedException e) { return; }
            long now = System.nanoTime();
            int longFrames = nativeLongFrames();
            boolean burst = longFrames - lastLong >= 5 && now - lastDump >= 10_000_000_000L && now - start >= 15_000_000_000L;
            if (now < nextPeriodic && !burst) continue;
            lastLong = longFrames;
            lastDump = now;
            if (now >= nextPeriodic) nextPeriodic = now + 60_000_000_000L;
            seen = dumpVendorLog(seen, recent, order);
        }
    }

    private double dumpVendorLog(double seen, Set<String> recent, ArrayDeque<String> order) {
        java.util.List<String> lines = new java.util.ArrayList<>();
        double newest = seen;
        Process process = null;
        try {
            process = new ProcessBuilder("logcat", "-d", "-v", "monotonic", "--pid=" + android.os.Process.myPid())
                .redirectErrorStream(true).start();
            try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream(), StandardCharsets.UTF_8))) {
                String row;
                while ((row = reader.readLine()) != null) {
                    Matcher m = LOGCAT.matcher(row);
                    if (!m.matches()) continue;
                    double at = Double.parseDouble(m.group(1));
                    if (at <= seen) continue;
                    if (at > newest) newest = at;
                    String tag = m.group(5), message = m.group(6);
                    if ("HeroesV".equals(tag) || message.startsWith("[hyperos]")) continue;
                    if (!VENDOR.matcher(tag).find() && !VENDOR.matcher(message).find()) continue;
                    String key = tag + ":" + message;
                    if (recent.contains(key)) continue;
                    recent.add(key);
                    order.add(key);
                    if (order.size() > 400) recent.remove(order.removeFirst());
                    if (lines.size() < 50)
                        lines.add("lt=" + m.group(1) + " pid=" + m.group(2) + " tid=" + m.group(3) + " prio=" + m.group(4)
                            + " tag=" + word(tag) + " msg=" + word(message.length() > 600 ? message.substring(0, 600) : message));
                }
            }
            process.waitFor();
        } catch (Exception e) {
            line("vendorlog", "n=0 error=!" + e.getClass().getSimpleName());
            return newest;
        } finally {
            if (process != null) process.destroy();
        }
        line("vendorlog", "n=" + lines.size());
        for (String l : lines) line("vendorlog", l);
        return newest;
    }
}
