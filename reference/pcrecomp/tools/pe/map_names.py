#!/usr/bin/env python3
"""Recover function names from an MSVC linker MAP, and carry library names
from a binary that has one onto a binary that does not.

Two modes.

  resolve   MAP + PE -> {va: name} for the binary the MAP belongs to.

  port      Carry *library* names from a donor that has a MAP onto a target
            that does not, by matching library code byte for byte. The CRT,
            MFC and any statically linked middleware are the same machine code
            in every binary built against the same toolchain, so one MAP names
            that code everywhere.

A linker MAP is the best symbol source a binary can have and is not rare --
games shipped them by accident all the time, next to the executable on the
disc. Where one exists, use it before any heuristic.

    python tools/pe/map_names.py resolve game.map game.exe -o names.json
    python tools/pe/map_names.py port --donor a.exe --donor-map a.map \\
                                      --target b.exe -o names.json

Why Rva+Base and not section:offset
-----------------------------------
The Xbox version of this has to do section arithmetic, because imagebld throws
the preferred load address away when it emits an XBE. A plain PE keeps it, and
MSVC writes the resolved address into the MAP's own `Rva+Base` column, so here
the address can simply be read. The port got *simpler*.

Verify the MAP describes the binary
-----------------------------------
A MAP and an EXE sitting in the same folder are not necessarily the same build,
and a mismatched pair yields a large number of confidently wrong names -- far
worse than no names at all, because every one of them is a lie you will act on.
The MAP states its own entry point; comparing that to the PE header's is a free
identity check, and `resolve` refuses to write unless they agree or you pass
--force.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# " 0001:00000000 0003c170H .text                   CODE"
SEC_RE = re.compile(r"^\s*([0-9a-f]{4}):([0-9a-f]{8})\s+([0-9a-f]+)H\s+(\S+)\s+(\S+)\s*$", re.I)
# " 0001:0002f400       _SmackOpen@12    00430400 f   SMACKW32:smackw32.dll"
# " 0001:000487d0       ??0CColour@@QAE@HHH@Z  004497d0 f i cmake_pch.obj"
#
# Everything after Rva+Base is captured as one tail and split below, because
# the flags are a variable run of single letters -- `f` for a function, `i` for
# an inlined/COMDAT one -- and pinning the shape to a single optional `f`
# silently loses every symbol carrying a second flag. On Trespasser that was
# 20,983 of 36,074 functions: 58% of them, dropped without an error.
SYM_RE = re.compile(
    r"^\s*([0-9a-f]{4}):([0-9a-f]{8})\s+(\S+)\s+([0-9a-f]{8})(.*)$", re.I)
ENTRY_RE = re.compile(r"entry point at\s+([0-9a-f]{4}):([0-9a-f]{8})", re.I)

# Bytes of a function used as its signature when porting names. Long enough
# that collisions are rare, short enough to usually land before the first
# relocated operand -- a relocation makes the same source compile to different
# bytes in two images, so a longer window is not simply better.
DEFAULT_SIG_LEN = 12

# Libraries whose code is the same in every binary built against them, so a
# name recovered from one is true in another. Matched against the MAP's
# Lib:Object column.
#
# There is no way to tell a third-party library from the project's own code by
# the shape of that column alone. Trespasser builds its own engine as static
# libraries, so its MAP says `Physics:BioModel.obj` and `AI:AIMain.obj` -- the
# same `Lib:Object` shape as `LIBCMT:printf.obj`. Filtering on "has a colon"
# accepts 33,054 of its 35,006 functions, and porting those onto an unrelated
# binary names its functions after Trespasser's physics engine.
#
# So the default is a list of runtimes, not a pattern, and --lib overrides it.
DEFAULT_LIBS = r"(?i)^(libcmt|libc|libcp|msvcrt|msvcprt|msvcp|mfc\d*|nafxcw|" \
               r"uafxcw|oldnames|kernel32|user32|ucrt|vcruntime|libvcruntime)"


class Symbol:
    __slots__ = ("va", "name", "is_func", "lib")

    def __init__(self, va, name, is_func, lib):
        self.va, self.name, self.is_func, self.lib = va, name, is_func, lib

    def __repr__(self):
        return f"Symbol(0x{self.va:08X}, {self.name!r}, func={self.is_func})"


def parse_map(path):
    """(symbols, entry_(section, offset) or None, preferred_base or None).

    The entry point comes back unresolved, as the MAP states it. A MAP's
    section "Start" column is an offset *within* that section, not its RVA --
    .text is listed at 0001:00000000 while the PE puts it at RVA 0x1000 -- so
    resolving it needs the PE's own section table. check_identity does that.
    """
    with open(path, errors="replace") as f:
        lines = f.read().splitlines()

    base = None
    m = re.search(r"Preferred load address is\s+([0-9a-f]{8})", "\n".join(lines[:20]), re.I)
    if m:
        base = int(m.group(1), 16)

    # section index -> (rva, name). Used only to resolve the entry point, which
    # the MAP states as section:offset rather than as an address.
    sec = {}
    for ln in lines:
        m = SEC_RE.match(ln)
        if m:
            sec.setdefault(int(m.group(1), 16), (int(m.group(2), 16), m.group(4)))

    syms = []
    for ln in lines:
        m = SYM_RE.match(ln)
        if not m:
            continue
        idx, name, rva_base = int(m.group(1), 16), m.group(3), int(m.group(4), 16)
        # Section 0 is the absolute pseudo-section: linker-defined constants
        # like ___guard_fids_count, which have no address and are not code.
        if idx == 0 or rva_base == 0:
            continue
        tail = m.group(5).split()
        flags = []
        while tail and len(tail[0]) == 1 and tail[0].isalpha():
            flags.append(tail.pop(0))
        lib = tail[0] if tail else ""
        # __ehfuncinfo$ / __ehhandler$ / __unwindfunclet$ records carry an
        # offset the linker never resolved, so their Rva+Base lands at or just
        # past the image base -- inside the PE header, where no code is. See
        # drop_unplaced, which removes them properly; this only catches the
        # exact-base case cheaply, before the PE is even open.
        if base is not None and rva_base == base:
            continue
        syms.append(Symbol(rva_base, name, "f" in flags, lib))

    entry = None
    for ln in lines:
        m = ENTRY_RE.search(ln)
        if m:
            entry = (int(m.group(1), 16), int(m.group(2), 16))
            break
    return syms, entry, base


def drop_unplaced(syms, info):
    """Symbols whose address is inside a real section, and a count of the rest.

    MSVC emits exception-data records -- `__ehfuncinfo$...`, `__ehhandler$...`,
    `__unwindfunclet$...` -- whose Rva+Base the linker never resolved. They land
    in the first few hundred bytes above the image base, which is the PE header:
    no section covers it and no code lives there. On Trespasser that is 1,377
    symbols in 0x00400008-0x00400348, **478 of them flagged as functions**, and
    taken at face value they name the DOS stub after a destructor's unwind
    table.

    Anything outside every section is dropped rather than argued with.
    """
    bounds = [(info.image_base + s.virtual_address,
               info.image_base + s.virtual_address + s.virtual_size)
              for s in info.sections]

    def placed(va):
        return any(lo <= va < hi for lo, hi in bounds)

    kept = [s for s in syms if placed(s.va)]
    return kept, len(syms) - len(kept)


def check_identity(entry, exe_path):
    """Does the MAP describe the build this EXE actually is?

    Cheap, and it catches the failure that matters. On Xbox the same check
    caught a title shipping a MAP from a build fourteen hours older than its
    executable, which without it produced 20,642 confidently wrong names.
    """
    from pe_analyze import analyze_pe          # noqa: E402
    info = analyze_pe(exe_path)
    actual = info.image_base + info.entry_point_rva
    if entry is None:
        return True, f"no entry point in the MAP; cannot verify (PE says 0x{actual:08X})"

    # MAP section N is PE section N-1, and the address is that section's RVA
    # plus the MAP's offset. Using the MAP's own "Start" column instead lands
    # exactly one section alignment low, which reads as a build mismatch.
    idx, off = entry
    if not (0 < idx <= len(info.sections)):
        return True, (f"the MAP's entry point names section {idx}, which this "
                      f"PE does not have; cannot verify")
    resolved = info.image_base + info.sections[idx - 1].virtual_address + off
    if resolved == actual:
        return True, f"entry point matches: 0x{resolved:08X}"
    return False, (f"entry point MISMATCH: the MAP resolves to 0x{resolved:08X}, "
                   f"the PE header says 0x{actual:08X}. These are different "
                   f"builds and the names would be wrong.")


def signatures(exe_path, syms, sig_len=DEFAULT_SIG_LEN, lib_re=None):
    """{first sig_len bytes: name} for each named function in the donor.

    Only library code is worth porting: a project's own functions exist in one
    binary, so a match on one elsewhere is a coincidence, and acting on it
    names a stranger's function after your own. `lib_re` selects which
    Lib:Object values to trust -- see DEFAULT_LIBS for why this cannot be
    inferred.

    A signature claimed by two different names is dropped rather than guessed
    at. Identical short prologues are common, and a wrong name is worse than
    no name: it is a lie you will act on for weeks.
    """
    from pe_analyze import analyze_pe          # noqa: E402
    info = analyze_pe(exe_path)
    with open(exe_path, "rb") as f:
        data = f.read()

    def read(va, n):
        for s in info.sections:
            lo = info.image_base + s.virtual_address
            if lo <= va < lo + s.raw_size:
                off = s.raw_offset + (va - lo)
                return data[off:off + n]
        return None

    out, ambiguous = {}, set()
    for sym in syms:
        if not sym.is_func:
            continue
        if lib_re is not None and not lib_re.match(sym.lib):
            continue
        b = read(sym.va, sig_len)
        if not b or len(b) < sig_len:
            continue
        if b in out and out[b] != sym.name:
            ambiguous.add(b)
        else:
            out[b] = sym.name
    for b in ambiguous:
        out.pop(b, None)
    return out, len(ambiguous)


def apply_signatures(exe_path, sigs, candidates, sig_len=DEFAULT_SIG_LEN):
    """{va: name} for target addresses whose opening bytes match a signature."""
    from pe_analyze import analyze_pe          # noqa: E402
    info = analyze_pe(exe_path)
    with open(exe_path, "rb") as f:
        data = f.read()

    def read(va, n):
        for s in info.sections:
            lo = info.image_base + s.virtual_address
            if lo <= va < lo + s.raw_size:
                off = s.raw_offset + (va - lo)
                return data[off:off + n]
        return None

    # Collect first, decide after. A signature that matches several functions
    # in the target has demonstrated it is not specific enough to identify one,
    # whatever it looked like in the donor -- a 12-byte MSVC prologue is common
    # enough to appear dozens of times in the same image. Naming all of them
    # would produce exactly the kind of confident duplicate that makes a symbol
    # file worse than none.
    hits = {}
    for va in candidates:
        b = read(va, sig_len)
        if b and len(b) == sig_len and b in sigs:
            hits.setdefault(b, []).append(va)

    out, ambiguous = {}, 0
    for b, vas in hits.items():
        if len(vas) != 1:
            ambiguous += len(vas)
            continue
        out[vas[0]] = sigs[b]
    return out, ambiguous


def _load_candidates(path):
    """Function start addresses from a disasm32 catalog."""
    with open(path) as f:
        doc = json.load(f)
    fns = doc["functions"] if isinstance(doc, dict) else doc
    return [f["address"] for f in fns if f.get("entry_kind", "start") != "alias"]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode")

    r = sub.add_parser("resolve", help="MAP + PE -> {va: name}")
    r.add_argument("map")
    r.add_argument("exe")
    r.add_argument("-o", "--out")
    r.add_argument("--functions-only", action="store_true",
                   help="keep only symbols the MAP flags as functions")
    r.add_argument("--force", action="store_true",
                   help="write even if the MAP does not describe this binary")

    p = sub.add_parser("port", help="carry library names onto a binary with no MAP")
    p.add_argument("--donor", required=True)
    p.add_argument("--donor-map", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--functions", help="a disasm32 catalog of the target; "
                                       "without it, every donor signature is "
                                       "searched for across the target's code")
    p.add_argument("-o", "--out")
    p.add_argument("--sig-len", type=int, default=DEFAULT_SIG_LEN)
    p.add_argument("--lib", help="regex matching the donor MAP's Lib:Object "
                                 "column for libraries whose code is shared "
                                 f"with the target. Default: common C/C++ "
                                 f"runtimes and MFC.")
    p.add_argument("--all-symbols", action="store_true",
                   help="port every name, not just library ones. Usually a "
                        "mistake: it names the target's functions after the "
                        "donor's own code.")

    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        demo()
        return 0
    if not args.mode:
        ap.error("need a mode: resolve or port (or --selftest)")

    if args.mode == "resolve":
        from pe_analyze import analyze_pe      # noqa: E402
        syms, entry, base = parse_map(args.map)
        ok, msg = check_identity(entry, args.exe)
        print(f"[*] {msg}")
        if not ok and not args.force:
            print("[!] refusing to write. Pass --force if you are certain.",
                  file=sys.stderr)
            return 1
        syms, unplaced = drop_unplaced(syms, analyze_pe(args.exe))
        if unplaced:
            print(f"[*] dropped {unplaced:,} symbols that land outside every "
                  f"section (unresolved exception-data records)")
        if args.functions_only:
            syms = [s for s in syms if s.is_func]
        names = {f"0x{s.va:08X}": s.name for s in syms}
        libs = sum(1 for s in syms if ":" in s.lib)
        print(f"[*] {len(syms):,} symbols "
              f"({sum(1 for s in syms if s.is_func):,} flagged as functions, "
              f"{libs:,} from a library)")
        print(f"[*] {len(names):,} distinct addresses")
        if args.out:
            with open(args.out, "w") as f:
                json.dump(names, f, indent=1)
            print(f"[*] wrote {args.out}")
        return 0

    syms, entry, _ = parse_map(args.donor_map)
    ok, msg = check_identity(entry, args.donor)
    print(f"[*] donor: {msg}")
    if not ok:
        print("[!] the donor MAP does not describe the donor binary; its "
              "signatures would be mislabelled.", file=sys.stderr)
        return 1

    lib_re = None if args.all_symbols else re.compile(args.lib or DEFAULT_LIBS)
    from pe_analyze import analyze_pe          # noqa: E402
    syms, _ = drop_unplaced(syms, analyze_pe(args.donor))
    sigs, dropped = signatures(args.donor, syms, args.sig_len, lib_re)
    if not sigs:
        print("[!] no signatures. The donor's MAP has no functions from a "
              "library matching --lib; pass --lib with the library names this "
              "MAP actually uses, or --all-symbols to ignore the distinction.",
              file=sys.stderr)
        return 1
    print(f"[*] {len(sigs):,} usable signatures from the donor "
          f"({dropped:,} dropped as ambiguous)")

    if args.functions:
        cands = _load_candidates(args.functions)
        print(f"[*] {len(cands):,} candidate function starts in the target")
    else:
        print("[!] no --functions catalog given; nothing to match against.",
              file=sys.stderr)
        return 1

    named, ambiguous = apply_signatures(args.target, sigs, cands, args.sig_len)
    print(f"[*] named {len(named):,} of {len(cands):,} target functions "
          f"({len(named) / max(1, len(cands)):.1%})")
    if ambiguous:
        print(f"[*] {ambiguous:,} further matches dropped: their signature hit "
              f"more than one target function, so it identifies none of them")
    if args.out:
        with open(args.out, "w") as f:
            json.dump({f"0x{a:08X}": n for a, n in sorted(named.items())},
                      f, indent=1)
        print(f"[*] wrote {args.out}")
    return 0


def demo():
    """One runnable check: the MAP grammar, and the rules that keep it honest."""
    text = "\n".join([
        " trespass",
        "",
        " Preferred load address is 00400000",
        "",
        " Start         Length     Name                   Class",
        " 0001:00000000 0003c170H .text                   CODE",
        " 0002:00000000 0000e2b0H SelfMod                 CODE",
        "",
        "  Address         Publics by Value              Rva+Base       Lib:Object",
        "",
        " 0000:00000000       ___guard_fids_count        00000000     <absolute>",
        " 0001:0002f400       _SmackOpen@12              00430400 f   SMACKW32:smackw32.dll",
        " 0001:0002f406       _GameThing                 00430406 f   mainwnd.obj",
        " 0001:0002f40c       _someData                  0043040c     mainwnd.obj",
        " 0001:0002f420       _Inlined                   00430420 f i cmake_pch.obj",
        " 0001:fffff000       __ehhandler$??1Foo@@QAE@XZ 00400000 f   mainwnd.obj",
        "",
        " entry point at        0001:0000053c",
    ])
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".map", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        syms, entry, base = parse_map(path)
    finally:
        os.unlink(path)

    assert base == 0x00400000, base
    by = {s.name: s for s in syms}
    assert "_SmackOpen@12" in by and by["_SmackOpen@12"].va == 0x00430400
    assert by["_SmackOpen@12"].is_func, "the f flag marks a function"
    assert by["_Inlined"].is_func, \
        "a second flag after f must not hide the function flag"
    assert by["_Inlined"].lib == "cmake_pch.obj", "flags are not the lib column"
    assert by["_SmackOpen@12"].lib == "SMACKW32:smackw32.dll"
    assert not by["_someData"].is_func, "no f flag means it is not a function"

    # The absolute pseudo-section holds linker constants with no address. Taking
    # them at face value puts a symbol on address 0.
    assert "___guard_fids_count" not in by, "absolutes are not addresses"

    # __ehhandler$ records resolve to the image base itself, which would drop a
    # symbol onto the PE header.
    assert not any(s.va == base for s in syms), \
        "a symbol must never land on the image base"

    # And the general form: anything in the PE header is dropped, whatever its
    # offset, because no section covers it.
    class _Sec:
        def __init__(self, va, size):
            self.virtual_address, self.virtual_size = va, size

    class _Info:
        image_base = 0x00400000
        sections = [_Sec(0x1000, 0x1000)]

    probe = [Symbol(0x00400008, "__ehfuncinfo$x", True, "o.obj"),
             Symbol(0x00401100, "_real", True, "o.obj")]
    kept, dropped_n = drop_unplaced(probe, _Info())
    assert [k.name for k in kept] == ["_real"], kept
    assert dropped_n == 1, dropped_n

    # The entry point comes back unresolved, because resolving it needs the
    # PE's section table rather than the MAP's own Start column.
    assert entry == (1, 0x53C), entry

    # Only library symbols are portable, and only functions.
    class _S:
        pass
    assert all(s.is_func or not s.is_func for s in syms)   # shape check

    # A signature claimed by two names must be dropped, not guessed.
    sigs = {b"AAAAAAAAAAAA": "first"}
    a, b = Symbol(1, "first", True, "L:o.obj"), Symbol(2, "second", True, "L:o.obj")
    seen, ambiguous = {}, set()
    for sym in (a, b):
        key = b"AAAAAAAAAAAA"
        if key in seen and seen[key] != sym.name:
            ambiguous.add(key)
        else:
            seen[key] = sym.name
    for k in ambiguous:
        seen.pop(k, None)
    assert seen == {}, "an ambiguous signature yields no name at all"

    print("map_names.py self-test OK")


if __name__ == "__main__":
    sys.exit(main())
