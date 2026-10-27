"""Check legacy loading-screen placement against real original resource schemas."""
from functools import lru_cache
import json
import posixpath
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from test_d3d_lifecycle import function
from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
from editions import game_directory
import port_ui


class LoadingLayoutTest(unittest.TestCase):
    def test_original_legacy_schema_and_native_wide_placement(self):
        helpers = (ROOT / "android/host/touch_scale.c").read_text(encoding="utf8")
        helpers = "\n".join(function(helpers, name) for name in (
            "static float scale_native_position(", "static float scale_size("))
        for edition in ("vanilla", "hof"):
            with self.subTest(edition=edition):
                try:
                    game = game_directory(edition)
                except (FileNotFoundError, ValueError):
                    self.skipTest("Original legacy game configuration unavailable")
                if not game.is_dir():
                    self.skipTest("Original legacy game resources unavailable")
                original_source = port_ui.source_resource
                @lru_cache(maxsize=None)
                def resource(folder, name, edition):
                    return original_source(folder, name, edition)
                with patch.object(port_ui, "source_resource", side_effect=resource):
                    members = port_ui.loading_logo(game, edition)

                def read(name):
                    return ET.fromstring(members.get(name) or resource(game, name, edition)[0])
                def layout(name):
                    node = read(name)
                    href = node.find("Shared").get("href").split("#")[0]
                    shared_name = href.lstrip("/") if href.startswith("/") else posixpath.normpath(posixpath.dirname(name) + "/" + href)
                    shared = read(shared_name)
                    values = {}
                    for field in ("HorAllign", "VerAllign", "Position", "Size", "LowerMargin", "UpperMargin"):
                        value = node.find("Placement/" + field)
                        values[field] = (value if value.findtext("Second") == "true" else
                                         shared.find("Placement/" + field)).find("First")
                    modes = {"EPA_LOW_END": 0, "ERA_CENTER": 1, "EPA_HIGH_END": 2, "EPA_MARGIN": 3}
                    return [modes[values[axis].text] for axis in ("HorAllign", "VerAllign")] + [
                        float(values[field].findtext(axis)) for field in ("Position", "Size", "LowerMargin", "UpperMargin")
                        for axis in ("x", "y")]
                names = ("UI/PWLScreen.(WindowScreen).xdb", "UI/pwlscreen/Main.(WindowSimple).xdb",
                         "UI/pwlscreen/Logo.(WindowSimple).xdb")
                rows = [layout(name) for name in names]
                self.assertEqual([row[0] for row in rows], [3, 1, 1])
                self.assertEqual(rows[2][1], 1)
                self.assertEqual(rows[1][4:6], [1024, 768])
                self.assertEqual(rows[2][4:6], [640, 480])
                for name in names[:2]:
                    before = ET.fromstring(resource(game, name, edition)[0])
                    after = read(name)
                    for field in ("ClassTypeID", "Shared", "Name", "Visible", "Enabled"):
                        old, new = before.find(field), after.find(field)
                        self.assertEqual(None if old is None else ET.tostring(old), None if new is None else ET.tostring(new))
                rows = ",\n".join("{" + ",".join(map(str, row)) + "}" for row in rows)
                harness = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
/* HELPERS */
static const double windows[][10]={/* ROWS */};
int main(void) {
 const float widths[]={1024,1365,1707,2400};
 for(unsigned n=0;n<4;++n) {
  float origin=0,span=widths[n],positions[3],sizes[3];
  for(unsigned i=0;i<3;++i) {
   const double *w=windows[i];sizes[i]=scale_size((uint32_t)w[0],span,(float)w[4],(float)w[6],(float)w[8]);
   positions[i]=scale_native_position((uint32_t)w[0],origin,span,(float)w[2],(float)w[6],sizes[i]);
   origin=positions[i];span=sizes[i];
  }
  assert(positions[0]==0&&sizes[0]==widths[n]);
  assert(sizes[1]==1024&&sizes[2]==640&&fabsf((positions[1]+512)-widths[n]*.5f)<=1);
  assert(fabsf((positions[2]+320)-widths[n]*.5f)<=1&&positions[2]>=0&&positions[2]+640<=widths[n]);
  assert(positions[1]+25>=0&&positions[1]+25+971<=widths[n]);
 }
 const double *logo=windows[2];float height=scale_size((uint32_t)logo[1],768,(float)logo[5],(float)logo[7],(float)logo[9]);
 float y=scale_native_position((uint32_t)logo[1],0,768,(float)logo[3],(float)logo[7],height);
 assert(height==480&&y==0&&y+height<=490&&windows[2][4]/height==4.0/3.0);
 puts("PASS original legacy loading schemas and actual native placement: full-width root, centered1024 content, preserved640x480 art above captions, centered progress frame, 4:3 and wide1707 canvas without stretching");
}
'''.replace("/* HELPERS */", helpers).replace("/* ROWS */", rows)
                compile_probe("loading_layout_" + edition, harness, {})


if __name__ == "__main__":
    unittest.main()
