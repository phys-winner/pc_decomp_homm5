package org.homm5.port;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ShortcutInfo;
import android.content.pm.ShortcutManager;
import android.graphics.drawable.Icon;
import java.util.ArrayList;
import java.util.List;

/** Long-press actions on the one launcher icon; game actions do not start a launcher activity. */
final class GameShortcuts {
    static void install(Context context) {
        ShortcutManager manager = context.getSystemService(ShortcutManager.class);
        if (manager == null || manager.isRateLimitingActive()) return;
        try {
            String pkg = context.getPackageName();
            ComponentName home = new ComponentName(pkg, pkg + ".launcher.LauncherActivity");
            boolean ru = "ru".equals(context.getResources().getConfiguration().getLocales().get(0).getLanguage());
            String[] ids = {"vanilla", "hof", "toe", "launcher"};
            String[] activities = {"VanillaGameActivity", "HofGameActivity", "GameActivity", "launcher.LauncherActivity"};
            String[] labels = {"Heroes V 1.6", "Hammers of Fate 2.1", "Tribes of the East 3.1", ru ? "Лаунчер" : "Launcher"};
            int icon = context.getResources().getIdentifier("ic_launcher", "mipmap", pkg);
            List<ShortcutInfo> actions = new ArrayList<>();
            for (int i = 0; i < ids.length; ++i) {
                Intent intent = new Intent(Intent.ACTION_MAIN).setClassName(pkg, pkg + "." + activities[i])
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
                if (i == 3) intent.putExtra("launcher.show", true); // Never let autoLaunch turn this into Play.
                ShortcutInfo.Builder action = new ShortcutInfo.Builder(context, "homm5." + ids[i])
                    .setActivity(home).setShortLabel(labels[i]).setLongLabel(labels[i]).setRank(i).setIntent(intent);
                if (icon != 0) action.setIcon(Icon.createWithResource(context, icon));
                actions.add(action.build());
            }
            if (manager.getMaxShortcutCountPerActivity() >= actions.size()) manager.setDynamicShortcuts(actions);
        } catch (RuntimeException error) {
            android.util.Log.w("HeroesV", "Could not update launcher shortcuts", error);
        }
    }

    private GameShortcuts() { }
}
