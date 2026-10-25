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

/** Keeps the process in the foreground while the launcher unpacks the game
 *  (several minutes for the game; in the background Android would freeze it),
 *  its progress in a notification. Unpacker.current is the work. */
public final class UnpackService extends Service {
    private static final String CHANNEL = "unpack";
    private static final int PROGRESS = 1, RESULT = 2;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private NotificationManager notifications;
    private Notification.Builder builder;

    @Override public void onCreate() {
        super.onCreate();
        notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(CHANNEL, Launcher.text(Launcher.T_UNPACKING_TITLE),
            NotificationManager.IMPORTANCE_LOW));
        notifications.cancel(RESULT);
        Intent open = new Intent(this, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        builder = new Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle(Launcher.text(Launcher.T_UNPACKING_TITLE))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        startForeground(PROGRESS, builder.build());
        handler.post(tick);
    }

    private final Runnable tick = new Runnable() {
        @Override public void run() {
            Unpacker.Job job = Unpacker.current;
            if (job == null || job.finished) {
                if (job != null && !Launcher.visible) result(job);
                stopForeground(true);
                stopSelf();
                return;
            }
            long size = Math.max(1, job.plan.size);
            builder.setProgress(1000, (int) (job.done * 1000 / size), false)
                .setContentText(Launcher.progressText(job.done, job.plan.size));
            notifications.notify(PROGRESS, builder.build());
            handler.postDelayed(this, 1000);
        }
    };

    /** The launcher is not on the screen: say how it ended there. */
    private void result(Unpacker.Job job) {
        Intent open = new Intent(this, Launcher.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        boolean ok = job.failure == null;
        notifications.notify(RESULT, new Notification.Builder(this, CHANNEL)
            .setSmallIcon(ok ? android.R.drawable.stat_sys_download_done : android.R.drawable.stat_notify_error)
            .setContentTitle(Launcher.text(ok ? Launcher.T_UNPACKED_TITLE : Launcher.T_FAILED_TITLE))
            .setContentText(job.target.getPath())
            .setAutoCancel(true)
            .setContentIntent(PendingIntent.getActivity(this, 1, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT))
            .build());
    }

    static void cancelResult(android.content.Context c) {
        c.getSystemService(NotificationManager.class).cancel(RESULT);
    }

    @Override public int onStartCommand(Intent intent, int flags, int id) { return START_NOT_STICKY; }

    @Override public void onDestroy() {
        handler.removeCallbacks(tick);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
