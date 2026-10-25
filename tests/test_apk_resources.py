"""Compile/link actual adaptive icon resources without packaging a game APK."""
import os
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET
import zipfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import SDK

ROOT = Path(__file__).resolve().parents[1]
AAPT = SDK / "build-tools/36.1.0/aapt2.exe"
ANDROID_JAR = SDK / "platforms/android-36/android.jar"
ANDROID = "{http://schemas.android.com/apk/res/android}"


class ApkResourcesTest(unittest.TestCase):
    def test_adaptive_and_themed_icon_references(self):
        app = ROOT / "android/app"
        manifest = ET.parse(app / "AndroidManifest.xml").getroot()
        application = manifest.find("application")
        self.assertEqual(application.get(ANDROID + "icon"), "@mipmap/ic_launcher")
        self.assertEqual(application.get(ANDROID + "roundIcon"), "@mipmap/ic_launcher")
        activities = {activity.get(ANDROID + "name"): activity for activity in application.findall("activity")}
        self.assertEqual(set(activities), {".Launcher", ".GameActivity"})
        game = activities[".GameActivity"]
        self.assertEqual(game.get(ANDROID + "windowSoftInputMode"), "adjustNothing")
        self.assertEqual(game.get(ANDROID + "exported"), "true")      # tools start it with am start -n

        def launcher_entries(activity):
            return [(filter_.find("action").get(ANDROID + "name"), filter_.find("category").get(ANDROID + "name"))
                    for filter_ in activity.findall("intent-filter")]
        main = ("android.intent.action.MAIN", "android.intent.category.LAUNCHER")
        self.assertEqual(launcher_entries(activities[".Launcher"]), [main])
        self.assertEqual(activities[".Launcher"].get(ANDROID + "exported"), "true")
        self.assertEqual(launcher_entries(game), [])
        services = [service.get(ANDROID + "name") for service in application.findall("service")]
        self.assertEqual(services, [".UnpackService", ".TextureService"])
        for service in application.findall("service"):
            self.assertEqual(service.get(ANDROID + "exported"), "false", service.get(ANDROID + "name"))
        # Foreground services; the texture converter holds a partial wake lock while it runs.
        permissions = {permission.get(ANDROID + "name") for permission in manifest.findall("uses-permission")}
        self.assertLessEqual({"android.permission.FOREGROUND_SERVICE", "android.permission.WAKE_LOCK"}, permissions)
        package = manifest.get("package").replace(".", "/")
        for component in (".Launcher", ".GameActivity", ".UnpackService", ".TextureService"):
            self.assertTrue((app / "src" / package / (component[1:] + ".java")).is_file(), component)
        for version in (26, 33):
            icon = ET.parse(app / f"res/mipmap-anydpi-v{version}/ic_launcher.xml").getroot()
            self.assertEqual(icon.tag, "adaptive-icon")
            self.assertEqual(icon.find("background").get(ANDROID + "drawable"), "@color/ic_launcher_background")
            self.assertEqual(icon.find("foreground").get(ANDROID + "drawable"), "@drawable/ic_launcher_foreground")
            if version == 33:
                self.assertEqual(icon.find("monochrome").get(ANDROID + "drawable"), "@drawable/ic_launcher_foreground")

    @unittest.skipUnless(AAPT.exists() and ANDROID_JAR.exists(), "Android SDK36 tools required")
    def test_actual_aapt_compile_link_and_manifest(self):
        out = ROOT / "build/apk-resource-check"
        out.mkdir(parents=True, exist_ok=True)
        resources, apk = out / "resources.zip", out / "resources-only.apk"
        for command in (
            [str(AAPT), "compile", "--dir", str(ROOT / "android/app/res"), "-o", str(resources)],
            [str(AAPT), "link", "-I", str(ANDROID_JAR), "--manifest", str(ROOT / "android/app/AndroidManifest.xml"),
             str(resources), "-o", str(apk)],
        ):
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with zipfile.ZipFile(apk) as archive:
            self.assertIn("resources.arsc", archive.namelist())
            self.assertTrue(any("ic_launcher_foreground" in name for name in archive.namelist()))
            self.assertNotIn("classes.dex", archive.namelist())
            self.assertFalse(any(name.startswith("lib/") for name in archive.namelist()))
        tree = subprocess.run([str(AAPT), "dump", "xmltree", "--file", "AndroidManifest.xml", str(apk)],
                              capture_output=True, text=True)
        self.assertEqual(tree.returncode, 0, tree.stdout + tree.stderr)
        self.assertIn("android:icon", tree.stdout)
        self.assertIn("android:roundIcon", tree.stdout)


if __name__ == "__main__":
    unittest.main()
