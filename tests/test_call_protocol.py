"""Decoded x87 flag effects and masked exits observed by a full-protocol caller."""
import json
import sys
import tempfile
from pathlib import Path
import unittest

from capstone import Cs, CS_ARCH_X86, CS_MODE_32
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / 'tools'))
import call_protocol
from protocol_transform import Protocol, transform_body


class CallProtocolTest(unittest.TestCase):
    def test_popping_x87_compares_kill_the_callers_flags(self):
        decoder = Cs(CS_ARCH_X86, CS_MODE_32)
        decoder.detail = True
        for opcode in ('dff1', 'dfe9'):
            instruction = next(decoder.disasm(bytes.fromhex(opcode), 0x10000))
            self.assertIn(instruction.mnemonic, ('fcompi', 'fucompi'))
            decoded = call_protocol.classify(instruction)
            self.assertEqual((decoded.flag_use, decoded.flag_kill), (0, call_protocol.FL_BOTH))

    def test_preserved_registers_are_current_for_full_protocol_callers_in_every_edition(self):
        header = (ROOT / 'android/runtime/recomp_types.h').read_text()
        macros = header[header.index('/* Masked call protocol'):header.index('/* `push target; ret`')]
        prefix = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define RECOMP_GENERATED_CODE 1
#define RECOMP_LOCAL_REGS 1
static uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
#define RECOMP_REGS_LOCALS uint32_t l_eax=g_eax,l_ecx=g_ecx,l_edx=g_edx,l_ebx=g_ebx,l_esp=g_esp,l_ebp=g_ebp,l_esi=g_esi,l_edi=g_edi;
#define ebx l_ebx
#define esi l_esi
#define edi l_edi
#define ebp l_ebp
#define esp l_esp
#define RECOMP_XMM_OUT() ((void)0)
#define RECOMP_XMM_IN() ((void)0)
#define RECOMP_BACKEDGE_OUT() ((void)0)
#define RECOMP_BACKEDGE_IN() ((void)0)
#define RECOMP_FLAGS_OUT() ((void)0)
#define RECOMP_RETADDR 0
#define PUSH32(s,v) ((s)-=4)
#include "protocol.h"
#define RECOMP_REGS_OUT() RECOMP_PUBLISH(0xFFu)
#define RECOMP_BACKEDGE() RECOMP_PUBLISH(0xFFu)
#define RECOMP_EH_ENTER() RECOMP_PUBLISH(0xFFu)
#define RECOMP_CALL(f) do { RECOMP_PUBLISH(0xFFu); f(); RECOMP_RELOAD(0xFFu); } while(0)
static void sub_00000002(void) { g_esp+=4; }
static void host_callback(void) { assert(g_ebx==20&&g_esi==30&&g_edi==40&&g_ebp==50); }
'''
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'summary.json'
            for edition in ('toe', 'vanilla', 'hof'):
                path.write_text(json.dumps(dict(edition=edition, flags_in=[], flags_out=[], problems=[],
                    regs={'sub_00000002': [0xE8, 0]}, names=['sub_00000001', 'sub_00000002'])))
                protocol = Protocol(path, edition=edition)
                functions, checks = [], []
                for index, publication in enumerate(('RECOMP_CALL(sub_00000002);',
                        'RECOMP_CALL(host_callback);', 'RECOMP_BACKEDGE();', 'RECOMP_EH_ENTER();', '')):
                    body = ('\n    RECOMP_REGS_LOCALS\n'
                        '    ebx=20;esi=30;edi=40;ebp=50;\n    ' + publication + '\n'
                        '    ebx=2;esi=3;edi=4;ebp=5;\n    RECOMP_REGS_OUT(); return;\n}\n').encode()
                    transformed = transform_body('sub_00000001', body, protocol, 'game').decode()
                    functions.append('static void probe_' + str(index) + '(void) {' + transformed)
                    checks.append('g_ebx=2;g_esi=3;g_edi=4;g_ebp=5;probe_' + str(index) + '();'
                                  'assert(g_ebx==2&&g_esi==3&&g_edi==4&&g_ebp==5);')
                harness = prefix + '\n'.join(functions) + '\nint main(void) {' + ''.join(checks) + '\nreturn 0;}'
                compile_probe('protocol-clean-exits-' + edition, harness, {'protocol.h': macros})


if __name__ == '__main__':
    unittest.main()
