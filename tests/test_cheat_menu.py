"""Run the production cheat actions with the original-game boundaries mocked."""
import re
import subprocess
import sys
import unittest

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe
from test_touch_controls import JAVA


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "touch.h"
static uint8_t memory[0x10000];
#define MEM8(p) memory[(uint32_t)(p)]
#define MEM32(p) (*(uint32_t *)(memory+(uint32_t)(p)))
#define VLOG(...) ((void)0)
enum {SCREEN_MENU,SCREEN_ADVENTURE};
static uint32_t selected=0x1000,hero=0x5000;
static int enabled=1,allow_enable=1,callback=-1,calls,enables,handler_ok=1;
static uint32_t called_method,called_self,called_count,called_args[3];
static int void_vm_readable(uint32_t p,uint32_t n){return p>=0x100&&(uint64_t)p+n<=sizeof memory;}
static uint32_t read32(uint32_t p){return void_vm_readable(p,4)?MEM32(p):0;}
static uint32_t current_screen(void){return selected;}
static int screen_kind(uint32_t screen){return screen==0x1000?SCREEN_ADVENTURE:SCREEN_MENU;}
int void_port_console_enabled(void){return enabled;}
static void void_android_cheats(uint32_t generation,int state){assert(generation);callback=state;}
static uint32_t void_call_guest(uint32_t va,int n,const uint32_t *args,int stdcall_pops){
 assert(va==0x58CA00&&n==1&&args[0]==selected&&stdcall_pops==1);enables++;
 MEM8(0x2074)=(uint8_t)allow_enable;return 0;
}
static uint32_t void_call_guest_this(uint32_t va,uint32_t self,int n,const uint32_t *args){
 if(va==0x603860){assert(self==0x2000&&!n);return hero;}
 assert(n>=0&&n<=3);calls++;called_method=va;called_self=self;called_count=n;
 if(n)memcpy(called_args,args,n*4);return (uint32_t)handler_ok;
}
/* ACTUAL */
static void action(int which,int value){
 void_touch_event event={.kind=TOUCH_CHEAT_ACTION,.x=(float)which,.y=(float)value,
     .dx=(float)cheat_target.generation,.scale=1};cheats_action(&event);
}
int main(void){
 MEM32(0x10A0)=0x3000;MEM32(0x15F4)=0x2000;
 cheats_show();assert(callback==0&&!enables);
 action(3,1000);assert(callback==0&&!calls);
 allow_enable=0;action(0,0);assert(enables==1&&callback==2&&!MEM8(0x2074));
 allow_enable=1;action(0,0);assert(enables==2&&callback==1&&MEM8(0x2074));
 struct {int action,value;uint32_t method,count,a,b,c;} cases[]={
  {1,0,0x602AD0,0,0,0,0},{2,1000000,0x602B30,1,1000000,0,0},
  {3,10000,0x602C90,1,10000,0,0},{4,0,0x602510,1,1,0,0},
  {5,0,0x602DF0,2,5,5,0},{6,1,0x602060,3,1,0,100},
  {6,16,0x602060,3,8,1,100},{6,24,0x602060,3,8,2,100},
  {7,12,0x602570,1,12,0,0},{8,0,0x58DE80,1,0,0,0},{9,0,0x602B80,0,0,0,0}};
 for(unsigned i=0;i<sizeof cases/sizeof *cases;++i){
  cheats_show();int before=calls;action(cases[i].action,cases[i].value);
  assert(calls==before+1&&callback==3&&called_method==cases[i].method&&called_count==cases[i].count);
  assert(called_self==(cases[i].action==8?0x1000u:0x2000u));
  uint32_t expected[]={cases[i].a,cases[i].b,cases[i].c};assert(!memcmp(called_args,expected,called_count*4));
  action(cases[i].action,cases[i].value);assert(calls==before+1);
 }
 cheats_show();int before=calls;
 action(2,1);action(3,-1);action(3,1000001);action(6,0);action(6,25);action(7,13);action(10,0);
 assert(calls==before);
 enabled=0;action(1,0);assert(calls==before);enabled=1;
 hero=0x5100;action(4,0);assert(calls==before&&callback==4);hero=0x5000;
 selected=0x1100;action(1,0);assert(calls==before);selected=0x1000;
 MEM32(0x10A0)=0x3100;action(1,0);assert(calls==before);MEM32(0x10A0)=0x3000;
 MEM32(0x15F4)=0x2100;action(1,0);assert(calls==before);MEM32(0x15F4)=0x2000;
 void_touch_event stale={.x=1,.dx=(float)cheat_target.generation-1,.scale=1};cheats_action(&stale);assert(calls==before);
 handler_ok=0;action(4,0);assert(callback==4&&calls==before+1);
 puts("PASS cheats: real enable state, original handlers, all army upgrades, rejected values, stale map/hero/menu, opt-out and failure");
}
'''


class CheatMenuTest(unittest.TestCase):
    def test_actual_dialog_choices_and_late_dismissal(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf-8")
        methods = "\n".join(function(source, "    private " + signature) for signature in (
            "static String cheatText(", "void showCheatDialog(", "android.app.AlertDialog.Builder cheatBuilder(",
            "void confirmCheat(", "void showCheats(", "void showCheatOptions("))
        methods = methods.replace("android.app.AlertDialog", "Dialog").replace("android.widget.Toast", "Toast")
        methods = methods.replace("android.R.style.Theme_Material_Dialog_Alert", "1")
        harness = r'''
import java.util.*;
public class CheatDialogsCheck {
    static String language="ru";
    static String edition="toe";
    String gameEdition(){return edition;}
    static final int T_CANCEL=3;
    static int generation,action,value,calls;
    static String toast;
    static final List<Runnable> pending=new ArrayList<>();
    Dialog cheatDialog;
    static class Touch {void requestFocus(){}}
    Touch touch=new Touch();
    void releaseAll(){} void hideSystemUi(){}
    static String text(int id){assert id==T_CANCEL;return cheatText("Cancel","Отмена");}
    static void nativeCheatAction(int g,int a,int v){generation=g;action=a;value=v;calls++;}
    interface Click {void run(Dialog dialog,int which);}
    interface Dismiss {void run(Dialog dialog);}
    static class Dialog {
        String title,message;String[] items;Click item,positive;Dismiss listener;boolean shown;
        void setOnDismissListener(Dismiss d){listener=d;}
        void show(){shown=true;}
        void dismiss(){if(shown){shown=false;if(listener!=null)pending.add(()->listener.run(this));}}
        void choose(int index){assert shown;item.run(this,index);dismiss();}
        void apply(){assert shown&&positive!=null;positive.run(this,0);dismiss();}
        static class Builder {
            Dialog d=new Dialog();
            Builder(CheatDialogsCheck a,int theme){assert a!=null&&theme==1;}
            Builder setTitle(String s){d.title=s;return this;}
            Builder setMessage(String s){d.message=s;return this;}
            Builder setItems(String[] s,Click c){d.items=s;d.item=c;return this;}
            Builder setPositiveButton(String s,Click c){d.positive=c;return this;}
            Builder setNegativeButton(String s,Click c){assert c==null;return this;}
            Dialog create(){return d;}
        }
    }
    static class Toast {
        static final int LENGTH_LONG=1;
        static Toast makeText(CheatDialogsCheck a,String text,int length){toast=text;return new Toast();}
        void show(){}
    }
    /* ACTUAL */
    static void drain(){while(!pending.isEmpty())pending.remove(0).run();}
    static void sent(int g,int a,int v){assert generation==g&&action==a&&value==v;}
    public static void main(String[] unused){
        CheatDialogsCheck c=new CheatDialogsCheck();
        c.showCheats(7,0);assert c.cheatDialog.message.equals("Включить читы для текущей карты?");
        c.cheatDialog.dismiss();drain();assert calls==0&&c.cheatDialog==null;
        c.showCheats(7,0);c.cheatDialog.apply();drain();sent(7,0,0);
        c.showCheats(8,1);assert c.cheatDialog.items.length==9;
        c.cheatDialog.choose(5);Dialog factions=c.cheatDialog;drain();
        assert c.cheatDialog==factions&&factions.items.length==8;
        factions.choose(7);Dialog upgrades=c.cheatDialog;drain();
        assert c.cheatDialog==upgrades&&upgrades.items.length==3;
        upgrades.choose(2);Dialog confirm=c.cheatDialog;drain();
        assert c.cheatDialog==confirm&&confirm.message.contains("100");confirm.apply();drain();sent(8,6,24);
        c.showCheats(9,1);c.cheatDialog.choose(1);drain();
        assert c.cheatDialog.title.contains("обнулятся");c.cheatDialog.choose(2);drain();
        assert c.cheatDialog.message.contains("обнулятся");c.cheatDialog.apply();drain();sent(9,2,1000000);
        c.showCheats(10,1);c.cheatDialog.choose(2);drain();c.cheatDialog.choose(0);drain();sent(10,3,1000);
        c.showCheats(11,1);c.cheatDialog.choose(6);drain();
        assert c.cheatDialog.items.length==12;c.cheatDialog.choose(11);drain();sent(11,7,12);
        for(int id:new int[]{1,4,5,8,9}){
            c.showCheats(20+id,1);c.cheatDialog.choose(id-1);drain();
            if(id==1||id==9){assert c.cheatDialog.message.contains("заменены");c.cheatDialog.apply();drain();}
            sent(20+id,id,0);
        }
        c.showCheats(40,3);assert toast.equals("Готово");
        c.showCheats(40,4);assert toast.contains("Выберите своего героя");
        language="en";c.showCheats(41,0);assert c.cheatDialog.message.equals("Enable cheats for the current map?");
        System.out.println("PASS actual cheat dialogs: enable/decline, all actions, gold/army disclosure, twelve skills, submenu lifetime, RU/EN");
    }
}
'''.replace("/* ACTUAL */", methods)
        out = ROOT / "build/java-cheat-menu-check"
        out.mkdir(parents=True, exist_ok=True)
        path = out / "CheatDialogsCheck.java"
        path.write_text(harness, encoding="utf-8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(path)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "CheatDialogsCheck"], check=True)

    def test_original_actions_and_stale_dialog_guards(self):
        source = (ROOT / "android/host/touch_engine.c").read_text(encoding="utf-8")
        target = re.search(r"static struct \{ uint32_t generation, screen, root, controller, hero; \} cheat_target;", source)
        self.assertIsNotNone(target)
        actual = target[0] + "\n" + function(source, "static void cheats_show(") + function(source, "static void cheats_action(")
        compile_probe("cheat_menu", HARNESS.replace("/* ACTUAL */", actual),
                      {"touch.h": (ROOT / "android/host/touch.h").read_text()})

    def test_original_legacy_cheat_ret_abi(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from port_patches import load_contract
        for edition, chunk, army, spells, flag in (
                ("vanilla", "game_0154.c", "005D0880", "005D13C0", "0x60"),
                ("hof", "game_0152.c", "005D3940", "005D4630", "0x68")):
            text = (ROOT / "generated" / edition / "game-x86" / chunk).read_text()
            mapping = load_contract(edition)["addresses"]
            self.assertEqual(mapping["00602060"], army)
            self.assertEqual(mapping["00602510"], spells)
            for address, count in ((army, 8 if edition == "vanilla" else 12), (spells, 0)):
                original = function(text, "void sub_" + address + "(")
                ret = re.findall(r'/\* 0x[0-9A-F]{8}: ret\s*(.*?) \*/', original)
                self.assertTrue(ret)
                self.assertEqual({int(value, 0) if value else 0 for value in ret}, {count})
                self.assertRegex(original, r'cmp byte ptr \[e\w+ \+ ' + flag + r'\]')

    def test_legacy_original_handlers_and_parameter_counts(self):
        sys.path.insert(0, str(ROOT / "tools"))
        from port_patches import adapt_host_source, load_contract
        import port_ui
        for edition in ("vanilla", "hof"):
            path, _ = adapt_host_source(ROOT / "android/host/touch_engine.c",
                                       ROOT / "build/tests" / ("legacy-cheats-" + edition), edition)
            source = path.read_text()
            start = source.index("static struct { uint32_t generation, screen, root, controller, hero; } cheat_target;")
            actual = source[start:source.index("int void_touch_text_focus(", start)]
            harness = HARNESS.replace("0x10A0", "0x1098").replace("0x15F4", "0x156C" if edition == "vanilla" else "0x1578")
            harness = harness.replace("0x2074", "0x2060" if edition == "vanilla" else "0x2068")
            harness = harness.replace("{4,0,0x602510,1,1,0,0}", "{4,0,0x602510,0,0,0,0}")
            if edition == "vanilla":
                harness = harness.replace("{6,1,0x602060,3,1,0,100}",
                                          "{6,1,0x602060,2,0,0,0},{6,3,0x602060,2,2,0,0},{6,6,0x602060,2,5,0,0}")
            harness = harness.replace("{6,16,0x602060,3,8,1,100},{6,24,0x602060,3,8,2,100}",
                                      "{6,14,0x602060,2,5,1,0}" if edition == "vanilla" else "{6,15,0x602060,3,7,1,100}")
            harness = harness.replace("action(6,25);", "action(6,25);action(6,8);action(6,17);")
            mapping = load_contract(edition)["addresses"]
            harness = re.sub(r'0x([0-9a-fA-F]+)', lambda m:
                             '0x' + mapping.get(f'{int(m[1], 16):08X}', m[1]), harness)
            compile_probe("cheat-menu-" + edition, harness.replace("/* ACTUAL */", actual),
                          {"touch.h": (ROOT / "android/host/touch.h").read_text()})
            self.assertIn("OnJog-Scenario", source)
            legacy = {row[0]: row for row in port_ui.options(edition)}
            self.assertEqual(legacy["port_touch_cursor"][3], "Показывать курсор")
            self.assertIn("книги приключений", legacy["port_console"][4])


if __name__ == "__main__":
    unittest.main()
