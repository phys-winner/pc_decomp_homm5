"""Reproduce Pixel's JoinFleeBox geometry through each actual scale adapter."""
import re
import sys
import unittest
from test_static_tls import ROOT, compile_probe
from test_d3d_lifecycle import function

sys.path.insert(0, str(ROOT / "tools"))
import port_patches


class ScaledModalsTest(unittest.TestCase):
    def test_actual_modal_measurement_and_profile_anchor_for_every_edition(self):
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                source = ROOT / "android/host/touch_scale.c"
                if edition != "toe":
                    source, _ = port_patches.adapt_host_source(source, ROOT / "build/tests" / ("scaled-modal-" + edition), edition)
                text = source.read_text(encoding="utf-8")
                types = re.search(r"typedef struct \{\n    float view_w, view_h;.*?\} scale_pass;", text, re.S)[0]
                signatures = ("static uint32_t scale_read32(", "static uint32_t scale_placement(",
                    "static float scale_native_position(", "static int scale_near(", "static float scale_clamp(",
                    "static float scale_anchor_shift(", "static int scale_rect(", "static int scale_is_root(",
                    "static float scale_size(", "static int scale_covers(", "static int scale_named(",
                    "static int scale_element(", "static void scale_place(", "static void scale_anchor(", "static int scale_fits(")
                code = types + "\n" + "\n".join(function(text, s) for s in signatures)
                addresses = {} if edition == "toe" else port_patches.load_contract(edition)["addresses"]
                layout = addresses.get("00487990", "00487990")
                flags = ["/DROOT_LAYOUT=0x" + layout,
                         "/DROOT_REPOSITION=" + ("0x00488330" if edition == "toe" else "0"),
                         "/DMODAL_HEAD=" + ("0x14C" if edition == "toe" else "0x144")]
                fixture = (ROOT / "tests/fixtures/scaled_modal_probe.c").read_text().replace("/* ACTUAL */", code)
                compile_probe("scaled-modal-" + edition, fixture, {}, flags)


if __name__ == "__main__":
    unittest.main()
