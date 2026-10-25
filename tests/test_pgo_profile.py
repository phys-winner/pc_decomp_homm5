"""Execute the actual profile writer and link its weak APIs with the Android runtime."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import unittest

import test_builder_thinlto as builder_tests
from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import TOOLCHAIN


HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned enters,leaves,sets,writes,logs,depth;
static int mock_write_result;
static char data[2048]="/sdcard/HeroesV/userdata", selected[2048],message[4096],events[32];
static unsigned event_count;
static const char *selected_pointer;
static void event(char e) {assert(event_count+1<sizeof events);events[event_count++]=e;events[event_count]=0;}
static const char *void_data_dir(void) {return data;}
static void void_machine_enter(void) {assert(!depth++);++enters;event('E');}
static void void_machine_leave(void) {assert(depth--==1);++leaves;event('X');}
static void void_log(const char *format,...) {
    va_list ap;va_start(ap,format);vsnprintf(message,sizeof message,format,ap);va_end(ap);++logs;event('L');
}
static void set_filename(const char *name) {
    assert(depth==1);assert(strlen(name)<sizeof selected);strcpy(selected,name);selected_pointer=name;++sets;event('S');
}
static int write_file(void) {assert(depth==1&&sets);++writes;event('W');return mock_write_result;}
static void (*__llvm_profile_set_filename)(const char *);
static int (*__llvm_profile_write_file)(void);
/* ACTUAL_WRITER */
static void reset(void) {
    assert(!depth);enters=leaves=sets=writes=logs=event_count=0;events[0]=message[0]=selected[0]=0;selected_pointer=NULL;mock_write_result=0;
}
static void clobber_stack(void) {volatile unsigned char scratch[4096];for(unsigned i=0;i<sizeof scratch;++i)scratch[i]=(unsigned char)i;}
int main(void) {
    reset();write_profile();assert(!enters&&!leaves&&!sets&&!writes&&!logs);
    __llvm_profile_write_file=write_file;write_profile();assert(!enters&&!writes&&!logs);
    __llvm_profile_write_file=NULL;__llvm_profile_set_filename=set_filename;write_profile();assert(!enters&&!sets&&!logs);
    __llvm_profile_write_file=write_file;
    write_profile();assert(enters==1&&leaves==1&&sets==1&&writes==1&&logs==1&&!depth);
    assert(!strcmp(events,"ESWLX"));assert(!strcmp(selected,"/sdcard/HeroesV/userdata/homm5-%p.profraw"));
    assert(strstr(message,"profile written (0)")&&strstr(message,selected));
    clobber_stack();assert(!strcmp(selected_pointer,selected));
    reset();mock_write_result=-7;write_profile();assert(enters==1&&leaves==1&&writes==1&&!depth);
    assert(!strcmp(events,"ESWLX"));assert(strstr(message,"profile write failed (-7)")&&strstr(message,selected));
    reset();memset(data,'x',sizeof data-1);data[sizeof data-1]=0;write_profile();
    assert(enters==1&&leaves==1&&!sets&&!writes&&logs==1&&!depth);assert(!strcmp(events,"EXL"));
    assert(strstr(message,"profile path too long"));
    reset();strcpy(data,"/data/local/tmp/h5");write_profile();
    assert(!strcmp(selected,"/data/local/tmp/h5/homm5-%p.profraw"));assert(enters==1&&leaves==1&&writes==1);
    puts("PASS actual PGO writer: weak-null no-op, writable filename, serialized snapshot, persistent path, failed write, bounded path and recovery");
    return 0;
}
'''


class ProfileWriterTest(unittest.TestCase):
    def test_android_frontend_profile_attachment_and_strict_mismatch(self):
        ndk=(TOOLCHAIN / 'bin')
        with builder_tests.ThinLTOBuilderTest().fixture() as (root,records,invoke):
            source=root/'generated/fmod-x86/fmod_0000.c'
            source.write_text('int pgo_probe(int x) { if (x > 0) return x + 3; return x - 7; }\n')

            def flags():
                command=next(c for c in reversed(records['compiles']) if c[c.index('-c')+1]==str(source))
                return command[1:command.index('-c')]

            def compile_ir(options,name):
                output=root/name
                result=subprocess.run([str(ndk/'clang.exe'),*options,'-S','-emit-llvm',str(source),'-o',str(output)],
                                      cwd=root,capture_output=True,text=True)
                return result,output

            invoke(['--shared','--thinlto','--pgo-generate'])
            result,instrumented=compile_ir(flags(),'instrumented.ll')
            self.assertEqual(result.returncode,0,result.stderr)
            ir=instrumented.read_text()
            profile_hash=re.search(r'@__profd_pgo_probe =.*?\{ i64 -?\d+, i64 (-?\d+),',ir)
            counters=re.search(r'@__profc_pgo_probe =.*?\[(\d+) x i64\]',ir)
            self.assertIsNotNone(profile_hash)
            self.assertIsNotNone(counters)
            self.assertEqual(int(counters[1]),2)
            # Synthetic counts use the actual frontend hash; no device execution is needed.
            text_profile=root/'profile.txt'
            text_profile.write_text(f'pgo_probe\n{profile_hash[1]}\n2\n1000\n900\n')
            profile=root/'profile.profdata'
            result=subprocess.run([str(ndk/'llvm-profdata.exe'),'merge',str(text_profile),'-o',str(profile)],
                                  cwd=root,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)

            invoke(['--shared','--thinlto','--pgo-use',str(profile)])
            use_flags=flags()
            result,output=compile_ir(use_flags,'correct.ll')
            self.assertEqual(result.returncode,0,result.stderr)
            ir=output.read_text()
            self.assertIn('!"function_entry_count", i64 1000',ir)
            self.assertIn('!"branch_weights", i32 901, i32 101',ir)

            source.write_text('int pgo_probe(int x) { if (x == 42) return 19; if (x > 0) return x + 3; return x - 7; }\n')
            result,_=compile_ir(use_flags,'changed.ll')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('profile-instr-out-of-date',result.stderr)
            result,_=compile_ir([*use_flags,'-w'],'muted.ll')
            self.assertEqual(result.returncode,0,result.stderr)

            source.write_text('int unknown_probe(int x) { if (x > 0) return x + 3; return x - 7; }\n')
            result,_=compile_ir(use_flags,'missing.ll')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('profile-instr-unprofiled',result.stderr)

    def test_actual_writer_lifetime_and_failures(self):
        source=(ROOT/'android/host/script.c').read_text(encoding='utf-8')
        writer=function(source,'static void write_profile(')
        compile_probe('pgo_profile_writer',HARNESS.replace('/* ACTUAL_WRITER */',writer),{})

    def test_android_profile_runtime_and_normal_weak_link(self):
        source=(ROOT/'android/host/script.c').read_text(encoding='utf-8')
        declarations='\n'.join(re.findall(r'^extern (?:int|void) __llvm_profile_.*?;$',source,re.M))
        self.assertEqual(declarations.count('__attribute__((weak))'),2)
        writer=function(source,'static void write_profile(')
        out=ROOT/'build/tests/pgo_link';out.mkdir(parents=True,exist_ok=True)
        ndk=(TOOLCHAIN / 'bin')
        clang=ndk/'clang.exe'
        counter='int training_branch(int n){int total=0;while(n-->0)total+=n&1;return total;}\n'
        harness='''#include <stdio.h>
#include <stdarg.h>
static void void_machine_enter(void){}
static void void_machine_leave(void){}
static const char *void_data_dir(void){return "/sdcard/HeroesV/userdata";}
static void void_log(const char *format,...){(void)format;}
'''+declarations+'\n'+writer+'''
extern int training_branch(int);
__attribute__((visibility("default"))) int pgo_probe(int n){int value=training_branch(n);write_profile();return value;}
'''
        (out/'writer.c').write_text(harness,encoding='utf-8');(out/'counter.c').write_text(counter,encoding='utf-8')
        common=['--target=aarch64-linux-android30','-O2','-fPIC','-fvisibility=hidden','-ffp-contract=off','-fno-strict-aliasing','-fwrapv']
        commands=[]
        def run(args):
            commands.append([str(a) for a in args])
            result=subprocess.run([str(a) for a in args],cwd=out,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            return result.stdout
        run([clang,*common,'-c','writer.c','-o','writer.o'])
        for mode in ('normal','instrumented'):
            flags=['-fprofile-instr-generate'] if mode=='instrumented' else []
            run([clang,*common,*flags,'-c','counter.c','-o',mode+'.o'])
            library=mode+'.so'
            run([clang,'--target=aarch64-linux-android30','-shared','-Wl,--no-undefined','-Wl,--gc-sections',
                 '-Wl,-z,nostart-stop-gc','-Wl,-z,max-page-size=16384','-Wl,--build-id=sha1',*flags,'writer.o',mode+'.o','-o',library])
            names=run([ndk/'llvm-nm.exe','--defined-only',library])
            sections=run([ndk/'llvm-readelf.exe','--sections',library])
            if mode=='instrumented':
                self.assertIn('__llvm_profile_set_filename',names)
                self.assertIn('__llvm_profile_write_file',names)
                self.assertIn('__llvm_prf_cnts',sections)
            else:
                self.assertNotIn('__llvm_profile_write_file',names)
                self.assertNotIn('__llvm_prf_cnts',sections)
        receipt={'scope':'isolated actual writer + one native counter; no APK/device',
                 'script_sha256':hashlib.sha256(source.encode()).hexdigest(),'commands':commands,
                 'normal':'weak unresolved APIs accepted, no counters/runtime',
                 'instrumented':'Android profile runtime linked, filename/write APIs and counter section retained'}
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')


if __name__=='__main__':
    unittest.main()
