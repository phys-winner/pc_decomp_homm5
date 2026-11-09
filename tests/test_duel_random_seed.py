"""Original startup entropy failure and the actual ISAAC stream in all editions."""
import hashlib
import json
import re
import sys
import unittest

import pefile

from test_mmx_packed import CLANG, command, environment, pc_header
from test_scene_native import body
from test_static_tls import ROOT

sys.path.insert(0, str(ROOT / "tools"))
from editions import generated_root
from port_patches import adapt_generated_source, load_contract


# Independently read original PE imports, constructor call, and global state.
FACTS = {
    "toe": ("game_0560.c", "00B25320", "00B25600", "00B25910", "00B25F50", "00B261A0", "00B25D40",
            0x01026028, 0xE0A104, 0xE0A100,
            "b8ffed54d19f6f32d9534e033c773542049cdba5beede3b78d90b9ac0c6d255a",
            "c95085bcbbc87ddc70f7c92ce1f7b9389b8f96752d7a341437cf1c15804edb61"),
    "vanilla": ("game_0585.c", "00B2F2B0", "00B2F590", "00B2F8A0", "00B2FED0", "00B30120", "00B2FCC0",
                0x010B6F98, 0xDE3118, 0xDE3114,
                "d0e8ef7504b10a8d21ec435b8178babb697d211c099e1f715162f31caa6e8e1d",
                "a2587160f4ded5bc95f4e6854a8d1e2043d2bfc91cdd428976ac4dcafa19b50c"),
    "hof": ("game_0086.c", "004F9FA0", "004FA280", "004FA590", "004FABC0", "004FAF80", "004FA9B0",
            0x00F4BBE0, 0xDBA04C, 0xDBA048,
            "ba3e191e3c811c7d2c79673dc9e40cfc9694f2398861dafdff80519429caf0b0",
            "2a777b1c62613ad4cf0eafa8eb1039a74c5e7ee3acf8c3f35eefea6887f9e68c"),
}


def seed_patch(edition):
    """Exact generated-patch anchor to install in the edition contract."""
    _, _, _, _, gather, initialize, *_ = FACTS[edition]
    site = {"toe": "00B261CC", "vanilla": "00B3014C", "hof": "004FAFAC"}[edition]
    old = f"    RECOMP_CALL(sub_{gather}); /* 0x{site}: call 0x{int(gather, 16):x} */"
    return dict(module="game", function="sub_" + initialize, old=old,
                new=old + "\n    { extern void void_initial_seed_entropy(uint32_t); void_initial_seed_entropy(esp + 0x14u); }")


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>
enum { BYTES=0x1200000, STACK=0x40000, MATERIAL=0x20000, STATE_BYTES=0x810 };
static uint8_t memory[BYTES];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#define RECOMP_LOCAL_REGS
#define RECOMP_PLAIN_MEMORY
#include "recomp_types.h"
uint32_t g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi;
uint32_t g_flag_k,g_flag_a,g_flag_b,g_flag_cf,g_backedges,g_cur_func;
uint64_t g_mm[8];xmm_t g_xmm[8];uint32_t g_mxcsr;
double g_st[8];int64_t g_st_i64[8];int g_fp_top,void_fpu_cmp;uint16_t g_fpu_cw;
void (*recomp_yield_hook)(void);
static unsigned drive_calls,entropy_calls,validating,fatal_seen;
static jmp_buf invalid_buffer;
static int void_vm_writable(uint32_t va,uint32_t size) {
    return va>=0x100 && (uint64_t)va+size<=BYTES;
}
static _Noreturn void void_fatal(const char *format,...) {
    (void)format;assert(validating);++fatal_seen;longjmp(invalid_buffer,1);
}
__declspec(dllimport) long __stdcall BCryptGenRandom(void*,unsigned char*,unsigned long,unsigned long);
static void arc4random_buf(void *out,size_t bytes) {
    ++entropy_calls;assert(!BCryptGenRandom(NULL,out,(unsigned long)bytes,2));
}
#include "entropy.h"
static void logical_drives(void) {
    assert(MEM32(g_esp+4)>=5);memcpy(GPTR(MEM32(g_esp+8)),"C:\\\0",5);
    ++drive_calls;g_eax=4;g_esp+=12;
}
static void drive_type(void) {
    assert(!strcmp((const char*)GPTR(MEM32(g_esp+4)),"C:\\"));g_eax=3;g_esp+=8;
}
recomp_func_t void_resolve(uint32_t target) {
    if(target==0x1111)return logical_drives;
    if(target==0x2222)return drive_type;
    fprintf(stderr,"unexpected import %08x\n",target);abort();
}
static void file_entropy(void) {assert(!"the original collector must skip file/clock/rand entropy");}
static void rng_refill(void),rng_mix(void),rng_draw(void),gather(void),process_init(void),original_init(void);
#include "original.h"
static void prepare_call(void) {
    g_esp=STACK;MEM32(g_esp)=RECOMP_RETADDR;
    g_eax=0xAABBCCDD;g_ecx=MATERIAL;g_edx=0x12345678;
    g_ebx=0xABABABAB;g_ebp=0xCDCDCDCD;g_esi=0xEFEFEFEF;g_edi=0x789ABCDE;
}
static void startup(int patched) {
    memset(memory,0,sizeof memory);MEM32(DRIVES_IMPORT)=0x1111;MEM32(TYPE_IMPORT)=0x2222;
    prepare_call();
    if(patched)process_init();else original_init();
    assert(g_esp==STACK+4 && g_ebx==0xABABABAB && g_ebp==0xCDCDCDCD &&
        g_esi==0xEFEFEFEF && g_edi==0x789ABCDE);
    assert(MEM32(RNG_STATE)==256);
}
static uint32_t draw(void) {
    prepare_call();rng_draw();assert(g_esp==STACK+4);return g_eax;
}
int main(void) {
    /* The actual collector returns with material unchanged on the only C: drive. */
    memset(memory,0xA7,sizeof memory);MEM32(DRIVES_IMPORT)=0x1111;MEM32(TYPE_IMPORT)=0x2222;
    prepare_call();MEM32(STACK+4)=MATERIAL;
    gather();assert(g_esp==STACK+8 && drive_calls==1 && !entropy_calls);
    for(unsigned i=0;i<STATE_BYTES;++i)assert(MEM8(MATERIAL+i)==0xA7);
    uint8_t baseline[STATE_BYTES],saved[STATE_BYTES];uint32_t sequence[768];
    startup(0);memcpy(baseline,GPTR(RNG_STATE),sizeof baseline);
    for(unsigned i=0;i<768;++i)sequence[i]=draw();
    startup(0);assert(!memcmp(baseline,GPTR(RNG_STATE),sizeof baseline));
    for(unsigned i=0;i<768;++i)assert(sequence[i]==draw());
    assert(!entropy_calls);
    /* Fresh OS seed material changes startup; all later draws remain the original code. */
    unsigned seen[24]={0};
    for(unsigned trial=0;trial<16;++trial) {
        startup(1);assert(entropy_calls==trial+1);
        assert(memcmp(baseline,GPTR(RNG_STATE),sizeof baseline));
        memcpy(baseline,GPTR(RNG_STATE),sizeof baseline);
        for(unsigned i=0;i<32;++i)++seen[draw()%24];
    }
    unsigned covered=0;for(unsigned i=0;i<24;++i)covered+=!!seen[i];assert(covered>20);
    /* Explicit seed and full saved state round-trip retain their deterministic stream. */
    for(unsigned trial=0;trial<3;++trial) {
        memset(GPTR(MATERIAL),0,STATE_BYTES);
        for(unsigned i=0;i<256;++i)MEM32(MATERIAL+4+i*4)=i*0x9E3779B9u+trial;
        prepare_call();g_ecx=MATERIAL;rng_mix();memcpy(GPTR(RNG_STATE),GPTR(MATERIAL),STATE_BYTES);
        unsigned before=entropy_calls;
        memcpy(saved,GPTR(RNG_STATE),sizeof saved);
        for(unsigned i=0;i<768;++i)sequence[i]=draw();
        memcpy(GPTR(RNG_STATE),saved,sizeof saved);
        for(unsigned i=0;i<768;++i)assert(sequence[i]==draw());
        assert(before==entropy_calls);
    }
    memset(GPTR(MATERIAL-1),0xC3,1026);prepare_call();
    uint32_t before_regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,
        g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    void_initial_seed_entropy(MATERIAL);
    uint32_t after_regs[]={g_eax,g_ecx,g_edx,g_ebx,g_esp,g_ebp,g_esi,g_edi,
        g_flag_k,g_flag_a,g_flag_b,g_flag_cf};
    assert(!memcmp(before_regs,after_regs,sizeof before_regs));
    assert(MEM8(MATERIAL-1)==0xC3 && MEM8(MATERIAL+1024)==0xC3);
    validating=1;
    if(!setjmp(invalid_buffer)){void_initial_seed_entropy(BYTES-1023);assert(0);}
    if(!setjmp(invalid_buffer)){void_initial_seed_entropy(UINT32_MAX-10);assert(0);}
    assert(fatal_seen==2 && entropy_calls==17);
    printf("PASS actual one-C-drive failure; 16 fresh startup seeds, %u/24 random indices; 4608 explicit-seed/restored draws; exact1024B bounds and guest ABI\n",covered);
    printf("fresh-process fingerprint %08x %08x\n",MEM32(MATERIAL),MEM32(MATERIAL+4));
    return 0;
}
'''


class DuelRandomSeedTest(unittest.TestCase):
    def test_original_and_startup_fix_all_editions(self):
        helper_source = (ROOT / "android/host/rpc.c").read_text()
        start = helper_source.index("void void_initial_seed_entropy(uint32_t material)")
        helper = helper_source[start:helper_source.index("\n}", start) + 2]
        env, linker = environment("x64")
        for edition, facts in FACTS.items():
            with self.subTest(edition=edition):
                unit, refill, mix, draw, gather, initialize, file_entropy, state, drives, drive_type, gather_sha, init_sha = facts
                generated = generated_root(edition)
                original = (generated / "game-x86" / unit).read_bytes().decode()
                pe = pefile.PE(str(generated / "input/H5_Game.exe"), fast_load=True)
                for address, size, expected in ((gather, 0x22D, gather_sha), (initialize, 0x53, init_sha)):
                    self.assertEqual(hashlib.sha256(pe.get_data(int(address, 16) - pe.OPTIONAL_HEADER.ImageBase, size)).hexdigest(), expected)
                functions = [body(original, "sub_" + va) for va in (refill, mix, draw, gather, initialize)]
                anchor = seed_patch(edition)
                self.assertIn(anchor, load_contract(edition)["generated_patches"])
                self.assertEqual(functions[-1].count(anchor["old"]), 1)
                patched = adapt_generated_source(functions[-1].encode(), "game", edition).decode()
                self.assertIn("void_initial_seed_entropy(esp + 0x14u)", patched)
                functions.append(functions[-1].replace("void sub_" + initialize + "(void)", "static void original_init(void)", 1))
                functions[-2] = patched
                source = "\n".join(functions)
                for va, name in zip((refill, mix, draw, gather, initialize, file_entropy),
                                    ("rng_refill", "rng_mix", "rng_draw", "gather", "process_init", "file_entropy")):
                    source = source.replace("sub_" + va, name)
                source = re.sub(r"^void (rng_refill|rng_mix|rng_draw|gather|process_init)\(void\)", r"static void \1(void)", source, flags=re.M)
                out = ROOT / "build/tests/duel-random-seed" / edition
                out.mkdir(parents=True, exist_ok=True)
                prefix = f"#define RNG_STATE 0x{state:X}u\n#define DRIVES_IMPORT 0x{drives:X}u\n#define TYPE_IMPORT 0x{drive_type:X}u\n"
                files = {"probe.c": prefix + HARNESS, "entropy.h": helper, "original.h": source,
                         "recomp_types.h": pc_header((ROOT / "android/runtime/recomp_types.h").read_text())}
                for name, text in files.items():
                    (out / name).write_text(text)
                command([CLANG, "/nologo", "/W0", "/O2", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS",
                         "/clang:--target=x86_64-pc-windows-msvc", "/clang:-fwrapv", "/clang:-fno-strict-aliasing",
                         "/c", "probe.c", "/Foprobe.obj"], out, env)
                command([linker, "/nologo", "probe.obj", "bcrypt.lib", "/OUT:probe.exe"], out, env)
                runs = [command([out / "probe.exe"], out, env).stdout for _ in range(2)]
                self.assertNotEqual(runs[0].splitlines()[-1], runs[1].splitlines()[-1])
                (out / "receipt.json").write_text(json.dumps(dict(edition=edition, result=runs,
                    original_entropy_sha256=gather_sha, original_constructor_sha256=init_sha,
                    helper_sha256=hashlib.sha256(helper.encode()).hexdigest(), patch=anchor, device_tested=False), indent=2) + "\n")
                print(edition + ": " + runs[0].strip())


if __name__ == "__main__":
    unittest.main()
