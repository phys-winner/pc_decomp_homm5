package org.homm5.port;

import java.io.File;
import java.io.IOException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

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

    /** Seed the engine's own selection before it reads global*.cfg. */
    static void selectSingleProfile(File data, String edition) throws IOException {
        suffix(edition);
        String suffix = "toe".equals(edition) ? "_a2" : "hof".equals(edition) ? "_a1" : "";
        File profiles = child(data, "Documents/My Games/" + ("toe".equals(edition)
            ? "Heroes of Might and Magic V \u2014 Tribes of the East/Profiles"
            : "Heroes of Might and Magic V/" + ("hof".equals(edition) ? "Hammers of Fate/" : "") + "Profiles"));
        File[] folders = profiles == null ? null : profiles.listFiles(File::isDirectory);
        if (folders == null) return;
        File single = null;
        for (File folder : folders) {
            File user = child(folder, "user" + suffix + ".cfg");
            if (Files.isSymbolicLink(folder.toPath()) || user == null || !user.isFile()) continue;
            if (single != null) return;
            single = folder;
        }
        if (single == null) return;
        String name = single.getName();
        Charset ansi = Charset.forName("windows-1251");
        if (name.indexOf('\r') >= 0 || name.indexOf('\n') >= 0 || !ansi.newEncoder().canEncode(name)) return;
        File global = child(profiles, "global" + suffix + ".cfg");
        if (global == null) global = new File(profiles, "global" + suffix + ".cfg");
        if (global.length() > 1024 * 1024) throw new IOException("Profile selection file is too large");
        String before = global.isFile() ? new String(Files.readAllBytes(global.toPath()), StandardCharsets.ISO_8859_1) : "";
        String line = "setvar profile_name = " + new String(name.getBytes(ansi), StandardCharsets.ISO_8859_1);
        Matcher selection = Pattern.compile("(?m)^[ \\t]*setvar[ \\t]+profile_name[ \\t]*=[^\\r\\n]*").matcher(before);
        String newline = before.contains("\r\n") ? "\r\n" : "\n";
        String after = selection.find() ? selection.replaceAll(Matcher.quoteReplacement(line))
            : before + (before.isEmpty() || before.endsWith("\n") ? "" : newline) + line + newline;
        if (after.equals(before)) return;
        File part = File.createTempFile("profile-", ".cfg", profiles);
        try {
            Files.write(part.toPath(), after.getBytes(StandardCharsets.ISO_8859_1));
            Files.move(part.toPath(), global.toPath(), StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { part.delete(); }
    }

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

    /** Only marker checks: never hash multi-gigabyte archives on the launcher's UI thread. */
    static String conflict(File root, String edition, Map<String, File> folders) {
        if (root == null) return null;
        try {
            String path = root.getCanonicalPath();
            for (Map.Entry<String, File> entry : folders.entrySet()) {
                File other = entry.getValue();
                if (entry.getKey().equals(edition) || other == null ||
                    (!"toe".equals(edition) && !"toe".equals(entry.getKey()))) continue;
                String peer = other.getCanonicalPath();
                if (path.equals(peer) || path.startsWith(peer + File.separator) || peer.startsWith(path + File.separator))
                    return title(edition) + " / " + title(entry.getKey()) + ": " + path + " / " + peer;
            }
            if (!"toe".equals(edition) && child(root, "data/a2p1-data.pak") != null)
                return title(edition) + " / " + title("toe") + ": " + path;
            if ("toe".equals(edition) && (child(root, "data/p3c-data.pak") != null || child(root, "DataLS/p6-data.pak") != null))
                return title(edition) + " / " + title("vanilla") + ": " + path;
        } catch (IOException unreadable) { return unreadable.getMessage(); }
        return null;
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
