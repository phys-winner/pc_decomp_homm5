"""Build libtexconv.so, the launcher's texture converter (android/texconv), for arm64.

It links astcenc (reference/astcenc, NEON) and etcpak (reference/etcpak) with
the NDK's zlib. Objects are reused while their sources and headers are older.
tools/build_game_apk.py runs this and packages the library.
"""
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_android import CLANG, TARGET  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/arm64-texconv"
LIBRARY = OUT / "libtexconv.so"
CXX = CLANG.with_name("clang++.exe")
ASTC = ["-DASTCENC_NEON=1", "-DASTCENC_SVE=0", "-DASTCENC_SSE=0", "-DASTCENC_AVX=0", "-DASTCENC_POPCNT=0", "-DASTCENC_F16C=0"]
COMMON = ["--target=" + TARGET, "-O2", "-fPIC", "-fvisibility=hidden", "-ffunction-sections", "-fdata-sections", "-std=c++17",
          "-ffile-prefix-map=" + str(ROOT) + "=."]


def units():
    out = [(p, ASTC) for p in sorted((ROOT / "reference/astcenc").glob("*.cpp"))]
    out += [(ROOT / "reference/etcpak" / n, ["-DBCDEC_STATIC", "-DBCDEC_IMPLEMENTATION"])
            for n in ("ProcessRGB.cpp", "Tables.cpp", "Dither.cpp", "Decode.cpp")]
    out += [(ROOT / "android/texconv/texconv.cpp", ASTC + ["-Wall", "-Wextra", "-Werror"]),
            (ROOT / "android/texconv/texconv_jni.cpp", ["-Wall", "-Wextra", "-Werror"])]
    return out


def compile_unit(unit, headers):
    source, flags = unit
    obj = OUT / "obj" / (source.parent.name + "_" + source.stem + ".o")
    if obj.exists() and obj.stat().st_mtime >= max(source.stat().st_mtime, headers):
        return obj
    command = [str(CXX), *COMMON, *flags, "-c", str(source), "-o", str(obj)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"{source.name}: {result.stdout}{result.stderr}")
    return obj


def main():
    (OUT / "obj").mkdir(parents=True, exist_ok=True)
    headers = max(p.stat().st_mtime for p in [ROOT / "android/texconv/texconv.h", *(ROOT / "reference/astcenc").glob("*.h"),
                                              *(ROOT / "reference/etcpak").glob("*.hpp"), Path(__file__),
                                              ROOT / "tools/build_android.py"])
    with ThreadPoolExecutor(max_workers=12) as pool:
        objects = list(pool.map(lambda u: compile_unit(u, headers), units()))
    if not LIBRARY.exists() or LIBRARY.stat().st_mtime < max(o.stat().st_mtime for o in objects):
        command = [str(CXX), "--target=" + TARGET, "-shared", "-fuse-ld=lld", "-static-libstdc++", "-Wl,--gc-sections",
                   "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1", *map(str, objects),
                   "-lz", "-llog", "-o", str(LIBRARY)]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f"link: {result.stdout}{result.stderr}")
    print(f"texconv: {LIBRARY} ({LIBRARY.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
