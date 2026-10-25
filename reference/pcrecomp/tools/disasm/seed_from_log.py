#!/usr/bin/env python3
"""Feed the addresses a *run* discovered back into the next disassembly.

Static analysis cannot see every function, and two kinds are routinely
invisible no matter how good the scan gets:

  * **Indirect-call targets.** Where a vtable slot or a function pointer
    actually points is a runtime fact. `tools/rtti` will recover some of them
    statically for a C++ binary that kept its RTTI; most binaries did not.
  * **Thread and callback entry points.** The address handed to `CreateThread`
    is only ever *pushed* as an argument -- nothing calls it -- so no scan
    finds it, it gets no dispatch entry, and the thread silently never starts.
    The process then exits cleanly after a few API calls, which reads like a
    successful run rather than like zero progress.

The `recomp32` runtime already prints both, from the dispatch-failure paths of
RECOMP_ICALL and RECOMP_ITAIL:

    ICALL: unresolved VA 0x004A1C30 from 0x0048D4E0
    ITAIL: unresolved VA 0x004B2088 from 0x00401D10

Today a human reads those out of a console and hand-edits a seed list; several
projects carry one. This closes the loop.

    python tools/disasm/seed_from_log.py run.log game.exe --seeds config/seeds.json
    python tools/disasm/disasm32.py game.exe --seed-functions config/seeds.json -o funcs.json

An address the program mentioned is NOT automatically a function
----------------------------------------------------------------
A garbage slot points at data just as easily, and seeding data is worse than
the missing target was: it splits a real function in half and can break the
build, where the missing target only broke one dispatch. So every candidate
has to clear two gates:

  1. it lies in an executable section, and
  2. `probes_as_function_body` reads it as code -- it decodes forward to a
     `ret` or a tail jump without hitting bytes that are not instructions.

Both are needed. The section test alone lets through any four bytes that point
into `.text`; the probe alone accepts data that happens to decode, and a table
of code addresses decodes very happily indeed.

The caller is kept as a note. `ICALL ... from 0x0048D4E0` names the function
that made the call, and when a seed turns out to be wrong, the caller is where
you go to find out why.
"""
import argparse
import bisect
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pe"))

# One group for the target, one for the calling function.
LOG_PATTERNS = [
    (re.compile(r"ICALL:\s*unresolved VA\s*(0x[0-9A-Fa-f]+)"
                r"(?:\s*from\s*(0x[0-9A-Fa-f]+))?"),
     "indirect call"),
    (re.compile(r"ITAIL:\s*unresolved VA\s*(0x[0-9A-Fa-f]+)"
                r"(?:\s*from\s*(0x[0-9A-Fa-f]+))?"),
     "indirect tail call"),
    # The 16-bit runtime's equivalent, which reports seg:off rather than a VA.
    (re.compile(r"recomp_dispatch:\s*unresolved\s*([0-9A-Fa-f]{4}):([0-9A-Fa-f]{4})"),
     "16-bit far dispatch"),
]


def scan_log(text):
    """{target: (kind, caller_or_None)} for everything the log complained about.

    First mention wins, so the caller recorded is the first one observed --
    which is the one that ran earliest and is usually the easiest to reason
    about.
    """
    out = {}
    for pat, kind in LOG_PATTERNS:
        for m in pat.finditer(text):
            groups = m.groups()
            if kind == "16-bit far dispatch":
                target = (int(groups[0], 16) << 4) + int(groups[1], 16)
                caller = None
            else:
                target = int(groups[0], 16)
                caller = int(groups[1], 16) if groups[1] else None
            out.setdefault(target, (kind, caller))
    return out


def load_seeds(path):
    """Existing seed file as a list of dicts, or [] if there is not one yet."""
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        doc = json.load(f)
    # Accept both the list-of-dicts this writes and a bare list of addresses,
    # since that is what a hand-maintained seed list usually looks like.
    out = []
    for e in doc:
        if isinstance(e, dict):
            out.append(e)
        else:
            out.append({"address": int(e, 0) if isinstance(e, str) else e,
                        "note": "hand-added"})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log", nargs="?", help="stdout+stderr of a run")
    ap.add_argument("exe", nargs="?", help="the 32-bit PE the run was built from")
    ap.add_argument("--seeds", help="seed file to create or update")
    ap.add_argument("--functions", help="an existing disasm32 catalog, to report "
                                        "whether a candidate is a new function "
                                        "or lands inside a known one")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be added and write nothing")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        demo()
        return 0
    if not (args.log and args.exe and args.seeds):
        ap.error("need a log, the exe, and --seeds (or --selftest)")

    from pe_analyze import analyze_pe          # noqa: E402
    from disasm32 import Disassembler          # noqa: E402

    with open(args.log, errors="replace") as f:
        candidates = scan_log(f.read())
    if not candidates:
        print("No unresolved dispatches in the log. Nothing to seed.")
        return 0

    info = analyze_pe(args.exe)
    with open(args.exe, "rb") as f:
        dis = Disassembler(f.read(), info.image_base, info.sections)

    bounds = []
    if args.functions:
        with open(args.functions) as f:
            doc = json.load(f)
        bounds = sorted((fn["address"], fn.get("end", fn["address"]),
                         fn.get("name", ""))
                        for fn in (doc["functions"] if isinstance(doc, dict) else doc))
    starts = [b[0] for b in bounds]

    seeds = load_seeds(args.seeds)
    have = {e["address"] for e in seeds}

    added = skipped = known = 0
    for va, (kind, caller) in sorted(candidates.items()):
        where = f" from 0x{caller:08X}" if caller else ""
        if va in have:
            print(f"  = 0x{va:08X}  already seeded")
            continue
        if not dis.is_code_address(va):
            print(f"  - 0x{va:08X}  not in an executable section{where}")
            skipped += 1
            continue
        if not dis.probes_as_function_body(va):
            print(f"  - 0x{va:08X}  does not decode as a function body{where}")
            skipped += 1
            continue
        note = f"{kind} observed at runtime"
        if caller:
            note += f", from 0x{caller:08X}"
        # Three different things, and they mean different things to whoever
        # reads this output. An address that is already a catalogued function
        # start was never the problem -- if a run could not dispatch it, the
        # gap is in the dispatch table, not in function recovery, and seeding
        # it again will not help.
        i = bisect.bisect_right(starts, va) - 1
        if i >= 0 and bounds[i][0] == va:
            # Seeding it would change nothing: the disassembler already found
            # it. Report it loudly anyway, because it means a run failed to
            # dispatch a function the catalog contains -- a different bug, in
            # the dispatch table or the lift, and not one this tool can fix.
            known += 1
            print(f"  ! 0x{va:08X}  ALREADY a known function "
                  f"({bounds[i][2] or 'unnamed'}) -- the dispatch table is "
                  f"what is missing it, not the disassembler  ({kind}){where}")
            continue
        if i >= 0 and bounds[i][0] < va < bounds[i][1]:
            print(f"  + 0x{va:08X}  alternate entry inside "
                  f"{bounds[i][2] or 'a known function'}  ({kind}){where}")
        else:
            print(f"  + 0x{va:08X}  new function  ({kind}){where}")
        seeds.append({"address": va, "address_hex": f"0x{va:08X}", "note": note})
        added += 1

    print(f"\n{len(candidates)} unresolved addresses: {added} seeded, "
          f"{skipped} rejected, {known} already catalogued, "
          f"{len(candidates) - added - skipped - known} already seeded")
    if known:
        print(f"  {known} of them are functions the disassembler already "
              f"has. Those are a dispatch-table problem, not a recovery one.")

    if args.dry_run:
        print("dry run: nothing written")
        return 0
    if added:
        d = os.path.dirname(os.path.abspath(args.seeds))
        if d:
            os.makedirs(d, exist_ok=True)
        with open(args.seeds, "w") as f:
            json.dump(seeds, f, indent=1)
        print(f"wrote {args.seeds} ({len(seeds)} seeds)")
        print(f"now re-run: disasm32.py {args.exe} "
              f"--seed-functions {args.seeds} ... and lift again")
    return 0


def demo():
    """One runnable check: the log parser, and both rejection gates."""
    log = (
        "some unrelated output\n"
        "ICALL: unresolved VA 0x004A1C30 from 0x0048D4E0\n"
        "ITAIL: unresolved VA 0x004B2088 from 0x00401D10\n"
        "ICALL: unresolved VA 0x004A1C30 from 0x00499999\n"   # dup, first wins
        "recomp_dispatch: unresolved 1A2B:0010\n"
        "ICALL: unresolved VA 0x004C0000\n"                   # no caller
    )
    got = scan_log(log)
    assert got[0x004A1C30] == ("indirect call", 0x0048D4E0), got
    assert got[0x004B2088] == ("indirect tail call", 0x00401D10), got
    assert got[0x004C0000] == ("indirect call", None), got
    assert got[(0x1A2B << 4) + 0x10][0] == "16-bit far dispatch", got
    assert len(got) == 4, f"one entry per target address: {got}"

    # A log with nothing in it must not invent work.
    assert scan_log("clean run, exit 0\n") == {}

    # The gates. Reuse disasm32's own fake image so this needs no PE on disk.
    from disasm32 import Disassembler

    class _Sec:
        def __init__(self, name, va, off, size, code):
            self.name, self.virtual_address = name, va
            self.raw_offset, self.raw_size = off, size
            self.virtual_size, self.is_code = size, code

    BASE = 0x400000
    body = b"\x55\x8b\xec\x33\xc0\xc3"      # push ebp; mov ebp,esp; xor eax,eax; ret
    junk = b"\x0f\xff" * 4                  # not decodable
    text = body + junk
    text += b"\x90" * (0x200 - len(text))
    dis = Disassembler(b"\x00" * 0x400 + text, BASE,
                       [_Sec(".text", 0x1000, 0x400, 0x200, True)])

    assert dis.is_code_address(BASE + 0x1000)
    assert dis.probes_as_function_body(BASE + 0x1000), "a real body seeds"
    assert not dis.probes_as_function_body(BASE + 0x1000 + len(body)), \
        "bytes that do not decode must be rejected, not seeded"
    assert not dis.is_code_address(BASE + 0x9000), \
        "an address outside every code section must be rejected"

    print("seed_from_log.py self-test OK")


if __name__ == "__main__":
    sys.exit(main())
