"""Package all three patched ARM64 engines into an APK and optionally install it.

    python tools/build_game_apk.py [--install] [--serial SERIAL]
The libraries come from tools/build_android.py --shared and travel as ARM64-filtered
XZ assets, unpacked once per build. Game data and profiles live under /sdcard/HeroesV.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile
from android_tools import SDK, TOOLS, ANDROID_JAR, JAVA_HOME, ADB, CLANG
from editions import EDITION_IDS, edition_spec, generated_root, module_manifest, build_root, override_files

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/android-game"
LICENSE_FILES = {
    "GPL-3.0.txt": "LICENSE",
    "THIRD_PARTY_NOTICES.md": "THIRD_PARTY_NOTICES.md",
    "pcrecomp.txt": "reference/pcrecomp/LICENSE",
    "mojoshader.txt": "reference/mojoshader/LICENSE.txt",
    "astcenc.txt": "reference/astcenc/LICENSE.txt",
    "etcpak.txt": "reference/etcpak/LICENSE.txt",
    "xz-embedded.txt": "reference/xz-embedded/COPYING",
}

CHUNK = 128 << 20


def xz_tool():
    for candidate in (os.environ.get("XZ"), shutil.which("xz"), r"C:\Program Files\Git\mingw64\bin\xz.exe"):
        if candidate and Path(candidate).is_file():
            version = run(candidate, "--robot", "--version").stdout
            if int(next(line.split("=")[1] for line in version.splitlines() if line.startswith("XZ_VERSION="))) >= 50040002:
                return str(candidate)
    raise SystemExit("XZ Utils 5.4+ is required (ARM64 filter); set XZ or install Git for Windows")


def compress_library(library):
    """Independent XZ streams: ARM64 BCJ and word-aligned LZMA literals."""
    data = library.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    cache = ROOT / "build/native-xz"
    cache.mkdir(parents=True, exist_ok=True)
    packed = cache / f"{library.name}.{digest}.{CHUNK >> 20}m-lp2.xz"
    table = packed.with_suffix(".sizes")
    if not (packed.is_file() and table.is_file()):
        tool = xz_tool()

        def pack(at):
            return subprocess.run([tool, "--stdout", "--arm64", f"--lzma2=preset=9e,dict={CHUNK},lc=0,lp=2,pb=2",
                                   "--check=crc32", "--threads=1"], input=data[at:at + CHUNK],
                                  capture_output=True, check=True).stdout

        # Each encoder can use ~1.5 GiB; bound workers independently of CPU count.
        with ThreadPoolExecutor(max_workers=2) as pool:
            streams = list(pool.map(pack, range(0, len(data), CHUNK)))
        part = packed.with_suffix(".part")
        part.write_bytes(b"".join(streams))
        part.replace(packed)
        table.write_text(",".join(str(len(s)) for s in streams), encoding="ascii")
    sizes = [int(size) for size in table.read_text(encoding="ascii").split(",")]
    if len(sizes) != (len(data) + CHUNK - 1) // CHUNK or min(sizes) <= 0 or sum(sizes) != packed.stat().st_size:
        raise ValueError("Invalid native XZ cache: " + str(packed))
    return packed, f"{library.name} {len(data)} {digest} {CHUNK} {','.join(map(str, sizes))}\n"


def build_unpacker():
    xz = ROOT / "reference/xz-embedded"
    output = ROOT / "build/native-xz/libhomm5xz.so"
    output.parent.mkdir(parents=True, exist_ok=True)
    run(CLANG, "--target=aarch64-linux-android26", "-O2", "-std=gnu11", "-fPIC", "-shared",
        "-Wall", "-Wextra", "-Werror", "-DXZ_DEC_ARM64", "-DXZ_DEC_SINGLE",
        "-I" + str(xz / "linux/include/linux"), "-I" + str(xz / "userspace"),
        ROOT / "android/unpack/unpack.c",
        *(xz / "linux/lib/xz" / name for name in ("xz_crc32.c", "xz_dec_stream.c", "xz_dec_lzma2.c", "xz_dec_bcj.c")),
        "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1", "-Wl,-s",
        "-pthread", "-landroid", "-o", output)
    return output


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
    from port_patches import validate_overlay
    from profile_defaults import bootstrap_profiles
    licenses = folder / "licenses"
    licenses.mkdir(parents=True)
    for name, relative in LICENSE_FILES.items():
        shutil.copy2(ROOT / relative, licenses / name)
    receipts = {}
    for edition in EDITION_IDS:
        spec = edition_spec(edition, ROOT)
        suffix = spec["assets_suffix"]
        lifted = folder / ("lifted" + suffix)
        lifted.mkdir(parents=True)
        modules = module_manifest(edition, ROOT)
        for row in modules:
            shutil.copy2(generated_root(edition, ROOT) / "input" / row["file"], lifted / row["file"])
        write_index(lifted, [row["file"] for row in modules])
        overlay = folder / ("overlay" + suffix)
        profile_suffix = spec["profile_suffix"]
        profiles = bootstrap_profiles(ROOT, edition)
        for relative, contents in profiles.items():
            target = overlay / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        music, _ = build_town_music_override(ROOT, edition=edition)
        ui, _ = build_port_ui_override(ROOT, edition=edition)
        copies = {}
        for archive in (music, ui):
            additions = override_files(edition, archive)
            if {name.casefold() for name in copies} & {name.casefold() for name in additions}:
                raise ValueError(edition + ": UI/music overrides collide")
            copies.update(additions)
        for relative, contents in copies.items():
            (overlay / relative).parent.mkdir(parents=True, exist_ok=True)
            (overlay / relative).write_bytes(contents)
        write_index(overlay, [*profiles, *copies])
        receipts[edition] = validate_overlay(edition, overlay, root=ROOT)
        intro = folder / ("overlay-intro" + suffix)
        intro.mkdir()
        shutil.copy2(ROOT / "config/video/intro_a1.xml", intro / ("intro.xml" if edition == "vanilla" else "intro_a1.xml"))
    return receipts


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
    pgo.add_argument("--pgo-use", metavar="PROFDATA", help="use this ToE profile; other engines use their own default profiles")
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
    from port_patches import validate_packaged_native
    for edition in EDITION_IDS:
        for row in module_manifest(edition, ROOT):
            report = generated_root(edition, ROOT) / f"{row['name']}-x86/report.json"
            if not report.exists() or json.loads(report.read_text()).get("status") != "GENERATED":
                raise SystemExit(f"Static generation is incomplete: {edition}/{row['name']}")
    modes = [(flag, name) for flag, name, on in (("--global-regs", "globalregs", args.global_regs),
                                                 ("--volatile-memory", "volatilemem", args.volatile_memory),
                                                 ("--pgo-generate", "pgogen", args.pgo_generate),
                                                 ("--thinlto", "thinlto", args.thinlto),
                                                 ("--protocol-check", "check", args.protocol_check)) if on]
    pgo_flags = ["--pgo-use", args.pgo_use] if args.pgo_use is not None else ["--no-pgo"] if args.no_pgo else []
    lto_flags = ["--thinlto-jobs", str(args.thinlto_jobs)] if args.thinlto_jobs is not None else []
    if not args.skip_native:
        for edition in EDITION_IDS:
            edition_pgo_flags = pgo_flags if edition == "toe" or args.pgo_use is None else []
            subprocess.run([sys.executable, str(ROOT / "tools/build_android.py"), "--shared", "--jobs", "12", "--edition", edition,
                            *(flag for flag, _ in modes), *edition_pgo_flags, *lto_flags], check=True)
    libraries, receipts = [], {}
    for edition in EDITION_IDS:
        library = build_root(edition, [name for _, name in modes], ROOT) / ("lib" + edition_spec(edition, ROOT)["library"] + ".so")
        if not library.is_file():
            raise SystemExit(f"Native library does not exist: {library}; all three patched engines are required")
        try:
            receipts[edition] = {"native": validate_packaged_native(edition, library, root=ROOT)}
        except (ValueError, RuntimeError, OSError) as failure:
            raise SystemExit(f"{edition}: mandatory native patches are incomplete: {failure}") from failure
        libraries.append(library)
    # The launcher's texture converter (android/texconv) is its own small library.
    subprocess.run([sys.executable, str(ROOT / "tools/build_texconv.py")], check=True)
    texconv = ROOT / "build/arm64-texconv/libtexconv.so"
    unpacker = build_unpacker()
    payloads = [compress_library(library) for library in libraries]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="apk-assets-", dir=OUT.parent) as temporary:
        staged = Path(temporary) / "assets"
        try:
            overlays = stage_assets(staged)
        except (ValueError, RuntimeError, OSError) as failure:
            raise SystemExit(f"Mandatory resource patches are incomplete: {failure}") from failure
        for edition, overlay in overlays.items():
            receipts[edition]["overlay"] = overlay
        (staged / "edition-patches.json").write_text(json.dumps(receipts, indent=2) + "\n", encoding="utf-8")
        if OUT.exists():
            OUT.resolve().relative_to(ROOT.resolve())
            shutil.rmtree(OUT)
        (OUT / "classes").mkdir(parents=True)
        (OUT / "dex").mkdir()
        shutil.move(staged, OUT / "assets")
    assets = OUT / "assets"
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
        for edition, library in zip(EDITION_IDS, libraries):
            try:
                if validate_packaged_native(edition, library, root=ROOT) != receipts[edition]["native"]:
                    raise ValueError("Native patch receipt changed during packaging")
            except (ValueError, RuntimeError, OSError) as failure:
                raise SystemExit(f"{edition}: native patches changed during packaging: {failure}") from failure
        for packed, row in payloads:
            apk.write(packed, "assets/native/" + row.split()[0] + ".xz", compress_type=zipfile.ZIP_STORED)
        apk.writestr("assets/native/index.txt", "".join(row for _, row in payloads))
        apk.write(unpacker, "lib/arm64-v8a/libhomm5xz.so")
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
