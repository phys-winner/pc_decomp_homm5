"""Windows Android toolchain locations, shared by builders and native checks."""
import os
from pathlib import Path

SDK = Path(os.environ.get("ANDROID_SDK") or os.environ.get("ANDROID_HOME") or
           os.environ.get("ANDROID_SDK_ROOT") or Path.home() / "AppData/Local/Android/Sdk")
NDK = Path(os.environ.get("ANDROID_NDK") or SDK / "ndk/27.2.12479018")
TOOLCHAIN = NDK / "toolchains/llvm/prebuilt/windows-x86_64"
CLANG = TOOLCHAIN / "bin/clang.exe"
TOOLS = SDK / "build-tools/36.1.0"
ANDROID_JAR = SDK / "platforms/android-36/android.jar"
JAVA_HOME = Path(os.environ.get("JAVA_HOME", ""))
ADB = SDK / "platform-tools/adb.exe"
