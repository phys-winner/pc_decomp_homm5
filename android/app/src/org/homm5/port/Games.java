package org.homm5.port;

import java.io.File;
import java.io.IOException;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;

/** Edition identities and installation checks shared by import and launch. */
final class Games {
    static final String[] IDS = {"vanilla", "hof", "toe"};

    private Games() { }

    static boolean valid(String edition) { return Arrays.asList(IDS).contains(edition); }
    static String suffix(String edition) {
        if (!valid(edition)) throw new IllegalArgumentException("Unknown game: " + edition);
        return "toe".equals(edition) ? "" : "-" + edition;
    }
    static String title(String edition) {
        return "vanilla".equals(edition) ? "Heroes of Might and Magic V"
            : "hof".equals(edition) ? "Hammers of Fate" : "Tribes of the East";
    }
    static String version(String edition) { return "vanilla".equals(edition) ? "1.6" : "hof".equals(edition) ? "2.1" : "3.1"; }
    static String library(String edition) { return "homm5" + suffix(edition).replace('-', '_'); }
    static String pathKey(String edition) { return "game" + suffix(edition); }
    static String userdata(String edition) { return "userdata" + suffix(edition); }
    static String preferences(String edition) { return "port_settings" + suffix(edition); }
    static String images(String edition) { return "lifted" + suffix(edition); }
    static String overlay(String edition) { return "overlay" + suffix(edition); }
    static String cache(String edition) { return "gl" + suffix(edition); }
    static String marker(String edition) { return "game-started" + suffix(edition); }
    static String process(String packageName, String edition) { return packageName + ("toe".equals(edition) ? "" : ":" + edition); }
    static String intro(String edition) { return "vanilla".equals(edition) ? "intro.xml" : "intro_a1.xml"; }

    static String[] required(String edition) {
        suffix(edition);
        if ("hof".equals(edition)) return new String[] {"bina1/H5_Game.exe", "data/data.pak", "dataa1/a1-data.pak", "dataa1/a1p1-data.pak"};
        if ("vanilla".equals(edition)) return new String[] {"bin/H5_Game.exe", "data/data.pak", "data/p3c-data.pak", "DataLS/p6-data.pak"};
        return new String[] {"bin/H5_Game.exe", "data/data.pak", "data/a2p1-data.pak"};
    }

    static File child(File root, String path) {
        File at = root;
        for (String part : path.split("/")) {
            if (at == null) return null;
            File direct = new File(at, part);
            if (direct.exists()) { at = direct; continue; }
            File[] children = at.listFiles();
            at = null;
            if (children != null) for (File item : children) if (item.getName().equalsIgnoreCase(part)) { at = item; break; }
        }
        return at;
    }

    static boolean installed(File root, String edition) {
        if (root == null || !root.isDirectory()) return false;
        for (String path : required(edition)) {
            File file = child(root, path);
            if (file == null || !file.isFile() || !file.canRead()) return false;
        }
        return true;
    }

    static List<String> editions(File root) {
        List<String> editions = new ArrayList<>();
        for (String id : IDS) if (installed(root, id)) editions.add(id);
        return editions;
    }

    /** A selected game folder, an inner folder, or a common parent of installations. */
    static List<File> discover(File source) {
        List<File> result = new ArrayList<>();
        File up = source;
        for (int i = 0; i <= 3 && up != null; ++i, up = up.getParentFile()) {
            if (!editions(up).isEmpty()) { result.add(up); return result; }
        }
        if (source == null || !source.isDirectory()) return result;
        String boundary;
        try { boundary = source.getCanonicalPath(); } catch (IOException unreadable) { return result; }
        String prefix = boundary.endsWith(File.separator) ? boundary : boundary + File.separator;
        ArrayDeque<File> folders = new ArrayDeque<>();
        ArrayDeque<Integer> depths = new ArrayDeque<>();
        HashSet<String> seen = new HashSet<>();
        folders.add(source); depths.add(0);
        int count = 0;
        while (!folders.isEmpty() && count++ < 512) {
            File folder = folders.removeFirst(); int depth = depths.removeFirst();
            String canonical;
            try { canonical = folder.getCanonicalPath(); } catch (IOException unreadable) { continue; }
            if ((!canonical.equals(boundary) && !canonical.startsWith(prefix)) || !seen.add(canonical)) continue;
            if (!editions(folder).isEmpty()) { result.add(folder); continue; }
            if (depth >= 4) continue;
            File[] children = folder.listFiles(File::isDirectory);
            if (children != null) {
                Arrays.sort(children);
                for (File child : children) if (!child.getName().startsWith(".")) { folders.add(child); depths.add(depth + 1); }
            }
        }
        return result;
    }
}
