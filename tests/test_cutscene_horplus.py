"""Wide cutscene resources and the bounded legacy FOV adapter."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

from test_static_tls import compile_probe
from test_d3d_lifecycle import function

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_android
from editions import game_directory
import port_ui


HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[0x1000000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEMF(a) (*(float *)GPTR(a))
typedef struct { uint32_t words[16]; double fp[8]; } void_regs;
static void_regs machine;
#define g_esp machine.words[0]
#define g_st machine.fp
#define fp_f32(v) ((float)(v))
static void void_regs_save(void_regs *s) { *s=machine; }
static void void_regs_load(const void_regs *s) { machine=*s; }
static int void_vm_readable(uint32_t a,uint32_t n) { return a>=0x100 && (uint64_t)a+n<=sizeof memory; }
static int missing,adjustments;
static int void_dispatch_find(uint32_t a) { (void)a;return !missing; }
static uint32_t void_call_guest(uint32_t a,int n,const uint32_t *args,int pops) {
 assert(g_esp==0x10000);
 memset(machine.words+1,0xCD,sizeof machine.words-sizeof(uint32_t));
 if(a==0x008385A0) {assert(n==0&&pops);return 0x1000;}
 assert(a==0x00D119FC&&n==5&&!pops&&args[0]==0x1104&&args[2]==0x00F272C0&&args[3]==0x00F323A8);
 return 0x2000;
}
static uint32_t void_call_guest_this(uint32_t a,uint32_t self,int n,const uint32_t *args) {
 assert(a==0x00CF64F0&&self==0x4000&&n==1&&g_esp==0x10000);
 float fov;memcpy(&fov,args,4);
 g_st[0]=2*atan(tan(fov*3.141592653589793/360)*.75*MEMF(self)/MEMF(self+4))*180/3.141592653589793;
 ++adjustments;return 0;
}
#include "cutscene_impl.h"
static uint32_t bits(float v) {uint32_t r;memcpy(&r,&v,4);return r;}
static float value(uint32_t v) {float r;memcpy(&r,&v,4);return r;}
int main(void) {
 MEM32(0xFE719C)=0x1000;MEM32(0x1004)=0x1200;MEM32(0x1204)=0x100;
 MEM32(0x2000)=0x00E3261C;MEM32(0x218C)=0x3000;
 for(unsigned i=0;i<sizeof machine;++i)((uint8_t *)&machine)[i]=(uint8_t)(i*17+3);
 void_regs before=machine;
 const float widths[]={1024,1920,2400,2424};
 const float heights[]={768,1080,1080,1080};
 const float fovs[]={35,54.43f,90};
 for(unsigned i=0;i<4;++i)for(unsigned j=0;j<3;++j){
  MEMF(0x4000)=widths[i];MEMF(0x4004)=heights[i];
  uint32_t fov=bits(fovs[j]),r=void_cutscene_fov(0x3000,0x4000,fov,0x10000);
  double expected=2*atan(tan(fovs[j]*3.141592653589793/360)*.75*widths[i]/heights[i])*180/3.141592653589793;
  assert(fabs(value(r)-expected)<1e-4&&memcmp(&before,&machine,sizeof before)==0);
  assert(MEM32(0x3014)==0);
 }
 assert(adjustments==9);
 MEM32(0x2000)=0x00E3DD4C;assert(void_cutscene_fov(0x3000,0x4000,bits(35),0x10000)==bits(35));
 MEM32(0x2000)=0x00E3261C;assert(void_cutscene_fov(0x3004,0x4000,bits(35),0x10000)==bits(35));
 missing=1;assert(void_cutscene_fov(0x3000,0x4000,bits(35),0x10000)==bits(35));missing=0;
 MEMF(0x4004)=0;assert(void_cutscene_fov(0x3000,0x4000,bits(35),0x10000)==bits(35));
 MEMF(0x4004)=NAN;assert(void_cutscene_fov(0x3000,0x4000,bits(35),0x10000)==bits(35));
 assert(adjustments==9&&memcmp(&before,&machine,sizeof before)==0);
 puts("PASS legacy Hor+: original helper and current camera gate, 4:3 unchanged, no FOV/state writes, viewport and unavailable guards");
}
'''


class CutsceneHorplus(unittest.TestCase):
    def test_final_edition_archives_keep_dialogue_anchors_after_generic_migration(self):
        try:
            games = {edition: game_directory(edition) for edition in ("toe", "vanilla", "hof")}
        except (FileNotFoundError, ValueError):
            self.skipTest("Original edition resource configuration unavailable")
        if any(not game.is_dir() for game in games.values()):
            self.skipTest("Original edition resources unavailable")
        output_root = ROOT / "build/tests"
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="cutscene-final-", dir=output_root) as folder:
            root = Path(folder)
            (root / "port.json").write_text(json.dumps({
                "game_directory": str(games["toe"]),
                "editions": {edition: {"game_directory": str(game)} for edition, game in games.items()},
            }), encoding="utf-8")
            for edition, game in games.items():
                with self.subTest(edition=edition):
                    archive_path, _ = port_ui.build_port_ui_override(root, game, edition)
                    with zipfile.ZipFile(archive_path) as archive:
                        for panel, height in (("DialogueTop", 64), ("DialoguePanel", 256)):
                            prefix = f"UI/DialogueScreen/{panel}."
                            name = prefix + "(WindowSimple).xdb"
                            node = ET.fromstring(archive.read(name))
                            original = ET.fromstring(port_ui.source_resource(game, name, edition)[0])
                            self.assertEqual(node.tag, original.tag)
                            self.assertEqual(node.findtext("ClassTypeID"), original.findtext("ClassTypeID"))
                            self.assertEqual(node.find("Shared").get("href"), original.find("Shared").get("href"))
                            self.assertEqual(node.findtext("Placement/HorAllign/First"), "EPA_MARGIN")
                            self.assertEqual(node.findtext("Placement/HorAllign/Second"), "true")
                            for margin in ("LowerMargin", "UpperMargin"):
                                self.assertEqual(node.findtext(f"Placement/{margin}/First/x"), "0")
                                self.assertEqual(node.findtext(f"Placement/{margin}/Second"), "true")
                            self.assertEqual(node.findtext("Placement/Size/First/y"), original.findtext("Placement/Size/First/y"))
                            if panel == "DialoguePanel":
                                self.assertEqual(node.findtext("Placement/VerAllign/First"), "EPA_HIGH_END")
                                self.assertEqual(node.findtext("Placement/VerAllign/Second"), "true")
                                self.assertEqual(node.findtext("Placement/Position/First/y"), "0")
                            shared = ET.fromstring(archive.read(prefix + "(WindowSimpleShared).xdb"))
                            background_name = f"Port{panel}.(BackgroundSimpleScallingTexture).xdb"
                            self.assertEqual(shared.find("Background").get("href"),
                                             background_name + "#xpointer(/BackgroundSimpleScallingTexture)")
                            background = ET.fromstring(archive.read("UI/DialogueScreen/" + background_name))
                            self.assertEqual(background.tag, "BackgroundSimpleScallingTexture")
                            self.assertEqual(background.findtext("ClassTypeID"), "285694784")
                            self.assertEqual(background.findtext("Size/y"), str(height))
                            self.assertEqual(background.find("Texture").get("href"),
                                             panel + ".(Texture).xdb#xpointer(/Texture)")
                        for screen in ("DialogueScreen", "CutsceneScreen"):
                            window = ET.fromstring(archive.read(f"UI/{screen}.(WindowScreen).xdb"))
                            self.assertEqual(window.findtext("Placement/HorAllign/First"), "EPA_MARGIN")
                            self.assertEqual(window.findtext("Placement/VerAllign/First"), "EPA_MARGIN")
                        skip = ET.fromstring(archive.read("UI/DialogueScreen/SkipScene.(WindowMSButton).xdb"))
                        self.assertEqual(skip.findtext("Placement/HorAllign/First"), "EPA_HIGH_END")
                        self.assertEqual(skip.findtext("Placement/Position/First/x"), "-36")

    def test_native_adapter(self):
        source = (ROOT / "android/host/cutscene.c").read_text(encoding="utf-8")
        source = source.replace('#include "host.h"', '')
        compile_probe("cutscene_horplus", HARNESS, {"cutscene_impl.h": source})

    def test_only_original_legacy_load_is_adapted(self):
        source = (ROOT / "generated/game-x86/game_0310.c").read_bytes()
        result = build_android.cutscene_projection(source)
        self.assertEqual(result.count(b"edx = void_cutscene_fov("), 1)
        self.assertIn(b"MEM32(esp + 0x4C)", result)
        self.assertIn(b"RECOMP_CALL(sub_00CF7D90); /* 0x007D2120", result)
        other = (ROOT / "generated/game-x86/game_0278.c").read_bytes()
        self.assertEqual(build_android.cutscene_projection(other), other)

    def test_dialogue_layout_keeps_type_and_vertical_scale(self):
        game = json.loads((ROOT / "port.json").read_text())["game_directory"]
        if not Path(game).is_dir():
            self.skipTest("Original game resources unavailable")
        members = port_ui.cutscene_horplus(game)
        for name, data in members.items():
            node = ET.fromstring(data)
            if node.find("Placement") is None:
                continue
            original = ET.fromstring(port_ui.source_resource(game, name)[0])
            self.assertEqual(node.tag, original.tag)
            for path in ("Placement/Size/First/x", "Placement/Size/First/y"):
                self.assertEqual(node.findtext(path), original.findtext(path), name)
        for name in ("DialogueScreen", "CutsceneScreen"):
            node = ET.fromstring(members[f"UI/{name}.(WindowScreen).xdb"])
            self.assertEqual(node.findtext("HorAlign"), "ALIGN_SCREEN")
            self.assertEqual(node.findtext("VerAlign"), "ALIGN_SCREEN")
            self.assertEqual(node.findtext("Placement/HorAllign/First"), "EPA_MARGIN")
        for name in ("DialogueScreen", "CusceneScreen"):
            node = ET.fromstring(members[f"UI/{name}.(WindowScreenShared).xdb"])
            self.assertTrue(len(node.find("Children")))
            self.assertFalse(any("BlackBorder" in c.get("href", "") for c in node.find("Children")))
        button = ET.fromstring(members["UI/DialogueScreen/SkipScene.(WindowMSButton).xdb"])
        self.assertEqual(button.findtext("Placement/Position/First/x"), "-36")
        self.assertEqual(button.findtext("Placement/HorAllign/First"), "EPA_HIGH_END")
        for panel in ("DialogueTop", "DialoguePanel"):
            background = ET.fromstring(members[f"UI/DialogueScreen/Port{panel}.(BackgroundSimpleScallingTexture).xdb"])
            self.assertEqual(background.tag, "BackgroundSimpleScallingTexture")
            self.assertEqual(background.findtext("ClassTypeID"), "285694784")

    def test_cutscene_anchors_at_small_and_large_ui(self):
        game = json.loads((ROOT / "port.json").read_text())["game_directory"]
        if not Path(game).is_dir():
            self.skipTest("Original game resources unavailable")
        members = port_ui.cutscene_horplus(game)

        def placement(name, patched):
            def read(path):
                return ET.fromstring(members[path] if patched and path in members else
                                     port_ui.source_resource(game, path)[0])
            node = read(name)
            shared = read(str(Path(name).parent).replace("\\", "/") + "/" +
                          node.find("Shared").get("href").split("#")[0])
            values = {}
            for field in ("Position", "Size", "LowerMargin", "UpperMargin", "HorAllign", "VerAllign"):
                own = node.find("Placement/" + field)
                values[field] = (own if own.findtext("Second") == "true" else
                                 shared.find("Placement/" + field)).find("First")
            modes = {"EPA_LOW_END": 0, "ERA_CENTER": 1, "EPA_HIGH_END": 2, "EPA_MARGIN": 3}
            return [modes[values["HorAllign"].text], modes[values["VerAllign"].text]] + [
                float(values[field].findtext(axis)) for field in
                ("Position", "Size", "LowerMargin", "UpperMargin") for axis in ("x", "y")]

        names = [("DialogueTop", "WindowSimple"), ("DialoguePanel", "WindowSimple"),
                 ("SkipScene", "WindowMSButton"), ("HeroName", "WindowTextView"),
                 ("HeroText", "WindowTextView"), ("HeroFace", "WindowSimple")]
        rows = []
        for name, kind in names:
            path = f"UI/DialogueScreen/{name}.({kind}).xdb"
            old, new = placement(path, False), placement(path, True)
            rows.append("{{" + ",".join(map(str, old)) + "},{" + ",".join(map(str, new)) + "}}")
        source = (ROOT / "android/host/touch_scale.c").read_text(encoding="utf-8")
        helpers = "\n".join(function(source, name) for name in
                            ("static float scale_native_position(", "static float scale_size(",
                             "static float scale_anchor_shift("))
        harness = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
/* HELPERS */
static const double items[][2][10] = {/* ITEMS */};
int main(void) {
 for(unsigned i=0;i<6;++i)for(int axis=0;axis<2;++axis){
  const double *old=items[i][0],*now=items[i][1];float span=axis?768.0f:1024.0f;
  float before=scale_native_position((uint32_t)old[axis],0,span,(float)old[2+axis],(float)old[6+axis],(float)old[4+axis]);
  float size=scale_size((uint32_t)now[axis],span,(float)now[4+axis],(float)now[6+axis],(float)now[8+axis]);
  float after=scale_native_position((uint32_t)now[axis],0,span,(float)now[2+axis],(float)now[6+axis],size);
  assert(fabs(before-after)<.01f);
 }
 const float scales[]={50,100,200};
 for(unsigned k=0;k<3;++k){
  float view[2]={1724*100/scales[k],768*100/scales[k]};
  float frame[2]={fmaxf(1024,view[0]),fmaxf(768,view[1])};
  for(unsigned i=0;i<6;++i)for(int axis=0;axis<2;++axis){
   const double *now=items[i][1];uint32_t mode=(uint32_t)now[axis];
   float size=scale_size(mode,frame[axis],(float)now[4+axis],(float)now[6+axis],(float)now[8+axis]);
   float p=scale_native_position(mode,0,frame[axis],(float)now[2+axis],(float)now[6+axis],size);
   float shift=scales[k]>100?scale_anchor_shift(mode,p,size,0,frame[axis],view[axis]):0;
   if(axis==1){
    if(i==0)assert(p+shift==0);
    if(i==1)assert(fabsf(p+shift+size-view[1])<1.01f);
    assert(p+shift>=0&&p+shift+size<=view[1]+1.01f);
   }else if(i==2){
    assert(fabsf(p+shift+size-(view[0]-36))<1.01f);
   }else if(i==5){
    assert(p+shift==19);
   }
  }
 }
 puts("PASS cutscene resource layout with production placement/anchors: original 4:3 geometry, UI50/100/200 top/bottom panels and controls, original portrait/skip margins");
}
'''.replace("/* HELPERS */", helpers).replace("/* ITEMS */", ",\n".join(rows))
        compile_probe("cutscene_scale", harness, {})


if __name__ == "__main__":
    unittest.main()
