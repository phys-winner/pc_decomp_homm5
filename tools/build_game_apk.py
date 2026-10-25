"""Package the ARM64 game library into an APK (no Gradle) and optionally install it.

    python tools/build_game_apk.py [--install] [--serial SERIAL]
The library comes from tools/build_android.py --shared; game data, the PE
images and the writable profile live under /sdcard/HeroesV on the device.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from android_tools import SDK, TOOLS, ANDROID_JAR, JAVA_HOME, ADB

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/android-game"
LICENSE_FILES = {
    "GPL-3.0.txt": "LICENSE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
    "pcrecomp.txt": "reference/pcrecomp/LICENSE",
    "mojoshader.txt": "reference/mojoshader/LICENSE.txt",
    "astcenc.txt": "reference/astcenc/LICENSE.txt",
    "etcpak.txt": "reference/etcpak/LICENSE.txt",
}


def write_index(folder, files):
    """index.txt: "path size sha256" a line; Assets.java copies by it once per APK."""
    lines = []
    for relative in sorted(files):
        data = (folder / relative).read_bytes()
        lines.append(f"{relative} {len(data)} {hashlib.sha256(data).hexdigest()}")
    (folder / "index.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def stage_assets(folder):
    """assets/lifted: the PE images the lifted code runs on (generated/input);
    assets/overlay: the port's files shadowing the installation for reading;
    assets/overlay-intro: the empty intro playlist, used when the intro is skipped."""
    sys.path.insert(0, str(ROOT / "tools"))
    from port_ui import build_port_ui_override
    from town_music import build_town_music_override
    licenses = folder / "licenses"
    licenses.mkdir(parents=True)
    for name, relative in LICENSE_FILES.items():
        shutil.copy2(ROOT / relative, licenses / name)
    lifted = folder / "lifted"
    lifted.mkdir(parents=True)
    modules = json.loads((ROOT / "config/modules.json").read_text(encoding="utf-8"))
    for row in modules:
        shutil.copy2(ROOT / "generated/input" / row["file"], lifted / row["file"])
    write_index(lifted, [row["file"] for row in modules])
    overlay = folder / "overlay"
    copies = {
        "profiles/autoexec_a2.cfg": ROOT / "config/profiles/autoexec_a2.cfg",
        "profiles/default_profile/user_a2.cfg": ROOT / "config/profiles/default_profile/user_a2.cfg",
    }
    music, _ = build_town_music_override(ROOT)
    ui, _ = build_port_ui_override(ROOT)
    copies["data/" + music.name] = music
    copies["data/" + ui.name] = ui
    for relative, source in copies.items():
        (overlay / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, overlay / relative)
    write_index(overlay, copies)
    (folder / "overlay-intro").mkdir()
    shutil.copy2(ROOT / "config/video/intro_a1.xml", folder / "overlay-intro/intro_a1.xml")
    return folder


def run(*args, **kwargs):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    if result.returncode:
        print(result.stdout[-3000:], result.stderr[-3000:])
        raise SystemExit(f"{Path(str(args[0])).name} failed ({result.returncode})")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--serial", default=os.environ.get("HOMM5_SERIAL") or os.environ.get("ANDROID_SERIAL"))
    parser.add_argument("--skip-native", action="store_true")
    parser.add_argument("--global-regs", action="store_true", help="build_android.py upstream mode (see there)")
    parser.add_argument("--volatile-memory", action="store_true", help="build_android.py upstream mode (see there)")
    pgo = parser.add_mutually_exclusive_group()
    pgo.add_argument("--pgo-generate", action="store_true", help="package the instrumented arm64-pgogen library")
    pgo.add_argument("--pgo-use", metavar="PROFDATA", help="pass the merged profile to build_android.py")
    pgo.add_argument("--no-pgo", action="store_true", help="build without an existing default profile")
    parser.add_argument("--thinlto", action="store_true", help="package the separate ThinLTO library")
    parser.add_argument("--thinlto-jobs", type=int, default=None, metavar="N",
                        help="pass the ThinLTO backend worker limit to build_android.py")
    parser.add_argument("--protocol-check", action="store_true", help="build_android.py validation build (see there)")
    args = parser.parse_args()
    if args.thinlto_jobs is not None and (not args.thinlto or args.thinlto_jobs < 1):
        parser.error("--thinlto-jobs must be positive and requires --thinlto")
    if not os.environ.get("JAVA_HOME"):
        parser.error("set JAVA_HOME to a JDK installation")
    for tool in (TOOLS / "aapt2.exe", TOOLS / "d8.bat", TOOLS / "zipalign.exe",
                 TOOLS / "apksigner.bat", ANDROID_JAR, JAVA_HOME / "bin/javac.exe",
                 JAVA_HOME / "bin/keytool.exe"):
        if not tool.is_file():
            parser.error(f"missing build tool: {tool}; check ANDROID_HOME and JAVA_HOME")
    for row in json.loads((ROOT / "config/modules.json").read_text(encoding="utf-8")):
        report = ROOT / f"generated/{row['name']}-x86/report.json"
        if not report.exists() or json.loads(report.read_text()).get("status") != "GENERATED":
            raise SystemExit(f"Static generation is incomplete: {row['name']}")
    modes = [(flag, name) for flag, name, on in (("--global-regs", "globalregs", args.global_regs),
                                                 ("--volatile-memory", "volatilemem", args.volatile_memory),
                                                 ("--pgo-generate", "pgogen", args.pgo_generate),
                                                 ("--thinlto", "thinlto", args.thinlto),
                                                 ("--protocol-check", "check", args.protocol_check)) if on]
    pgo_flags = ["--pgo-use", args.pgo_use] if args.pgo_use is not None else ["--no-pgo"] if args.no_pgo else []
    lto_flags = ["--thinlto-jobs", str(args.thinlto_jobs)] if args.thinlto_jobs is not None else []
    if not args.skip_native:
        subprocess.run([sys.executable, str(ROOT / "tools/build_android.py"), "--shared", "--jobs", "12",
                        *(flag for flag, _ in modes), *pgo_flags, *lto_flags], check=True)
    library = ROOT / ("build/arm64-" + "-".join(name for _, name in modes) if modes else "build/arm64") / "libhomm5.so"
    if not library.is_file():
        raise SystemExit(f"Native library does not exist: {library}")
    # The launcher's texture converter (android/texconv) is its own small library.
    subprocess.run([sys.executable, str(ROOT / "tools/build_texconv.py")], check=True)
    texconv = ROOT / "build/arm64-texconv/libtexconv.so"
    if OUT.exists():
        OUT.resolve().relative_to(ROOT.resolve())
        shutil.rmtree(OUT)
    (OUT / "classes").mkdir(parents=True)
    (OUT / "dex").mkdir()
    assets = stage_assets(OUT / "assets")
    resources = ROOT / "android/app/res"
    compiled_resources = []
    if resources.is_dir():
        archive = OUT / "resources.zip"
        run(TOOLS / "aapt2.exe", "compile", "--dir", resources, "-o", archive)
        compiled_resources = [archive]
    run(TOOLS / "aapt2.exe", "link", "-I", ANDROID_JAR, "--manifest", ROOT / "android/app/AndroidManifest.xml",
        "-A", assets, *compiled_resources, "-o", OUT / "base.apk")
    sources = sorted((ROOT / "android/app/src").rglob("*.java"))
    run(JAVA_HOME / "bin/javac.exe", "--release", "8", "-encoding", "UTF-8", "-cp", ANDROID_JAR, "-d", OUT / "classes", *sources)
    classes = sorted((OUT / "classes").rglob("*.class"))
    run(TOOLS / "d8.bat", "--lib", ANDROID_JAR, "--min-api", "26", "--output", OUT / "dex", *classes, shell=False)
    unsigned = OUT / "unsigned.apk"
    shutil.copy(OUT / "base.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(OUT / "dex/classes.dex", "classes.dex")
        apk.write(library, "lib/arm64-v8a/libhomm5.so")
        apk.write(texconv, "lib/arm64-v8a/libtexconv.so")
    aligned = OUT / "aligned.apk"
    # -P 16: uncompressed native code on 16 KiB boundaries (Android 15+ 16 KiB page devices).
    run(TOOLS / "zipalign.exe", "-f", "-P", "16", "4", unsigned, aligned)
    keystore = ROOT / "build/android/debug.keystore"
    if not keystore.exists():
        keystore.parent.mkdir(parents=True, exist_ok=True)
        run(JAVA_HOME / "bin/keytool.exe", "-genkeypair", "-keystore", keystore, "-storepass", "android",
            "-keypass", "android", "-alias", "androiddebugkey", "-keyalg", "RSA", "-keysize", "2048",
            "-validity", "10000", "-dname", "CN=Heroes V Port")
    apk = OUT / "heroes-v.apk"
    run(TOOLS / "apksigner.bat", "sign", "--ks", keystore, "--ks-pass", "pass:android", "--key-pass", "pass:android",
        "--out", apk, aligned)
    print(f"APK: {apk} ({apk.stat().st_size / 1e6:.1f} MB)")
    if args.install:
        run(ADB, *(["-s", args.serial] if args.serial else []), "install", "-r", "-g", apk)
        print("installed")


if __name__ == "__main__":
    main()
