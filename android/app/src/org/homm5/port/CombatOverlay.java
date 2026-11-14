package org.homm5.port;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.TextView;
import java.util.function.IntConsumer;

/** Native battle previews own the route; this layer confirms orders and shows touch hints. */
final class CombatOverlay extends FrameLayout {
    private final Button confirm;
    private final TextView hint;
    private final boolean russian;
    private int generation, hintEpoch, hintKind, dismissedEpoch;
    private boolean running = true;
    private float uiScale = 1;

    CombatOverlay(Context context, boolean russian, IntConsumer action) {
        super(context);
        if (Build.VERSION.SDK_INT >= 29) setForceDarkAllowed(false);
        this.russian = russian;
        setClipChildren(false);
        confirm = new Button(context);
        confirm.setText(russian ? "Подтвердить" : "Confirm action");
        confirm.setTextColor(0xFFFFEDBA);
        confirm.setTextSize(15);
        confirm.setTypeface(Typeface.create("serif", Typeface.BOLD));
        confirm.setAllCaps(false);
        confirm.setMinHeight(dp(48));
        confirm.setMinimumHeight(dp(48));
        confirm.setPadding(dp(20), dp(6), dp(20), dp(6));
        confirm.setBackground(panel(0xEF304634, 0xF016241B));
        confirm.setElevation(dp(3));
        confirm.setOnClickListener(view -> {
            int selected = generation;
            if (selected == 0 || !confirm.isEnabled()) return;
            confirm.setEnabled(false);
            action.accept(selected);
        });
        addView(confirm, new LayoutParams(-2, dp(48), Gravity.BOTTOM | Gravity.RIGHT));
        hint = new TextView(context);
        hint.setTextColor(0xFFFFE9BD);
        hint.setTextSize(14);
        hint.setGravity(Gravity.CENTER);
        hint.setPadding(dp(16), dp(8), dp(16), dp(8));
        hint.setBackground(panel(0xE42E3028, 0xE416201B));
        hint.setClickable(true);
        hint.setFocusable(true);
        hint.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        hint.setOnClickListener(view -> {
            dismissedEpoch = hintEpoch;
            hint.setVisibility(GONE);
            if (generation == 0) setVisibility(GONE);
        });
        LayoutParams hints = new LayoutParams(-2, -2, Gravity.TOP | Gravity.CENTER_HORIZONTAL);
        hints.setMargins(dp(24), dp(12), dp(24), 0);
        addView(hint, hints);
        update(0, 0, 0);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private GradientDrawable panel(int top, int bottom) {
        GradientDrawable background = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{top, bottom});
        background.setCornerRadius(dp(6));
        background.setStroke(dp(1), 0xFFC5A76A);
        return background;
    }

    void update(int generation, int hintEpoch, int hintKind) {
        if (this.generation != generation) confirm.setEnabled(true);
        boolean changedHint = this.hintEpoch != hintEpoch || this.hintKind != hintKind;
        this.generation = generation;
        this.hintEpoch = hintEpoch;
        this.hintKind = hintKind;
        confirm.setVisibility(generation != 0 ? VISIBLE : GONE);
        if (hintKind != 0 && hintEpoch != dismissedEpoch) {
            if (changedHint) {
                String attack = hintKind == 1 ? (russian ? "рукопашной атаки стрелка" : "a shooter's melee attack")
                    : hintKind == 2 ? (russian ? "атаки без возвращения" : "an attack without returning")
                    : (russian ? "рукопашной атаки или атаки без возвращения" : "melee or an attack without returning");
                hint.setText(russian ? "Проведите от своего отряда к цели для " + attack + ".  ×"
                    : "Drag from your unit to its target for " + attack + ".  ×");
                hint.setContentDescription(hint.getText() + (russian ? " Коснитесь, чтобы скрыть." : " Tap to hide."));
            }
            hint.setVisibility(VISIBLE);
        } else hint.setVisibility(GONE);
        setVisibility(running && (generation != 0 || hint.getVisibility() == VISIBLE) ? VISIBLE : GONE);
    }

    void setRunning(boolean value) {
        running = value;
        setVisibility(value && (generation != 0 || hint.getVisibility() == VISIBLE) ? VISIBLE : GONE);
    }

    void setUiScale(float value) {
        float next = Float.isFinite(value) ? Math.max(0.5f, Math.min(2, value)) : 1;
        if (uiScale == next) return;
        uiScale = next;
        positionControls(getWidth(), getHeight());
    }

    private void positionControls(int width, int height) {
        if (width <= 0 || height <= 0) return;
        LayoutParams position = (LayoutParams)confirm.getLayoutParams();
        position.gravity = Gravity.BOTTOM | Gravity.RIGHT;
        position.rightMargin = dp(12);
        position.bottomMargin = Math.max(dp(12), Math.min(height - dp(60), Math.round(height * 0.27f * uiScale)));
        confirm.setLayoutParams(position);
        hint.setMaxWidth(Math.max(dp(160), width - dp(48)));
    }

    @Override protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        positionControls(width, height);
    }

}
