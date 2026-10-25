"""Current packed helpers and a real generated leaf versus original x86 MMX."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unittest

import pefile

ROOT = Path(__file__).resolve().parents[1]
CLANG = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64/bin/clang-cl.exe"


def pc_header(source):
    """The tested integer helpers are exact; only irrelevant ARM-only setup goes."""
    source, guard = re.subn(r'#if defined\(_MSC_VER\) \|\| !defined\(__aarch64__\)\n#error[^\n]*\n#endif', '/* PC-only architecture assertion omitted. */', source, count=1)
    source, counter = re.subn(r'static inline uint64_t __rdtsc\(void\) \{.*?\n\}', '/* Unused ARM-only RDTSC implementation omitted. */', source, count=1, flags=re.S)
    assert guard == counter == 1
    return source


def generated_leaf():
    source = (ROOT / "generated/game-x86/game_0657.c").read_text()
    start = source.index("void sub_00C68210(void) {")
    depth = 0
    for end in range(source.index("{", start), len(source)):
        depth += (source[end] == "{") - (source[end] == "}")
        if not depth:
            return source[start:end + 1] + "\n"
    raise AssertionError("missing generated leaf terminator")


def environment(arch):
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"], text=True).strip())
    msvc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(r"C:\Program Files (x86)\Windows Kits\10")
    version = sorted((sdk / "Lib").iterdir())[-1].name
    env = os.environ.copy()
    env["PATH"] = str(msvc / "bin/Hostx64" / arch) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk / f"Include/{version}/ucrt", sdk / f"Include/{version}/shared", sdk / f"Include/{version}/um"]))
    env["LIB"] = ";".join(map(str, [msvc / f"lib/{arch}", sdk / f"Lib/{version}/ucrt/{arch}", sdk / f"Lib/{version}/um/{arch}"]))
    return env, msvc / "bin/Hostx64" / arch / "link.exe"


def command(args, out, env, check=True):
    result = subprocess.run(list(map(str, args)), cwd=out, env=env, text=True, capture_output=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    if check and result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result


def compile_variant(out, header, arch, name):
    (out / "recomp_types.h").write_text(pc_header(header))
    target = "i686" if arch == "x86" else "x86_64"
    flags = [CLANG, "/nologo", "/W0", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS", f"/clang:--target={target}-pc-windows-msvc", "/clang:-fno-strict-aliasing", "/clang:-fwrapv", "/clang:-ffp-contract=off", "/DPC_COMPARE_CASES=1024", "/DPC_COMPARE_BENCH=0"]
    if arch == "x86":
        flags.append("/DVOID_GUEST_BASE=0")
    env, linker = environment(arch)
    command([*flags, "/DRECOMP_GENERATED_CODE", "/DRECOMP_LOCAL_REGS", "/DRECOMP_PLAIN_MEMORY", "/DRECOMP_TRACE", "/c", "leaf.c", "/Foleaf.obj"], out, env)
    command([*flags, "/c", "probe.c", "/Foprobe.obj"], out, env)
    command([linker, "/nologo", "probe.obj", "leaf.obj", f"/OUT:{name}.exe", "/BASE:" + ("0x70000000" if arch == "x86" else "0x140000000"), "/DYNAMICBASE:NO", "/FIXED", "/STACK:262144"], out, env)
    return command([out / f"{name}.exe"], out, env, check=False)


class PackedMmxTest(unittest.TestCase):
    def test_exact_hardware_and_generated_leaf(self):
        out = ROOT / "build/tests/mmx_packed"
        out.mkdir(parents=True, exist_ok=True)
        pe = pefile.PE(str(ROOT / "generated/input/H5_Game.exe"), fast_load=True)
        native = pe.get_data(0xC68210 - pe.OPTIONAL_HEADER.ImageBase, 191)
        self.assertEqual(hashlib.sha256(native).hexdigest(), "d911021330b8acf0e063d5cc0ee93b3141ed7db10f14176c33b5568c15a0694d")
        (out / "native_code.h").write_text("static const unsigned char original_code[] = {" + ",".join(map(str, native)) + "};\n")
        (out / "leaf.c").write_text('#include "recomp_types.h"\n' + generated_leaf())
        (out / "probe.c").write_text((ROOT / "tests/fixtures/mmx_packed_probe.c").read_text())
        header = (ROOT / "android/runtime/recomp_types.h").read_text()
        reports = []
        for arch in ("x86", "x64"):
            tested = compile_variant(out, header, arch, arch)
            self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
            self.assertIn('"native_instruction_results":360000', tested.stdout)
            self.assertIn('"full_guest_memory_bytes":131072', tested.stdout)
            reports.append(tested.stdout)
        # Exercise the retained scalar bodies too, with the same hardware oracle.
        scalar = header.replace("#define RECOMP_MMX_PACKED 1", "/* Test only: force retained scalar implementation. */", 1)
        tested = compile_variant(out, scalar, "x86", "scalar")
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
        reports.append(tested.stdout)
        # The independent instruction oracle must reject bad signed shift counts.
        mutant = header.replace("if (c > 15) c = 15;\n    return MMX_RAW(signed_words", "if (c > 15) return 0;\n    return MMX_RAW(signed_words", 1)
        self.assertNotEqual(mutant, header)
        failed = compile_variant(out, mutant, "x86", "bad_shift")
        self.assertEqual(failed.returncode, 25, failed.stdout + failed.stderr)
        self.assertIn("helper psraw", failed.stderr)
        (out / "receipt.json").write_text(json.dumps({"accepted": True, "runtime_header_sha256": hashlib.sha256(header.encode()).hexdigest(), "production_models": ["LOCAL_REGS", "PLAIN_MEMORY", "TRACE"], "passes": reports, "negative_control": failed.stderr}, indent=2) + "\n")


if __name__ == "__main__":
    unittest.main()
