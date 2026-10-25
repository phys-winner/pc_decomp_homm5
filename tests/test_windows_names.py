"""Execute the actual private Win32 name cache against its pinned linear oracle."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import prepare_windows_runtime as prepare
import build_windows as builder

HARNESS = r'''
static unsigned failures;
#define CHECK(c) do { if (!(c)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#c); ++failures; } } while(0)
static void add(uint32_t va,const char *name) {
    baseline_add(va,"test",name);add_name(va,"test",name);
    CHECK(baseline_count==g_name_n);
    if(g_name_n) CHECK(!memcmp(baseline_names+g_name_n-1,g_names+g_name_n-1,sizeof g_names[0]));
}
static const char *lookup(uint32_t va) {
    const char *a=baseline_lookup(va),*b=native32_name(va);
    CHECK((a==NULL)==(b==NULL));
    if(a&&b) {
        CHECK(!strcmp(a,b));
        CHECK((uintptr_t)a-(uintptr_t)baseline_names==(uintptr_t)b-(uintptr_t)g_names);
    }
    return b;
}
static uint32_t bucket(uint32_t va){return(va*0x9E3779B1u)>>24;}
static uint32_t index_bucket(uint32_t va){return(va*0x9E3779B1u)>>19;}
static HANDLE ready,proceed;
static uintptr_t worker_cache;
static DWORD WINAPI worker(void *unused) {
    (void)unused;worker_cache=(uintptr_t)g_name_cache;
    CHECK(native32_name(0xE0000011u)==NULL);CHECK(native32_name(0xE0000011u)==NULL);
    SetEvent(ready);CHECK(WaitForSingleObject(proceed,5000)==WAIT_OBJECT_0);
    const char *name=native32_name(0xE0000011u);
    CHECK(name&&!strcmp(name,"test!late-thread"));return 0;
}
int main(void) {
    lookup(0);lookup(0xFFFFFFFFu);
    add(0,"zero");add(0xFFFFFFFFu,"full-32-bit");
    lookup(0);lookup(0xFFFFFFFFu);
    const char *stable=lookup(0xFFFFFFFFu);int count=g_name_n;
    add(0xFFFFFFFFu,"duplicate-must-not-rename");
    CHECK(g_name_n==count&&lookup(0xFFFFFFFFu)==stable);
    lookup(0x12345678u);unsigned before=cached_probes;
    lookup(0x12345678u);CHECK(cached_probes==before); /* NULL is a real hit. */
    add(0x12345678u,"late");CHECK(lookup(0x12345678u)!=NULL);
    before=cached_probes;lookup(0x12345678u);CHECK(cached_probes==before);
    uint32_t left=0x10000u,right=left+1;
    while(bucket(left)!=bucket(right))++right;
    CHECK(left!=right);add(left,"collision-left");add(right,"collision-right");
    lookup(left);lookup(right);lookup(left);lookup(right);
    uint32_t wrapped[3],candidate=0x01000000u;
    for(unsigned i=0;i<3;++i) {
        while(index_bucket(candidate)!=8191u)++candidate;
        wrapped[i]=candidate++;add(wrapped[i],"wrapped-index-cluster");
    }
    for(unsigned i=0;i<3;++i)lookup(wrapped[i]);
    add(0xABCDEF01u,"invalidate-positive");
    CHECK(lookup(0xFFFFFFFFu)==stable);
    SetLastError(0x99887766);lookup(0xABCDEF01u);CHECK(GetLastError()==0x99887766);
    SetLastError(0x11223344);lookup(0x013579BDu);CHECK(GetLastError()==0x11223344);
    ready=CreateEvent(NULL,FALSE,FALSE,NULL);proceed=CreateEvent(NULL,FALSE,FALSE,NULL);
    CHECK(ready&&proceed);lookup(0xE0000011u);
    HANDLE thread=CreateThread(NULL,0,worker,NULL,0,NULL);CHECK(thread!=NULL);
    CHECK(WaitForSingleObject(ready,5000)==WAIT_OBJECT_0);
    CHECK(worker_cache!=(uintptr_t)g_name_cache);
    add(0xE0000011u,"late-thread");CHECK(lookup(0xE0000011u)!=NULL);
    SetEvent(proceed);CHECK(WaitForSingleObject(thread,5000)==WAIT_OBJECT_0);
    CloseHandle(thread);CloseHandle(ready);CloseHandle(proceed);
    uint32_t random=1;
    for(unsigned i=0;i<16384;++i){random=random*1664525u+1013904223u;lookup(random);lookup(random);}
    uint32_t next=0x80000000u;
    while(g_name_n<MAX_NAMES)add(next++,"capacity");
    CHECK(g_name_n==MAX_NAMES);
    lookup(0x76543210u);before=cached_probes;lookup(0x76543210u);CHECK(cached_probes==before);
    add(0x76543210u,"must-not-add-full");CHECK(lookup(0x76543210u)==NULL);
    CHECK(lookup(0xFFFFFFFFu)==stable);
    before=cached_probes;unsigned linear_before=baseline_probes;
    for(unsigned i=0;i<16384;++i){random=random*1664525u+1013904223u;lookup(random);}
    CHECK(cached_probes-before<131072u);
    CHECK(baseline_probes-linear_before>60000000u);
    printf("name-cache checks: failures=%u baseline_probes=%u cached_probes=%u names=%d\n",failures,baseline_probes,cached_probes,g_name_n);
    return failures?1:0;
}
'''


def names_section(source):
    start = source.index('#define MAX_NAMES 4096')
    end = source.index('/* ------------------------------------------------------- guest -> Windows */', start)
    return source[start:end]


def make_source(mutant=None):
    vendor = (ROOT / 'reference/pcrecomp/runtime/native32/native32.c').read_bytes()
    assert prepare.digest(vendor) == prepare.VENDOR_SHA
    raw = vendor.decode().replace('\r\n', '\n')
    original = names_section(raw)
    actual = names_section(prepare.platform_runtime(raw))
    assert actual.count('static __declspec(thread) name_cache_slot g_name_cache[256]') == 1
    if mutant == 'generation':
        actual = actual.replace('slot->va == va && slot->count == count', 'slot->va == va')
    elif mutant == 'full-va':
        actual = actual.replace('slot->va == va && slot->count == count', 'slot->count == count')
    elif mutant == 'index-insert':
        actual = actual.replace('g_name_index[bucket] = (uint16_t)g_name_n;', '(void)bucket;')
    elif mutant == 'index-full-va':
        actual = actual.replace('g_names[entry - 1].va == va', '1')
    elif mutant == 'linear-fallback':
        start = actual.index('    unsigned bucket = (va * 0x9E3779B1u) >> 19, entry;')
        end = actual.index('    slot->va = va;', start)
        actual = actual[:start] + ('    for (int i = 0; i < count; i++)\n'
                 '        if (g_names[i].va == va) { name = g_names[i].name; break; }\n') + actual[end:]
    original = original.replace('if (g_names[i].va == va)', 'if ((++baseline_probes, g_names[i].va == va))')
    actual = actual.replace('while ((entry = g_name_index[bucket]) != 0)',
                            'while ((++cached_probes, (entry = g_name_index[bucket]) != 0))')
    actual = actual.replace('if (g_names[i].va == va)', 'if ((++cached_probes, g_names[i].va == va))')
    prefix = '#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <stdint.h>\n#include <stdio.h>\n#include <string.h>\nstatic unsigned baseline_probes,cached_probes;\n'
    aliases = dict(native32_name='baseline_lookup',add_name='baseline_add',g_names='baseline_names',g_name_n='baseline_count')
    return prefix + ''.join('#define '+key+' '+value+'\n' for key,value in aliases.items()) + original + ''.join('#undef '+key+'\n' for key in aliases) + actual + HARNESS


def run_probe(mutant=None, thinlto=False):
    out = ROOT / 'build/tests' / ('windows_names_' + (mutant or 'actual') + ('_thinlto' if thinlto else ''))
    out.mkdir(parents=True, exist_ok=True)
    source = out / 'probe.c';source.write_text(make_source(mutant), encoding='utf-8')
    compiler,linker,env = builder.compiler_environment()
    command = [str(compiler), '/nologo', '/O2', '/W3', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS',
               '/clang:--target=i686-pc-windows-msvc', '/c', str(source), '/Fo'+str(out/'probe.obj')]
    if thinlto: command.append('/clang:-flto=thin')
    compiled = subprocess.run(command, cwd=out, env=env, capture_output=True, text=True, timeout=30)
    (out/'compile.log').write_text(compiled.stdout+compiled.stderr, encoding='utf-8')
    assert compiled.returncode == 0, compiled.stdout+compiled.stderr
    link_program = [str(compiler.with_name('ld.lld.exe')), '-flavor', 'link'] if thinlto else [str(linker)]
    link_command = link_program + ['/nologo', str(out/'probe.obj'), '/OUT:'+str(out/'probe.exe'), '/MACHINE:X86']
    linked = subprocess.run(link_command, cwd=out, env=env, capture_output=True, text=True, timeout=30)
    assert linked.returncode == 0, linked.stdout+linked.stderr
    result = subprocess.run([str(out/'probe.exe')], cwd=out, capture_output=True, text=True, timeout=20)
    (out/'result.txt').write_text(result.stdout+result.stderr,encoding='utf-8')
    (out/'receipt.json').write_text(json.dumps(dict(command=command,link_command=link_command,source_sha256=builder.sha(source),
        executable_sha256=builder.sha(out/'probe.exe'),adapter_sha256=builder.sha(ROOT/'tools/prepare_windows_runtime.py'),
        vendor_sha256=prepare.VENDOR_SHA,mutant=mutant,thinlto=thinlto,exit_code=result.returncode,output=result.stdout+result.stderr),indent=2)+'\n')
    return result


class WindowsNamesTest(unittest.TestCase):
    def test_actual_names_against_linear_oracle_threads_and_warm_misses(self):
        result = run_probe();self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_actual_names_with_thinlto(self):
        result = run_probe(thinlto=True);self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_missing_generation_is_rejected_at_runtime(self):
        result = run_probe('generation');self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('FAIL',result.stderr)

    def test_missing_full_address_is_rejected_at_runtime(self):
        result = run_probe('full-va');self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('FAIL',result.stderr)

    def test_missing_index_insertion_is_rejected_at_runtime(self):
        result = run_probe('index-insert');self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('FAIL',result.stderr)

    def test_index_missing_full_address_is_rejected_at_runtime(self):
        result = run_probe('index-full-va');self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('FAIL',result.stderr)

    def test_linear_fallback_exceeds_the_cold_miss_work_bound(self):
        result = run_probe('linear-fallback');self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn('cached_probes-before<131072u',result.stderr)


if __name__ == '__main__':unittest.main()
