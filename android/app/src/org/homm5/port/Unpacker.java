package org.homm5.port;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.zip.CRC32;

/** The launcher's unpacking of the game from a ZIP archive. The game's root
 *  in the archive is the folder above bin\H5_Game.exe (the shallowest one);
 *  only the folders the game reads are unpacked (not the editor, manuals or
 *  installers). The files go into a hidden folder first and into place once
 *  every one came out whole (CRC-32), so a stopped or failed unpacking leaves
 *  nothing of itself behind. Plain Java. */
final class Unpacker {
    static final String GAME_EXE = "bin/H5_Game.exe", DATA = "data/data.pak", PATCH = "data/a2p1-data.pak";
    static final String FOLDER = "HeroesV", TEMP = ".unpacking";
    /** What the game itself reads (tools/deploy.py's list). */
    static final String[] NEEDED = {"bin", "bina1", "data", "dataa1", "datals", "music", "video", "profiles", "maps", "usercampaigns", "usermods",
        "hwcursors", "duelpresets"};
    /* Failures, which the launcher names in its own words. */
    static final int NOT_ZIP = 1, SPLIT = 2, NO_GAME = 3, NOT_HOMM5 = 4, UNSAFE = 5, METHOD = 6, ENCRYPTED = 7,
        CORRUPT = 8, FULL = 9, READ_ONLY = 10, IO = 11, CANCELLED = 12;

    static final class Failure extends IOException {
        final int code;
        final String detail;

        Failure(int code, String detail) {
            super("unpacking failure " + code + (detail != null ? ": " + detail : ""));
            this.code = code;
            this.detail = detail;
        }
    }

    private Unpacker() { }

    /** An archive's game: its root in the archive, the files under it in
     *  the order of their data, whether it carries the 3.1 patch. */
    static final class Plan {
        final Zip zip;
        final String root;
        final List<Zip.Entry> files;
        final List<String> paths, folders;   /* files' paths under the root; folders' */
        final long size;
        final boolean patched;
        final List<String> editions;

        Plan(Zip zip, String root, List<Zip.Entry> files, List<String> paths, List<String> folders, long size, boolean patched) {
            this.zip = zip;
            this.root = root;
            this.files = files;
            this.paths = paths;
            this.folders = folders;
            this.size = size;
            this.patched = patched;
            this.editions = new ArrayList<>();
            for (String edition : Games.IDS) {
                boolean complete = true;
                for (String required : Games.required(edition)) {
                    boolean found = false;
                    for (String path : paths) if (path.equalsIgnoreCase(required)) { found = true; break; }
                    if (!found) { complete = false; break; }
                }
                if (complete) editions.add(edition);
            }
        }
    }

    static boolean needed(String path) {
        int slash = path.indexOf('/');
        String top = (slash < 0 ? path : path.substring(0, slash)).toLowerCase(Locale.ROOT);
        if (slash < 0) return false;   /* the root's own files: readmes, installers, icons */
        for (String n : NEEDED) if (n.equals(top)) return true;
        return false;
    }

    static Plan plan(Zip zip) throws IOException {
        String root = root(zip.entries);
        List<Object[]> items = new ArrayList<>();   /* {entry, its path under the root} */
        List<String> folders = new ArrayList<>();
        boolean data = false, patched = false;
        long size = 0;
        for (Zip.Entry e : zip.entries) {
            if (!e.name.regionMatches(true, 0, root, 0, root.length())) continue;
            String path = relative(e.name.substring(root.length()));
            if (path == null) throw new Failure(UNSAFE, e.name);
            if (path.isEmpty()) continue;
            if (e.directory()) {
                if (needed(path + "/x")) folders.add(path);
                continue;
            }
            if (!needed(path)) continue;
            if (e.encrypted()) throw new Failure(ENCRYPTED, e.name);
            if (!Zip.supported(e.method)) throw new Failure(METHOD, Zip.methodName(e.method));
            items.add(new Object[] {e, path});
            size += e.size;
            if (path.equalsIgnoreCase(DATA)) data = true;
            else if (path.equalsIgnoreCase(PATCH)) patched = true;
        }
        if (!data) throw new Failure(NOT_HOMM5, root.isEmpty() ? "/" : root);
        /* One pass over the archive, in the order its data lies. */
        Collections.sort(items, (a, b) -> Long.compare(((Zip.Entry) a[0]).header, ((Zip.Entry) b[0]).header));
        List<Zip.Entry> files = new ArrayList<>(items.size());
        List<String> paths = new ArrayList<>(items.size());
        for (Object[] i : items) {
            files.add((Zip.Entry) i[0]);
            paths.add((String) i[1]);
        }
        Plan plan = new Plan(zip, root, files, paths, folders, size, patched);
        if (plan.editions.isEmpty()) throw new Failure(NOT_HOMM5, root.isEmpty() ? "/" : root);
        return plan;
    }

    /** The folder above the shallowest bin/H5_Game.exe ("" at the top). */
    static String root(List<Zip.Entry> entries) throws Failure {
        String best = null;
        for (Zip.Entry e : entries) {
            String name = e.name;
            for (String executable : new String[] {GAME_EXE, "bina1/H5_Game.exe"}) {
                int cut = name.length() - executable.length();
                if (e.directory() || cut < 0 || !name.regionMatches(true, cut, executable, 0, executable.length())) continue;
                if (cut > 0 && name.charAt(cut - 1) != '/') continue;
                String root = name.substring(0, cut);
                if (root.startsWith("__MACOSX/")) continue;
                if (best == null || depth(root) < depth(best)) best = root;
            }
        }
        if (best == null) throw new Failure(NO_GAME, null);
        return best;
    }

    private static int depth(String path) {
        int n = 0;
        for (int i = 0; i < path.length(); ++i) if (path.charAt(i) == '/') ++n;
        return n;
    }

    /** A path inside the root without empty or "." parts; null if it leaves the root. */
    static String relative(String path) {
        StringBuilder out = new StringBuilder();
        for (String part : path.split("/")) {
            if (part.isEmpty() || part.equals(".")) continue;
            if (part.equals("..") || part.indexOf('\0') >= 0) return null;
            if (out.length() > 0) out.append('/');
            out.append(part);
        }
        return out.toString();
    }

    /** Where the game goes in the folder the player chose: the folder itself
     *  when it is empty, else a new HeroesV (HeroesV-2, ...) in it, so
     *  nothing already there is ever replaced. reserved is the port's own
     *  folder (/sdcard/HeroesV, the saves in it): the game's root must not be it. */
    static File target(File chosen, File reserved) throws Failure {
        String[] names = chosen.list();
        if (names == null) throw new Failure(READ_ONLY, chosen.getPath());
        if (names.length == 0 && !chosen.getAbsoluteFile().equals(reserved.getAbsoluteFile())) return chosen;
        for (int n = 1;; ++n) {
            File f = new File(chosen, n == 1 ? (chosen.equals(reserved) ? "game" : FOLDER) : FOLDER + "-" + n);
            if (!f.exists()) return f;
        }
    }

    /* ------------------------------------------------------- existing copies */

    /** dir's child called name, its case ignored (as Windows would); null if none. */
    static File child(File dir, String name) {
        if (dir == null) return null;
        File f = new File(dir, name);
        if (f.exists()) return f;
        String[] names = dir.list();
        if (names != null) for (String n : names) if (n.equalsIgnoreCase(name)) return new File(dir, n);
        return null;
    }

    static boolean isRoot(File dir) {
        File exe = child(child(dir, "bin"), "H5_Game.exe");
        File expansion = child(child(dir, "bina1"), "H5_Game.exe");
        return (exe != null && exe.isFile()) || (expansion != null && expansion.isFile());
    }

    /** A complete installation: the game's data archive is there too. */
    static boolean isGame(File root) {
        return !Games.editions(root).isEmpty();
    }

    static boolean isPatched(File root) {
        File patch = child(child(root, "data"), "a2p1-data.pak");
        return patch != null && patch.isFile();
    }

    /** The game's root at a folder the player chose: the folder itself, one
     *  above it (a folder inside the game was chosen) or one below it (a
     *  folder holding the game), by bin\H5_Game.exe; null if none. */
    static File findRoot(File dir) {
        File up = dir;
        for (int i = 0; i <= 3 && up != null; ++i, up = up.getParentFile()) if (isRoot(up)) return up;
        List<File> level = Collections.singletonList(dir);
        int visited = 0;
        for (int depth = 0; depth < 3 && !level.isEmpty(); ++depth) {
            List<File> next = new ArrayList<>();
            for (File d : level) {
                File[] subs = d.listFiles(File::isDirectory);
                if (subs == null) continue;
                Arrays.sort(subs);
                for (File s : subs) {
                    if (s.getName().startsWith(".")) continue;
                    if (isRoot(s)) return s;
                    if (++visited > 2000) return null;
                    next.add(s);
                }
            }
            level = next;
        }
        return null;
    }

    /* ----------------------------------------------------------------- job */

    /** The unpacking in progress (one at a time): the launcher and
     *  UnpackService read its progress; it outlives the launcher's window. */
    static volatile Job current;

    static final class Job implements Runnable {
        final Plan plan;
        final File target;
        final boolean created;   /* the target is a new folder, removed again on failure */
        final String source;     /* the archive (the launcher's document), offered for deletion after */
        final File sourceFile;   /* the same as a file, if known */
        volatile long done;
        volatile String file = "";
        volatile boolean cancelled, finished;
        volatile Failure failure;

        Job(Plan plan, File target, String source, File sourceFile) {
            this.plan = plan;
            this.target = target;
            this.created = !target.exists();
            this.source = source;
            this.sourceFile = sourceFile;
        }

        File temp() { return new File(target, TEMP); }

        @Override public void run() {
            try {
                unpack();
            } catch (Failure f) {
                failure = f;
            } catch (IOException e) {
                String m = String.valueOf(e.getMessage());
                failure = new Failure(m.contains("ENOSPC") ? FULL : m.contains("EACCES") || m.contains("EROFS") ? READ_ONLY : IO, m);
            } catch (RuntimeException e) {
                failure = new Failure(IO, e.toString());
            } finally {
                if (failure != null) clean(temp(), created ? target : null);
                try {
                    plan.zip.close();
                } catch (IOException e) {
                    /* the archive was only read */
                }
                finished = true;
            }
        }

        private void unpack() throws IOException {
            File temp = temp();
            if (!temp.isDirectory() && !temp.mkdirs()) throw new Failure(READ_ONLY, target.getPath());
            for (String f : plan.folders) new File(temp, f).mkdirs();
            byte[] buffer = new byte[1 << 20];
            CRC32 crc = new CRC32();
            for (int i = 0; i < plan.files.size(); ++i) {
                Zip.Entry e = plan.files.get(i);
                String path = plan.paths.get(i);
                file = path;
                File out = new File(temp, path);
                File parent = out.getParentFile();
                if (!parent.isDirectory() && !parent.mkdirs()) throw new Failure(READ_ONLY, parent.getPath());
                crc.reset();
                long written = 0;
                try (java.io.InputStream in = plan.zip.open(e); FileOutputStream o = new FileOutputStream(out)) {
                    for (int n; (n = in.read(buffer, 0, buffer.length)) > 0;) {
                        if (cancelled) throw new Failure(CANCELLED, null);
                        o.write(buffer, 0, n);
                        crc.update(buffer, 0, n);
                        written += n;
                        done += n;
                    }
                }
                if (cancelled) throw new Failure(CANCELLED, null);
                if (written != e.size || crc.getValue() != e.crc) throw new Failure(CORRUPT, path);
            }
            /* Into place: the target held nothing (or was new). */
            String[] items = temp.list();
            if (items == null) throw new Failure(IO, temp.getPath());
            Arrays.sort(items);
            for (String name : items) {
                File to = new File(target, name);
                if (to.exists() || !new File(temp, name).renameTo(to)) throw new Failure(IO, to.getPath());
            }
            if (!temp.delete()) throw new Failure(IO, temp.getPath());
        }
    }

    /** Removes an unpacking's hidden folder, and its target if it was new and is left empty. */
    static void clean(File temp, File createdTarget) {
        delete(temp);
        if (createdTarget != null) {
            String[] left = createdTarget.list();
            if (left != null && left.length == 0) createdTarget.delete();
        }
    }

    /** f and everything in it, without following links out of it. */
    static void delete(File f) {
        if (f.isDirectory() && !java.nio.file.Files.isSymbolicLink(f.toPath())) {
            File[] items = f.listFiles();
            if (items != null) for (File i : items) delete(i);
        }
        f.delete();
    }
}
