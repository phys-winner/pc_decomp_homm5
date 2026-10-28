package org.homm5.port;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.graphics.Color;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.hardware.input.InputManager;
import android.os.Bundle;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.InputDevice;
import android.view.PointerIcon;
import android.view.Display;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import android.view.View;
import android.view.HapticFeedbackConstants;
import android.view.Window;
import android.view.WindowManager;
import android.view.Gravity;
import android.view.WindowInsets;
import android.view.inputmethod.BaseInputConnection;
import android.view.inputmethod.EditorInfo;
import android.view.inputmethod.InputConnection;
import android.view.inputmethod.InputMethodManager;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import java.io.File;
import java.lang.ref.WeakReference;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;
import java.util.HashSet;

/** Finger gestures are resolved by the game's own UI, orders and camera code. */
public class GameActivity extends Activity implements SurfaceHolder.Callback {
    protected String gameEdition() { return "toe"; }

    private static native void nativeStart(String game, String data, String images, String overlay, String cache,
            int width, int height, boolean verbose);
    private static native void nativeSurface(Object surface);
    private static native void nativeKey(int scanCode, boolean down);
    private static native void nativeHardwareKey(int virtualKey, boolean down);
    private static native void nativePointer(float x, float y, boolean relative);
    private static native void nativeMouseButton(int button, boolean down);
    private static native void nativeWheel(int delta);
    private static native void nativePadCamera(float rotation, float tilt);
    private static native void nativeTouch(int kind, float x, float y, float dx, float dy, float scale, float rotationRadians);
    private static native void nativePause(boolean paused);
    private static native void nativeUiScale(float scale);
    private static native void nativeRenderScale(float scale);
    private static native void nativeCameraSensitivity(float value);
    private static native void nativeNewCreatureFramework(boolean enabled);
    private static native void nativeRefreshRates(float[] rates);
    private static native void nativeLanPeers(String peers);
    /** Tribes of the East's renderer (android/host/d3d9_dxvk.c): mode as RendererPolicy.nativeMode. */
    private static native void nativeRenderer(int mode, String libraryDir, String cacheDir);
    /** The mode the session renders with once Direct3D was created (-1 before; 0 OpenGL ES). */
    private static native int nativeRendererActive();
    private static native boolean nativeText(int generation, String text);
    private static native boolean nativeTextKey(int generation, int key, int count);
    private static native int nativeTextCancel();
    /** Startup work done so far (files opened), and whether the first screen is up. */
    private static native int nativeLoadWork();
    private static native boolean nativeLoadReady();
    private static native void nativeRequestGameSwitch();
    private static volatile WeakReference<GameActivity> currentActivity = new WeakReference<>(null);

    private static final int ESC = 0x01;
    private final Map<Integer, Runnable> keyReleases = new HashMap<>();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private TouchLayer touch;
    private HardwareInput hardware;
    private android.app.AlertDialog gamepadHelp;
    private android.app.AlertDialog gameSwitchDialog;
    private volatile Intent pendingGameLaunch;
    private GestureProbe gestureProbe;
    /* Wi-Fi chips drop broadcast and multicast frames to save power unless an
       app holds this: the LAN game finds its sessions by UDP broadcast. */
    private android.net.wifi.WifiManager.MulticastLock lanLock;
    private SurfaceView surface;
    private FrameLayout game;
    private LinearLayout textPreview;
    private TextView textPreviewValue;
    private HorizontalScrollView textPreviewScroll;
    private Surface refreshSurface;
    private SharedPreferences preferences;
    private boolean textEditing;
    private int textGeneration;
    private TextConnection textConnection;
    private String fieldText = "";
    private int fieldCaret;
    /* The loading screen over the black surface until the game shows its first screen. */
    private View loading;
    private ProgressBar loadingBar;
    private TextView loadingText;
    private long loadingStart;
    private int loadingExpected;
    private float loadingShown;
    private boolean nativeReady;
    private boolean resumed;
    /* The renderer of this start (RendererPolicy; OpenGL ES for the other editions). The DXVK
       modes keep one surface for the activity's life and hand it back on onStart (surfaceHidden). */
    private String renderer = RendererPolicy.GLES;
    private boolean surfaceHidden, rendererReported;
    private android.app.AlertDialog rendererDialog;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        requestWindowFeature(Window.FEATURE_NO_TITLE);
        game = new FrameLayout(this);
        createLoading();
        loadingBar.setIndeterminate(true);
        loadingText.setText(Locale.getDefault().getLanguage().equals("ru") ? "Подготовка игры…" : "Preparing game…");
        setContentView(game);
        new Thread(() -> {
            try {
                NativeLibrary.load(this, Games.library(gameEdition()));
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    nativeReady = true;
                    prepareRenderer();
                });
            } catch (java.io.IOException | UnsatisfiedLinkError e) {
                android.util.Log.e("HeroesV", "native library: " + e);
                runOnUiThread(() -> {
                    if (isFinishing() || isDestroyed()) return;
                    new android.app.AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                        .setMessage(e.getMessage()).setPositiveButton(android.R.string.ok, (dialog, which) -> finish())
                        .setOnCancelListener(dialog -> finish()).show();
                });
            }
        }, "native-library").start();
    }

    /* ------------------------------------------------------------ renderer */

    /** Tribes of the East: the renderer is fixed before the engine starts. While nobody has chosen
     *  a mode (the launcher picks the best one once its driver check has finished, or the player
     *  does), a start that would run on OpenGL ES offers the best mode once. No restart is needed:
     *  nothing has created Direct3D yet. */
    private void prepareRenderer() {
        /* DXVK/Turnip support is commented out (RendererPolicy.ENABLED): OpenGL ES, as for the other editions. */
        if (!RendererPolicy.ENABLED || !"toe".equals(gameEdition())) { startGame(); return; }
        String chosen = Renderers.chosen(this);
        boolean undecided = chosen.isEmpty()
            || (RendererPolicy.GLES.equals(chosen) && Renderers.AUTO.equals(Renderers.origin(this)));
        if (!undecided || Renderers.offered(this) || !Renderers.needsProbe(this)) { startRenderer(chosen); return; }
        if (Renderers.report(this) != null) { offerRenderer(chosen); return; }
        Renderers.probe(this);
        loadingText.setText(Renderers.ru() ? "Проверка видеодрайвера…" : "Checking the graphics driver…");
        final long until = SystemClock.uptimeMillis() + 6000;
        handler.postDelayed(new Runnable() {
            @Override public void run() {
                if (isFinishing() || isDestroyed()) return;
                if (Renderers.report(GameActivity.this) == null && SystemClock.uptimeMillis() < until) {
                    handler.postDelayed(this, 250);
                    return;
                }
                offerRenderer(chosen);
            }
        }, 250);
    }

    private void offerRenderer(String chosen) {
        java.util.Map<String, String> report = Renderers.report(this);
        if (report == null) { startRenderer(chosen); return; }   /* not checked in time: next start */
        String best = RendererPolicy.best(Renderers.statuses(this, report), report);
        if (RendererPolicy.GLES.equals(best)) {
            if (chosen.isEmpty()) Renderers.choose(this, RendererPolicy.GLES, Renderers.AUTO);
            startRenderer(RendererPolicy.GLES);
            return;
        }
        boolean ru = Renderers.ru();
        String title = RendererPolicy.title(best);
        rendererDialog = new android.app.AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle(ru ? "Режим отрисовки" : "Renderer")
            .setMessage(String.format(ru
                ? "Игра запускается на OpenGL ES, а этому устройству доступен %1$s.\n\n%2$s\n\n%3$s\n\nПереключиться? Выбор можно изменить в лаунчере."
                : "The game starts on OpenGL ES, and %1$s is available on this device.\n\n%2$s\n\n%3$s\n\nSwitch? The launcher can change it later.",
                title, RendererPolicy.description(best, ru), RendererPolicy.limits(ru)))
            .setPositiveButton(ru ? "Переключить на " + title : "Switch to " + title, (dialog, which) -> {
                Renderers.choose(this, best, Renderers.OFFER);
                Renderers.markOffered(this);
                startRenderer(best);
            })
            .setNegativeButton(ru ? "Оставить OpenGL ES" : "Keep OpenGL ES", (dialog, which) -> {
                Renderers.choose(this, RendererPolicy.GLES, Renderers.USER);
                Renderers.markOffered(this);
                startRenderer(RendererPolicy.GLES);
            })
            .setCancelable(false)
            .create();
        rendererDialog.setOnDismissListener(dialog -> rendererDialog = null);
        rendererDialog.show();
    }

    /** A chosen DXVK mode that is known not to run here any more starts on OpenGL ES; without a
     *  current check (just updated) the choice stands, and the engine falls back if DXVK fails. */
    private void startRenderer(String chosen) {
        if (isFinishing() || isDestroyed()) return;
        if ("toe".equals(gameEdition()) && RendererPolicy.valid(chosen) && !RendererPolicy.GLES.equals(chosen)) {
            java.util.Map<String, String> report = Renderers.report(this);
            RendererPolicy.Status status = RendererPolicy.status(Renderers.statuses(this, report), chosen);
            renderer = status.available || (report == null && Renderers.needsProbe(this)) ? chosen : RendererPolicy.GLES;
            if (!renderer.equals(chosen)) android.util.Log.w("HeroesV", "renderer " + chosen + " unavailable: " + status.reason);
        }
        startGame();
    }

    private boolean dxvkSurface() { return !RendererPolicy.GLES.equals(renderer) && Build.VERSION.SDK_INT >= 30; }

    private void startGame() {
        currentActivity = new WeakReference<>(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_FULLSCREEN | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (Build.VERSION.SDK_INT >= 28) {
            /* The picture covers the camera cutout too: without this a landscape window ends at it. */
            WindowManager.LayoutParams params = getWindow().getAttributes();
            params.layoutInDisplayCutoutMode = Build.VERSION.SDK_INT >= 30
                ? WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
                : WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            getWindow().setAttributes(params);
        }
        setVolumeControlStream(android.media.AudioManager.STREAM_MUSIC);
        hideSystemUi();
        game = new FrameLayout(this);
        game.setBackgroundColor(Color.BLACK);
        surface = new SurfaceView(this);
        /* DXVK keeps a presenter (swapchain) per window: one surface for the activity's life,
           hidden and handed back around onStop/onStart, never leaves one behind per Home press. */
        if (dxvkSurface()) surface.setSurfaceLifecycle(SurfaceView.SURFACE_LIFECYCLE_FOLLOWS_ATTACHMENT);
        surface.getHolder().addCallback(this);
        game.addView(surface, new FrameLayout.LayoutParams(-1, -1));
        touch = new TouchLayer(this);
        game.addView(touch, new FrameLayout.LayoutParams(-1, -1));
        PointerIcon invisible = PointerIcon.getSystemIcon(this, PointerIcon.TYPE_NULL);
        game.setPointerIcon(invisible);
        surface.setPointerIcon(invisible);
        touch.setPointerIcon(invisible);
        hardware = new HardwareInput();
        ((InputManager)getSystemService(Context.INPUT_SERVICE)).registerInputDeviceListener(hardware, handler);
        createTextPreview();
        createLoading();
        setContentView(game);

        preferences = getSharedPreferences(Games.preferences(gameEdition()), MODE_PRIVATE);
        File base = Launcher.baseDir();
        gestureProbe = GestureProbe.register(this, touch, base);
        try {
            android.net.wifi.WifiManager wifi = (android.net.wifi.WifiManager) getApplicationContext()
                .getSystemService(Context.WIFI_SERVICE);
            if (wifi != null) {
                lanLock = wifi.createMulticastLock("HeroesV:lan");
                lanLock.setReferenceCounted(false);
            }
        } catch (RuntimeException e) {
            android.util.Log.w("HeroesV", "no Wi-Fi multicast lock: " + e);
        }
        File data = new File(base, Games.userdata(gameEdition()));
        data.mkdirs();
        File gameDir = Launcher.chosenGame(this, getIntent(), gameEdition());
        if (gameDir == null) {
            startActivity(new Intent(this, Launcher.class).putExtra("game_exited", true).putExtra("edition", gameEdition()));
            finish();
            return;
        }
        File images = Assets.images(this, base, gameEdition());
        File overlay = Assets.overlay(this, Launcher.skipIntro(this), gameEdition());
        File cache = new File(getCacheDir(), Games.cache(gameEdition()));
        cache.mkdirs();
        /* The saved scales seed the game's port variables before it registers them. */
        nativeUiScale(savedFloat("ui_scale", 1));
        nativeRenderScale(savedFloat("render_scale", 1));
        nativeCameraSensitivity(savedFloat("camera_sensitivity", 1));
        /* MMH5.5's New Creature Framework patches exist for the 3.1 engine only (android/host/ncf.c). */
        if ("toe".equals(gameEdition())) nativeNewCreatureFramework(Launcher.newCreatureFramework(this));
        /* ToE's frame rate combobox lists the display's own rates (port_settings.c). */
        if ("toe".equals(gameEdition())) nativeRefreshRates(displayRefreshRates());
        /* Tailscale/VPN players for the LAN search, used with the game's option (network.c). */
        if ("toe".equals(gameEdition())) nativeLanPeers(Launcher.lanPeers(this));
        /* So is the DXVK renderer (android/host/d3d9_dxvk.c): its libraries were extracted with the APK. */
        if (RendererPolicy.ENABLED && "toe".equals(gameEdition())) {
            nativeRenderer(RendererPolicy.nativeMode(renderer), getApplicationInfo().nativeLibraryDir, getCacheDir().getAbsolutePath());
            Renderers.startedWith(this, renderer);
            android.util.Log.i("HeroesV", "renderer " + renderer);
        }
        android.util.Log.i("HeroesV", "game " + gameDir + ", images " + images + ", overlay " + overlay);
        /* Until this start shows its first screen, the icon opens the launcher: a start that
           crashes or hangs must not be repeated by every later tap on the icon. */
        if (!Launcher.startupMarker(this, gameEdition()).delete() && Launcher.startupMarker(this, gameEdition()).exists())
            android.util.Log.w("HeroesV", "startup marker stays");
        nativeStart(gameDir.getAbsolutePath(), data.getAbsolutePath(), images.getAbsolutePath(),
                overlay != null ? overlay.getAbsolutePath() : null, cache.getAbsolutePath(), 0, 0,
                new File(base, "verbose").exists());
        nativePause(!resumed);
        if (resumed && lanLock != null && !lanLock.isHeld()) lanLock.acquire();
        startLoading();
    }

    private float savedFloat(String key, float fallback) {
        try { return preferences.getFloat(key, fallback); }
        catch (ClassCastException ignored) { return fallback; }
    }

    /* Refresh rates of the display's modes at its current resolution. */
    private float[] displayRefreshRates() {
        Display display = getWindowManager().getDefaultDisplay();
        Display.Mode current = display != null ? display.getMode() : null;
        Display.Mode[] modes = display != null ? display.getSupportedModes() : null;
        if (current == null || modes == null) return new float[0];
        float[] rates = new float[modes.length];
        int count = 0;
        for (Display.Mode mode : modes)
            if (mode != null && mode.getPhysicalWidth() == current.getPhysicalWidth()
                    && mode.getPhysicalHeight() == current.getPhysicalHeight() && Float.isFinite(mode.getRefreshRate()))
                rates[count++] = mode.getRefreshRate();
        return java.util.Arrays.copyOf(rates, count);
    }

    private int dp(float value) { return Math.round(value * getResources().getDisplayMetrics().density); }

    private void pulseKey(int code) {
        Runnable previous = keyReleases.remove(code);
        if (previous != null) touch.removeCallbacks(previous);
        else nativeKey(code, true);
        Runnable release = () -> { nativeKey(code, false); keyReleases.remove(code); };
        keyReleases.put(code, release);
        touch.postDelayed(release, 100);
    }

    private void hideSystemUi() {
        getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) { hideSystemUi(); requestHighRefresh(); }
        else if (touch != null) releaseAll();
    }

    private static int chooseRefreshMode(Display.Mode current, Display.Mode[] modes) {
        if (current == null || modes == null || current.getPhysicalWidth() <= 0 || current.getPhysicalHeight() <= 0) return 0;
        int chosen = 0;
        float bestDistance = Float.POSITIVE_INFINITY;
        for (Display.Mode mode : modes) {
            if (mode == null || mode.getModeId() <= 0 || mode.getPhysicalWidth() != current.getPhysicalWidth()
                    || mode.getPhysicalHeight() != current.getPhysicalHeight()) continue;
            float rate = mode.getRefreshRate();
            if (!Float.isFinite(rate) || rate < 119.5f) continue;
            float distance = Math.abs(rate - 120);
            if (distance < bestDistance || (distance == bestDistance && mode.getModeId() == current.getModeId())) {
                chosen = mode.getModeId();
                bestDistance = distance;
            }
        }
        return chosen;
    }

    private void requestHighRefresh() {
        if (surface == null) return;
        Surface target = surface.getHolder().getSurface();
        if (target == null || !target.isValid()) return;
        Display display = surface.getDisplay();
        if (display == null) return;
        int mode = chooseRefreshMode(display.getMode(), display.getSupportedModes());
        WindowManager.LayoutParams params = getWindow().getAttributes();
        if (mode != 0 && params.preferredDisplayModeId != mode) {
            params.preferredDisplayModeId = mode;
            getWindow().setAttributes(params);
        }
        if (Build.VERSION.SDK_INT >= 30 && refreshSurface != target) {
            try {
                target.setFrameRate(120, Surface.FRAME_RATE_COMPATIBILITY_DEFAULT);
                refreshSurface = target;
            } catch (IllegalArgumentException ignored) { /* The surface can disappear during a lifecycle callback. */ }
        }
    }

    /* The game's options page and profile own these values (port_settings.c);
     * they are kept here as the next start's seeds. */
    private static void onPortSetting(int which, float value) {
        GameActivity activity = currentActivity.get();
        if (activity == null || !Float.isFinite(value)) return;
        String key = which == 0 ? "ui_scale" : which == 1 ? "render_scale" : which == 2 ? "camera_sensitivity" : null;
        if (key != null) activity.preferences.edit().putFloat(key, value).apply();
    }

    /* The native exit has saved the profile; the launcher survives in its own process. */
    private static void onGameExit() {
        GameActivity activity = currentActivity.get();
        if (activity != null) {
            Intent next = activity.pendingGameLaunch;
            if (next == null) next = new Intent(activity, Launcher.class)
                    .putExtra("game_exited", true)
                    .putExtra("edition", activity.gameEdition())
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
            activity.startActivity(next);
        }
    }

    private static void onSwitchGame() {
        GameActivity activity = currentActivity.get();
        if (activity != null) activity.runOnUiThread(() -> {
            if (currentActivity.get() == activity) activity.showGameSwitch();
        });
    }

    private void showGameSwitch() {
        if (isFinishing() || isDestroyed() || gameSwitchDialog != null || pendingGameLaunch != null) return;
        releaseAll();
        java.util.List<String> installed = Launcher.readyGames(this);
        String[] titles = new String[installed.size()];
        for (int i = 0; i < titles.length; ++i) titles[i] = Games.title(installed.get(i))
                + (installed.get(i).equals(gameEdition()) ? text(T_CURRENT_GAME) : "");
        gameSwitchDialog = new android.app.AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
                .setTitle(text(T_SWITCH_GAME))
                .setItems(titles, (dialog, which) -> switchToGame(installed.get(which)))
                .setNeutralButton(text(T_OPEN_LAUNCHER), (dialog, which) -> switchToGame(null))
                .setNegativeButton(text(T_CANCEL), null)
                .create();
        gameSwitchDialog.setOnDismissListener(dialog -> {
            gameSwitchDialog = null;
            hideSystemUi();
            touch.requestFocus();
        });
        gameSwitchDialog.show();
    }

    private void switchToGame(String edition) {
        if (pendingGameLaunch != null || gameEdition().equals(edition)) return;
        Intent target;
        if (edition == null) {
            target = new Intent(this, Launcher.class).putExtra("game_exited", true)
                    .putExtra("show_launcher", true).putExtra("edition", gameEdition())
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        } else {
            File folder = Launcher.chosenGame(this, null, edition);
            if (folder == null || !Assets.runtimeAvailable(this, Launcher.baseDir(), edition)) return;
            // Launcher owns its preferences in another process; let it record and start the selection.
            target = new Intent(this, Launcher.class).putExtra("game_exited", true)
                    .putExtra("edition", edition).putExtra("launch_edition", edition)
                    .putExtra(Launcher.EXTRA_GAME, folder.getAbsolutePath())
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        }
        // The engine saves its profile and closes before onGameExit starts this target.
        pendingGameLaunch = target;
        nativeRequestGameSwitch();
    }

    /** "Back" is the game's own Escape: its menu and its dialogs' cancel. */
    @Override public void onBackPressed() {
        if (!nativeReady) { super.onBackPressed(); return; }
        releaseAll();
        pulseKey(ESC);
    }

    @Override public void surfaceCreated(SurfaceHolder holder) {
        refreshSurface = null;
        requestHighRefresh();
        surfaceHidden = false;
        nativeSurface(holder.getSurface());
    }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) { requestHighRefresh(); }
    @Override public void surfaceDestroyed(SurfaceHolder holder) {
        refreshSurface = null;
        releaseAll();
        if (!surfaceHidden) nativeSurface(null);
        surfaceHidden = false;
    }

    /* DXVK modes: the surface outlives onStop (SURFACE_LIFECYCLE_FOLLOWS_ATTACHMENT), so the game
       is told it is gone, waits in its present as without a surface, and gets the same window back. */
    @Override protected void onStop() {
        if (nativeReady && surface != null && dxvkSurface() && !surfaceHidden) {
            surfaceHidden = true;
            releaseAll();
            nativeSurface(null);
        }
        super.onStop();
    }

    @Override protected void onStart() {
        super.onStart();
        if (surfaceHidden && surface != null && surface.getHolder().getSurface().isValid()) {
            surfaceHidden = false;
            nativeSurface(surface.getHolder().getSurface());
        }
    }

    @Override protected void onPause() {
        resumed = false;
        releaseAll();
        if (nativeReady) nativePause(true);
        if (lanLock != null && lanLock.isHeld()) lanLock.release();
        super.onPause();
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        if (nativeReady) nativePause(false);
        requestHighRefresh();
        if (lanLock != null && !lanLock.isHeld()) lanLock.acquire();
    }

    @Override protected void onDestroy() {
        releaseAll();
        if (hardware != null) ((InputManager)getSystemService(Context.INPUT_SERVICE)).unregisterInputDeviceListener(hardware);
        if (gamepadHelp != null) gamepadHelp.dismiss();
        if (gameSwitchDialog != null) gameSwitchDialog.dismiss();
        if (rendererDialog != null) rendererDialog.dismiss();
        handler.removeCallbacksAndMessages(null);
        if (gestureProbe != null) unregisterReceiver(gestureProbe);
        if (lanLock != null && lanLock.isHeld()) lanLock.release();
        if (currentActivity.get() == this) currentActivity.clear();
        super.onDestroy();
    }

    /* ------------------------------------------------------------ loading */

    private void createLoading() {
        FrameLayout box = new FrameLayout(this);
        box.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                new int[] {Color.rgb(20, 34, 48), Color.rgb(10, 16, 24), Color.rgb(2, 3, 5)}));
        box.setClickable(true);
        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setGravity(Gravity.CENTER_HORIZONTAL);
        TextView title = new TextView(this);
        title.setText(Games.title(gameEdition()));
        title.setTextColor(Color.rgb(235, 203, 127));
        title.setTextSize(34);
        title.setTypeface(Typeface.create(Typeface.SERIF, Typeface.BOLD));
        title.setGravity(Gravity.CENTER);
        title.setPadding(0, 0, 0, dp(36));
        column.addView(title, new LinearLayout.LayoutParams(-1, -2));
        loadingBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        loadingBar.setMax(1000);
        loadingBar.setProgressTintList(ColorStateList.valueOf(Color.rgb(235, 203, 127)));
        loadingBar.setProgressBackgroundTintList(ColorStateList.valueOf(Color.rgb(60, 60, 70)));
        column.addView(loadingBar, new LinearLayout.LayoutParams(-1, dp(14)));
        loadingText = new TextView(this);
        loadingText.setTextColor(Color.rgb(190, 190, 200));
        loadingText.setTextSize(15);
        loadingText.setGravity(Gravity.CENTER);
        loadingText.setPadding(0, dp(12), 0, 0);
        column.addView(loadingText);
        box.addView(column, new FrameLayout.LayoutParams(Math.min(dp(600),
                getResources().getDisplayMetrics().widthPixels - dp(48)), -2, Gravity.CENTER));
        loading = box;
        game.addView(loading, new FrameLayout.LayoutParams(-1, -1));
    }

    /* The work of a start is calibrated by the previous one (files the game
     * opened until its first screen): the bar is a fraction of that. */
    private void startLoading() {
        loadingStart = System.currentTimeMillis();
        loadingExpected = Math.max(200, preferences.getInt("startup_work", 2600));
        handler.post(loadingTick);
    }

    private final Runnable loadingTick = new Runnable() {
        @Override public void run() {
            if (loading == null) return;
            boolean ready = nativeLoadReady();
            int work = nativeLoadWork();
            float target = ready ? 1f : Math.min(0.97f, work / (float) loadingExpected);
            /* Ease toward the target; time alone keeps the bar alive between bursts. */
            float elapsed = (System.currentTimeMillis() - loadingStart) / 1000f;
            target = Math.max(target, Math.min(0.3f, elapsed / 60f));
            loadingShown += (target - loadingShown) * (ready ? 1f : 0.35f);
            loadingBar.setProgress(Math.round(loadingShown * 1000));
            loadingText.setText(String.format(Locale.getDefault(), "%s  %d%%", text(T_LOADING), Math.round(loadingShown * 100)));
            if (ready) {
                try { Launcher.markStarted(GameActivity.this, gameEdition()); }
                catch (java.io.IOException e) { android.util.Log.w("HeroesV", "startup marker: " + e); }
                reportRenderer();
                if (work > 50) preferences.edit().putInt("startup_work", work).apply();
                View done = loading;
                loading = null;
                done.animate().alpha(0f).setDuration(350).setListener(new AnimatorListenerAdapter() {
                    @Override public void onAnimationEnd(Animator animation) { game.removeView(done); }
                });
                return;
            }
            handler.postDelayed(this, 100);
        }
    };

    /** The first screen is up, so Direct3D exists: a DXVK mode that fell back to OpenGL ES is told
     *  once here and in the launcher (homm5.log has the reason). */
    private void reportRenderer() {
        if (rendererReported || !"toe".equals(gameEdition()) || RendererPolicy.GLES.equals(renderer)) return;
        rendererReported = true;
        if (nativeRendererActive() != RendererPolicy.GLES_NATIVE) { Renderers.clearFallback(this); return; }
        Renderers.fellBack(this, renderer);
        android.widget.Toast.makeText(this, String.format(Renderers.ru()
            ? "%s не запустился, игра идёт на OpenGL ES" : "%s did not start; the game runs on OpenGL ES",
            RendererPolicy.title(renderer)), android.widget.Toast.LENGTH_LONG).show();
    }

    private static final int T_LOADING = 0, T_SWITCH_GAME = 1, T_OPEN_LAUNCHER = 2, T_CANCEL = 3, T_CURRENT_GAME = 4;
    private static String text(int id) {
        String lang = Locale.getDefault().getLanguage();
        boolean ru = "ru".equals(lang) || "uk".equals(lang) || "be".equals(lang);
        switch (id) {
        case T_LOADING: return ru ? "Загрузка" : "Loading";
        case T_SWITCH_GAME: return ru ? "Сменить игру" : "Switch game";
        case T_OPEN_LAUNCHER: return ru ? "Открыть лаунчер" : "Open launcher";
        case T_CANCEL: return ru ? "Отмена" : "Cancel";
        case T_CURRENT_GAME: return ru ? " (текущая)" : " (current)";
        default: return "";
        }
    }

    /* --------------------------------------------------------------- text */

    private static void onTextFocus(boolean enabled, int generation) {
        GameActivity activity = currentActivity.get();
        if (activity != null) activity.runOnUiThread(() -> {
            if (currentActivity.get() == activity) activity.setTextFocus(enabled, generation);
        });
    }

    private static void onTextState(int generation, String text, int caret) {
        GameActivity activity = currentActivity.get();
        if (activity != null) activity.runOnUiThread(() -> {
            if (currentActivity.get() == activity) activity.setTextState(generation, text, caret);
        });
    }

    private void setTextState(int generation, String text, int caret) {
        if (!textEditing || generation != textGeneration) return;
        fieldText = text == null ? "" : text;
        fieldCaret = Math.max(0, Math.min(fieldText.length(), caret));
        updateTextPreview();
    }

    private String visibleText() {
        String composing = textConnection != null && textConnection.valid() ? textConnection.composing : "";
        return fieldText.substring(0, fieldCaret) + composing + "│" + fieldText.substring(fieldCaret);
    }

    private void createTextPreview() {
        textPreview = new LinearLayout(this);
        textPreview.setOrientation(LinearLayout.VERTICAL);
        textPreview.setPadding(dp(16), dp(10), dp(16), dp(12));
        GradientDrawable background = new GradientDrawable();
        background.setColor(0xF0202125);
        background.setCornerRadius(dp(12));
        textPreview.setBackground(background);
        textPreview.setElevation(dp(12));
        textPreview.setClickable(true);
        TextView caption = new TextView(this);
        caption.setText("Ввод текста");
        caption.setTextSize(12);
        caption.setTextColor(0xFFBDC1C6);
        textPreview.addView(caption);
        textPreviewValue = new TextView(this);
        textPreviewValue.setTextSize(18);
        textPreviewValue.setTextColor(Color.WHITE);
        textPreviewValue.setSingleLine(true);
        textPreviewScroll = new HorizontalScrollView(this);
        textPreviewScroll.setHorizontalScrollBarEnabled(false);
        /* Wrap content: a match-parent TextView keeps its first measured width
           when its text changes, which clipped the field after its first letter. */
        textPreviewScroll.addView(textPreviewValue, new FrameLayout.LayoutParams(-2, -2));
        textPreview.addView(textPreviewScroll, new LinearLayout.LayoutParams(-1, -2));
        FrameLayout.LayoutParams layout = new FrameLayout.LayoutParams(-1, -2, Gravity.BOTTOM);
        layout.setMargins(dp(20), 0, dp(20), dp(12));
        game.addView(textPreview, layout);
        textPreview.setVisibility(View.GONE);
        game.getViewTreeObserver().addOnGlobalLayoutListener(this::positionTextPreview);
        game.setOnApplyWindowInsetsListener((view, insets) -> {
            view.post(this::positionTextPreview);
            return insets;
        });
    }

    private void positionTextPreview() {
        if (!textEditing || textPreview == null) return;
        int keyboard = 0;
        WindowInsets insets = game.getRootWindowInsets();
        if (Build.VERSION.SDK_INT >= 30 && insets != null) {
            keyboard = insets.getInsets(WindowInsets.Type.ime()).bottom;
        } else {
            Rect visible = new Rect();
            game.getWindowVisibleDisplayFrame(visible);
            int[] location = new int[2];
            game.getLocationOnScreen(location);
            int covered = location[1] + game.getHeight() - visible.bottom;
            if (covered > game.getHeight() / 5) keyboard = covered;
        }
        FrameLayout.LayoutParams layout = (FrameLayout.LayoutParams)textPreview.getLayoutParams();
        int bottom = Math.min(keyboard, Math.max(0, game.getHeight() - textPreview.getHeight())) + dp(12);
        if (layout.bottomMargin != bottom) { layout.bottomMargin = bottom; textPreview.setLayoutParams(layout); }
        /* The preview stands in for the field the keyboard covers: without a
           keyboard on screen the game's own field is visible. */
        int visibility = keyboard > 0 ? View.VISIBLE : View.GONE;
        if (textPreview.getVisibility() != visibility) textPreview.setVisibility(visibility);
    }

    private void updateTextPreview() {
        if (textPreview == null) return;
        if (!textEditing) { textPreview.setVisibility(View.GONE); return; }
        textPreviewValue.setText(visibleText());
        textPreviewValue.requestLayout();
        int composing = textConnection != null && textConnection.valid() ? textConnection.composing.length() : 0;
        InputMethodManager input = (InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
        if (input != null) input.updateSelection(touch, fieldCaret + composing, fieldCaret + composing,
                composing == 0 ? -1 : fieldCaret, composing == 0 ? -1 : fieldCaret + composing);
        positionTextPreview();
        textPreviewScroll.post(() -> {
            if (!textEditing || textPreviewValue.getLayout() == null) return;
            int currentComposition = textConnection != null && textConnection.valid() ? textConnection.composing.length() : 0;
            int caret = Math.min(fieldCaret + currentComposition, textPreviewValue.length());
            int x = (int)textPreviewValue.getLayout().getPrimaryHorizontal(caret);
            textPreviewScroll.scrollTo(Math.max(0, x - textPreviewScroll.getWidth() / 2), 0);
        });
    }

    private void hideTextInput() {
        textEditing = false;
        if (textConnection != null) textConnection.composing = "";
        fieldText = "";
        fieldCaret = 0;
        updateTextPreview();
        InputMethodManager input = (InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
        if (input != null) input.hideSoftInputFromWindow(touch.getWindowToken(), 0);
    }

    private void setTextFocus(boolean enabled, int generation) {
        if (Integer.compareUnsigned(generation, textGeneration) < 0) return;
        if (enabled && (!hasWindowFocus() || isFinishing() || isDestroyed())) {
            textGeneration = nativeTextCancel();
            hideTextInput();
            return;
        }
        if (generation != textGeneration) { fieldText = ""; fieldCaret = 0; }
        textGeneration = generation;
        if (textConnection != null) textConnection.composing = "";
        textEditing = enabled;
        if (!enabled) { hideTextInput(); return; }
        updateTextPreview();
        touch.requestFocus();
        InputMethodManager input = (InputMethodManager)getSystemService(INPUT_METHOD_SERVICE);
        if (input != null) {
            input.restartInput(touch);
            input.showSoftInput(touch, InputMethodManager.SHOW_IMPLICIT);
        }
    }

    private void releaseAll() {
        if (touch == null) return;
        if (hardware != null) hardware.release();
        touch.cancelGesture();
        hideTextInput();
        textGeneration = nativeTextCancel();
        for (Map.Entry<Integer, Runnable> entry : keyReleases.entrySet()) {
            touch.removeCallbacks(entry.getValue());
            nativeKey(entry.getKey(), false);
        }
        keyReleases.clear();
    }

    @Override public boolean dispatchKeyEvent(KeyEvent event) {
        return hasWindowFocus() && hardware != null && hardware.key(event) || super.dispatchKeyEvent(event);
    }

    @Override public boolean dispatchGenericMotionEvent(MotionEvent event) {
        return hasWindowFocus() && hardware != null && hardware.motion(event) || super.dispatchGenericMotionEvent(event);
    }

    @Override public boolean dispatchTouchEvent(MotionEvent event) {
        return hasWindowFocus() && hardware != null && hardware.mouse(event) || super.dispatchTouchEvent(event);
    }

    private static void onGamepadHelp() {
        GameActivity activity = currentActivity.get();
        if (activity != null) activity.runOnUiThread(activity::showGamepadHelp);
    }

    private void showGamepadHelp() {
        if (isFinishing() || isDestroyed() || gamepadHelp != null) return;
        releaseAll();
        gamepadHelp = new android.app.AlertDialog.Builder(this)
            .setTitle("Управление")
            .setMessage("Сенсорное управление\n\n"
                + "Касание — выбор или действие; удержание — описание. В бою отпустите палец, чтобы отдать приказ. "
                + "Пока палец наводит, коснитесь экрана вторым пальцем и держите его — откроется карточка "
                + "существа под первым пальцем. Поднимите второй палец, чтобы закрыть её и продолжить наведение; "
                + "если первым поднять наводящий палец, приказа не будет. Быстрое касание двумя пальцами "
                + "отменяет приказ. При расстановке войск отряды перетаскиваются между полем и ячейками запаса.\n"
                + ("toe".equals(gameEdition())
                    ? "Портрет на шкале инициативы выделяется касанием; второе касание этого портрета открывает карточку "
                        + "существа, каждое следующее переключает описание и эффекты, касание в другом месте закрывает её.\n"
                        + "Двойное касание мини-карты (или касание её двумя пальцами) включает и выключает подсветку объектов.\n"
                        + "Книга заклинаний: свайп влево или вправо листает страницы, вверх или вниз — закладки; касание "
                        + "рядом с закладкой выбирает её.\n"
                    : "")
                + "Два пальца — перемещение, масштаб и поворот камеры; два пальца рядом вверх-вниз — наклон. "
                + "Одновременное короткое касание поля тремя пальцами — исходные наклон и поворот; в бою также положение камеры.\n\n"
                + "Разделение армий\n\n"
                + "Удерживайте отряд и, не отпуская его, коснитесь другим пальцем ячейки армии: "
                + "один воин перейдёт в первую свободную ячейку. Удержание второго пальца над другой ячейкой "
                + "открывает окно выбора количества; если там такой же отряд, оба делятся поровну.\n"
                + "Удерживайте отряд, перетащите на портрет его героя и отпустите — отряды этого типа "
                + "равномерно займут свободные ячейки; уже отделённые одиночки сохранятся. "
                + "Быстрое перетаскивание отряда на портрет собирает этот тип вместе. "
                + "Перетаскивание на портрет другого героя передаёт ему отряд.\n\n"
                + "Смещение курсора от пальца и его отображение: Настройки → Дополнительные → Управление.\n\n"
                + "Геймпад\n\nЛевый стик — курсор; LB / L1 — точное перемещение.\n\n"
                + "A / крест — левый клик. Удерживайте для перетаскивания; два нажатия — двойной клик.\n"
                + "B / круг — правый клик: описание, отмена действия.\n"
                + "Правый стик — поворот и наклон камеры; в бою вверх-вниз — сдвиг камеры.\n"
                + "Крестовина — перемещение камеры. LT / L2 и RT / R2 — колесо мыши: масштаб или прокрутка.\n\n"
                + "X / квадрат — книга заклинаний (C). Y / треугольник — ожидание в бою (W).\n"
                + "RB / R1 — Shift: с A разделить отряд; с X — Enter / защита; с Y — конец хода (E).\n"
                + "Нажать левый стик — следующий герой (Tab). Нажать правый — исходная камера (Home).\n"
                + "Start / Options — меню или закрыть окно (Esc). Select / View / Share — эта справка.\n\n"
                + "Все кнопки интерфейса доступны курсором. Для ввода имени выберите поле: откроется клавиатура. "
                + "Курсор скрывается после 30 секунд без перемещения и появляется при движении мыши или левого стика.\n\n"
                + "В справке: крестовина — прокрутка; A или B — закрыть.")
            .setPositiveButton("Закрыть", (dialog, which) -> {})
            .create();
        gamepadHelp.setOnKeyListener((dialog, code, event) -> {
            if (code == KeyEvent.KEYCODE_BUTTON_A || code == KeyEvent.KEYCODE_BUTTON_B
                    || code == KeyEvent.KEYCODE_BUTTON_START || code == KeyEvent.KEYCODE_BUTTON_SELECT) {
                if (event.getAction() == KeyEvent.ACTION_UP) dialog.dismiss();
                return true;
            }
            return false;
        });
        gamepadHelp.setOnDismissListener(dialog -> { gamepadHelp = null; hideSystemUi(); touch.requestFocus(); });
        gamepadHelp.show();
    }

    /** External devices feed the original DirectInput path; fingers keep their own gestures. */
    private final class HardwareInput implements InputManager.InputDeviceListener {
        private final Map<Long, Integer> held = new HashMap<>();
        private final Map<Integer, Pad> pads = new HashMap<>();
        private boolean ticking;
        private long lastTick;

        private final class Pad {
            float x, y, rx, ry, lt, rt, wheel;
            boolean leftTrigger, rightTrigger, precise, shift;
        }

        private Pad pad(int device) {
            Pad p = pads.get(device);
            if (p == null) { p = new Pad(); pads.put(device, p); }
            return p;
        }

        private void output(int value, boolean down) {
            if (value >= 256) nativeMouseButton(value - 256, down);
            else nativeHardwareKey(value, down);
        }

        private void hold(int device, int token, int value, boolean down) {
            long id = ((long)device << 32) | (token & 0xffffffffL);
            if (down) {
                if (held.containsKey(id)) return;
                boolean already = held.containsValue(value);
                held.put(id, value);
                if (!already) output(value, true);
            } else {
                Integer old = held.remove(id);
                if (old != null && !held.containsValue(old)) output(old, false);
            }
        }

        void release() {
            for (int value : new HashSet<>(held.values())) output(value, false);
            held.clear(); pads.clear();
            touch.removeCallbacks(tick);
            ticking = false;
        }

        @Override public void onInputDeviceAdded(int device) {}
        @Override public void onInputDeviceChanged(int device) { onInputDeviceRemoved(device); }
        @Override public void onInputDeviceRemoved(int device) {
            for (long id : new HashSet<>(held.keySet())) if ((int)(id >> 32) == device)
                hold(device, (int)id, 0, false);
            pads.remove(device);
        }

        boolean key(KeyEvent event) {
            int action = event.getAction(), code = event.getKeyCode(), device = event.getDeviceId();
            if (action != KeyEvent.ACTION_DOWN && action != KeyEvent.ACTION_UP) return false;
            boolean down = action == KeyEvent.ACTION_DOWN;
            if (event.isFromSource(InputDevice.SOURCE_MOUSE)
                    && (code == KeyEvent.KEYCODE_BACK || code == KeyEvent.KEYCODE_FORWARD)) return true;
            if (event.isFromSource(InputDevice.SOURCE_GAMEPAD) || event.isFromSource(InputDevice.SOURCE_JOYSTICK)) {
                Pad p = pad(device);
                if (down && event.getRepeatCount() != 0) return true;
                int value;
                switch (code) {
                case KeyEvent.KEYCODE_BUTTON_A: value = 256; break;
                case KeyEvent.KEYCODE_BUTTON_B: value = 257; break;
                case KeyEvent.KEYCODE_BUTTON_X: value = p.shift ? 0x0D : 'C'; break;
                case KeyEvent.KEYCODE_BUTTON_Y: value = p.shift ? 'E' : 'W'; break;
                case KeyEvent.KEYCODE_BUTTON_L1: p.precise = down; return true;
                case KeyEvent.KEYCODE_BUTTON_R1: p.shift = down; value = 0xA0; break;
                case KeyEvent.KEYCODE_BUTTON_L2: p.leftTrigger = down; startTick(); return true;
                case KeyEvent.KEYCODE_BUTTON_R2: p.rightTrigger = down; startTick(); return true;
                case KeyEvent.KEYCODE_BUTTON_THUMBL: value = 0x09; break;
                case KeyEvent.KEYCODE_BUTTON_THUMBR: value = 0x24; break;
                case KeyEvent.KEYCODE_BUTTON_START: case KeyEvent.KEYCODE_BACK: value = 0x1B; break;
                case KeyEvent.KEYCODE_BUTTON_SELECT:
                    if (down) showGamepadHelp();
                    return true;
                default: value = keyboardKey(code); if (value == 0) return false;
                }
                hold(device, code, value, down);
                return true;
            }
            if (!event.isFromSource(InputDevice.SOURCE_KEYBOARD)) return false;
            int value = keyboardKey(code);
            if (!down && held.containsKey(((long)device << 32) | (code & 0xffffffffL))) {
                hold(device, code, value, false);
                return true;
            }
            if (value == 0) return false;
            // An active Android editor already has a validated native text destination.
            if (textEditing && textConnection != null && (event.getUnicodeChar() >= 32
                    || code == KeyEvent.KEYCODE_DEL || code == KeyEvent.KEYCODE_FORWARD_DEL
                    || code == KeyEvent.KEYCODE_ENTER) && !event.isCtrlPressed() && !event.isAltPressed())
                return textConnection.sendKeyEvent(event);
            hold(device, code, value, down);
            return true;
        }

        private float axis(MotionEvent event, int axis, boolean centered) {
            InputDevice device = event.getDevice();
            InputDevice.MotionRange range = device == null ? null : device.getMotionRange(axis, event.getSource());
            float value = event.getAxisValue(axis);
            if (!Float.isFinite(value)) return 0;
            float flat = centered ? Math.max(.16f, range == null ? 0 : range.getFlat()) : .05f;
            flat = Math.min(.95f, flat);
            if (Math.abs(value) <= flat) return 0;
            return Math.copySign(Math.min(1, (Math.abs(value) - flat) / (1 - flat)), value);
        }

        boolean motion(MotionEvent event) {
            if (mouse(event)) return true;
            if (!event.isFromSource(InputDevice.SOURCE_JOYSTICK) || event.getActionMasked() != MotionEvent.ACTION_MOVE)
                return false;
            int device = event.getDeviceId();
            Pad p = pad(device);
            p.x = axis(event, MotionEvent.AXIS_X, true); p.y = axis(event, MotionEvent.AXIS_Y, true);
            p.rx = axis(event, MotionEvent.AXIS_Z, true); p.ry = axis(event, MotionEvent.AXIS_RZ, true);
            InputDevice source = event.getDevice();
            if (source != null && source.getMotionRange(MotionEvent.AXIS_Z, event.getSource()) == null) {
                p.rx = axis(event, MotionEvent.AXIS_RX, true); p.ry = axis(event, MotionEvent.AXIS_RY, true);
            }
            p.lt = Math.max(axis(event, MotionEvent.AXIS_LTRIGGER, false), axis(event, MotionEvent.AXIS_BRAKE, false));
            p.rt = Math.max(axis(event, MotionEvent.AXIS_RTRIGGER, false), axis(event, MotionEvent.AXIS_GAS, false));
            float hx = event.getAxisValue(MotionEvent.AXIS_HAT_X), hy = event.getAxisValue(MotionEvent.AXIS_HAT_Y);
            hold(device, 1001, 0x25, hx < -.5f); hold(device, 1002, 0x27, hx > .5f);
            hold(device, 1003, 0x26, hy < -.5f); hold(device, 1004, 0x28, hy > .5f);
            startTick();
            return true;
        }

        boolean mouse(MotionEvent event) {
            if (!event.isFromSource(InputDevice.SOURCE_MOUSE) && !event.isFromSource(InputDevice.SOURCE_MOUSE_RELATIVE))
                return false;
            int action = event.getActionMasked();
            if (touch.getWidth() <= 0 || touch.getHeight() <= 0) return true;
            if (action == MotionEvent.ACTION_CANCEL) { onInputDeviceRemoved(event.getDeviceId()); return true; }
            if (action == MotionEvent.ACTION_HOVER_EXIT) return true;
            boolean relative = event.isFromSource(InputDevice.SOURCE_MOUSE_RELATIVE);
            if (action == MotionEvent.ACTION_MOVE || action == MotionEvent.ACTION_HOVER_MOVE
                    || action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_UP
                    || action == MotionEvent.ACTION_BUTTON_PRESS || action == MotionEvent.ACTION_BUTTON_RELEASE)
                nativePointer(event.getX() / touch.getWidth(), event.getY() / touch.getHeight(), relative);
            int buttons = event.getButtonState();
            for (int i = 0; i < 5; ++i)
                hold(event.getDeviceId(), 2000 + i, 256 + i, (buttons & (1 << i)) != 0);
            if (action == MotionEvent.ACTION_SCROLL) {
                float scroll = event.getAxisValue(MotionEvent.AXIS_VSCROLL);
                if (Float.isFinite(scroll)) nativeWheel(Math.round(Math.max(-100, Math.min(100, scroll)) * 120));
            }
            return true;
        }

        private void startTick() {
            if (!ticking) {
                ticking = true; lastTick = SystemClock.uptimeMillis();
                touch.postOnAnimation(tick);
            }
        }

        private final Runnable tick = new Runnable() {
            @Override public void run() {
                ticking = false;
                if (!hasWindowFocus()) { release(); return; }
                long now = SystemClock.uptimeMillis();
                float dt = Math.min(.05f, Math.max(0, (now - lastTick) / 1000f)); lastTick = now;
                boolean active = false;
                for (Pad p : pads.values()) {
                    if (p.x != 0 || p.y != 0) {
                        float length = Math.max(1, (float)Math.hypot(p.x, p.y));
                        float speed = .8f * dt * (p.precise ? .22f : 1);
                        float aspect = touch.getWidth() / (float)Math.max(1, touch.getHeight());
                        nativePointer(p.x * Math.abs(p.x) / length * speed,
                                p.y * Math.abs(p.y) / length * speed * aspect, true);
                        active = true;
                    }
                    if (p.rx != 0 || p.ry != 0) {
                        nativePadCamera(-p.rx * dt * 1.6f, -p.ry * dt * .5f);
                        active = true;
                    }
                    float wheel = Math.max(p.rt, p.rightTrigger ? 1 : 0) - Math.max(p.lt, p.leftTrigger ? 1 : 0);
                    if (wheel != 0) {
                        p.wheel += wheel * dt * 7;
                        int steps = (int)p.wheel;
                        if (steps != 0) { nativeWheel(steps * 120); p.wheel -= steps; }
                        active = true;
                    } else p.wheel = 0;
                }
                if (active) { ticking = true; touch.postOnAnimation(this); }
            }
        };
    }

    private static int keyboardKey(int code) {
        if (code >= KeyEvent.KEYCODE_A && code <= KeyEvent.KEYCODE_Z) return 'A' + code - KeyEvent.KEYCODE_A;
        if (code >= KeyEvent.KEYCODE_0 && code <= KeyEvent.KEYCODE_9) return '0' + code - KeyEvent.KEYCODE_0;
        if (code >= KeyEvent.KEYCODE_F1 && code <= KeyEvent.KEYCODE_F12) return 0x70 + code - KeyEvent.KEYCODE_F1;
        if (code >= KeyEvent.KEYCODE_NUMPAD_0 && code <= KeyEvent.KEYCODE_NUMPAD_9) return 0x60 + code - KeyEvent.KEYCODE_NUMPAD_0;
        switch (code) {
        case KeyEvent.KEYCODE_ESCAPE: return 0x1B;
        case KeyEvent.KEYCODE_ENTER: return 0x0D;
        case KeyEvent.KEYCODE_NUMPAD_ENTER: return 0x0C;
        case KeyEvent.KEYCODE_SPACE: return 0x20;
        case KeyEvent.KEYCODE_TAB: return 0x09;
        case KeyEvent.KEYCODE_DEL: return 0x08;
        case KeyEvent.KEYCODE_FORWARD_DEL: return 0x2E;
        case KeyEvent.KEYCODE_SHIFT_LEFT: return 0xA0;
        case KeyEvent.KEYCODE_SHIFT_RIGHT: return 0xA1;
        case KeyEvent.KEYCODE_CTRL_LEFT: return 0xA2;
        case KeyEvent.KEYCODE_CTRL_RIGHT: return 0xA3;
        case KeyEvent.KEYCODE_ALT_LEFT: return 0xA4;
        case KeyEvent.KEYCODE_ALT_RIGHT: return 0xA5;
        case KeyEvent.KEYCODE_DPAD_LEFT: return 0x25;
        case KeyEvent.KEYCODE_DPAD_UP: return 0x26;
        case KeyEvent.KEYCODE_DPAD_RIGHT: return 0x27;
        case KeyEvent.KEYCODE_DPAD_DOWN: return 0x28;
        case KeyEvent.KEYCODE_PAGE_UP: return 0x21;
        case KeyEvent.KEYCODE_PAGE_DOWN: return 0x22;
        case KeyEvent.KEYCODE_MOVE_HOME: return 0x24;
        case KeyEvent.KEYCODE_MOVE_END: return 0x23;
        case KeyEvent.KEYCODE_INSERT: return 0x2D;
        case KeyEvent.KEYCODE_MINUS: return 0xBD;
        case KeyEvent.KEYCODE_EQUALS: case KeyEvent.KEYCODE_PLUS: return 0xBB;
        case KeyEvent.KEYCODE_GRAVE: return 0xC0;
        case KeyEvent.KEYCODE_SEMICOLON: return 0xBA;
        case KeyEvent.KEYCODE_APOSTROPHE: return 0xDE;
        case KeyEvent.KEYCODE_COMMA: return 0xBC;
        case KeyEvent.KEYCODE_PERIOD: return 0xBE;
        case KeyEvent.KEYCODE_SLASH: return 0xBF;
        case KeyEvent.KEYCODE_LEFT_BRACKET: return 0xDB;
        case KeyEvent.KEYCODE_RIGHT_BRACKET: return 0xDD;
        case KeyEvent.KEYCODE_BACKSLASH: return 0xDC;
        case KeyEvent.KEYCODE_CAPS_LOCK: return 0x14;
        case KeyEvent.KEYCODE_NUM_LOCK: return 0x90;
        case KeyEvent.KEYCODE_SCROLL_LOCK: return 0x91;
        case KeyEvent.KEYCODE_SYSRQ: return 0x2C;
        case KeyEvent.KEYCODE_BREAK: return 0x13;
        case KeyEvent.KEYCODE_NUMPAD_MULTIPLY: return 0x6A;
        case KeyEvent.KEYCODE_NUMPAD_ADD: return 0x6B;
        case KeyEvent.KEYCODE_NUMPAD_SUBTRACT: return 0x6D;
        case KeyEvent.KEYCODE_NUMPAD_DOT: return 0x6E;
        case KeyEvent.KEYCODE_NUMPAD_DIVIDE: return 0x6F;
        default: return 0;
        }
    }

    private final class TextConnection extends BaseInputConnection {
        private final int generation;
        private String composing = "";

        TextConnection(int generation) { super(touch, false); this.generation = generation; }
        private boolean valid() { return textEditing && generation == textGeneration; }

        @Override public boolean commitText(CharSequence text, int cursor) {
            composing = "";
            updateTextPreview();
            return valid() && text.length() <= 256 && (text.length() == 0 || nativeText(generation, text.toString()));
        }

        @Override public boolean setComposingText(CharSequence text, int cursor) {
            if (!valid() || text.length() > 256) return false;
            composing = text.toString();
            updateTextPreview();
            return true;
        }

        @Override public boolean finishComposingText() {
            String text = composing;
            composing = "";
            updateTextPreview();
            return valid() && (text.isEmpty() || nativeText(generation, text));
        }

        @Override public boolean deleteSurroundingText(int before, int after) {
            return deleteText(before, after, false);
        }

        @Override public boolean deleteSurroundingTextInCodePoints(int before, int after) {
            return deleteText(before, after, true);
        }

        private boolean deleteText(int before, int after, boolean codePoints) {
            if (!valid() || before < 0 || after < 0 || before > 256 || after > 256) return false;
            int composingDelete = Math.min(before, codePoints ? composing.codePointCount(0, composing.length()) : composing.length());
            int end = codePoints ? composing.offsetByCodePoints(composing.length(), -composingDelete) : composing.length() - composingDelete;
            composing = composing.substring(0, end);
            updateTextPreview();
            before -= composingDelete;
            return (before == 0 || nativeTextKey(generation, 8, before))
                    && (after == 0 || nativeTextKey(generation, 46, after));
        }

        @Override public CharSequence getTextBeforeCursor(int length, int flags) {
            if (!valid() || length < 0) return "";
            String before = fieldText.substring(0, fieldCaret) + composing;
            return before.substring(Math.max(0, before.length() - length));
        }

        @Override public CharSequence getTextAfterCursor(int length, int flags) {
            if (!valid() || length < 0) return "";
            return fieldText.substring(fieldCaret, fieldCaret + Math.min(length, fieldText.length() - fieldCaret));
        }

        @Override public boolean performEditorAction(int action) {
            if (!finishComposingText() || !nativeTextKey(generation, 13, 1)) return false;
            hideTextInput();
            return true;
        }

        @Override public boolean sendKeyEvent(KeyEvent event) {
            if (!valid()) return false;
            if (event.getAction() == KeyEvent.ACTION_UP) return true;
            if (event.getAction() == KeyEvent.ACTION_MULTIPLE) {
                String text = event.getCharacters();
                return text != null && finishComposingText() && commitText(text, 1);
            }
            if (event.getAction() != KeyEvent.ACTION_DOWN) return false;
            if (event.getKeyCode() == KeyEvent.KEYCODE_DEL) return deleteSurroundingText(1, 0);
            if (event.getKeyCode() == KeyEvent.KEYCODE_FORWARD_DEL) return deleteSurroundingText(0, 1);
            if (event.getKeyCode() == KeyEvent.KEYCODE_ENTER) return performEditorAction(EditorInfo.IME_ACTION_DONE);
            int character = event.getUnicodeChar();
            return character >= 32 && Character.isValidCodePoint(character) && finishComposingText()
                    && commitText(new String(Character.toChars(character)), 1);
        }
    }

    /* ------------------------------------------------------------ gestures */

    /**
     * One finger: tap, double tap, drag, hold. A short three-finger chord resets
     * the camera. Two or more moving fingers:
     * a transform of the whole set (centroid, spread, the angle of its first
     * two), re-based whenever a finger joins or leaves so that the camera never
     * jumps, and continued by the remaining fingers until the last one lifts;
     * two fingers moving up or down together (side by side) tilt instead. A
     * second finger added to a held or dragged one keeps the first one's
     * gesture (troop splitting, cancelling an aim; a combat aim shows its
     * card while the second finger rests).
     */
    private final class TouchLayer extends View {
        private static final int BEGIN = 0, TAP = 1, DOUBLE_TAP = 2, PAN = 3, TRANSFORM = 4,
                HOLD_BEGIN = 5, HOLD_DRAG = 6, END = 7, TWO_FINGER_BEGIN = 8,
                TWO_FINGER_CANCEL = 9, ABORT = 10, SECOND_BEGIN = 11, SECOND_TAP = 12, SECOND_HOLD = 13,
                THREE_FINGER_TAP = 14, TILT = 15, SECOND_END = 19, FIRST_END = 20, TWO_FINGER_TAP = 21;
        private static final long HOLD_MS = 450, MULTI_TAP_MS = 300, CHORD_JOIN_MS = 120, CHORD_TAP_MS = 300;
        /* ToE: a finger added this long after the first is a second finger (combat card, troop split)
           rather than the start of a two-finger camera gesture, whose fingers land together. */
        private static final long SECOND_MS = 200;
        private int pointer = -1, secondPointer = -1;
        private boolean open, panning, holding, multi, transformed, tilting;
        private float downX, downY, lastX, lastY, lastTapX, lastTapY;
        private int nextTapCount;
        private long lastTapTime = -1;
        private boolean chordCandidate, chord, pairTap;
        private long chordDownTime;
        private int chordContacts;
        private final int[] chordIds = new int[3];
        private final float[] chordX = new float[3], chordY = new float[3];
        private Runnable hold, secondaryHold;
        /* The multi-finger set: its baseline and the two fingers giving its angle. */
        private float baseX, baseY, baseSpan, baseAngle, lastSpan, lastAngle;
        private float pairDownY1, pairDownY2, pairDownX1, pairDownX2, pairDownSpan, pairDownAngle;
        private int angleA = -1, angleB = -1;
        private float secondaryX, secondaryY, secondaryDownX, secondaryDownY;
        private boolean secondaryCandidate, secondaryHeld;
        /* released: the first finger lifted past the resting second one (FIRST_END), whose own
           lift ends the gesture (SECOND_END). */
        private boolean released;

        TouchLayer(Context context) {
            super(context);
            setFocusable(true);
            setFocusableInTouchMode(true);
            setContentDescription("Игровое поле: касание — выбор или действие, удержание — описание, "
                    + "два пальца — перемещение, масштаб и поворот, два пальца вверх-вниз — наклон, "
                    + "касание двумя пальцами — отмена, одновременное касание тремя пальцами — камера по умолчанию");
        }

        @Override public boolean onCheckIsTextEditor() { return textEditing; }

        @Override public InputConnection onCreateInputConnection(EditorInfo info) {
            if (!textEditing) return null;
            info.inputType = InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS;
            info.imeOptions = EditorInfo.IME_ACTION_DONE | EditorInfo.IME_FLAG_NO_EXTRACT_UI | EditorInfo.IME_FLAG_NO_FULLSCREEN;
            info.initialSelStart = info.initialSelEnd = fieldCaret;
            textConnection = new TextConnection(textGeneration);
            return textConnection;
        }

        private void emit(int kind, float x, float y) { emit(kind, x, y, 0, 0, 1, 0); }

        private void emit(int kind, float x, float y, float dx, float dy, float scale, float rotation) {
            int width = getWidth(), height = getHeight();
            if (width <= 0 || height <= 0) {
                nativeTouch(ABORT, 0, 0, 0, 0, 1, 0);
                return;
            }
            // Native code removes the renderer's aspect fit before asking the engine to pick.
            nativeTouch(kind, x / width, y / height, dx / width, dy / height, scale, rotation);
        }

        private void cancelHold() {
            if (hold != null) { removeCallbacks(hold); hold = null; }
        }

        private void cancelSecondaryHold() {
            if (secondaryHold != null) { removeCallbacks(secondaryHold); secondaryHold = null; }
        }

        private void reset() {
            cancelHold();
            cancelSecondaryHold();
            open = panning = holding = multi = transformed = tilting = released = false;
            pointer = secondPointer = angleA = angleB = -1;
            secondaryCandidate = secondaryHeld = false;
            chordCandidate = chord = pairTap = false;
            chordContacts = 0;
        }

        void cancelGesture() {
            reset();
            // A released finger may still have a click waiting for the native UI's next frame.
            nativeTouch(ABORT, 0, 0, 0, 0, 1, 0);
            lastTapTime = -1;
        }

        private void moveSingle(float x, float y) {
            if (!panning && Math.hypot(x - downX, y - downY) > dp(16)) {
                cancelHold();
                panning = true;
                lastTapTime = -1;
            }
            if (panning && (x != lastX || y != lastY)) {
                emit(holding ? HOLD_DRAG : PAN, x, y, x - lastX, y - lastY, 1, 0);
                lastX = x; lastY = y;
            }
        }

        private float angleDelta(float angle, float previous) {
            float delta = angle - previous;
            if (delta > Math.PI) delta -= (float)(2 * Math.PI);
            else if (delta < -Math.PI) delta += (float)(2 * Math.PI);
            return delta;
        }

        /* Pointers of the set after this event (a lifting finger is gone). */
        private boolean included(MotionEvent event, int i) {
            int action = event.getActionMasked();
            return !((action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_UP) && i == event.getActionIndex());
        }

        /* Centroid, spread and angle of the set; false when fewer than one finger remains. */
        private final float[] shape = new float[4];
        private boolean measure(MotionEvent event) {
            int count = 0;
            float sx = 0, sy = 0;
            for (int i = 0; i < event.getPointerCount(); ++i) {
                if (!included(event, i)) continue;
                sx += event.getX(i); sy += event.getY(i); ++count;
            }
            if (count == 0) return false;
            float cx = sx / count, cy = sy / count, spread = 0;
            for (int i = 0; i < event.getPointerCount(); ++i)
                if (included(event, i)) spread += (float)Math.hypot(event.getX(i) - cx, event.getY(i) - cy);
            spread = count > 1 ? 2 * spread / count : 0;
            int a = angleA >= 0 ? event.findPointerIndex(angleA) : -1, b = angleB >= 0 ? event.findPointerIndex(angleB) : -1;
            float angle = a >= 0 && b >= 0 && included(event, a) && included(event, b)
                    ? (float)Math.atan2(event.getY(b) - event.getY(a), event.getX(b) - event.getX(a)) : lastAngle;
            shape[0] = cx; shape[1] = cy; shape[2] = spread; shape[3] = angle;
            return Float.isFinite(cx) && Float.isFinite(cy) && Float.isFinite(spread) && Float.isFinite(angle);
        }

        /* A finger joined or left: the next deltas start from here. */
        private boolean rebase(MotionEvent event) {
            angleA = angleB = -1;
            for (int i = 0; i < event.getPointerCount(); ++i) {
                if (!included(event, i)) continue;
                if (angleA < 0) angleA = event.getPointerId(i);
                else if (angleB < 0) angleB = event.getPointerId(i);
            }
            if (!measure(event)) return false;
            lastX = shape[0]; lastY = shape[1]; lastSpan = shape[2]; lastAngle = shape[3];
            int a = event.findPointerIndex(angleA), b = event.findPointerIndex(angleB);
            if (a >= 0 && b >= 0) {
                pairDownX1 = event.getX(a); pairDownY1 = event.getY(a);
                pairDownX2 = event.getX(b); pairDownY2 = event.getY(b);
                pairDownSpan = lastSpan; pairDownAngle = lastAngle;
            }
            baseX = lastX; baseY = lastY; baseSpan = lastSpan; baseAngle = lastAngle;
            return true;
        }

        private void beginMulti(MotionEvent event) {
            cancelHold();
            cancelSecondaryHold();
            secondaryCandidate = secondaryHeld = false;
            multi = true;
            panning = holding = transformed = tilting = false;
            lastTapTime = -1;
            if (!rebase(event)) { cancelGesture(); return; }
            downX = lastX; downY = lastY;
            emit(TWO_FINGER_BEGIN, lastX, lastY);
        }

        /* Two fingers side by side that moved up or down together: a tilt. Fingers
           never move in lockstep, so each one only has to share the direction and
           have covered a good part of the pair's travel. */
        private boolean shove(MotionEvent event) {
            int a = event.findPointerIndex(angleA), b = event.findPointerIndex(angleB);
            if (a < 0 || b < 0) return false;
            float dy1 = event.getY(a) - pairDownY1, dy2 = event.getY(b) - pairDownY2;
            float dx1 = event.getX(a) - pairDownX1, dx2 = event.getX(b) - pairDownX2;
            float travel = Math.abs(dy1 + dy2) * 0.5f;
            float slope = Math.abs(pairDownY2 - pairDownY1), across = Math.abs(pairDownX2 - pairDownX1);
            return dy1 * dy2 > 0 && Math.abs(dy1) > travel * 0.35f && Math.abs(dy2) > travel * 0.35f
                    && Math.abs(dx1 + dx2) * 0.5f < travel * 0.6f
                    && Math.abs(dx1) < Math.max(Math.abs(dy1), travel) && Math.abs(dx2) < Math.max(Math.abs(dy2), travel)
                    && slope < across && Math.abs(shape[2] - pairDownSpan) < travel * 0.35f + dp(4);
        }

        private void moveMulti(MotionEvent event) {
            if (!measure(event)) { cancelGesture(); return; }
            float x = shape[0], y = shape[1], span = shape[2], angle = shape[3];
            int fingers = 0;
            for (int i = 0; i < event.getPointerCount(); ++i) if (included(event, i)) ++fingers;
            if (!transformed && !tilting && fingers >= 2) {
                /* Fingers never start in step, so the gesture is told only once the set
                   has clearly moved, from the whole motion so far, and then all of it
                   applies: a tilt is a shared vertical move that is not mostly a pinch
                   or a turn. */
                float moved = (float)Math.hypot(x - baseX, y - baseY);
                float spread = Math.abs(span - baseSpan);
                float arc = Math.abs(angleDelta(angle, baseAngle)) * Math.min(baseSpan, span) * 0.5f;
                if (moved > dp(12) || spread > dp(12) || arc > dp(12)) {
                    tilting = moved > dp(12) && shove(event) && spread < moved * 0.5f && arc < moved;
                    transformed = !tilting;
                    lastX = baseX; lastY = baseY; lastSpan = baseSpan; lastAngle = baseAngle;
                }
            } else if (!transformed && !tilting && Math.hypot(x - baseX, y - baseY) > dp(8)) {
                transformed = true;
            }
            if (tilting) {
                if (y != lastY) emit(TILT, x, y, 0, y - lastY, 1, 0);
            } else if (transformed) {
                float scale = fingers >= 2 && lastSpan > dp(1) && span > dp(1) ? span / lastSpan : 1;
                float rotation = fingers >= 2 && lastSpan > dp(1) && span > dp(1) ? angleDelta(angle, lastAngle) : 0;
                if (x != lastX || y != lastY || span != lastSpan || rotation != 0)
                    emit(TRANSFORM, x, y, x - lastX, y - lastY, scale, rotation);
            }
            lastX = x; lastY = y; lastSpan = span; lastAngle = angle;
        }

        private void moveSecondary(MotionEvent event) {
            int first = event.findPointerIndex(pointer), second = event.findPointerIndex(secondPointer);
            if (first < 0 || second < 0) { cancelGesture(); return; }
            secondaryX = event.getX(second); secondaryY = event.getY(second);
            if (!Float.isFinite(secondaryX) || !Float.isFinite(secondaryY)) { cancelGesture(); return; }
            moveSingle(event.getX(first), event.getY(first));
            if (Math.hypot(secondaryX - secondaryDownX, secondaryY - secondaryDownY) > dp(8)) {
                beginMulti(event);
                moveMulti(event);
            }
        }

        /* Once three contacts form a chord, consume the whole contact set even
           if it moves or times out: releasing it must never issue an order. */
        private boolean chordEvent(MotionEvent event) {
            if (!chordCandidate && !chord) return false;
            int action = event.getActionMasked(), index = event.getActionIndex();
            long elapsed = event.getEventTime() - chordDownTime;
            if (elapsed < 0 || elapsed > CHORD_TAP_MS) chordCandidate = false;
            for (int n = 0; n < chordContacts; ++n) {
                int i = event.findPointerIndex(chordIds[n]);
                if (i >= 0 && (!Float.isFinite(event.getX(i)) || !Float.isFinite(event.getY(i))
                        || Math.hypot(event.getX(i) - chordX[n], event.getY(i) - chordY[n]) > dp(16)))
                    chordCandidate = false;
            }
            if (action == MotionEvent.ACTION_POINTER_DOWN && chordCandidate) {
                if (chord || chordContacts >= 3 || event.getPointerCount() > 3 || elapsed > CHORD_JOIN_MS
                        || holding || panning || transformed || tilting
                        || !Float.isFinite(event.getX(index)) || !Float.isFinite(event.getY(index))) chordCandidate = false;
                else {
                    chordIds[chordContacts] = event.getPointerId(index);
                    chordX[chordContacts] = event.getX(index); chordY[chordContacts] = event.getY(index);
                    ++chordContacts;
                    if (chordContacts == 3) {
                        chord = true;
                        cancelHold(); cancelSecondaryHold();
                        lastTapTime = -1;
                    }
                }
            }
            if (chord) {
                if (action == MotionEvent.ACTION_UP) {
                    if (chordCandidate) {
                        float x = (chordX[0] + chordX[1] + chordX[2]) / 3;
                        float y = (chordY[0] + chordY[1] + chordY[2]) / 3;
                        emit(THREE_FINGER_TAP, x, y);
                        emit(END, x, y);
                    } else emit(ABORT, 0, 0);
                    reset();
                }
                return true;
            }
            if (action == MotionEvent.ACTION_POINTER_UP || action == MotionEvent.ACTION_UP) {
                if (chordCandidate && chordContacts == 2 && multi) pairTap = true;
                chordCandidate = false;
            }
            return false;
        }

        @Override public boolean onTouchEvent(MotionEvent event) {
            int action = event.getActionMasked(), index = event.getActionIndex();
            if (action == MotionEvent.ACTION_CANCEL) { cancelGesture(); return true; }
            if (action == MotionEvent.ACTION_DOWN) {
                if (open) cancelGesture();
                if (getWidth() <= 0 || getHeight() <= 0) return true;
                reset();
                pointer = event.getPointerId(index);
                downX = lastX = event.getX(index);
                downY = lastY = event.getY(index);
                long elapsed = event.getEventTime() - lastTapTime;
                boolean follows = lastTapTime >= 0 && elapsed >= 0 && elapsed < MULTI_TAP_MS
                        && Math.hypot(downX - lastTapX, downY - lastTapY) < dp(32);
                nextTapCount = follows ? 2 : 1;
                open = true;
                chordCandidate = true;
                chordDownTime = event.getEventTime();
                chordContacts = 1;
                chordIds[0] = pointer; chordX[0] = downX; chordY[0] = downY;
                emit(BEGIN, downX, downY);
                hold = () -> {
                    hold = null;
                    if (open && !multi && secondPointer < 0 && !panning) {
                        holding = true;
                        lastTapTime = -1;
                        performHapticFeedback(HapticFeedbackConstants.LONG_PRESS);
                        emit(HOLD_BEGIN, downX, downY);
                    }
                };
                postDelayed(hold, HOLD_MS);
            } else if (!open) {
                return true;
            } else if (released) {
                // Only the resting second finger is left; later contacts and moves are ignored.
                if (action == MotionEvent.ACTION_UP || (action == MotionEvent.ACTION_POINTER_UP
                        && event.getPointerId(index) == secondPointer)) {
                    emit(SECOND_END, secondaryX, secondaryY);
                    cancelGesture();
                }
                return true;
            } else if (chordEvent(event)) {
                return true;
            } else if (action == MotionEvent.ACTION_POINTER_DOWN) {
                if (multi) { if (!rebase(event)) cancelGesture(); return true; }
                if (secondPointer >= 0) return true;
                int first = event.findPointerIndex(pointer);
                if (first < 0) { cancelGesture(); return true; }
                cancelHold();
                secondPointer = event.getPointerId(index);
                boolean late = "toe".equals(gameEdition()) && !chordCandidate
                        && event.getEventTime() - event.getDownTime() >= SECOND_MS;
                if (holding || panning || late) {
                    secondaryCandidate = true; secondaryHeld = false;
                    secondaryDownX = secondaryX = event.getX(index);
                    secondaryDownY = secondaryY = event.getY(index);
                    lastTapTime = -1;
                    emit(SECOND_BEGIN, secondaryX, secondaryY);
                    secondaryHold = () -> {
                        secondaryHold = null;
                        if (open && secondaryCandidate) {
                            secondaryHeld = true;
                            emit(SECOND_HOLD, secondaryX, secondaryY);
                        }
                    };
                    postDelayed(secondaryHold, 600);
                } else beginMulti(event);
            } else if (action == MotionEvent.ACTION_MOVE) {
                int first = event.findPointerIndex(pointer);
                if (secondaryCandidate) moveSecondary(event);
                else if (multi) moveMulti(event);
                else if (first >= 0) moveSingle(event.getX(first), event.getY(first));
                else cancelGesture();
            } else if (action == MotionEvent.ACTION_POINTER_UP) {
                int lifted = event.getPointerId(index);
                if (secondaryCandidate) {
                    if (lifted == pointer) {
                        emit(FIRST_END, event.getX(index), event.getY(index));
                        cancelSecondaryHold();
                        released = true;
                        return true;
                    }
                    if (lifted == secondPointer) {
                        moveSecondary(event);
                        if (!open) return true;
                        if (secondaryCandidate) {
                            cancelSecondaryHold();
                            if (!secondaryHeld) emit(SECOND_TAP, event.getX(index), event.getY(index));
                            emit(SECOND_END, event.getX(index), event.getY(index));
                            secondaryCandidate = secondaryHeld = false;
                            secondPointer = -1;
                            return true;
                        }
                    }
                }
                // The remaining fingers carry the transform on from their own baseline.
                if (multi && !rebase(event)) cancelGesture();
            } else if (action == MotionEvent.ACTION_UP) {
                if (secondaryCandidate) { cancelGesture(); return true; }
                cancelHold();
                cancelSecondaryHold();
                if (multi) {
                    if (pairTap && !transformed && !tilting && "toe".equals(gameEdition())
                            && event.getEventTime() - chordDownTime <= CHORD_TAP_MS) emit(TWO_FINGER_TAP, lastX, lastY);
                    else if (!transformed && !tilting) emit(TWO_FINGER_CANCEL, lastX, lastY);
                    emit(END, lastX, lastY);
                } else {
                    float x = event.getX(index), y = event.getY(index);
                    moveSingle(x, y);
                    if (!panning && !holding) {
                        int count = nextTapCount;
                        emit(count == 2 ? DOUBLE_TAP : TAP, x, y);
                        lastTapTime = count == 2 ? -1 : event.getEventTime();
                        lastTapX = x; lastTapY = y;
                        performClick();
                    }
                    emit(END, x, y);
                }
                reset();
            }
            return true;
        }

        @Override public boolean performClick() { super.performClick(); return true; }

        @Override protected void onSizeChanged(int w, int h, int oldw, int oldh) {
            super.onSizeChanged(w, h, oldw, oldh);
            if (w != oldw || h != oldh) cancelGesture();
        }
    }
}
