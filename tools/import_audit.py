"""Audit lifted PE imports against the exact Android host registrations.

The NDK preprocessor expands the host macros, including aliases and wrappers.
This checks symbol availability; an existing registration may still be a stub.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import pefile
from android_tools import NDK

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = re.compile(
    r'\bconst\s+void_shim\s+\w+\s+[^;{}]*=\s*\{\s*"([^"]+)"\s*,\s*'
    r'(?:"([^"]+)"|[^,]+)\s*,\s*(0[xX][0-9a-fA-F]+|\d+)[uU]?\s*,')


def parse_registrations(text):
    result = set()
    for dll, name, ordinal in REGISTRATION.findall(text):
        if name:
            result.add((dll.lower(), name))
        if int(ordinal, 0):
            result.add((dll.lower(), f"#{int(ordinal, 0)}"))
    return result


def host_registrations(host, clang):
    result, sources = set(), {}
    for path in sorted(host.glob("*.c")):
        if not re.search(r"\b(?:WINAPI_|CDECL_EXPORT|RAW_EXPORT|VOID_SHIM_SECTION)", path.read_text(encoding="utf-8")):
            continue
        command = [str(clang), "--target=aarch64-linux-android30", "-E", "-P", "-DRECOMP_TRACE",
                   "-I" + str(host), "-I" + str(host.parent / "runtime"), str(path)]
        preprocessed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=True)
        entries = parse_registrations(preprocessed.stdout)
        if not entries:
            raise ValueError(f"No host registrations recognized in {path}")
        result.update(entries)
        sources[path.name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "symbols": len(entries)}
    if not result:
        raise ValueError(f"No host registrations found in {host}")
    return result, sources


def parse_aliases(text):
    result = {}
    for condition, target in re.findall(r'if\s*\(([^\n]+)\)\s*name\s*=\s*"([^"]+)"', text):
        for source in re.findall(r'name_matches\(name,\s*"([^"]+)"\)', condition):
            result[source.lower()] = target.lower()
    return result


def module_aliases(host):
    return parse_aliases((host / "pe.c").read_text(encoding="utf-8"))


def read_module(path):
    raw = path.read_bytes()
    pe = pefile.PE(data=raw)
    if pe.FILE_HEADER.Machine != 0x14C or pe.OPTIONAL_HEADER.Magic != 0x10B:
        raise ValueError(f"Expected PE32 i386: {path}")
    exports = {}
    for symbol in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
        if not symbol.address:
            continue
        value = symbol.forwarder.decode("ascii") if symbol.forwarder else None
        exports[f"#{symbol.ordinal}"] = value
        if symbol.name:
            exports[symbol.name.decode("ascii")] = value
    imports = []
    for directory, delay in (("DIRECTORY_ENTRY_IMPORT", False), ("DIRECTORY_ENTRY_DELAY_IMPORT", True)):
        for descriptor in getattr(pe, directory, []):
            for symbol in descriptor.imports:
                imports.append({"dll": descriptor.dll.decode("ascii").lower(),
                                "symbol": symbol.name.decode("ascii") if symbol.name else f"#{symbol.ordinal}",
                                "delay": delay})
    return {"file": path.name, "sha256": hashlib.sha256(raw).hexdigest(),
            "base": pe.OPTIONAL_HEADER.ImageBase, "size": pe.OPTIONAL_HEADER.SizeOfImage,
            "packed": any(section.Name.startswith(b"UPX") for section in pe.sections),
            "tls": bool(pe.OPTIONAL_HEADER.DATA_DIRECTORY[9].VirtualAddress),
            "exports": exports, "imports": imports}


def audit(modules, registered, aliases):
    missing, counts, rows = defaultdict(lambda: defaultdict(set)), Counter(), {}
    for name, module in sorted(modules.items()):
        imports = []
        for imported in module["imports"]:
            dll, symbol = imported["dll"], imported["symbol"]
            target = aliases.get(dll, dll)
            local = modules.get(target)
            if local is not None:
                status = "lifted_export" if symbol in local["exports"] and local["exports"][symbol] is None else "missing"
            else:
                status = "host_registration" if (target, symbol) in registered else "missing"
            counts[status] += 1
            if status == "missing":
                missing[dll][symbol].add(module["file"])
            imports.append({**imported, "resolved_dll": target, "status": status})
        rows[name] = {**{key: value for key, value in module.items() if key != "exports"}, "imports": imports}
    collisions = []
    names = sorted(modules)
    for i, first in enumerate(names):
        a = modules[first]
        for second in names[i + 1:]:
            b = modules[second]
            if a["base"] < b["base"] + b["size"] and b["base"] < a["base"] + a["size"]:
                collisions.append([first, second])
    return {"modules": rows, "counts": dict(counts), "aliases": aliases,
            "missing": {dll: {symbol: sorted(users) for symbol, users in sorted(symbols.items())}
                        for dll, symbols in sorted(missing.items())},
            "packed_modules": [name for name in names if modules[name]["packed"]],
            "base_collisions": collisions,
            "notes": ["Registrations establish symbol availability, including any existing stubs.",
                      "GetProcAddress and LoadLibrary targets are not enumerated by the static import table.",
                      "Packed images must be audited again after unpacking; their imports are incomplete."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, default=ROOT / "generated/input")
    parser.add_argument("--host", type=Path, default=ROOT / "android/host")
    parser.add_argument("--manifest", type=Path, default=ROOT / "config/modules.json")
    parser.add_argument("--output", type=Path, default=ROOT / "build/import_audit.json")
    parser.add_argument("--clang", type=Path, default=NDK / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe")
    parser.add_argument("--strict", action="store_true", help="Fail on missing imports, packed images, delay imports, or image overlaps")
    args = parser.parse_args()
    if not args.bin.is_dir():
        parser.error(f"Input directory does not exist: {args.bin}")
    paths = {path.name.lower(): path for path in args.bin.iterdir() if path.is_file()}
    specs = json.loads(args.manifest.read_text(encoding="utf-8"))
    modules = {row["file"].lower(): read_module(paths[row["file"].lower()]) for row in specs}
    registered, sources = host_registrations(args.host, args.clang)
    report = audit(modules, registered, module_aliases(args.host))
    report["host_sources"] = sources
    report["input_directory"] = str(args.bin.resolve())
    report["delay_import_modules"] = [name for name, module in modules.items() if any(row["delay"] for row in module["imports"])]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    missing = sum(len(symbols) for symbols in report["missing"].values())
    print(json.dumps({"modules": len(modules), "counts": report["counts"], "missing_unique": missing,
                      "packed_modules": report["packed_modules"], "base_collisions": len(report["base_collisions"]),
                      "report": str(args.output.resolve())}, indent=2))
    return int(args.strict and bool(missing or report["packed_modules"] or report["base_collisions"] or report["delay_import_modules"]))


if __name__ == "__main__":
    raise SystemExit(main())
