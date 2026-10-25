"""Which x87 operand the lifter reads.

Capstone is not consistent about how it spells an x87 register operand. Most
forms carry one register: `fld st(2)` is ['st(2)']. Two carry both, with the
implicit st(0) FIRST: `fxch st(2)` is ['st(0)', 'st(2)'] and `fcmovb st(2)` is
['st(0)', 'st(2)']. A lifter that reaches for ops[0] on those two gets st(0)
every time, emits a swap of a register with itself, and produces code that
compiles and runs with the x87 stack quietly in the wrong order.

That is not a crash, so nothing catches it downstream: it surfaces as one
wrong float somewhere in a matrix, hundreds of frames later. Hence this test.

Run: py -3.11 tools/lift/test_fpu_operands.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capstone

from lift32_cpu import Lifter


def emit(encoding):
    """Lift one instruction and return the C it generated."""
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    insn = next(iter(md.disasm(encoding, 0x1000)))
    lifter = Lifter.__new__(Lifter)
    lifter.md = md
    return " ".join(lifter.fpu(insn))


def main():
    # fxch st(N): both registers are spelled, st(0) first.
    assert "fst(c, 2)" in emit(b"\xd9\xca"), emit(b"\xd9\xca")
    assert "fst(c, 3)" in emit(b"\xd9\xcb"), emit(b"\xd9\xcb")
    # fxch with no operand means st(1), and D9 C9 is exactly how it encodes.
    assert "fst(c, 1)" in emit(b"\xd9\xc9"), emit(b"\xd9\xc9")

    # fcmovb st(N) is spelled the same way and must read the same operand.
    assert "fst(c, 2)" in emit(b"\xda\xc2"), emit(b"\xda\xc2")

    # Single-operand forms still have to name the register they were given,
    # which is the case that would break if ops[-1] were applied blindly.
    assert "fst(c, 2)" in emit(b"\xd9\xc2"), emit(b"\xd9\xc2")      # fld st(2)
    assert "fst(c, 2)" in emit(b"\xdd\xd2"), emit(b"\xdd\xd2")      # fst st(2)

    # A swap of a register with itself is the exact shape of the old bug.
    for enc in (b"\xd9\xca", b"\xd9\xcb", b"\xd9\xc9"):
        c = emit(enc)
        assert "*fst(c, 0) = *fst(c, 0);" not in c, c

    print("x87 operand selection: ok")


if __name__ == "__main__":
    main()
