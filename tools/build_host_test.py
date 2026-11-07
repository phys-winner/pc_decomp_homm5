"""Build one on-device host test of tests/ (a C file that #includes a production source) for ARM64.

The test is linked with every object of the current libhomm5.so build except the production sources it
includes itself (it wins duplicate definitions: its objects come first), so the rest of the host runtime and the lifted game
are the production ones. Objects come from <--objects> (default: the build/<task>/obj cache).

usage: build_host_test.py tests/test_x.c --objects build/<task>/obj --output build/<task>/tests/test_x
"""
import argparse
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SDK = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "AppData/Local/Android/Sdk"))
NDK = Path(os.environ.get("ANDROID_NDK_HOME", SDK / "ndk/27.2.12479018"))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("test", type=Path)
    p.add_argument("--objects", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--define", action="append", default=[])
    p.add_argument("--exclude", action="append", default=[],
                   help="object stems left out too, e.g. android_main when the test stubs its symbols")
    a = p.parse_args()
    clang = NDK / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
    text = a.test.read_text(encoding="utf-8")
    included = {Path(m).name for m in re.findall(r'#include "\.\./android/host/([a-z0-9_]+\.c)"', text)}
    included |= {Path(m).name for m in re.findall(r'#include "\.\./reference/mojoshader/([a-z0-9_]+\.c)"', text)}
    skip = {Path(n).stem for n in included} | set(a.exclude)
    objects = [o for o in sorted(a.objects.rglob("*.o")) if o.stem not in skip]
    flags = ["--target=aarch64-linux-android29", "-O1", "-g", "-fno-strict-aliasing", "-fwrapv", "-ffp-contract=off",
             "-DRECOMP_X87_WINDOW", "-Iandroid/runtime", "-Iandroid/host", "-Igenerated", "-Ireference/mojoshader",
             "-DVOID_ANDROID_APP", "-std=gnu11", "-w"] + ["-D" + d for d in a.define]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    rsp = a.output.with_suffix(".rsp")
    rsp.write_text("\n".join('"' + o.as_posix() + '"' for o in objects))
    cmd = [str(clang), *flags, str(a.test), "@" + str(rsp), "-o", str(a.output), "-Wl,-z,max-page-size=16384",
           "-Wl,--allow-multiple-definition", "-flto=thin", "-Wl,--thinlto-jobs=8",
           "-Wl,--thinlto-cache-dir=" + str(a.objects.parent / "thin-test-cache"),
            "-lm", "-ldl", "-llog", "-landroid", "-lEGL", "-lGLESv3", "-laaudio", "-lOpenSLES", "-lz"]
    subprocess.run(cmd, cwd=ROOT, check=True)
    print(a.output)


if __name__ == "__main__":
    main()
