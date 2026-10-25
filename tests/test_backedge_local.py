"""Exact local loop counters through real register, call, yield and EH macros."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unittest

from test_mmx_packed import CLANG, ROOT, command, environment, pc_header
from test_user32_startup import body
sys.path.insert(0, str(ROOT / 'tools'))
import build_android as builder


def prepare_projection(out, header):
    fixture = (ROOT / 'tests/fixtures/x87_window_projection_probe.c').read_text()
    fixture = fixture.replace('#include <assert.h>', '#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <assert.h>')
    fixture = fixture.replace('static uint8_t memory[0x30000];', '')
    fixture = fixture.replace('#define ADDR(va) (memory+(uint32_t)(va))',
                              '#define ADDR(va) ((void *)((uintptr_t)(uint32_t)(va)+(uintptr_t)0x20000000u))')
    # The production window helpers, whatever the recentre's inline/outline attributes.
    recentre = re.search(r'^static [^\n]*\bvoid fp_window_recentre\(', header, re.M).start()
    helpers = header[recentre:header.index('#define fp_push(val) fp_window_push((val))')]
    fixture = fixture.replace('/* ACTUAL_WINDOW_HELPERS */', helpers).replace('/* BASELINE_WINDOW_HELPERS */', '')
    fixture = fixture.replace('baseline_window_', 'fp_window_')
    matches = list(re.finditer(r'^static __attribute__\(\(noinline\)\) void (original|cached)\(void\) \{.*?^\}', fixture, re.M | re.S))
    assert len(matches) == 2
    names = dict(zip(('eax', 'ecx', 'edx', 'ebx', 'esp', 'ebp', 'esi', 'edi', '_cf', '_flag_k', '_flag_a', '_flag_b'),
                     ('g_eax', 'g_ecx', 'g_edx', 'g_ebx', 'g_esp', 'g_ebp', 'g_esi', 'g_edi', 'g_flag_cf', 'g_flag_k', 'g_flag_a', 'g_flag_b')))
    rename = lambda text: re.sub(r'\b(' + '|'.join(names) + r')\b', lambda m: names[m[0]], text)
    aliases = ''.join('#define ' + n + ' l_' + n + '\n' for n in list(names)[:8])
    resets = ''.join('#undef ' + n + '\n' for n in list(names)[:8])
    macros = '\n'.join(next(line for line in header.splitlines() if line.startswith(marker)) for marker in
                        ('#define RECOMP_REGS_LOCALS ', '#define RECOMP_REGS_OUT() (g_eax',
                         '#define RECOMP_REGS_IN() (l_eax', '#define RECOMP_FLAGS_OUT() '))
    # The default loop counter (as the other probes build it); the waiter-gated
    # RECOMP_YIELD_ON_WAITERS variant reads native32's g_mach_waiters instead.
    backedge = next(m.group() for m in re.finditer(r'#define RECOMP_BACKEDGE\(\) do \{.*?while \(0\)', header, re.S)
                    if 'g_mach_waiters' not in m.group())
    macros += '\n#define RECOMP_XMM_OUT() ((void)0)\n#define RECOMP_XMM_IN() ((void)0)\n'
    macros += '#define RECOMP_BACKEDGE_OUT() ((void)0)\n#define RECOMP_BACKEDGE_IN() ((void)0)\n'
    macros += '#define RECOMP_BACKEDGE_COUNTER g_backedges\n#define RECOMP_YIELD_EVERY 65536u\n' + backedge + '\n'
    parts, pos = [], 0
    for i, match in enumerate(matches):
        parts.append(rename(fixture[pos:match.start()]))
        inner = match[0][match[0].index('{') + 1:-1]
        generated = ('void sub_F20000' + str(i) + '0(void) {\n    RECOMP_REGS_LOCALS\n'
                     '    uint32_t _cf=g_flag_cf,_flag_k=g_flag_k,_flag_a=g_flag_a,_flag_b=g_flag_b;\n'
                     '    RECOMP_BACKEDGE();\n' + inner +
                     '    RECOMP_BACKEDGE();\n    RECOMP_FLAGS_OUT(); RECOMP_REGS_OUT();\n}\n')
        if i:
            generated = builder.localize_backedges(generated.encode()).decode()
        parts.append('void sub_F20000' + str(i) + '0(void) __attribute__((noinline));\n' + aliases + generated + resets)
        pos = match.end()
    parts.append(rename(fixture[pos:]))
    fixture = ''.join(parts)
    point = fixture.index('#define fp_push(v)')
    fixture = fixture[:point] + macros + fixture[point:]
    point = fixture.index('static uint32_t g_eax')
    fixture = fixture[:point] + ('static uint32_t g_backedges,yield_count;\n'
                               'static void counter_yield(void);\nstatic void (*recomp_yield_hook)(void);\n') + fixture[point:]
    fixture = fixture.replace('int top,cmp,sp;uint16_t cw;', 'int top,cmp,sp;uint16_t cw;uint32_t counter,yields;')
    fixture = fixture.replace('s->sp=g_fp_sp;', 's->sp=g_fp_sp;s->counter=g_backedges;s->yields=yield_count;')
    fixture = fixture.replace('g_fp_sp=s->sp;', 'g_fp_sp=s->sp;g_backedges=s->counter;yield_count=s->yields;')
    fixture = fixture.replace('g_fp_sp=test%249;', 'g_fp_sp=test%249;g_backedges=(test%3==0)?0xFFFFFFFFu:(test%3==1?65535u:7u);yield_count=0;recomp_yield_hook=(test&1)?counter_yield:NULL;')
    fixture = fixture.replace('int main(void) {', 'static void counter_yield(void) {++yield_count;g_backedges=7;}\nint main(void) {\n    assert(VirtualAlloc((void *)0x20010000u,0x20000,MEM_RESERVE|MEM_COMMIT,PAGE_READWRITE)==(void *)0x20010000u);')
    fixture = fixture.replace('original();', 'sub_F2000000();').replace('cached();', 'sub_F2000010();')
    fixture = fixture.replace('current-vs-unhinted x87 window projection comparisons', 'global-vs-local counter projection comparisons')
    (out / 'generated.c').write_text(fixture)
    return ('generated',)


def prepare(out, mutant=None, arm=False, sort=False, projection=False):
    out.mkdir(parents=True, exist_ok=True)
    header = (ROOT / 'android/runtime/recomp_types.h').read_text()
    (out / 'recomp_types.h').write_text(header if arm else pc_header(header))
    if projection:
        return prepare_projection(out, header)
    if sort:
        original = (ROOT / 'generated/game-x86/game_0356.c').read_text()
        original = re.search(r'^void sub_008800B0\(void\) \{.*?^\}', original, re.M | re.S).group().encode() + b'\n'
        localized = builder.localize_backedges(original)
        prefix = '#include "recomp_types.h"\nvoid sub_008791F0(void),sub_00879240(void);\n'
        (out / 'baseline.c').write_text(prefix + original.decode().replace('sub_008800B0(void)', 'baseline_sort(void)'))
        (out / 'generated.c').write_text(prefix + localized.decode().replace('sub_008800B0(void)', 'local_sort(void)'))
        (out / 'probe.c').write_bytes((ROOT / 'tests/fixtures/backedge_sort_probe.c').read_bytes())
        return ('baseline', 'generated', 'probe')
    fixture = (ROOT / 'tests/fixtures/backedge_local_probe.c').read_text()
    start = fixture.index('/* GENERATED_BEGIN */')
    end = fixture.index('/* GENERATED_END */') + len('/* GENERATED_END */')
    generated = builder.localize_backedges(builder.localize_sse(fixture[start:end].encode())).decode()
    if mutant:
        old, new = {
            'flush': ('#define RECOMP_BACKEDGE_OUT() (g_backedges = l_backedges)', '#define RECOMP_BACKEDGE_OUT() ((void)0)'),
            'reload': ('#define RECOMP_BACKEDGE_IN() (l_backedges = g_backedges)', '#define RECOMP_BACKEDGE_IN() ((void)0)'),
            'reset': ('#define RECOMP_BACKEDGE_COUNTER g_backedges', '#define RECOMP_BACKEDGE_COUNTER l_backedges'),
        }[mutant]
        assert old in generated
        generated = generated.replace(old, new, 1)
    (out / 'generated.c').write_text(fixture[:start] + generated)
    probe = fixture[:start] + fixture[end:]
    core = (ROOT / 'android/host/core.c').read_text()
    host = (ROOT / 'android/host/host.h').read_text()
    definitions = core[core.index('VOID_HIDDEN uint32_t g_eax'):core.index('#define VOID_ENTER_RING')]
    definitions += '\nuint32_t g_enter_trace[1024],g_enter_idx;\n'
    replacements = {
        'ACTUAL_REGISTER_DEFS': definitions,
        'CURRENT_STATE': re.search(r'typedef struct void_regs \{.*?\} void_regs;', host, re.S).group(),
        'CURRENT_SAVE': body(core, 'void void_regs_save('),
        'CURRENT_LOAD': body(core, 'void void_regs_load('),
    }
    for tag, value in replacements.items():
        assert probe.count('/* ' + tag + ' */') == 1
        probe = probe.replace('/* ' + tag + ' */', value)
    (out / 'probe.c').write_text(probe)
    return ('generated', 'probe')


def run_probe(out, thin=False, mutant=None, arm=False, sort=False, threshold=65536, projection=False):
    sources = prepare(out, mutant, arm, sort, projection)
    env, linker = environment('x86')
    flags = [CLANG, '/nologo', '/W0', '/O2', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
             '/clang:--target=i686-pc-windows-msvc', '/clang:-fno-strict-aliasing',
             '/clang:-fwrapv', '/clang:-ffp-contract=off', '/DVOID_GUEST_BASE=0',
             '/DRECOMP_X87_WINDOW', '/DRECOMP_TRACE', '/DRECOMP_YIELD_EVERY=' + str(threshold) + 'u']
    if thin:
        flags += ['/clang:-flto=thin', '/Gy']
    if arm:
        flags = [builder.CLANG, '--target=' + builder.TARGET, '-O2', '-std=gnu11',
                 '-fno-strict-aliasing', '-fwrapv', '-ffp-contract=off', '-fPIE',
                 '-Werror', '-Wno-unused-variable', '-Wno-unused-label',
                 '-DRECOMP_X87_WINDOW', '-DRECOMP_TRACE', '-DRECOMP_YIELD_EVERY=' + str(threshold) + 'u']
        env = os.environ.copy()
    commands = []
    for name in sources:
        extra = (['-DRECOMP_GENERATED_CODE', '-DRECOMP_LOCAL_REGS', '-DRECOMP_PLAIN_MEMORY'] if arm else
                 ['/DRECOMP_GENERATED_CODE', '/DRECOMP_LOCAL_REGS', '/DRECOMP_PLAIN_MEMORY']) if name != 'probe' else []
        args = [*flags, *extra, '-c', name + '.c', '-o', name + '.obj'] if arm else [*flags, *extra, '/c', name + '.c', '/Fo' + name + '.obj']
        commands.append(list(map(str, args)))
        result = command(args, out, env, check=False)
        if result.returncode:
            assert mutant == 'reset', result.stdout + result.stderr
            (out / 'receipt.json').write_text(json.dumps(dict(
                stage='expected_compile_rejection', mutant=mutant, commands=commands,
                exit=result.returncode, stdout=result.stdout, stderr=result.stderr,
                executable_run=False,
                source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.c')},
                header_sha256=hashlib.sha256((out / 'recomp_types.h').read_bytes()).hexdigest()), indent=2) + '\n')
            return result
    objects = [name + '.obj' for name in sources]
    if arm:
        args = [builder.CLANG, '--target=' + builder.TARGET, '-pie', *objects, '-lm', '-o', 'probe']
    else:
        tool = [CLANG.with_name('ld.lld.exe'), '-flavor', 'link'] if thin else [linker]
        extra = ['/threads:1', '/opt:lldltojobs=1', '/opt:lldlto=2'] if thin else []
        args = [*tool, '/nologo', *objects, '/OUT:probe.exe', '/BASE:0x70000000', '/DYNAMICBASE:NO', '/FIXED', *extra]
    commands.append(list(map(str, args)))
    command(args, out, env)
    executable = out / ('probe' if arm else 'probe.exe')
    if arm:
        elf = executable.read_bytes()
        assert elf[:5] == b'\x7fELF\x02' and int.from_bytes(elf[18:20], 'little') == 183
        import subprocess
        result = subprocess.CompletedProcess([str(executable)], 0, 'ARM64 built; device execution pending', '')
    else:
        result = command([executable], out, env, check=False)
    (out / 'receipt.json').write_text(json.dumps(dict(thinlto=thin, mutant=mutant,
        arm64_build_only=arm, sort=sort, projection=projection, threshold=threshold, commands=commands,
        exit=result.returncode, stdout=result.stdout, stderr=result.stderr,
        executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
        source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('*.c')},
        header_sha256=hashlib.sha256((out / 'recomp_types.h').read_bytes()).hexdigest()), indent=2) + '\n')
    return result


class BackedgeLocalTest(unittest.TestCase):
    def test_source_scope_and_idempotence(self):
        body = b'void sub_00401000(void) {\n    RECOMP_REGS_LOCALS\n    RECOMP_BACKEDGE();\n}\n'
        localized = builder.localize_backedges(body)
        self.assertIn(b'uint32_t l_backedges = g_backedges;', localized)
        self.assertEqual(builder.localize_backedges(localized), localized)
        self.assertEqual(builder.localize_backedges(b'void sub_00401000(void) {\n}\n'), b'void sub_00401000(void) {\n}\n')
        self.assertIn(builder.BACKEDGE_GLOBAL, localized)
        self.assertNotIn(b'#undef _xmm', localized)

    def test_production_selection_preserves_other_bodies(self):
        names = (b'sub_00401000', *builder.BACKEDGE_HOT_FUNCTIONS, b'sub_00B1C300')
        bodies = [b'void ' + name + b'(void) {\n    RECOMP_REGS_LOCALS\n    RECOMP_BACKEDGE();\n}\n' for name in names]
        for newline in (b'\n', b'\r\n'):
            source = b''.join(bodies).replace(b'\n', newline)
            selected = builder.localize_backedges(source, builder.BACKEDGE_HOT_FUNCTIONS)
            self.assertEqual(selected.count(b'uint32_t l_backedges = g_backedges;'), 2)
            self.assertEqual(builder.localize_backedges(selected, builder.BACKEDGE_HOT_FUNCTIONS), selected)
            self.assertEqual(builder.localize_backedges(source, ()), source)
            for body in (bodies[0], bodies[-1]):
                self.assertIn(body.replace(b'\n', newline), selected)
            self.assertEqual(builder.localize_backedges(source).count(b'uint32_t l_backedges = g_backedges;'), 4)

    def test_full_vm_transfers_and_negative_controls(self):
        for thin, threshold in [(False, 65536), (True, 65536), (False, 7), (False, 1)]:
            out = ROOT / 'build/tests/backedge_local' / ('thin' if thin else 'o2') / str(threshold)
            result = run_probe(out, thin=thin, threshold=threshold)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('2048 random counter/threshold/wrap cases', result.stdout)
        for mutant in ['flush', 'reload', 'reset']:
            result = run_probe(ROOT / 'build/tests/backedge_local' / mutant, mutant=mutant)
            self.assertNotEqual(result.returncode, 0, mutant)
            self.assertIn('l_backedges' if mutant == 'reset' else 'FAIL', result.stdout + result.stderr)

    def test_actual_whole_sort_o2_and_thinlto(self):
        for thin in [False, True]:
            result = run_probe(ROOT / 'build/tests/backedge_sort' / ('thin' if thin else 'o2'), thin=thin, sort=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('42 actual whole-sort comparisons', result.stdout)

    def test_arm64_full_transfer_probe_build(self):
        result = run_probe(ROOT / 'build/tests/backedge_local/arm64', arm=True)
        self.assertIn('device execution pending', result.stdout)

    def test_raw_projection_with_actual_counter_and_register_macros(self):
        for thin in [False, True]:
            result = run_probe(ROOT / 'build/tests/backedge_projection' / ('thin' if thin else 'o2'), thin=thin, projection=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('4096 global-vs-local counter projection comparisons', result.stdout)


if __name__ == '__main__':
    unittest.main()
