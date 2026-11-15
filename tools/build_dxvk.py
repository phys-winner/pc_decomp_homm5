"""Stage the DXVK renderer of all three editions: import the pinned runtime and build its bridge.

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
API = 30   # DXVK modes need Android 11 (android/port.json minSdk 30): adrenotools' and the surface lifecycle's level
TARGET = f"aarch64-linux-android{API}"
BRIDGE_SOURCES = ("android/dxvk/bridge.cpp", "android/dxvk/probe.cpp")
# Everything the bridge is built from or must agree with; the APK builder refuses a stale receipt.
RECEIPT_SOURCES = (*BRIDGE_SOURCES, "android/dxvk/bridge_abi.h", "android/dxvk/turnip.h",
                   "android/dxvk/vulkan_requirements.h", "android/dxvk/bridge_metadata.h",
                   "android/dxvk/bridge_dispatch.h", "android/dxvk/bridge_special_names.h",
                   "android/host/dxvk_methods.h", "tools/build_dxvk.py", "tools/generate_dxvk_bridge.py")
TURNIP_DRIVER = {"libh5turnip.so": "libut3_turnip.so"}   # packaged name: name in the ut3 runtime
# Packaged without symbols and debug sections; the pinned originals stay in build/dxvk/symbols.
# Not through llvm-strip for the Turnip driver: its last PT_LOAD (a patchelf-style .dynstr segment)
# follows the debug sections in the file, and llvm-strip moved it to an offset that no longer matches
# its address modulo 64 KiB, which the Android linker refuses (adrenotools then loaded the system
# driver; device test 2026-11-15). strip_keep_layout drops those sections and keeps that rule
# (17.16 -> 13.69 MB, identical dynamic section and symbols); check_elf guards it. On abb24fae
# (Adreno 650, Android 15) adrenotools loaded the stripped driver ("Turnip Vulkan 1.3 driver loaded
# through adrenotools", adapter "Turnip Adreno (TM) 650"; ToE menu 33.3 fps as unstripped, 2026-11-15).
STRIPPED = ("libdxvk_d3d9.so", "libhook_impl.so")
STRIP_TURNIP = True
SHF_ALLOC, SHT_NOBITS = 2, 8
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
    """An AArch64 shared object whose loadable segments allow 16 KiB pages (Android 15+ devices) and
    lie in the file at their addresses modulo their alignment, as the Android linker maps them."""
    data = Path(path).read_bytes()
    if data[:5] != b"\x7fELF\x02" or struct.unpack_from("<HH", data, 16) != (3, 183):
        raise ValueError(f"{path.name}: not an AArch64 ELF shared object")
    table, entry, count = struct.unpack_from("<Q", data, 32)[0], struct.unpack_from("<H", data, 54)[0], struct.unpack_from("<H", data, 56)[0]
    for index in range(count):
        at = table + index * entry
        if struct.unpack_from("<I", data, at)[0] != 1:
            continue
        offset, address = struct.unpack_from("<QQ", data, at + 8)
        align = struct.unpack_from("<Q", data, at + 48)[0]
        if align < 16384:
            raise ValueError(f"{path.name}: PT_LOAD alignment below 16 KiB")
        if offset % align != address % align:
            raise ValueError(f"{path.name}: PT_LOAD at file offset {offset:#x} does not match its address "
                             f"{address:#x} modulo its alignment {align:#x}")


def strip_keep_layout(data):
    """An ELF64 little-endian shared object without its non-allocated sections (debug information,
    .symtab, .strtab, .comment); .shstrtab stays. Every PT_LOAD keeps its contents and moves to the
    lowest file offset after the previous one that is congruent to its address modulo its alignment,
    as the Android linker maps segments. The section header table keeps every index (a dropped
    section becomes an SHT_NULL header that keeps its name), so .dynsym and sh_link need no
    renumbering, and no address changes."""
    if data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("not an ELF64 little-endian object")
    phoff, shoff = struct.unpack_from("<QQ", data, 32)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from("<HHHHH", data, 54)
    phdrs = [list(struct.unpack_from("<IIQQQQQQ", data, phoff + i * phentsize)) for i in range(phnum)]
    shdrs = [list(struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize)) for i in range(shnum)]
    out, moves = bytearray(), []   # moves: (old start, old end, new start) of each PT_LOAD's bytes
    for _, _, old, _, _, size, _, align in sorted((p for p in phdrs if p[0] == 1), key=lambda p: p[2]):
        cursor = len(out)
        if old < cursor:
            raise ValueError(f"overlapping PT_LOAD at {old:#x}")
        new = cursor + (old - cursor) % max(align, 1)
        out += bytes(new - cursor) + data[old:old + size]
        moves.append((old, old + size, new))

    def moved(offset):
        for start, end, new in moves:
            if start <= offset <= end:
                return offset - start + new
        raise ValueError(f"file offset {offset:#x} lies outside the loadable segments")

    for p in phdrs:
        if p[0] != 0 and (p[2] or p[5]):   # PT_NULL and empty headers (PT_GNU_STACK) stay
            p[2] = moved(p[2])
    if phoff + phnum * phentsize > moves[0][1] or moves[0][0] != 0:
        raise ValueError("the program headers are not in the first segment")
    for i, p in enumerate(phdrs):
        struct.pack_into("<IIQQQQQQ", out, phoff + i * phentsize, *p)
    names = shdrs[shstrndx]
    names_at = len(out)
    out += data[names[4]:names[4] + names[5]]
    for i, s in enumerate(shdrs):
        if i == shstrndx:
            s[4] = names_at
        elif s[2] & SHF_ALLOC:
            s[4] = moved(s[4])
        elif i:
            shdrs[i] = [s[0], 0, 0, 0, 0, 0, 0, 0, 0, 0]
    table = (len(out) + 7) & ~7
    out += bytes(table - len(out))
    for s in shdrs:
        out += struct.pack("<IIQQQQIIQQ", *s)
    struct.pack_into("<Q", out, 40, table)
    # The loaded image is unchanged: every allocated section's bytes are where its header says.
    for i, s in enumerate(shdrs):
        if s[2] & SHF_ALLOC and s[1] != SHT_NOBITS:
            original = struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize)
            if out[s[4]:s[4] + s[5]] != data[original[4]:original[4] + original[5]]:
                raise ValueError(f"section {i} changed while stripping")
    return bytes(out)


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

    runtime, licenses, symbols = OUT / "runtime", OUT / "licenses", OUT / "symbols"
    turnip_dir = args.turnip_runtime or args.ut3 / "build/turnip-runtime/runtime"

    def pick(name, digest, *candidates):
        """The first candidate with the pinned digest; an earlier staging's pinned original
        (symbols/, or runtime/ for unstripped ones) after the given sources."""
        for candidate in (*candidates, symbols / name, runtime / name):
            if candidate and Path(candidate).is_file() and sha(candidate) == digest:
                return candidate
        return next(c for c in candidates if c)
    dxvk_pin = pinned["dxvk"]["runtime"]["libdxvk_d3d9.so"]
    sources = {"libdxvk_d3d9.so": (pick("libdxvk_d3d9.so", dxvk_pin, args.dxvk_library, args.ut3 / "build/dxvk/libdxvk_d3d9.so"), dxvk_pin)}
    libcxx_pin = pinned["libcxx_shared"]["runtime"]["libc++_shared.so"]
    sources["libc++_shared.so"] = (pick("libc++_shared.so", libcxx_pin, TOOLCHAIN / "sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"), libcxx_pin)
    for name, digest in pinned["adrenotools"]["runtime"].items():
        sources[name] = (pick(name, digest, turnip_dir / name), digest)
    for name, original in TURNIP_DRIVER.items():
        digest = pinned["turnip"]["runtime"][name]
        sources[name] = (pick(name, digest, turnip_dir / original), digest)
    # Verified and read before the old staging goes (one of them may come from it).
    staged = {name: Path(verified(source, digest, name)).read_bytes() for name, (source, digest) in sources.items()}
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    symbols.mkdir(parents=True, exist_ok=True)
    for name, data in staged.items():
        if name in STRIPPED:
            # The APK carries them without symbols and debug sections (1.3 MB less installed);
            # the pinned originals stay here for symbolising profiles.
            (symbols / name).write_bytes(data)
            run([TOOLCHAIN / "bin/llvm-strip.exe", "--strip-all", "-o", runtime / name, symbols / name])
        elif name in TURNIP_DRIVER and STRIP_TURNIP:
            (symbols / name).write_bytes(data)
            (runtime / name).write_bytes(strip_keep_layout(data))
        else:
            (runtime / name).write_bytes(data)
        check_elf(runtime / name)
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
        "symbols": [{"name": name, "sha256": sha(symbols / name)} for name in (*STRIPPED, *(TURNIP_DRIVER if STRIP_TURNIP else ()))],
        "reused_from": "ut3 port: DXVK Native 2.4.1 D3D9 + Android WSI, adrenotools/hooks, Mesa Turnip 26.0.0 R8",
        "device_verified": False,
    }
    (OUT / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    total = sum(row["bytes"] for row in receipt["runtime"])
    print(f"DXVK runtime staged: {len(names)} libraries, {total / 1e6:.1f} MB -> {runtime}")


if __name__ == "__main__":
    main()
