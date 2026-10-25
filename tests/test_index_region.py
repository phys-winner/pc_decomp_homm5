"""Exact whole-function hardware and yield oracles for the shared index pass."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import unittest

import capstone
import pefile

from test_d3d_lifecycle import function
from test_mmx_packed import CLANG, ROOT, command, environment, pc_header

sys.path.insert(0, str(ROOT / 'tools'))
import build_android as builder
import index_region as index_pass

OUTPUT = ROOT / 'build/pc-full/index-region-proof/production'
NATIVE_SHA = 'f1a679ffb91c3756591556d1e33616542e74a04b09f3926e51575b877dcf33c7'
INPUT_IDENTITIES = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in
                    (Path(index_pass.__file__), ROOT / 'tools/build_android.py', ROOT / 'android/runtime/recomp_types.h')}


def unchanged_inputs():
    for path, digest in INPUT_IDENTITIES.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, 'Proof input changed while running: ' + path


def mutate(source, name):
    if name == 'overlap-snapshot':
        replacements = (
            ('(h5_src_end <= edi || h5_dst_end <= esi)', '1u'),
            ('} while ((int32_t)eax > 0);', '} while ((int32_t)eax > 0);\n                uint8_t h5_source_snapshot[65532]; memcpy(h5_source_snapshot, (const void *)ADDR(esi), h5_n * 2u);'),
            ('h5_u16x4 h5_input = *(volatile h5_u16x4 *)ADDR(esi);', 'h5_u16x4 h5_input; memcpy(&h5_input, h5_source_snapshot + h5_i * 8u, 8);'),
            ('eax = (uint32_t)*(volatile h5_unaligned16 *)ADDR(esi) + ebx;', 'uint16_t h5_tail; memcpy(&h5_tail, h5_source_snapshot + (h5_n - ecx) * 2u, 2); eax = (uint32_t)h5_tail + ebx;'))
    else:
        replacements = ({
            'budget': ('h5_steps < RECOMP_YIELD_EVERY - RECOMP_BACKEDGE_COUNTER', '1u'),
            'warmup': ('edx = *(volatile h5_unaligned32 *)ADDR(esi + eax * 2u);', 'edx = 0;'),
            'widen': ('__builtin_convertvector(h5_input,h5_u32x4) + h5_bias', '__builtin_convertvector(h5_input,h5_u32x4) - h5_bias'),
            'counter': ('RECOMP_BACKEDGE_COUNTER += h5_steps;', 'RECOMP_BACKEDGE_COUNTER += h5_steps + 1u;')}[name],)
    for old, new in replacements:
        assert source.count(old) == 1, old
        source = source.replace(old, new, 1)
    return source


def prepare(out, mutant=None):
    unchanged_inputs()
    out.mkdir(parents=True, exist_ok=True)
    raw = (ROOT / 'generated/input/H5_Game.exe').read_bytes()
    manifest = json.loads((ROOT / 'config/modules.json').read_text())
    assert hashlib.sha256(raw).hexdigest() == manifest[0]['sha256']
    pe = pefile.PE(data=raw, fast_load=True)
    try:
        native = pe.get_data(0xC362E0 - pe.OPTIONAL_HEADER.ImageBase, 606)
    finally:
        pe.close()
    assert hashlib.sha256(native).hexdigest() == NATIVE_SHA
    assert native[-3:] == b'\xC2\x14\x00'
    (out / 'native_code.h').write_text('static const unsigned char original_code[] = {' + ','.join(map(str, native)) + '};\n')
    canonical = function((ROOT / 'generated/game-x86/game_0641.c').read_text(), 'void sub_00C362E0(void) {') + '\n'
    original = canonical.encode()
    canonical = builder.localize_backedges(original).decode()
    localized = builder.localize_backedges(index_pass.index_region(original)).decode()
    assert localized != canonical
    if mutant:
        localized = mutate(localized, mutant)
    declarations = '\n'.join('void ' + name + '(void);' for name in sorted(set(re.findall(r'RECOMP_CALL\((\w+)\)', canonical))))
    for prefix, body in (('before', canonical), ('after', localized)):
        body = body.replace('sub_00C362E0', prefix + '_index')
        (out / (prefix + '.c')).write_text('#include "recomp_types.h"\n' + declarations + '\n' + body)
    (out / 'probe.c').write_text((ROOT / 'tests/fixtures/index_region_probe.c').read_text())
    (out / 'recomp_types.h').write_text(pc_header((ROOT / 'android/runtime/recomp_types.h').read_text()))
    (out / 'input-identities.json').write_text(json.dumps(INPUT_IDENTITIES, indent=2) + '\n')


def codegen(out):
    rows = []
    for line in (out / 'probe.map').read_text().splitlines():
        match = re.match(r'\s*0001:[0-9A-Fa-f]{8}\s+(\S+)\s+([0-9A-Fa-f]{8,16})\s+', line)
        if match:
            rows.append((int(match[2], 16), match[1]))
    names = {name: address for address, name in rows}
    # Public data are in their own MAP section.
    for line in (out / 'probe.map').read_text().splitlines():
        match = re.match(r'\s*\d+:[0-9A-Fa-f]{8}\s+(_g_mm)\s+([0-9A-Fa-f]{8,16})\s+', line)
        if match:
            names[match[1]] = int(match[2], 16)
    pe = pefile.PE(str(out / 'probe.exe'), fast_load=True)
    cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    cs.detail = True
    report = {}
    try:
        for variant in ('before', 'after'):
            start = names['_' + variant + '_index']
            end = min(address for address, _ in rows if address > start)
            instructions = list(cs.disasm(pe.get_data(start - pe.OPTIONAL_HEADER.ImageBase, end - start), start))
            (out / (variant + '-assembly.txt')).write_text('\n'.join(f'{i.address:08X} {i.mnemonic} {i.op_str}' for i in instructions) + '\n')
            loops = []
            for branch in instructions:
                if branch.mnemonic.startswith('j') and len(branch.operands) == 1 and branch.operands[0].type == capstone.x86.X86_OP_IMM:
                    target = branch.operands[0].imm
                    body = [i for i in instructions if target <= i.address <= branch.address]
                    if not body or target >= branch.address or not any(i.mnemonic == 'punpcklwd' for i in body):
                        continue
                    mm_refs = [f'{i.address:08X} {i.mnemonic} {i.op_str}' for i in body for op in i.operands
                               if op.type == capstone.x86.X86_OP_MEM and names['_g_mm'] <= op.mem.disp < names['_g_mm'] + 64]
                    loops.append(dict(start=target, end=branch.address, instructions=len(body), global_mmx_references=mm_refs))
            report[variant] = dict(bytes=end - start, instructions=len(instructions), packed_loops=loops)
    finally:
        pe.close()
    (out / 'codegen.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def probe(out, thin=False, mutant=None, timing=False):
    prepare(out, mutant)
    flags = [CLANG, '/nologo', '/W0', '/O2', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
             '/clang:--target=i686-pc-windows-msvc', '/clang:-fno-strict-aliasing', '/clang:-fwrapv', '/clang:-ffp-contract=off',
             '/DVOID_GUEST_BASE=0', '/DRECOMP_X87_WINDOW', '/DPC_INDEX_TIMING=' + str(int(timing))]
    if thin:
        flags += ['/clang:-flto=thin', '/Gy']
    env, linker = environment('x86')
    for name in ('before', 'after', 'probe'):
        extra = ['/DRECOMP_GENERATED_CODE', '/DRECOMP_LOCAL_REGS', '/DRECOMP_PLAIN_MEMORY', '/DRECOMP_TRACE'] if name != 'probe' else []
        command([*flags, *extra, '/c', name + '.c', '/Fo' + name + '.obj'], out, env)
    link = [CLANG.with_name('ld.lld.exe'), '-flavor', 'link'] if thin else [linker]
    lto = ['/threads:1', '/opt:lldltojobs=1', '/opt:lldlto=2', '/lldltocache:' + str(out / 'thinlto-cache')] if thin else []
    command([*link, '/nologo', 'before.obj', 'after.obj', 'probe.obj', '/OUT:probe.exe', '/MAP:probe.map',
             '/BASE:0x70000000', '/DYNAMICBASE:NO', '/FIXED', '/STACK:262144', *lto], out, env)
    tested = command([out / 'probe.exe'], out, env, check=False)
    unchanged_inputs()
    proof = codegen(out) if tested.returncode == 0 and not mutant else None
    receipt = dict(thinlto=thin, mutant=mutant, returncode=tested.returncode, stdout=tested.stdout, stderr=tested.stderr,
                   original_pe_sha256=hashlib.sha256((ROOT / 'generated/input/H5_Game.exe').read_bytes()).hexdigest(),
                   original_function_sha256=NATIVE_SHA, flags=list(map(str, flags)), codegen=proof,
                   source_sha256={name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in ('before.c', 'after.c', 'probe.c', 'recomp_types.h')},
                   executable_sha256=hashlib.sha256((out / 'probe.exe').read_bytes()).hexdigest(), input_identities=INPUT_IDENTITIES)
    if (out / 'native-vectors.bin').exists():
        receipt['native_vectors'] = dict(bytes=(out / 'native-vectors.bin').stat().st_size,
                                         sha256=hashlib.sha256((out / 'native-vectors.bin').read_bytes()).hexdigest())
    (out / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return tested, proof


def android_probe(out, vectors):
    """Build only; the root operator owns all device execution."""
    prepare(out)
    shutil.copyfile(ROOT / 'android/runtime/recomp_types.h', out / 'recomp_types.h')
    shutil.copyfile(vectors, out / 'native-vectors.bin')
    compiler = CLANG.with_name('clang.exe')
    flags = [compiler, *builder.COMMON, '-O2', '-std=c11', '-D_GNU_SOURCE', '-Werror']
    env, _ = environment('x64')
    for name in ('before', 'after', 'probe'):
        extra = ['-DRECOMP_GENERATED_CODE', '-DRECOMP_LOCAL_REGS', '-DRECOMP_PLAIN_MEMORY', '-DRECOMP_TRACE'] if name != 'probe' else []
        command([*flags, *extra, '-c', name + '.c', '-o', name + '.o'], out, env)
    command([*flags, 'before.o', 'after.o', 'probe.o', '-o', 'probe-arm64'], out, env)
    disassembly = command([CLANG.with_name('llvm-objdump.exe'), '-d', '--no-show-raw-insn', out / 'probe-arm64'], out, env)
    (out / 'assembly.txt').write_text(disassembly.stdout)
    unchanged_inputs()
    receipt = dict(device_execution='pending_root', flags=list(map(str, flags)), original_function_sha256=NATIVE_SHA,
                   guest_base='0x2000000000', target=builder.TARGET,
                   input_identities=INPUT_IDENTITIES,
                   files={name: dict(bytes=(out / name).stat().st_size, sha256=hashlib.sha256((out / name).read_bytes()).hexdigest())
                          for name in ('probe-arm64', 'native-vectors.bin', 'before.c', 'after.c', 'probe.c', 'recomp_types.h')})
    (out / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


class IndexRegionTest(unittest.TestCase):
    def test_original_whole_function_o2_and_thinlto(self):
        for thin in (False, True):
            with self.subTest(thinlto=thin):
                result, proof = probe(OUTPUT / ('thinlto' if thin else 'o2'), thin=thin)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('"native_whole_function":"PASS"', result.stdout)
                self.assertIn('"mutating_yield":"PASS"', result.stdout)
                self.assertTrue(any(not loop['global_mmx_references'] for loop in proof['after']['packed_loops']), proof)

    def test_faulty_budget_registers_counter_and_overlap_are_rejected(self):
        for mutant in ('budget', 'warmup', 'widen', 'counter', 'overlap-snapshot'):
            with self.subTest(mutant=mutant):
                result, _ = probe(OUTPUT / ('bad-' + mutant), mutant=mutant)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('mismatch', result.stderr)


if __name__ == '__main__':
    unittest.main()
