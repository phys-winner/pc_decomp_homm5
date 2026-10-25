"""Exercise the actual launcher reaction, native exit/cancel and button visibility."""
import unittest
import xml.etree.ElementTree as ET
import json
import sys
from test_static_tls import ROOT, compile_probe
sys.path.insert(0, str(ROOT / "tools"))
import port_ui


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x40000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEM8(a) (*(uint8_t *)GPTR(a))
typedef void (*void_fn)(void);
static uint32_t g_ecx,g_edx,g_eax,g_esp;
typedef struct {uint32_t ecx,edx,eax,esp;} void_regs;
static void void_regs_save(void_regs *r) {*r=(void_regs){g_ecx,g_edx,g_eax,g_esp};}
static void void_regs_load(const void_regs *r) {g_ecx=r->ecx;g_edx=r->edx;g_eax=r->eax;g_esp=r->esp;}
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100&&(uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n) {return void_vm_readable(a,n);}
static uint32_t read32(uint32_t a) {return void_vm_readable(a,4)?MEM32(a):0;}
static uint32_t mock_screen=0x1000, mock_db=0x2000;
static uint32_t current_screen(void) {return mock_screen;}
static int originals,confirms,returns,accepts,messages,clones;
static int helps;
void void_android_gamepad_help(void) {helps++;}
static void passthrough(void) {originals++;g_esp+=16;}
static void confirm(void) {confirms++;g_esp+=8;}
void void_android_return_to_launcher(void) {returns++;}
static void port_exit_confirm(void);
static void_fn void_dispatch_find(uint32_t a) {return a==0x1234||a==0x5678||a==0xA4D570?passthrough:NULL;}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args) {
    if(va==0x6895E0) {assert(self==mock_screen+0x174&&n==1&&args[0]==0);port_exit_confirm();return 0;}
    if(va==0x5678) {assert(n==1&&self==0x5090);MEM8(MEM32(self-0x90+0x20)+0x70)=(uint8_t)args[0];return 0;}
    assert(n==0&&!args);
    if(va==0xB299F0) {assert(self==0x300C);g_ecx=0xFFFF;return mock_db;}
    if(va==0x75C8E0) {assert(self==mock_screen);accepts++;return 0;}
    assert(va==0x1234);return MEM32(self+0x20);
}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *args,int pops) {
    if(va==0xA4D570) {assert(n==0&&!args&&pops&&g_ecx==0xC090&&g_edx==0x5090);clones++;return 0xF000;}
    assert(va==0x689790&&n==0&&!args&&pops);messages++;return 0;
}
#include "launcher_menu.h"
static void click(const char *event,uint32_t table) {
    MEM32(mock_screen)=table;MEM32(mock_db+0x48)=0x2100;MEM32(mock_db+0x4C)=0x2100+(uint32_t)strlen(event);
    memcpy(GPTR(0x2100),event,strlen(event)+1);
    g_ecx=0x3000;g_edx=77;g_eax=0xFF00;g_esp=0x4000;port_game_message();
    assert(g_ecx==0x3000&&g_edx==77&&g_esp==0x4010);
}
int main(void) {
    original_game_message=passthrough;original_exit_confirm=confirm;
    click("other",0);assert(originals==1&&!messages&&!confirms&&!returns);
    click("port_gamepad",0);assert(helps==1&&originals==1&&!messages&&!returns&&g_eax==0xFF01);
    MEM32(mock_screen+0x1A0)=1;click("port_launcher",0xE3DA1C);assert(!accepts&&!messages);
    MEM32(mock_screen+0x1A0)=2;click("port_launcher",0xE3DA1C);
    assert(accepts==1&&messages==1&&launcher_pending&&!returns);
    port_menu_pump();assert(launcher_pending); /* Waiting for the native question. */
    MEM32(mock_screen)=0xE3112C;port_menu_pump();assert(launcher_question_seen);
    MEM32(mock_screen)=0;port_menu_pump();assert(!launcher_pending); /* Cancel. */
    port_exit_confirm();assert(confirms==1&&!returns); /* Ordinary exit stays ordinary. */
    click("port_launcher",0xE3DA1C);port_exit_confirm();assert(returns==1&&confirms==2&&!launcher_pending);
    click("port_launcher",0xE3112C);assert(returns==2&&confirms==3&&!launcher_pending);
    /* A real window getter and bounded child vector; only the named button changes. */
    MEM32(0x5000)=0x6000;MEM32(0x6008)=0x1234;MEM32(0x5020)=0x7000;
    MEM32(0x5010)=0xD000;MEM32(0xD008)=0x80;MEM32(0x5090)=0xE000;MEM32(0xE044)=0x5678;
    MEM32(0x7058)=0x8000;MEM32(0x705C)=0x8013;memcpy(GPTR(0x8000),"PortOptionsLauncher",19);
    port_launcher_visibility(0x5000,0,1);assert(MEM8(0x7070));
    port_launcher_visibility(0x5000,0,0);assert(!MEM8(0x7070));
    MEM32(0x705C)=0x8000;MEM8(0x7070)=1;MEM32(0x50A4)=0x5000;MEM32(0x50A8)=0x5004;
    port_launcher_visibility(0x5000,0,1); /* Cyclic tree bounded. */
    MEM32(mock_screen)=0xE3112C;MEM32(mock_screen+0xA0)=0xA0F8;
    MEM32(0xA0A4)=0xB000;MEM32(0xA0A8)=0xB008;MEM32(0xB000)=0x5000;MEM32(0xB004)=0xC000;
    MEM32(0xC000)=0xE3091C;MEM32(0xC010)=0xD100;MEM32(0xD108)=0x80;
    MEM32(0x705C)=0x8010;memcpy(GPTR(0x8000),"PortExitLauncher",16);
    port_menu_pump();assert(clones==1&&!MEM8(0x7070));
    port_menu_pump();assert(clones==1&&MEM32(0xB000)==0x5000&&MEM32(0xB004)==0xC000); /* No repeated clones or raw reparenting. */
    puts("PASS launcher: native options accept, exit message, cancel, ordinary exit, confirmed launcher exit, register ABI and bounded visibility");
}
'''


class LauncherMenuTest(unittest.TestCase):
    def test_gamepad_button_fits_native_menu(self):
        game = json.loads((ROOT / "port.json").read_text(encoding="utf8"))["game_directory"]
        members = port_ui.gamepad_button(game)
        button = ET.fromstring(members["UI/MainMenu2/PortGamepad.(WindowMSButton).xdb"])
        self.assertEqual(button.findtext("Placement/Position/First/y"), "180")
        self.assertEqual(button.findtext("Placement/Size/First/y"), "34")
        self.assertEqual(members["UI/PortGamepad.txt"].decode("utf16"), "Геймпад")
        shared = ET.fromstring(members["UI/MainMenu2/Menu.(WindowSimpleShared).xdb"])
        self.assertEqual(len(shared.find("Children")), 6)
        quit_button = ET.fromstring(members["UI/MainMenu2/Quit.(WindowMSButton).xdb"])
        self.assertEqual(quit_button.findtext("Placement/Position/First/y"), "216")
        reaction = ET.fromstring(members["UI/PortGamepad.(ARSendGameMessage).xdb"])
        self.assertEqual(reaction.findtext("EventName"), "port_gamepad")

    def test_launcher_services_share_process(self):
        app = ET.parse(ROOT / "android/app/AndroidManifest.xml").getroot().find("application")
        android = "{http://schemas.android.com/apk/res/android}"
        launcher = next(a for a in app.findall("activity") if a.get(android + "name") == ".Launcher")
        self.assertEqual(launcher.get(android + "process"), ":launcher")
        for service in app.findall("service"):
            self.assertEqual(service.get(android + "process"), launcher.get(android + "process"))

    def test_native_menu(self):
        source = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf8")
        start = source.index("void void_android_return_to_launcher(void);")
        end = source.index("\n#endif", start)
        compile_probe("launcher_menu", HARNESS, {"launcher_menu.h": source[start:end]})


if __name__ == "__main__":
    unittest.main()
