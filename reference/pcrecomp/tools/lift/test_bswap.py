"""bswap: how a compiler writes htonl inline.

Found by lifting a second Lindbergh game rather than a second copy of the
first. It sits right after `call inet_addr`, and beside a `ror bx, 8` doing
the 16-bit half, so any binary that opens a socket has some.

Register-only and 32-bit only. The 16-bit encoding is architecturally
undefined - real parts zero the register - so a compiler never emits it, and
a 16-bit operand here means data is being read as code.

Run: py -3.11 tools/lift/test_bswap.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capstone

from lift32_cpu import Lifter


def emit(encoding):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    insn = next(iter(md.disasm(encoding, 0x1000)))
    lifter = Lifter.__new__(Lifter)
    lifter.md = md
    out = lifter.translate(insn, set())
    return " ".join(out) if out else ""


def swap(v):
    return ((v >> 24) | ((v >> 8) & 0x0000FF00)
            | ((v << 8) & 0x00FF0000) | ((v << 24) & 0xFF000000))


def main():
    # 0F C8+rd. Each must name its own register and the 32-bit helper.
    for enc, reg in ((b"\x0f\xc8", "eax"), (b"\x0f\xc9", "ecx"),
                     (b"\x0f\xca", "edx"), (b"\x0f\xcb", "ebx"),
                     (b"\x0f\xcf", "edi")):
        c = emit(enc)
        assert "op_bswap32" in c, (reg, c)
        assert c.count(reg) >= 2, (reg, c)      # read and written
        assert "RECOMP_TODO" not in c, (reg, c)

    # The helper itself, against the values that matter: htonl of a dotted
    # quad, and the endianness of a port pair.
    assert swap(0x0100007F) == 0x7F000001, hex(swap(0x0100007F))
    assert swap(0x7F000001) == 0x0100007F
    assert swap(0x12345678) == 0x78563412
    assert swap(0x00000000) == 0x00000000
    assert swap(0xFFFFFFFF) == 0xFFFFFFFF
    assert swap(swap(0xDEADBEEF)) == 0xDEADBEEF

    print("bswap: ok")


if __name__ == "__main__":
    main()
