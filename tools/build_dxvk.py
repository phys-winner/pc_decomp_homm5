"""Stage the DXVK renderer of Tribes of the East: import the pinned runtime and build its bridge.

    python -X utf8 tools/build_dxvk.py [--ut3 DIR] [--dxvk-library SO] [--turnip-runtime DIR] [--dxvk-headers DIR]

Nothing is downloaded or rebuilt from DXVK sources. The game-agnostic binaries the sibling
ut3 port built and verified on devices are reused: DXVK Native 2.4.1 D3D9 with its Android WSI
(libdxvk_d3d9.so), adrenotools with its hooks, and the Mesa Turnip driver; libc++_shared.so
comes from the NDK. Each must match its pin in dependencies.json ("dxvk", "adrenotools",
"turnip", "libcxx_shared"); DXVK Native's d3d9/windows headers are imported into
reference/dxvk (private) the same way. Then the committed bridge tables are checked against
those headers (tools/generate_dxvk_bridge.py) and android/dxvk/bridge.cpp + probe.cpp are
linked into libh5dxvk.so.

Outputs: build/dxvk/runtime/*.so, named as they are packaged under lib/arm64-v8a;
build/dxvk/licenses/; build/dxvk/build-receipt.json, which tools/build_game_apk.py checks
against the current bridge sources before it packages them. Changing the DXVK DSO itself means
rebuilding it with the ut3 port's tools/build_dxvk.py and updating the pins here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from android_tools import TOOLCHAIN

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/dxvk"
HEADERS = ROOT / "reference/dxvk"
API = 30   # DXVK modes need Android 11 (RendererPolicy.java): adrenotools' and the surface lifecycle's level
TARGET = f"aarch64-linux-android{API}"
BRIDGE_SOURCES = ("android/dxvk/bridge.cpp", "android/dxvk/probe.cpp")
# Everything the bridge is built from or must agree with; the APK builder refuses a stale receipt.
RECEIPT_SOURCES = (*BRIDGE_SOURCES, "android/dxvk/bridge_abi.h", "android/dxvk/turnip.h",
                   "android/dxvk/vulkan_requirements.h", "android/dxvk/bridge_metadata.h",
                   "android/dxvk/bridge_dispatch.h", "android/dxvk/bridge_special_names.h",
                   "android/host/dxvk_methods.h", "tools/build_dxvk.py", "tools/generate_dxvk_bridge.py")
TURNIP_DRIVER = {"libh5turnip.so": "libut3_turnip.so"}   # packaged name: name in the ut3 runtime
LICENSES = {   # packaged name (assets/licenses): pinned source
    "dxvk.txt": ("dxvk", "LICENSE"),
    "mingw-w64-directx-headers.txt": ("dxvk", "include/native/directx/COPYING.MinGW-w64.txt"),
    "adrenotools.txt": ("adrenotools", "adrenotools.BSD-2-Clause.txt"),
    "linkernsbypass.txt": ("adrenotools", "linkernsbypass.BSD-2-Clause.txt"),
    "turnip-mesa.txt": ("turnip", "Turnip-LICENSE-NOTE.txt"),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sha(path):
    """LF-normalised, as the patch contracts pin sources (Git may check them out with CRLF)."""
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def pins():
    data = json.loads((ROOT / "dependencies.json").read_text(encoding="utf-8"))
    return {name: data[name] for name in ("dxvk", "adrenotools", "turnip", "libcxx_shared")}


def check_elf(path):
    """An AArch64 shared object whose loadable segments allow 16 KiB pages (Android 15+ devices)."""
    data = Path(path).read_bytes()
    if data[:5] != b"\x7fELF\x02" or struct.unpack_from("<HH", data, 16) != (3, 183):
        raise ValueError(f"{path.name}: not an AArch64 ELF shared object")
    table, entry, count = struct.unpack_from("<Q", data, 32)[0], struct.unpack_from("<H", data, 54)[0], struct.unpack_from("<H", data, 56)[0]
    for index in range(count):
        at = table + index * entry
        if struct.unpack_from("<I", data, at)[0] == 1 and struct.unpack_from("<Q", data, at + 48)[0] < 16384:
            raise ValueError(f"{path.name}: PT_LOAD alignment below 16 KiB")


def verified(source, expected, what):
    source = Path(source)
    if not source.is_file():
        raise SystemExit(f"{what}: {source} is missing")
    if sha(source) != expected:
        raise SystemExit(f"{what}: {source} does not match its pin in dependencies.json")
    return source


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    data = Path(source).read_bytes()
    if not target.is_file() or target.read_bytes() != data:
        target.write_bytes(data)
    return target


def import_headers(pinned, sources):
    """DXVK Native's d3d9/windows headers and license into reference/dxvk (verified, private)."""
    for directory in sources:
        if directory and all((Path(directory) / name).is_file() and sha(Path(directory) / name) == digest
                             for name, digest in pinned.items()):
            for name in pinned:
                if Path(directory).resolve() != HEADERS.resolve():
                    copy(Path(directory) / name, HEADERS / name)
            return
    raise SystemExit("DXVK Native headers matching dependencies.json were not found in: " +
                     ", ".join(str(d) for d in sources if d))


def compile_bridge(runtime):
    clang = TOOLCHAIN / "bin/clang++.exe"
    if not clang.is_file():
        raise SystemExit(f"NDK clang++ is missing: {clang}")
    objects = OUT / "obj"
    objects.mkdir(parents=True, exist_ok=True)
    flags = ["--target=" + TARGET, "-std=c++17", "-O2", "-fPIC", "-fvisibility=hidden", "-fvisibility-inlines-hidden",
             "-Wall", "-Wextra", "-Werror", "-Wno-missing-field-initializers", "-Wno-unused-parameter",
             "-ffile-prefix-map=" + str(ROOT) + "=.",
             "-I" + str(HEADERS / "include/native/windows"), "-I" + str(HEADERS / "include/native/directx"),
             "-I" + str(ROOT / "android/dxvk")]
    built = []
    for relative in BRIDGE_SOURCES:
        obj = objects / (Path(relative).stem + ".o")
        run([clang, *flags, "-c", ROOT / relative, "-o", obj])
        built.append(obj)
    library = runtime / "libh5dxvk.so"
    run([clang, "--target=" + TARGET, "-shared", "-fuse-ld=lld", *built, "-o", library, "-Wl,--no-undefined",
         "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1", "-Wl,-s", "-landroid", "-ldl", "-llog"])
    return library


def run(args):
    print(subprocess.list2cmdline([str(a) for a in args]), flush=True)
    subprocess.run([str(a) for a in args], check=True)


def sibling_ut3():
    """E:/static_recompilation/ut3 beside this checkout (also from a worktree below it)."""
    for parent in ROOT.parents:
        if (parent / "ut3/build/dxvk").is_dir():
            return parent / "ut3"
    return ROOT.parent / "ut3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ut3", type=Path, default=sibling_ut3(),
                        help="sibling ut3 checkout whose build/dxvk, build/turnip-runtime and reference/dxvk are reused")
    parser.add_argument("--dxvk-library", type=Path, help="libdxvk_d3d9.so (default: <ut3>/build/dxvk)")
    parser.add_argument("--turnip-runtime", type=Path, help="adrenotools/Turnip runtime folder (default: <ut3>/build/turnip-runtime/runtime)")
    parser.add_argument("--dxvk-headers", type=Path, help="DXVK source tree with include/native (default: reference/dxvk, then <ut3>/reference/dxvk)")
    args = parser.parse_args()
    pinned = pins()
    import_headers(pinned["dxvk"]["headers"], (args.dxvk_headers, HEADERS, args.ut3 / "reference/dxvk"))
    sys.path.insert(0, str(ROOT / "tools"))
    import generate_dxvk_bridge
    generated, _ = generate_dxvk_bridge.outputs(HEADERS / "include/native/directx/d3d9.h")
    stale = [name for name, data in generated.items()
             if not (ROOT / name).is_file() or (ROOT / name).read_bytes().replace(b"\r\n", b"\n") != data]
    if stale:
        raise SystemExit("Committed DXVK bridge tables differ from the pinned headers; run tools/generate_dxvk_bridge.py: " + ", ".join(stale))

    runtime, licenses = OUT / "runtime", OUT / "licenses"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    turnip_dir = args.turnip_runtime or args.ut3 / "build/turnip-runtime/runtime"
    sources = {"libdxvk_d3d9.so": (args.dxvk_library or args.ut3 / "build/dxvk/libdxvk_d3d9.so", pinned["dxvk"]["runtime"]["libdxvk_d3d9.so"]),
               "libc++_shared.so": (TOOLCHAIN / "sysroot/usr/lib/aarch64-linux-android/libc++_shared.so",
                                    pinned["libcxx_shared"]["runtime"]["libc++_shared.so"])}
    for name, digest in pinned["adrenotools"]["runtime"].items():
        sources[name] = (turnip_dir / name, digest)
    for name, original in TURNIP_DRIVER.items():
        sources[name] = (turnip_dir / original, pinned["turnip"]["runtime"][name])
    for name, (source, digest) in sources.items():
        check_elf(copy(verified(source, digest, name), runtime / name))
    licenses.mkdir(parents=True, exist_ok=True)
    for name, (component, relative) in LICENSES.items():
        source = HEADERS / relative if component == "dxvk" else turnip_dir / "licenses" / relative
        digest = pinned[component]["headers" if component == "dxvk" else "licenses"][relative]
        copy(verified(source, digest, name), licenses / name)

    library = compile_bridge(runtime)
    check_elf(library)
    names = sorted(p.name for p in runtime.iterdir())
    receipt = {
        "target": TARGET, "ndk_clang_sha256": sha(TOOLCHAIN / "bin/clang++.exe"),
        "sources": {relative: source_sha(ROOT / relative) for relative in RECEIPT_SOURCES},
        "pins_sha256": hashlib.sha256(json.dumps(pinned, sort_keys=True).encode()).hexdigest(),
        "runtime": [{"name": name, "bytes": (runtime / name).stat().st_size, "sha256": sha(runtime / name)} for name in names],
        "licenses": [{"name": name, "sha256": sha(licenses / name)} for name in sorted(LICENSES)],
        "reused_from": "ut3 port: DXVK Native 2.4.1 D3D9 + Android WSI, adrenotools/hooks, Mesa Turnip 26.0.0 R8",
        "device_verified": False,
    }
    (OUT / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    total = sum(row["bytes"] for row in receipt["runtime"])
    print(f"DXVK runtime staged: {len(names)} libraries, {total / 1e6:.1f} MB -> {runtime}")


if __name__ == "__main__":
    main()
