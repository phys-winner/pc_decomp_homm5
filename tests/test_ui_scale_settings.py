"""The port's settings live in the game's own options (port_settings.c): native
registration and frame pump, the JNI seeds, and the Activity's persistence."""
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from test_touch_controls import ROOT, JAVA
from test_d3d_lifecycle import function
from test_static_tls import compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import port_ui

JAVA_FIXTURE = r'''
import java.lang.ref.WeakReference;
import java.util.*;
public class PortSettingsCheck {
    static class SharedPreferences {
        final Map<String,Object> values=new HashMap<>();
        int applies;
        float getFloat(String key,float fallback) {
            Object value=values.get(key);
            if(value==null) return fallback;
            if(!(value instanceof Float)) throw new ClassCastException(key);
            return (Float)value;
        }
        Editor edit() {return new Editor(this);}
    }
    static class Editor {
        final SharedPreferences owner;final Map<String,Object> pending=new HashMap<>();
        Editor(SharedPreferences owner) {this.owner=owner;}
        Editor putFloat(String key,float value) {pending.put(key,value);return this;}
        void apply() {owner.values.putAll(pending);owner.applies++;}
    }
    private final SharedPreferences preferences=new SharedPreferences();
    private static WeakReference<PortSettingsCheck> currentActivity=new WeakReference<>(null);
    static float nativeUi,nativeRender,nativeCamera;
    static int nativeCalls;
    private static void nativeUiScale(float scale) {nativeUi=scale;nativeCalls++;}
    private static void nativeRenderScale(float scale) {nativeRender=scale;nativeCalls++;}
    private static void nativeCameraSensitivity(float value) {nativeCamera=value;nativeCalls++;}
    /* ACTUAL_METHODS */
    void startSeeds() {
        nativeCalls=0;
        /* ACTUAL_SEEDS */
        assert nativeCalls==3;
    }
    static Map<String,Object> saved(float ui,float render,float camera) {
        Map<String,Object> map=new HashMap<>();
        map.put("ui_scale",ui);map.put("render_scale",render);map.put("camera_sensitivity",camera);return map;
    }
    public static void main(String[] args) {
        PortSettingsCheck check=new PortSettingsCheck();
        /* First start: nothing saved, the defaults seed the game's variables. */
        check.startSeeds();assert nativeUi==1&&nativeRender==1&&nativeCamera==1;
        /* No live Activity: the native notification is dropped. */
        onPortSetting(0,1.5f);assert check.preferences.applies==0;
        currentActivity=new WeakReference<>(check);
        /* port_settings.c's indices: 0 UI, 1 render, 2 camera. */
        onPortSetting(0,1.25f);onPortSetting(1,.6f);onPortSetting(2,2f);
        assert check.preferences.values.equals(saved(1.25f,.6f,2f))&&check.preferences.applies==3;
        onPortSetting(3,.7f);onPortSetting(-1,.7f);onPortSetting(0,Float.NaN);onPortSetting(1,Float.POSITIVE_INFINITY);
        assert check.preferences.values.equals(saved(1.25f,.6f,2f))&&check.preferences.applies==3;
        /* The next start seeds what the game last reported. */
        check.startSeeds();assert nativeUi==1.25f&&nativeRender==.6f&&nativeCamera==2f;
        /* A value stored with another type (an old build) falls back to the default. */
        check.preferences.values.put("render_scale",70);
        check.startSeeds();assert nativeUi==1.25f&&nativeRender==1&&nativeCamera==2f;
        /* Only the current Activity persists. */
        PortSettingsCheck next=new PortSettingsCheck();currentActivity=new WeakReference<>(next);
        onPortSetting(2,.5f);
        assert next.preferences.values.get("camera_sensitivity").equals(.5f)&&check.preferences.values.get("camera_sensitivity").equals(2f);
        System.out.println("PASS actual Activity port settings: onPortSetting persists ui/render/camera by native index, ignores unknown/non-finite/no Activity; startup seeds saved values, defaults 1 and type fallback");
    }
}
'''

NATIVE_HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define VOID_ANDROID_APP 1
static uint8_t memory[0x40000];
#define GPTR(a) (memory + (uint32_t)(a))
#define MEM8(a) (*(uint8_t *)GPTR(a))
#define MEM16(a) (*(uint16_t *)GPTR(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEMF(a) (*(float *)GPTR(a))
static uint32_t g_eax, g_ebx, g_ecx, g_edx, g_esi, g_edi, g_ebp, g_esp = 0x30000;
#define RECOMP_RETADDR 0xFEEDF00Du
#define PUSH32(sp, val) do { (sp) -= 4; MEM32(sp) = (uint32_t)(val); } while (0)
typedef int pthread_mutex_t;
#define PTHREAD_MUTEX_INITIALIZER 0
static int pthread_mutex_lock(pthread_mutex_t *m) { assert(!*m); *m = 1; return 0; }
static int pthread_mutex_unlock(pthread_mutex_t *m) { assert(*m); *m = 0; return 0; }
static uint32_t heap = 0x10000;
static int live_blocks;
static uint32_t void_galloc(uint32_t size) {
    uint32_t at = heap; heap += (size + 15) & ~15u; assert(heap < 0x20000);
    memset(GPTR(at), 0, size); ++live_blocks; return at;
}
static void void_gfree(uint32_t va) { assert(va >= 0x10000 && va < heap); --live_blocks; }
static void void_log(const char *format, ...) { (void)format; }
static void void_fatal(const char *format, ...) { fprintf(stderr, "%s\n", format); abort(); }
static float ui_applied = -1, render_applied = -1;
static int ui_sets, render_sets;
static void void_touch_set_scale(float scale) { ui_applied = scale; ++ui_sets; }
static void void_touch_set_render_scale(float scale) { render_applied = scale; ++render_sets; }
static int notifications, notified_which[64];
static float notified_value[64];
void void_android_settings_changed(int which, float value) {
    assert(notifications < 64); notified_which[notifications] = which; notified_value[notifications++] = value;
}
/* The engine's variable registration (0x00C11400): ECX name {begin,end,cap},
 * EDX value copier, stack: return, storage, default, profile level; RET 0xC. */
typedef struct { char name[64]; uint32_t storage, copier, level; float value; char text[32]; } registration;
static registration registered[16];
static int registrations;
void sub_00C11400_lifted(void) {
    assert(MEM32(g_esp) == RECOMP_RETADDR && registrations < 16);
    registration *r = &registered[registrations++];
    uint32_t name = g_ecx, begin = MEM32(name), end = MEM32(name + 4);
    assert(end >= begin && end - begin < sizeof r->name && MEM32(name + 8) == end + 1 && !MEM8(end));
    memcpy(r->name, GPTR(begin), end - begin); r->name[end - begin] = 0;
    r->copier = g_edx; r->storage = MEM32(g_esp + 4); r->level = MEM32(g_esp + 12);
    uint32_t value = MEM32(g_esp + 8), wide = MEM32(value + 4), wide_end = MEM32(value + 8);
    r->value = MEMF(value);
    assert(wide_end >= wide && !((wide_end - wide) & 1) && (wide_end - wide) / 2 < sizeof r->text);
    assert(MEM32(value + 12) == wide_end + 2 && !MEM16(wide_end));
    for (uint32_t i = 0; i < (wide_end - wide) / 2; ++i) { assert(MEM16(wide + 2 * i) < 128); r->text[i] = (char)MEM16(wide + 2 * i); }
    r->text[(wide_end - wide) / 2] = 0;
    g_esp += 16;
    /* The callee's register file, as the first caller must get it back. */
    g_eax = 0x1000u + (uint32_t)registrations; g_ecx = 0xC000u + (uint32_t)registrations; g_edx = 0xD000u + (uint32_t)registrations;
    g_ebx = 0xB000u + (uint32_t)registrations; g_esi = 0x5000u + (uint32_t)registrations;
    g_edi = 0xE000u + (uint32_t)registrations; g_ebp = 0xF000u + (uint32_t)registrations;
}
#include "port_settings_impl.h"
static uint32_t engine_name;
static void engine_registers(const char *name) {
    size_t length = strlen(name);
    memcpy(GPTR(engine_name + 16), name, length + 1);
    MEM32(engine_name) = engine_name + 16; MEM32(engine_name + 4) = engine_name + 16 + (uint32_t)length;
    MEM32(engine_name + 8) = engine_name + 17 + (uint32_t)length;
    MEMF(0x2F000) = 30; MEM32(0x2F004) = 0x2F100; MEM32(0x2F008) = 0x2F104; MEM32(0x2F00C) = 0x2F106;
    MEM16(0x2F100) = '3'; MEM16(0x2F102) = '0'; MEM16(0x2F104) = 0;
    uint32_t entry = g_esp;
    PUSH32(g_esp, 2); PUSH32(g_esp, 0x2F000); PUSH32(g_esp, 0x2F010); PUSH32(g_esp, RECOMP_RETADDR);
    g_ecx = engine_name; g_edx = 0x00499630u;
    sub_00C11400();
    assert(g_esp == entry);
}
static int notified(int which, float value) {
    return notifications && notified_which[notifications - 1] == which && notified_value[notifications - 1] == value;
}
static const float option_values[4][16] = {/* OPTION_VALUES */};
static const int option_counts[4] = {/* OPTION_COUNTS */};
int main(void) {
    static const char *const names[4] = {"port_ui_scale", "port_render_scale", "port_camera_sensitivity", "port_fps_limit"};
    for (int i = 0; i < 3; ++i) assert(port_defaults[i] == 1.0f);
    assert(port_defaults[3] == 60.0f && void_port_fps_limit() == 60.0f);
    /* Java's saved values seed the defaults; invalid seeds are ignored. */
    void_port_set_default(0, 1.25f); void_port_set_default(1, 0.6f); void_port_set_default(2, 2.0f);
    void_port_set_default(3, 1.5f); void_port_set_default(-1, 1.5f); void_port_set_default(0, NAN);
    void_port_set_default(1, 0); void_port_set_default(2, -1); void_port_set_default(2, INFINITY);
    assert(port_defaults[0] == 1.25f && port_defaults[1] == 0.6f && port_defaults[2] == 2.0f);
    /* Before the game registers its variables: the seeded default, and no pump. */
    assert(void_port_camera_sensitivity() == 2.0f);
    void_port_settings_pump(); assert(!ui_sets && !render_sets && !notifications);
    /* The first engine registration also registers the port's four profile floats. */
    engine_name = void_galloc(64); int blocks = live_blocks;
    engine_registers("net_timeout");
    assert(registrations == 5 && !strcmp(registered[0].name, "net_timeout") && registered[0].storage == 0x2F010);
    assert(g_eax == 0x1001 && g_ecx == 0xC001 && g_edx == 0xD001 && g_ebx == 0xB001);
    assert(g_esi == 0x5001 && g_edi == 0xE001 && g_ebp == 0xF001);
    static const char *const texts[4] = {"1.25", "0.6", "2", "60"};
    for (int i = 0; i < 4; ++i) {
        const registration *r = &registered[1 + i];
        assert(!strcmp(r->name, names[i]) && r->level == 2 && r->copier == 0x00499630u);
        assert(r->storage == port_storage + 4u * (uint32_t)i && r->value == port_defaults[i] && !strcmp(r->text, texts[i]));
        assert(MEMF(r->storage) == port_defaults[i]);
    }
    assert(live_blocks == blocks + 1);     /* storage only: names, texts and scratch are freed */
    engine_registers("net_port");
    assert(registrations == 6 && !strcmp(registered[5].name, "net_port") && g_eax == 0x1006);
    /* The frame pump applies and reports each change once, clamped to its range. */
    void_port_settings_pump();
    assert(ui_sets == 1 && ui_applied == 1.25f && render_sets == 1 && render_applied == 0.6f && notifications == 3);
    assert(notified_which[0] == 0 && notified_value[0] == 1.25f && notified_which[1] == 1 && notified_value[1] == 0.6f);
    assert(notified(2, 2.0f) && void_port_camera_sensitivity() == 2.0f);
    void_port_settings_pump(); assert(ui_sets == 1 && render_sets == 1 && notifications == 3);
    MEMF(port_storage) = 1.5f; void_port_settings_pump();
    assert(ui_sets == 2 && ui_applied == 1.5f && render_sets == 1 && notifications == 4 && notified(0, 1.5f));
    MEMF(port_storage + 4) = 5; void_port_settings_pump();
    assert(render_sets == 2 && render_applied == 1.0f && notifications == 5 && notified(1, 1.0f));
    MEMF(port_storage + 4) = 2; void_port_settings_pump(); assert(render_sets == 2 && notifications == 5);
    MEMF(port_storage + 8) = 0.1f; void_port_settings_pump();
    assert(ui_sets == 2 && render_sets == 2 && notifications == 6 && notified(2, 0.25f) && void_port_camera_sensitivity() == 0.25f);
    MEMF(port_storage + 8) = 9; assert(void_port_camera_sensitivity() == 4.0f);
    MEMF(port_storage + 8) = NAN; assert(void_port_camera_sensitivity() == 2.0f);
    void_port_settings_pump(); assert(notifications == 7 && notified(2, 2.0f));
    MEMF(port_storage) = 0.1f; void_port_settings_pump(); assert(ui_applied == 0.5f && notified(0, 0.5f));
    MEMF(port_storage + 4) = 0.1f; void_port_settings_pump(); assert(render_applied == 0.25f && notified(1, 0.25f));
    /* Every value the options pages offer reaches the game unclamped. */
    for (int which = 0; which < 4; ++which) for (int i = 0; i < option_counts[which]; ++i) {
        float value = option_values[which][i];
        MEMF(port_storage + 4u * (uint32_t)which) = value; void_port_settings_pump();
        if (which == 0) assert(ui_applied == value);
        if (which == 1) assert(render_applied == value);
        if (which == 2) assert(void_port_camera_sensitivity() == value);
        if (which < 3) assert(port_applied[which] == value);
        else assert(void_port_fps_limit() == value);
    }
    MEMF(port_storage + 12) = NAN; assert(void_port_fps_limit() == 60.0f);
    MEMF(port_storage + 12) = INFINITY; assert(void_port_fps_limit() == 60.0f);
    MEMF(port_storage + 12) = -1; assert(void_port_fps_limit() == 0.0f);
    MEMF(port_storage + 12) = 1; assert(void_port_fps_limit() == 30.0f);
    MEMF(port_storage + 12) = 1000; assert(void_port_fps_limit() == 240.0f);
    assert(!port_lock);
    puts("PASS actual port settings: Java seeds, first registration adds port_ui/render/camera as level-2 profile floats with %g defaults (caller registers kept), later ones pass through, pump applies/reports each change once with UI/render/camera clamps and every options value");
    return 0;
}
'''


class PortSettingsTest(unittest.TestCase):
    def test_additional_category_and_launcher_buttons(self):
        game = __import__("json").loads((ROOT / "port.json").read_text(encoding="utf8"))["game_directory"]
        original, _ = port_ui.source_resource(game, port_ui.UICONSTS)
        tree = ET.fromstring(port_ui.patch_uiconsts(original))
        categories = tree.findall("GameOptions/Categories/Item")
        self.assertEqual([c.findtext("ID") for c in categories], ["game", "video_audio", "port_additional"])
        for category in categories[:2]:
            self.assertFalse(any(o.findtext("ID", "").startswith("port_") for o in category.findall(".//Options/Item")))
        self.assertEqual([o.findtext("ID") for o in categories[2].findall(".//Options/Item")], [o[0] for o in port_ui.OPTIONS])
        self.assertEqual(len(categories[2].findall("Pages/Item")), 2)  # Native two-column templates have valid initial widths.
        self.assertEqual(tree.findtext(".//Options/Item[ID='tooltip_delay']/DefaultValue1"), "0")
        members = port_ui.launcher_buttons(game)
        for name, visible in (("PortOptionsLauncher", "false"), ("PortExitLauncher", "true")):
            button = ET.fromstring(members[f"UI/{name}.(WindowMSButton).xdb"])
            self.assertEqual(button.findtext("Visible"), visible)
            self.assertEqual(button.findtext("Placement/Size/First/x"), "122")
            self.assertEqual(len(button.find("GameMessageReactions")), 0)
            self.assertIn("PortLauncher.(UISDirectRunReaction)", button.find("ButtonStates/Item/CommandsOnEnterState/Commands/Item").get("href"))
        self.assertEqual(port_ui.texts()["UI/Consts/GameOptions/PortAdditional.txt"].decode("utf16"), "Дополнительные")

    def test_activity_persists_and_seeds(self):
        source = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        methods = function(source, "    private float savedFloat(")
        methods += function(source, "    private static void onPortSetting(").replace("GameActivity activity", "PortSettingsCheck activity")
        start = source.index("        nativeUiScale(savedFloat(")
        end = source.index("\n", source.index("        nativeCameraSensitivity(savedFloat(")) + 1
        seeds = source[start:end]
        self.assertEqual(len(re.findall(r"\bnative\w+\(savedFloat\(", seeds)), 3, seeds)
        self.assertLess(start, source.index("        nativeStart("))    # seeded before the game starts
        out = ROOT / "build/java-port-settings-check"
        out.mkdir(parents=True, exist_ok=True)
        fixture = out / "PortSettingsCheck.java"
        fixture.write_text(JAVA_FIXTURE.replace("    /* ACTUAL_METHODS */", methods).replace("        /* ACTUAL_SEEDS */", seeds), encoding="utf8")
        subprocess.run([str(JAVA / "javac.exe"), "--release", "8", "-encoding", "UTF-8", "-d", str(out), str(fixture)], check=True)
        subprocess.run([str(JAVA / "java.exe"), "-ea", "-cp", str(out), "PortSettingsCheck"], check=True)

    def test_native_registration_and_pump(self):
        source = (ROOT / "android/host/port_settings.c").read_text(encoding="utf-8")
        for name in ("host.h", "touch.h"):
            source = source.replace(f'#include "{name}"\n', "")
        options = {option[1]: option for option in port_ui.OPTIONS}
        names = ("port_ui_scale", "port_render_scale", "port_camera_sensitivity", "port_fps_limit")
        self.assertEqual(set(options), set(names))
        rows, counts = [], []
        for name in names:
            values = options[name][7]
            self.assertEqual(values[options[name][8]], 60.0 if name == "port_fps_limit" else 1.0)
            rows.append("{" + ",".join(f"{value!r}f" for value in values) + "}")
            counts.append(str(len(values)))
        harness = NATIVE_HARNESS.replace("/* OPTION_VALUES */", ",".join(rows)).replace("/* OPTION_COUNTS */", ",".join(counts))
        compile_probe("port_settings", harness, {"port_settings_impl.h": source})

    def test_frame_limit_option_labels(self):
        option = next(row for row in port_ui.OPTIONS if row[0] == "port_fps_limit")
        self.assertEqual(option[7], (30.0, 45.0, 60.0, 0.0))
        text = port_ui.texts()
        prefix = "UI/Consts/GameOptions/Port_port_fps_limit/"
        self.assertEqual(text[prefix + "Item02.txt"].decode("utf-16"), "60 кадров/с")
        self.assertEqual(text[prefix + "Item03.txt"].decode("utf-16"), "Частота экрана")
        self.assertIn(b"<GlobalVar1>port_fps_limit</GlobalVar1>", port_ui.option_xml(option))

    def test_loading_logo_layout(self):
        window = b'''<WindowSimple><Name>Logo</Name><Placement>
        <Position><First><x>2</x><y>0</y></First><Second>true</Second></Position>
        <Size><First><x>1024</x><y>768</y></First><Second>true</Second></Size>
        </Placement></WindowSimple>'''
        shared = b'<WindowSimpleShared><Background href="old"/><Children/></WindowSimpleShared>'
        with patch.object(port_ui, "source_resource", side_effect=[(window,"base"),(shared,"base")]):
            members = port_ui.loading_logo("unused")
        prefix = "UI/pwlscreen/"
        logo = ET.fromstring(members[prefix + "Logo.(WindowSimple).xdb"])
        width = int(logo.findtext("Placement/Size/First/x"))
        height = int(logo.findtext("Placement/Size/First/y"))
        y = int(logo.findtext("Placement/Position/First/y")) + (768-height)/2
        self.assertEqual(width/height, 1024/768)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y+height, 490)  # Above the map title/description.
        self.assertEqual(logo.findtext("Name"), "Logo")
        background = ET.fromstring(members[prefix + "PortLogo.(BackgroundSimpleScallingTexture).xdb"])
        self.assertEqual(background.findtext("Size/y"), "768")  # Original artwork crop.
        self.assertIn("FrontA2", background.find("Texture").get("href"))

    def test_jni_and_frame_wiring(self):
        java = (ROOT / "android/app/src/org/homm5/port/GameActivity.java").read_text(encoding="utf8")
        native = (ROOT / "android/host/android_main.c").read_text(encoding="utf-8")
        seeds = {}
        for name in ("nativeUiScale", "nativeRenderScale", "nativeCameraSensitivity"):
            self.assertRegex(java, r"private static native void " + name + r"\(float \w+\);")
            jni = re.search(r"JNIEXPORT void JNICALL Java_org_homm5_port_GameActivity_" + name + r"\(JNIEnv \*env, jobject self, jfloat (\w+)\)\n\{(.*?)\n\}", native, re.S)
            self.assertIsNotNone(jni, name)
            seeds[name] = re.search(r"void_port_set_default\((\d), " + jni[1] + r"\);", jni[2])[1]
        self.assertEqual(seeds, {"nativeUiScale": "0", "nativeRenderScale": "1", "nativeCameraSensitivity": "2"})
        callback = re.search(r"void void_android_settings_changed\(int which, float value\)\n\{(.*?)\n\}", native, re.S)[1]
        self.assertIn('GetStaticMethodID(env, (jclass)activity, "onPortSetting", "(IF)V")', callback)
        self.assertIn("CallStaticVoidMethod(env, (jclass)activity, callback, (jint)which, (jfloat)value)", callback)
        self.assertIn("    private static void onPortSetting(int which, float value) {", java)
        # The engine's registration binds to the native override; every frame pump applies changes.
        sys.path.insert(0, str(ROOT / "tools"))
        import build_android
        self.assertIn("sub_00C11400", build_android.NATIVE_OVERRIDES)
        pumps = (ROOT / "android/host/touch_queue.c").read_text(encoding="utf-8")
        for pump in ("void void_touch_pump(void)", "void void_touch_render_frame_pump(void)"):
            start = pumps.index(pump)
            self.assertIn("void_port_settings_pump();", pumps[start:pumps.index("\n}\n", start)], pump)


if __name__ == "__main__":
    unittest.main()
