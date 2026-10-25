#!/usr/bin/env python3
"""Recover which source file each function came from, using the binary's own
`__FILE__` strings.

An `assert` bakes `__FILE__` into the binary as a string literal and references
it from the code of the function containing the assert. Plenty of shipped
"release" builds keep some of their asserts -- a subsystem built with NDEBUG
off, a library compiled separately, a developer who left them in on purpose --
so the strings are there far more often than you would expect.

That gives two passes:

  direct        A function references "AIMain.cpp" -> it was compiled from
                AIMain.cpp. Majority vote when a function references more than
                one, since inlining pulls a callee's asserts into its caller.

  interpolated  The linker emits each object file's functions contiguously, so
                an unattributed run bracketed by two functions that agree on
                the same file almost certainly belongs to that file too. Only
                runs whose endpoints agree are filled, and never across a
                section boundary -- different sections are different link units
                and contiguity means nothing between them.

    python tools/pe/debug_symbols.py game.exe --functions funcs.json -o src.json

This does not name functions. It says which *file* each one came from, which is
what turns 40,000 anonymous functions into a browsable tree and tells you which
ones are worth reverse-engineering together.

Ported from xboxrecomp's `tools/debug_symbols/`. The Xbox version consumes a
strings.json with cross-references already computed; pcrecomp has no such file,
so the references are found here by scanning each function's bytes for the
address of a string -- which is what `push offset aFoo` compiles to.
"""
import argparse
import json
import os
import re
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CODE_EXTS = ("c", "cc", "cpp", "cxx")
HEADER_EXTS = ("h", "hh", "hpp", "hxx")

# A source filename, with or without a leading path. Anchored on the extension
# and a NUL so it matches a whole C string rather than a fragment of one.
def _source_re(include_headers):
    exts = "|".join(CODE_EXTS + (HEADER_EXTS if include_headers else ()))
    return re.compile(rb"[A-Za-z0-9_.\-\\/:]{1,200}\.(?:" + exts.encode()
                      + rb")\x00", re.I)


def find_source_strings(data, sections, image_base, include_headers=False):
    """{va: filename} for every source-file string in the image."""
    pat = _source_re(include_headers)
    out = {}
    for s in sections:
        size = min(s.raw_size, len(data) - s.raw_offset)
        if size <= 0:
            continue
        blob = data[s.raw_offset:s.raw_offset + size]
        base = image_base + s.virtual_address
        for m in pat.finditer(blob):
            text = m.group()[:-1].decode("latin1")
            # A path may be absolute or relative; the basename is what matches
            # an object file name, and is what a __FILE__ usually holds anyway.
            name = re.split(r"[\\/]", text)[-1]
            if name:
                out[base + m.start()] = name
    return out


def string_xrefs(data, sections, image_base, functions, string_vas):
    """{function start: Counter(filename)} from addresses embedded in code.

    Scans every byte offset of each function for a little-endian word equal to
    a string's address. Unaligned on purpose: `push offset aFoo` puts the
    address one byte into a five-byte instruction, so an aligned-only scan
    misses the single most common way a string is referenced.
    """
    # va -> file offset, for code only.
    ranges = [(image_base + s.virtual_address,
               image_base + s.virtual_address + min(s.raw_size,
                                                    len(data) - s.raw_offset),
               s.raw_offset - (image_base + s.virtual_address))
              for s in sections if s.is_code]

    def to_off(va):
        for lo, hi, adj in ranges:
            if lo <= va < hi:
                return va + adj
        return None

    votes = defaultdict(Counter)
    for start, end in functions:
        off = to_off(start)
        if off is None or end <= start:
            continue
        n = min(end - start, 65536)
        blob = data[off:off + n]
        for i in range(len(blob) - 3):
            va = struct.unpack_from("<I", blob, i)[0]
            name = string_vas.get(va)
            if name is not None:
                votes[start][name] += 1
    return votes


def resolve_votes(votes):
    """Majority vote per function; a .c/.cpp beats a header on a tie."""
    resolved, ambiguous = {}, 0
    for addr, counter in votes.items():
        if len(counter) > 1:
            ambiguous += 1
        best = max(counter.items(),
                   key=lambda kv: (kv[1],
                                   not kv[0].lower().endswith(HEADER_EXTS)))
        resolved[addr] = best[0]
    return resolved, ambiguous


def interpolate(ordered, direct):
    """Fill unattributed runs bracketed by two functions agreeing on one file.

    `ordered` is [(start, section)] sorted by address.
    """
    filled = {}
    starts = [a for a, _ in ordered]
    sect = {a: s for a, s in ordered}
    known = [(a, i) for i, a in enumerate(starts) if a in direct]
    for (a, i), (b, j) in zip(known, known[1:]):
        if j - i < 2 or direct[a] != direct[b]:
            continue
        if sect[a] != sect[b]:
            continue
        for k in range(i + 1, j):
            if sect[starts[k]] != sect[a]:
                continue
            filled[starts[k]] = direct[a]
    return filled


def run(exe_path, functions_path, include_headers=False):
    from pe_analyze import analyze_pe          # noqa: E402
    info = analyze_pe(exe_path)
    with open(exe_path, "rb") as f:
        data = f.read()

    with open(functions_path) as f:
        doc = json.load(f)
    fns = doc["functions"] if isinstance(doc, dict) else doc
    fns = [f for f in fns if f.get("entry_kind", "start") != "alias"]

    def section_of(va):
        for s in info.sections:
            lo = info.image_base + s.virtual_address
            if lo <= va < lo + s.virtual_size:
                return s.name
        return "?"

    ordered = sorted((f["address"], section_of(f["address"])) for f in fns)
    ranges = [(f["address"], f.get("end", f["address"])) for f in fns]

    strings = find_source_strings(data, info.sections, info.image_base,
                                  include_headers)
    votes = string_xrefs(data, info.sections, info.image_base, ranges, strings)
    direct, ambiguous = resolve_votes(votes)
    filled = interpolate(ordered, direct)
    return {
        "strings": strings,
        "direct": direct,
        "interpolated": filled,
        "ambiguous": ambiguous,
        "total_functions": len(fns),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe", nargs="?")
    ap.add_argument("--functions", help="a disasm32 catalog of the same binary")
    ap.add_argument("-o", "--out", help="write {address: filename} as JSON")
    ap.add_argument("--include-headers", action="store_true",
                    help="also match .h/.hpp strings. Off by default: an "
                         "assert in a header attributes the caller to the "
                         "header, which is true and not useful.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="list the files found and how many functions each got")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        demo()
        return 0
    if not (args.exe and args.functions):
        ap.error("need an exe and --functions (or --selftest)")

    r = run(args.exe, args.functions, args.include_headers)
    direct, filled = r["direct"], r["interpolated"]
    total = r["total_functions"]
    attributed = len(direct) + len(filled)

    print(f"[*] {os.path.basename(args.exe)}")
    print(f"[*] source-file strings in the image : {len(set(r['strings'].values())):,}"
          f"  ({len(r['strings']):,} occurrences)")
    print(f"[*] attributed directly              : {len(direct):,}"
          f"  ({r['ambiguous']:,} voted between more than one file)")
    print(f"[*] filled by interpolation          : {len(filled):,}")
    print(f"[*] total                            : {attributed:,} of {total:,}"
          f"  ({attributed / max(1, total):.1%})")
    if not r["strings"]:
        print("[*] No source-file strings. This build kept none of its "
              "asserts, which is the normal case for a release build.")

    if args.verbose:
        c = Counter(list(direct.values()) + list(filled.values()))
        for name, n in c.most_common(30):
            print(f"    {name:<40} {n:>6,}")

    if args.out:
        # How an attribution was reached is part of the attribution. A function
        # that references "AIMain.cpp" itself is an observation; one that sits
        # between two functions which do is a guess from linker layout.
        #
        # The expectation is that the observation is much the safer of the two.
        # Measured against Trespasser's own MAP, it is not: direct attributions
        # are right 96.7% of the time (267/276) and interpolated ones 97.0%
        # (3,363/3,467). Interpolation is very slightly *better*.
        #
        # That is not interpolation being clever, it is inlining being awkward.
        # A direct reference proves an assert's __FILE__ is in this function's
        # bytes, not that this function was compiled from that file -- inlining
        # a callee drags its asserts along with it. Interpolation, meanwhile,
        # only fills runs whose two ends already agree, which is a strong
        # filter. Both are useful; neither is authoritative; and recording
        # which is which is the only way a reader can tell.
        out = {f"0x{a:08X}": {"file": n, "how": "interpolated"}
               for a, n in filled.items()}
        out.update({f"0x{a:08X}": {"file": n, "how": "direct"}
                    for a, n in direct.items()})
        with open(args.out, "w") as f:
            json.dump(dict(sorted(out.items())), f, indent=1)
        print(f"[*] wrote {args.out} ({len(out):,} attributions: "
              f"{len(direct):,} observed, {len(filled):,} inferred)")
    return 0


def demo():
    """One runnable check: both passes, and the rules that bound them."""
    # Votes: majority wins, and a header loses a tie to a source file.
    v = {0x1000: Counter({"a.cpp": 3, "b.cpp": 1}),
         0x2000: Counter({"x.h": 1, "x.cpp": 1}),
         0x3000: Counter({"only.cpp": 1})}
    resolved, ambiguous = resolve_votes(v)
    assert resolved[0x1000] == "a.cpp", resolved
    assert resolved[0x2000] == "x.cpp", "a source file beats a header on a tie"
    assert resolved[0x3000] == "only.cpp"
    assert ambiguous == 2, ambiguous

    # Interpolation fills a bracketed run whose ends agree...
    ordered = [(0x1000, ".text"), (0x1100, ".text"), (0x1200, ".text"),
               (0x1300, ".text")]
    direct = {0x1000: "a.cpp", 0x1300: "a.cpp"}
    got = interpolate(ordered, direct)
    assert got == {0x1100: "a.cpp", 0x1200: "a.cpp"}, got

    # ...and does not when they disagree, because the boundary between two
    # object files is somewhere in that run and nothing here says where.
    assert interpolate(ordered, {0x1000: "a.cpp", 0x1300: "b.cpp"}) == {}

    # Never across a section boundary: different sections are different link
    # units, so adjacency carries no information.
    split = [(0x1000, ".text"), (0x1100, ".text"),
             (0x1200, "OTHER"), (0x1300, "OTHER")]
    assert interpolate(split, {0x1000: "a.cpp", 0x1300: "a.cpp"}) == {}, \
        "contiguity means nothing across sections"

    # Adjacent known functions have nothing between them to fill.
    assert interpolate([(0x1000, ".text"), (0x1100, ".text")],
                       {0x1000: "a.cpp", 0x1100: "a.cpp"}) == {}

    # The string matcher wants a whole C string, not a fragment, and takes the
    # basename so it can be compared with an object file name.
    pat = _source_re(False)
    assert pat.search(b"xx\\src\\ai\\AIMain.cpp\x00yy"), "a path is matched"
    assert not pat.search(b"AIMain.cppX"), "an unterminated match is not a string"
    assert not pat.search(b"notes.txt\x00"), "only source extensions"

    class _S:
        def __init__(s_, name, va, off, size, code):
            s_.name, s_.virtual_address = name, va
            s_.raw_offset, s_.raw_size, s_.virtual_size = off, size, size
            s_.is_code = code

    blob = b"\x00" * 16 + b"src\\AIMain.cpp\x00" + b"\x00" * 16
    found = find_source_strings(blob, [_S(".rdata", 0x2000, 0, len(blob), False)],
                                0x400000)
    assert list(found.values()) == ["AIMain.cpp"], found
    assert list(found)[0] == 0x400000 + 0x2000 + 16, [hex(k) for k in found]

    print("debug_symbols.py self-test OK")


if __name__ == "__main__":
    sys.exit(main())
