package org.homm5.port;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.res.ColorStateList;
import android.database.Cursor;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import android.system.Os;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** The game's launcher: where the game's files are — a ZIP archive of the
 *  installation, unpacked into a folder the player chooses in the system's
 *  picker, or a folder that holds them — skipping the opening videos, and the
 *  start. The game runs in GameActivity, which takes the chosen folder. */
public final class Launcher extends Activity {
    static final String EXTRA_GAME = "game", PREFS = "launcher";
    private static final int ASK_ARCHIVE = 1, ASK_TARGET = 2, ASK_FOLDER = 3, ASK_STORAGE = 4;
    private static final String EXTERNAL = "com.android.externalstorage.documents",
        DOWNLOADS = "com.android.providers.downloads.documents";
    private static final int GOLD = Color.rgb(235, 203, 127), GOLD_DARK = Color.rgb(160, 120, 40),
        CELL = Color.rgb(46, 44, 52), GREY = Color.rgb(165, 165, 178), RED = Color.rgb(255, 125, 110);
    /** On the screen: UnpackService tells the end of an unpacking in a notification otherwise. */
    static volatile boolean visible;

    private SharedPreferences prefs;
    private String edition = "toe";
    private File base;   /* /sdcard/HeroesV: saves, profiles, development copies */
    private File game;   /* the chosen game's root; null: none yet */
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Uri archive;
    private File archiveFile;
    private Unpacker.Plan plan;
    private String busy;
    private boolean storageRefused, storageSeen;
    private File cleanupScanning;
    private GameCleanup.Plan cleanupPlan;
    private int cleanupGeneration;

    private TextView gameTitle, gamePath, note, progressTarget, progressText;
    private LinearLayout copies;
    private LinearLayout editionCards;
    private final List<View> editionControls = new ArrayList<>();
    private ProgressBar progress;
    private View progressBox, permissionBox, archiveButton, folderButton, stopButton;
    private TextView cleanupButton;
    private LinearLayout skipBox;
    /* Textures: shown when the GPU cannot sample DXT (Textures.Gpu). */
    private LinearLayout texBox, texFormats, texProgressBox;
    private TextView texStatus, texMemory, texConvert, texDelete, texUndo, texProgressText, texStop;
    private ProgressBar texProgress;
    private Textures.Status texState;
    private Textures.Gpu texGpu;
    private boolean texScanning;
    private int texFormat;
    /* Tribes of the East's renderer (RendererPolicy): the driver check runs in :probe and is polled. */
    private TextView rendererDescription, rendererNote;
    private LinearLayout rendererModes;
    private Spinner rendererSpinner;
    private RendererAdapter rendererAdapter;
    private int rendererShown = -1;
    private boolean rendererAuto;
    private long rendererWaitUntil;

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String requested = getIntent().getStringExtra("edition");
        if (!Games.valid(requested)) requested = prefs.getString("edition", "toe");
        edition = Games.valid(requested) ? requested : "toe";
        android.app.ActivityManager manager = (android.app.ActivityManager) getSystemService(ACTIVITY_SERVICE);
        List<android.app.ActivityManager.RunningAppProcessInfo> processes = manager.getRunningAppProcesses();
        if (getIntent().getStringExtra("launch_edition") == null && !getIntent().getBooleanExtra("game_exited", false)
                && !getIntent().getBooleanExtra("show_launcher", false) && processes != null) {
            for (android.app.ActivityManager.RunningAppProcessInfo process : processes) {
                /* A live process alone is no game on screen: only a task that still holds the game's
                   activity is brought back; otherwise the launcher shows (and can start it anew). */
                if (Games.process(getPackageName(), edition).equals(process.processName) && gameTaskAlive(manager)) {
                    startActivity(new Intent(this, gameClass(edition)));
                    finish();
                    return;
                }
            }
        }
        base = baseDir();
        if (launchRequestedGame()) return;
        if (autoLaunch()) return;
        getWindow().setStatusBarColor(Color.rgb(20, 34, 48));
        getWindow().setNavigationBarColor(Color.rgb(2, 3, 5));
        build();
        if (!storage()) askStorage();
        if (RendererPolicy.ENABLED) {   /* DXVK/Turnip support is commented out (RendererPolicy.ENABLED) */
            Renderers.probe(this);
            rendererWaitUntil = System.currentTimeMillis() + Renderers.PROBE_TIMEOUT_MS + 2000;
        }
        refresh();
        if (RendererPolicy.ENABLED) handler.post(rendererWatcher);
    }

    static File startupMarker(Context context) { return new File(context.getFilesDir(), "game-started"); }
    static File startupMarker(Context context, String edition) { return new File(context.getFilesDir(), Games.marker(edition)); }

    /** The installed build: a start marker of another build (before an update) does not skip the launcher. */
    static String buildStamp(Context context) {
        try {
            android.content.pm.PackageInfo info = context.getPackageManager().getPackageInfo(context.getPackageName(), 0);
            return info.versionCode + ":" + info.lastUpdateTime;
        } catch (android.content.pm.PackageManager.NameNotFoundException e) {
            return "";
        }
    }

    /** GameActivity: this build's start reached the game's first screen. */
    static void markStarted(Context context, String edition) throws java.io.IOException {
        try (java.io.FileOutputStream out = new java.io.FileOutputStream(startupMarker(context, edition))) {
            out.write(buildStamp(context).getBytes(java.nio.charset.StandardCharsets.US_ASCII));
        }
    }

    /** The last start of this edition, with this build, reached its first screen (GameActivity clears
     *  the marker before every start), so the icon may go straight into the game. */
    static boolean startedWithThisBuild(Context context, String edition) {
        File marker = startupMarker(context, edition);
        if (!marker.isFile()) return false;
        try {
            String stamp = new String(java.nio.file.Files.readAllBytes(marker.toPath()), java.nio.charset.StandardCharsets.US_ASCII);
            return !stamp.isEmpty() && stamp.equals(buildStamp(context));
        } catch (java.io.IOException e) {
            return false;
        }
    }

    /** Whether one of this app's tasks still holds the edition's game activity. */
    private boolean gameTaskAlive(android.app.ActivityManager manager) {
        String game = gameClass(edition).getName();
        try {
            for (android.app.ActivityManager.AppTask task : manager.getAppTasks()) {
                android.app.ActivityManager.RecentTaskInfo info = task.getTaskInfo();
                if ((info.baseActivity != null && game.equals(info.baseActivity.getClassName()))
                        || (info.topActivity != null && game.equals(info.topActivity.getClassName()))) return true;
            }
        } catch (RuntimeException e) {
            android.util.Log.w("HeroesV", "launcher: tasks: " + e);
        }
        return false;
    }

    static Class<? extends GameActivity> gameClass(String edition) {
        Games.suffix(edition);
        return "vanilla".equals(edition) ? VanillaGameActivity.class : "hof".equals(edition) ? HofGameActivity.class : GameActivity.class;
    }

    static List<String> readyGames(Context context) {
        List<String> result = new ArrayList<>();
        for (String id : Games.IDS) if (chosenGame(context, null, id) != null
                && Assets.runtimeAvailable(context, baseDir(), id)) result.add(id);
        return result;
    }

    private boolean launchRequestedGame() {
        String requested = getIntent().getStringExtra("launch_edition");
        if (!Games.valid(requested) || !storage() || Unpacker.current != null || Textures.current != null) return false;
        edition = requested;
        String source = getIntent().getStringExtra(EXTRA_GAME);
        if (source == null || !Games.installed(new File(source), edition)) return false;
        game = new File(source);
        if (!Assets.runtimeAvailable(this, base, edition)) return false;
        play();
        return true;
    }

    private boolean autoLaunch() {
        if (getIntent().getStringExtra("launch_edition") != null || getIntent().getBooleanExtra("game_exited", false)
                || getIntent().getBooleanExtra("show_launcher", false)
                || !startedWithThisBuild(this, edition)
                || !storage() || Unpacker.current != null || Textures.current != null) return false;
        game = chosenGame(this, getIntent(), edition);
        if (game == null || !Assets.runtimeAvailable(this, base, edition)) return false;
        play();
        return true;
    }

    @Override protected void onResume() {
        super.onResume();
        if (isFinishing()) return;
        visible = true;
        UnpackService.cancelResult(this);
        TextureService.cancelResult(this);
        if (Unpacker.current != null) {
            handler.removeCallbacks(watcher);
            handler.post(watcher);
        }
        if (Textures.current != null) {
            handler.removeCallbacks(texWatcher);
            handler.post(texWatcher);
        }
        if (prefs != null) refresh();
    }

    @Override protected void onPause() {
        visible = false;
        super.onPause();
    }

    @Override protected void onDestroy() {
        handler.removeCallbacks(watcher);
        handler.removeCallbacks(texWatcher);
        handler.removeCallbacks(rendererWatcher);
        if (!isChangingConfigurations()) dropArchive();
        super.onDestroy();
    }

    /* ------------------------------------------------------------ choosing */

    /** The folder the game runs from: the launcher's (or a tool's) choice,
     *  else, as before the launcher, /sdcard/HeroesV/game or the first copy
     *  there; null if none. */
    static File chosenGame(Context c, Intent intent) {
        return chosenGame(c, intent, "toe");
    }

    static File chosenGame(Context c, Intent intent, String edition) {
        String extra = intent != null ? intent.getStringExtra(EXTRA_GAME) : null;
        if (extra != null && Games.installed(new File(extra), edition)) return new File(extra);
        String saved = c.getSharedPreferences(PREFS, MODE_PRIVATE).getString(Games.pathKey(edition), null);
        if (saved != null && Games.installed(new File(saved), edition)) return new File(saved);
        List<File> found = copies(baseDir(), edition);
        return found.isEmpty() ? null : found.get(0);
    }

    static File baseDir() { return new File(Environment.getExternalStorageDirectory(), "HeroesV"); }

    static boolean skipIntro(Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean("skip_intro", true);
    }

    /** The copies tools/deploy.py puts in /sdcard/HeroesV: game, game-*. */
    static List<File> copies(File base) {
        return copies(base, "toe");
    }

    static List<File> copies(File base, String edition) {
        List<File> out = new ArrayList<>();
        File[] dirs = base.listFiles();
        if (dirs == null) return out;
        Arrays.sort(dirs);
        for (File d : dirs) if (d.isDirectory() && d.getName().startsWith("game") && Games.installed(d, edition)) out.add(d);
        return out;
    }

    static String label(File root) {
        List<String> names = new ArrayList<>();
        for (String id : Games.editions(root)) names.add(Games.title(id));
        return String.join(" / ", names);
    }

    private void select(File root) {
        List<String> found = Games.editions(root);
        if (found.isEmpty()) return;
        SharedPreferences.Editor saved = prefs.edit();
        for (String id : found) saved.putString(Games.pathKey(id), root.getAbsolutePath());
        if (!found.contains(edition)) edition = found.get(0);
        game = root;
        saved.putString("edition", edition).apply();
        note(null, false);
        refresh();
    }

    private void pickArchive() {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        i.putExtra(Intent.EXTRA_MIME_TYPES, new String[] {"application/zip", "application/x-zip-compressed",
            "application/x-zip", "application/octet-stream"});
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        ask(i, ASK_ARCHIVE);
    }

    private void pickFolder(int request, File near) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        Uri initial = near != null ? documentOf(near) : null;
        if (initial != null) i.putExtra(DocumentsContract.EXTRA_INITIAL_URI, initial);
        ask(i, request);
    }

    /** The system's file picker; some firmwares disable it (no Files app). */
    private void ask(Intent picker, int request) {
        try {
            startActivityForResult(picker, request);
        } catch (android.content.ActivityNotFoundException | SecurityException e) {
            android.util.Log.w("HeroesV", "launcher: picker: " + e);
            if (request == ASK_TARGET) dropArchive();
            error(text(E_NO_PICKER));
        }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        Uri uri = result == RESULT_OK && data != null ? data.getData() : null;
        if (uri == null) {
            if (request == ASK_TARGET) dropArchive();
            return;
        }
        if (request == ASK_ARCHIVE) readArchive(uri);
        else if (request == ASK_TARGET) chooseTarget(uri);
        else if (request == ASK_FOLDER) chooseFolder(uri);
    }

    private void readArchive(Uri uri) {
        dropArchive();
        final ParcelFileDescriptor fd;
        try {
            fd = getContentResolver().openFileDescriptor(uri, "r");
            if (fd == null) throw new IOException(uri.toString());
        } catch (Exception e) {
            error(fmt(E_IO, e.getMessage()));
            return;
        }
        final File file = fileOf(uri, fd);
        setBusy(text(T_READING));
        new Thread(() -> {
            Unpacker.Plan p = null;
            String failure = null;
            FileInputStream in = new ParcelFileDescriptor.AutoCloseInputStream(fd);
            try {
                p = Unpacker.plan(new Zip(in.getChannel()));
            } catch (Unpacker.Failure f) {
                failure = describe(f);
            } catch (IOException | RuntimeException | Error e) {
                android.util.Log.w("HeroesV", "launcher: archive " + uri, e);
                failure = fmt(E_IO, String.valueOf(e.getMessage() != null ? e.getMessage() : e));
            }
            if (p == null) close(in);
            final Unpacker.Plan read = p;
            final String error = failure;
            handler.post(() -> {
                setBusy(null);
                if (isFinishing() || isDestroyed()) {
                    if (read != null) close(read.zip);
                    return;
                }
                if (error != null) {
                    error(error);
                    return;
                }
                archive = uri;
                archiveFile = file;
                plan = read;
                askTarget();
            });
        }, "archive").start();
    }

    private String archiveLabel() {
        List<String> titles = new ArrayList<>();
        for (String id : plan.editions) titles.add(Games.title(id));
        return String.join(" / ", titles);
    }

    private void askTarget() {
        dialog().setTitle(text(T_TARGET_TITLE))
            .setMessage(fmt(T_TARGET_BODY, archiveLabel(), plan.files.size(), size(plan.size)))
            .setPositiveButton(text(T_CHOOSE), (d, w) -> pickFolder(ASK_TARGET, archiveFile != null ? archiveFile.getParentFile() : base))
            .setNegativeButton(text(T_CANCEL), (d, w) -> dropArchive())
            .setOnCancelListener(d -> dropArchive())
            .show();
    }

    private void chooseTarget(Uri tree) {
        if (plan == null) {
            error(text(E_NO_ARCHIVE));
            return;
        }
        File chosen = treePath(tree);
        if (chosen == null || !chosen.isDirectory()) {
            error(text(E_NO_PATH));
            dropArchive();
            return;
        }
        File target;
        try {
            target = Unpacker.target(chosen, base);
        } catch (Unpacker.Failure f) {
            error(describe(f));
            dropArchive();
            return;
        }
        long free = chosen.getUsableSpace();
        boolean holdsGame = Unpacker.isGame(chosen);
        StringBuilder body = new StringBuilder(fmt(T_CONFIRM_BODY, archiveLabel(), size(plan.size), target.getPath(), size(free)));
        if (!target.equals(chosen)) body.append("\n\n").append(fmt(T_TAKEN, target.getName()));
        if (holdsGame) body.append("\n\n").append(text(T_HAS_GAME));
        boolean room = free >= plan.size + (64L << 20);
        if (!room) body.append("\n\n").append(fmt(E_SPACE, size(plan.size), size(free)));
        AlertDialog.Builder b = dialog().setTitle(text(T_CONFIRM_TITLE)).setMessage(body)
            .setNegativeButton(text(T_CANCEL), (d, w) -> dropArchive())
            .setOnCancelListener(d -> dropArchive());
        if (room) b.setPositiveButton(text(T_UNPACK), (d, w) -> unpack(target));
        if (holdsGame) b.setNeutralButton(text(T_USE), (d, w) -> { dropArchive(); select(chosen); });
        else b.setNeutralButton(text(T_OTHER), (d, w) -> pickFolder(ASK_TARGET, chosen));
        b.show();
    }

    private void chooseFolder(Uri tree) {
        File dir = treePath(tree);
        if (dir == null || !dir.isDirectory()) {
            error(text(E_NO_PATH));
            return;
        }
        setBusy(text(T_SEARCHING));
        new Thread(() -> {
            List<File> roots = Games.discover(dir);
            handler.post(() -> {
                setBusy(null);
                if (roots.isEmpty()) error(text(E_FOLDER));
                else {
                    for (File root : roots) {
                        SharedPreferences.Editor saved = prefs.edit();
                        for (String id : Games.editions(root)) saved.putString(Games.pathKey(id), root.getAbsolutePath());
                        saved.apply();
                    }
                    File selected = roots.get(0);
                    for (File root : roots) if (Games.installed(root, edition)) { selected = root; break; }
                    select(selected);
                }
            });
        }, "folder").start();
    }

    private void dropArchive() {
        if (plan != null) close(plan.zip);
        plan = null;
        archive = null;
        archiveFile = null;
    }

    /* ----------------------------------------------------------- unpacking */

    private void unpack(File target) {
        if (plan == null || Unpacker.current != null) return;
        Unpacker.Job job = new Unpacker.Job(plan, target, archive.toString(), archiveFile);
        plan = null;   /* the job owns the archive now */
        archive = null;
        archiveFile = null;
        prefs.edit().putString("unpacking", target.getAbsolutePath()).putBoolean("unpackingCreated", job.created).apply();
        Unpacker.current = job;
        new Thread(job, "unpack").start();
        try {
            startForegroundService(new Intent(this, UnpackService.class));
        } catch (RuntimeException e) {
            /* Some firmwares refuse foreground services (battery savers): unpack on screen anyway. */
            android.util.Log.w("HeroesV", "launcher: unpack service: " + e);
        }
        note(null, false);
        handler.post(watcher);
    }

    private final Runnable watcher = new Runnable() {
        @Override public void run() {
            Unpacker.Job job = Unpacker.current;
            showProgress(job);
            if (job == null) return;
            if (!job.finished) handler.postDelayed(this, 250);
            else if (visible) finished(job);
        }
    };

    private void showProgress(Unpacker.Job job) {
        progressBox.setVisibility(job != null && !job.finished ? View.VISIBLE : View.GONE);
        if (job != null) {
            progressTarget.setText(job.target.getPath());
            progress.setProgress((int) (job.done * 1000 / Math.max(1, job.plan.size)));
            progressText.setText(progressText(job.done, job.plan.size) + (job.file.isEmpty() ? "" : " · " + job.file));
            stopButton.setEnabled(!job.cancelled);
        }
        enable();
    }

    private void finished(Unpacker.Job job) {
        Unpacker.current = null;
        prefs.edit().remove("unpacking").remove("unpackingCreated").apply();
        UnpackService.cancelResult(this);
        showProgress(null);
        if (job.failure == null) {
            select(job.target);
            askDelete(job);
        } else if (job.failure.code == Unpacker.CANCELLED) {
            note(text(T_STOPPED), false);
        } else {
            dialog().setTitle(text(T_FAILED_TITLE)).setMessage(describe(job.failure))
                .setPositiveButton(text(T_OK), null).show();
        }
    }

    private void askStop() {
        Unpacker.Job job = Unpacker.current;
        if (job == null || job.finished) return;
        dialog().setMessage(text(T_STOP_ASK))
            .setPositiveButton(text(T_STOP), (d, w) -> job.cancelled = true)
            .setNegativeButton(text(T_CONTINUE), null)
            .show();
    }

    private void askDelete(Unpacker.Job job) {
        Uri uri = Uri.parse(job.source);
        String name = archiveName(uri, job.sourceFile);
        long length = archiveSize(uri, job.sourceFile);
        dialog().setTitle(text(T_UNPACKED_TITLE))
            .setMessage(fmt(T_DELETE_ASK, job.target.getPath(), name, length >= 0 ? size(length) : "?"))
            .setPositiveButton(text(T_DELETE), (d, w) -> {
                boolean deleted = false;
                try {
                    deleted = DocumentsContract.deleteDocument(getContentResolver(), uri);
                } catch (Exception e) {
                    android.util.Log.i("HeroesV", "launcher: the archive's document: " + e);
                }
                if (!deleted && job.sourceFile != null) deleted = job.sourceFile.delete() || !job.sourceFile.exists();
                Toast.makeText(this, text(deleted ? T_DELETED : T_NOT_DELETED), Toast.LENGTH_LONG).show();
            })
            .setNegativeButton(text(T_KEEP), null)
            .show();
    }

    /** An unpacking that ended with the process: its hidden folder goes, and a folder it made. */
    private void cleanStale() {
        String stale = prefs.getString("unpacking", null);
        if (stale == null || Unpacker.current != null) return;
        File target = new File(stale);
        Unpacker.clean(new File(target, Unpacker.TEMP), prefs.getBoolean("unpackingCreated", false) ? target : null);
        prefs.edit().remove("unpacking").remove("unpackingCreated").apply();
        note(text(T_INTERRUPTED), false);
    }

    /* ---------------------------------------------------------------- play */

    private void play() {
        if (game == null || Unpacker.current != null || busy != null
                || (Textures.current != null && !Textures.current.finished)) return;
        if (!Games.installed(game, edition)) {
            error(text(E_FOLDER));
            game = null;
            refresh();
            return;
        }
        if (!Assets.runtimeAvailable(this, base, edition)) {
            error(text(T_RUNTIME_MISSING));
            return;
        }
        prefs.edit().putString(Games.pathKey(edition), game.getAbsolutePath()).putString("edition", edition).apply();
        android.util.Log.i("HeroesV", "launcher: playing " + game + ", opening videos " + (skipIntro(this) ? "skipped" : "shown"));
        startActivity(new Intent(this, gameClass(edition)).putExtra(EXTRA_GAME, game.getAbsolutePath()));
        finish();
    }

    private void setSkipIntro(boolean on) {
        prefs.edit().putBoolean("skip_intro", on).apply();
    }

    /** MMH5.5's New Creature Framework patches for Tribes of the East: off unless chosen here. */
    static boolean newCreatureFramework(Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean("new_creature_framework", false);
    }

    private void setNewCreatureFramework(boolean on) {
        prefs.edit().putBoolean("new_creature_framework", on).apply();
    }

    /** Tailscale/VPN players for Tribes of the East's LAN game (android/host/network.c): addresses or names. */
    static String lanPeers(Context c) {
        return c.getSharedPreferences(PREFS, MODE_PRIVATE).getString("lan_peers", "");
    }

    /* A row like a toggle's: the list (or "none") and a dialog to edit it. */
    private View lanPeersRow() {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(0, dp(6), 0, dp(6));
        String peers = lanPeers(this).trim();
        row.addView(label(text(T_LAN_PEERS), 15, Color.WHITE));
        row.addView(label(peers.isEmpty() ? text(T_LAN_PEERS_NONE) : peers, 13, peers.isEmpty() ? GREY : GOLD));
        row.addView(label(text(T_LAN_PEERS_HINT), 12, GREY));
        row.setOnClickListener(v -> {
            final android.widget.EditText field = new android.widget.EditText(this);
            field.setText(lanPeers(this));
            field.setHint("100.x.y.z, peer.example");
            field.setSingleLine(false);
            field.setMinLines(2);
            field.setInputType(android.text.InputType.TYPE_CLASS_TEXT | android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                    | android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
            dialog().setTitle(text(T_LAN_PEERS)).setMessage(text(T_LAN_PEERS_DIALOG)).setView(field)
                    .setPositiveButton(android.R.string.ok, (d, w) -> {
                        prefs.edit().putString("lan_peers", field.getText().toString().trim()).apply();
                        refresh();
                    })
                    .setNegativeButton(android.R.string.cancel, null).show();
        });
        return row;
    }

    private void refreshCleanup() {
        final File selected = storage() ? game : null;
        if (selected != null && selected.equals(cleanupScanning)) return;
        final int request = ++cleanupGeneration;
        cleanupPlan = null;
        cleanupScanning = selected;
        cleanupButton.setVisibility(View.GONE);
        if (selected == null) return;
        new Thread(() -> {
            GameCleanup.Plan found = null;
            try { found = GameCleanup.scan(selected); }
            catch (IOException | RuntimeException e) { android.util.Log.w("HeroesV", "cleanup preview: " + selected, e); }
            final GameCleanup.Plan result = found;
            handler.post(() -> {
                if (isFinishing() || isDestroyed() || request != cleanupGeneration || !selected.equals(game)) return;
                cleanupScanning = null;
                cleanupPlan = result;
                enable();
            });
        }, "cleanup-preview").start();
    }

    private void scanCleanup() {
        if (game == null || busy != null || Unpacker.current != null) return;
        final File selected = game;
        setBusy(text(T_CLEAN_SCAN));
        new Thread(() -> {
            GameCleanup.Plan found = null;
            String failure = null;
            try { found = GameCleanup.scan(selected); }
            catch (IOException | RuntimeException e) { failure = fmt(E_IO, String.valueOf(e.getMessage())); }
            final GameCleanup.Plan plan = found;
            final String problem = failure;
            handler.post(() -> {
                setBusy(null);
                if (isFinishing() || isDestroyed()) return;
                if (problem != null) { error(problem); return; }
                cleanupPlan = plan;
                enable();
                if (plan.files.isEmpty()) { note(text(T_CLEAN_EMPTY), false); return; }
                StringBuilder list = new StringBuilder(fmt(T_CLEAN_PREVIEW, plan.root, plan.files.size(), size(plan.bytes)));
                for (GameCleanup.Entry file : plan.files)
                    list.append('\n').append(file.file.getAbsolutePath().substring(plan.root.getAbsolutePath().length() + 1))
                        .append(" — ").append(size(file.size));
                ScrollView scroll = new ScrollView(this);
                TextView contents = label(list.toString(), 14, Color.WHITE);
                contents.setPadding(dp(18), dp(8), dp(18), dp(8));
                scroll.addView(contents);
                dialog().setTitle(text(T_CLEAN)).setView(scroll)
                    .setPositiveButton(text(T_DELETE), (d, w) -> deleteExtras(plan))
                    .setNegativeButton(text(T_CANCEL), null).show();
            });
        }, "cleanup-scan").start();
    }

    private void deleteExtras(GameCleanup.Plan plan) {
        ++cleanupGeneration;
        cleanupScanning = null;
        cleanupPlan = null;
        setBusy(text(T_CLEAN_BUSY));
        new Thread(() -> {
            long bytes = 0;
            String failure = null;
            try { bytes = GameCleanup.delete(plan); }
            catch (IOException | RuntimeException e) { failure = fmt(E_IO, String.valueOf(e.getMessage())); }
            final long freed = bytes;
            final String problem = failure;
            handler.post(() -> {
                setBusy(null);
                if (isFinishing() || isDestroyed()) return;
                if (problem != null) error(problem); else note(fmt(T_CLEAN_DONE, size(freed)), false);
                refreshCleanup();
            });
        }, "cleanup").start();
    }

    /* ---------------------------------------------------------- permission */

    private boolean storage() {
        return checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
            && checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
    }

    private void askStorage() {
        if (storageRefused && !shouldShowRequestPermissionRationale(Manifest.permission.WRITE_EXTERNAL_STORAGE)) {
            startActivity(new Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.fromParts("package", getPackageName(), null)));
            return;
        }
        requestPermissions(new String[] {Manifest.permission.READ_EXTERNAL_STORAGE,
            Manifest.permission.WRITE_EXTERNAL_STORAGE}, ASK_STORAGE);
    }

    @Override public void onRequestPermissionsResult(int request, String[] permissions, int[] results) {
        if (request != ASK_STORAGE) return;
        if (!storage()) storageRefused = true;
        refresh();
    }

    /* ---------------------------------------------------------------- paths */

    /** A folder chosen in the system's picker as a file: the game reads its
     *  files by path (the storage permission), so only folders of the
     *  device's own storage do. */
    static File treePath(Uri tree) {
        try {
            return documentPath(tree.getAuthority(), DocumentsContract.getTreeDocumentId(tree));
        } catch (RuntimeException e) {
            return null;
        }
    }

    static File documentPath(String authority, String id) {
        if (id == null) return null;
        if (DOWNLOADS.equals(authority) && id.startsWith("raw:")) return new File(id.substring(4));
        if (!EXTERNAL.equals(authority)) return null;
        int colon = id.indexOf(':');
        String volume = colon < 0 ? id : id.substring(0, colon), path = colon < 0 ? "" : id.substring(colon + 1);
        File root = volume.equals("primary") ? Environment.getExternalStorageDirectory()
            : volume.equals("home") ? new File(Environment.getExternalStorageDirectory(), Environment.DIRECTORY_DOCUMENTS)
            : new File("/storage", volume);
        return path.isEmpty() ? root : new File(root, path);
    }

    static Uri documentOf(File dir) {
        String storage = Environment.getExternalStorageDirectory().getPath(), p = dir.getPath(), id;
        if (p.equals(storage)) {
            id = "primary:";
        } else if (p.startsWith(storage + "/")) {
            id = "primary:" + p.substring(storage.length() + 1);
        } else {
            Matcher m = Pattern.compile("^/storage/([^/]+)(?:/(.*))?$").matcher(p);
            if (!m.matches() || m.group(1).equals("emulated") || m.group(1).equals("self")) return null;
            id = m.group(1) + ":" + (m.group(2) != null ? m.group(2) : "");
        }
        return DocumentsContract.buildDocumentUri(EXTERNAL, id);
    }

    private static File fileOf(Uri uri, ParcelFileDescriptor fd) {
        long size = -1;
        try {
            size = Os.fstat(fd.getFileDescriptor()).st_size;
        } catch (Exception e) {
            /* compared only when known */
        }
        List<String> candidates = new ArrayList<>();
        try {
            File f = documentPath(uri.getAuthority(), DocumentsContract.getDocumentId(uri));
            if (f != null) candidates.add(f.getPath());
        } catch (RuntimeException e) {
            /* not a document */
        }
        try {
            String link = Os.readlink("/proc/self/fd/" + fd.getFd());
            candidates.add(link);
            Matcher m;
            if ((m = Pattern.compile("^/data/media/(\\d+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/emulated/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/[a-z_]+/\\d+/emulated/(\\d+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/emulated/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/[a-z_]+/\\d+/([0-9A-Fa-f]{4}-[0-9A-Fa-f]{4})/(.*)$").matcher(link)).matches())
                candidates.add("/storage/" + m.group(1) + "/" + m.group(2));
            if ((m = Pattern.compile("^/mnt/media_rw/([^/]+)/(.*)$").matcher(link)).matches())
                candidates.add("/storage/" + m.group(1) + "/" + m.group(2));
        } catch (Exception e) {
            /* no such link */
        }
        for (String c : candidates) {
            File f = new File(c);
            if (f.isFile() && (size < 0 || f.length() == size)) return f;
        }
        return null;
    }

    private String archiveName(Uri uri, File file) {
        String name = query(uri, OpenableColumns.DISPLAY_NAME);
        return name != null ? name : file != null ? file.getName() : "?";
    }

    private long archiveSize(Uri uri, File file) {
        String n = query(uri, OpenableColumns.SIZE);
        try {
            if (n != null) return Long.parseLong(n);
        } catch (NumberFormatException e) {
            /* the file's, then */
        }
        return file != null && file.isFile() ? file.length() : -1;
    }

    private String query(Uri uri, String column) {
        if (uri == null) return null;
        try (Cursor c = getContentResolver().query(uri, new String[] {column}, null, null, null)) {
            if (c != null && c.moveToFirst() && !c.isNull(0)) return c.getString(0);
        } catch (Exception e) {
            /* the document is gone or not ours any more */
        }
        return null;
    }

    private static void close(java.io.Closeable c) {
        try {
            c.close();
        } catch (IOException e) {
            /* it was only read */
        }
    }

    /* ------------------------------------------------------------------ UI */

    private int dp(float v) { return Math.round(v * getResources().getDisplayMetrics().density); }

    private void build() {
        FrameLayout root = new FrameLayout(this);
        root.setBackground(new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
            new int[] {Color.rgb(20, 34, 48), Color.rgb(10, 16, 24), Color.rgb(2, 3, 5)}));
        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        LinearLayout column = new LinearLayout(this) {
            @Override protected void onMeasure(int w, int h) {
                int max = dp(600);
                if (MeasureSpec.getSize(w) > max) w = MeasureSpec.makeMeasureSpec(max, MeasureSpec.EXACTLY);
                super.onMeasure(w, h);
            }
        };
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(dp(16), dp(20), dp(16), dp(24));

        LinearLayout head = new LinearLayout(this);
        head.setGravity(Gravity.CENTER);
        ImageView icon = new ImageView(this);
        icon.setImageDrawable(getApplicationInfo().loadIcon(getPackageManager()));
        head.addView(icon, new LinearLayout.LayoutParams(dp(64), dp(64)));
        LinearLayout names = new LinearLayout(this);
        names.setOrientation(LinearLayout.VERTICAL);
        names.setPadding(dp(12), 0, 0, 0);
        TextView title = new TextView(this);
        title.setText("Heroes of Might and Magic V");
        title.setTextColor(GOLD);
        title.setTextSize(26);
        title.setTypeface(Typeface.create(Typeface.SERIF, Typeface.BOLD));
        names.addView(title);
        TextView subtitle = new TextView(this);
        subtitle.setText("Heroes V / Hammers of Fate / Tribes of the East");
        subtitle.setTextColor(Color.rgb(200, 170, 110));
        subtitle.setTextSize(16);
        subtitle.setTypeface(Typeface.create(Typeface.SERIF, Typeface.ITALIC));
        names.addView(subtitle);
        head.addView(names, new LinearLayout.LayoutParams(0, -2, 1));
        column.addView(head, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout card = card(column);
        card.addView(heading(text(T_GAME)));
        gameTitle = label("", 18, Color.WHITE);
        gameTitle.setTypeface(Typeface.DEFAULT_BOLD);
        card.addView(gameTitle);
        gamePath = label("", 13, GREY);
        card.addView(gamePath);
        LinearLayout buttons = new LinearLayout(this);
        buttons.setPadding(0, dp(10), 0, dp(4));
        archiveButton = button(text(T_ARCHIVE), false, this::pickArchive);
        folderButton = button(text(T_FOLDER), false, () -> pickFolder(ASK_FOLDER, base.isDirectory() ? base : null));
        LinearLayout.LayoutParams half = new LinearLayout.LayoutParams(0, dp(48), 1);
        half.setMargins(0, 0, dp(6), 0);
        buttons.addView(archiveButton, half);
        half = new LinearLayout.LayoutParams(0, dp(48), 1);
        half.setMargins(dp(6), 0, 0, 0);
        buttons.addView(folderButton, half);
        card.addView(buttons);
        card.addView(label(text(T_HINT), 13, GREY));
        copies = new LinearLayout(this);
        copies.setOrientation(LinearLayout.VERTICAL);
        card.addView(copies);

        editionCards = new LinearLayout(this);
        editionCards.setOrientation(LinearLayout.VERTICAL);
        column.addView(editionCards);

        if (RendererPolicy.ENABLED) buildRenderer(column);
        buildTextures(column);

        LinearLayout box = card(column);
        progressBox = box;
        box.addView(heading(text(T_UNPACKING_TITLE)));
        progressTarget = label("", 13, GREY);
        box.addView(progressTarget);
        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(1000);
        progress.setProgressTintList(ColorStateList.valueOf(GOLD));
        box.addView(progress, new LinearLayout.LayoutParams(-1, dp(18)));
        progressText = label("", 14, Color.WHITE);
        box.addView(progressText);
        stopButton = button(text(T_STOP), false, this::askStop);
        LinearLayout.LayoutParams stop = new LinearLayout.LayoutParams(-1, dp(44));
        stop.setMargins(0, dp(10), 0, 0);
        box.addView(stopButton, stop);
        progressBox.setVisibility(View.GONE);

        LinearLayout options = card(column);
        skipBox = new LinearLayout(this);
        skipBox.setOrientation(LinearLayout.VERTICAL);
        options.addView(skipBox);
        options.addView(label(text(T_SETTINGS_HINT), 13, GREY));
        cleanupButton = button(text(T_CLEAN), false, this::scanCleanup);
        cleanupButton.setVisibility(View.GONE);
        LinearLayout.LayoutParams clean = new LinearLayout.LayoutParams(-1, dp(48));
        clean.setMargins(0, dp(10), 0, 0);
        options.addView(cleanupButton, clean);

        LinearLayout permission = card(column);
        permissionBox = permission;
        permission.addView(label(text(T_PERMISSION), 15, Color.WHITE));
        LinearLayout.LayoutParams allow = new LinearLayout.LayoutParams(-1, dp(44));
        allow.setMargins(0, dp(10), 0, 0);
        permission.addView(button(text(T_ALLOW), false, this::askStorage), allow);

        note = label("", 14, GOLD);
        note.setPadding(dp(4), dp(12), dp(4), 0);
        note.setVisibility(View.GONE);
        column.addView(note);

        scroll.addView(column, new FrameLayout.LayoutParams(-1, -2, Gravity.CENTER_HORIZONTAL));
        root.addView(scroll, new FrameLayout.LayoutParams(-1, -1));
        setContentView(root);
    }

    private void refresh() {
        boolean files = storage();
        if (files && !storageSeen) {
            storageSeen = true;
            cleanStale();
            if (game == null) game = chosenGame(this, null, edition);
        }
        permissionBox.setVisibility(files ? View.GONE : View.VISIBLE);
        refreshEditions(files);
        if (game != null) {
            gameTitle.setText(files ? Games.title(edition) : game.getName());
            gameTitle.setTextColor(Color.WHITE);
            gamePath.setText(game.getPath());
            gamePath.setVisibility(View.VISIBLE);
        } else {
            gameTitle.setText(text(T_NONE));
            gameTitle.setTextColor(GREY);
            gamePath.setVisibility(View.GONE);
        }
        copies.removeAllViews();
        List<File> found = files ? copies(base, edition) : new ArrayList<>();
        if (!found.isEmpty() && !(found.size() == 1 && found.get(0).equals(game))) {
            copies.addView(heading(text(T_FOUND)));
            for (File f : found) copies.addView(copyRow(f));
        }
        skipBox.removeAllViews();
        skipBox.addView(toggle(text(T_SKIP_INTRO), skipIntro(this), true, null, this::setSkipIntro));
        skipBox.addView(toggle(text(T_NCF), newCreatureFramework(this), true, text(T_NCF_HINT), this::setNewCreatureFramework));
        refreshRenderer();
        if ("toe".equals(edition)) skipBox.addView(lanPeersRow());
        enable();
        refreshCleanup();
        refreshTextures();
    }

    /* ------------------------------------------------------------ renderer */

    /** The modes with what they need, unavailable ones greyed with their reason (RendererPolicy). */
    private final class RendererAdapter extends ArrayAdapter<String> {
        RendererPolicy.Status[] statuses;

        RendererAdapter() {
            super(Launcher.this, android.R.layout.simple_spinner_item, new ArrayList<>());
            for (String mode : RendererPolicy.MODES) add(RendererPolicy.title(mode));
            setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        }

        @Override public boolean areAllItemsEnabled() { return false; }
        @Override public boolean isEnabled(int position) { return statuses == null || statuses[position].available; }

        @Override public View getView(int position, View convert, ViewGroup parent) {
            TextView view = (TextView) super.getView(position, convert, parent);
            view.setTextColor(Color.WHITE);
            view.setTextSize(17);
            return view;
        }

        @Override public View getDropDownView(int position, View convert, ViewGroup parent) {
            TextView view = (TextView) super.getDropDownView(position, convert, parent);
            boolean on = isEnabled(position);
            view.setText(RendererPolicy.title(RendererPolicy.MODES[position]) + (on ? "" : "  ·  " + text(T_RENDERER_UNAVAILABLE)));
            view.setTextColor(on ? Color.WHITE : GREY);
            view.setBackgroundColor(CELL);
            return view;
        }
    }

    private void buildRenderer(LinearLayout column) {
        LinearLayout box = card(column);
        box.addView(heading(text(T_RENDERER)));
        rendererSpinner = new Spinner(this, Spinner.MODE_DROPDOWN);
        rendererAdapter = new RendererAdapter();
        rendererSpinner.setAdapter(rendererAdapter);
        rendererSpinner.setPopupBackgroundDrawable(new android.graphics.drawable.ColorDrawable(CELL));
        rendererSpinner.setBackgroundTintList(ColorStateList.valueOf(GOLD));
        rendererSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                /* Programmatic selections (rendererShown) are no choice of the player. */
                if (position == rendererShown || !rendererAdapter.isEnabled(position)) return;
                Renderers.choose(Launcher.this, RendererPolicy.MODES[position], Renderers.USER);
                rendererAuto = false;
                refreshRenderer();
            }

            @Override public void onNothingSelected(AdapterView<?> parent) { }
        });
        box.addView(rendererSpinner, new LinearLayout.LayoutParams(-1, dp(48)));
        rendererDescription = label("", 13, Color.WHITE);
        box.addView(rendererDescription);
        rendererNote = label("", 13, GOLD);
        box.addView(rendererNote);
        rendererModes = new LinearLayout(this);
        rendererModes.setOrientation(LinearLayout.VERTICAL);
        box.addView(rendererModes);
    }

    /** The check finished, failed or timed out: show it (and make the first start's choice). */
    private final Runnable rendererWatcher = new Runnable() {
        @Override public void run() {
            if (isFinishing() || isDestroyed()) return;
            boolean waiting = Renderers.needsProbe(Launcher.this) && Renderers.report(Launcher.this) == null;
            refreshRenderer();
            if (waiting && System.currentTimeMillis() < rendererWaitUntil) handler.postDelayed(this, 300);
        }
    };

    private void refreshRenderer() {
        if (rendererSpinner == null) return;
        boolean ru = Renderers.ru();
        Map<String, String> report = Renderers.report(this);
        boolean waiting = report == null && Renderers.needsProbe(this);
        RendererPolicy.Status[] statuses = Renderers.statuses(this, report);
        String chosen = Renderers.chosen(this);
        if (chosen.isEmpty() && !waiting) {
            /* The first start with a finished check picks the best mode by itself. */
            chosen = RendererPolicy.best(statuses, report);
            Renderers.choose(this, chosen, Renderers.AUTO);
            rendererAuto = true;
            android.util.Log.i("HeroesV", "launcher: renderer " + chosen + " chosen for this device");
        }
        String shown = chosen.isEmpty() ? RendererPolicy.GLES : chosen;
        rendererAdapter.statuses = statuses;
        rendererAdapter.notifyDataSetChanged();
        rendererShown = java.util.Arrays.asList(RendererPolicy.MODES).indexOf(shown);
        if (rendererSpinner.getSelectedItemPosition() != rendererShown) rendererSpinner.setSelection(rendererShown, false);
        RendererPolicy.Status current = RendererPolicy.status(statuses, shown);
        StringBuilder about = new StringBuilder(RendererPolicy.description(shown, ru));
        if (!RendererPolicy.GLES.equals(shown)) about.append("\n").append(RendererPolicy.limits(ru));
        rendererDescription.setText(about);
        String note = null, fallback = Renderers.fallback(this), last = Renderers.lastStart(this);
        int colour = RED;
        /* The texture section's scan of the chosen ToE game: DXVK has no D3D9 format for ASTC/ETC2. */
        boolean converted = "toe".equals(edition) && texState != null && texState.failure == null && texState.converted != 0;
        if (converted && !RendererPolicy.GLES.equals(shown)) note = fmt(T_RENDERER_CONVERTED, RendererPolicy.title(shown));
        else if (!current.available && !waiting) note = fmt(T_RENDERER_NOW_GLES, RendererPolicy.title(shown), current.reason);
        else if (!fallback.isEmpty()) note = fmt(T_RENDERER_FALLBACK, RendererPolicy.title(fallback));
        else if (!RendererPolicy.GLES.equals(last) && !startupMarker(this, "toe").isFile()) note = fmt(T_RENDERER_FAILED, RendererPolicy.title(last));
        else if (rendererAuto) { note = fmt(T_RENDERER_AUTO, RendererPolicy.title(shown)); colour = GOLD; }
        else if (waiting) { note = text(T_RENDERER_CHECKING); colour = GOLD; }
        rendererNote.setText(note);
        rendererNote.setTextColor(colour);
        rendererNote.setVisibility(note == null ? View.GONE : View.VISIBLE);
        rendererModes.removeAllViews();
        for (RendererPolicy.Status status : statuses) {
            String line = RendererPolicy.title(status.mode) + "  —  " + (status.available ? text(T_RENDERER_AVAILABLE) : status.reason);
            rendererModes.addView(label(line, 12, status.available ? GOLD : GREY));
        }
        if (report != null) {
            String gpu = report.getOrDefault("stock.device", "");
            if (!gpu.isEmpty()) {
                String line = fmt(T_RENDERER_GPU, gpu, report.getOrDefault("stock.api", "?"));
                if ("ok".equals(report.get("turnip.status")) || "missing".equals(report.get("turnip.status")))
                    line += "; Turnip: Vulkan " + report.getOrDefault("turnip.api", "?");
                rendererModes.addView(label(line, 12, GREY));
            }
        }
    }

    private void selectEdition(String id) {
        edition = id;
        game = chosenGame(this, null, id);
        prefs.edit().putString("edition", id).apply();
        texState = null;
        cleanupPlan = null;
        ++cleanupGeneration;
        note(null, false);
        refresh();
    }

    private void refreshEditions(boolean files) {
        editionCards.removeAllViews();
        editionControls.clear();
        for (String id : Games.IDS) {
            File located = files ? chosenGame(this, null, id) : null;
            boolean runtime = Assets.runtimeAvailable(this, base, id);
            LinearLayout box = card(editionCards);
            TextView title = label(Games.title(id) + "  " + Games.version(id), 17, id.equals(edition) ? GOLD : Color.WHITE);
            title.setTypeface(Typeface.DEFAULT_BOLD);
            box.addView(title);
            if (located != null) box.addView(label(located.getPath(), 12, GREY));
            box.addView(label(!runtime ? text(T_RUNTIME_MISSING) : located == null ? text(T_NONE) : text(T_READY), 12,
                runtime && located != null ? GOLD : GREY));
            TextView start = button(text(T_PLAY), true, () -> playEdition(id));
            start.setTag(runtime && located != null);
            box.addView(start, new LinearLayout.LayoutParams(-1, dp(48)));
            box.setOnClickListener(v -> playEdition(id));
            box.setTag(runtime && located != null);
            editionControls.add(box);
            editionControls.add(start);
        }
    }

    private void playEdition(String id) {
        if (!storage() || Unpacker.current != null || busy != null
                || (Textures.current != null && !Textures.current.finished)) return;
        selectEdition(id);
        play();
    }

    private void enable() {
        boolean idle = Unpacker.current == null && busy == null, files = storage();
        setEnabled(archiveButton, idle && files);
        setEnabled(folderButton, idle && files);
        Textures.Job tex = Textures.current;
        idle = idle && (tex == null || tex.finished);
        for (View control : editionControls) setEnabled(control, idle && files && Boolean.TRUE.equals(control.getTag()));
        boolean extras = files && game != null && cleanupPlan != null && game.equals(cleanupPlan.root) && !cleanupPlan.files.isEmpty();
        cleanupButton.setVisibility(extras ? View.VISIBLE : View.GONE);
        if (extras) cleanupButton.setText(text(T_CLEAN) + "  ·  " + size(cleanupPlan.bytes));
        setEnabled(cleanupButton, idle && extras);
        for (int i = 0; i < copies.getChildCount(); ++i) copies.getChildAt(i).setEnabled(idle);
    }

    private static void setEnabled(View v, boolean on) {
        v.setEnabled(on);
        v.setAlpha(on ? 1f : 0.4f);
    }

    private void setBusy(String what) {
        busy = what;
        note(what, false);
        enable();
    }

    private void note(String text, boolean error) {
        note.setVisibility(text == null ? View.GONE : View.VISIBLE);
        note.setText(text);
        note.setTextColor(error ? RED : GOLD);
    }

    private void error(String text) {
        note(text, true);
        dialog().setMessage(text).setPositiveButton(text(T_OK), null).show();
    }

    private AlertDialog.Builder dialog() { return new AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert); }

    private LinearLayout card(LinearLayout parent) {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(16), dp(10), dp(16), dp(14));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(Color.argb(235, 22, 20, 26));
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), Color.argb(110, 235, 203, 127));
        c.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(14), 0, 0);
        parent.addView(c, lp);
        return c;
    }

    private TextView label(String text, float sp, int colour) {
        TextView t = new TextView(this);
        t.setText(text);
        t.setTextSize(sp);
        t.setTextColor(colour);
        t.setPadding(0, dp(4), 0, dp(2));
        return t;
    }

    private TextView heading(String text) {
        TextView t = label(text, 13, GOLD);
        t.setPadding(0, dp(8), 0, dp(2));
        return t;
    }

    private TextView button(String text, boolean primary, Runnable action) {
        TextView b = new TextView(this);
        b.setText(text);
        b.setGravity(Gravity.CENTER);
        b.setTextSize(primary ? 20 : 15);
        b.setTextColor(primary ? GOLD : Color.WHITE);
        if (primary) b.setTypeface(Typeface.DEFAULT_BOLD);
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(primary ? 14 : 10));
        bg.setColor(primary ? Color.rgb(64, 44, 14) : CELL);
        if (primary) bg.setStroke(dp(2), GOLD_DARK);
        b.setBackground(bg);
        b.setOnClickListener(v -> action.run());
        return b;
    }

    private View copyRow(File dir) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(12), dp(8), dp(12), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(10));
        bg.setColor(CELL);
        if (dir.equals(game)) bg.setStroke(dp(2), GOLD);
        row.setBackground(bg);
        row.addView(label(label(dir), 15, Color.WHITE));
        row.addView(label(dir.getPath(), 12, GREY));
        row.setOnClickListener(v -> select(dir));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(6), 0, 0);
        row.setLayoutParams(lp);
        return row;
    }

    private interface BoolSink { void set(boolean v); }

    /** A label and a drawn switch (the platform's is near invisible on black). */
    private View toggle(String text, boolean value, boolean enabled, String why, BoolSink sink) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(6), 0, dp(6));
        LinearLayout words = new LinearLayout(this);
        words.setOrientation(LinearLayout.VERTICAL);
        words.addView(label(text, 15, Color.WHITE));
        if (why != null) words.addView(label(why, 12, GREY));
        row.addView(words, new LinearLayout.LayoutParams(0, -2, 1));
        final boolean[] on = {value};
        View pill = new View(this) {
            private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);

            @Override protected void onDraw(Canvas c) {
                float w = getWidth(), h = getHeight(), r = h / 2f;
                p.setColor(on[0] ? GOLD_DARK : Color.rgb(85, 85, 95));
                c.drawRoundRect(0, 0, w, h, r, r, p);
                p.setColor(on[0] ? GOLD : Color.rgb(215, 215, 222));
                c.drawCircle(on[0] ? w - r : r, r, r * 0.8f, p);
            }
        };
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(52), dp(30));
        lp.setMargins(dp(10), 0, 0, 0);
        row.addView(pill, lp);
        row.setAlpha(enabled ? 1f : 0.45f);
        if (enabled) {
            row.setOnClickListener(v -> {
                on[0] = !on[0];
                sink.set(on[0]);
                pill.invalidate();
            });
        }
        return row;
    }

    /* ------------------------------------------------------------ textures */

    private void buildTextures(LinearLayout column) {
        texBox = card(column);
        /* Fold setup controls together; an active conversion keeps its progress visible. */
        TextView head = heading("");
        texBox.addView(head);
        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.addView(label(text(T_TEX_WHY), 13, GREY));
        texMemory = label("", 13, GREY);
        info.addView(texMemory);
        texBox.addView(info);
        Runnable fold = () -> {
            boolean open = prefs.getBoolean("tex_info", false);
            info.setVisibility(open ? View.VISIBLE : View.GONE);
            head.setText((open ? "▾  " : "▸  ") + text(T_TEX_TITLE) + (open ? "" : "  ·  " + text(T_TEX_MORE)));
        };
        head.setOnClickListener(v -> {
            prefs.edit().putBoolean("tex_info", !prefs.getBoolean("tex_info", false)).apply();
            fold.run();
        });
        head.setMinHeight(dp(40));
        head.setGravity(Gravity.CENTER_VERTICAL);
        fold.run();
        texStatus = label("", 15, Color.WHITE);
        texBox.addView(texStatus);
        texFormats = new LinearLayout(this);
        texFormats.setOrientation(LinearLayout.VERTICAL);
        info.addView(texFormats);
        texConvert = button(text(T_TEX_CONVERT_BUTTON), false, this::askConvert);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(48));
        lp.setMargins(0, dp(10), 0, 0);
        info.addView(texConvert, lp);
        texProgressBox = new LinearLayout(this);
        texProgressBox.setOrientation(LinearLayout.VERTICAL);
        texProgress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        texProgress.setMax(1000);
        texProgress.setProgressTintList(ColorStateList.valueOf(GOLD));
        texProgressBox.addView(texProgress, new LinearLayout.LayoutParams(-1, dp(18)));
        texProgressText = label("", 14, Color.WHITE);
        texProgressBox.addView(texProgressText);
        texStop = button(text(T_STOP), false, this::askStopTextures);
        lp = new LinearLayout.LayoutParams(-1, dp(44));
        lp.setMargins(0, dp(8), 0, 0);
        texProgressBox.addView(texStop, lp);
        texBox.addView(texProgressBox);
        texDelete = button(text(T_TEX_DELETE), false, this::askDeleteOriginals);
        lp = new LinearLayout.LayoutParams(-1, dp(44));
        lp.setMargins(0, dp(10), 0, 0);
        texBox.addView(texDelete, lp);
        texUndo = button(text(T_TEX_UNDO), false, this::askUndoTextures);
        lp = new LinearLayout.LayoutParams(-1, dp(44));
        lp.setMargins(0, dp(8), 0, 0);
        texBox.addView(texUndo, lp);
        texBox.setVisibility(View.GONE);
    }

    /** The section follows the chosen game: probe the GPU and scan once per game. */
    private void refreshTextures() {
        Textures.Job job = Textures.current;
        boolean running = job != null && !job.finished;
        if (game == null || !storage() || !Textures.available() || (texGpu != null && (texGpu.s3tc || !texGpu.probed))) {
            texBox.setVisibility(running ? View.VISIBLE : View.GONE);
            return;
        }
        if (!running && !texScanning && (texGpu == null || texState == null || !game.equals(texState.game))) {
            scanTextures();
            return;
        }
        showTextures();
    }

    private void scanTextures() {
        final File target = game;
        texScanning = true;
        texStatus.setText(text(T_TEX_SCANNING));
        new Thread(() -> {
            Textures.Gpu gpu = Textures.gpu();
            Textures.Status state = gpu.probed && !gpu.s3tc ? Textures.scan(target) : null;
            handler.post(() -> {
                texScanning = false;
                texGpu = gpu;
                if (state != null && target.equals(game)) texState = state;
                if (texFormat == 0) texFormat = gpu.astc ? Textures.ASTC : Textures.ETC2;
                refreshTextures();
                refreshRenderer();   /* converted textures rule out the DXVK modes */
            });
        }, "texture-scan").start();
    }

    private void showTextures() {
        Textures.Job job = Textures.current;
        boolean running = job != null && !job.finished, idle = !running && Unpacker.current == null && busy == null;
        Textures.Status st = texState;
        boolean scanned = st != null && st.failure == null;
        boolean converted = scanned && st.converted != 0;
        texBox.setVisibility(scanned && (st.textures > 0 || converted) || running ? View.VISIBLE : View.GONE);
        if (st != null && st.failure != null) {
            texBox.setVisibility(View.VISIBLE);
            texStatus.setText(fmt(T_TEX_UNREADABLE, st.failure));
        } else if (converted) {
            String status = fmt(T_TEX_DONE, st.converted == Textures.ASTC ? "ASTC" : "ETC2", st.convertedTextures, size(st.convertedBytes))
                + "\n" + (st.originalsPartiallyRemoved ? text(T_TEX_PARTLY_REMOVED) + "\n" + fmt(T_TEX_KEPT, size(st.removable))
                    : st.originalsRemoved ? text(T_TEX_GONE) : fmt(T_TEX_KEPT, size(st.removable)));
            texStatus.setText(status);
        } else if (scanned) {
            String status = st.textures > 0 ? fmt(T_TEX_FOUND, st.textures, size(st.bytes)) : text(T_TEX_NOTHING);
            if (st.mixedFormats) status += "\n" + text(T_TEX_MIXED);
            else if (st.partial) status += "\n" + text(T_TEX_PARTIAL);
            texStatus.setText(status);
        }
        /* How much the conversion matters here: by the device's RAM (4 GB phones report about 3.6). */
        long ram = totalMemory();
        boolean low = ram > 0 && ram <= 4608L << 20;
        texMemory.setVisibility(ram > 0 && scanned && !converted ? View.VISIBLE : View.GONE);
        texMemory.setText(fmt(low ? T_TEX_RAM_LOW : T_TEX_RAM_OK, ram > 0 ? Math.round(ram / (double) (1L << 30)) + " " + text(T_GB) : "?"));
        texMemory.setTextColor(low ? GOLD : GREY);
        texFormats.removeAllViews();
        boolean choose = scanned && !converted && st.textures > 0 && !running;
        if (choose) {
            boolean astc = texGpu != null && texGpu.astc;
            texFormats.addView(formatRow(Textures.ASTC, text(T_TEX_ASTC), astc ? text(T_TEX_ASTC_HINT) : text(T_TEX_NO_ASTC), astc));
            texFormats.addView(formatRow(Textures.ETC2, text(T_TEX_ETC2), text(T_TEX_ETC2_HINT), true));
        }
        texConvert.setVisibility(choose ? View.VISIBLE : View.GONE);
        setEnabled(texConvert, idle);
        texProgressBox.setVisibility(running ? View.VISIBLE : View.GONE);
        texDelete.setVisibility(converted && st.removalPending && !running ? View.VISIBLE : View.GONE);
        setEnabled(texDelete, idle);
        texUndo.setVisibility(converted && !st.originalsRemoved && !running ? View.VISIBLE : View.GONE);
        setEnabled(texUndo, idle);
        if (running) showTextureProgress(job);
    }

    private long totalMemory() {
        android.app.ActivityManager am = (android.app.ActivityManager) getSystemService(ACTIVITY_SERVICE);
        if (am == null) return 0;
        android.app.ActivityManager.MemoryInfo info = new android.app.ActivityManager.MemoryInfo();
        am.getMemoryInfo(info);
        return info.totalMem;
    }

    private View formatRow(int format, String title, String hint, boolean enabled) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.VERTICAL);
        row.setPadding(dp(12), dp(8), dp(12), dp(8));
        GradientDrawable bg = new GradientDrawable();
        bg.setCornerRadius(dp(10));
        bg.setColor(CELL);
        if (format == texFormat && enabled) bg.setStroke(dp(2), GOLD);
        row.setBackground(bg);
        row.addView(label(title, 15, Color.WHITE));
        row.addView(label(hint, 12, GREY));
        row.setAlpha(enabled ? 1f : 0.45f);
        if (enabled) row.setOnClickListener(v -> { texFormat = format; showTextures(); });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(8), 0, 0);
        row.setLayoutParams(lp);
        return row;
    }

    private void askConvert() {
        Textures.Status st = texState;
        if (st == null || game == null || st.textures == 0) return;
        if (texFormat == Textures.ASTC && (texGpu == null || !texGpu.astc)) texFormat = Textures.ETC2;
        String name = texFormat == Textures.ASTC ? "ASTC" : "ETC2";
        dialog().setTitle(text(T_TEX_TITLE))
            .setMessage(fmt(T_TEX_ASK, st.textures, name, size(st.bytes)))
            .setPositiveButton(text(T_TEX_CONVERT), (d, w) -> startTextures(Textures.CONVERT, texFormat))
            .setNegativeButton(text(T_CANCEL), null)
            .show();
    }

    private void askDeleteOriginals() {
        Textures.Status st = texState;
        if (st == null || game == null) return;
        long largest = 0;
        try {
            for (File bank : Textures.banks(game)) {
                File[] paks = bank.listFiles((dir, name) -> name.toLowerCase(Locale.ROOT).endsWith(".pak"));
                if (paks != null) for (File f : paks)
                    if (!f.getName().toLowerCase(Locale.ROOT).startsWith("zz_port_")) largest = Math.max(largest, f.length());
            }
        } catch (RuntimeException e) {
            error(fmt(E_IO, e.getMessage()));
            return;
        }
        dialog().setTitle(text(T_TEX_DELETE))
            .setMessage(fmt(T_TEX_DELETE_ASK, size(st.removable), size(largest)))
            .setPositiveButton(text(T_DELETE), (d, w) -> startTextures(Textures.REMOVE_ORIGINALS, 0))
            .setNegativeButton(text(T_CANCEL), null)
            .show();
    }

    private void askUndoTextures() {
        Textures.Status st = texState;
        if (st == null || game == null) return;
        dialog().setTitle(text(T_TEX_UNDO))
            .setMessage(fmt(T_TEX_UNDO_ASK, size(st.convertedBytes)))
            .setPositiveButton(text(T_DELETE), (d, w) -> startTextures(Textures.REMOVE_CONVERTED, 0))
            .setNegativeButton(text(T_CANCEL), null)
            .show();
    }

    private void startTextures(int kind, int format) {
        if (game == null || Textures.start(this, game, kind, format) == null) return;
        note(null, false);
        handler.removeCallbacks(texWatcher);
        handler.post(texWatcher);
    }

    private void askStopTextures() {
        Textures.Job job = Textures.current;
        if (job == null || job.finished) return;
        dialog().setMessage(text(T_TEX_STOP_ASK))
            .setPositiveButton(text(T_STOP), (d, w) -> job.cancel())
            .setNegativeButton(text(T_CONTINUE), null)
            .show();
    }

    private final Runnable texWatcher = new Runnable() {
        @Override public void run() {
            Textures.Job job = Textures.current;
            if (job == null) return;
            if (!job.finished) {
                showTextures();
                enable();
                handler.postDelayed(this, 250);
            } else if (visible) {
                texturesFinished(job);
            }
        }
    };

    private void showTextureProgress(Textures.Job job) {
        long[] p = job.progress();
        long total = Math.max(1, p[4]);
        texProgress.setIndeterminate(p[4] == 0);
        texProgress.setProgress((int) (p[3] * 1000 / total));
        String line = TextureService.title(job) + " · " + (p[2] > 0 ? fmt(T_TEX_COUNT, p[1], p[2]) : text(T_TEX_SCANNING));
        long elapsed = System.currentTimeMillis() - job.started;
        if (p[3] > 0 && p[4] > p[3] && elapsed > 5000) {
            long left = (long) (elapsed * (double) (p[4] - p[3]) / p[3] / 1000);
            line += fmt(T_TEX_LEFT, left >= 90 ? fmt(T_TEX_MIN, (left + 30) / 60) : fmt(T_TEX_SEC, Math.max(5, left)));
        }
        texProgressText.setText(line);
        setEnabled(texStop, !job.cancelled && job.kind != Textures.REMOVE_CONVERTED);
    }

    private void texturesFinished(Textures.Job job) {
        Textures.current = null;
        TextureService.cancelResult(this);
        texState = null;   /* scan again: the archives changed */
        if (job.failure != null) {
            dialog().setTitle(text(T_TEX_FAILED)).setMessage(job.failure).setPositiveButton(text(T_OK), null).show();
        } else if (job.cancelled) {
            note(text(T_TEX_STOPPED), false);
        } else {
            note(text(T_TEX_FINISHED), false);
        }
        refresh();
    }

    /* --------------------------------------------------------------- texts */

    static String size(long bytes) {
        Locale l = Locale.getDefault();
        if (bytes >= 1_000_000_000L) return String.format(l, "%.1f %s", bytes / 1e9, text(T_GB));
        return String.format(l, bytes >= 10_000_000L ? "%.0f %s" : "%.1f %s", Math.max(0, bytes) / 1e6, text(T_MB));
    }

    static String progressText(long done, long total) { return fmt(T_PROGRESS, size(done), size(total)); }

    private String describe(Unpacker.Failure f) {
        switch (f.code) {
        case Unpacker.NOT_ZIP: return text(E_NOT_ZIP);
        case Unpacker.SPLIT: return text(E_SPLIT);
        case Unpacker.NO_GAME: return text(E_NO_GAME);
        case Unpacker.NOT_HOMM5: return fmt(E_NO_DATA, f.detail);
        case Unpacker.UNSAFE: return fmt(E_UNSAFE, f.detail);
        case Unpacker.METHOD: return fmt(E_METHOD, f.detail);
        case Unpacker.ENCRYPTED: return text(E_ENCRYPTED);
        case Unpacker.CORRUPT: return fmt(E_CORRUPT, f.detail);
        case Unpacker.FULL: return text(E_FULL);
        case Unpacker.READ_ONLY: return fmt(E_READ_ONLY, f.detail);
        default: return fmt(E_IO, f.detail);
        }
    }

    /* The launcher speaks Russian on a Russian (Ukrainian, Belarusian) phone, English otherwise. */
    static final int T_GAME = 0, T_NONE = 1, T_ARCHIVE = 2, T_FOLDER = 3, T_HINT = 4, T_FOUND = 5, T_PLAY = 6,
        T_READING = 7, T_SEARCHING = 8, T_TARGET_TITLE = 9, T_TARGET_BODY = 10, T_CHOOSE = 11, T_CANCEL = 12,
        T_CONFIRM_TITLE = 13, T_CONFIRM_BODY = 14, T_TAKEN = 15, T_UNPACK = 16, T_OTHER = 17, T_USE = 18,
        T_UNPACKING_TITLE = 19, T_PROGRESS = 20, T_STOP = 21, T_STOP_ASK = 22, T_CONTINUE = 23, T_UNPACKED_TITLE = 24,
        T_DELETE_ASK = 25, T_DELETE = 26, T_KEEP = 27, T_DELETED = 28, T_NOT_DELETED = 29, T_FAILED_TITLE = 30,
        T_STOPPED = 31, T_INTERRUPTED = 32, T_PERMISSION = 33, T_ALLOW = 34, T_GB = 35, T_MB = 36, T_SKIP_INTRO = 37,
        T_OK = 38, E_NOT_ZIP = 39, E_SPLIT = 40, E_NO_GAME = 41, E_NO_DATA = 42, E_UNSAFE = 43, E_METHOD = 44,
        E_ENCRYPTED = 45, E_CORRUPT = 46, E_FULL = 47, E_READ_ONLY = 48, E_IO = 49, E_SPACE = 50, E_NO_PATH = 51,
        E_FOLDER = 52, E_FOLDER_NO_DATA = 53, E_IMAGES = 54, E_NO_ARCHIVE = 55, T_HAS_GAME = 56,
        T_CLEAN = 57, T_CLEAN_SCAN = 58, T_CLEAN_EMPTY = 59, T_CLEAN_PREVIEW = 60, T_CLEAN_BUSY = 61, T_CLEAN_DONE = 62,
        T_TITLE = 63, T_TITLE_TOE = 64, T_SETTINGS_HINT = 65,
        T_TEX_TITLE = 66, T_TEX_WHY = 67, T_TEX_ASTC = 68, T_TEX_ASTC_HINT = 69, T_TEX_ETC2 = 70, T_TEX_ETC2_HINT = 71,
        T_TEX_NO_ASTC = 72, T_TEX_CONVERT = 73, T_TEX_FOUND = 74, T_TEX_DONE = 75, T_TEX_KEPT = 76, T_TEX_GONE = 77,
        T_TEX_DELETE = 78, T_TEX_DELETE_ASK = 79, T_TEX_UNDO = 80, T_TEX_UNDO_ASK = 81, T_TEX_RUNNING = 82,
        T_TEX_REWRITING = 83, T_TEX_SCANNING = 84, T_TEX_COUNT = 85, T_TEX_LEFT = 86, T_TEX_FINISHED = 87,
        T_TEX_FAILED = 88, T_TEX_STOPPED = 89, T_TEX_ASK = 90, T_TEX_STOP_ASK = 91, T_TEX_MIN = 92, T_TEX_SEC = 93,
        T_TEX_UNREADABLE = 94, T_TEX_NOTHING = 95, T_TEX_CONVERT_BUTTON = 96, T_TEX_RAM_LOW = 97, T_TEX_RAM_OK = 98,
        T_TEX_MORE = 99, T_SELECT_GAME = 100, T_READY = 101, T_RUNTIME_MISSING = 102,
        T_TEX_PARTIAL = 103, T_TEX_MIXED = 104, T_TEX_PARTLY_REMOVED = 105, E_NO_PICKER = 106, T_NCF = 107,
        T_NCF_HINT = 108, T_RENDERER = 109, T_RENDERER_UNAVAILABLE = 110, T_RENDERER_AVAILABLE = 111,
        T_RENDERER_AUTO = 112, T_RENDERER_FALLBACK = 113, T_RENDERER_FAILED = 114, T_RENDERER_CHECKING = 115,
        T_RENDERER_GPU = 116, T_RENDERER_NOW_GLES = 117, T_RENDERER_CONVERTED = 118,
        T_LAN_PEERS = 119, T_LAN_PEERS_NONE = 120, T_LAN_PEERS_HINT = 121, T_LAN_PEERS_DIALOG = 122;
    private static final String[][] TEXTS = {
        {"Game files", "Файлы игр"},
        {"No game chosen yet", "Игра ещё не выбрана"},
        {"ZIP archive…", "ZIP-архив…"},
        {"Folder…", "Папка…"},
        {"The game's files: a ZIP archive of the installed game (it is unpacked) or the folder of the installation — "
             + "with the bin/data folders, and bina1/dataa1 for Hammers of Fate.",
         "Файлы игры: ZIP-архив установленной игры (он будет распакован) или папка установки — та, где лежат "
             + "папки bin/data, а для Hammers of Fate также bina1/dataa1."},
        {"On this device", "На устройстве"},
        {"Play", "Играть"},
        {"Reading the archive…", "Читаю архив…"},
        {"Looking for the game…", "Ищу игру…"},
        {"Where to unpack", "Куда распаковать"},
        {"%1$s\nFiles: %2$d, %3$s.\n\nChoose the folder for the game: an empty folder becomes the game's folder; in a "
             + "folder that holds anything, a new folder HeroesV is made.",
         "%1$s\nФайлов: %2$d, %3$s.\n\nВыберите папку для игры: пустая папка станет папкой игры, а в непустой будет "
             + "создана новая папка HeroesV."},
        {"Choose a folder", "Выбрать папку"},
        {"Cancel", "Отмена"},
        {"Unpack the game?", "Распаковать игру?"},
        {"%1$s\n%2$s → %3$s\nFree there: %4$s", "%1$s\n%2$s → %3$s\nСвободно там: %4$s"},
        {"The chosen folder is not empty: the game goes into a new folder %s in it.",
         "В выбранной папке уже что-то есть — игра ляжет в новую папку %s внутри неё."},
        {"Unpack", "Распаковать"},
        {"Another folder", "Другая папка"},
        {"Use this folder", "Взять эту папку"},
        {"Unpacking Heroes V", "Распаковка Heroes V"},
        {"%1$s of %2$s", "%1$s из %2$s"},
        {"Stop", "Прервать"},
        {"Stop unpacking? What is unpacked so far is removed.", "Прервать распаковку? Уже распакованное будет удалено."},
        {"Continue", "Продолжить"},
        {"The game is unpacked", "Игра распакована"},
        {"The game is in %1$s.\n\nDelete the archive %2$s (%3$s)?", "Игра в папке %1$s.\n\nУдалить архив %2$s (%3$s)?"},
        {"Delete", "Удалить"},
        {"Keep", "Оставить"},
        {"The archive is deleted", "Архив удалён"},
        {"The archive could not be deleted", "Не удалось удалить архив"},
        {"Unpacking failed", "Распаковка не удалась"},
        {"Unpacking stopped; nothing is left of it", "Распаковка прервана, от неё ничего не осталось"},
        {"The last unpacking was interrupted; what it had unpacked is removed",
         "Прошлая распаковка прервалась — распакованное ею удалено"},
        {"The game reads its files and keeps its saves in the device's storage: allow access to files.",
         "Игра читает свои файлы и хранит сохранения в памяти устройства: разрешите доступ к файлам."},
        {"Allow", "Разрешить"},
        {"GB", "ГБ"},
        {"MB", "МБ"},
        {"Skip the opening videos", "Пропускать вступительные видео"},
        {"OK", "OK"},
        {"This is not a ZIP archive, or it is damaged.", "Это не ZIP-архив, или он повреждён."},
        {"The archive is split into parts: join them into one ZIP.", "Архив разбит на части: соберите его в один ZIP."},
        {"There is no bin\\H5_Game.exe in the archive.", "В архиве нет bin\\H5_Game.exe."},
        {"The game in the archive (%s) has no data\\data.pak.", "У игры в архиве (%s) нет data\\data.pak."},
        {"The archive has a path that leads out of its folder: %s", "В архиве есть путь, ведущий за пределы его папки: %s"},
        {"The archive is packed with %s; a ZIP packed with Deflate, Deflate64 or not packed is needed.",
         "Архив сжат методом %s; нужен ZIP со сжатием Deflate, Deflate64 или без сжатия."},
        {"The archive is encrypted.", "Архив зашифрован."},
        {"%s came out of the archive damaged (CRC): the archive is damaged.",
         "%s распаковался с ошибкой (CRC): архив повреждён."},
        {"The storage ran out of space.", "В хранилище кончилось место."},
        {"The app cannot write into %s: choose a folder in the device's internal storage.",
         "Приложение не может писать в %s: выберите папку во внутренней памяти устройства."},
        {"Error: %s", "Ошибка: %s"},
        {"Not enough space: %1$s needed, %2$s free.", "Не хватает места: нужно %1$s, свободно %2$s."},
        {"This is not on the device's storage (a cloud?): choose a file or a folder on the device.",
         "Это не в памяти устройства (облако?): выберите файл или папку на устройстве."},
        {"There is no bin\\H5_Game.exe in this folder, above it or below it.",
         "Ни в этой папке, ни выше, ни ниже нет bin\\H5_Game.exe."},
        {"%s has no data\\data.pak: the installation is incomplete.", "В %s нет data\\data.pak — установка неполная."},
        {"This APK does not carry the game's module images, and they are not in /sdcard/HeroesV/lifted either.",
         "В этом APK нет образов модулей игры, и в /sdcard/HeroesV/lifted их тоже нет."},
        {"Choose the archive again.", "Выберите архив ещё раз."},
        {"This folder already holds the game.", "В этой папке уже есть игра."},
        {"Remove files the game does not use…", "Удалить файлы, которые игра не использует…"},
        {"Counting extra files…", "Подсчёт лишних файлов…"},
        {"No extra files found", "Лишних файлов не найдено"},
        {"%1$s\nFiles: %2$d. Reclaimable: %3$s.\nGame data, saves and settings are kept.\n\nRemove these files?\n",
         "%1$s\nФайлов: %2$d. Освободится: %3$s.\nДанные игры, сохранения и настройки сохраняются.\n\nУдалить эти файлы?\n"},
        {"Removing extra files…", "Удаление лишних файлов…"},
        {"Freed: %s", "Освобождено: %s"},
        {"Heroes of Might and Magic V", "Heroes of Might and Magic V"},
        {"Heroes of Might and Magic V — Tribes of the East", "Heroes of Might and Magic V — Повелители Орды"},
        {"Render scale, interface scale and camera sensitivity are in the game: Settings → Additional.",
         "Масштаб рендера, интерфейса и чувствительность камеры — в самой игре: Настройки → Дополнительные."},
        {"Textures", "Текстуры"},
        {"This device's GPU cannot read the DXT (S3TC) format the game's textures are stored in. So the processor "
             + "unpacks every texture while a screen loads, and in video memory it then takes 4–8 times more room: "
             + "screens open slower and the game stutters. Converted once into a format the GPU reads directly, the "
             + "textures load straight away and need less memory.",
         "Видеочип этого устройства не умеет читать формат DXT (S3TC), в котором хранятся текстуры игры. Поэтому "
             + "каждую текстуру при загрузке экрана распаковывает процессор, а в видеопамяти она занимает в 4–8 раз "
             + "больше места: экраны открываются дольше, игра подтормаживает. Один раз сконвертированные в формат, "
             + "который видеочип читает напрямую, текстуры загружаются сразу и требуют меньше памяти."},
        {"ASTC — best quality", "ASTC — лучшее качество"},
        {"Nearly indistinguishable from the original. Converting takes a few minutes.",
         "Почти неотличимо от оригинала. Конвертация займёт несколько минут."},
        {"ETC2 — fastest", "ETC2 — быстрее"},
        {"Every OpenGL ES 3 GPU reads it; the picture is a little softer. Converting takes about a minute.",
         "Читается любым видеочипом с OpenGL ES 3; картинка чуть мягче. Конвертация — около минуты."},
        {"This GPU does not support ASTC.", "Этот видеочип не поддерживает ASTC."},
        {"Convert", "Конвертировать"},
        {"Textures in DXT format: %1$d, %2$s.", "Текстур в формате DXT: %1$d, %2$s."},
        {"Converted to %1$s: %2$d textures, %3$s.", "Сконвертировано в %1$s: %2$d текстур, %3$s."},
        {"The original textures are kept (%s in the game's archives).",
         "Оригинальные текстуры сохранены (%s в архивах игры)."},
        {"The original textures are deleted.", "Оригинальные текстуры удалены."},
        {"Delete the original textures…", "Удалить оригинальные текстуры…"},
        {"The game will use only the converted textures. Its archives are rewritten without the originals: this "
             + "frees %1$s and needs up to %2$s of free space while it runs.\n\nTo convert again, or into the other "
             + "format, the game would have to be unpacked anew from its ZIP archive or folder.",
         "Игра будет использовать только сконвертированные текстуры. Её архивы будут перезаписаны без оригиналов: "
             + "освободится %1$s, а на время работы нужно до %2$s свободного места.\n\nЧтобы позже сконвертировать "
             + "заново или в другой формат, игру придётся заново распаковать из ZIP-архива или папки."},
        {"Go back to the original textures…", "Вернуть оригинальные текстуры…"},
        {"Delete the converted textures (%s)? The game will unpack the originals on the processor again.",
         "Удалить сконвертированные текстуры (%s)? Игра снова будет распаковывать оригиналы процессором."},
        {"Converting textures", "Конвертация текстур"},
        {"Rewriting the game's archives", "Перезапись архивов игры"},
        {"Checking the textures…", "Проверка текстур…"},
        {"%1$d of %2$d", "%1$d из %2$d"},
        {" · about %s left", " · осталось около %s"},
        {"The textures are ready", "Текстуры готовы"},
        {"Texture conversion failed", "Конвертация текстур не удалась"},
        {"Stopped; nothing was changed.", "Остановлено; ничего не изменено."},
        {"Convert %1$d textures into %2$s?\n\nThe converted copies take about %3$s; the original textures stay "
             + "where they are. The game can be started once it is done.",
         "Сконвертировать %1$d текстур в %2$s?\n\nСконвертированные копии займут около %3$s; оригинальные "
             + "текстуры остаются на месте. Запустить игру можно будет после завершения."},
        {"Stop? Nothing will be changed.", "Остановить? Ничего не изменится."},
        {"%d min", "%d мин"},
        {"%d s", "%d с"},
        {"The textures cannot be checked: %s", "Не удалось проверить текстуры: %s"},
        {"There are no DXT textures to convert.", "Текстур DXT для конвертации нет."},
        {"Convert textures", "Конвертировать текстуры"},
        {"Recommended for this device. With %s of RAM the unpacked textures may not fit: on large maps the game can "
             + "slow down or be closed by the system. Converted, they need several times less memory.",
         "Рекомендуется для этого устройства. При %s оперативной памяти распакованные текстуры могут в неё не "
             + "поместиться: на больших картах игра может тормозить или закрываться системой. Сконвертированным "
             + "текстурам нужно в несколько раз меньше памяти."},
        {"With %s of RAM the game runs without it too. Converting still frees memory: the textures then take "
             + "several times less of it, so more stays for the system and the apps in the background, and Android is "
             + "less likely to close the game while you switch away.",
         "При %s оперативной памяти игра работает и без конвертации. Но она всё равно освобождает память: текстуры "
             + "займут её в несколько раз меньше — больше останется системе и фоновым приложениям, и Android реже "
             + "закроет игру, пока вы переключаетесь на другие приложения."},
        {"details", "подробнее"},
        {"Select game", "Выбрать игру"},
        {"Ready to play", "Готова к запуску"},
        {"This game is not available in the installed build.",
         "Эта игра недоступна в установленной сборке."},
        {"Some game files still need texture conversion. Convert again to finish.",
         "Часть файлов игры ещё требует конвертации текстур. Повторите конвертацию для завершения."},
        {"The game files use different texture formats. Convert them to one format.",
         "Файлы игры используют разные форматы текстур. Сконвертируйте их в один формат."},
        {"Original textures were removed from some files. Continue removing them to finish.",
         "Оригинальные текстуры удалены из части файлов. Продолжите удаление для завершения."},
        {"The system file picker is unavailable on this device. Enable the Files app (Settings → Apps) and try again.",
         "На устройстве недоступен системный выбор файлов. Включите приложение «Файлы» (Настройки → Приложения) и повторите."},
        {"Tribes of the East: New Creature Framework", "Tribes of the East: New Creature Framework"},
        {"MMH5.5 patches: creature limit 999 for mods with new creatures. Only with such a mod installed: "
            + "without its creature files the game does not start.",
         "Патчи MMH5.5: лимит существ 999 для модов с новыми существами. Только с установленным модом: "
            + "без его файлов существ игра не запустится."},
        {"Tribes of the East: renderer", "Tribes of the East: отрисовка"},
        {"unavailable", "недоступно"},
        {"available", "доступно"},
        {"%s was chosen as the best mode for this device.", "Выбран режим %s — лучший для этого устройства."},
        {"%s did not start last time; the game ran on OpenGL ES. Details: /sdcard/HeroesV/userdata/homm5.log.",
         "%s в прошлый раз не запустился, игра шла на OpenGL ES. Подробности: /sdcard/HeroesV/userdata/homm5.log."},
        {"The last start with %s did not reach the main menu. If the game does not start, choose OpenGL ES.",
         "Прошлый запуск с %s не дошёл до главного меню. Если игра не запускается, выберите OpenGL ES."},
        {"Checking the graphics driver…", "Проверка видеодрайвера…"},
        {"GPU: %1$s, Vulkan %2$s (system driver)", "Видеочип: %1$s, Vulkan %2$s (системный драйвер)"},
        {"%1$s is not available here (%2$s): the game starts with OpenGL ES.",
         "%1$s здесь недоступен (%2$s): игра запустится на OpenGL ES."},
        {"This game's textures are converted for OpenGL ES (ASTC/ETC2), which %s cannot read: go back to the "
             + "original textures (Textures) or choose OpenGL ES.",
         "Текстуры этой игры сконвертированы для OpenGL ES (ASTC/ETC2), а %s их не читает: верните оригинальные "
             + "текстуры (раздел «Текстуры») или выберите OpenGL ES."},
        {"LAN over Tailscale/VPN: players", "LAN через Tailscale/VPN: игроки"},
        {"No addresses", "Адреса не заданы"},
        {"For a network game across Tailscale: the other players' Tailscale addresses or names. Also turn on "
            + "Settings → Additional → «LAN over Tailscale/VPN» in the game on every device.",
         "Для сетевой игры через Tailscale: адреса или имена других игроков в Tailscale. Также включите в игре "
            + "Настройки → Дополнительные → «LAN через Tailscale/VPN» на каждом устройстве."},
        {"Tailscale (100.x.y.z) addresses or MagicDNS names of the other players, separated by spaces, commas "
            + "or lines. The game sends its LAN search to them; their replies come back the same way.",
         "Адреса Tailscale (100.x.y.z) или имена MagicDNS других игроков через пробел, запятую или с новой "
            + "строки. Поиск сетевых игр отправляется и на них, ответы приходят тем же путём."},
    };

    static String text(int id) {
        String lang = Locale.getDefault().getLanguage();
        int col = "ru".equals(lang) || "uk".equals(lang) || "be".equals(lang) ? 1 : 0;
        return TEXTS[id][col];
    }

    static String fmt(int id, Object... args) { return String.format(Locale.getDefault(), text(id), args); }
}
