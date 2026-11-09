"""Exact entry inventory/transform tests and a real multithreaded atomic fixture.

No Android device access. --build-arm64 additionally compiles the same fixture
and the complete monitor runtime for the device owner to run separately.
"""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import function_coverage as fc


def lifted(va):
    return f"void sub_{va}(void) {{\n RECOMP_ENTER(0x{va}u);\n sub_{va}();\n}}\n"


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.generated = self.root / "generated"
        (self.generated / "game").mkdir(parents=True)
        (self.generated / "granny2").mkdir()
        self.source = self.generated / "game/functions_0000.c"
        self.source.write_text('#include "functions.h"\n' + lifted("00400000") + lifted("00400010"))
        self.physics = self.generated / "granny2/functions_0000.c"
        self.physics.write_text('#include "functions.h"\n' + lifted("1E000000"))
        self.host = self.root / "host.c"
        self.host.write_text("void sub_00400000(void) { mode(); }\n"
            "#define ENTRY(name) \\\n"
            " void name(void) { mode(); }\n"
            "ENTRY(sub_00400010)\n")
        self.plan = fc.CoveragePlan.create(self.generated, [self.source, self.physics], [self.host],
            ["sub_00400000", "sub_00400010"], self.root / "coverage",
            [{"name": "game", "file": "H5_Game.exe"}, {"name": "granny2", "file": "granny2.dll"}])

    def bitmap(self, cumulative, window):
        count = len(self.plan.manifest["entries"])
        data = fc.HEADER.pack(fc.MAGIC, 1, count, 1, 0, 1, 2, 3, 100, 101, 120000, 60000,
                              self.plan.manifest["identity_sha256"].encode())
        path = self.root / "capture.bin"
        path.write_bytes(data + struct.pack("<QQ", cumulative, window))
        return path

    def test_all_entries_direct_calls_and_separate_implementations(self):
        self.assertEqual(len(self.plan.manifest["entries"]), 5)
        text, count = self.plan.instrument_generated(self.source.read_text(), "game")
        self.assertEqual(count, 2)
        self.assertEqual(text.count("VOID_FUNCTION_COVERAGE_HIT("), 2)
        self.assertIn('#include "functions.h"', text)
        self.assertIn("sub_00400000();", text)  # Same-unit direct call still enters its instrumented body.
        text, count = self.plan.instrument_host(self.host.read_text())
        self.assertEqual(count, 2)
        self.assertIn("VOID_FUNCTION_COVERAGE_HIT(VOID_FC_NATIVE_##name);", text)
        self.assertLess(text.index("VOID_FUNCTION_COVERAGE_HIT("), text.index("mode();"))

    def test_generator_drift_fails_closed(self):
        for text in (lifted("00400000").replace("RECOMP_ENTER", "OTHER_ENTER"),
                     lifted("00400000").replace("0x00400000u", "0x00400010u"),
                     lifted("00400000") + "RECOMP_ENTER(0x00400000u);"):
            with self.assertRaises(ValueError):
                fc.generated_entries(text)

    def test_renamed_original_keeps_its_lifted_id(self):
        original = self.source.read_text().replace("void sub_00400000(void)", "void sub_00400000_lifted(void)")
        transformed, count = self.plan.instrument_generated(original, "game-x86")
        self.assertEqual(count, 2)
        self.assertIn("sub_00400000_lifted(void)", transformed)
        self.assertEqual(transformed.count("VOID_FUNCTION_COVERAGE_HIT("), 2)

    def test_actual_fmod_macro_inventory(self):
        text = (ROOT / "android/host/fmod_stream.c").read_text()
        self.assertEqual(len(fc.native_entries(text)), 16)
        self.assertEqual(sum(len(calls) for _, _, calls in fc.native_macros(text)), 14)

    def test_manual_algorithm_id_is_not_router_entry(self):
        self.host.write_text("static void router(void) { original(); }\n"
                             "void algorithm(void) { work(); }\n"
                             "void_dispatch_add(0x00400000u, router);\n")
        plan = fc.CoveragePlan.create(self.generated, [self.source], [self.host], [], self.root / "manual",
            [{"name":"game","file":"H5_Game.exe"}], manual_entries=[dict(module="game",address="00400000",
                symbol="algorithm",source="host.c",manual_algorithmic_port=True)])
        router = next(r for r in plan.manifest["entries"] if r["symbol"] == "router")
        algorithm = next(r for r in plan.manifest["entries"] if r["symbol"] == "algorithm")
        self.assertFalse(router["manual_algorithmic_port"])
        self.assertTrue(algorithm["manual_algorithmic_port"])
        self.assertNotEqual(router["id"], algorithm["id"])
        text, _ = plan.instrument_host(self.host.read_text())
        self.assertIn(f'void algorithm(void) {{ VOID_FUNCTION_COVERAGE_HIT({algorithm["id"]}u);',text)

    def test_real_algorithm_sources_mark_selected_bodies_and_leave_selectors_unmarked(self):
        import native_routes as routes
        from port_patches import adapt_host_source
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                records = routes.algorithm_entries(edition)
                self.assertEqual(len(records), {"toe": 274, "vanilla": 18, "hof": 19}[edition])
                self.assertEqual(len({r["address"] for r in records}), len(records) - (edition == "toe"))
                source = self.generated / "game" / (edition + "_catalog.c")
                source.write_text("".join(lifted(address) for address in dict.fromkeys(r["address"] for r in records)))
                hosts = [adapt_host_source(ROOT / "android/host" / name, self.root / (edition + "_adapted"), edition)[0]
                         for name in sorted(routes.NATIVE_SOURCES)]
                plan = fc.CoveragePlan.create(self.generated, [source], hosts, [], self.root / (edition + "_catalog"),
                    [{"name": "game", "file": "H5_Game.exe"}], edition=edition, manual_entries=records)
                total = 0
                for host in hosts:
                    original = host.read_text()
                    rewritten, count = plan.instrument_host(original, host.name)
                    expected = {r["symbol"] for r in records if r["source"] == host.name}
                    self.assertEqual(count, len(expected))
                    total += count
                    for match in fc.HOST_DEFINITION.finditer(rewritten):
                        inserted = re.match(r"\s*VOID_FUNCTION_COVERAGE_HIT\(", rewritten[match.end():]) is not None
                        self.assertEqual(inserted, match[1] in expected, (edition, host.name, match[1]))
                self.assertEqual(total, len(records))
                manual = [r for r in plan.manifest["entries"] if r["kind"] == "manual_native"]
                contextual = {"grid_field", "vector_field", "reference_tile_cast", "reference_tile_assign", "reference_release", "reference_virtual_base"}
                if edition == "hof":
                    contextual.add("reference_hof_base")
                self.assertEqual({r["symbol"] for r in manual if not r["global_route"]}, contextual)

    def test_same_guest_va_keeps_distinct_actual_implementations_and_one_union_function(self):
        self.host.write_text("void global_algorithm(void) { work(); }\nstatic void contextual_algorithm(void) { work(); }\n")
        records = [dict(module="game", address="00400000", source="host.c", manual_algorithmic_port=True,
                        symbol=symbol, global_route=global_route)
                   for symbol, global_route in (("global_algorithm", True), ("contextual_algorithm", False))]
        plan = fc.CoveragePlan.create(self.generated, [self.source], [self.host], [], self.root / "same_va",
            [{"name":"game","file":"H5_Game.exe"}], manual_entries=records)
        native = [r for r in plan.manifest["entries"] if r["kind"] == "manual_native"]
        self.assertEqual(len(native), 2)
        self.assertNotEqual(native[0]["id"], native[1]["id"])
        text, count = plan.instrument_host(self.host.read_text())
        self.assertEqual(count, 2)
        bits = sum(1 << r["id"] for r in native)
        path = self.root / "same_va.bin"
        path.write_bytes(fc.HEADER.pack(fc.MAGIC, 1, len(plan.manifest["entries"]), 1, 0, 1, 2, 3, 100, 101, 0, 0,
                         plan.manifest["identity_sha256"].encode()) + struct.pack("<QQ", bits, bits))
        window = fc.decode(plan.manifest_path, path)["banks"]["window"]
        self.assertEqual(window["entered_implementation_count"], 2)
        self.assertEqual(window["unique_guest_function_count"], 1)
        self.assertEqual(window["observed_manual_algorithm_count"], 1)

    def test_diagnostic_script_controls_leave_original_unchanged(self):
        source = (ROOT / "android/host/script.c").read_text()
        transformed, _ = self.plan.instrument_host(source, "script.c")
        self.assertIn('"fcstart"',transformed)
        self.assertIn('"fcstop"',transformed)
        self.assertNotIn('"fcstart"',source)
        self.assertIn("void_function_coverage_finish()",transformed)

    def test_missing_wrapper_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Uninstrumented wrappers"):
            fc.CoveragePlan.create(self.generated, [self.source, self.physics], [], ["sub_00400000"],
                                  self.root / "bad", [{"name": "game", "file": "H5_Game.exe"}, {"name": "granny2", "file": "granny2.dll"}])

    def test_explicit_dispatch_overrides_and_unknown_addresses(self):
        text = "#define ADDR 0x00400000u\nenum { ENUM_ADDR=0x00400010u };\n"
        text += "static void first(void) { mode(); }\nstatic void second(void) { mode(); }\n"
        text += "void_dispatch_add(ADDR,first); void_dispatch_add(ENUM_ADDR,second);\n"
        text += "void_dispatch_add(ADDR, saved[0]); void_dispatch_add(old[i].va,old[i].fn);\n"
        self.assertEqual(fc.override_entries(text), [("first", "00400000"), ("second", "00400010")])
        self.host.write_text(text)
        plan = fc.CoveragePlan.create(self.generated, [self.source], [self.host], [], self.root / "overrides",
                                     [{"name": "game", "file": "H5_Game.exe"}])
        transformed, count = plan.instrument_host(text)
        self.assertEqual(count, 2)
        self.assertEqual(transformed.count("VOID_FUNCTION_COVERAGE_HIT("), 2)
        for invalid in (text.replace("ADDR,first", "UNKNOWN,first"), text + "void_dispatch_add(0x00400010u,first);",
                        text + "void_dispatch_add(0x00400000u,unknown);"):
            with self.assertRaises(ValueError):
                fc.override_entries(invalid)

    def test_decode_union_and_separate_banks(self):
        result = fc.decode(self.plan.manifest_path, self.bitmap(31, 15))
        self.assertEqual(result["banks"]["cumulative"]["unique_guest_function_count"], 3)
        self.assertEqual(result["banks"]["window"]["unique_guest_function_count"], 2)
        self.assertEqual(result["banks"]["window"]["entered_implementation_count"], 4)
        self.assertEqual(result["actual_window_seconds_bounds"], [97e-9, 99e-9])

    def test_decode_rejects_wrong_build_padding_and_partial_write(self):
        path = self.bitmap(31, 30)
        data = path.read_bytes()
        for invalid in (data[:-1], data + b"x", data[:80] + b"x" + data[81:],
                        data[:-16] + struct.pack("<QQ", 63, 0),
                        data[:-16] + struct.pack("<QQ", 1, 2)):
            path.write_bytes(invalid)
            with self.assertRaises(ValueError):
                fc.decode(self.plan.manifest_path, path)


NATIVE = r'''
#include "function_coverage_runtime.h"
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>
extern int void_function_coverage_parse_request(const char *,size_t,uint64_t *,uint64_t *);
#ifdef _WIN32
#include <windows.h>
typedef HANDLE thread_t;
#define THREAD_RET DWORD WINAPI
#define THREAD_DONE return 0
#define YIELD() SwitchToThread()
static thread_t spawn(LPTHREAD_START_ROUTINE fn, void *arg) { HANDLE h=CreateThread(NULL,0,fn,arg,0,NULL); assert(h); return h; }
static void join(thread_t t) { assert(WaitForSingleObject(t,INFINITE)==WAIT_OBJECT_0); CloseHandle(t); }
#else
#include <pthread.h>
#include <sched.h>
typedef pthread_t thread_t;
#define THREAD_RET void *
#define THREAD_DONE return NULL
#define YIELD() sched_yield()
static thread_t spawn(void *(*fn)(void *), void *arg) { pthread_t t; assert(!pthread_create(&t,NULL,fn,arg)); return t; }
static void join(thread_t t) { assert(!pthread_join(t,NULL)); }
#endif
static _Atomic unsigned phase, done, admitted, release_writer, stopped;
void void_fc_test_admitted(uint32_t word, uint64_t mask) {
    if(word==64 && mask==1) {
        atomic_store(&admitted,1);
        while(!atomic_load(&release_writer)) YIELD();
    }
}
static THREAD_RET worker(void *argument) {
    unsigned base=(unsigned)(uintptr_t)argument*256;
    while(atomic_load(&phase)<1) YIELD();
    for(unsigned i=0;i<128;++i) VOID_FUNCTION_COVERAGE_HIT(base+i);
    for(unsigned i=0;i<10000;++i) VOID_FUNCTION_COVERAGE_HIT(4095);
    atomic_fetch_add(&done,1);
    while(atomic_load(&phase)<2) YIELD();
    for(unsigned i=64;i<192;++i) VOID_FUNCTION_COVERAGE_HIT(base+i);
    for(unsigned i=0;i<10000;++i) VOID_FUNCTION_COVERAGE_HIT(4095);
    atomic_fetch_add(&done,1);
    THREAD_DONE;
}
static THREAD_RET held_writer(void *argument) { (void)argument; VOID_FUNCTION_COVERAGE_HIT(4096); THREAD_DONE; }
static THREAD_RET stopper(void *argument) { (void)argument; void_function_coverage_stop(); atomic_store(&stopped,1); THREAD_DONE; }
static void test_request_parser(void) {
    const struct { const char *text; int valid; uint64_t warmup,duration; } cases[] = {
        {"120000 60000\n",1,120000,60000}, {"0 1",1,0,1}, {"3600000 600000",1,3600000,600000},
        {" \t00001\r\n00002 \t",1,1,2}, {"",0,0,0}, {" \n",0,0,0}, {"0",0,0,0},
        {"0 0",0,0,0}, {"3600001 1",0,0,0}, {"0 600001",0,0,0},
        {"-1 60000",0,0,0}, {"-18446744073709551615 60000",0,0,0},
        {"0 -18446744073709551615",0,0,0}, {"+0 1",0,0,0}, {"0 +1",0,0,0},
        {"0+1",0,0,0}, {"18446744073709551616 1",0,0,0}, {"0 18446744073709551616",0,0,0},
        {"999999999999999999999999999999999999 1",0,0,0}, {"0 1 trailing",0,0,0},
        {"0 1 2",0,0,0}, {"0 1x",0,0,0}, {"0 0x10",0,0,0}, {"1.0 2",0,0,0}
    };
    for(unsigned i=0;i<sizeof cases/sizeof cases[0];++i) {
        uint64_t warmup=111,duration=222;
        const int valid=void_function_coverage_parse_request(cases[i].text,strlen(cases[i].text),&warmup,&duration);
        assert(valid==cases[i].valid);
        assert(warmup==(valid?cases[i].warmup:111) && duration==(valid?cases[i].duration:222));
    }
    const char embedded[]="0 1\0trailing";
    uint64_t warmup=111,duration=222;
    assert(!void_function_coverage_parse_request(embedded,sizeof embedded-1,&warmup,&duration));
    assert(warmup==111 && duration==222);
    puts("PASS coverage request parser: 25 cases, signs/overflow/trailing/NUL rejected, zero/min/max bounds checked");
}
int main(int argc,char **argv) {
    assert(argc==2);
    test_request_parser();
    assert(!void_function_coverage_export(argv[1],1,2,3,4,5,0,1));
    thread_t workers[8];
    for(unsigned i=0;i<8;++i) workers[i]=spawn(worker,(void *)(uintptr_t)i);
    atomic_store(&phase,1);
    while(atomic_load(&done)<8) YIELD();
    assert(void_function_coverage_arm());
    assert(!void_function_coverage_arm());
    atomic_store(&phase,2);
    while(atomic_load(&done)<16) YIELD();
    for(unsigned i=0;i<8;++i) join(workers[i]);
    thread_t held=spawn(held_writer,NULL);
    while(!atomic_load(&admitted)) YIELD();
    thread_t closing=spawn(stopper,NULL);
    while(atomic_load(&void_fc_state)&VOID_FC_FLAGS) YIELD();
    assert(!atomic_load(&stopped));
    VOID_FUNCTION_COVERAGE_HIT(4097);
    atomic_store(&release_writer,1);
    join(held); join(closing);
    assert(atomic_load(&void_fc_state)==0);
    for(unsigned i=0;i<VOID_FC_COUNT;++i) {
        const int special=(i==4095 || i==4096);
        const int expected_c=special || (i<2048 && i%256<192);
        const int expected_w=special || (i<2048 && i%256>=64 && i%256<192);
        const int c=(atomic_load(&void_fc_cumulative[i/64])>>(i%64))&1;
        const int w=(atomic_load(&void_fc_window[i/64])>>(i%64))&1;
        assert(c==expected_c && w==expected_w);
    }
    for(unsigned i=0;i<VOID_FC_COUNT;++i) VOID_FUNCTION_COVERAGE_HIT(i);
    assert(!((atomic_load(&void_fc_cumulative[64])>>1)&1));
    assert(void_function_coverage_export(argv[1],1,2,3,100,101,120000,60000));
    puts("PASS exact function coverage: 8 threads, 160000 repeated entries, 1538 cumulative IDs, 1026 window IDs, held-writer close race");
    return 0;
}
'''


def native_fixture(build_arm64):
    out = ROOT / "build/function-coverage-20261109/tests"
    out.mkdir(parents=True, exist_ok=True)
    entries = [{"id": i, "module": "fixture", "image": "fixture.exe", "address": f"{0x400000+i*16:08X}",
                "symbol": f"sub_{0x400000+i*16:08X}", "kind": "lifted", "source": "fixture.c"} for i in range(4099)]
    manifest = {"version": 1, "scope": "fixture", "excluded": "fixture", "meaning": "fixture", "entries": entries}
    identity = fc.digest_bytes(fc.canonical(manifest))
    manifest["identity_sha256"] = identity
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "function_coverage_ids.h").write_text(f'#define VOID_FC_COUNT 4099u\n#define VOID_FC_WORDS 65u\n#define VOID_FC_IDENTITY "{identity}"\n')
    source = out / "fixture.c"
    source.write_text(NATIVE)
    if os.name == "nt":
        from test_mmx_packed import CLANG, environment
        env, linker = environment("x64")
        # NDK's installed stdatomic.h assumes Bionic sys/cdefs.h even for a
        # Windows target. Map the standard operations to the same Clang C11
        # intrinsics in a test-private header; production uses Android's header.
        adapter = out / "host-include"
        adapter.mkdir(exist_ok=True)
        (adapter / "stdatomic.h").write_text('''#pragma once
enum { memory_order_relaxed=__ATOMIC_RELAXED, memory_order_acquire=__ATOMIC_ACQUIRE,
 memory_order_release=__ATOMIC_RELEASE, memory_order_acq_rel=__ATOMIC_ACQ_REL,
 memory_order_seq_cst=__ATOMIC_SEQ_CST };
#define atomic_load_explicit __c11_atomic_load
#define atomic_store_explicit __c11_atomic_store
#define atomic_fetch_add_explicit __c11_atomic_fetch_add
#define atomic_fetch_sub_explicit __c11_atomic_fetch_sub
#define atomic_fetch_or_explicit __c11_atomic_fetch_or
#define atomic_fetch_and_explicit __c11_atomic_fetch_and
#define atomic_compare_exchange_weak_explicit __c11_atomic_compare_exchange_weak
#define atomic_compare_exchange_strong_explicit __c11_atomic_compare_exchange_strong
#define atomic_load(p) atomic_load_explicit(p,memory_order_seq_cst)
#define atomic_store(p,v) atomic_store_explicit(p,v,memory_order_seq_cst)
#define atomic_fetch_add(p,v) atomic_fetch_add_explicit(p,v,memory_order_seq_cst)
#define atomic_compare_exchange_strong(p,e,v) atomic_compare_exchange_strong_explicit(p,e,v,memory_order_seq_cst,memory_order_seq_cst)
''')
        binary = out / "fixture.exe"
        command = [str(CLANG), "/nologo", "/O2", "/clang:-std=c11", "/clang:-Werror", "/D_CRT_SECURE_NO_WARNINGS", "/DVOID_FC_NO_MONITOR", "/DVOID_FC_TEST_HOOK",
                   "/I" + str(adapter), "/I" + str(ROOT / "tools"), "/I" + str(out), str(source), str(ROOT / "tools/function_coverage_runtime.c"),
                   "/c"]
    else:
        env = os.environ.copy()
        binary = out / "fixture"
        command = ["clang", "-std=c11", "-O2", "-Werror", "-DVOID_FC_NO_MONITOR", "-DVOID_FC_TEST_HOOK", "-I" + str(ROOT / "tools"),
                   "-I" + str(out), str(source), str(ROOT / "tools/function_coverage_runtime.c"), "-pthread", "-o", str(binary)]
    built = subprocess.run(command, cwd=out, env=env, text=True, capture_output=True)
    (out / "host-build.log").write_text(built.stdout + built.stderr)
    assert built.returncode == 0, built.stdout + built.stderr
    if os.name == "nt":
        linked = subprocess.run([str(linker), "/nologo", str(out / "fixture.obj"), str(out / "function_coverage_runtime.obj"),
                                 "/OUT:" + str(binary)], cwd=out, env=env, text=True, capture_output=True)
        assert linked.returncode == 0, linked.stdout + linked.stderr
    # Windows rename() does not replace an existing destination. Give each host
    # fixture a fresh path; production Android still publishes with atomic rename.
    with tempfile.TemporaryDirectory(prefix="capture-", dir=out) as temporary:
        capture = Path(temporary) / "capture.bin"
        ran = subprocess.run([str(binary), str(capture)], capture_output=True, text=True, timeout=30)
        (out / "host-result.txt").write_text(ran.stdout + ran.stderr)
        assert ran.returncode == 0 and "PASS exact function coverage:" in ran.stdout and "PASS coverage request parser:" in ran.stdout, ran.stdout + ran.stderr
        decoded = fc.decode(out / "manifest.json", capture)
        (out / "capture.bin").write_bytes(capture.read_bytes())
    assert decoded["banks"]["cumulative"]["unique_guest_function_count"] == 1538
    assert decoded["banks"]["window"]["unique_guest_function_count"] == 1026
    print(ran.stdout, end="")
    if build_arm64:
        sdk = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "AppData/Local/Android/Sdk"))
        ndk = Path(os.environ.get("ANDROID_NDK_HOME", sdk / "ndk/27.2.12479018"))
        clang = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
        common = [str(clang), "--target=aarch64-linux-android26", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                  "-I" + str(ROOT / "tools"), "-I" + str(out)]
        arm = subprocess.run([*common, "-DVOID_FC_NO_MONITOR", "-DVOID_FC_TEST_HOOK", str(source),
                              str(ROOT / "tools/function_coverage_runtime.c"), "-o", str(out / "fixture-arm64")], capture_output=True, text=True)
        monitor = subprocess.run([*common, "-c", str(ROOT / "tools/function_coverage_runtime.c"), "-o", str(out / "monitor-arm64.o")], capture_output=True, text=True)
        (out / "arm64-build.log").write_text(arm.stdout + arm.stderr + monitor.stdout + monitor.stderr)
        assert arm.returncode == monitor.returncode == 0, arm.stderr + monitor.stderr
        print("ARM64 fixture and full POSIX monitor compiled:", out / "fixture-arm64")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-arm64", action="store_true")
    args = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoverageTests))
    if not result.wasSuccessful():
        raise SystemExit(1)
    native_fixture(args.build_arm64)
