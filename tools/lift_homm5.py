"""Generate checked static x86-to-C code for the installed Heroes V modules.

    python tools/lift_homm5.py [--module NAME] [--upx PATH]

Original files stay untouched. Packed inputs are unpacked privately, and DLLs
are relocated before cataloging so every generated symbol uses its live VA.
"""
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import pefile
from lift_game import ROOT, collect_functions, emit_dispatch, emit_functions
from pe_rebase import rebase_image
from fpu_cache import cache_particle_math_source
from editions import EDITION_IDS, generated_root, module_manifest, game_directory

EDITION = "toe"
GENERATED = generated_root()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def prepare(spec, game, upx):
    source = game / spec["source"]
    raw = source.read_bytes()
    if digest(raw) != spec["sha256"]:
        raise ValueError(f"{spec['file']}: original SHA-256 mismatch")
    unpacked = raw
    if spec.get("unpack"):
        path = ROOT / ("build/unpacked" if EDITION == "toe" else f"build/unpacked-{EDITION}") / spec["file"]
        receipt = path.with_suffix(path.suffix + ".json")
        old = read_json(receipt) if receipt.exists() else {}
        if (path.exists() and old.get("original_sha256") == digest(raw)
                and old.get("unpacked_sha256") == digest(path.read_bytes())):
            unpacked = path.read_bytes()
        else:
            if not upx:
                raise ValueError(f"{spec['file']}: supply --upx to unpack the private copy")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            subprocess.run([str(upx), "-d", str(path)], check=True)
            unpacked = path.read_bytes()
            write_json(receipt, {"original_sha256": digest(raw), "unpacked_sha256": digest(unpacked)})
    pe = pefile.PE(data=unpacked)
    if pe.FILE_HEADER.Machine != 0x14C or pe.OPTIONAL_HEADER.Magic != 0x10B:
        raise ValueError(f"{spec['file']}: expected PE32 i386")
    if any(s.Name.startswith(b"UPX") for s in pe.sections):
        raise ValueError(f"{spec['file']}: packed sections remain")
    if pe.OPTIONAL_HEADER.DATA_DIRECTORY[13].VirtualAddress:
        raise ValueError(f"{spec['file']}: delay imports need explicit loader support")
    base = int(spec["base"], 0)
    original_base = pe.OPTIONAL_HEADER.ImageBase
    rebased = unpacked if original_base == base else rebase_image(unpacked, base)[0]
    if original_base != base and rebase_image(rebased, original_base)[0] != unpacked:
        raise ValueError(f"{spec['file']}: reverse relocation does not reproduce input")
    binary = GENERATED / "input" / spec["file"]
    binary.parent.mkdir(parents=True, exist_ok=True)
    if not binary.exists() or binary.read_bytes() != rebased:
        binary.write_bytes(rebased)
    return binary, {"binary_sha256": digest(raw), "unpacked_sha256": digest(unpacked),
                    "rebased_sha256": digest(rebased), "base": hex(base),
                    "span": hex(pe.OPTIONAL_HEADER.SizeOfImage),
                    "input_image": binary.relative_to(ROOT).as_posix()}


def catalog(binary, name, sha256):
    path = ROOT / f"config/{name}.catalog.json" if EDITION == "toe" else GENERATED / "catalog" / f"{name}.catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = path.with_suffix(".sha256")
    if not path.exists() or not receipt.exists() or receipt.read_text().strip() != sha256:
        subprocess.run([sys.executable, str(ROOT / "reference/pcrecomp/tools/disasm/disasm32.py"),
                        str(binary), "--output", str(path)], check=True)
        receipt.write_text(sha256 + "\n")
    rows = read_json(path)["functions"]
    if len({r["address"] for r in rows}) != len(rows):
        raise ValueError(f"{name}: duplicate function catalog addresses")
    return [{"address": r["address"], "size": r["size"]} for r in rows]


def previous_entries(specs):
    entries, headers = [], []
    for spec in specs:
        name = spec["name"]
        directory = GENERATED / f"{name}-x86"
        if not (directory / "report.json").exists():
            continue
        report = read_json(directory / "report.json")
        if report.get("status") != "GENERATED":
            continue
        entries.extend(int(a, 0) for a in report["dispatch_entries"])
        headers.append(f"../{name}-x86/{name}_funcs.h")
    if len(set(entries)) != len(entries):
        raise ValueError("Overlapping previous module dispatch entries")
    return entries, headers


def merge_dispatch(specs):
    entries, headers = previous_entries(specs)
    completed = [s for s in specs if (GENERATED / f"{s['name']}-x86/report.json").exists()
                 and read_json(GENERATED / f"{s['name']}-x86/report.json").get("status") == "GENERATED"]
    if completed:
        directory = GENERATED / f"{completed[-1]['name']}-x86"
        destination = directory / "recomp_dispatch.c"
        emit_dispatch(destination, entries, headers)
        report = read_json(directory / "report.json")
        report["merged_dispatch_entries"] = len(entries)
        report["dispatch_source"] = "recomp_dispatch.c"
        write_json(directory / "report.json", report)


def finalize_sources(directory, sources):
    """Fail closed for inherited x87 save no-ops and count unique guest trap sites."""
    noop = re.compile(r'/\* (?:fnsave|fsave|frstor): FPU state is not a memory image here \*/ '
                      r'(/\* 0x([0-9A-F]{8}): ([^\r\n]*?) \*/)')
    traps, containing = set(), []
    for file in sources:
        path = directory / file
        text = path.read_text(encoding="utf-8")
        fixed = noop.sub(lambda m: f"void_lift_trap(0x{m[2]}u, {json.dumps(m[3])}); {m[1]}", text)
        if "FPU state is not a memory image here" in fixed:
            raise ValueError(f"{path}: unmatched inherited x87 no-op")
        if EDITION == "toe":
            fixed = cache_particle_math_source(fixed)
        if fixed != text:
            path.write_text(fixed, encoding="utf-8")
        traps.update((address, json.loads(instruction)) for address, instruction in re.findall(
            r'void_lift_trap\(0x([0-9A-F]+)u, ("(?:[^"\\]|\\.)*")\);', fixed))
        functions = list(re.finditer(r'^void sub_([0-9A-F]+)\(void\) \{', fixed, re.M))
        for index, match in enumerate(functions):
            end = functions[index + 1].start() if index + 1 < len(functions) else len(fixed)
            if "void_lift_trap(" in fixed[match.end():end]:
                containing.append(hex(int(match[1], 16)))
    return [{"address": "0x" + address, "instruction": instruction} for address, instruction in sorted(traps)], containing


def refresh_traps(specs):
    for spec in specs:
        directory = GENERATED / f"{spec['name']}-x86"
        path = directory / "report.json"
        if not path.exists():
            continue
        report = read_json(path)
        if report.get("status") != "GENERATED":
            continue
        traps, containing = finalize_sources(directory, report["sources"])
        write_json(directory / "static-traps.json", traps)
        report.update(unique_static_trap_sites=len(traps), functions_containing_traps=containing)
        write_json(path, report)
        print(f"{spec['name']}: {len(traps)} unique static traps", flush=True)


def regenerate_function(spec, address, game, upx):
    """Replace one existing emitted body; preserve its original local CFG and EH."""
    name = spec["name"]
    directory = GENERATED / f"{name}-x86"
    report = read_json(directory / "report.json")
    if report.get("status") != "GENERATED":
        raise ValueError(f"{name}: complete generation is required before a targeted repair")
    entries = [int(a, 0) for a in report["dispatch_entries"]]
    index = entries.index(address)
    binary, _ = prepare(spec, game, upx)
    info = pefile.PE(str(binary))
    if not int(spec["base"], 0) <= address < int(spec["base"], 0) + info.OPTIONAL_HEADER.SizeOfImage:
        raise ValueError("Target function is outside its module")
    from lift_game import BoundedDisassembler, analyze_pe, build_iat_map, complete_eh_owner
    parsed = analyze_pe(str(binary))
    imports = build_iat_map(parsed)
    table_rows = read_json(ROOT / spec["jump_tables"]) if spec.get("jump_tables") else []
    tables = {int(r["address"], 0): (r["first_index"], r["count"]) for r in table_rows}
    decoder = BoundedDisassembler(binary.read_bytes(), parsed.image_base, parsed.sections, jump_tables=tables)
    function = decoder.disassemble_function(address, imports)
    complete_eh_owner(decoder, function, imports)
    source = directory / report["sources"][index // 100]
    text = source.read_text(encoding="utf-8")
    symbol = f"void sub_{address:08X}(void) {{"
    if text.count(symbol) != 1:
        raise ValueError("Target source/body does not match the dispatch report")
    start = text.index(symbol)
    end = text.find("\nvoid sub_", start + 1)
    end = len(text) if end < 0 else end
    with tempfile.TemporaryDirectory(prefix="h5-function-") as temporary:
        output = Path(temporary)
        emitted = emit_functions(output, imports, decoder, {address: function}, additional_entries=entries)
        replacement = (output / emitted["sources"][0]).read_text(encoding="utf-8")
        replacement = replacement[replacement.index(symbol):].rstrip() + "\n\n"
    source.write_text(text[:start] + replacement + text[end:], encoding="utf-8")
    refresh_traps([spec])
    print(f"Repaired {name} 0x{address:08X} in {source.relative_to(ROOT)}", flush=True)


def generate(spec, prior, game, upx):
    name = spec["name"]
    directory = GENERATED / f"{name}-x86"
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / "report.json", {"status": "GENERATING", "module": spec["file"]})
    binary, proof = prepare(spec, game, upx)
    rows = catalog(binary, name, proof["rebased_sha256"])
    pe = pefile.PE(str(binary))
    exports = pe.DIRECTORY_ENTRY_EXPORT.symbols if hasattr(pe, "DIRECTORY_ENTRY_EXPORT") else []
    seeds = [pe.OPTIONAL_HEADER.ImageBase + e.address
             for e in exports
             if not e.forwarder and any(s.IMAGE_SCN_MEM_EXECUTE and s.contains_rva(e.address) for s in pe.sections)]
    if hasattr(pe, "DIRECTORY_ENTRY_TLS"):
        tls = pe.DIRECTORY_ENTRY_TLS.struct
        callbacks = tls.AddressOfCallBacks
        while callbacks:
            value = int.from_bytes(pe.get_data(callbacks - pe.OPTIONAL_HEADER.ImageBase, 4), "little")
            if not value:
                break
            seeds.append(value)
            callbacks += 4
    table_rows = read_json(ROOT / spec["jump_tables"]) if spec.get("jump_tables") else []
    tables = {int(row["address"], 0): (row["first_index"], row["count"]) for row in table_rows}
    if len(tables) != len(table_rows):
        raise ValueError(f"{name}: duplicate declared jump tables")
    info, imports, decoder, functions, rejected = collect_functions(binary, rows, seeds, label=spec["file"],
        max_entries=250000, compact=spec["exe"], jump_tables=tables)
    old_entries, headers = previous_entries(prior)
    if set(old_entries) & set(functions):
        raise ValueError(f"{name}: dispatch overlap")
    emitted = emit_functions(directory, imports, decoder, functions, label=spec["file"],
                             header_name=f"{name}_funcs.h", chunk_prefix=name,
                             additional_entries=old_entries)
    emit_dispatch(directory / "recomp_dispatch.c", [*old_entries, *functions], [*headers, f"{name}_funcs.h"])
    traps, emitted["functions_containing_traps"] = finalize_sources(directory, emitted["sources"])
    write_json(directory / "static-traps.json", traps)
    report = {"status": "GENERATED", "module": spec["file"], **proof, **emitted,
              "entry": hex(info.image_base + info.entry_point_rva), "dispatch_entries": [hex(a) for a in sorted(functions)],
              "merged_dispatch_entries": len(old_entries) + len(functions), "unique_static_trap_sites": len(traps),
              "rejected_non_catalog_entries": rejected, "declared_jump_tables": len(tables), "whole_game": "UNVERIFIED"}
    write_json(directory / "report.json", report)
    (directory / f"{name}_entry.h").write_text(
        f"#define {name.upper()}_BASE 0x{info.image_base:08X}u\n"
        f"#define {name.upper()}_ENTRY 0x{info.image_base + info.entry_point_rva:08X}u\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("module", "functions", "merged_dispatch_entries", "unique_static_trap_sites")}), flush=True)
    del functions, decoder, imports
    gc.collect()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=EDITION_IDS, default="toe")
    parser.add_argument("--module", help="Generate only this module and merge all completed modules")
    parser.add_argument("--function", type=lambda value: int(value, 0), help="Replace one existing body in --module without closing the full graph")
    parser.add_argument("--upx", default=os.environ.get("HOMM5_UPX", shutil.which("upx")))
    parser.add_argument("--refresh-traps", action="store_true", help="Normalize existing generated sources and refresh trap reports")
    args = parser.parse_args()
    global EDITION, GENERATED
    EDITION = args.edition
    GENERATED = generated_root(EDITION)
    specs = module_manifest(EDITION)
    if args.refresh_traps:
        refresh_traps(specs)
        return
    if args.module and args.module not in {s["name"] for s in specs}:
        parser.error("Unknown module")
    game = game_directory(EDITION)
    if args.function is not None:
        if not args.module:
            parser.error("--function requires --module")
        regenerate_function(next(s for s in specs if s["name"] == args.module), args.function, game, args.upx)
        return
    for index, spec in enumerate(specs):
        if args.module and spec["name"] != args.module:
            continue
        try:
            generate(spec, specs[:index], game, args.upx)
            if not args.module:
                merge_dispatch(specs)
        except Exception as error:
            write_json(GENERATED / f"{spec['name']}-x86/report.json",
                       {"status": "FAILED", "module": spec["file"], "error": str(error)})
            raise
    if args.module:
        merge_dispatch(specs)


if __name__ == "__main__":
    main()
