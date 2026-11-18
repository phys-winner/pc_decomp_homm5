package org.homm5.port;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Rect;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.view.Gravity;
import android.view.InputDevice;
import android.view.PointerIcon;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;

/** Optional stack actions. The engine owns the selection token, validation and every army order. */
final class ArmyActions {
    interface Command { void run(int generation, int action); }
    private final Activity activity;
    private final FrameLayout root;
    private final SharedPreferences preferences;
    private final boolean russian;
    private final Command command;
    private final LinearLayout bar;
    private int generation;
    private boolean enabled;
    private AlertDialog suggestion;

    ArmyActions(Activity activity, FrameLayout root, SharedPreferences preferences, boolean russian, Command command) {
        this.activity = activity; this.root = root; this.preferences = preferences;
        this.russian = russian; this.command = command;
        bar = new LinearLayout(activity);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER);
        bar.setElevation(dp(8));
        bar.setPointerIcon(PointerIcon.getSystemIcon(activity, PointerIcon.TYPE_ARROW));
        GradientDrawable background = new GradientDrawable();
        background.setColor(0xf0221b12); background.setCornerRadius(dp(5));
        background.setStroke(dp(1), 0xffb79451);
        bar.setBackground(background);
        String[] labels = {"1", "½", "="};
        String[] descriptions = russian ? new String[] {"Отделить одного", "Отделить половину", "Поровну по свободным ячейкам"}
            : new String[] {"Split one", "Split half", "Distribute equally across free slots"};
        for (int i = 0; i < labels.length; ++i) {
            final int action = i;
            Button button = new Button(activity);
            button.setText(labels[i]); button.setTextSize(19); button.setTextColor(Color.rgb(244, 222, 168));
            button.setContentDescription(descriptions[i]); button.setPadding(0, 0, 0, 0);
            button.setMinimumWidth(0); button.setMinWidth(0);
            button.setMinimumHeight(0); button.setMinHeight(0);
            button.setBackgroundColor(Color.TRANSPARENT);
            button.setOnClickListener(v -> {
                int token = generation;
                hide();
                if (token != 0) command.run(token, action);
            });
            bar.addView(button, new LinearLayout.LayoutParams(dp(48), dp(48)));
        }
        bar.setVisibility(View.GONE);
        root.addView(bar, new FrameLayout.LayoutParams(dp(144), dp(48), Gravity.TOP | Gravity.LEFT));
    }

    private int dp(int value) { return Math.round(value * activity.getResources().getDisplayMetrics().density); }
    private String text(String en, String ru) { return russian ? ru : en; }

    void setEnabled(boolean value) { enabled = value; if (!enabled) hide(); }

    void hide() { generation = 0; bar.setVisibility(View.GONE); }

    boolean hit(float x, float y) {
        return bar.getVisibility() == View.VISIBLE && x >= bar.getX() && x < bar.getX() + bar.getWidth()
            && y >= bar.getY() && y < bar.getY() + bar.getHeight();
    }

    void show(int token, float x, float y, int width, int height) {
        if (!enabled || token <= 0 || width <= 0 || height <= 0 || !Float.isFinite(x) || !Float.isFinite(y)) {
            hide(); return;
        }
        // Inverse of android_main.c:map_touch_point, including a deliberately letterboxed game mode.
        float scale = Math.min(root.getWidth() / (float)width, root.getHeight() / (float)height);
        if (!(scale > 0)) { hide(); return; }
        float px = (root.getWidth() - width * scale) * .5f + x * scale;
        float py = (root.getHeight() - height * scale) * .5f + y * scale;
        Rect safe = new Rect(0, 0, root.getWidth(), root.getHeight());
        WindowInsets insets = root.getRootWindowInsets();
        if (Build.VERSION.SDK_INT >= 28 && insets != null && insets.getDisplayCutout() != null) {
            safe.left += insets.getDisplayCutout().getSafeInsetLeft();
            safe.right -= insets.getDisplayCutout().getSafeInsetRight();
            safe.top += insets.getDisplayCutout().getSafeInsetTop();
            safe.bottom -= insets.getDisplayCutout().getSafeInsetBottom();
        }
        bar.setX(Math.max(safe.left, Math.min(safe.right - dp(144), px - dp(72))));
        bar.setY(Math.max(safe.top, Math.min(safe.bottom - dp(48), py - dp(52))));
        generation = token;
        bar.setVisibility(View.VISIBLE);
    }

    /** Once per edition, after the game is ready. Never silently enable a preference for a mouse. */
    void offerForMouse() {
        if (enabled || suggestion != null || preferences.getBoolean("army_mouse_suggestion", false)
                || activity.isFinishing() || activity.isDestroyed()) return;
        boolean mouse = false;
        for (int id : InputDevice.getDeviceIds()) {
            InputDevice device = InputDevice.getDevice(id);
            if (device != null && device.supportsSource(InputDevice.SOURCE_MOUSE)) { mouse = true; break; }
        }
        if (!mouse) return;
        preferences.edit().putBoolean("army_mouse_suggestion", true).apply();
        suggestion = new AlertDialog.Builder(activity)
            .setTitle(text("Mouse connected", "Подключена мышь"))
            .setMessage(text("Enable the optional army buttons? Clicking a stack will offer split one, split half and equal distribution. You can also change this in Options → Additional → Interface.",
                "Включить кнопки разделения армии? Клик по отряду покажет: по одному, половину и поровну. Их также можно переключить в Настройки → Дополнительные → Интерфейс."))
            .setPositiveButton(text("Enable", "Включить"), (d, w) -> { enabled = true; command.run(0, 3); })
            .setNegativeButton(text("Not now", "Не сейчас"), null).create();
        suggestion.setOnDismissListener(d -> suggestion = null);
        suggestion.show();
    }

    void close() { hide(); if (suggestion != null) suggestion.dismiss(); }
}
