"""Exact, optional function-entry coverage for build copies of the lifted modules.

This records presence, not call counts or timings. Generated functions and native
guest-entry wrappers have separate IDs, then are unioned by (module, guest VA) in
the report. Native Android libraries/drivers and ordinary host helpers are outside
this inventory. The source transform also covers direct calls within one C file.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct

ROOT = Path(__file__).resolve().parents[1]
DEFINITION = re.compile(r"^void (sub_([0-9A-F]{8})(?:_lifted)?)\(void\)\s*\{", re.M)
ENTRY = re.compile(r"\bRECOMP_ENTER\(0x([0-9A-Fa-f]{8})u\);")
WRAPPER = re.compile(r"\bvoid (__wrap_sub_([0-9A-F]{8}))\s*\(void\)\s*\{")
WRAPPER_MACRO = re.compile(r"\bvoid __wrap_sub_##([A-Za-z_][A-Za-z_0-9]*)\(void\)\s*\{")
HOST_DEFINITION = re.compile(r"\b(?:static\s+)?void\s+([A-Za-z_]\w*)\s*\(void\)\s*\{")
DISPATCH_ADD = re.compile(r"\bvoid_dispatch_add\(\s*([^,()]*)\s*,\s*([^()]*)\s*\)")
MAGIC = b"H5FCOV1\0"
HEADER = struct.Struct("<8sIIIIQQQQQQQ64s")


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def generated_entries(text):
    definitions = [(m[1], m[2]) for m in DEFINITION.finditer(text)]
    entries = [m[1].upper() for m in ENTRY.finditer(text)]
    if [va for _, va in definitions] != entries:
        raise ValueError("Each lifted definition must have exactly one matching RECOMP_ENTER, in source order")
    return definitions


def native_macros(text):
    """The existing one-argument FMOD body macros; fail if their syntax drifts."""
    result = []
    pattern = re.compile(r"^#define\s+(\w+)\((\w+)\)(?:[^\n]*\\\n)+[^\n]*", re.M)
    for macro in pattern.finditer(text):
        name, parameter = macro[1], macro[2]
        body = re.search(r"\bvoid\s+" + re.escape(parameter) + r"\(void\)\s*\{", macro[0])
        if not body:
            continue
        calls = re.findall(r"^" + re.escape(name) + r"\((sub_[0-9A-F]{8})\)\s*$", text, re.M)
        if not calls:
            raise ValueError("Native function macro has no recognized invocations: " + name)
        result.append((macro.start() + body.end(), parameter, calls))
    return result


def native_entries(text):
    result = [(m[1], m[1][4:]) for m in HOST_DEFINITION.finditer(text)
              if re.fullmatch(r"sub_[0-9A-F]{8}", m[1])]
    for _, _, calls in native_macros(text):
        result += [(name, name[4:]) for name in calls]
    if len({name for name, _ in result}) != len(result):
        raise ValueError("Duplicate native original-address body")
    return result


def wrapper_entries(text):
    """Recognise ordinary wrappers and the existing simple token-paste macro.

    Unexpected wrapper syntax is rejected when the declared wrap set is checked,
    so a new wrapper cannot silently disappear from the inventory.
    """
    result = [(m[1], m[2]) for m in WRAPPER.finditer(text)]
    for match in WRAPPER_MACRO.finditer(text):
        prefix = text[:match.start()]
        # Select the immediately preceding multiline macro declaration.
        macros = list(re.finditer(r"^#define\s+(\w+)\([^\n]*\\\s*$", prefix, re.M))
        if not macros:
            raise ValueError("Unrecognised token-paste wrapper declaration")
        name = macros[-1][1]
        invocations = re.findall(r"^" + re.escape(name) + r"\(([0-9A-F]{8})\s*,", text, re.M)
        if not invocations:
            raise ValueError("Wrapper macro has no recognised invocations")
        result += [("__wrap_sub_" + va, va) for va in invocations]
    if len({name for name, _ in result}) != len(result):
        raise ValueError("Duplicate native wrapper definition")
    return result


def included_host_text(text):
    """The .inc files of android/host a host source includes (a replacement may be defined in one)."""
    return "\n".join((ROOT / "android/host" / name).read_text(encoding="utf-8", errors="replace")
                     for name in re.findall(r'#include "([A-Za-z0-9_]+\.inc)"', text)
                     if (ROOT / "android/host" / name).is_file())


def override_entries(text):
    """Resolve explicit original-VA dispatch replacements, including enum names.

    Variable-address table maintenance and restoring saved original pointers are
    not new implementations. A constant address with an unknown named function,
    or a known function registered under an unresolved address, fails closed.
    """
    constants = dict(re.findall(r"(?:#define\s+|\b)([A-Za-z_]\w*)\s*(?:=\s*|\s+)(0x[0-9A-Fa-f]+)[uUlL]*", text))
    definitions = {m[1] for m in HOST_DEFINITION.finditer(text)}
    result = {}
    for match in DISPATCH_ADD.finditer(text):
        address, symbol = match[1].strip(), match[2].strip()
        if symbol.startswith("__wrap_sub_"):
            continue  # Already checked against the link wrap list.
        literal = constants.get(address, address)
        known_address = re.fullmatch(r"0x[0-9A-Fa-f]+[uUlL]*", literal)
        if not known_address:
            if symbol in definitions:
                raise ValueError(f"Unresolved dispatch override address {address} for {symbol}")
            continue  # Runtime hash maintenance uses variable VA/function values.
        if not re.fullmatch(r"[A-Za-z_]\w*", symbol):
            if re.fullmatch(r"[A-Za-z_]\w*\[\d+\]", symbol):
                continue  # Restore a previously saved original entry.
            raise ValueError(f"Unknown dispatch replacement expression: {symbol}")
        if symbol not in definitions:
            raise ValueError(f"Dispatch replacement has no local definition: {symbol}")
        va = f"{int(literal.rstrip('uUlL'), 16):08X}"
        if symbol in result and result[symbol] != va:
            raise ValueError(f"One native override has multiple guest addresses: {symbol}")
        result[symbol] = va
    return sorted(result.items())


class CoveragePlan:
    """Inventory once, then instrument sources after other build transforms."""

    def __init__(self, manifest, output):
        self.manifest = manifest
        self.output = Path(output).resolve()
        self.by_key = {(r["module"], r["address"], r["kind"]): r for r in manifest["entries"]}
        self.wrappers = {r["symbol"]: r for r in manifest["entries"] if r["kind"] == "native_override"}
        self.overrides = {r["symbol"]: r for r in manifest["entries"] if r["kind"] == "native_dispatch"}
        self.header = self.output / "function_coverage_ids.h"
        self.manifest_path = self.output / "manifest.json"

    @classmethod
    def create(cls, generated, lifted, host_sources, wraps, output, specs=None, edition="toe", manual_entries=(), build_identity=None):
        generated = Path(generated).resolve()
        host_sources = tuple(map(Path, host_sources))
        if specs is None:
            from editions import module_manifest
            specs = module_manifest(edition)
        modules = {r["name"]: r for r in specs}
        entries, addresses, module_counts, sources = [], {}, Counter(), []
        for path in sorted(map(Path, lifted)):
            module = path.parent.name.removesuffix("-x86")
            if module not in modules:
                if generated_entries(path.read_text(encoding="utf-8")):
                    raise ValueError(f"Lifted functions in unknown module: {path}")
                continue
            text = path.read_text(encoding="utf-8")
            logical = f"{module}-x86/{path.name}"
            sources.append(dict(source=logical, sha256=digest_bytes(text.encode())))
            for symbol, va in generated_entries(text):
                key = (module, va)
                if key in addresses:
                    raise ValueError(f"Duplicate lifted entry {key}")
                item = {"module": module, "image": modules[module]["file"], "address": va,
                        "symbol": symbol, "kind": "lifted", "source": logical,
                        "manual_algorithmic_port": False}
                entries.append(item)
                addresses[key] = item
                module_counts[module] += 1
        expected = set(wraps)
        found = set()
        override_symbols = set()
        for path in sorted(map(Path, host_sources)):
            text = path.read_text(encoding="utf-8")
            sources.append(dict(source="android/host/" + path.name, sha256=digest_bytes(text.encode())))
            for symbol, va in native_entries(text):
                original = symbol
                if original not in expected:
                    raise ValueError(f"Native body absent from override list: {symbol}")
                if original in found:
                    raise ValueError(f"Duplicate wrapper: {symbol}")
                found.add(original)
                candidates = [r for (mod, addr), r in addresses.items() if addr == va]
                if len(candidates) != 1:
                    raise ValueError(f"Wrapper guest module is ambiguous or absent: {symbol}")
                item = candidates[0].copy()
                item.update(symbol=symbol, kind="native_override", source=path.name)
                entries.append(item)
            for symbol, va in override_entries(text):
                if symbol in override_symbols:
                    raise ValueError(f"Native override symbol ambiguous between host files: {symbol}")
                override_symbols.add(symbol)
                candidates = [r for (mod, addr), r in addresses.items() if addr == va]
                if len(candidates) != 1:
                    raise ValueError(f"Native override guest module is ambiguous or absent: {symbol}")
                item = candidates[0].copy()
                item.update(symbol=symbol, kind="native_dispatch", source=path.name)
                entries.append(item)
        if expected != found:
            raise ValueError(f"Uninstrumented wrappers: {sorted(expected - found)}")
        # A future hand-written implementation must explicitly name its source,
        # original module/VA and symbol; observing an adapter never proves this.
        for record in manual_entries:
            required = {"module", "address", "symbol", "source", "manual_algorithmic_port"}
            if (not required <= set(record) or set(record) - required - {"global_route"} or
                    record["manual_algorithmic_port"] is not True or
                    ("global_route" in record and type(record["global_route"]) is not bool)):
                raise ValueError("Invalid explicit manual implementation record")
            key = (record["module"], record["address"])
            if key not in addresses or any(r["symbol"] == record["symbol"] for r in entries):
                raise ValueError("Missing original or duplicate manual implementation")
            path = next((p for p in map(Path, host_sources) if p.name == record["source"]), None)
            if path is None or record["symbol"] not in {m[1] for m in HOST_DEFINITION.finditer(path.read_text())}:
                raise ValueError("Manual implementation has no actual body")
            entries.append(dict(addresses[key], **record, kind="manual_native"))
        entries.sort(key=lambda r: (r["module"], int(r["address"], 16), r["kind"], r["symbol"]))
        for index, entry in enumerate(entries):
            entry["id"] = index
        payload = {"version": 1, "edition": edition, "scope": "lifted module bodies, native original-VA adapter bodies and explicit dispatch replacement bodies; all calling threads",
                   "excluded": "ordinary native host helpers, COM/import/export thunks without an original generated VA, dynamic dispatch table maintenance, external native libraries, Android framework, libc and drivers",
                   "meaning": "exact entered-function union, not call counts, costs, semantic reachability or an unused-code proof; a native adapter is not automatically a manual algorithmic port",
                   "sources": sources, "build_identity": build_identity or {}, "collector_sha256": digest_bytes(Path(__file__).read_bytes()),
                   "runtime_sha256": digest_bytes((ROOT / "tools/function_coverage_runtime.c").read_bytes()),
                   "header_sha256": digest_bytes((ROOT / "tools/function_coverage_runtime.h").read_bytes()),
                   "modules": [{"name": name, "image": modules[name]["file"],
                                "image_sha256": modules[name].get("sha256"), "generated_entries": count}
                               for name, count in sorted(module_counts.items())], "entries": entries}
        payload["identity_sha256"] = digest_bytes(canonical(payload))
        plan = cls(payload, output)
        plan.output.mkdir(parents=True, exist_ok=True)
        plan.manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        plan.header.write_text(
            "/* Generated inventory; diagnostic builds only. */\n#pragma once\n"
            f"#define VOID_FC_COUNT {len(entries)}u\n#define VOID_FC_WORDS {(len(entries) + 63) // 64}u\n"
            f'#define VOID_FC_IDENTITY "{payload["identity_sha256"]}"\n' +
            "".join(f'#define VOID_FC_NATIVE_{r["symbol"]} {r["id"]}u\n' for r in entries if r["kind"] != "lifted"),
            encoding="utf-8")
        return plan

    def instrument_generated(self, text, module):
        generated_entries(text)  # Fail closed if upstream generator syntax changes.
        count = 0

        def replace(match):
            nonlocal count
            record = self.by_key[(module.removesuffix("-x86"), match[1].upper(), "lifted")]
            count += 1
            return f'VOID_FUNCTION_COVERAGE_HIT({record["id"]}u); ' + match[0]

        rewritten = ENTRY.sub(replace, text)
        if count:
            rewritten = '#include "function_coverage_runtime.h"\n' + rewritten
        return rewritten, count

    def instrument_host(self, text, name=""):
        entries = native_entries(text)
        overrides = override_entries(text)
        for symbol, _ in entries:
            if symbol not in self.wrappers:
                raise ValueError(f"Unknown wrapper {symbol}")
        rewritten = text
        for offset, parameter, _ in reversed(native_macros(text)):
            rewritten = rewritten[:offset] + f' VOID_FUNCTION_COVERAGE_HIT(VOID_FC_NATIVE_##{parameter});' + rewritten[offset:]
        for symbol, va in overrides:
            if symbol not in self.overrides or self.overrides[symbol]["address"] != va:
                raise ValueError(f"Unknown native override: {symbol} at {va}")
        by_symbol = {r["symbol"]:r for r in self.manifest["entries"] if r["kind"] != "lifted"}
        rewritten = HOST_DEFINITION.sub(lambda m: m[0] +
            (f' VOID_FUNCTION_COVERAGE_HIT({by_symbol[m[1]]["id"]}u);' if m[1] in by_symbol else ""), rewritten)
        if name == "script.c":
            anchor = '    if (!strcmp(e->action, "key")) {'
            if text.count(anchor) != 1:
                raise ValueError("Script command anchor changed")
            rewritten = rewritten.replace(anchor,
                '    if (!strcmp(e->action, "fcstart")) {\n'
                '        void_log("[coverage] start %d", void_function_coverage_begin(void_data_dir()));\n'
                '    } else if (!strcmp(e->action, "fcstop")) {\n'
                '        void_log("[coverage] stop/export %d", void_function_coverage_finish());\n'
                '    } else if (!strcmp(e->action, "key")) {')
        if rewritten != text:
            rewritten = '#include "function_coverage_runtime.h"\n' + rewritten
        manual_symbols = {r["symbol"] for r in self.manifest["entries"] if r["kind"] == "manual_native"}
        manual_count = sum(m[1] in manual_symbols for m in HOST_DEFINITION.finditer(text))
        return rewritten, len(entries) + len(overrides) + manual_count

    def write_copy(self, text, category, module, name):
        path = self.output / category / module / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
        return path


def decode(manifest, binary):
    manifest = json.loads(Path(manifest).read_text(encoding="utf-8"))
    identity = manifest.pop("identity_sha256")
    if digest_bytes(canonical(manifest)) != identity:
        raise ValueError("Coverage manifest identity mismatch")
    manifest["identity_sha256"] = identity
    entries = manifest["entries"]
    if not entries or [r.get("id") for r in entries] != list(range(len(entries))):
        raise ValueError("Noncanonical coverage entry IDs")
    keys = [(r["module"], r["address"], r["kind"], r["symbol"]) for r in entries]
    if len(set(keys)) != len(keys) or any(not re.fullmatch("[0-9A-F]{8}", r["address"]) for r in entries):
        raise ValueError("Duplicate or malformed coverage implementation")
    data = Path(binary).read_bytes()
    if len(data) < HEADER.size:
        raise ValueError("Truncated coverage header")
    magic, version, count, words, reserved, accepted, start_before, start_after, stop_before, stop_after, warmup, duration, recorded_identity = HEADER.unpack_from(data)
    if magic != MAGIC or version != 1 or reserved != 0:
        raise ValueError("Unknown coverage binary format")
    if count != len(manifest["entries"]) or words != (count + 63) // 64 or recorded_identity.decode("ascii") != identity:
        raise ValueError("Coverage binary belongs to a different instrumented build")
    if len(data) != HEADER.size + words * 16:
        raise ValueError("Truncated or trailing coverage bitmap data")
    cumulative = struct.unpack_from(f"<{words}Q", data, HEADER.size)
    window = struct.unpack_from(f"<{words}Q", data, HEADER.size + words * 8)
    if any(w & ~c for c, w in zip(cumulative, window)):
        raise ValueError("Window entries are not a subset of cumulative entries")
    if count % 64 and ((cumulative[-1] | window[-1]) >> (count % 64)):
        raise ValueError("Set bits outside the function inventory")
    if not accepted <= start_before <= start_after <= stop_before <= stop_after:
        raise ValueError("Invalid monotonic coverage timestamps")
    result = {"status": "EXACT_FUNCTION_ENTRY_UNION", "identity_sha256": identity,
              "edition": manifest.get("edition"),
              "scope": manifest["scope"], "excluded": manifest["excluded"], "meaning": manifest["meaning"],
              "inventory_entries": count, "request_accepted_ns": accepted,
              "arm_monotonic_ns_bracket": [start_before, start_after],
              "close_monotonic_ns_bracket": [stop_before, stop_after],
              "actual_window_seconds_bounds": [(stop_before - start_after) / 1e9, (stop_after - start_before) / 1e9],
              "requested_warmup_ms": warmup, "requested_duration_ms": duration,
              "boundary": "atomic arming/closing with explicit clock brackets; admitted first-hit writers drained before snapshot; cumulative stops with window",
              "banks": {}}
    for label, bitmap in (("cumulative", cumulative), ("window", window)):
        rows = [r for r in manifest["entries"] if bitmap[r["id"] // 64] & (1 << (r["id"] % 64))]
        unique = {}
        for row in rows:
            key = (row["module"], row["address"])
            if key not in unique:
                unique[key] = {"module": row["module"], "image": row["image"], "address": row["address"], "entered_implementations": [], "entered_symbols": [], "manual_algorithm_observed": False}
            unique[key]["entered_implementations"].append(row["kind"])
            unique[key]["entered_symbols"].append(row["symbol"])
            unique[key]["manual_algorithm_observed"] |= bool(row.get("manual_algorithmic_port"))
        result["banks"][label] = {"entered_implementation_count": len(rows), "unique_guest_function_count": len(unique),
                                  "observed_manual_algorithm_count": sum(r["manual_algorithm_observed"] for r in unique.values()),
                                  "by_module": dict(sorted(Counter(r["module"] for r in unique.values()).items())),
                                  "functions": list(unique.values()), "entries": rows}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory", help="Make a checked inventory without changing production sources")
    inventory.add_argument("--edition", choices=["toe", "vanilla", "hof"], default="toe")
    inventory.add_argument("--output", type=Path, required=True)
    report = sub.add_parser("decode", help="Verify and decode one closed runtime bitmap")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--binary", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inventory":
        import build_android as builder
        from port_patches import native_overrides, adapt_host_source
        from native_routes import algorithm_entries
        builder.configure_edition(args.edition)
        builder.OUT = args.output.resolve() / "prepared"
        builder.ACTIVE_NATIVE_OVERRIDES = native_overrides(args.edition, builder.NATIVE_OVERRIDES)
        sources = [builder.override_source(path, local_xmm=True)[0] for path in builder.generated_sources()]
        hosts = [adapt_host_source(path, builder.OUT, args.edition)[0] for path in builder.host_sources()]
        plan = CoveragePlan.create(builder.GENERATED, sources, hosts, builder.ACTIVE_NATIVE_OVERRIDES,
                                   args.output, specs=builder.MANIFEST, edition=args.edition,
                                   manual_entries=algorithm_entries(args.edition))
        print(json.dumps({"entries": len(plan.manifest["entries"]), "identity_sha256": plan.manifest["identity_sha256"],
                          "manifest": str(plan.manifest_path)}))
    else:
        result = decode(args.manifest, args.binary)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        for label, bank in result["banks"].items():
            path = args.output.with_name(args.output.stem + "-" + label + ".tsv")
            path.write_text("module\timage\taddress\tentered_implementations\n" + "".join(
                f'{r["module"]}\t{r["image"]}\t0x{r["address"]}\t{",".join(r["entered_implementations"])}\n'
                for r in bank["functions"]), encoding="utf-8")
        print(json.dumps({label: bank["unique_guest_function_count"] for label, bank in result["banks"].items()}))


if __name__ == "__main__":
    main()
