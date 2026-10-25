"""Thread roots accept legacy cdecl RET; other callbacks retain their exact ABI."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>
static uint32_t stack[1024];
#define MEM32(a) stack[(a)/4]
#define PUSH32(sp,v) do {(sp)-=4;MEM32(sp)=(v);} while(0)
#define RECOMP_RETADDR 0xDEAD0000u
static uint32_t g_esp,g_eax,g_ebx,g_esi,g_edi,g_ebp,g_cur_func;
static jmp_buf trap;
static unsigned pop_bytes;
static void worker(void) {
    assert(MEM32(g_esp)==RECOMP_RETADDR&&MEM32(g_esp+4)==0x12345678);
    g_esp+=4+pop_bytes;g_eax=23;g_ebx=g_esi=g_edi=g_ebp=0;g_cur_func=0xBAD;
}
typedef void (*recomp_func_t)(void);
static recomp_func_t void_resolve(uint32_t va) {assert(va==0x401000);return worker;}
static void void_log(const char *format,...) {(void)format;}
static void void_lift_trap(uint32_t va,const char *why) {assert(va==0x401000&&why);longjmp(trap,1);}
#include "thread_call.h"
static void check(int mode,unsigned cleanup,int allowed) {
    g_esp=0x800;g_ebx=1;g_esi=2;g_edi=3;g_ebp=4;g_cur_func=0x402000;pop_bytes=cleanup;
    uint32_t arg=0x12345678;
    if(setjmp(trap)) {assert(!allowed);return;}
    assert(void_call_guest(0x401000,1,&arg,mode)==23&&allowed);
    assert(g_esp==0x800&&g_ebx==1&&g_esi==2&&g_edi==3&&g_ebp==4&&g_cur_func==0x402000);
}
int main(void) {
    check(2,0,1);check(2,4,1);check(2,8,0);check(1,0,0);check(1,4,1);check(0,0,1);check(0,4,0);
    puts("PASS thread root: legacy cdecl and stdcall, malformed returns rejected, other callbacks strict, stack and nonvolatile registers restored");
}
'''


class ThreadStartTest(unittest.TestCase):
    def test_call_conventions(self):
        source = (ROOT / "android/host/threads.c").read_text(encoding="utf8")
        self.assertIn("void_call_guest(t->start, 1, args, 2)", source)
        compile_probe("thread_start", HARNESS, {"thread_call.h": function(source, "uint32_t void_call_guest(")})


if __name__ == "__main__":
    unittest.main()
