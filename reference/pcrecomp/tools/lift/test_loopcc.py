"""loope/loopne count ecx down and test ZF, not CF.

lift32 lifted both as `--ecx != 0 && _cf == 0`. Streets of SimCity's texture
spans end in `inc edi; loopne`: ZF is clear there (edi never wraps), so the
loop is a plain count, but the lift tested the carry an earlier `shr` left,
ended spans early and drew the next from a corrupt destination (a write
fault at 0x004B7CBE).

Run: py -3 tools/lift/test_loopcc.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capstone

from generate import LinearInstruction
from lift32 import Lifter


def lift(code):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    lifter = Lifter()
    out = []
    for insn in md.disasm(code, 0x1000):
        out += lifter.lift_instruction(LinearInstruction(insn))
    return "\n".join(out)


def loop_line(c):
    return next(l for l in c.splitlines() if "--ecx" in l)


def main():
    bad = 0
    cases = [
        # inc edi; loopne -2 (back to the inc)
        (b"\x47\xe0\xfd", "jne"),
        # cmp eax, ebx; loope -4 (back to the cmp)
        (b"\x39\xd8\xe1\xfc", "je"),
    ]
    for code, cc in cases:
        c = lift(code)
        line = loop_line(c)
        if "_cf" in line:
            print("FAIL %s: tests CF:\n  %s" % (code.hex(), line))
            bad += 1
        # The ZF test must be taken before the decrement.
        if line.find("_zc =") < 0 or line.find("_zc =") > line.find("--ecx"):
            print("FAIL %s: condition not taken before ecx counts down:\n  %s" % (code.hex(), line))
            bad += 1
    # A plain loop stays a plain count.
    line = loop_line(lift(b"\x47\xe2\xfd"))
    if line.split(";")[0].strip() != "if (--ecx != 0) goto L_00001000":
        print("FAIL loop: %s" % line)
        bad += 1
    print("test_loopcc: %s" % ("FAILED" if bad else "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
