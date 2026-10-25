"""Compare actual window helpers and VM snapshots against the old shift model."""
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

from test_user32_startup import body

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android
import build_windows
import prepare_windows_runtime


def run_probe(mutation=None, thin=False, arm=False):
    out = ROOT / "build/tests" / ("x87_window_" + (mutation or "correct") + ("_thinlto" if thin else "_arm64" if arm else ""))
    runtime = out / "runtime"
    if arm:
        runtime.mkdir(parents=True, exist_ok=True)
        original = ROOT / "android/runtime/recomp_types.h"
        (runtime / "recomp_types.h").write_bytes(original.read_bytes())
        receipt = {"platform": "Android ARM64", "original_header_sha256": build_windows.sha(original)}
    else:
        receipt = prepare_windows_runtime.prepare(runtime)
    header_path = runtime / "recomp_types.h"
    header = header_path.read_text()
    if mutation == "stale_tail":
        old = "    g_st[7] = 0.0;\n    g_st_i64[7] = 0;"
        assert header.count(old) == 1
        header = header.replace(old, "    /* omitted logical tail zeros */", 1)
    elif mutation == "lost_shadow":
        old = "    memmove(g_st_i64_win + to, g_st_i64_win + g_fp_sp, sizeof g_st_i64);"
        assert header.count(old) == 1
        header = header.replace(old, "    /* omitted shadow recenter */", 1)
    elif mutation == "pointer_size":
        old = "#define g_st (*(double (*)[8])(g_st_win + g_fp_sp))"
        assert header.count(old) == 1
        header = header.replace(old, "#define g_st (g_st_win + g_fp_sp)", 1)
    header_path.write_text(header)
    core = (ROOT / "android/host/core.c").read_text()
    host = (ROOT / "android/host/host.h").read_text()
    original_header = (ROOT / "android/runtime/recomp_types.h").read_text()
    state = re.search(r"typedef struct void_regs \{.*?\} void_regs;", host, re.S).group()
    definitions = core[core.index("VOID_HIDDEN uint32_t g_eax"):core.index("#define VOID_ENTER_RING")]
    fixture = (ROOT / "tests/fixtures/x87_window_probe.c").read_text()
    replacements = {
        "ACTUAL_REGISTER_DEFS": definitions, "CURRENT_STATE": state,
        "CURRENT_SAVE": body(core, "void void_regs_save("),
        "CURRENT_LOAD": body(core, "void void_regs_load("),
        "BASE_PUSH": body(original_header, "static inline void fp_push_impl(").replace("fp_push_impl", "baseline_push").replace("g_st_i64", "baseline_i64"),
        "BASE_POP": body(original_header, "static inline double fp_pop_impl(").replace("fp_pop_impl", "baseline_pop").replace("g_st_i64", "baseline_i64"),
    }
    for tag, text in replacements.items():
        assert fixture.count("/* " + tag + " */") == 1
        fixture = fixture.replace("/* " + tag + " */", text)
    (out / "probe.c").write_text(fixture)
    cc, linker, env = build_windows.compiler_environment()
    flags = ["/nologo", "/O2", "/W3", "/std:c11", "/DRECOMP_X87_WINDOW", "/DVOID_GUEST_BASE=0",
             "/clang:--target=i686-pc-windows-msvc", "/clang:-fwrapv", "/clang:-fno-strict-aliasing",
             "/clang:-ffp-contract=off", "/I" + str(runtime)]
    if thin:
        flags += ["/clang:-flto=thin", "/Gy"]
    if arm:
        cc = build_android.CLANG
        flags = [*build_android.COMMON, "-O2", "-std=gnu11", "-Wall", "-Werror", "-I" + str(runtime)]
        commands = [[str(cc), *flags, "-c", str(out / "probe.c"), "-o", str(out / "probe.obj")]]
    else:
        commands = [[str(cc), *flags, "/c", str(out / "probe.c"), "/Fo" + str(out / "probe.obj")]]
    compiled = subprocess.run(commands[-1], env=env, capture_output=True, text=True, timeout=30)
    if mutation == "pointer_size":
        assert compiled.returncode != 0 and "x87 snapshot array size" in compiled.stderr, compiled.stdout + compiled.stderr
        return compiled
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    if arm:
        executable = out / "probe-arm64"
        commands.append([str(cc), *build_android.COMMON, str(out / "probe.obj"), "-o", str(executable)])
    else:
        executable = out / "probe.exe"
        linktool = [str(cc.with_name("ld.lld.exe")), "-flavor", "link"] if thin else [str(linker)]
        commands.append([*linktool, "/nologo", "/MACHINE:X86", "/OUT:" + str(executable), str(out / "probe.obj")])
        if thin:
            commands[-1] += ["/OPT:REF", "/OPT:ICF", "/OPT:lldlto=2", "/OPT:lldltojobs=4", "/threads:4",
                             "/lldltocache:" + str(out / "thinlto-cache")]
    linked = subprocess.run(commands[-1], env=env, capture_output=True, text=True, timeout=30)
    assert linked.returncode == 0, linked.stdout + linked.stderr
    if arm:
        raw = executable.read_bytes()
        assert raw[:5] == b"\x7fELF\x02" and int.from_bytes(raw[18:20], "little") == 183
        result = subprocess.CompletedProcess([str(executable)], 0, "ARM64 binary built; device execution pending", "")
    else:
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=20)
    (out / "receipt.json").write_text(json.dumps({"mutation": mutation, "thinlto": thin, "arm64_build_only": arm, "exit": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr, "runtime": receipt, "commands": commands,
        "executable_sha256": build_windows.sha(executable),
        "header_sha256": build_windows.sha(header_path),
        "fixture_sha256": build_windows.sha(out / "probe.c")}, indent=2) + "\n")
    return result


# The recentre helper's definition line, whatever its inline/outline attributes.
RECENTRE = re.compile(r"^static [^\n]*\bvoid fp_window_recentre\(", re.M)


def run_projection_probe(thin=False, arm=False, outlined=False):
    out = ROOT / "build/tests" / ("x87_window_projection_" + ("outlined" if outlined else "correct")
                                 + ("_thinlto" if thin else "_arm64" if arm else ""))
    out.mkdir(parents=True, exist_ok=True)
    header_path = ROOT / "android/runtime/recomp_types.h"
    header = header_path.read_text()
    helpers = header[RECENTRE.search(header).start():header.index("#define fp_push(val) fp_window_push((val))")]
    # The reference is the inline, unhinted window: the hints and the recentre's
    # linkage must not change any result, computed NaN payloads included.
    baseline = RECENTRE.sub("static inline void fp_window_recentre(", helpers, count=1)
    baseline = baseline.replace("__builtin_expect(g_fp_sp <= 8, 0)", "g_fp_sp <= 8")
    baseline = baseline.replace("__builtin_expect(g_fp_sp > RECOMP_X87_SLOTS - 9, 0)",
                                "g_fp_sp > RECOMP_X87_SLOTS - 9")
    baseline = baseline.replace("fp_window_", "baseline_window_")
    if outlined:
        helpers = RECENTRE.sub("static __attribute__((noinline, cold)) void fp_window_recentre(", helpers, count=1)
    fixture_path = ROOT / "tests/fixtures/x87_window_projection_probe.c"
    fixture = fixture_path.read_text()
    generated = (ROOT / "generated/game-x86/game_0355.c").read_text()
    region = generated[generated.index("    fp_push(*(float*)&MEM32(ecx + edi + 0x4)); /* 0x0087E5A4:"):
                       generated.index("L_0087E5E9:")]
    region = region[:region.index("    ecx = MEM32(esi); /* 0x0087E5D3:")]
    # Both fixture bodies must retain the literal generated arithmetic and stores.
    assert fixture.count(region.rstrip()) == 2
    fixture = fixture.replace("/* ACTUAL_WINDOW_HELPERS */", helpers)
    fixture = fixture.replace("/* BASELINE_WINDOW_HELPERS */", baseline)
    source = out / "probe.c"
    source.write_text(fixture)
    cc, linker, env = build_windows.compiler_environment()
    flags = ["/nologo", "/O2", "/W0", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
             "/clang:--target=i686-pc-windows-msvc", "/clang:-fwrapv",
             "/clang:-fno-strict-aliasing", "/clang:-ffp-contract=off"]
    if thin:
        flags += ["/clang:-flto=thin"]
    obj = out / "probe.obj"
    if arm:
        cc = build_android.CLANG
        flags = [*build_android.COMMON, "-O2", "-std=gnu11", "-Wall", "-Werror"]
        commands = [[str(cc), *flags, "-c", str(source), "-o", str(obj)]]
    else:
        commands = [[str(cc), *flags, "/c", str(source), "/Fo" + str(obj)]]
    compiled = subprocess.run(commands[-1], env=env, capture_output=True, text=True, timeout=30)
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    executable = out / ("probe-arm64" if arm else "probe.exe")
    if arm:
        commands.append([str(cc), *build_android.COMMON, str(obj), "-lm", "-o", str(executable)])
    else:
        linktool = [str(cc.with_name("ld.lld.exe")), "-flavor", "link"] if thin else [str(linker)]
        commands.append([*linktool, "/nologo", "/MACHINE:X86", "/OUT:" + str(executable), str(obj)])
        if thin:
            commands[-1] += ["/OPT:REF", "/OPT:ICF", "/OPT:lldlto=2", "/OPT:lldltojobs=1", "/threads:1"]
    linked = subprocess.run(commands[-1], env=env, capture_output=True, text=True, timeout=30)
    assert linked.returncode == 0, linked.stdout + linked.stderr
    if arm:
        raw = executable.read_bytes()
        assert raw[:5] == b"\x7fELF\x02" and int.from_bytes(raw[18:20], "little") == 183
        result = subprocess.CompletedProcess([str(executable)], 0, "ARM64 binary built; device execution pending", "")
    else:
        result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    (out / "receipt.json").write_text(json.dumps({"thinlto": thin, "arm64_build_only": arm,
        "outlined_mutant": outlined, "exit": result.returncode, "stdout": result.stdout,
        "stderr": result.stderr, "commands": commands, "executable_sha256": build_windows.sha(executable),
        "header_sha256": build_windows.sha(header_path), "fixture_sha256": build_windows.sha(fixture_path),
        "prepared_source_sha256": build_windows.sha(source)}, indent=2) + "\n")
    return result


class X87WindowTest(unittest.TestCase):
    def test_actual_helpers_full_state_and_vm_restore(self):
        result = run_probe()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("403801 full8 operations", result.stdout)
        print(result.stdout.strip())

    def test_thinlto_actual_helpers_full_state_and_vm_restore(self):
        result = run_probe(thin=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("403801 full8 operations", result.stdout)

    def test_arm64_cli_build_for_device_oracle(self):
        result = run_probe(arm=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("device execution pending", result.stdout)

    def test_hot_projection_raw_arithmetic_o2_and_thinlto(self):
        for thin in (False, True):
            with self.subTest(thinlto=thin):
                result = run_projection_probe(thin=thin)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("4096 current-vs-unhinted x87 window projection comparisons", result.stdout)

    def test_outlining_computed_nan_regression_is_detected(self):
        result = run_projection_probe(outlined=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Mismatch case=", result.stderr)

    def test_arm64_hot_projection_build_for_device_oracle(self):
        result = run_projection_probe(arm=True)
        self.assertIn("device execution pending", result.stdout)

    def test_stale_tail_and_lost_shadow_are_rejected(self):
        for mutation in ("stale_tail", "lost_shadow"):
            with self.subTest(mutation=mutation):
                result = run_probe(mutation)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Assertion failed", result.stderr)

    def test_pointer_size_macro_is_compile_time_error(self):
        run_probe("pointer_size")

    def test_every_current_generated_source_has_no_window_alias_hazard(self):
        chunks = list((ROOT / "generated").glob("*-x86/*_[0-9][0-9][0-9][0-9].c"))
        self.assertGreater(len(chunks), 1000)
        for source in chunks:
            try:
                build_android.guard_x87_window_source(source.read_bytes())
            except ValueError as error:
                self.fail(str(source) + ": " + str(error))


if __name__ == "__main__":
    unittest.main()
