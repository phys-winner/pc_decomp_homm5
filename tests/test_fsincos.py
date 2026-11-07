"""Compare the real FSINCOS emission and stack helper with x86 execution."""
import math
import struct
import sys
import unittest

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EFLAGS
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
from lift_game import CheckedLifter


class FsincosTest(unittest.TestCase):
    def test_cosine_on_top_sine_below_and_lower_stack_preserved(self):
        opcode = bytes.fromhex("d9fb")
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        lifted = "\n".join(CheckedLifter().lift_instruction(next(decoder.disasm(opcode, 0x10000))))
        angles = (0.0, 1e-6, -1e-6, .01, -.01, math.pi / 180, -math.pi / 180,
                  math.pi / 4, -math.pi / 4, math.pi / 2, math.pi, 2 * math.pi, 10.0, -10.0)
        rows = []
        for angle in angles:
            uc = Uc(UC_ARCH_X86, UC_MODE_32)
            uc.mem_map(0x10000, 4096)
            # FNINIT, FLD sentinel, FLD angle, FSINCOS, FSTP cos/sin/sentinel.
            code = bytes.fromhex("dbe3dd05") + struct.pack("<I", 0x10308)
            code += bytes.fromhex("dd05") + struct.pack("<I", 0x10300) + opcode
            for address in (0x10400, 0x10408, 0x10410):
                code += bytes.fromhex("dd1d") + struct.pack("<I", address)
            uc.mem_write(0x10000, code)
            uc.mem_write(0x10300, struct.pack("<dd", angle, 9.125))
            uc.reg_write(UC_X86_REG_EFLAGS, 0x202)
            uc.emu_start(0x10000, 0x10000 + len(code), count=20)
            cosine, sine, sentinel = struct.unpack("<ddd", uc.mem_read(0x10400, 24))
            self.assertEqual(sentinel, 9.125)
            self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), 0x202)
            self.assertAlmostEqual(cosine, math.cos(angle), places=12)
            self.assertAlmostEqual(sine, math.sin(angle), places=12)
            rows.append("{" + ",".join(map(repr, (angle, cosine, sine))) + "}")
        header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf8")
        push = function(header, "static inline void fp_push_impl(")
        compile_probe("fsincos", r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
static int64_t g_st_i64[8];
#include "push.h"
#define fp_push(v) fp_push_impl(_st, &_fp_top, (v))
int main(void) {
    double cases[][3] = {CASES};
    for (unsigned i = 0; i < sizeof cases / sizeof *cases; ++i) {
        double _st[8] = {cases[i][0], 9.125};
        int _fp_top = 1, _fpu_cmp = 0;
        g_st_i64[1] = 73;
        LIFTED
        assert(_fp_top == 2 && _fpu_cmp == 1 && _st[2] == 9.125 && g_st_i64[2] == 73);
        assert(fabs(_st[0] - cases[i][1]) < 1e-12);
        assert(fabs(_st[1] - cases[i][2]) < 1e-12);
    }
    puts("PASS FSINCOS: 14 x86 oracle cases, cosine on top, sine below, lower stack and EFLAGS preserved");
    return 0;
}
'''.replace("CASES", ",".join(rows)).replace("LIFTED", lifted), {"push.h": push}, extra_flags=("/O2",))


if __name__ == "__main__":
    unittest.main()
