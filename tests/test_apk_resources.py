"""Compile/link actual adaptive icon resources and the manifest the launcher base expands, without
packaging a game APK."""
from pathlib import Path
import subprocess
import unittest
import xml.etree.ElementTree as ET
import zipfile
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import SDK

from test_launcher_base import LAUNCHER, PLATFORM_JAR, prepare

ROOT = Path(__file__).resolve().parents[1]
AAPT = SDK / "build-tools/36.1.0/aapt2.exe"
ANDROID = "{http://schemas.android.com/apk/res/android}"


class ApkResourcesTest(unittest.TestCase):
    def test_adaptive_and_themed_icon_references(self):
        app = ROOT / "android/app"
        text = (app / "AndroidManifest.xml").read_text(encoding="utf-8")
        manifest = ET.fromstring(text)
        sdk = manifest.find("uses-sdk")
        self.assertEqual((sdk.get(ANDROID + "minSdkVersion"), sdk.get(ANDROID + "targetSdkVersion")), ("26", "37"))
        for marker in ("<!-- launcher:manifest -->", "<!-- launcher:application -->"):
            self.assertEqual(text.count(marker), 1, marker)
        application = manifest.find("application")
        self.assertEqual(application.get(ANDROID + "icon"), "@mipmap/ic_launcher")
        self.assertEqual(application.get(ANDROID + "roundIcon"), "@mipmap/ic_launcher")
        self.assertEqual(application.get(ANDROID + "appCategory"), "game")   # Android 16 keeps a game's orientation on tablets
        self.assertEqual(application.get(ANDROID + "requestLegacyExternalStorage"), "true")   # Android 10
        activities = {activity.get(ANDROID + "name"): activity for activity in application.findall("activity")}
        self.assertEqual(set(activities), {".GameActivity", ".VanillaGameActivity", ".HofGameActivity"})
        game = activities[".GameActivity"]
        self.assertEqual(game.get(ANDROID + "windowSoftInputMode"), "adjustNothing")
        self.assertEqual(game.get(ANDROID + "exported"), "true")      # tools start it with am start -n
        for activity in activities.values():
            self.assertEqual(activity.findall("intent-filter"), [])   # the home-screen entry is the launcher base's
            self.assertEqual(activity.get(ANDROID + "launchMode"), "singleTask")
        self.assertEqual(application.findall("service"), [])          # the base declares its own work service
        permissions = {permission.get(ANDROID + "name"): permission.get(ANDROID + "maxSdkVersion")
                       for permission in manifest.findall("uses-permission")}
        self.assertLessEqual({"android.permission.FOREGROUND_SERVICE", "android.permission.WAKE_LOCK",
                              "android.permission.CHANGE_WIFI_MULTICAST_STATE"}, set(permissions))
        self.assertEqual(permissions["android.permission.WRITE_EXTERNAL_STORAGE"], "29")
        package = manifest.get("package").replace(".", "/")
        for component in (".GameActivity", ".VanillaGameActivity", ".HofGameActivity", ".LauncherHooks", ".TexconvBackend"):
            self.assertTrue((app / "src" / package / (component[1:] + ".java")).is_file(), component)
        for gone in ("Launcher", "UnpackService", "TextureService", "RendererProbe", "Unpacker", "Zip", "Deflate64",
                     "GameCleanup", "Renderers", "RendererPolicy"):
            self.assertFalse((app / "src" / package / (gone + ".java")).exists(), gone + " is the launcher base's now")
        for version in (26, 33):
            icon = ET.parse(app / f"res/mipmap-anydpi-v{version}/ic_launcher.xml").getroot()
            self.assertEqual(icon.tag, "adaptive-icon")
            self.assertEqual(icon.find("background").get(ANDROID + "drawable"), "@color/ic_launcher_background")
            self.assertEqual(icon.find("foreground").get(ANDROID + "drawable"), "@drawable/ic_launcher_foreground")
            if version == 33:
                self.assertEqual(icon.find("monochrome").get(ANDROID + "drawable"), "@drawable/ic_launcher_foreground")

    @unittest.skipUnless(AAPT.exists() and PLATFORM_JAR.exists() and LAUNCHER is not None,
                         "aapt2, android-37.0 and the launcher base required")
    def test_actual_aapt_compile_link_and_manifest(self):
        out = ROOT / "build/apk-resource-check"
        out.mkdir(parents=True, exist_ok=True)
        prepared = prepare(out / "launcher")
        resources, apk = out / "resources.zip", out / "resources-only.apk"
        for command in (
            [str(AAPT), "compile", "--dir", str(ROOT / "android/app/res"), "-o", str(resources)],
            [str(AAPT), "link", "-I", str(PLATFORM_JAR), "--manifest", prepared["manifest"], str(resources), "-o", str(apk)],
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
        self.assertIn("org.homm5.port.launcher.LauncherActivity", tree.stdout)
        self.assertIn("targetSdkVersion(0x01010270)=37", tree.stdout)


if __name__ == "__main__":
    unittest.main()
