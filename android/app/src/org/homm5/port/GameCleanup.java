package org.homm5.port;

import java.io.File;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Files of a copied installation the game never reads: the map editor, its
 *  documentation, manuals, installers and the GOG client's files. Only the
 *  folders Unpacker.NEEDED stay; links are never followed, and the preview is
 *  exactly the set deletion uses. */
final class GameCleanup {
    static final class Entry {
        final File file;
        final long size;

        Entry(File file, long size) {
            this.file = file;
            this.size = size;
        }
    }

    static final class Plan {
        final File root;
        final List<Entry> files;
        final long bytes;

        Plan(File root, List<Entry> files) {
            this.root = root;
            this.files = Collections.unmodifiableList(files);
            long sum = 0;
            for (Entry entry : files) sum += entry.size;
            bytes = sum;
        }
    }

    private GameCleanup() { }

    static Plan scan(File folder) throws IOException {
        File root = folder.getAbsoluteFile();
        if (!Unpacker.isGame(root)) throw new IOException("The selected folder is not a complete game installation");
        List<Entry> files = new ArrayList<>();
        File[] entries = root.listFiles();
        if (entries == null) throw new IOException("Cannot read " + root);
        java.util.Arrays.sort(entries, (a, b) -> a.getName().compareToIgnoreCase(b.getName()));
        for (File file : entries) {
            if (keep(file)) continue;
            collect(file, files);
        }
        return new Plan(root, files);
    }

    private static boolean keep(File top) {
        String name = top.getName();
        if (name.startsWith(".")) return true;           /* an unpacking in progress, hidden state */
        if (top.isDirectory() && Unpacker.needed(name + "/x")) return true;
        /* The port's own development folders, should one share the folder. */
        if (!top.isDirectory()) return false;
        for (String edition : Games.IDS)
            if (name.equalsIgnoreCase(Games.userdata(edition)) || name.equalsIgnoreCase(Games.images(edition))) return true;
        return false;
    }

    private static void collect(File file, List<Entry> out) throws IOException {
        BasicFileAttributes attributes = Files.readAttributes(file.toPath(), BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        if (attributes.isSymbolicLink()) return;
        if (attributes.isRegularFile()) {
            out.add(new Entry(file, attributes.size()));
        } else if (attributes.isDirectory()) {
            File[] entries = file.listFiles();
            if (entries == null) throw new IOException("Cannot read " + file);
            java.util.Arrays.sort(entries, (a, b) -> a.getName().compareToIgnoreCase(b.getName()));
            for (File child : entries) collect(child, out);
        }
    }

    /** Deletes the previewed files (those unchanged since), then emptied folders. */
    static long delete(Plan plan) throws IOException {
        long freed = 0;
        List<File> folders = new ArrayList<>();
        for (Entry entry : plan.files) {
            File file = entry.file;
            if (!file.getAbsolutePath().startsWith(plan.root.getAbsolutePath() + File.separator)) continue;
            if (!file.isFile() || file.length() != entry.size) continue;
            if (file.delete()) freed += entry.size;
            for (File parent = file.getParentFile(); parent != null && !parent.equals(plan.root); parent = parent.getParentFile())
                if (!folders.contains(parent)) folders.add(parent);
        }
        /* Deepest first: a folder empties once its children are gone. */
        Collections.sort(folders, (a, b) -> b.getAbsolutePath().length() - a.getAbsolutePath().length());
        for (File folder : folders) {
            String[] left = folder.list();
            if (left != null && left.length == 0) folder.delete();
        }
        return freed;
    }
}
