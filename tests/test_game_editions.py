"""Run actual edition metadata, discovery and runtime gating (import and cleanup: test_launcher_base.py)."""
import json
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET

from test_d3d_lifecycle import function
from test_touch_controls import JAVA, ROOT
from test_launcher_base import LAUNCHER, PLATFORM_JAR, javac, prepare

JAVA_SOURCE = ROOT / "android/app/src/org/homm5/port"

CHECK = r'''
package org.homm5.port;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.zip.*;

public class EditionCheck {
    static void file(Path root, String relative) throws Exception {
        Path path=root.resolve(relative); Files.createDirectories(path.getParent()); Files.write(path,new byte[]{1});
    }
    static File install(Path root, String... editions) throws Exception {
        for(String edition:editions) for(String path:Games.required(edition)) file(root,path);
        return root.toFile();
    }
    static void delete(File f) {
        if (f.isDirectory() && !Files.isSymbolicLink(f.toPath())) { File[] items = f.listFiles(); if (items != null) for (File i : items) delete(i); }
        f.delete();
    }
    public static void main(String[] args) throws Exception {
        if(args.length>0) {
            for(String row:args) {
                String[] v=row.split("\\|",-1); String id=v[0];
                assert Games.version(id).equals(v[1]); assert Games.library(id).equals(v[2]);
                assert Games.userdata(id).equals(v[3]); assert Games.images(id).equals("lifted"+v[4]);
                assert Games.overlay(id).equals("overlay"+v[4]); assert Games.required(id)[0].equals(v[5]+"/H5_Game.exe");
            }
            System.out.println("PASS actual Java metadata against config/editions.json"); return;
        }
        Path root=Files.createTempDirectory("homm5-editions-");
        try {
            File vanilla=install(root.resolve("common/Original"),"vanilla");
            File hof=install(root.resolve("common/Gold"),"vanilla","hof");
            File toe=install(root.resolve("common/Tribes"),"toe");
            assert Games.editions(vanilla).equals(Arrays.asList("vanilla"));
            assert Games.editions(hof).equals(Arrays.asList("vanilla","hof"));
            assert Games.editions(toe).equals(Arrays.asList("toe"));
            assert Games.discover(root.resolve("common").toFile()).size()==3;
            assert Games.discover(new File(hof,"dataa1")).equals(Arrays.asList(hof));
            assert Games.discover(root.resolve("absent").toFile()).isEmpty();
            assert !Games.installed(toe,"vanilla") && !Games.installed(vanilla,"toe");
            Path partial=root.resolve("partial"); file(partial,"bin/H5_Game.exe"); file(partial,"data/data.pak"); file(partial,"data/p3c-data.pak");
            assert Games.editions(partial.toFile()).isEmpty() : "Unknown versions must not become another game's ready tile";
            Path mixed=root.resolve("mixed");
            for(String name:Games.required("hof")) file(mixed,name.toUpperCase(Locale.ROOT));
            assert Games.installed(mixed.toFile(),"hof");
            assert Games.pathKey("toe").equals("game") && Games.userdata("toe").equals("userdata");
            assert Games.preferences("toe").equals("port_settings") && Games.marker("toe").equals("game-started");
            HashSet<String> userdata=new HashSet<>(),prefs=new HashSet<>(),libs=new HashSet<>(),markers=new HashSet<>();
            for(String id:Games.IDS) { userdata.add(Games.userdata(id)); prefs.add(Games.preferences(id)); libs.add(Games.library(id)); markers.add(Games.marker(id)); }
            assert userdata.size()==3 && prefs.size()==3 && libs.size()==3 && markers.size()==3;
            boolean rejected=false; try { Games.library("unknown"); } catch(IllegalArgumentException expected) { rejected=true; }
            assert rejected;
            try {
                Path boundary=Files.createDirectory(root.resolve("links"));
                Files.createSymbolicLink(boundary.resolve("outside"),hof.toPath());
                assert Games.discover(boundary.toFile()).isEmpty();
            } catch(IOException|UnsupportedOperationException|SecurityException unavailable) {
                System.out.println("Symlink boundary fixture unavailable: "+unavailable.getClass().getSimpleName());
            }
            System.out.println("PASS actual edition discovery: separate/combined installations, case, missing versions, isolated state");
        } finally { delete(root.toFile()); }
    }
}
'''


class GameEditionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = ROOT / "build/tests/game-editions"
        cls.out.mkdir(parents=True, exist_ok=True)
        harness = cls.out / "EditionCheck.java"
        harness.write_text(CHECK, encoding="utf-8")
        sources = [JAVA_SOURCE / (name + ".java") for name in ("Games",)]
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(cls.out), *map(str, sources), str(harness)], check=True)

    def test_actual_discovery_and_isolated_state(self):
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(self.out), "org.homm5.port.EditionCheck"], check=True)

    def test_actual_metadata_matches_build(self):
        editions = json.loads((ROOT / "config/editions.json").read_text(encoding="utf-8"))
        rows = ["|".join([id, row["version"], row["library"], row["userdata"], row["assets_suffix"], row["bin"]]) for id, row in editions.items()]
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(self.out), "org.homm5.port.EditionCheck", *rows], check=True)

    def test_process_and_profile_isolation(self):
        android = "{http://schemas.android.com/apk/res/android}"
        app = ET.parse(ROOT / "android/app/AndroidManifest.xml").getroot().find("application")
        for edition, name in [("vanilla", ".VanillaGameActivity"), ("hof", ".HofGameActivity")]:
            activity = next(a for a in app.findall("activity") if a.get(android + "name") == name)
            self.assertEqual(activity.get(android + "process"), ":" + edition)
            self.assertEqual(activity.get(android + "taskAffinity"), "org.homm5.port." + edition)
        source = (JAVA_SOURCE / "GameActivity.java").read_text(encoding="utf-8")
        self.assertNotIn('static { System.loadLibrary("homm5"); }', source)
        self.assertIn("NativeLibrary.load(this, Games.library(gameEdition()))", source)
        for path in ("preferences", "userdata", "cache"):
            self.assertIn("Games." + path + "(gameEdition())", source)

    def test_actual_runtime_ready_requires_matching_library_images_and_overlay(self):
        source = (JAVA_SOURCE / "Assets.java").read_text(encoding="utf-8")
        methods = "\n".join(function(source, signature) for signature in (
            "static boolean carriesImages(Context c, String edition)",
            "private static boolean carries(Context c, String path)",
            "static boolean runtimeAvailable("))
        check = r'''
package org.homm5.port;
import java.io.*;
import java.nio.file.*;
import java.util.*;
public class RuntimeCheck {
    static class NativeLibrary {
        static boolean available(Context c,String library) {
            return c.files.contains("native/"+library) || new File(c.info.nativeLibraryDir,System.mapLibraryName(library)).isFile();
        }
    }
    static class ApplicationInfo { String nativeLibraryDir; }
    static class Context {
        ApplicationInfo info=new ApplicationInfo(); Set<String> files=new HashSet<>();
        ApplicationInfo getApplicationInfo() { return info; }
        Context getAssets() { return this; }
        InputStream open(String path) throws IOException {
            if(!files.contains(path)) throw new FileNotFoundException(path);
            return new ByteArrayInputStream(new byte[]{1});
        }
    }
    /* ACTUAL */
    public static void main(String[] args) throws Exception {
        File base=Files.createTempDirectory("homm5-ready-").toFile();
        try {
            Context c=new Context(); c.info.nativeLibraryDir=base.getPath();
            for(String id:Games.IDS) {
                assert !runtimeAvailable(c,base,id);
                c.files.add(Games.images(id)+"/index.txt"); c.files.add(Games.overlay(id)+"/index.txt");
                assert !runtimeAvailable(c,base,id) : "Assets alone must not make a game ready";
                c.files.add("native/"+Games.library(id)); assert runtimeAvailable(c,base,id);
                c.files.remove("native/"+Games.library(id));
                File library=new File(base,System.mapLibraryName(Games.library(id))); assert library.createNewFile();
                assert runtimeAvailable(c,base,id);
                c.files.remove(Games.overlay(id)+"/index.txt");
                assert !runtimeAvailable(c,base,id) : "A matching patched overlay is mandatory";
                c.files.clear(); assert !runtimeAvailable(c,base,id);
                assert library.delete();
            }
            File image=new File(base,"lifted/H5_Game.exe"); assert image.getParentFile().mkdirs(); assert image.createNewFile();
            File library=new File(base,System.mapLibraryName(Games.library("toe"))); assert library.createNewFile();
            assert runtimeAvailable(c,base,"toe") : "Keep the existing ToE development deployment";
            assert !runtimeAvailable(c,base,"vanilla") && !runtimeAvailable(c,base,"hof");
            System.out.println("PASS actual readiness: matching library, images and overlay; ToE-only legacy fallback");
        } finally { delete(base); }
    }
    static void delete(File f) {
        if (f.isDirectory()) { File[] items = f.listFiles(); if (items != null) for (File i : items) delete(i); }
        f.delete();
    }
}
'''
        harness = self.out / "RuntimeCheck.java"
        harness.write_text(check.replace("/* ACTUAL */", methods), encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-cp", str(self.out), "-d", str(self.out), str(harness)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(self.out), "org.homm5.port.RuntimeCheck"], check=True)

    @unittest.skipUnless(LAUNCHER is not None and PLATFORM_JAR.is_file(), "the launcher base and android-37.0 are required")
    def test_production_java_callers_compile(self):
        prepared = prepare(self.out / "launcher")
        javac(self.out / "android", [*sorted(JAVA_SOURCE.glob("*.java")), *map(Path, prepared["sources"])])


if __name__ == "__main__":
    unittest.main()
