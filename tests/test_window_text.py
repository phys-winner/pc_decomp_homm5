"""Exercise actual saved window-title A/W getters and CP1251/UTF-16 setters."""
import unittest

from test_static_tls import ROOT, compile_probe
from test_user32_startup import body


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x40000];
static uint32_t args[3],last_error;
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM8(a) (*(uint8_t *)GPTR(a))
#define MEM16(a) (*(uint16_t *)GPTR(a))
#define ARG(i) args[i]
#define WINAPI_EXPORT(dll,name,nargs) enum { name##_nargs=nargs }; uint32_t name##_impl(void)
#define VLOG(...) ((void)0)
#define ERROR_INVALID_PARAMETER_ 87u
#define ERROR_INVALID_ADDRESS_ 487u
typedef struct {uint32_t hwnd;int alive;char title[256];} window_t;
static window_t windows[2]={{0x10010,1,""},{0x10020,1,"other window"}};
static int window_count=2,user_lock,lock_depth;
static void pthread_mutex_lock(int *lock) {assert(lock==&user_lock&&!lock_depth);++lock_depth;}
static void pthread_mutex_unlock(int *lock) {assert(lock==&user_lock&&lock_depth==1);--lock_depth;}
static void void_set_last_error(uint32_t value) {last_error=value;}
static int void_vm_writable(uint32_t a,uint32_t n) {
    return a>=0x100&&(uint64_t)a+n<=sizeof memory&&
        !((uint64_t)a<0x21000&&(uint64_t)a+n>0x20000)&&
        !((uint64_t)a<0x31000&&(uint64_t)a+n>0x30000);
}
/* STRINGS */
/* ACTUAL */
static uint32_t get(int wide,uint32_t hwnd,uint32_t dst,int cap) {
    args[0]=hwnd;args[1]=dst;args[2]=(uint32_t)cap;
    return wide?GetWindowTextW_impl():GetWindowTextA_impl();
}
int main(void) {
    assert(GetWindowTextA_nargs==3&&GetWindowTextW_nargs==3);
    memcpy(GPTR(0x1000),"Heroes V",9);args[0]=0x10010;args[1]=0x1000;
    assert(SetWindowTextA_impl()==1&&!lock_depth);
    memset(GPTR(0x11000),0xA5,32);last_error=0x12345678;
    assert(get(0,0x10010,0x11000,32)==8&&!memcmp(GPTR(0x11000),"Heroes V",9));
    assert(MEM8(0x11009)==0xA5&&last_error==0x12345678);
    memset(GPTR(0x11000),0xA5,32);
    assert(get(0,0x10010,0x11000,4)==3&&!memcmp(GPTR(0x11000),"Her",4)&&MEM8(0x11004)==0xA5);
    assert(get(0,0x10010,0x11000,1)==0&&!MEM8(0x11000));
    MEM8(0x11000)=0xA5;assert(get(0,0x10010,0x11000,0)==0&&MEM8(0x11000)==0xA5);
    assert(get(0,0x999,UINT32_MAX,0)==0&&last_error==0x12345678);
    const uint8_t russian[]={0xCF,0xF0,0xE8,0xE2,0xE5,0xF2,0x20,0xA8,0xE6,0};
    memcpy(GPTR(0x1000),russian,sizeof russian);args[0]=0x10010;args[1]=0x1000;assert(SetWindowTextA_impl());
    assert(get(0,0x10010,0x11000,32)==9&&!memcmp(GPTR(0x11000),russian,sizeof russian));
    assert(get(0,0x10010,0x11000,3)==2&&MEM8(0x11000)==0xCF&&MEM8(0x11001)==0xF0&&!MEM8(0x11002));
    assert(get(1,0x10010,0x11000,32)==9&&MEM16(0x11000)==0x41F&&MEM16(0x11002)==0x440&&!MEM16(0x11012));
    const uint16_t unicode[]={0x41,0x411,0xD83D,0xDE00,0x4E2D,0};
    memcpy(GPTR(0x1000),unicode,sizeof unicode);args[0]=0x10010;args[1]=0x1000;assert(SetWindowTextW_impl());
    const uint8_t ansi[]={0x41,0xC1,'?','?',0};
    assert(get(0,0x10010,0x11000,32)==4&&!memcmp(GPTR(0x11000),ansi,sizeof ansi));
    assert(get(1,0x10010,0x11000,32)==5&&!memcmp(GPTR(0x11000),unicode,sizeof unicode));
    memset(GPTR(0x11000),0xA5,32);
    assert(get(1,0x10010,0x11000,4)==3&&MEM16(0x11004)==0xD83D&&!MEM16(0x11006)&&MEM8(0x11008)==0xA5);
    assert(get(1,0x10010,0x11000,1)==0&&!MEM16(0x11000));
    last_error=0x55667788;assert(get(0,0x10020,0x11000,32)==12&&last_error==0x55667788);
    MEM8(0x1000)=0;args[0]=0x10010;args[1]=0x1000;assert(SetWindowTextA_impl());
    assert(get(0,0x10010,0x11000,32)==0&&!MEM8(0x11000)&&last_error==0x55667788);
    assert(get(1,0x10010,0x11000,32)==0&&!MEM16(0x11000)&&last_error==0x55667788);
    assert(get(0,0x999,0x11000,32)==0&&!MEM8(0x11000)&&last_error==1400);
    windows[1].alive=0;assert(get(1,0x10020,0x11000,32)==0&&!MEM16(0x11000)&&last_error==1400);
    memcpy(GPTR(0x1000),"Heroes V",9);args[0]=0x10010;args[1]=0x1000;assert(SetWindowTextA_impl());
    for(int wide=0;wide<=1;++wide) {
        memset(GPTR(0x20000),0xA5,32);assert(get(wide,0x10010,0x20000,32)==0&&last_error==487&&MEM8(0x20000)==0xA5);
        memset(GPTR(0x2FFFC),0xA5,4);assert(get(wide,0x10010,0x2FFFC,32)==0&&last_error==487&&MEM8(0x2FFFC)==0xA5);
        assert(get(wide,0x10010,UINT32_MAX,32)==0&&last_error==487);
        assert(get(wide,0x10010,0,32)==0&&last_error==487);
        assert(get(wide,0x10010,0x11000,-1)==0&&last_error==87);
        assert(get(wide,0x10010,0x11000,INT32_MAX)==8);
    }
    puts("PASS actual GetWindowTextA/W: saved per-window UTF8 titles, original CP1251/UTF16 setters/converters, NUL/count/truncation including UTF16 high surrogate, preserved success LastError, empty/invalid/dead windows, zero/negative capacity, read-only/unmapped/overflow guest buffers without partial writes");
}
'''


class WindowTextTest(unittest.TestCase):
    def test_saved_titles_and_checked_ansi_unicode_buffers(self):
        user = (ROOT / "android/host/user32.c").read_text(encoding="utf8")
        strings = (ROOT / "android/host/strings.c").read_text(encoding="utf8").replace('#include "host.h"', '')
        actual = body(user, "static window_t *find_window(") + body(user, "static uint32_t get_window_text(")
        actual += "\n".join(body(user, "WINAPI_EXPORT(U32, " + name + ",") for name in (
            "SetWindowTextA", "SetWindowTextW", "GetWindowTextA", "GetWindowTextW"))
        compile_probe("window_text", HARNESS.replace("/* STRINGS */", strings).replace("/* ACTUAL */", actual), {})


if __name__ == "__main__":
    unittest.main()
