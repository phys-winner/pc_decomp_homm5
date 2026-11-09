"""Real shared mode initialization: concurrent first use and strict parsing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

from test_mmx_packed import CLANG, command, environment

ROOT = Path(__file__).resolve().parents[1]
HEADER = ROOT / "android/host/native_mode.h"
OUT = ROOT / "build/tests/native-mode"

FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <stdarg.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
typedef HANDLE thread_t;
#define THREAD_RET DWORD WINAPI
#define THREAD_DONE return 0
#define YIELD() SwitchToThread()
static thread_t spawn(LPTHREAD_START_ROUTINE fn,void *arg){HANDLE h=CreateThread(NULL,0,fn,arg,0,NULL);assert(h);return h;}
static void join(thread_t h){assert(WaitForSingleObject(h,INFINITE)==WAIT_OBJECT_0);CloseHandle(h);}
#else
#include <pthread.h>
#include <sched.h>
typedef pthread_t thread_t;
#define THREAD_RET void *
#define THREAD_DONE return NULL
#define YIELD() sched_yield()
static thread_t spawn(void *(*fn)(void *),void *arg){pthread_t h;assert(!pthread_create(&h,NULL,fn,arg));return h;}
static void join(thread_t h){assert(!pthread_join(h,NULL));}
#endif
#define LOAD(p) __c11_atomic_load((p),__ATOMIC_ACQUIRE)
#define STORE(p,v) __c11_atomic_store((p),(v),__ATOMIC_RELEASE)
#define ADD(p,v) __c11_atomic_fetch_add((p),(v),__ATOMIC_ACQ_REL)
static _Atomic(int) hold_read,read_started,release_read,entered,completed,opens,reads,logs;
static const char *directory=".";
static const char *void_data_dir(void){return directory;}
static void void_log(const char *format,...){assert(!strcmp(format,"[mode-test] mode=%d"));ADD(&logs,1);}
static FILE *counted_open(const char *path,const char *mode){ADD(&opens,1);return fopen(path,mode);}
static size_t held_read(void *data,size_t size,size_t count,FILE *file){
 ADD(&reads,1);
 if(LOAD(&hold_read)){STORE(&read_started,1);while(!LOAD(&release_read))YIELD();}
 return fread(data,size,count,file);
}
#define fopen counted_open
#define fread held_read
#include "native_mode.h"
#undef fopen
#undef fread
static void_native_mode_cache shared=VOID_NATIVE_MODE_CACHE_INIT;
static int choices[8];
static THREAD_RET worker(void *arg){unsigned i=(unsigned)(uintptr_t)arg;ADD(&entered,1);
 choices[i]=void_native_mode_get(&shared,"mode-qa-file","[mode-test] mode=%d");ADD(&completed,1);THREAD_DONE;}
static void write_value(const char *name,const char *value,size_t size){FILE *f=fopen(name,"wb");assert(f);assert(fwrite(value,1,size,f)==size);assert(!fclose(f));}
int main(void){
 write_value("mode-qa-file","1",1);STORE(&hold_read,1);
 thread_t threads[8];threads[0]=spawn(worker,(void *)(uintptr_t)0);
 while(!LOAD(&read_started))YIELD();
 for(unsigned i=1;i<8;i++)threads[i]=spawn(worker,(void *)(uintptr_t)i);
 while(LOAD(&entered)<8)YIELD();
 for(unsigned i=0;i<10000;i++)YIELD();
 if(LOAD(&completed)){fputs("EARLY PUBLICATION\n",stderr);return 42;}
 if(LOAD(&opens)!=1||LOAD(&reads)!=1||LOAD(&logs)!=0){fputs("MULTIPLE INITIALIZERS\n",stderr);return 43;}
 STORE(&release_read,1);for(unsigned i=0;i<8;i++)join(threads[i]);STORE(&hold_read,0);
 assert(LOAD(&completed)==8&&LOAD(&opens)==1&&LOAD(&reads)==1&&LOAD(&logs)==1);
 for(unsigned i=0;i<8;i++)assert(choices[i]==1);
 write_value("mode-qa-file","0",1);
 for(unsigned i=0;i<100000;i++)assert(void_native_mode_get(&shared,"mode-qa-file","[mode-test] mode=%d")==1);
 assert(LOAD(&opens)==1&&LOAD(&reads)==1&&LOAD(&logs)==1);
 const struct {const char *value;size_t size;int expected;} cases[]={
  {"1",1,1},{"1\n",2,1},{"",0,0},{"0",1,0},{"2",1,0},{"01",2,0},{"1\r\n",3,0},
  {"1\nextra",7,0},{"1\n\n",3,0},{"1\0",2,0},{" 1",2,0},{"1 ",2,0}};
 for(unsigned i=0;i<sizeof cases/sizeof cases[0];i++){
  write_value("mode-qa-file",cases[i].value,cases[i].size);
  void_native_mode_cache cache=VOID_NATIVE_MODE_CACHE_INIT;int before=LOAD(&logs);
  int actual=void_native_mode_get(&cache,"mode-qa-file","[mode-test] mode=%d");
  if(actual!=cases[i].expected){fputs("STRICT PARSE FAILED\n",stderr);return 44;}
  assert(LOAD(&logs)==before+1);
 }
 assert(!remove("mode-qa-file"));
 void_native_mode_cache missing=VOID_NATIVE_MODE_CACHE_INIT;
 assert(!void_native_mode_get(&missing,"mode-qa-file","[mode-test] mode=%d"));
 int before=LOAD(&opens);directory=NULL;void_native_mode_cache null_dir=VOID_NATIVE_MODE_CACHE_INIT;
 assert(!void_native_mode_get(&null_dir,"mode-qa-file","[mode-test] mode=%d")&&LOAD(&opens)==before);
 char long_dir[1100];memset(long_dir,'x',sizeof long_dir-1);long_dir[sizeof long_dir-1]=0;directory=long_dir;
 void_native_mode_cache overflow=VOID_NATIVE_MODE_CACHE_INIT;
 assert(!void_native_mode_get(&overflow,"mode-qa-file","[mode-test] mode=%d")&&LOAD(&opens)==before);
 directory=".";write_value("mode-qa-a","1\n",2);write_value("mode-qa-b","0",1);
 void_native_mode_cache group_a=VOID_NATIVE_MODE_CACHE_INIT,group_b=VOID_NATIVE_MODE_CACHE_INIT;
 assert(void_native_mode_get(&group_a,"mode-qa-a","[mode-test] mode=%d")==1);
 assert(void_native_mode_get(&group_b,"mode-qa-b","[mode-test] mode=%d")==0);
 assert(!remove("mode-qa-a")&&!remove("mode-qa-b"));
 puts("PASS native mode:8held-reader threads,one initializer/logger,no temporary fallback,100000cached calls,12strict parser cases,independent groups");
 return 0;
}
'''


def host_probe(label, header):
    out = OUT / label
    out.mkdir(parents=True, exist_ok=True)
    (out / "native_mode.h").write_text(header, encoding="utf-8")
    (out / "probe.c").write_text(FIXTURE, encoding="utf-8")
    env, linker = environment("x64")
    command([CLANG, "/nologo", "/W3", "/WX", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
             "/clang:--target=x86_64-pc-windows-msvc", "/c", "probe.c", "/Foprobe.obj"], out, env)
    command([linker, "/nologo", "probe.obj", "/OUT:probe.exe"], out, env)
    result = command([out / "probe.exe"], out, env, check=False)
    (out / "result.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    return result


class NativeModeTest(unittest.TestCase):
    def test_held_initializer_and_strict_cached_choices(self):
        result = host_probe("positive", HEADER.read_text())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS native mode:8held-reader", result.stdout)

    def test_reject_transient_fallback_publication(self):
        original = HEADER.read_text()
        self.assertEqual(original.count("        mode = 0;"), 1)
        mutant = original.replace("        mode = 0;", "        mode = 0; __c11_atomic_store(cache, 0, __ATOMIC_RELEASE);", 1)
        result = host_probe("temporary-zero-mutant", mutant)
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        self.assertIn("EARLY PUBLICATION", result.stderr)

    def test_all_current_groups_use_real_shared_initializer(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from native_routes import NATIVE_SOURCES
        for name in NATIVE_SOURCES:
            text = (ROOT / "android/host" / name).read_text()
            self.assertIn('#include "native_mode.h"', text, name)
            self.assertEqual(text.count("void_native_mode_get("), 1, name)
            self.assertEqual(text.count("VOID_NATIVE_MODE_CACHE_INIT"), 1, name)
            self.assertNotRegex(text, r"static int (?:mode|reference_mode)\s*=\s*-1")


def build_arm():
    out = ROOT / "build/native-world-combat-2026-11-09/native-mode-arm"
    out.mkdir(parents=True, exist_ok=False)
    (out / "probe.c").write_text(FIXTURE, encoding="utf-8")
    (out / "native_mode.h").write_bytes(HEADER.read_bytes())
    ndk = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64"
    binary = out / "native-mode-once"
    args = [str(ndk / "bin/clang.exe"), "--target=aarch64-linux-android26", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
            "-Wl,-z,max-page-size=16384", "probe.c", "-o", str(binary)]
    result = subprocess.run(args, cwd=out, capture_output=True, text=True, timeout=60)
    (out / "compile.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = dict(probes=[dict(label="native-mode-once", executable=str(binary), executable_sha256=sha(binary),
        helper_sha256=sha(HEADER), fixture_sha256=sha(out / "probe.c"), command=args, invocations=[[]], expected_exit=0,
        expected_outputs=["PASS native mode:8held-reader"], timeout_seconds_per_invocation=30,
        cwd_requirement="Fresh root-owned QA temp directory; writes/removes only mode-qa-file,mode-qa-a,mode-qa-b.",
        physical_device_executed=False)], device_calls_by_preparer=0)
    (out / "manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print("ARM fixture:", binary, sha(binary))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-arm64", action="store_true")
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(NativeModeTest))
    if not result.wasSuccessful():
        raise SystemExit(1)
    if args.build_arm64:
        build_arm()
