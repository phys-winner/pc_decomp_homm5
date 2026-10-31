"""Heroes V on the shared launcher base: android/port.json against the editions the port knows,
the manifest the base prepares, and the base's own import, discovery and cleanup run in Java on
real archives and folders with this port's specification."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
import zipfile

from test_touch_controls import JAVA, ROOT

sys.path.insert(0, str(ROOT / "tools"))
from android_tools import SDK  # noqa: E402

SPEC = ROOT / "android/port.json"
MANIFEST = ROOT / "android/app/AndroidManifest.xml"
APP = ROOT / "android/app/src/org/homm5/port"
PLATFORM_JAR = SDK / "platforms/android-37.0/android.jar"
AAPT = SDK / "build-tools/36.1.0/aapt2.exe"
ANDROID = "{http://schemas.android.com/apk/res/android}"
EDITIONS = ("toe", "hof", "vanilla")


def launcher_base():
    """As tools/build_game_apk.py finds it: PORT_LAUNCHER, android/launcher, ../launcher."""
    candidates = [Path(os.environ["PORT_LAUNCHER"])] if os.environ.get("PORT_LAUNCHER") else []
    candidates += [ROOT / "android/launcher", ROOT.parent / "launcher"]
    return next((path for path in candidates if (path / "tools/launcher.py").is_file()), None)


LAUNCHER = launcher_base()
if LAUNCHER is not None and str(LAUNCHER / "tools") not in sys.path:
    sys.path.insert(0, str(LAUNCHER / "tools"))
needs_base = unittest.skipUnless(LAUNCHER is not None and PLATFORM_JAR.is_file(), "the launcher base and android-37.0 are required")


def spec():
    return json.loads(SPEC.read_text(encoding="utf-8"))


def prepare(out):
    """The launcher base prepared as the APK build prepares it (sources, manifest, assets)."""
    import launcher
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    return launcher.prepare(SPEC, MANIFEST, out)


def javac(out, sources, classpath=()):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-Xlint:-options", "-encoding", "UTF-8",
                             "-cp", os.pathsep.join([str(PLATFORM_JAR), *map(str, classpath)]), "-d", str(out),
                             *map(str, sources)], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


def java(classes, main, *args, timeout=60):
    result = subprocess.run([str(JAVA / "java.exe"), "-ea", "-Dfile.encoding=UTF-8", "-Dstdout.encoding=UTF-8",
                             "-cp", os.pathsep.join([str(classes), str(PLATFORM_JAR)]), main, *map(str, args)],
                            capture_output=True, timeout=timeout)
    output = result.stdout.decode("utf-8", "replace") + result.stderr.decode("utf-8", "replace")
    if result.returncode:
        raise AssertionError(output)
    return output


def java_text(value):
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def distributions_java():
    """Java statements building the base's Spec.Distribution objects from android/port.json (the
    base reads it with org.json, which android.jar only stubs on the PC)."""
    lines = ["static java.util.List<Spec.Distribution> distributions() {",
             "  java.util.List<Spec.Distribution> all = new java.util.ArrayList<>();"]
    for d in spec()["distributions"]:
        lines += ["  { Spec.Distribution d = new Spec.Distribution();",
                  f"    d.id = {java_text(d['id'])}; d.activity = {java_text(d['activity'])}; d.version = {java_text(d.get('version', ''))};"]
        for p in d["parts"]:
            lines += ["    { Spec.Part p = new Spec.Part();",
                      f"      p.id = {java_text(p['id'])}; p.folder = {java_text(p.get('folder', ''))};",
                      f"      p.fixed = {str(p.get('fixed', False)).lower()}; p.mount = {str(p.get('mount', False)).lower()};"]
            for r in p["required"]:
                lines.append(f"      p.required.add({java_text(r)});")
            lines.append(f"      p.marker = {java_text(p.get('marker', p['required'][0]))};")
            for n in p.get("needed", []):
                lines.append(f"      p.needed.add(new Glob({java_text(n)}));")
            lines.append("      d.parts.add(p); }")
        lines.append("    all.add(d); }")
    lines += ["  return all;", "}"]
    categories = ["static java.util.List<Spec.Category> categories() {",
                  "  java.util.List<Spec.Category> all = new java.util.ArrayList<>();"]
    for c in spec()["cleanup"]["categories"]:
        categories += ["  { Spec.Category c = new Spec.Category();", f"    c.id = {java_text(c['id'])}; c.part = {java_text(c.get('part', ''))};"]
        for g in c["globs"]:
            categories.append(f"    c.globs.add(new Glob({java_text(g)}));")
        categories.append("    all.add(c); }")
    categories += ["  return all;", "}"]
    return "\n".join(lines + categories)


def games_required():
    """Games.required(edition) and Games.pathKey(edition), as the old launcher and the game check them."""
    out = ROOT / "build/tests/launcher-base/games"
    harness = out / "src/org/homm5/port/GamesDump.java"
    harness.parent.mkdir(parents=True, exist_ok=True)
    harness.write_text('''package org.homm5.port;
public class GamesDump {
    public static void main(String[] args) {
        for (String id : Games.IDS) System.out.println(id + "|" + Games.pathKey(id) + "|" + String.join(",", Games.required(id)));
    }
}
''', encoding="utf-8")
    javac(out / "classes", [APP / "Games.java", harness])
    rows = {}
    for line in java(out / "classes", "org.homm5.port.GamesDump").splitlines():
        if "|" in line:
            id, key, required = line.strip().split("|")
            rows[id] = (key, required.split(","))
    return rows


class LauncherSpecTest(unittest.TestCase):
    @needs_base
    def test_spec_is_valid_for_the_base(self):
        import launcher
        launcher.validate(spec())
        checked = subprocess.run([sys.executable, str(LAUNCHER / "tools/launcher.py"), "check", "--spec", str(SPEC)],
                                 capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)

    def test_distributions_are_the_three_editions_with_their_old_detection(self):
        data = spec()
        app = data["app"]
        self.assertEqual((app["storage"], app["github"], app["languages"]), ("HeroesV", "phys-winner/pc_decomp_homm5", ["en", "ru"]))
        self.assertTrue(app["autoLaunch"] and app["localNetwork"] and app["allFilesAccess"])
        self.assertEqual(app["processes"]["launcher"], ":launcher")
        activities = {"toe": "org.homm5.port.GameActivity", "hof": "org.homm5.port.HofGameActivity",
                      "vanilla": "org.homm5.port.VanillaGameActivity"}
        self.assertEqual([d["id"] for d in data["distributions"]], list(EDITIONS))
        games = games_required()
        for d in data["distributions"]:
            with self.subTest(edition=d["id"]):
                self.assertEqual(d["activity"], activities[d["id"]])
                self.assertEqual(d["renderers"], ["gles"])
                self.assertEqual(d["intro"], {"default": True})          # the old launcher skipped the videos by default
                part, = d["parts"]
                key, required = games[d["id"]]
                self.assertEqual(part["id"], "game")
                self.assertEqual(part["required"], required)             # exactly what Games.installed accepts
                self.assertEqual(part["marker"], required[0])
                self.assertEqual(part["folder"], "{storage}/" + key)     # tools/deploy.py's copies, the old fallback
                self.assertFalse(part.get("fixed", False))               # the game is told its folder (nativeStart)
                self.assertFalse(part.get("mount", False))               # the host has no stored-ZIP layer
                # The old unpacking's folders (Unpacker.NEEDED), for every edition alike.
                self.assertEqual(part["needed"], ["bin/", "bina1/", "data/", "dataa1/", "datals/", "music/", "video/", "profiles/",
                                                  "maps/", "usercampaigns/", "usermods/", "hwcursors/", "duelpresets/"])
        self.assertEqual([m["id"] for m in data["renderers"]["modes"]], ["gles"])   # DXVK/Turnip stay disabled
        options = {o["key"]: o for o in data["options"]}
        self.assertEqual(set(options), {"new_creature_framework", "lan_peers"})
        self.assertEqual((options["new_creature_framework"]["type"], options["new_creature_framework"]["default"]), ("bool", "0"))
        self.assertEqual((options["lan_peers"]["type"], options["lan_peers"]["default"]), ("text", ""))
        self.assertEqual(options["new_creature_framework"]["only"], ["toe"])   # MMH5.5's patch data exists for 3.1 only
        self.assertNotIn("only", options["lan_peers"])                         # every edition's LAN search
        for name in (app["hooks"], data["textures"]["backend"]):
            self.assertTrue((ROOT / "android/app/src" / (name.replace(".", "/") + ".java")).is_file(), name)

    @needs_base
    def test_prepared_manifest(self):
        prepared = prepare(ROOT / "build/tests/launcher-base/prepared")
        self.assertEqual(prepared["package"], "org.homm5.port.launcher")
        self.assertFalse(prepared["probe"], "OpenGL ES only: no Vulkan driver check")
        root = ET.parse(prepared["manifest"]).getroot()
        sdk = root.find("uses-sdk")
        self.assertEqual((sdk.get(ANDROID + "minSdkVersion"), sdk.get(ANDROID + "targetSdkVersion")), ("26", "37"))
        permissions = {p.get(ANDROID + "name"): p.get(ANDROID + "maxSdkVersion") for p in root.findall("uses-permission")}
        for name in ("READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE"):
            self.assertEqual(permissions["android.permission." + name], "29")    # Android 8-10
        for name in ("MANAGE_EXTERNAL_STORAGE", "ACCESS_LOCAL_NETWORK", "POST_NOTIFICATIONS", "FOREGROUND_SERVICE_DATA_SYNC",
                     "INTERNET", "CHANGE_WIFI_MULTICAST_STATE", "WAKE_LOCK"):
            self.assertIn("android.permission." + name, permissions)
        self.assertEqual(len(root.findall("uses-permission")), len(permissions), "no permission twice")
        application = root.find("application")
        self.assertEqual(application.get(ANDROID + "appCategory"), "game")
        self.assertEqual(application.get(ANDROID + "requestLegacyExternalStorage"), "true")   # Android 10
        entries = [a.get(ANDROID + "name") for a in application.findall("activity")
                   if any(c.get(ANDROID + "name") == "android.intent.category.LAUNCHER" for c in a.iter("category"))]
        self.assertEqual(entries, ["org.homm5.port.launcher.LauncherActivity"])
        activities = {a.get(ANDROID + "name"): a for a in application.findall("activity")}
        self.assertEqual(activities["org.homm5.port.launcher.LauncherActivity"].get(ANDROID + "process"), ":launcher")
        self.assertIsNone(activities[".GameActivity"].get(ANDROID + "process"))   # Tribes of the East: the main process
        for name, edition in ((".VanillaGameActivity", "vanilla"), (".HofGameActivity", "hof")):
            self.assertEqual(activities[name].get(ANDROID + "process"), ":" + edition)
            self.assertEqual(activities[name].get(ANDROID + "taskAffinity"), "org.homm5.port." + edition)
        services = {s.get(ANDROID + "name"): s.get(ANDROID + "process") for s in application.findall("service")}
        self.assertEqual(services, {"org.homm5.port.launcher.Work$WorkService": ":launcher"})   # no :probe
        assets = Path(prepared["assets"]) / "launcher"
        self.assertEqual(json.loads((assets / "port.json").read_text(encoding="utf-8")), spec())
        build = json.loads((assets / "build.json").read_text(encoding="utf-8"))
        self.assertEqual((build["versionName"], build["versionCode"]), (root.get(ANDROID + "versionName"), int(root.get(ANDROID + "versionCode"))))

    @needs_base
    @unittest.skipUnless(AAPT.is_file(), "aapt2 required")
    def test_aapt_links_the_prepared_manifest(self):
        out = ROOT / "build/tests/launcher-base/aapt"
        prepared = prepare(out / "prepared")
        resources, apk = out / "resources.zip", out / "base.apk"
        for command in ([str(AAPT), "compile", "--dir", str(ROOT / "android/app/res"), "-o", str(resources)],
                        [str(AAPT), "link", "-I", str(PLATFORM_JAR), "--manifest", prepared["manifest"], "-A", prepared["assets"],
                         str(resources), "-o", str(apk)]):
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with zipfile.ZipFile(apk) as archive:
            self.assertIn("assets/launcher/port.json", archive.namelist())

    @needs_base
    def test_game_and_base_sources_compile_together(self):
        prepared = prepare(ROOT / "build/tests/launcher-base/compile/prepared")
        javac(ROOT / "build/tests/launcher-base/compile/classes",
              sorted((ROOT / "android/app/src").rglob("*.java")) + [Path(p) for p in prepared["sources"]])


IMPORT = r'''
package org.homm5.port.launcher;
import java.io.*;
import java.util.*;

public class HeroesImportCheck {
    /* DISTRIBUTIONS */
    static Spec.Distribution d(String id) { for (Spec.Distribution x : distributions()) if (x.id.equals(id)) return x; throw new AssertionError(id); }
    static List<Spec.Distribution> all = distributions();
    static Spec.Distribution find(List<Spec.Distribution> list, String id) { for (Spec.Distribution x : list) if (x.id.equals(id)) return x; return null; }

    public static void main(String[] args) throws Exception {
        String mode = args[0];
        File work = new File(args[2]);
        if (mode.equals("toe")) {
            Zip zip = new Zip(new FileInputStream(args[1]).getChannel());
            List<Install.ArchivePart> plan = Install.plan(zip, all);
            assert plan.size() == 1 && plan.get(0).distribution.id.equals("toe") && plan.get(0).also.isEmpty() : plan.size();
            Install.ArchivePart toe = plan.get(0);
            assert toe.root.equals("heroes v/") : toe.root;
            assert !toe.paths.contains("Setup.exe") && !toe.paths.contains("Editor/tool.exe") : toe.paths;
            File target = new File(work, "game");
            Install.UnpackJob job = new Install.UnpackJob(null, zip, plan, Collections.singletonList(target));
            job.run();
            assert job.failure == null : job.failure;
            assert Install.present(toe.part, target);
            for (String path : toe.paths) {
                File f = new File(target, path);
                System.out.println(path + "\t" + f.length() + "\t" + f.lastModified());
            }
        } else if (mode.equals("gold")) {
            Zip zip = new Zip(new FileInputStream(args[1]).getChannel());
            List<Install.ArchivePart> plan = Install.plan(zip, all);
            assert plan.size() == 2 : "Tribes of the East, and one part for Hammers of Fate with the original game: " + plan.size();
            Install.ArchivePart toe = plan.get(0), gold = plan.get(1);
            assert toe.distribution.id.equals("toe") && toe.root.equals("games/tribes/") : toe.root;
            assert gold.distribution.id.equals("hof") && gold.also.size() == 1 && gold.also.get(0).distribution.id.equals("vanilla")
                : "Hammers of Fate is installed over the original game: one folder, unpacked once";
            assert gold.paths.contains("DataLS/p6-data.pak") && gold.paths.contains("bina1/H5_Game.exe") && !gold.paths.contains("manual.pdf");
            List<File> targets = Install.distinct(plan, Arrays.asList(new File(work, "game"), new File(work, "game-hof")));
            Install.UnpackJob job = new Install.UnpackJob(null, zip, plan, targets);
            job.run();
            assert job.failure == null : job.failure;
            assert Install.present(d("toe").parts.get(0), targets.get(0));
            assert Install.present(d("hof").parts.get(0), targets.get(1)) && Install.present(d("vanilla").parts.get(0), targets.get(1));
            assert !Install.present(d("vanilla").parts.get(0), targets.get(0)) && !Install.present(d("toe").parts.get(0), targets.get(1));
            System.out.println("PASS merged import");
        } else if (mode.equals("discover")) {
            File games = new File(args[1]), gold = new File(games, "Gold"), tribes = new File(games, "Tribes");
            List<Install.Found> found = Install.discover(all, new File(gold, "DataLS"));
            Map<String, File> at = new HashMap<>();
            for (Install.Found f : found) at.put(f.distribution.id, f.folder);
            assert at.size() == 2 && at.get("vanilla").equals(gold) && at.get("hof").equals(gold) : at;
            found = Install.discover(all, games);
            at.clear();
            for (Install.Found f : found) at.put(f.distribution.id, f.folder);
            assert at.size() == 3 && at.get("toe").equals(tribes) && at.get("hof").equals(gold) && at.get("vanilla").equals(gold) : at;
            assert Install.discover(all, new File(games, "Partial")).isEmpty() : "an unknown version is no edition's ready game";
            File mixed = new File(games, "Mixed");
            assert Install.present(d("hof").parts.get(0), mixed) : "case is ignored, as on Windows";
            System.out.println("PASS discovery");
        } else if (mode.equals("cleanup")) {
            File game = new File(args[1]);
            List<Spec.Category> categories = categories();
            Cleanup.Plan plan = Cleanup.scan(game, categories);
            Set<String> listed = new TreeSet<>();
            for (Cleanup.Entry e : plan.files) listed.add(e.file.getAbsolutePath().substring(game.getAbsolutePath().length() + 1).replace('\\', '/'));
            System.out.println("LISTED " + String.join(",", listed));
            Cleanup.Job job = new Cleanup.Job(null, plan);
            job.run();
            assert job.failure == null : job.failure;
            assert Install.present(d("toe").parts.get(0), game) : "the game still starts";
        }
    }
}
'''


class LauncherImportTest(unittest.TestCase):
    """The base's Install, Zip and Cleanup with Heroes V's port.json (what the old launcher's own
    Unpacker, Games.discover and GameCleanup did)."""

    @classmethod
    def setUpClass(cls):
        if LAUNCHER is None or not PLATFORM_JAR.is_file():
            raise unittest.SkipTest("the launcher base and android-37.0 are required")
        cls.out = ROOT / "build/tests/launcher-base/import"
        prepared = prepare(cls.out / "prepared")
        source = cls.out / "src/org/homm5/port/launcher/HeroesImportCheck.java"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(IMPORT.replace("/* DISTRIBUTIONS */", distributions_java()), encoding="utf-8")
        cls.classes = cls.out / "classes"
        if cls.classes.exists():
            shutil.rmtree(cls.classes)
        javac(cls.classes, [*map(Path, prepared["sources"]), source])

    @staticmethod
    def install(root, edition, upper=False):
        for path in {"toe": ["bin/H5_Game.exe", "data/data.pak", "data/a2p1-data.pak"],
                     "hof": ["bina1/H5_Game.exe", "data/data.pak", "dataa1/a1-data.pak", "dataa1/a1p1-data.pak"],
                     "vanilla": ["bin/H5_Game.exe", "data/data.pak", "data/p3c-data.pak", "DataLS/p6-data.pak"]}[edition]:
            target = Path(root) / (path.upper() if upper else path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 16)

    def test_cp866_names_archive_times_and_only_needed_folders(self):
        stamp = (2008, 10, 7, 13, 14, 16)
        files = {"Heroes V/bin/H5_Game.exe": b"MZ" + bytes(64), "Heroes V/data/data.pak": b"PK" + bytes(100),
                 "Heroes V/data/a2p1-data.pak": b"PK" + bytes(50), "Heroes V/Maps/Моя карта.h5m": b"map",
                 "Heroes V/UserMODs/Ёлка.h5u": b"mod", "Heroes V/Maps/─.txt": b"box",
                 "Heroes V/Setup.exe": b"installer", "Heroes V/Editor/tool.exe": b"editor"}
        original = zipfile.ZipInfo._encodeFilenameFlags

        def oem(info):   # Windows Explorer's way: OEM (CP866) names without the UTF-8 flag
            try:
                return info.filename.encode("ascii"), info.flag_bits
            except UnicodeEncodeError:
                return info.filename.encode("cp866"), info.flag_bits & ~0x800
        with tempfile.TemporaryDirectory() as work:
            archive = Path(work) / "game.zip"
            zipfile.ZipInfo._encodeFilenameFlags = oem
            try:
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                    for name, data in files.items():
                        info = zipfile.ZipInfo(name, date_time=stamp)
                        info.compress_type = zipfile.ZIP_DEFLATED
                        z.writestr(info, data)
            finally:
                zipfile.ZipInfo._encodeFilenameFlags = original
            rows = {}
            for line in java(self.classes, "org.homm5.port.launcher.HeroesImportCheck", "toe", archive, work).splitlines():
                if line.count("\t") == 2:
                    path, size, modified = line.split("\t")
                    rows[path] = (int(size), int(modified))
            self.assertIn("Maps/Моя карта.h5m", rows)
            self.assertIn("UserMODs/Ёлка.h5u", rows)
            self.assertIn("Maps/─.txt", rows)     # not a CP866 letter: read as CP437 (the same glyph)
            self.assertEqual(rows["Maps/Моя карта.h5m"][0], 3)
            expected = time.mktime(stamp + (0, 0, -1)) * 1000
            for path, (_, modified) in rows.items():
                self.assertLessEqual(abs(modified - expected), 2000, path)

    def test_hammers_of_fate_over_the_original_unpacks_once(self):
        with tempfile.TemporaryDirectory() as work:
            source = Path(work) / "source"
            self.install(source / "Games/Gold", "vanilla")
            self.install(source / "Games/Gold", "hof")
            (source / "Games/Gold/manual.pdf").write_bytes(b"pdf")
            self.install(source / "Games/Tribes", "toe")
            archive = Path(work) / "games.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                for path in sorted(p for p in source.rglob("*") if p.is_file()):
                    z.write(path, path.relative_to(source).as_posix())
            output = java(self.classes, "org.homm5.port.launcher.HeroesImportCheck", "gold", archive, Path(work) / "out")
            self.assertIn("PASS merged import", output)

    def test_folder_discovery_inner_parent_and_several_editions(self):
        with tempfile.TemporaryDirectory() as work:
            games = Path(work) / "Games"
            self.install(games / "Gold", "vanilla")
            self.install(games / "Gold", "hof")
            self.install(games / "Tribes", "toe")
            for path in ("bin/H5_Game.exe", "data/data.pak", "data/p3c-data.pak"):   # neither edition complete
                (games / "Partial" / path).parent.mkdir(parents=True, exist_ok=True)
                (games / "Partial" / path).write_bytes(b"x")
            self.install(games / "Mixed", "hof", upper=True)
            output = java(self.classes, "org.homm5.port.launcher.HeroesImportCheck", "discover", games, work)
            self.assertIn("PASS discovery", output)

    def test_cleanup_removes_what_the_old_cleanup_did_and_keeps_the_game(self):
        with tempfile.TemporaryDirectory() as work:
            game = Path(work) / "game"
            self.install(game, "toe")
            removable = ["Editor/tool.exe", "Editor Documentation/manual.chm", "bin/H5_MapEditor.exe", "unins000.exe",
                         "unins000.dat", "Manual.pdf", "Readme.txt", "goggame-1207658787.info", "webcache.zip",
                         "DirectX/dxsetup.exe", "__redist/vcredist_x86.exe", "gog.ico", "Heroes V Launcher.exe"]
            kept = ["bin/H5_Game.exe", "bin/granny2.dll", "data/data.pak", "Maps/custom.h5m", "Music/town.ogg",
                    "Video/intro.bik", "profiles/autoexec_a2.cfg", "UserMODs/mod.h5u", "HWCursors/arrow.ani",
                    "duelpresets/preset.xdb", "dataa1/a1-data.pak", "userdata/save.sav", "lifted/H5_Game.exe", ".nomedia",
                    "Maps/readme.txt", "data/notes.pdf"]
            for path in removable + kept:
                (game / path).parent.mkdir(parents=True, exist_ok=True)
                (game / path).write_bytes(b"content")
            output = java(self.classes, "org.homm5.port.launcher.HeroesImportCheck", "cleanup", game, work)
            listed = set(next(line for line in output.splitlines() if line.startswith("LISTED "))[7:].split(","))
            self.assertEqual(listed, set(removable))
            for path in kept:
                self.assertTrue((game / path).is_file(), path)
            for path in removable:
                self.assertFalse((game / path).exists(), path)


if __name__ == "__main__":
    unittest.main()
