"""CALL-next must push the real EIP and continue once, including overlapping owners."""
import hashlib
import json
import re
import struct
import sys
import unittest

import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32
from unicorn.x86_const import UC_X86_REG_EFLAGS, UC_X86_REG_ESP
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
from lift_game import CheckedLifter
from tools.disasm.disasm32 import Instruction
import call_protocol

SITES = {"toe": (0x6B0001, 0xBD55FF, 0xBD56DB),
         "vanilla": (0x895A8F, 0x895B6B, 0xC5D912), "hof": (0xB2B03F, 0xB2B11B)}


class CallNextTest(unittest.TestCase):
    def test_protocol_does_not_invent_a_callee_for_inline_call_next(self):
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        for displacement, expected in ((0, None), (1, ("direct", "sub_other"))):
            code = b"\xe8" + struct.pack("<i", displacement) + bytes.fromhex("0f94c1c3")
            decoded = {i.address: call_protocol.classify(i) for i in decoder.disasm(code, 0x10000)}
            f = call_protocol.Function("sub_test", 0x10000, {"name": "game"}, "fixture.c")
            f.addresses = sorted(decoded)
            f.tags = ["op" if not displacement else "call", "op", "ret"]
            f.callees = {0x10000: "sub_other"} if displacement else {}
            body = call_protocol.build_body(f, decoded, {})
            self.assertEqual(body.call[0], expected)
            self.assertEqual(body.succ[0], [1])
            self.assertEqual(body.insns[1].flag_use, call_protocol.FL_L)

    def test_actual_emission_against_x86_stack_and_flags(self):
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        cases = []
        for address in (*SITES["toe"], *SITES["vanilla"], *SITES["hof"], 0xFFFFFFFB):
            for flags in (0x202, 0x246, 0xAD7):
                uc = Uc(UC_ARCH_X86, UC_MODE_32)
                uc.mem_map(address & ~4095, 4096)
                uc.mem_map(0x10000, 4096)
                uc.mem_write(address, bytes.fromhex("e800000000"))
                uc.reg_write(UC_X86_REG_ESP, 0x10040)
                uc.reg_write(UC_X86_REG_EFLAGS, flags)
                uc.emu_start(address, (address + 5) & 0xFFFFFFFF, count=1)
                sp = uc.reg_read(UC_X86_REG_ESP) - 0x10000
                word = struct.unpack("<I", uc.mem_read(0x10000 + sp, 4))[0]
                self.assertEqual(uc.reg_read(UC_X86_REG_EFLAGS), flags)
                i = next(decoder.disasm(bytes.fromhex("e800000000"), address))
                instruction = Instruction(i.address, i.size, i.mnemonic, i.op_str, i.bytes, i.operands)
                lifter = CheckedLifter()
                lifter._flag_state = ("cmp", "0x123u, 0x456u")
                emitted = "\n".join(lifter.lift_instruction(instruction))
                cases.append("{ uint32_t esp=64;\n" + emitted +
                             f"\nassert(esp=={sp} && MEM32(esp)==0x{word:08X}u && !calls); }}")
                self.assertEqual(lifter._flag_state, ("cmp", "0x123u, 0x456u"))
        header = (ROOT / "android/runtime/recomp_types.h").read_text(encoding="utf8")
        start = header.index("#define PUSH32(")
        push = header[start:header.index("\n\n", start)]
        compile_probe("call-next", r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
static uint32_t memory[32], calls;
#define MEM32(a) memory[(a)/4]
#include "push.h"
#define RECOMP_CALL(fn) do { ++calls; PUSH32(esp,0xDEAD0000u); esp+=4; } while(0)
#define RECOMP_FLAGS_IN() ((void)0)
int main(void) {
    CASES
    puts("PASS CALL-next: 27 x86 cases, real EIP, one push, no C continuation and unchanged flags");
    return 0;
}
'''.replace("CASES", "\n".join(cases)), {"push.h": push}, extra_flags=("/O2",))

    def test_pinned_original_sites_and_every_generated_owner(self):
        owners = 0
        for edition, sites in SITES.items():
            root = ROOT / "generated" / ("" if edition == "toe" else edition)
            report = json.loads((root / "game-x86/report.json").read_text())
            raw = (root / "input/H5_Game.exe").read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), report["rebased_sha256"])
            pe = pefile.PE(data=raw, fast_load=True)
            for site in sites:
                self.assertEqual(pe.get_data(site - pe.OPTIONAL_HEADER.ImageBase, 5), bytes.fromhex("e800000000"))
            for source in report["sources"]:
                text = (root / "game-x86" / source).read_text(encoding="utf8")
                for site in sites:
                    for line in text.splitlines():
                        if f"/* 0x{site:08X}: call " in line:
                            self.assertIn(f"PUSH32(esp, 0x{site + 5:08X}u);", line)
                            self.assertNotIn("RECOMP_CALL", line)
                            owners += 1
        self.assertEqual(owners, 19)


if __name__ == "__main__":
    unittest.main()
