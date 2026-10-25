package org.homm5.port;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

/** Keeps the process running, and the CPU awake, while the launcher converts
 *  textures or rewrites the game's archives (minutes; in the background
 *  Android would freeze or kill it), with its progress in a notification.
 *  Textures.current is the work. */
public final class TextureService extends Service {
    private static final String CHANNEL = "textures";
    private static final int PROGRESS = 3, RESULT = 4;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private NotificationManager notifications;
    private Notification.Builder builder;
    private PowerManager.WakeLock awake;

    @Override public void onCreate() {
        super.onCreate();
        notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, Launcher.text(Launcher.T_TEX_TITLE),
            NotificationManager.IMPORTANCE_LOW));
        notifications.cancel(RESULT);
        builder = new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(title(Textures.current))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(open(0));
        startForeground(PROGRESS, builder.build());
        awake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "HeroesV:textures");
        awake.acquire(2 * 60 * 60 * 1000L);
        handler.post(tick);
    }

    private PendingIntent open(int request) {
        Intent open = new Intent(this, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        return PendingIntent.getActivity(this, request, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static String title(Textures.Job job) {
        return Launcher.text(job != null && job.kind == Textures.REMOVE_ORIGINALS ? Launcher.T_TEX_REWRITING : Launcher.T_TEX_RUNNING);
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            Textures.Job job = Textures.current;
            if (job == null || job.finished) {
                if (job != null && !Launcher.visible) result(job);
                stopForeground(true);
                stopSelf();
                return;
            }
            long[] p = job.progress();
            long total = Math.max(1, p[4]);
            builder.setContentTitle(title(job)).setProgress(1000, (int) (p[3] * 1000 / total), p[4] == 0)
                .setContentText(p[2] > 0 ? Launcher.fmt(Launcher.T_TEX_COUNT, p[1], p[2]) : Launcher.text(Launcher.T_TEX_SCANNING));
            notifications.notify(PROGRESS, builder.build());
            handler.postDelayed(this, 1000);
        }
    };

    /** The launcher is not on the screen: say how it ended there. */
    private void result(Textures.Job job) {
        boolean ok = job.failure == null && !job.cancelled;
        notifications.notify(RESULT, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(ok ? android.R.drawable.stat_sys_download_done : android.R.drawable.stat_notify_error)
            .setContentTitle(Launcher.text(ok ? Launcher.T_TEX_FINISHED : job.cancelled ? Launcher.T_TEX_STOPPED : Launcher.T_TEX_FAILED))
            .setContentText(job.failure != null ? job.failure : job.game.getPath())
            .setAutoCancel(true)
            .setContentIntent(open(1))
            .build());
    }

    static void cancelResult(android.content.Context c) {
        c.getSystemService(NotificationManager.class).cancel(RESULT);
    }

    @Override public int onStartCommand(Intent intent, int flags, int id) { return START_NOT_STICKY; }

    @Override public void onDestroy() {
        handler.removeCallbacks(tick);
        if (awake != null && awake.isHeld()) awake.release();
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
