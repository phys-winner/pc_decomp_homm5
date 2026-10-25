"""Resolve the build toolchain without any account-specific paths."""
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools/android_tools.py"


class AndroidTools(unittest.TestCase):
    def test_sdk_precedence_and_explicit_ndk_and_jdk(self):
        settings = {"ANDROID_SDK": "sdk-first", "ANDROID_HOME": "sdk-second",
                    "ANDROID_SDK_ROOT": "sdk-third", "ANDROID_NDK": "ndk-custom",
                    "JAVA_HOME": "jdk-custom"}
        with patch.dict(os.environ, settings, clear=True):
            tools = runpy.run_path(str(TOOLS))
            self.assertEqual(tools["SDK"], Path("sdk-first"))
            self.assertEqual(tools["CLANG"], Path("ndk-custom/toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"))
            self.assertEqual(tools["JAVA_HOME"], Path("jdk-custom"))
            del os.environ["ANDROID_SDK"]
            self.assertEqual(runpy.run_path(str(TOOLS))["SDK"], Path("sdk-second"))
            del os.environ["ANDROID_HOME"]
            self.assertEqual(runpy.run_path(str(TOOLS))["SDK"], Path("sdk-third"))

    def test_defaults_follow_current_home_and_pinned_ndk(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(Path, "home", return_value=Path("test-account")):
            tools = runpy.run_path(str(TOOLS))
        sdk = Path("test-account/AppData/Local/Android/Sdk")
        self.assertEqual(tools["SDK"], sdk)
        self.assertEqual(tools["NDK"], sdk / "ndk/27.2.12479018")
        self.assertEqual(tools["ANDROID_JAR"], sdk / "platforms/android-36/android.jar")


if __name__ == "__main__":
    unittest.main()
