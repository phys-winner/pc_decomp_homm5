package org.homm5.port;

import android.app.ActivityManager;
import android.app.ApplicationExitInfo;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.os.Build;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** Tribes of the East's homm5.log across game sessions. A player who restarts after a crash
 *  used to overwrite the log that recorded it; now the two previous logs stay beside the new
 *  one (homm5.1.log, homm5.2.log), the previous one ends with how Android saw its process end
 *  (ApplicationExitInfo, Android 11+: a native crash, a kill for memory, an ANR with its trace,
 *  an exit of the game itself), and a Java exception that takes the game down is written into
 *  the current log first. The engine (core.c) appends to the log this class begins. */
final class SessionLog {
    static final String LOG = "homm5.log";
    private static final String PREFERENCES = "session_log", REPORTED = "reported_exit";
    private static final int TRACE_LIMIT = 64 * 1024;
    private static boolean begun;

    private SessionLog() {}

    /** Once per game process, before the engine opens the log. */
    static synchronized void begin(Context context, File data) {
        if (begun) return;
        begun = true;
        File log = new File(data, LOG), previous = new File(data, "homm5.1.log"), older = new File(data, "homm5.2.log");
        if (previous.exists() && (!older.exists() || older.delete())) rename(previous, older);
        if (log.exists()) rename(log, previous);
        String exit = previousExit(context);
        if (exit != null) append(previous, exit);
        StringBuilder header = new StringBuilder(header(context));
        if (exit != null) header.append("[session] ").append(exit.substring(0, exit.indexOf('\n'))).append('\n');
        append(log, header.toString());
        Thread.UncaughtExceptionHandler fallback = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((thread, error) -> {
            append(log, "[java] uncaught exception on thread \"" + thread.getName() + "\": "
                + android.util.Log.getStackTraceString(error));
            if (fallback != null) fallback.uncaughtException(thread, error);
            else System.exit(10);
        });
    }

    private static void rename(File from, File to) {
        if (!from.renameTo(to)) android.util.Log.w("HeroesV", "log not moved: " + from + " -> " + to);
    }

    static void append(File file, String text) {
        try (OutputStream out = new FileOutputStream(file, true)) {
            out.write((text.endsWith("\n") ? text : text + "\n").getBytes(StandardCharsets.UTF_8));
        } catch (IOException e) {
            android.util.Log.w("HeroesV", "log " + file + ": " + e);
        }
    }

    private static String time(long millis) {
        return new SimpleDateFormat("yyyy-MM-dd HH:mm:ss", Locale.ROOT).format(new Date(millis));
    }

    private static String header(Context context) {
        String version = "?";
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            version = info.versionName + " (" + (Build.VERSION.SDK_INT >= 28 ? info.getLongVersionCode() : info.versionCode) + ")";
        } catch (Exception ignored) {}
        String soc = Build.VERSION.SDK_INT >= 31 ? Build.SOC_MANUFACTURER + " " + Build.SOC_MODEL : Build.HARDWARE;
        return "[session] Heroes V " + version + " started " + time(System.currentTimeMillis()) + " on "
            + Build.MANUFACTURER + " " + Build.MODEL + " (" + Build.DEVICE + "), Android " + Build.VERSION.RELEASE
            + " (SDK " + Build.VERSION.SDK_INT + "), " + soc + ", " + Build.SUPPORTED_ABIS[0] + "\n";
    }

    /** The newest end of this game process that no log has reported yet, or null. */
    private static String previousExit(Context context) {
        if (Build.VERSION.SDK_INT < 30) return null;
        try {
            ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
            List<ApplicationExitInfo> exits = manager.getHistoricalProcessExitReasons(context.getPackageName(), 0, 16);
            String process = android.app.Application.getProcessName();   /* this game's own process */
            SharedPreferences preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
            String key = REPORTED + ":" + process;
            for (ApplicationExitInfo exit : exits) {
                if (!process.equals(exit.getProcessName())) continue;
                if (exit.getTimestamp() <= preferences.getLong(key, 0)) return null;
                preferences.edit().putLong(key, exit.getTimestamp()).apply();
                return describe(exit);
            }
        } catch (RuntimeException e) {
            android.util.Log.w("HeroesV", "exit reasons: " + e);
        }
        return null;
    }

    private static String describe(ApplicationExitInfo exit) {
        int reason = exit.getReason(), status = exit.getStatus();
        String detail = reason == ApplicationExitInfo.REASON_EXIT_SELF
            ? "exit code " + status + (status == 70 ? " (an engine error, reported above)" : "")
            : reason == ApplicationExitInfo.REASON_CRASH_NATIVE || reason == ApplicationExitInfo.REASON_SIGNALED
            ? "signal " + status : "status " + status;
        StringBuilder text = new StringBuilder("[exit] the game process ended " + time(exit.getTimestamp()) + ": "
            + reason(reason) + ", " + detail);
        if (exit.getDescription() != null) text.append(", \"").append(exit.getDescription()).append('"');
        text.append(", memory ").append(exit.getPss() / 1024).append(" MiB PSS / ").append(exit.getRss() / 1024)
            .append(" MiB RSS\n");
        if (exit.getReason() == ApplicationExitInfo.REASON_CRASH_NATIVE)
            text.append("[exit] Android kept a tombstone of this native crash (adb bugreport)\n");
        if (exit.getReason() == ApplicationExitInfo.REASON_ANR) {
            /* The ANR trace is text: the threads' stacks when the game stopped answering. */
            try (InputStream trace = exit.getTraceInputStream()) {
                if (trace != null) {
                    byte[] buffer = new byte[TRACE_LIMIT];
                    int length = 0, read;
                    while (length < buffer.length && (read = trace.read(buffer, length, buffer.length - length)) > 0) length += read;
                    text.append("[exit] ANR trace (first ").append(length).append(" bytes):\n")
                        .append(new String(buffer, 0, length, StandardCharsets.UTF_8)).append('\n');
                }
            } catch (IOException | RuntimeException e) {
                text.append("[exit] ANR trace unavailable: ").append(e).append('\n');
            }
        }
        return text.toString();
    }

    private static String reason(int reason) {
        switch (reason) {
            case ApplicationExitInfo.REASON_EXIT_SELF: return "the game closed itself";
            case ApplicationExitInfo.REASON_SIGNALED: return "killed by a signal";
            case ApplicationExitInfo.REASON_LOW_MEMORY: return "killed by Android for low memory";
            case ApplicationExitInfo.REASON_CRASH: return "Java crash";
            case ApplicationExitInfo.REASON_CRASH_NATIVE: return "native crash";
            case ApplicationExitInfo.REASON_ANR: return "not responding (ANR)";
            case ApplicationExitInfo.REASON_INITIALIZATION_FAILURE: return "initialization failure";
            case ApplicationExitInfo.REASON_PERMISSION_CHANGE: return "a permission changed";
            case ApplicationExitInfo.REASON_EXCESSIVE_RESOURCE_USAGE: return "killed for excessive resource use";
            case ApplicationExitInfo.REASON_USER_REQUESTED: return "stopped by the user (swiped away or force stop)";
            case ApplicationExitInfo.REASON_USER_STOPPED: return "stopped with the user";
            case ApplicationExitInfo.REASON_DEPENDENCY_DIED: return "a dependency died";
            case ApplicationExitInfo.REASON_OTHER: return "other system reason";
            case 14: return "freezer";                 /* REASON_FREEZER, Android 13 */
            case 15: return "package state changed";   /* REASON_PACKAGE_STATE_CHANGE, Android 14 */
            case 16: return "package updated";         /* REASON_PACKAGE_UPDATED, Android 14 */
            default: return "unknown reason " + reason;
        }
    }
}
