"""GL-side share of the game thread in a simpleperf profile (tools/profile_cpu.py output).

usage: gl_share.py PROFILE_DIR --objects build/<task>/obj
The game thread is the busiest one. GL side: vendor GL libraries, the functions of the d3d9_*.o objects
and MojoShader. self: the sample's own frame; inclusive: any frame of its callchain.
"""
import argparse
import collections
import os
from pathlib import Path
import subprocess
import sys

SDK = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "AppData/Local/Android/Sdk"))
NDK = Path(os.environ.get("ANDROID_NDK_HOME", SDK / "ndk/27.2.12479018"))
VENDOR = ("libGLESv2_adreno", "libgsl", "libEGL_adreno", "libllvm-glnext", "libadreno_utils", "libllvm-qcom",
          "libGLES_mali", "libGLESv2_PVR", "libsrv_um", "libCB")


def gl_symbols(objects):
    nm = NDK / "toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-nm.exe"
    syms = {}
    for obj in sorted(objects.rglob("*.o")):
        if not (obj.stem.startswith("d3d9_") or obj.stem.startswith("mojoshader")):
            continue
        out = subprocess.check_output([str(nm), "--defined-only", str(obj)], text=True)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[1] in "TtWw":
                syms[parts[2]] = "mojoshader" if obj.stem.startswith("mojoshader") else "d3d9"
    return syms


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("profile", type=Path)
    p.add_argument("--objects", type=Path, required=True)
    a = p.parse_args()
    sys.path.insert(0, str(NDK / "simpleperf"))
    from simpleperf_report_lib import ReportLib
    syms = gl_symbols(a.objects)

    def cat(dso, sym):
        base = dso.rsplit("/", 1)[-1]
        if any(v in base for v in VENDOR):
            return "vendor-gl"
        if base.startswith("libhomm5") and sym in syms:
            return syms[sym]
        return None

    lib = ReportLib()
    lib.SetRecordFile(str(a.profile / "perf.data"))
    if (a.profile / "binary_cache").is_dir():
        lib.SetSymfs(str(a.profile / "binary_cache"))
    per_tid, incl, names = collections.Counter(), collections.Counter(), {}
    self_cat = collections.defaultdict(collections.Counter)
    while (s := lib.GetNextSample()) is not None:
        per_tid[s.tid] += s.period
        names[s.tid] = s.thread_comm
        sym = lib.GetSymbolOfCurrentSample()
        c = cat(sym.dso_name, sym.symbol_name)
        self_cat[s.tid][c] += s.period
        chain = lib.GetCallChainOfCurrentSample()
        if c or any(cat(chain.entries[i].symbol.dso_name, chain.entries[i].symbol.symbol_name) for i in range(chain.nr)):
            incl[s.tid] += s.period
    tid = max(per_tid, key=per_tid.get)
    total = per_tid[tid]
    gl = sum(self_cat[tid][k] for k in ("vendor-gl", "d3d9", "mojoshader"))
    print(f"game thread {tid} {names[tid]}: {100 * total / sum(per_tid.values()):.1f}% of process cycles")
    for k in ("vendor-gl", "d3d9", "mojoshader"):
        print(f"  self {k}: {100 * self_cat[tid][k] / total:.1f}%")
    print(f"  self GL side: {100 * gl / total:.1f}%, inclusive: {100 * incl[tid] / total:.1f}%")


if __name__ == "__main__":
    main()
