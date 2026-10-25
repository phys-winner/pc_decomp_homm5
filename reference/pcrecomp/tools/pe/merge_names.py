#!/usr/bin/env python3
"""Merge every symbol source into one name per address, fit to paste into C.

This repo now recovers names from several places, and they disagree in quality:

    map_names.py      real symbols from a linker MAP          -- authoritative
    rtti.py           Class__ADDR from MSVC RTTI              -- a real class
    debug_symbols.py  which source file a function came from  -- a grouping
    (anything else)   Ghidra, IDA, a hand-written list

Nothing combined them, so a project picked one and threw the rest away. This
takes them in precedence order, first source wins per address, and reports what
each contributed so a source that adds nothing can be dropped.

    python tools/pe/merge_names.py --source map=map.json --source rtti=rtti.json \\
                                   --files src.json -o names.json

Sanitising is the point, not a detail
-------------------------------------
The names worth having are not C identifiers. A MAP gives `_SmackOpen@12` and
`??0CColour@@QAE@HHH@Z`; RTTI gives `?$vector@H@std`. Generated code cannot use
any of them, so every consumer either sanitises and risks collisions or gives
up and keeps `sub_00430400`.

Collisions are the trap. The signature is kept precisely so overloads stay
apart -- `?f@@QAE@XZ` and `?f@@QAE@HH@Z` become `f_QAE_XZ` and `f_QAE_HH_Z`,
which is ugly and correct. But `@` and `_` both map to `_`, so any two symbols
differing only in which separator they used collide: `a@b` and `a_b` are one
identifier afterwards, and so are a mangled name and a hand-written one for the
same function. Letting one silently win produces C that does not compile, or
worse, compiles and calls the other function. Here the first claim keeps the
identifier and every later one gets its address appended, so the output is
always unique.
"""
import argparse
import json
import keyword
import os
import re
import sys
from collections import Counter

# C keywords plus the C++ ones a generated .c could still trip over, and the
# handful the runtime header already defines.
_RESERVED = set(keyword.kwlist) | {
    "auto", "break", "case", "char", "const", "continue", "default", "do",
    "double", "else", "enum", "extern", "float", "for", "goto", "if", "inline",
    "int", "long", "register", "restrict", "return", "short", "signed",
    "sizeof", "static", "struct", "switch", "typedef", "union", "unsigned",
    "void", "volatile", "while", "bool", "true", "false", "class", "new",
    "delete", "template", "this", "operator", "namespace", "try", "catch",
}


def sanitize(name):
    """A mangled symbol as a C identifier, or None if nothing usable is left."""
    # MSVC decorations first, so the readable part survives: _Name@12 -> Name,
    # ?Name@Class@@... -> Name_Class.
    s = re.sub(r"^[?_@]+", "", name)
    s = re.sub(r"@+", "_", s)
    s = re.sub(r"[^0-9A-Za-z_]", "_", s)
    s = re.sub(r"_{2,}", "_", s).strip("_")
    if not s:
        return None
    if s[0].isdigit():
        s = "f_" + s
    if s in _RESERVED:
        s += "_"
    return s


def load_source(path):
    """{int address: str name} from any of the shapes the tools here emit."""
    with open(path) as f:
        doc = json.load(f)
    out = {}
    for k, v in doc.items():
        try:
            addr = int(k, 16) if isinstance(k, str) else int(k)
        except ValueError:
            continue
        if isinstance(v, dict):
            # debug_symbols emits {"file": ..., "how": ...}; it names no
            # function, so it is not a name source. Callers pass it as --files.
            v = v.get("name")
        if isinstance(v, str) and v:
            out[addr] = v
    return out


def load_files(path):
    """{int address: source file} from debug_symbols.py output."""
    with open(path) as f:
        doc = json.load(f)
    out = {}
    for k, v in doc.items():
        addr = int(k, 16) if isinstance(k, str) else int(k)
        out[addr] = v["file"] if isinstance(v, dict) else v
    return out


def merge(sources, files=None):
    """sources is [(label, {addr: name})], best first.

    Returns {addr: {"name", "raw", "source", "file"}} with every `name` a
    unique C identifier.
    """
    files = files or {}
    chosen, taken = {}, {}
    stats = Counter()
    collisions = 0

    for label, table in sources:
        for addr in sorted(table):
            if addr in chosen:
                continue
            raw = table[addr]
            ident = sanitize(raw)
            if ident is None:
                stats[label + " (unusable)"] += 1
                continue
            owner = taken.get(ident)
            if owner is not None and owner != addr:
                # Someone already has this identifier. Keep both, distinguish
                # by address -- the alternative is C that does not compile.
                ident = f"{ident}_{addr:08X}"
                collisions += 1
            taken[ident] = addr
            chosen[addr] = {"name": ident, "raw": raw, "source": label}
            stats[label] += 1

    for addr, entry in chosen.items():
        if addr in files:
            entry["file"] = files[addr]
    # A file attribution for a function nothing named is still worth keeping:
    # it groups the anonymous ones, which is most of what it is for.
    for addr, fname in files.items():
        if addr not in chosen:
            chosen[addr] = {"name": f"sub_{addr:08X}", "raw": "",
                            "source": "unnamed", "file": fname}
            stats["file-only"] += 1

    return chosen, stats, collisions


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # LABEL=PATH, not LABEL:PATH. A colon separator collides with a Windows
    # drive letter, and a shell that rewrites colon-separated lists (MSYS does,
    # for PATH-like arguments) turns `map:C:/x.json` into `map;C:/x.json`
    # somewhere between the command line and argv -- after which the label is
    # `map;C` and the path is `/x.json`, which does not exist.
    ap.add_argument("--source", action="append", default=[], metavar="LABEL=PATH",
                    help="a {address: name} JSON, best first. Repeatable. The "
                         "label appears in the output so a name can be traced "
                         "back to what claimed it.")
    ap.add_argument("--files", help="debug_symbols.py output, for grouping")
    ap.add_argument("-o", "--out", help="write the merged table")
    ap.add_argument("--plain", help="also write a plain {address: name} map "
                                    "for consumers that want only that")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        demo()
        return 0
    if not args.source and not args.files:
        ap.error("need at least one --source or --files (or --selftest)")

    sources = []
    for spec in args.source:
        label, sep, path = spec.partition("=")
        if not sep:
            label, path = os.path.splitext(os.path.basename(spec))[0], spec
        sources.append((label, load_source(path)))

    files = load_files(args.files) if args.files else {}
    merged, stats, collisions = merge(sources, files)

    print(f"[*] {len(merged):,} addresses named")
    for label, n in stats.most_common():
        print(f"      {label:<24} {n:>7,}")
    if collisions:
        print(f"[*] {collisions:,} names had their address appended to stay "
              f"unique (two symbols sanitised to the same identifier)")

    if args.out:
        with open(args.out, "w") as f:
            json.dump({f"0x{a:08X}": v for a, v in sorted(merged.items())},
                      f, indent=1)
        print(f"[*] wrote {args.out}")
    if args.plain:
        with open(args.plain, "w") as f:
            json.dump({f"0x{a:08X}": v["name"]
                       for a, v in sorted(merged.items())}, f, indent=1)
        print(f"[*] wrote {args.plain}")
    return 0


def demo():
    """One runnable check: precedence, sanitising, and uniqueness."""
    assert sanitize("_SmackOpen@12") == "SmackOpen_12"
    # The digit rule fires after the decorations come off, which is easy to
    # forget when writing the expected value by hand.
    assert sanitize("??0CColour@@QAE@HHH@Z") == "f_0CColour_QAE_HHH_Z"
    assert sanitize("?$vector@H@std") == "vector_H_std"
    assert sanitize("CBaseValue__00449850") == "CBaseValue_00449850"
    assert sanitize("int") == "int_", "a C keyword must not be emitted bare"
    assert sanitize("9lives") == "f_9lives", "an identifier cannot start with a digit"
    assert sanitize("@@@") is None, "nothing usable left"
    assert sanitize("already_fine") == "already_fine"

    # Precedence: the first source to claim an address keeps it.
    best = ("map", {0x1000: "_Real@4", 0x2000: "_Other@8"})
    worse = ("rtti", {0x1000: "CFoo__1000", 0x3000: "CBar__3000"})
    merged, stats, coll = merge([best, worse])
    assert merged[0x1000]["source"] == "map", merged[0x1000]
    assert merged[0x1000]["name"] == "Real_4"
    assert merged[0x3000]["source"] == "rtti", "a later source still fills gaps"
    assert stats["map"] == 2 and stats["rtti"] == 1, stats

    # The raw name is kept, because the sanitised one is lossy and the mangled
    # one is what you paste into a demangler.
    assert merged[0x1000]["raw"] == "_Real@4"

    # Overloads must stay apart, which is why the signature is kept.
    over = ("map", {0x4000: "?f@@QAE@XZ", 0x5000: "?f@@QAE@HH@Z"})
    mo, _, co = merge([over])
    assert mo[0x4000]["name"] == "f_QAE_XZ", mo[0x4000]
    assert mo[0x5000]["name"] == "f_QAE_HH_Z", mo[0x5000]
    assert co == 0, "these do not collide, and must not be reported as if they do"

    # A real collision: '@' and '_' both sanitise to '_', so two symbols that
    # differ only in the separator become one identifier.
    clash = ("map", {0x4000: "a@b", 0x5000: "a_b"})
    m2, _, c2 = merge([clash])
    assert m2[0x4000]["name"] != m2[0x5000]["name"], m2
    assert c2 == 1, c2
    assert len({v["name"] for v in m2.values()}) == 2
    assert m2[0x5000]["name"].endswith("_00005000"), m2[0x5000]

    # An address named by nothing but attributed to a file still appears, so
    # the grouping is not lost with the name.
    m3, st3, _ = merge([("map", {0x1000: "_A@0"})],
                       files={0x1000: "a.cpp", 0x9000: "b.cpp"})
    assert m3[0x1000]["file"] == "a.cpp"
    assert m3[0x9000]["name"] == "sub_00009000", m3[0x9000]
    assert m3[0x9000]["file"] == "b.cpp"
    assert st3["file-only"] == 1

    print("merge_names.py self-test OK")


if __name__ == "__main__":
    sys.exit(main())
