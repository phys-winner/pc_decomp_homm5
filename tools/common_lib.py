"""libhomm5_common.so: the lifted DLL code that is byte-identical in all three engines.

FMOD, the VC7.1 CRT and C++ library, zlib, libcurl and zlibwapi ship as the same DLLs in
Tribes of the East 3.1, Hammers of Fate 2.1 and Heroes V 1.6, and build_android.py's
transforms turn them into the same C for every engine. Their objects are compiled once
(tools/build_android.py --common) and each engine links against the result
(--common-lib) instead of carrying its own copy.

Exactness. A file joins the library only when its transformed source (the bytes
build_android.override_source compiles) is identical for every engine, together with its
module's headers, file list and per-module compile flags; a module joins only when every
file does. The single per-engine difference, FMOD's backedge hand-off interval
(build_android.module_yield_every), becomes a constant each engine defines. Every engine
build checks its own transformed sources against the library's receipt again.

ABI. The engine keeps the register file and the runtime helpers (android/host/core.c,
fmod_stream.c). Their definitions are hidden, and the engine's generated objects reference
them as hidden, so the engine exports them under h5x_ names (--defsym aliases); the library
reaches them through its GOT/PLT with a copy of recomp_types.h whose VOID_HIDDEN is
default visibility and whose runtime names are mapped to the h5x_ aliases. The library's
functions are protected (direct calls inside the library) and only sub_* are exported, for
the engine's dispatch table and the host's *_lifted calls. The engine has DT_NEEDED
libhomm5_common.so and DT_RUNPATH $ORIGIN: NativeLibrary.java unpacks both into one private
folder and System.load maps the pair as one group, each resolving the other's symbols.

PGO training (--pgo-generate) and function-coverage builds keep each engine whole.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = "libhomm5_common.so"
RECEIPT = "libhomm5_common.patches.json"
EDITIONS = ("toe", "vanilla", "hof")
# Modules whose every transformed file must match across the engines. granny2 differs in
# three ToE files (FPU-cache and x87 plans) whose skinning calls cross into the other files
# hundreds of millions of times a session; split across a library boundary they would lose
# inlining, so granny2 stays in each engine.
CANDIDATE_MODULES = ("fmod", "msvcr71", "msvcp71", "zlib1", "libcurl", "zlibwapi")
PREFIX = "h5x_"
# Runtime names the generated code can reach in the engine (android/runtime/recomp_types.h,
# void_lift_trap from the *_funcs.h headers). Unused names cost nothing; a missing one stops
# the library link check.
RUNTIME_IMPORTS = (
    "g_eax", "g_ecx", "g_edx", "g_esp", "g_ebx", "g_esi", "g_edi", "g_ebp", "g_mm",
    "g_st_win", "g_st_i64_win", "g_fp_sp", "g_fp_top", "g_fpu_cw",
    "g_flag_k", "g_flag_a", "g_flag_b", "g_flag_cf", "void_fpu_cmp",
    "g_seg_cs", "g_seg_ds", "g_seg_es", "g_seg_fs", "g_seg_gs", "g_seg_ss",
    "g_mem_base", "g_fs_base", "g_gs_base", "g_es_base", "g_xmm", "g_mxcsr",
    "g_fp_round_mask", "g_fp_store_mask", "g_cur_func",
    "g_icall_trace", "g_icall_from", "g_icall_trace_idx", "g_icall_count",
    "g_enter_trace", "g_enter_idx", "recomp_yield_hook", "g_backedges",
    "void_fpu_remainder", "void_cpuid", "void_resolve", "void_lift_trap",
    "recomp_x87_violation", "recomp_protocol_violation", "recomp_eh_push", "recomp_eh_pop",
    "recomp_dump_trace",
)
VISIBILITY_ANCHOR = b'#define VOID_HIDDEN __attribute__((visibility("hidden")))'
SYSTEM_LIBRARIES = {"libc.so", "libm.so", "libdl.so"}
DEFAULT_YIELD = 0x10000


def common_root(modes, root=ROOT):
    return Path(root) / "build" / ("arm64-common" + "".join("-" + mode for mode in modes))


def engine_root(out):
    """Where an engine linked against the library lives (beside its whole-engine build)."""
    return Path(out) / "common"


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


# ------------------------------------------------------------------------------------ ELF
def elf_dynamic(path):
    """DT_NEEDED/DT_SONAME/DT_RUNPATH and the dynamic symbols of an AArch64 ELF64 library."""
    data = Path(path).read_bytes()
    if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
        raise ValueError(f"{path}: not a little-endian ELF64 file")
    shoff, = struct.unpack_from("<Q", data, 0x28)
    shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i * shentsize) for i in range(shnum)]
    by_type = lambda kind: [s for s in sections if s[1] == kind]

    def strings(index):
        _, _, _, _, offset, size, *_ = sections[index]
        return data[offset:offset + size]

    def text(table, at):
        return table[at:table.index(b"\0", at)].decode()

    dynsym = by_type(11)
    dynamic = by_type(6)
    if len(dynsym) != 1 or len(dynamic) != 1:
        raise ValueError(f"{path}: no single dynamic symbol table")
    _, _, _, _, offset, size, link, _, _, entsize = dynsym[0]
    names = strings(link)
    versym = by_type(0x6FFFFFFF)
    versions = None
    if versym:
        voff, vsize = versym[0][4], versym[0][5]
        versions = struct.unpack_from("<%dH" % (vsize // 2), data, voff)
    symbols = []
    for i in range(1, size // entsize):
        st_name, st_info, st_other, st_shndx, st_value, st_size = struct.unpack_from("<IBBHQQ", data, offset + i * entsize)
        symbols.append(dict(name=text(names, st_name), defined=st_shndx != 0, bind=st_info >> 4,
                            type=st_info & 15, visibility=st_other & 3,
                            versioned=bool(versions) and (versions[i] & 0x7FFF) > 1))
    _, _, _, _, doff, dsize, dlink, _, _, dentsize = dynamic[0]
    dynstr = strings(dlink)
    needed, soname, runpath = [], None, None
    for i in range(dsize // dentsize):
        tag, value = struct.unpack_from("<qQ", data, doff + i * dentsize)
        if tag == 0:
            break
        if tag == 1:
            needed.append(text(dynstr, value))
        elif tag == 14:
            soname = text(dynstr, value)
        elif tag in (15, 29):
            runpath = text(dynstr, value)
    return dict(needed=needed, soname=soname, runpath=runpath, symbols=symbols)


def exported(info):
    return {s["name"] for s in info["symbols"] if s["defined"] and s["bind"] in (1, 2)}


def imported(info):
    """Undefined symbols no versioned system library provides."""
    return {s["name"] for s in info["symbols"] if not s["defined"] and not s["versioned"]}


def check_pair(engine_path, engine_info, common_info, imports):
    """The engine maps libhomm5_common.so beside itself and each satisfies the other. (lld's
    --no-undefined already resolved the engine's other imports against the NDK's system
    stubs, several of which, like libaaudio's, carry no symbol versions.)"""
    problems = []
    if LIBRARY not in engine_info["needed"]:
        problems.append("it has no DT_NEEDED " + LIBRARY)
    if engine_info["runpath"] != "$ORIGIN":
        problems.append("its DT_RUNPATH is %r, not $ORIGIN" % engine_info["runpath"])
    lifted = {s["name"] for s in engine_info["symbols"] if not s["defined"] and s["name"].startswith("sub_")}
    missing = sorted(lifted - exported(common_info))
    if missing:
        problems.append("%d engine imports are not exported by %s (%s)" % (len(missing), LIBRARY, ", ".join(missing[:8])))
    unexported = sorted(set(imports) - exported(engine_info))
    if unexported:
        problems.append("it does not export %s" % ", ".join(unexported[:8]))
    if problems:
        raise ValueError(f"{engine_path}: " + "; ".join(problems))


# ---------------------------------------------------------------------- receipts / config
def receipt_path(modes, root=ROOT):
    return common_root(modes, root) / RECEIPT


def record_path(engine):
    return Path(engine).with_suffix(".common.json")


def load_receipt(modes, root=ROOT):
    path = receipt_path(modes, root)
    if not path.is_file():
        raise ValueError(f"{LIBRARY} is not built: run tools/build_android.py --common --shared"
                         + "".join(" --" + flag for flag in mode_flags(modes)))
    receipt = json.loads(path.read_text(encoding="utf-8"))
    library = common_root(modes, root) / LIBRARY
    if not library.is_file() or sha_file(library) != receipt.get("library_sha256"):
        raise ValueError(f"{library} does not match its receipt; rebuild it with --common")
    return receipt


def mode_flags(modes):
    names = {"volatilemem": "volatile-memory", "thinlto": "thinlto", "check": "protocol-check"}
    return [names[mode] for mode in modes]


def profile_inputs(root=ROOT):
    """The engines' default PGO profiles (build_android.py): the library merges them."""
    rows = {}
    for edition in EDITIONS:
        path = Path(root) / "build" / ("pgo" if edition == "toe" else "pgo-" + edition) / "homm5.profdata"
        if path.is_file():
            rows[edition] = path
    return rows


def config(clang, modes, pgo, root=ROOT):
    """What the library's objects depend on besides their sources: compiler, builder, runtime
    header and profiles. Engine builds and the packager compare it with the receipt's."""
    tools = Path(root) / "tools"
    return dict(
        modes=list(modes), pgo=bool(pgo),
        compiler_sha256=sha_file(clang),
        builder_sha256={name: sha_file(tools / name) for name in ("build_android.py", "common_lib.py")},
        runtime_sha256=sha_file(Path(root) / "android/runtime/recomp_types.h"),
        profiles={edition: sha_file(path) for edition, path in profile_inputs(root).items()} if pgo else {},
    )


def merged_profile(ba, root=ROOT):
    """build/pgo-common/homm5.profdata: the engines' default profiles merged (llvm-profdata),
    remade when one of them changes. None without any profile."""
    inputs = profile_inputs(root)
    if not inputs:
        return None
    folder = Path(root) / "build/pgo-common"
    output, stamp = folder / "homm5.profdata", folder / "inputs.json"
    wanted = {edition: sha_file(path) for edition, path in inputs.items()}
    if output.is_file() and stamp.is_file():
        recorded = json.loads(stamp.read_text(encoding="utf-8"))
        if recorded.get("inputs") == wanted and recorded.get("sha256") == sha_file(output):
            return output
    folder.mkdir(parents=True, exist_ok=True)
    tool = ba.TOOLCHAIN / "bin/llvm-profdata.exe"
    if not tool.is_file():
        tool = ba.TOOLCHAIN / "bin/llvm-profdata"
    part = output.with_suffix(".part")
    result = subprocess.run([str(tool), "merge", "-o", str(part), *[str(inputs[e]) for e in sorted(inputs)]],
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit("llvm-profdata merge failed:\n" + result.stderr[-3000:])
    part.replace(output)
    stamp.write_text(json.dumps({"inputs": wanted, "sha256": sha_file(output)}, indent=2) + "\n", encoding="utf-8")
    print(f"[common] merged profile from {', '.join(sorted(inputs))}", flush=True)
    return output


# ------------------------------------------------------------------------- shared sources
def yield_value(ba, module, edition):
    edges = ba.module_yield_every(module + "-x86", edition)
    return DEFAULT_YIELD if edges is None else edges


def yield_symbol(module):
    return PREFIX + "yield_" + module


PROTOTYPE = re.compile(rb"^void (sub_[0-9A-F]{8})\(void\);\r?$")
REFERENCE = re.compile(rb"\bsub_[0-9A-F]{8}\b")


def header_view(folder, referenced):
    """A module's headers as its sources see them. The generated *_funcs.h also declare other
    modules' functions, which differ between the engines; a prototype the sources never name
    emits nothing, and every prototype has the same form, so only the named ones count."""
    view = {}
    for path in sorted(Path(folder).glob("*.h")):
        other, names = [], set()
        for line in path.read_bytes().splitlines():
            match = PROTOTYPE.match(line)
            if match:
                names.add(match[1])
            else:
                other.append(line)
        view[path.name] = sha_bytes(b"\n".join(other) + b"\0" + b"\n".join(sorted(names & referenced)))
    return view


def module_inventory(ba, edition):
    """For one engine: each candidate module's source list, header view, the transformed
    text digest of every file (computed in memory) and its compile flags besides the yield."""
    from port_patches import native_overrides
    ba.configure_edition(edition)
    ba.ACTIVE_NATIVE_OVERRIDES = native_overrides(edition, ba.NATIVE_OVERRIDES)
    manifest = {row["name"]: row for row in ba.MANIFEST}
    modules = {}
    for module in CANDIDATE_MODULES:
        if module not in manifest:
            continue
        folder = ba.GENERATED / f"{module}-x86"
        report = json.loads((folder / "report.json").read_text())
        image = ba.GENERATED / "input" / manifest[module]["file"]
        if (report.get("status") != "GENERATED" or report.get("binary_sha256") != manifest[module]["sha256"]
                or not image.is_file() or sha_file(image) != report.get("rebased_sha256")):
            raise SystemExit(f"{edition}/{module}: generated image identity mismatch")
        files, referenced = {}, set()
        for name in report["sources"]:
            original, text = ba.transform_source(folder / name, local_xmm=True)
            files[name] = (sha_bytes(text), text if edition == "toe" else None, text == original)
            referenced.update(REFERENCE.findall(text))
        headers = header_view(folder, referenced)
        flags = [flag for flag in ba.module_compile_flags(module + "-x86") if not flag.startswith("-DRECOMP_YIELD_EVERY=")]
        modules[module] = dict(files=files, headers=headers, flags=flags, folder=folder,
                               overrides=sorted(name for name in ba.ACTIVE_NATIVE_OVERRIDES
                                                if any(name.startswith("sub_" + base) for base in module_prefixes(manifest[module]))))
    return modules


def module_prefixes(row):
    """The leading hex digit pair of a module's guest addresses (its rebased image base)."""
    base = int(str(row["base"]), 16) if isinstance(row["base"], str) else int(row["base"])
    return ("%02X" % (base >> 24),)


def imports_header(overrides, yields):
    lines = ["/* Generated by tools/common_lib.py for " + LIBRARY + "; do not edit.",
             " * The engine that maps this library owns the register file and the runtime",
             " * helpers; it exports them under these names (--defsym aliases). */",
             "#ifndef H5_COMMON_IMPORTS_H", "#define H5_COMMON_IMPORTS_H"]
    for name in RUNTIME_IMPORTS + tuple(overrides):
        lines.append(f"#define {name} {PREFIX}{name}")
    for module in yields:
        lines.append(f"extern const uint32_t {yield_symbol(module)};   /* RECOMP_YIELD_EVERY of {module} */")
    lines.append("#endif")
    return "\n".join(lines) + "\n"


def runtime_header(root=ROOT):
    """recomp_types.h with default-visibility declarations, including the import names."""
    text = (Path(root) / "android/runtime/recomp_types.h").read_bytes()
    if text.count(VISIBILITY_ANCHOR) != 1:
        raise SystemExit("recomp_types.h: the VOID_HIDDEN definition changed; update tools/common_lib.py")
    newline = b"\r\n" if b"\r\n" in text else b"\n"
    replacement = (b"/* " + LIBRARY.encode() + b": runtime state is imported from the engine. */" + newline +
                   b'#define VOID_HIDDEN __attribute__((visibility("default")))' + newline +
                   b'#include "h5_common_imports.h"')
    return text.replace(VISIBILITY_ANCHOR, replacement)


def write_if_changed(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)


# ------------------------------------------------------------------------------- build
def build_common(ba, args, modes):
    """build_android.py --common: select, compile, link and check the library."""
    import time
    started = time.time()
    root = common_root(modes, ba.ROOT)
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(ba.ROOT)
    pgo = bool(args.pgo_use)
    inventories = {edition: module_inventory(ba, edition) for edition in EDITIONS}
    print(f"[common] transformed sources of {len(EDITIONS)} engines compared in {time.time() - started:.0f}s", flush=True)
    shared, excluded = [], {}
    for module in CANDIDATE_MODULES:
        rows = [inventories[edition].get(module) for edition in EDITIONS]
        if any(row is None for row in rows):
            excluded[module] = "not in every engine"
            continue
        first = rows[0]
        reasons = []
        if any(row["headers"] != first["headers"] for row in rows):
            reasons.append("headers differ")
        if any(set(row["files"]) != set(first["files"]) for row in rows):
            reasons.append("source lists differ")
        if any(row["flags"] != first["flags"] for row in rows):
            reasons.append("compile flags differ")
        if any(row["overrides"] != first["overrides"] for row in rows):
            reasons.append("native overrides differ")
        different = [name for name in first["files"]
                     if any(row["files"].get(name, (None,))[0] != first["files"][name][0] for row in rows)]
        if different:
            reasons.append("%d transformed files differ (%s)" % (len(different), ", ".join(different[:4])))
        if reasons:
            excluded[module] = "; ".join(reasons)
        else:
            shared.append(module)
    for module, reason in excluded.items():
        print(f"[common] {module} stays in each engine: {reason}", flush=True)
    if not shared:
        raise SystemExit("[common] no module is identical in all three engines")
    yields = {module: {edition: yield_value(ba, module, edition) for edition in EDITIONS} for module in shared}
    variable = [module for module in shared if len(set(yields[module].values())) > 1]
    overrides = sorted({name for module in shared for name in inventories["toe"][module]["overrides"]})
    runtime = root / "runtime"
    write_if_changed(runtime / "h5_common_imports.h", imports_header(overrides, variable).encode())
    write_if_changed(runtime / "recomp_types.h", runtime_header(ba.ROOT))
    runtime_rel = runtime.relative_to(ba.ROOT).as_posix()
    base = []
    for flag in ba.GENERATED_FLAGS:
        if flag == "-fvisibility=hidden":
            flag = "-fvisibility=protected"
        elif flag == "-Iandroid/runtime":
            flag = "-I" + runtime_rel
        base.append(flag)
    if "-fvisibility=protected" not in base or "-I" + runtime_rel not in base:
        raise SystemExit("[common] build_android.GENERATED_FLAGS changed shape; update tools/common_lib.py")
    compiler_sha = sha_file(ba.CLANG)
    runtime_digest = ba.header_digest([runtime / "recomp_types.h", runtime / "h5_common_imports.h"])
    cache_path = root / "objects.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    jobs, sources, flags_by_module = [], {}, {}
    for module in shared:
        row = inventories["toe"][module]
        folder = row["folder"]
        module_digest = ba.header_digest([runtime / "recomp_types.h", runtime / "h5_common_imports.h"] +
                                         sorted(folder.glob("*.h")))
        constant = yields[module]["toe"]
        extra = ([f"-DRECOMP_YIELD_EVERY={yield_symbol(module)}"] if module in variable else
                 [f"-DRECOMP_YIELD_EVERY={constant}u"] if constant != DEFAULT_YIELD else [])
        flags = base + row["flags"] + extra + ["-I" + folder.relative_to(ba.ROOT).as_posix()]
        flags_by_module[module] = flags
        for name, (digest, text, unchanged) in row["files"].items():
            if unchanged:
                source = folder / name
            else:
                source = root / "patched" / f"{module}-x86" / name
                write_if_changed(source, text)
            sources[f"{module}-x86/{name}"] = digest
            obj = root / "obj" / f"{module}-x86" / (Path(name).stem + ".o")
            fp = sha_bytes(json.dumps([sha_file(source), module_digest, compiler_sha, flags]).encode())
            jobs.append((source, obj, flags, fp))
    guest = ba.ROOT / "android/host/guest_mem.c"
    guest_flags = ba.COMMON + ["-O2"] + (["-flto=thin"] if "thinlto" in modes else [])
    jobs.append((guest, root / "obj/guest_mem.o", guest_flags,
                 sha_bytes(json.dumps([sha_file(guest), compiler_sha, guest_flags]).encode())))
    headers = {module: inventories["toe"][module]["headers"] for module in shared}
    inventories.clear()
    jobs.sort(key=lambda job: -job[0].stat().st_size)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    compile_started = time.time()
    compiled = reused = 0
    failures = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(ba.compile_one, s, o, f, fp, cache) for s, o, f, fp in jobs]
        for future in as_completed(futures):
            try:
                rel, status, elapsed, entry = future.result()
            except RuntimeError as error:
                failures.append(str(error))
                print(str(error), flush=True)
                continue
            cache[rel] = entry
            compiled += status == "compiled"
            reused += status != "compiled"
            if status == "compiled" and elapsed > 20:
                print(f"[slow] {rel}: {elapsed:.1f}s", flush=True)
            if (compiled + reused) % 25 == 0:
                cache_path.write_text(json.dumps(cache, indent=1))
    cache_path.write_text(json.dumps(cache, indent=1))
    print(f"[common] compiled {compiled}, reused {reused}, failed {len(failures)} in {time.time() - compile_started:.0f}s", flush=True)
    if failures:
        sys.exit(1)
    script = root / "exports.map"
    write_if_changed(script, b"/* " + LIBRARY.encode() + b": the engines' dispatch tables and host calls. */\n"
                             b"{ global: sub_*; local: *; };\n")
    response = root / "link.rsp"
    response.write_text("\n".join(str(job[1]).replace("\\", "/") for job in jobs))
    output = root / LIBRARY
    link = [str(ba.CLANG), "--target=" + ba.TARGET, "-fuse-ld=lld", "-shared", "-Wl,-soname," + LIBRARY,
            "-Wl,--gc-sections", "-Wl,-z,nostart-stop-gc", "-Wl,-z,max-page-size=16384", "-Wl,--build-id=sha1",
            "-Wl,--version-script=" + script.as_posix(), "@" + str(response), "-o", str(output), "-lm"]
    if "thinlto" in modes:
        link += ["-flto=thin", "-Wl,--lto-O2", "-Wl,-mllvm,-basic-aa-separate-storage",
                 "-Wl,--thinlto-jobs=" + str(args.thinlto_jobs or 4),
                 "-Wl,--thinlto-cache-dir=" + (root / "thin-cache").as_posix(),
                 "-Wl,--thinlto-cache-policy=cache_size=0%:cache_size_bytes=4g:prune_interval=0s"]
    link_started = time.time()
    result = subprocess.run(link, cwd=ba.ROOT, capture_output=True, text=True)
    if result.returncode:
        print(result.stderr[-6000:])
        sys.exit(1)
    info = elf_dynamic(output)
    expected = {PREFIX + name for name in RUNTIME_IMPORTS + tuple(overrides)} | {yield_symbol(m) for m in variable}
    unexpected = sorted(imported(info) - expected)
    if info["soname"] != LIBRARY or unexpected or set(info["needed"]) - SYSTEM_LIBRARIES:
        raise SystemExit(f"[common] {output}: soname {info['soname']}, needed {info['needed']}, "
                         f"unexpected imports {unexpected[:12]}")
    exports = sorted(exported(info))
    if any(not name.startswith("sub_") for name in exports):
        raise SystemExit("[common] the library exports more than sub_*: " + ", ".join(n for n in exports if not n.startswith("sub_"))[:400])
    receipt = dict(
        library=LIBRARY, library_sha256=sha_file(output), modules=shared, excluded=excluded,
        config=config(ba.CLANG, modes, pgo, ba.ROOT), profile_sha256=sha_file(args.pgo_use) if pgo else None,
        sources=sources, headers=headers,
        flags=flags_by_module, imports=sorted(imported(info)), yields={m: yields[m] for m in variable},
        constant_yields={m: yields[m]["toe"] for m in shared if m not in variable},
        exports=len(exports), exports_sha256=sha_bytes("\n".join(exports).encode()))
    receipt["config_sha256"] = sha_bytes(canonical(receipt["config"]).encode())
    receipt["sources_sha256"] = sha_bytes(canonical(sources).encode())
    receipt_path(modes, ba.ROOT).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"linked {output} ({output.stat().st_size / 1e6:.1f} MB; {len(sources)} sources of "
          f"{', '.join(shared)}; {len(exports)} exports, {len(receipt['imports'])} imports) in "
          f"{time.time() - link_started:.0f}s", flush=True)
    return 0


# ------------------------------------------------------------------------ engine builds
class Plan:
    def __init__(self, receipt, shared, root):
        self.receipt, self.shared, self.root = receipt, shared, root


def engine_plan(ba, args, modes, prepared_generated, rebuild=True):
    """For build_android.py --common-lib: the generated sources the library already holds,
    after checking that this engine transforms each into exactly the bytes it was built from.
    A missing or stale library is rebuilt once (build_android.py --common)."""
    pgo = not args.no_pgo and bool(profile_inputs(ba.ROOT))
    problem = None
    try:
        receipt = load_receipt(modes, ba.ROOT)
        if receipt.get("config") != config(ba.CLANG, modes, pgo, ba.ROOT):
            problem = "built with another compiler, builder, runtime header, mode or profile"
    except ValueError as error:
        receipt, problem = None, str(error)
    by_name = {f"{original.parent.name}/{original.name}": (original, source)
               for original, source, _ in prepared_generated}
    if receipt and not problem:
        for relative, digest in receipt["sources"].items():
            row = by_name.get(relative)
            if row is None:
                problem = f"{relative} is not a source of {ba.EDITION}"
                break
            if sha_file(row[1]) != digest:
                problem = f"{ba.EDITION} transforms {relative} differently"
                break
        for module in receipt["modules"] if not problem else ():
            names = sorted(name for name in by_name if name.startswith(module + "-x86/") and not name.endswith("/recomp_dispatch.c"))
            if names != sorted(name for name in receipt["sources"] if name.startswith(module + "-x86/")):
                problem = f"{ba.EDITION}'s {module} has other source files"
                break
            referenced = set()
            for name in names:
                referenced.update(REFERENCE.findall(Path(by_name[name][1]).read_bytes()))
            if header_view(ba.GENERATED / f"{module}-x86", referenced) != receipt["headers"][module]:
                problem = f"{ba.EDITION}'s {module} headers differ"
                break
    if problem:
        if not rebuild:
            raise SystemExit(f"{LIBRARY}: {problem}")
        print(f"[common] {LIBRARY} needs a build: {problem}", flush=True)
        command = [sys.executable, "-X", "utf8", str(Path(ba.__file__).resolve()), "--common", "--shared",
                   "--jobs", str(args.jobs), *("--" + flag for flag in mode_flags(modes)),
                   *(["--no-pgo"] if not pgo else []),
                   *(["--thinlto-jobs", str(args.thinlto_jobs)] if args.thinlto_jobs else [])]
        if subprocess.run(command, cwd=ba.ROOT).returncode:
            raise SystemExit(f"{LIBRARY} build failed")
        return engine_plan(ba, args, modes, prepared_generated, rebuild=False)
    shared = {by_name[relative][0] for relative in receipt["sources"]}
    print(f"[common] {len(shared)} generated sources ({', '.join(receipt['modules'])}) come from {LIBRARY}", flush=True)
    return Plan(receipt, shared, common_root(modes, ba.ROOT))


def engine_link(ba, plan, output):
    """The engine's output path and extra link inputs: the edition's yield constants, the
    library itself, $ORIGIN and the h5x_ aliases of the runtime the library imports."""
    folder = engine_root(output.parent)
    folder.mkdir(parents=True, exist_ok=True)
    glue = ["/* Generated by tools/common_lib.py: " + ba.EDITION + "'s constants for " + LIBRARY + ". */",
            "#include <stdint.h>"]
    defined = set()
    for module, values in sorted(plan.receipt["yields"].items()):
        glue.append(f'__attribute__((visibility("protected"))) const uint32_t {yield_symbol(module)} = {values[ba.EDITION]}u;')
        defined.add(yield_symbol(module))
        if values[ba.EDITION] != yield_value(ba, module, ba.EDITION):
            raise SystemExit(f"{LIBRARY}: {module}'s hand-off interval for {ba.EDITION} changed; rebuild it with --common")
    source = folder / "h5_common_link.c"
    write_if_changed(source, ("\n".join(glue) + "\n").encode())
    obj = folder / "h5_common_link.o"
    result = subprocess.run([str(ba.CLANG), "--target=" + ba.TARGET, "-O2", "-fPIC", "-c", str(source), "-o", str(obj)],
                            cwd=ba.ROOT, capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stderr[-3000:])
    aliases = []
    for name in plan.receipt["imports"]:
        if name in defined:
            continue
        if not name.startswith(PREFIX):
            raise SystemExit(f"{LIBRARY} imports {name}, which no engine defines")
        aliases.append(f"-Wl,--defsym={name}={name[len(PREFIX):]}")
    library = plan.root / LIBRARY
    return folder / output.name, [str(obj), str(library), "-Wl,-rpath,$ORIGIN", *aliases]


def engine_record(ba, plan, output):
    """<engine>.common.json: which library build this engine was linked and checked against."""
    library = plan.root / LIBRARY
    if sha_file(library) != plan.receipt["library_sha256"]:
        raise SystemExit(f"{library} changed while the engine was linked")
    check_pair(output, elf_dynamic(output), elf_dynamic(library), plan.receipt["imports"])
    record = dict(edition=ba.EDITION, library_sha256=sha_file(output),
                  common_sha256=plan.receipt["library_sha256"], config_sha256=plan.receipt["config_sha256"],
                  sources_sha256=plan.receipt["sources_sha256"])
    record_path(output).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


# ---------------------------------------------------------------------------- packaging
def validate_package(engines, modes, clang, root=ROOT):
    """build_game_apk.py: the library every engine (edition -> path) was linked against, after
    checking its receipt against the current compiler/builder/header/profiles, each engine's
    link record and both libraries' dynamic tables."""
    receipt = load_receipt(modes, root)
    library = common_root(modes, root) / LIBRARY
    if receipt["config"] != config(clang, modes, receipt["config"]["pgo"], root):
        raise ValueError(f"{library} was built with another compiler, builder, runtime header or profile; "
                         "rebuild it with --common")
    common_info = elf_dynamic(library)
    for edition, engine in engines.items():
        engine = Path(engine)
        try:
            record = json.loads(record_path(engine).read_text(encoding="utf-8"))
        except (OSError, ValueError) as failure:
            raise ValueError(f"{edition}: {engine} has no {LIBRARY} link record; build it with --common-lib") from failure
        expected = dict(edition=edition, library_sha256=sha_file(engine), common_sha256=receipt["library_sha256"],
                        config_sha256=receipt["config_sha256"], sources_sha256=receipt["sources_sha256"])
        if record != expected:
            raise ValueError(f"{edition}: {engine} was linked against another {LIBRARY} build; relink it with --common-lib")
        check_pair(engine, elf_dynamic(engine), common_info, receipt["imports"])
    return library, receipt


def require_whole(engine):
    """A whole engine (build_android.py --monolithic) must not need the library."""
    info = elf_dynamic(engine)
    if LIBRARY in info["needed"]:
        raise ValueError(f"{engine} was linked against {LIBRARY}")
