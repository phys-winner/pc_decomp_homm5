"""Only the original desktop-fade startup sleep is removed, in all editions."""
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

import pefile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tests')]
import build_android as builder
import port_patches
from editions import generated_root
from test_mmx_packed import CLANG, command, environment, pc_header
from test_observer_native import PREFIX
from test_scene_native import body

# Own-original PE bytes/imports and independently located functions. Do not
# derive these expectations from the live address adapter or proposal files.
FACTS = {
    'toe': ('00D11800', '00D11730', '00D11630', '00D11833', '00D1183D', 'game_0707.c',
            '6502a8c4cd0e03e9ce43b474bcb4a85acb8b8bf5050d56317e93c8f13fff50bd'),
    'vanilla': ('00C0D4A0', '00C0D3D0', '00C0D2D0', '00C0D4D3', '00C0D4DD', 'game_0653.c',
                '2b4e8bd32bd929e8caf1d53f74bc4aa6be56c362080549b9dc675d4e88289950'),
    'hof': ('00C099C0', '00C098F0', '00C097F0', '00C099F3', '00C099FD', 'game_0650.c',
            'bad3b0c010b9d85193811bdf8ffa2afab30b865ea924c480ff7aac78a1e73140'),
}
OUT = ROOT / 'build/tests/launch-fade-native'


def proposal(edition):
    entry, _, _, site, _, _, _ = FACTS[edition]
    old = '    PUSH32(esp, 0x8E8u); /* 0x' + site + ': push 0x8e8 */'
    return {'module': 'game', 'function': 'sub_' + entry, 'old': old,
            'new': old.replace('PUSH32(esp, 0x8E8u)', 'PUSH32(esp, 0)')}


def production_pair(edition):
    """Use the real builder before/after only this proposed contract entry."""
    builder.configure_edition(edition)
    builder.OUT = OUT / edition / 'actual-builder'
    contract = port_patches.load_contract(edition)
    patch = proposal(edition)
    existing = [p for p in contract['generated_patches'] if p['module'] == 'game' and p['function'] == patch['function']]
    if existing and existing != [patch]:
        raise AssertionError('Unexpected existing fade-helper patch: ' + repr(existing))
    before = copy.deepcopy(contract)
    before['generated_patches'] = [p for p in before['generated_patches'] if p not in existing]
    after = copy.deepcopy(before)
    after['generated_patches'].append(patch)
    source = generated_root(edition) / 'game-x86' / FACTS[edition][5]
    whole = []
    for selected in (before, after):
        with mock.patch.object(port_patches, 'load_contract', return_value=selected), mock.patch.object(builder, 'PGO_USE', True):
            prepared, _ = builder.override_source(source, local_xmm=True)
            whole.append(prepared.read_text(encoding='utf-8'))
    if whole[1].count(patch['new']) != 1 or whole[0].count(patch['old']) != 1:
        raise AssertionError('The transformed exact fade anchor is not unique')
    if whole[1].replace(patch['new'], patch['old']) != whole[0]:
        raise AssertionError('Generated production code changed beyond the one Sleep operand')
    return source, whole, patch


HARNESS = PREFIX.replace('MEMORY_BYTES=0x80000', 'MEMORY_BYTES=0x1120000')
HARNESS = HARNESS.replace('MAX_EVENTS=1024', 'MAX_EVENTS=8')
FIXTURE = r'''
#include "names.h"
enum { CREATE_FN=0x1234,SLEEP_FN=0x1238,LOAD_FN=0x123C,PROC_FN=0x1240 };
static uint32_t requested_sleep,sleep_slot;
static unsigned scenario,load_calls,proc_calls;
static void alter_volatile(void) {
    g_ecx=0x71990000u|scenario;g_edx=0xE1990000u|scenario;
    g_flag_k=FK_ADD;g_flag_a=0x9911;g_flag_b=17;g_flag_cf=1;
    if(scenario&2) {
        g_st[2]+=0.25;g_st_i64[3]^=0x55AA55AA55AA55AAll;
        g_mm[4]^=0x1234567890ABCDEFull;((uint32_t*)g_xmm)[7]^=0x7FC0ABCD;
        g_fpu_cw^=0x400;g_mxcsr^=0x2000;void_fpu_cmp^=3;
    }
}
static void create_thread(void) {
    record(1);++callbacks;
    assert(MEM32(g_esp+4)==0&&MEM32(g_esp+8)==0&&MEM32(g_esp+12)==WORKER_VA);
    assert(MEM32(MEM32(g_esp+16))==1&&MEM32(g_esp+20)==0);
    if(!(scenario&1))MEM32(MEM32(g_esp+24))=0x1000u+scenario;
    alter_volatile();g_eax=(scenario&1)?0:0xA5010000u|scenario;g_esp+=28;
}
static void sleep_call(void) {
    requested_sleep=MEM32(g_esp+4);sleep_slot=g_esp+4;record(2);++callbacks;
    alter_volatile();g_eax=0;g_esp+=8;
}
static void load_library(void) {
    record(3);++load_calls;
    assert(!strcmp(GPTR(MEM32(g_esp+4)),LIBRARY_NAME));
    alter_volatile();g_eax=(scenario&1)?0:0xA0010000u;g_esp+=8;
}
static void get_proc(void) {
    record(4);++proc_calls;
    assert(MEM32(g_esp+4)==0xA0010000u);
    assert(!strcmp(GPTR(MEM32(g_esp+8)),"SetLayeredWindowAttributes"));
    alter_volatile();g_eax=0;g_esp+=12;
}
recomp_func_t void_resolve(uint32_t address) {
    switch(address){case CREATE_FN:return create_thread;case SLEEP_FN:return sleep_call;
        case LOAD_FN:return load_library;case PROC_FN:return get_proc;default:
        fprintf(stderr,"unexpected startup dependency %08x\n",address);abort();}
}
#define CREATOR_CANONICAL creator_unsupported
#include "before.h"
#include "after.h"
#include "creator.h"
#include "worker.h"
static void discard(void){for(unsigned i=0;i<events;i++)free(log_events[i].guest_memory);events=0;}
static void setup(unsigned seed) {
    memset(memory,(int)seed,sizeof memory);scenario=seed;
    g_eax=0xAABB0000u|seed;g_ecx=0x11220000u|seed;g_edx=0xCCDD0000u|seed;
    g_ebx=0x12345678;g_esp=STACK_VA;g_ebp=0x33445566;g_esi=0x778899AA;g_edi=0xBBCCDDEE;
    g_flag_k=FK_TEST;g_flag_a=seed;g_flag_b=3;g_flag_cf=1;g_backedges=7;
    g_cur_func=0x99887766;g_enter_idx=0;memset(g_enter_trace,0,sizeof g_enter_trace);
    for(unsigned i=0;i<RECOMP_X87_SLOTS;i++){uint64_t bits=0x7FF8000000000000ull+i;memcpy(g_st_win+i,&bits,8);g_st_i64_win[i]=0x1100000000000000ll+i;}
    for(unsigned i=0;i<8;i++)g_mm[i]=0x2233445566778899ull+i;
    for(unsigned i=0;i<32;i++)((uint32_t*)g_xmm)[i]=0x7FC01200+i;
    g_fp_sp=120;g_fp_top=3;g_fpu_cw=0xC7F;g_mxcsr=0x1F80;void_fpu_cmp=0x45;
    MEM32(STACK_VA)=RECOMP_RETADDR;MEM32(STACK_VA+4)=1;
    MEM32(CREATE_IAT)=CREATE_FN;MEM32(SLEEP_IAT)=SLEEP_FN;MEM32(LOAD_IAT)=LOAD_FN;MEM32(PROC_IAT)=PROC_FN;
    memcpy(GPTR(LIBRARY_STRING),LIBRARY_NAME,sizeof LIBRARY_NAME);
    memcpy(GPTR(PROC_STRING),"SetLayeredWindowAttributes",sizeof "SetLayeredWindowAttributes");
    callbacks=events=load_calls=proc_calls=0;requested_sleep=sleep_slot=0;recomp_yield_hook=NULL;
}
static void equal_except_sleep(const uint8_t *old,const uint8_t *now,uint32_t slot) {
    assert(slot==STACK_VA-12);uint32_t before,after;
    memcpy(&before,old+slot,4);memcpy(&after,now+slot,4);assert(before==2280&&after==0);
    assert(!memcmp(old,now,slot));assert(!memcmp(old+slot+4,now+slot+4,sizeof memory-slot-4));
}
int main(void) {
    for(unsigned seed=0;seed<16;seed++) {
        setup(seed);launch_before();assert(callbacks==2&&events==2&&requested_sleep==2280);
        saved_final=capture();memcpy(saved_memory,memory,sizeof memory);memcpy(saved_events,log_events,sizeof log_events);
        uint32_t old_slot=sleep_slot;
        setup(seed);launch_after();state now=capture();assert(callbacks==2&&events==2&&requested_sleep==0&&sleep_slot==old_slot);
        assert(!memcmp(&saved_final,&now,sizeof now));equal_except_sleep(saved_memory,memory,sleep_slot);
        for(unsigned i=0;i<2;i++){
            assert(saved_events[i].kind==i+1&&log_events[i].kind==i+1);
            assert(!memcmp(&saved_events[i].cpu,&log_events[i].cpu,sizeof(state)));
            if(i)equal_except_sleep(saved_events[i].guest_memory,log_events[i].guest_memory,sleep_slot);
            else assert(!memcmp(saved_events[i].guest_memory,log_events[i].guest_memory,sizeof memory));
            free(saved_events[i].guest_memory);
        }
        discard();setup(seed);fade_worker();
        assert(g_esp==STACK_VA+8&&g_eax==0&&load_calls==1&&proc_calls==((seed&1)?0:1));
        assert(callbacks==0&&events==((seed&1)?1:2));discard();
    }
    puts("PASS 16 startup before/after full CPU+guest snapshots;only explicit Sleep DWORD2280->0;unsupported worker exits before timer/window dependencies");return 0;
}
'''


class LaunchFadeNativeTest(unittest.TestCase):
    def test_all_three_actual_builder_and_native_state(self):
        for edition, (entry, worker, creator, site, sleep_site, unit, image_sha) in FACTS.items():
            with self.subTest(edition=edition):
                image = generated_root(edition) / 'input/H5_Game.exe'
                self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), image_sha)
                pe = pefile.PE(str(image))
                base = pe.OPTIONAL_HEADER.ImageBase
                get = lambda va, count: pe.get_data(int(va, 16) - base, count)
                self.assertEqual(get(site, 5), bytes.fromhex('68e8080000'))
                imports = {f.name.decode(): f.address for d in pe.DIRECTORY_ENTRY_IMPORT for f in d.imports if f.name}
                self.assertEqual(get(sleep_site, 6), b'\xFF\x15' + imports['Sleep'].to_bytes(4, 'little'))
                source, whole, patch = production_pair(edition)
                original = body(whole[0], 'sub_' + entry)
                changed = body(whole[1], 'sub_' + entry)
                self.assertEqual(changed.replace(patch['new'], patch['old']), original)
                self.assertEqual(re.findall(r'RECOMP_(?:I?CALL|BACKEDGE)[^;]*;', original),
                                 re.findall(r'RECOMP_(?:I?CALL|BACKEDGE)[^;]*;', changed))
                self.assertIn('RECOMP_ICALL_P(', original)
                creator_code = body(whole[0], 'sub_' + creator)
                worker_code = body(whole[0], 'sub_' + worker)
                raw = source.read_text(encoding='utf-8')
                raw_creator = body(raw, 'sub_' + creator)
                strings = {}
                for address in re.findall(r'PUSH32\(esp, 0x([0-9A-F]{8})u\)', raw_creator):
                    if not base <= int(address, 16) < base + pe.OPTIONAL_HEADER.SizeOfImage:
                        continue
                    value = get(address, 64).split(b'\0', 1)[0]
                    if value.lower() == b'user32.dll' or value == b'SetLayeredWindowAttributes':
                        strings[value.lower()] = (int(address, 16), value.decode('ascii'))
                library_va, library = strings[b'user32.dll']
                proc_va, _ = strings[b'setlayeredwindowattributes']
                pe.close()
                out = OUT / edition
                out.mkdir(parents=True, exist_ok=True)
                names = '\n'.join([
                    '#define WORKER_VA 0x' + worker + 'u',
                    '#define CREATE_IAT ' + hex(imports['CreateThread']),
                    '#define SLEEP_IAT ' + hex(imports['Sleep']),
                    '#define LOAD_IAT ' + hex(imports['LoadLibraryA']),
                    '#define PROC_IAT ' + hex(imports['GetProcAddress']),
                    '#define LIBRARY_STRING ' + hex(library_va), '#define PROC_STRING ' + hex(proc_va),
                    '#define LIBRARY_NAME ' + json.dumps(library),
                    '#define sub_' + creator + ' CREATOR_CANONICAL', ''])
                # The canonical body itself is preserved; only fixture symbols are renamed.
                files = {'probe.c': HARNESS + FIXTURE, 'names.h': names,
                         'before.h': original.replace('void sub_' + entry, 'void launch_before', 1),
                         'after.h': changed.replace('void sub_' + entry, 'void launch_after', 1),
                         'creator.h': creator_code.replace('void sub_' + creator, 'void creator_unsupported', 1),
                         'worker.h': worker_code.replace('void sub_' + worker, 'void fade_worker', 1),
                         'recomp_types.h': pc_header((ROOT / 'android/runtime/recomp_types.h').read_text(encoding='utf-8'))}
                for name, text in files.items():
                    (out / name).write_text(text, encoding='utf-8')
                env, linker = environment('x64')
                args = [CLANG, '/nologo', '/W0', '/O2', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
                        '/DRECOMP_PROTOCOL_CHECK', '/clang:--target=x86_64-pc-windows-msvc',
                        '/clang:-fno-strict-aliasing', '/clang:-fwrapv', '/clang:-ffp-contract=off']
                command([*args, '/c', 'probe.c', '/Foprobe.obj'], out, env)
                command([linker, '/nologo', 'probe.obj', '/OUT:probe.exe', '/STACK:1048576'], out, env)
                result = command([out / 'probe.exe'], out, env)
                self.assertIn('PASS 16 startup', result.stdout)
                (out / 'receipt.json').write_text(json.dumps({'edition': edition, 'pgo_transform': True,
                    'protocol_transform': True, 'protocol_checks_executed': True, 'image_sha256': image_sha,
                    'whole_before_sha256': hashlib.sha256(whole[0].encode()).hexdigest(),
                    'whole_after_sha256': hashlib.sha256(whole[1].encode()).hexdigest(),
                    'only_change': patch, 'fixture_sha256': hashlib.sha256(files['probe.c'].encode()).hexdigest(),
                    'result': result.stdout, 'device_calls': 0}, indent=2) + '\n', encoding='utf-8')
                print(edition + ': ' + result.stdout.strip())

    def test_wrong_anchor_is_rejected_in_each_edition(self):
        for edition, fact in FACTS.items():
            original = (generated_root(edition) / 'game-x86' / fact[5]).read_bytes()
            wrong = proposal(edition)
            wrong['old'] = wrong['old'].replace('0x' + fact[3] + ':', '0x00000000:')
            contract = copy.deepcopy(port_patches.load_contract(edition))
            contract['generated_patches'] = [wrong]
            with self.subTest(edition=edition), mock.patch.object(port_patches, 'load_contract', return_value=contract):
                with self.assertRaisesRegex(ValueError, 'anchor changed'):
                    port_patches.adapt_generated_source(original, 'game', edition)

    def test_another_sleep_outside_the_helper_is_rejected(self):
        for edition, fact in FACTS.items():
            original = (generated_root(edition) / 'game-x86' / fact[5]).read_text(encoding='utf-8')
            matches = re.findall(r'    PUSH32\(esp, 0x28u\); /\* 0x[0-9A-F]{8}: push 0x28 \*/', original)
            self.assertTrue(matches, edition + ': expected actual WinMain idle sleep is missing')
            self.assertNotIn(matches[0], body(original, 'sub_' + fact[0]))
            wrong = proposal(edition)
            wrong['old'] = matches[0]
            wrong['new'] = matches[0].replace('0x28u', '0')
            contract = copy.deepcopy(port_patches.load_contract(edition))
            contract['generated_patches'] = [wrong]
            with self.subTest(edition=edition), mock.patch.object(port_patches, 'load_contract', return_value=contract):
                with self.assertRaisesRegex(ValueError, 'anchor changed'):
                    port_patches.adapt_generated_source(original.encode(), 'game', edition)

    def test_duplicate_exact_anchor_is_rejected(self):
        for edition, fact in FACTS.items():
            source = (generated_root(edition) / 'game-x86' / fact[5]).read_text(encoding='utf-8')
            patch = proposal(edition)
            source = source.replace(patch['old'], patch['old'] + '\n' + patch['old'], 1)
            contract = copy.deepcopy(port_patches.load_contract(edition))
            contract['generated_patches'] = [patch]
            with self.subTest(edition=edition), mock.patch.object(port_patches, 'load_contract', return_value=contract):
                with self.assertRaisesRegex(ValueError, 'anchor changed'):
                    port_patches.adapt_generated_source(source.encode(), 'game', edition)

    def test_missing_layered_api_is_not_a_created_missing_thunk(self):
        host = ROOT / 'android/host'
        for path in host.glob('*.c'):
            self.assertNotRegex(path.read_text(encoding='utf-8'), r'WINAPI_EXPORT\(\s*U32\s*,\s*SetLayeredWindowAttributes\b', path.name)
        pe = (host / 'pe.c').read_text(encoding='utf-8')
        current = pe[pe.index('uint32_t void_module_proc('):pe.index('\n}', pe.index('uint32_t void_module_proc('))]
        self.assertIn('address = thunk_for(m->name, name, 0, 0);', current)
        thunk = pe[pe.index('static uint32_t thunk_for('):pe.index('\n}', pe.index('static uint32_t thunk_for('))]
        self.assertRegex(thunk, re.compile(r'else if \(create_missing\).*?else \{\s*return 0;', re.S))

    def test_actual_sleep_zero_never_blocks_and_other_sleep_is_unchanged(self):
        source = (ROOT / 'android/host/threads.c').read_text(encoding='utf-8')
        start = source.index('static void sleep_ms(uint32_t ms)\n{')
        actual = source[start:source.index('\n}', start) + 2]
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <time.h>
#include <errno.h>
static int busy,yielded,scheduled,begun,ended,slept,interrupt_once;
static struct timespec requested;
static int machine_contended(void){return busy;}
static void yield_hook(void){++yielded;}
static int sched_yield(void){++scheduled;return 0;}
static void void_blocking_begin(void){++begun;}
static void void_blocking_end(void){++ended;}
static int nanosleep(const struct timespec*input,struct timespec*remaining){
 ++slept;requested=*input;if(interrupt_once){interrupt_once=0;remaining->tv_sec=0;remaining->tv_nsec=2000000;errno=EINTR;return -1;}return 0;
}
/* ACTUAL_SLEEP */
int main(void){
 sleep_ms(0);assert(scheduled==1&&!yielded&&!begun&&!ended&&!slept);
 busy=1;sleep_ms(0);assert(scheduled==1&&yielded==1&&!begun&&!ended&&!slept);
 sleep_ms(17);assert(begun==1&&ended==1&&slept==1&&requested.tv_sec==0&&requested.tv_nsec==17000000);
 interrupt_once=1;sleep_ms(1001);assert(begun==2&&ended==2&&slept==3&&requested.tv_sec==0&&requested.tv_nsec==2000000);
 return 0;
}
'''.replace('/* ACTUAL_SLEEP */', actual)
        out = OUT / 'actual-sleep'
        out.mkdir(parents=True, exist_ok=True)
        (out / 'probe.c').write_text(fixture, encoding='utf-8')
        env, linker = environment('x64')
        command([CLANG, '/nologo', '/W0', '/O2', '/std:c11', '/clang:--target=x86_64-pc-windows-msvc',
                 '/c', 'probe.c', '/Foprobe.obj'], out, env)
        command([linker, '/nologo', 'probe.obj', '/OUT:probe.exe'], out, env)
        command([out / 'probe.exe'], out, env)


if __name__ == '__main__':
    unittest.main()
