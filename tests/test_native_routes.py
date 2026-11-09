"""The scene router must catch every route and retain the canonical original."""
from pathlib import Path
import json
import subprocess
import sys
import unittest

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import native_routes as routes
from native_routes import SCENE_ENTRIES, SCENE_ROUTER, apply_native_routes


# Independently proved image entries, in ToE/Vanilla/HoF order. Keep expected
# routes separate from the production catalog, including the two new groups.
EXPECTED = {
    "scene": (("00B1C300", "00957950", "004F2C80"), "void_scene_native_dispatch", "void_scene_native_commands"),
    "grid": (("00C059B0", "00A44AD0", "00807790"), "void_grid_native_dispatch", "void_grid_native_visit"),
    "observer": (("00C48A30", "00BB9AE0", "009EE700"), "void_observer_native_dispatch", "void_observer_native_forward"),
    "vector": (("004FA1A0", "00459020", "0047B260"), "void_vector_native_dispatch", "void_vector_native_visit"),
    "skin": (("00C6B0B0", "008C86D0", "00A48AA0"), "void_skin_native_dispatch", "void_skin_native_combine"),
    "curve_word": (("00BF5F30", "00A92870", "00B8D900"), "void_curve_native_word_dispatch", "void_curve_native_word"),
    "curve_scalar": (("00BF60E0", "00A92A20", "00B8DAB0"), "void_curve_native_scalar_dispatch", "void_curve_native_scalar"),
    "skin_math_one": (("00C68210", "008C52B0", "00A45B90"), "void_skin_math_one_dispatch", "void_skin_math_one"),
    "skin_math_two": (("00C682D0", "008C5370", "00A45C50"), "void_skin_math_two_dispatch", "void_skin_math_two"),
    "skin_math_three": (("00C683E0", "008C5480", "00A45D60"), "void_skin_math_three_dispatch", "void_skin_math_three"),
    "reference_object": (("004FA280", "00459100", "0047B340"), "void_reference_native_object_dispatch", "void_reference_native_object"),
    "reference_tile": (("00C05AC0", "00A44BE0", "008078A0"), "void_reference_native_tile_dispatch", "void_reference_native_tile"),
}


class NativeRoutesTest(unittest.TestCase):
    def test_late_targets_leave_original_body_masks_fp_and_host_fallback_unchanged(self):
        for edition, original in SCENE_ENTRIES.items():
            with self.subTest(edition=edition):
                body = ("void " + original + "(void) {\n    original_body();\n}\n").encode()
                source = body + ("void caller(void) {\n"
                    " X87_GPUSH(a,b); RECOMP_CALL_P(" + original + ", 0x17u, 0x17u, 0, 0x12345678u); X87_GPOP(c,d);\n"
                    " RECOMP_CALL(" + original + ");\n RECOMP_TAIL_P(" + original + ", 0xFFu, 0);\n"
                    " RECOMP_CALL(sub_12345678);\n}\n").encode()
                new, calls, entries = apply_native_routes(source, edition, module="game")
                self.assertEqual((calls, entries), (3, 0))
                self.assertIn(body, new)
                self.assertIn(b"0x17u, 0x17u, 0, 0x12345678u); X87_GPOP(c,d)", new)
                self.assertIn(b"RECOMP_CALL(sub_12345678)", new)
                self.assertEqual(apply_native_routes(new, edition, module="game"), (new, 0, 0))
                self.assertEqual(apply_native_routes(source, edition, module="host"), (source, 0, 0))
                # A DLL's direct callback to the game cannot bypass the router.
                self.assertEqual(apply_native_routes(source, edition, module="granny2"), (new, 3, 0))
                self.assertEqual(new.count(b"extern void " + SCENE_ROUTER.encode() + b"(void);"), 1)

    def test_dispatch_identity_is_exact_and_fail_closed(self):
        for edition, original in SCENE_ENTRIES.items():
            address = original[4:]
            source = ("const entry table[]={{0x" + address + "u," + original + "},{0x12345678u,sub_12345678}};\n").encode()
            new, calls, entries = apply_native_routes(source, edition, module="fmod", dispatch=True)
            self.assertEqual((calls, entries), (0, 1))
            self.assertIn(("{0x" + address + "u," + SCENE_ROUTER + "}").encode(), new)
            self.assertEqual(apply_native_routes(new, edition, module="fmod", dispatch=True), (new, 0, 0))
            for bad in (b"const entry table[]={};", source + source, source.replace(original.encode(), b"sub_12345678", 1)):
                with self.assertRaises(ValueError):
                    apply_native_routes(bad, edition, module="fmod", dispatch=True)
        with self.assertRaises(ValueError):
            apply_native_routes(b"", "unknown", module="game")

    def test_compiled_same_and_different_units_dispatch_recursion_and_original_modes(self):
        for edition, original in SCENE_ENTRIES.items():
            address = original[4:]
            prefix = """
#include <assert.h>
#include <stdint.h>
typedef struct { uint32_t va; void (*fn)(void); } entry;
extern int mode,depth,original_calls,native_calls,router_calls;
#define RECOMP_CALL(f) f()
#define RECOMP_CALL_P(f,p,r,fl,s) f()
#define RECOMP_TAIL_P(f,p,fl) f()
"""
            body = ("void " + original + "(void) { ++original_calls; if (depth) { --depth; RECOMP_CALL_P(" + original + ",0x17,0x17,0,0); } }\n"
                    "void same_tu(void) { RECOMP_CALL(" + original + "); }\n"
                    "void tail_tu(void) { RECOMP_TAIL_P(" + original + ",0xFF,0); }\n").encode()
            body, calls, _ = apply_native_routes(body, edition, module="game")
            self.assertEqual(calls, 3)
            other, count, _ = apply_native_routes(("void " + original + "(void);\nvoid other_tu(void) { RECOMP_CALL_P(" + original + ",0x17,0x17,0,0); }\n").encode(), edition, module="game")
            self.assertEqual(count, 1)
            table, _, entries = apply_native_routes(("void " + original + "(void);\nconst entry table[]={{0x" + address + "u," + original + "}};\n").encode(), edition, module="fmod", dispatch=True)
            self.assertEqual(entries, 1)
            router = ("int mode,depth,original_calls,native_calls,router_calls;\nvoid " + original + "(void);\n"
                      "void " + SCENE_ROUTER + "(void) { ++router_calls; if(mode==1) ++native_calls; else " + original + "(); }\n")
            main = ("void same_tu(void),other_tu(void),tail_tu(void); extern const entry table[];\n"
                    "int main(void) { for(mode=0;mode<=2;++mode) { for(int route=0;route<4;++route) {\n"
                    "depth=2;original_calls=native_calls=router_calls=0;\n"
                    "if(route==0)same_tu();else if(route==1)other_tu();else if(route==2)tail_tu();else table[0].fn();\n"
                    "assert(router_calls==(mode==1?1:3));assert(native_calls==(mode==1));assert(original_calls==(mode==1?0:3));}\n"
                    "depth=0;original_calls=native_calls=router_calls=0;" + original + "();assert(original_calls==1&&!native_calls&&!router_calls); }return 0;}\n")
            compile_probe("native-routes-" + edition, prefix + router + main,
                          {"same.c": prefix + body.decode(), "other.c": prefix + other.decode(), "table.c": prefix + table.decode()},
                          extra_flags=("same.c", "other.c", "table.c"))


class NativeCatalogTest(unittest.TestCase):
    def expected(self, edition):
        index = ("toe", "vanilla", "hof").index(edition)
        return [(addresses[index], router, algorithm) for addresses, router, algorithm in EXPECTED.values()]

    def test_catalog_selected_body_ids_and_explicit_source_policy(self):
        self.assertEqual(set(routes.ROUTE_GROUPS), set(EXPECTED))
        self.assertEqual(routes.NATIVE_SOURCES, {"scene_native.c", "grid_native.c", "observer_native.c",
            "vector_native.c", "skin_native.c", "leaves_native.c", "curves_native.c", "skin_math_native.c", "object_refs_native.c"})
        for edition in ("toe", "vanilla", "hof"):
            records = routes.algorithm_entries(edition)
            self.assertEqual(len(records), {"toe": 274, "vanilla": 18, "hof": 19}[edition])
            self.assertEqual(sum(r["global_route"] for r in records), 268 if edition == "toe" else 12)
            contextual = {"grid_field", "vector_field", "reference_tile_cast", "reference_tile_assign", "reference_release", "reference_virtual_base"}
            if edition == "hof":
                contextual.add("reference_hof_base")
            self.assertEqual({r["symbol"] for r in records if not r["global_route"]}, contextual)
            self.assertEqual(len({r["address"] for r in records}), len(records) - (edition == "toe"))
            for name, (addresses, router, algorithm) in EXPECTED.items():
                group = routes.ROUTE_GROUPS[name]
                index = ("toe", "vanilla", "hof").index(edition)
                self.assertEqual(group["entries"][edition], "sub_" + addresses[index])
                self.assertEqual((group["router"], group["algorithm"]), (router, algorithm))
                self.assertEqual(sum(r["address"] == addresses[index] and r["symbol"] == algorithm for r in records), 1)
                self.assertFalse(any(r["symbol"] == router for r in records))
        host = ["-O2", "-DRECOMP_TRACE", "-DRECOMP_PLAIN_MEMORY=0", "-DVOID_ANDROID_APP"]
        normal = routes.native_diagnostic_flags(host, ["-DRECOMP_PLAIN_MEMORY", "-DRECOMP_GUEST_STATE_SEPARATE"])
        self.assertNotIn("-DRECOMP_TRACE", normal)
        self.assertIn("-DRECOMP_PLAIN_MEMORY=0", normal)
        self.assertNotIn("-DRECOMP_PLAIN_MEMORY", normal)
        self.assertNotIn("-DRECOMP_GUEST_STATE_SEPARATE", normal)
        diagnostics = ["-DRECOMP_TRACE", "-DRECOMP_CALL_DIAG", "-DRECOMP_PROTOCOL_CHECK"]
        self.assertEqual(routes.native_diagnostic_flags(host, diagnostics), [f for f in host if f != "-DRECOMP_TRACE"] + diagnostics)

    def test_all_entry_routes_are_real_compiled_calls_and_dispatch_with_direct_original_fallback(self):
        for edition in ("toe", "vanilla", "hof"):
            with self.subTest(edition=edition):
                expected = self.expected(edition)
                if edition == "toe":
                    expected += [(va, "void_leaf_dispatch_" + va, "void_leaf_native_" + va) for va in routes.LEAF_ENTRIES]
                count = len(expected)
                self.assertEqual(count, 268 if edition == "toe" else 12)
                prefix = """
#include <assert.h>
#include <stdint.h>
typedef struct {uint32_t va; void(*fn)(void);} entry;
extern int mode, original_calls, native_calls, router_calls;
#define RECOMP_CALL(f) f()
#define RECOMP_CALL_P(f,p,r,fl,s) f()
#define RECOMP_TAIL_P(f,p,fl) f()
"""
                definitions = "".join("void sub_" + va + "(void) {++original_calls;}\n" for va, _, _ in expected)
                caller = "void calls_all(void) {\n" + "".join(
                    " RECOMP_CALL(sub_" + va + "); RECOMP_CALL_P(sub_" + va + ",0x17u,0x17u,0,0xABCDu); RECOMP_TAIL_P(sub_" + va + ",0x17u,0);\n"
                    for va, _, _ in expected) + "}\n"
                changed, calls, entries = routes.apply_native_routes((definitions + caller).encode(), edition, module="game", groups=routes.NATIVE_GROUPS)
                self.assertEqual((calls, entries), (count * 3, 0))
                self.assertIn(definitions.encode(), changed)
                self.assertEqual(routes.apply_native_routes(changed, edition, module="game", groups=routes.NATIVE_GROUPS), (changed, 0, 0))
                table = ("const entry table[]={" + ",".join("{0x" + va + "u,sub_" + va + "}" for va, _, _ in expected) + "};\n").encode()
                dispatch, calls, entries = routes.apply_native_routes(table, edition, module="fmod", dispatch=True, groups=routes.NATIVE_GROUPS)
                self.assertEqual((calls, entries), (0, count))
                for invalid in (table + table, table.replace(("{0x" + expected[0][0] + "u,sub_" + expected[0][0] + "}").encode(), b"{0x12345678u,sub_12345678}")):
                    with self.assertRaises(ValueError):
                        routes.apply_native_routes(invalid, edition, module="fmod", dispatch=True, groups=routes.NATIVE_GROUPS)
                declarations = "".join("void sub_" + va + "(void);\n" for va, _, _ in expected)
                host = "int mode, original_calls, native_calls, router_calls;\n" + declarations + "".join(
                    "void " + router + "(void) {++router_calls; if(mode==1) ++native_calls; else sub_" + va + "();}\n"
                    for va, router, _ in expected)
                self.assertEqual(routes.apply_native_routes(host.encode(), edition, module="host", groups=routes.NATIVE_GROUPS), (host.encode(), 0, 0))
                main = """void calls_all(void); extern const entry table[];
int main(void) {
 for(mode=0;mode<=2;mode++) {
  original_calls=native_calls=router_calls=0; calls_all();
  assert(router_calls==COUNT*3 && original_calls==(mode==1?0:COUNT*3) && native_calls==(mode==1?COUNT*3:0));
  original_calls=native_calls=router_calls=0; for(int i=0;i<COUNT;i++) table[i].fn();
  assert(router_calls==COUNT && original_calls==(mode==1?0:COUNT) && native_calls==(mode==1?COUNT:0));
 }
 return 0;
}
""".replace("COUNT", str(count))
                compile_probe("native-all-routes-" + edition, prefix + host + main,
                              {"calls.c": prefix + changed.decode(), "table.c": prefix + declarations + dispatch.decode()},
                              extra_flags=("calls.c", "table.c"))


if __name__ == "__main__":
    unittest.main()
