"""Run the actual activation, shared-cursor and CP1251 conversion bodies."""
import re
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[0x40000];
static uint32_t args[16], last_error, thread_id=1, messages;
#define MEM8(a) memory[(uint32_t)(a)]
#define ARG(i) args[i]
#define WINAPI_EXPORT(dll,name,nargs) uint32_t name##_impl(void)
#define ERROR_NOT_SUPPORTED_ 50u
#define ERROR_INVALID_ADDRESS_ 487u
/* WM_CONSTANTS */
static void void_set_last_error(uint32_t e) { last_error=e; }
static uint32_t void_thread_id(void) { return thread_id; }
static int void_vm_readable(uint32_t a, uint32_t n) {
    return a>=0x100 && (uint64_t)a+n<=sizeof memory && !((uint64_t)a<0x31000 && (uint64_t)a+n>0x30000);
}
static int void_vm_writable(uint32_t a, uint32_t n) {
    return void_vm_readable(a,n) && !((uint64_t)a<0x21000 && (uint64_t)a+n>0x20000);
}
typedef struct { uint32_t hwnd, thread, style, alive, wndproc; } window_t;
typedef struct { uint32_t thread, active; } queue_t;
static window_t windows[4]={{0x10010,1,0,1,1},{0x10020,1,0,1,1},{0x10030,2,0,1,1},{0x10040,1,0x40000000,1,1}};
static queue_t queues[4]; static int queue_count;
static uint32_t main_window=0x10010, focus_window;
static window_t *find_window(uint32_t hwnd) { for(int i=0;i<4;i++) if(windows[i].hwnd==hwnd && windows[i].alive) return &windows[i]; return NULL; }
static queue_t *queue_for(uint32_t t) {
    for(int i=0;i<queue_count;i++) if(queues[i].thread==t) return &queues[i];
    assert(queue_count<4); queues[queue_count].thread=t; return &queues[queue_count++];
}
static uint32_t send_message(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp) {
    assert(find_window(hwnd)); (void)msg; (void)wp; (void)lp; ++messages; return 0;
}
static uint32_t current_cursor=0x20001;
static uint8_t shared_cursors[256]={1};
/* ACTUAL_BODIES */
static const uint8_t lower_expected[256]={/* EXPECTED_CP1251 */};
int main(void) {
    assert(GetActiveWindow_impl()==0);
    args[0]=0x10010; assert(SetActiveWindow_impl()==0 && GetActiveWindow_impl()==0x10010 && focus_window==0x10010 && messages==4);
    assert(SetActiveWindow_impl()==0x10010 && messages==4);
    args[0]=0x10020; assert(SetActiveWindow_impl()==0x10010 && GetActiveWindow_impl()==0x10020 && focus_window==0x10020);
    thread_id=2; assert(GetActiveWindow_impl()==0);
    args[0]=0x10010; assert(SetActiveWindow_impl()==0 && GetActiveWindow_impl()==0 && focus_window==0x10020);
    args[0]=0x10030; assert(SetActiveWindow_impl()==0 && GetActiveWindow_impl()==0x10030);
    thread_id=1; assert(GetActiveWindow_impl()==0x10020);
    args[0]=0; assert(SetActiveWindow_impl()==0x10020 && GetActiveWindow_impl()==0 && focus_window==0x10030);
    args[0]=0x10010; assert(SetActiveWindow_impl()==0 && GetActiveWindow_impl()==0x10010);
    args[0]=0x999; assert(SetActiveWindow_impl()==0 && last_error==1400 && GetActiveWindow_impl()==0x10010);
    args[0]=0x10040; assert(SetActiveWindow_impl()==0 && GetActiveWindow_impl()==0x10010);
    args[0]=0x10030; assert(SetActiveWindow_impl()==0 && GetActiveWindow_impl()==0 && focus_window==0);
    args[0]=0x10010; SetActiveWindow_impl();
    assert(DestroyWindow_impl()==1 && GetActiveWindow_impl()==0 && focus_window==0 && main_window==0);
    args[0]=0x10020; SetActiveWindow_impl();
    def_window_proc(0x10020,WM_CLOSE,0,0); assert(!windows[1].alive && GetActiveWindow_impl()==0 && focus_window==0);
    args[0]=0; args[1]=32512; assert(LoadCursorA_impl()==0x20001);
    args[1]=32514; uint32_t wait=LoadCursorW_impl(); assert(wait==0x20003);
    args[0]=wait; assert(SetCursor_impl()==0x20001 && GetCursor_impl()==wait);
    args[0]=0; assert(SetCursor_impl()==wait && GetCursor_impl()==0);
    args[0]=0x20001; assert(DestroyCursor_impl()==1 && SetCursor_impl()==0 && GetCursor_impl()==0x20001);
    assert(DestroyCursor_impl()==0 && last_error==170 && GetCursor_impl()==0x20001);
    args[0]=0x20022; assert(SetCursor_impl()==0 && last_error==1402 && GetCursor_impl()==0x20001);
    assert(DestroyCursor_impl()==0 && last_error==1402);
    args[0]=UINT32_MAX; assert(LoadCursorFromFileA_impl()==0 && last_error==50);
    args[0]=0; args[1]=0; assert(LoadCursorA_impl()==0 && last_error==1814);
    args[0]=1; args[1]=32512; assert(LoadCursorA_impl()==0 && last_error==50);
    for(uint32_t i=0;i<256;i++) {
        args[0]=i; assert(CharLowerA_impl()==lower_expected[i]);
        args[0]=0xab00|i; assert(CharLowerA_impl()==(0xab00u|lower_expected[i]));
        MEM8(0x11000+i)=i ? (uint8_t)i : 'A';
    }
    MEM8(0x11100)=0; args[0]=0x11000;
    assert(CharLowerA_impl()==0x11000 && MEM8(0x11000)=='a');
    for(uint32_t i=1;i<256;i++) assert(MEM8(0x11000+i)==lower_expected[i]);
    MEM8(0x20000)='A'; MEM8(0x20001)=0; args[0]=0x20000;
    assert(CharLowerA_impl()==0 && last_error==487 && MEM8(0x20000)=='A');
    memcpy(memory+0x2fffc,"ABCD",4); args[0]=0x2fffc;
    assert(CharLowerA_impl()==0 && last_error==487 && !memcmp(memory+0x2fffc,"ABCD",4));
    args[0]=0x30000; assert(CharLowerA_impl()==0 && last_error==487);
    args[0]=UINT32_MAX; assert(CharLowerA_impl()==0 && last_error==487);
    puts("PASS actual user32: same/foreign-thread activation, NULL and invalid handles, destroy/close cleanup, current/shared cursors, CP1251 byte+string modes, protected/unmapped bounds and no partial writes");
    return 0;
}
'''


def body(text, signature):
    start = text.index(signature)
    first = text.index("{", start)
    depth = 1
    end = first + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end] + "\n"


class User32StartupTest(unittest.TestCase):
    def test_actual_bodies(self):
        text = (ROOT / "android/host/user32.c").read_text()
        declarations = ["static int shared_cursor(", "static uint32_t load_shared_cursor(",
                        "static void activate(", "static uint32_t def_window_proc("]
        names = ("SetActiveWindow", "GetActiveWindow", "DestroyWindow", "SetCursor", "GetCursor", "LoadCursorA", "LoadCursorW", "LoadCursorFromFileA", "DestroyCursor", "CharLowerA")
        strings = (ROOT / "android/host/strings.c").read_text(encoding="utf-8")
        pure = strings[strings.index("static const uint16_t cp1252_high"):strings.index("size_t void_utf8_encode")]
        code = pure + "\n".join(body(text, signature) for signature in declarations)
        code += "\n".join(body(text, "WINAPI_EXPORT(U32, " + name + ",") for name in names)
        expected = []
        for value in range(256):
            try:
                expected.append(bytes([value]).decode("cp1251").lower().encode("cp1251")[0])
            except UnicodeError:
                expected.append(value)
        macros = "\n".join(re.findall(r"^#define WM_.*$", text, flags=re.M))
        fixture = HARNESS.replace("/* WM_CONSTANTS */", macros).replace("/* ACTUAL_BODIES */", code)
        fixture = fixture.replace("/* EXPECTED_CP1251 */", ",".join(map(str, expected)))
        compile_probe("user32_startup", fixture, {})


if __name__ == "__main__":
    unittest.main()
