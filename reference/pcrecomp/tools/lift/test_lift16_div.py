#!/usr/bin/env python3
"""
test_lift16_div.py - lift16's div/idiv against the CPU's rules, including when
it faults: a zero divisor, and a quotient too big for its destination. Both
raise INT 0 on an x86, and the lifted code must call DIV0_FN with cpu->cs:ip
pointing at the divide, so a runtime can hand a game's INT 0 handler the
frame the CPU would have.

Each case lifts one divide, compiles it with a stub DIV0_FN that records the
call, runs it on a vector of register values and compares with Python's
reference. No game files, no emulator.

    python tools/lift/test_lift16_div.py          (needs gcc/clang/cc or $RECOMP_CC)
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'disasm'))
import lift16                      # noqa: E402
from decode16 import Decoder       # noqa: E402

RUNTIME = os.path.normpath(os.path.join(HERE, '..', '..', 'runtime'))

# (bytes, mnemonic, width, signed)
CASES = [
    (bytes([0xF6, 0xF3]), 'div bl', 8, False),
    (bytes([0xF7, 0xF3]), 'div bx', 16, False),
    (bytes([0x66, 0xF7, 0xF3]), 'div ebx', 32, False),
    (bytes([0xF6, 0xFB]), 'idiv bl', 8, True),
    (bytes([0xF7, 0xFB]), 'idiv bx', 16, True),
    (bytes([0x66, 0xF7, 0xFB]), 'idiv ebx', 32, True),
]

# (dividend, divisor) per width, signed values where it matters
VECTORS = {
    8: [(100, 7), (0x1234, 0x10), (5, 0), (0x00FF, 1), (0x0100, 1), (-128 & 0xFFFF, 0xFF)],
    16: [(1000, 7), (0x12345678, 0x1000), (5, 0), (0xFFFF, 1), (0x10000, 1), (0x80000000, 0xFFFF)],
    32: [(10**12, 12345), (5, 0), (0xFFFFFFFF, 1), (1 << 32, 1),
         (0x8000000000000000, 0xFFFFFFFF), (-7 & 0xFFFFFFFFFFFFFFFF, 2)],
}


def sx(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def reference(width, signed, n, d):
    """(quotient, remainder) or None for a fault."""
    nb = 2 * width
    if signed:
        n, d = sx(n, nb), sx(d, width)
        if d == 0:
            return None
        q = abs(n) // abs(d) * (1 if (n < 0) == (d < 0) else -1)
        r = n - q * d
        if not -(1 << (width - 1)) <= q < (1 << (width - 1)):
            return None
    else:
        n, d = n & ((1 << nb) - 1), d & ((1 << width) - 1)
        if d == 0:
            return None
        q, r = divmod(n, d)
        if q >= 1 << width:
            return None
    m = (1 << width) - 1
    return q & m, r & m


def lift_one(code):
    ins = Decoder(code, 0).decode_one()
    lift16._CODE_SEG = '0040'
    lf = lift16.Lifter()
    body = lf.lift_function('f', [ins], 0)
    return body


def compiler():
    if os.environ.get('RECOMP_CC'):
        return [os.environ['RECOMP_CC']]
    for c in ('gcc', 'clang', 'cc'):
        try:
            subprocess.run([c, '--version'], capture_output=True, check=True)
            return [c]
        except (OSError, subprocess.CalledProcessError):
            pass
    sys.exit('no C compiler: put gcc/clang on PATH or set RECOMP_CC')


def main():
    src = ['#include <stdio.h>', '#include <stdint.h>', '#define SEG_0040 0x40',
           '#include "recomp16/cpu.h"',
           'static int faults; static uint16_t f_cs, f_ip;',
           'void recomp_div0(const char *w) { (void)w; faults++; }',
           'static void recomp_dispatch(CPU *c, uint16_t s, uint16_t o) { (void)c; (void)s; (void)o; }']
    run = []
    for k, (code, text, width, signed) in enumerate(CASES):
        body = lift_one(code).replace('void f(CPU *cpu)', f'static void f{k}(CPU *cpu)')
        body = body.replace('recomp_div0(', 'f_cs = cpu->cs; f_ip = cpu->ip; recomp_div0(')
        src.append(body)
        for n, d in VECTORS[width]:
            run.append((k, text, width, signed, n, d))
    src.append('int main(void) { static uint8_t mem[MEM_SIZE]; CPU c = {0}; c.mem = mem;')
    for i, (k, text, width, signed, n, d) in enumerate(run):
        if width == 8:
            setup = f'c.ax = 0x{n & 0xFFFF:X}; c.bl = 0x{d & 0xFF:X};'
        elif width == 16:
            setup = f'c.dx = 0x{(n >> 16) & 0xFFFF:X}; c.ax = 0x{n & 0xFFFF:X}; c.bx = 0x{d & 0xFFFF:X};'
        else:
            setup = (f'c.edx = 0x{(n >> 32) & 0xFFFFFFFF:X}u; c.eax = 0x{n & 0xFFFFFFFF:X}u; '
                     f'c.ebx = 0x{d & 0xFFFFFFFF:X}u;')
        src.append(f'  faults = 0; f_cs = f_ip = 0; {setup} f{k}(&c); '
                   f'printf("%d %u %u %u %X %X\\n", {i}, faults, '
                   f'(unsigned)({"c.al" if width == 8 else "c.ax" if width == 16 else "c.eax"}), '
                   f'(unsigned)({"c.ah" if width == 8 else "c.dx" if width == 16 else "c.edx"}), f_cs, f_ip);')
    src.append('  return 0; }')
    with tempfile.TemporaryDirectory() as tmp:
        c_path, exe = os.path.join(tmp, 't.c'), os.path.join(tmp, 't.exe')
        open(c_path, 'w').write('\n'.join(src))
        r = subprocess.run(compiler() + ['-O1', '-I', RUNTIME, c_path, '-o', exe],
                           capture_output=True, text=True)
        if r.returncode:
            print(r.stderr[:3000])
            sys.exit('the lifted divides did not compile')
        out = subprocess.run([exe], capture_output=True, text=True, check=True).stdout.split('\n')
    bad = 0
    for line in filter(None, out):
        i, faults, q, rem, cs, ip = line.split()
        k, text, width, signed, n, d = run[int(i)]
        want = reference(width, signed, n, d)
        got = None if int(faults) else (int(q), int(rem))
        ok = got == want and (want is not None or (cs == '40' and ip == '0'))
        if not ok:
            bad += 1
            print(f'FAIL {text} n={n:#x} d={d:#x}: got {got} (cs:ip {cs}:{ip}), want {want}')
    print(f'{len(run) - bad}/{len(run)} divide cases agree'
          + ('' if bad else ' (faults on zero and on overflow, with cs:ip set)'))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
