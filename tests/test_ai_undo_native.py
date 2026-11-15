"""Names-table undo elision (android/host/ai_undo_native.c) against a model of the world's undo calls.

The model plays the call structure the kernel recognises, with the production entry/exit stack
effects: an object estimate (00BC5480) calls the world's rollback (0050C7C0) with its saved
transaction id; the rollback calls its commit (0050C550, entry ESP 0x54 below its own), runs a
pending full snapshot (0050C4A0), pops the transaction (every recorded entry back to its record)
and reads the touched objects back; the commit records the names table's entry and snapshots it
(0050C3E0: CChunklessSerializer save, then a CWorldCRCSaver CRC, each through the names table's
serializer 00C01130). The scenarios check that exactly the commit's save and CRC of the names
table are skipped when every condition holds (and the world's +16 byte gets the value a real save
leaves), and that each failed condition runs the original: option off, native-ai-original, WinSock
started, no estimate, a commit at another stack depth, a transaction that is not popped, a new
object, a full snapshot, an unknown +16 value, a rollback that does not restore the entry (which
also turns the skipping off for the process).
"""
import os
from pathlib import Path
import subprocess
import unittest

from test_mmx_packed import CLANG, command, environment, pc_header
from test_static_tls import ROOT

HERE = ROOT / "build/tests/ai-undo-native"
SOURCE = Path(os.environ.get("AI_UNDO_NATIVE_SOURCE", ROOT / "android/host/ai_undo_native.c"))

HOST = r'''
#include <stdint.h>
extern uint8_t memory[];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#include "recomp_types.h"
#undef ADDR
#define ADDR(va) ((uintptr_t)((uint32_t)(va) & 0xFFFFFu) + (uintptr_t)memory)
const char *void_data_dir(void);
void void_log(const char *fmt, ...);
'''

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
enum { MEMORY_BYTES = 0x100000 };
uint8_t memory[MEMORY_BYTES + 16];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#include "recomp_types.h"
#undef ADDR
#define ADDR(va) ((uintptr_t)((uint32_t)(va) & (MEMORY_BYTES - 1u)) + (uintptr_t)memory)
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_backedges,g_cur_func;
uint64_t g_mm[8];
xmm_t g_xmm[8];uint32_t g_mxcsr;
double g_st_win[RECOMP_X87_SLOTS];
int64_t g_st_i64_win[RECOMP_X87_SLOTS];int g_fp_sp;
int g_fp_top,void_fpu_cmp;
uint16_t g_fpu_cw;uint64_t g_fp_round_mask,g_fp_store_mask;
void (*recomp_yield_hook)(void);
static int logs, undo_failure_logs;
const char *void_data_dir(void) {return ".";}
void void_log(const char *format,...) {
    ++logs; if (strstr(format, "[ai-undo] rollback left")) ++undo_failure_logs;
    va_list a; va_start(a, format); vfprintf(stderr, format, a); va_end(a); fputc('\n', stderr);
}
static int fast_ai = 1, net = 0, live = 0;
int void_port_fast_ai(void) { return fast_ai; }
int void_network_started(void) { return net; }
int void_ai_live_original(int cached) { return live || cached; }
void void_ai_estimate_dispatch(void), void_ai_rollback_dispatch(void), void_ai_commit_dispatch(void);
void void_ai_full_snapshot_dispatch(void), void_ai_snapshot_dispatch(void), void_ai_names_serialize_dispatch(void);
void void_ai_undo_counts(uint64_t *, uint64_t *, uint64_t *);

#define CHUNKLESS 0x00E8D7BCu
#define CRC_SAVER 0x00E93664u
enum { WORLD = 0x10000, TABLE = 0x11000, OBJECT = 0x12000, BASES = 0x12100, VTABLE = 0x12200, ESTIMATE = 0x13000,
       SAVE = 0x14000, CRC = 0x14100, LOADER = 0x14200, RECORD = 0x15000, STACK = 0x80000, NAMES_INDEX = 3 };
static const uint32_t SELF = OBJECT + 0x20;   /* the serializer's this: object + 4 + [bases + 4] */
static uint32_t entry_of(unsigned i) { return TABLE + 40u * i; }
static int saves, crcs, loads, other_streams, full_pending, broken_pop, wrong_commit_depth, new_object;
static uint8_t flag_after_save = 1;

static void push(uint32_t v) { g_esp -= 4; MEM32(g_esp) = v; }

/* 00C01130: the names table's serializer (thiscall, one stream argument, ret 4). */
void sub_00C01130(void) {
    assert(g_ecx == SELF);
    const uint32_t stream = MEM32(g_esp + 4), vtable = MEM32(stream);
    if (vtable == CHUNKLESS && MEM32(stream + 24) == 2) {
        ++saves;
        MEM32(MEM32(stream + 20) + 4) = 0x5A5A0000u + saves;    /* the entry's bytes */
        MEM8(MEM32(stream + 16) + 8) = flag_after_save;          /* 0050BEB0: world +16 */
    } else if (vtable == CRC_SAVER) {
        ++crcs;
        MEM32(stream + 4) = 0xC0C00000u + crcs;
    } else if (vtable == CHUNKLESS && MEM32(stream + 24) == 1) {
        ++loads;
    } else ++other_streams;
    g_eax = 0;
    g_esp += 8;
}

/* 0050C3E0: snapshot(entry, object, flag), ret 0Ch. */
void sub_0050C3E0(void) {
    const uint32_t entry_esp = g_esp, world = g_ecx, entry = MEM32(g_esp + 4), object = MEM32(g_esp + 8);
    g_esp -= 16;                                    /* push ebx, ebp, esi, edi */
    MEM8(world + 16) = 0;
    MEM32(SAVE) = CHUNKLESS; MEM32(SAVE + 16) = world + 8; MEM32(SAVE + 20) = entry; MEM32(SAVE + 24) = 2;
    MEM32(entry + 4) = 0;                           /* 00403DA0: empty buffer */
    const uint32_t self = MEM32(MEM32(object + 4) + 4) + object + 4;
    push(SAVE); push(RECOMP_RETADDR); g_ecx = self;
    void_ai_names_serialize_dispatch();
    assert(g_esp == entry_esp - 16);
    MEM32(entry + 28) = MEM32(entry + 4) ^ 0x1111u;   /* 00B62340: checksum of the bytes */
    MEM8(entry + 32) = MEM8(world + 16);
    MEM32(CRC) = CRC_SAVER; MEM32(CRC + 4) = 0;
    push(CRC); push(RECOMP_RETADDR); g_ecx = self;
    void_ai_names_serialize_dispatch();
    assert(g_esp == entry_esp - 16);
    MEM32(entry + 36) = MEM32(CRC + 4);              /* 00B62380 */
    g_esp = entry_esp + 16;                          /* ret 0Ch */
}

/* 0050C4A0: snapshot every object (flag 0) when a full snapshot is pending. */
void sub_0050C4A0(void) {
    const uint32_t entry_esp = g_esp, world = g_ecx;
    g_esp -= 4;
    if (full_pending) {
        full_pending = 0;
        push(0); push(OBJECT); push(entry_of(NAMES_INDEX)); push(RECOMP_RETADDR); g_ecx = world;
        void_ai_snapshot_dispatch();
    }
    g_esp = entry_esp + 4;
}

/* 0050C550: commit, ret. Records the names entry, then snapshots it (record branch). */
void sub_0050C550(void) {
    const uint32_t entry_esp = g_esp, world = g_ecx, entry = entry_of(NAMES_INDEX);
    g_esp -= 0x1C;
    push(RECOMP_RETADDR); g_ecx = world; void_ai_full_snapshot_dispatch();
    memcpy(&MEM32(RECORD), &MEM32(entry), 40);      /* 0050D830: the history record */
    push(1); push(OBJECT); push(entry); push(RECOMP_RETADDR); g_ecx = world;
    void_ai_snapshot_dispatch();
    MEM32(world + 24) += 1;                         /* the new transaction's id */
    g_esp = entry_esp + 4;
}

/* 0050C7C0: rollback(target), ret 4: commit, full snapshot, pop, read back. */
void sub_0050C7C0(void) {
    const uint32_t entry_esp = g_esp, world = g_ecx, target = MEM32(g_esp + 4);
    g_esp -= wrong_commit_depth ? 0x54 : 0x50;
    push(RECOMP_RETADDR); g_ecx = world; void_ai_commit_dispatch();
    push(RECOMP_RETADDR); g_ecx = world; void_ai_full_snapshot_dispatch();
    while (MEM32(world + 24) > target) {             /* the pop */
        MEM32(world + 24) -= 1;
        if (!broken_pop) memcpy(&MEM32(entry_of(NAMES_INDEX)), &MEM32(RECORD), 40);
    }
    MEM32(LOADER) = CHUNKLESS; MEM32(LOADER + 24) = 1;   /* read back */
    push(LOADER); push(RECOMP_RETADDR); g_ecx = SELF;
    void_ai_names_serialize_dispatch();
    g_esp = entry_esp + 8;
}

/* 00BC5480: the estimate: its rollback goes back to the id it saved at +0x14. */
void sub_00BC5480(void) {
    const uint32_t entry_esp = g_esp, self = g_ecx;
    g_esp -= 0x44;
    push(MEM32(self + 0x14)); push(RECOMP_RETADDR); g_ecx = WORLD;
    void_ai_rollback_dispatch();
    assert(g_esp == entry_esp - 0x44);
    g_esp = entry_esp + 4;
}

static void setup(void) {
    memset(memory, 0, MEMORY_BYTES);
    MEM32(WORLD + 24) = 7;                          /* the next transaction id */
    MEM32(WORLD + 28) = TABLE; MEM32(WORLD + 32) = TABLE + 40u * 8;
    MEM32(OBJECT + 4) = BASES; MEM32(BASES + 4) = SELF - OBJECT - 4;
    MEM32(SELF) = VTABLE; MEM32(VTABLE + 12) = 0x00C01130u;
    MEM8(OBJECT + 13) = (uint8_t)new_object;
    const uint32_t entry = entry_of(NAMES_INDEX);
    MEM32(entry + 24) = OBJECT; MEM32(entry + 28) = 0xAAAA0001u; MEM8(entry + 32) = 1; MEM32(entry + 36) = 0xBBBB0001u;
    MEM32(ESTIMATE + 0x14) = 7;
}

static void estimate(void) {
    g_esp = STACK; push(RECOMP_RETADDR); g_ecx = ESTIMATE;
    void_ai_estimate_dispatch();
    assert(g_esp == STACK);
}

/* A real snapshot outside any estimate: shows the table's +16 value. */
static void normal_snapshot(void) {
    g_esp = STACK; push(1); push(OBJECT); push(entry_of(NAMES_INDEX)); push(RECOMP_RETADDR); g_ecx = WORLD;
    void_ai_snapshot_dispatch();
    assert(g_esp == STACK);
}

int main(int argc, char **argv) {
    const char *s = argc > 1 ? argv[1] : "";
    int prime = 1, expect_skip = 0, expect_failure = 0;
    if (!strcmp(s, "skip")) expect_skip = 1;
    else if (!strcmp(s, "flag0")) { expect_skip = 1; flag_after_save = 0; }
    else if (!strcmp(s, "off")) fast_ai = 0;
    else if (!strcmp(s, "net")) net = 1;
    else if (!strcmp(s, "live")) live = 1;
    else if (!strcmp(s, "depth")) wrong_commit_depth = 1;
    else if (!strcmp(s, "new")) new_object = 1;
    else if (!strcmp(s, "unknown")) prime = 0;
    else if (!strcmp(s, "notpopped")) ;
    else if (!strcmp(s, "full")) { expect_skip = 1; full_pending = 1; }
    else if (!strcmp(s, "broken")) { expect_skip = 1; broken_pop = 1; expect_failure = 1; }
    else if (!strcmp(s, "noestimate")) ;
    else { fprintf(stderr, "scenario?\n"); return 2; }
    setup();
    if (prime) { normal_snapshot(); assert(saves == 1 && crcs == 1); saves = crcs = 0; }
    const uint32_t entry = entry_of(NAMES_INDEX);
    MEM32(entry + 28) = 0xAAAA0001u; MEM8(entry + 32) = 1; MEM32(entry + 36) = 0xBBBB0001u;
    if (!strcmp(s, "notpopped")) MEM32(ESTIMATE + 0x14) = 9;   /* target above the next id: nothing popped */
    if (!strcmp(s, "noestimate")) {
        g_esp = STACK; push(7); push(RECOMP_RETADDR); g_ecx = WORLD; void_ai_rollback_dispatch();
    } else estimate();
    uint64_t estimates = 0, elided = 0, failures = 0;
    void_ai_undo_counts(&estimates, &elided, &failures);
    const int full = !strcmp(s, "full");
    printf("%s: saves %d crcs %d loads %d other %d estimates %llu elided %llu failures %llu flag %u\n", s, saves, crcs, loads,
           other_streams, (unsigned long long)estimates, (unsigned long long)elided, (unsigned long long)failures, MEM8(WORLD + 16));
    if (expect_skip) {
        assert(saves == full && crcs == full);       /* only the full snapshot's own pass runs */
        assert(elided == 1);
        assert(MEM8(WORLD + 16) == flag_after_save);
    } else {
        assert(saves == 1 && crcs == 1 && elided == 0);
    }
    assert(loads == (strcmp(s, "notpopped") ? 1 : 1));
    if (!broken_pop && strcmp(s, "notpopped")) {   /* the pop put the record back */
        assert(MEM32(entry + 28) == MEM32(RECORD + 28) && MEM8(entry + 32) == MEM8(RECORD + 32) &&
               MEM32(entry + 36) == MEM32(RECORD + 36));
        if (!full) assert(MEM32(entry + 28) == 0xAAAA0001u && MEM8(entry + 32) == 1 && MEM32(entry + 36) == 0xBBBB0001u);
    }
    assert((int)failures == expect_failure && undo_failure_logs == expect_failure);
    if (expect_failure) {                            /* switched off for the process */
        broken_pop = 0; saves = crcs = 0;
        MEM32(entry + 28) = 0xAAAA0001u; MEM8(entry + 32) = 1; MEM32(entry + 36) = 0xBBBB0001u;
        estimate();
        assert(saves == 1 && crcs == 1);
    }
    puts("PASS");
    return 0;
}
'''

SCENARIOS = ("skip", "flag0", "off", "net", "live", "depth", "new", "unknown", "notpopped", "full", "broken", "noestimate")


class AiUndoNativeTest(unittest.TestCase):
    def build(self, source=None, label="probe"):
        out = HERE / label
        out.mkdir(parents=True, exist_ok=True)
        files = {"probe.c": HARNESS, "native.c": source if source is not None else SOURCE.read_text(encoding="utf-8"),
                 "host.h": HOST, "native_mode.h": (ROOT / "android/host/native_mode.h").read_text(encoding="utf-8"),
                 "recomp_types.h": pc_header((ROOT / "android/runtime/recomp_types.h").read_text())}
        for name, text in files.items():
            (out / name).write_text(text, encoding="utf-8")
        env, linker = environment("x64")
        flags = [CLANG, "/nologo", "/W0", "/Od", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                 "/clang:--target=x86_64-pc-windows-msvc", "/clang:-fno-strict-aliasing", "/clang:-fwrapv"]
        command([*flags, "/c", "probe.c", "/Foprobe.obj"], out, env)
        command([*flags, "/c", "native.c", "/Fonative.obj"], out, env)
        command([linker, "/nologo", "probe.obj", "native.obj", "/OUT:probe.exe"], out, env)
        return out, env

    def run_scenario(self, out, env, scenario):
        return subprocess.run([str(out / "probe.exe"), scenario], cwd=out, env=env, text=True, capture_output=True,
                              timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)

    def test_scenarios(self):
        out, env = self.build()
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                result = self.run_scenario(out, env, scenario)
                self.assertEqual(result.returncode, 0, scenario + ": " + result.stdout + result.stderr)
                self.assertIn("PASS", result.stdout)

    def test_reject_unchecked_target(self):
        source = SOURCE.read_text(encoding="utf-8")
        old = "target != ld32(frames.estimate_this + 0x14u) || target > ld32(world + 24u)"
        self.assertEqual(source.count(old), 1)
        out, env = self.build(source.replace(old, "0"), "mutant-target")
        self.assertNotEqual(self.run_scenario(out, env, "notpopped").returncode, 0)

    def test_reject_unchecked_new_object(self):
        source = SOURCE.read_text(encoding="utf-8")
        old = "ld8(object + 13u) == 0 &&"
        self.assertEqual(source.count(old), 1)
        out, env = self.build(source.replace(old, ""), "mutant-new")
        self.assertNotEqual(self.run_scenario(out, env, "new").returncode, 0)

    def test_reject_skipped_flag(self):
        source = SOURCE.read_text(encoding="utf-8")
        old = "st8(frames.world + 16u, (uint8_t)__c11_atomic_load(&names_flag, __ATOMIC_RELAXED));"
        self.assertEqual(source.count(old), 1)
        out, env = self.build(source.replace(old, ""), "mutant-flag")
        self.assertNotEqual(self.run_scenario(out, env, "skip").returncode, 0)


if __name__ == "__main__":
    unittest.main()
