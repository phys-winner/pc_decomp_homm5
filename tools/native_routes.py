"""Late routing for admitted manual algorithms and runtime command hooks.

Run after call-protocol/x87 transforms, on generated C only. Host fallback
calls are deliberately outside this transform. No linker wrapping is needed.
"""
import re

SCENE_ENTRIES = {
    "toe": "sub_00B1C300",
    "vanilla": "sub_00957950",
    "hof": "sub_004F2C80",
}
SCENE_ROUTER = "void_scene_native_dispatch"
# Both native spellbook/ability callers are direct calls, so a dispatch-table
# hook alone cannot intercept them. Keep the original table entry and body;
# the host wrapper resolves the currently installed hook at execution time.
COMBAT_DIRECT_ENTRIES = {"toe": "sub_00542420", "vanilla": "sub_00514870", "hof": "sub_00529AB0"}
COMBAT_DIRECT_ROUTER = "void_touch_combat_direct_dispatch"
ROUTE_GROUPS = {
    "scene": {"source":"scene_native.c", "router":SCENE_ROUTER, "algorithm":"void_scene_native_commands",
              "entries":SCENE_ENTRIES, "contextual":[]},
    "grid": {"source":"grid_native.c", "router":"void_grid_native_dispatch", "algorithm":"void_grid_native_visit",
             "entries":{"toe":"sub_00C059B0","vanilla":"sub_00A44AD0","hof":"sub_00807790"},
             "contextual":[("grid_field",{"toe":"00C05A90","vanilla":"00A44BB0","hof":"00807870"})]},
    "observer": {"source":"observer_native.c", "router":"void_observer_native_dispatch", "algorithm":"void_observer_native_forward",
                 "entries":{"toe":"sub_00C48A30","vanilla":"sub_00BB9AE0","hof":"sub_009EE700"}, "contextual":[]},
    "vector": {"source":"vector_native.c", "router":"void_vector_native_dispatch", "algorithm":"void_vector_native_visit",
               "entries":{"toe":"sub_004FA1A0","vanilla":"sub_00459020","hof":"sub_0047B260"},
               "contextual":[("vector_field",{"toe":"004FA250","vanilla":"004590D0","hof":"0047B310"})]},
    "skin": {"source":"skin_native.c", "router":"void_skin_native_dispatch", "algorithm":"void_skin_native_combine",
             "entries":{"toe":"sub_00C6B0B0","vanilla":"sub_008C86D0","hof":"sub_00A48AA0"}, "contextual":[]},
    "curve_word": {"source":"curves_native.c", "router":"void_curve_native_word_dispatch", "algorithm":"void_curve_native_word",
                   "entries":{"toe":"sub_00BF5F30","vanilla":"sub_00A92870","hof":"sub_00B8D900"}, "contextual":[]},
    "curve_scalar": {"source":"curves_native.c", "router":"void_curve_native_scalar_dispatch", "algorithm":"void_curve_native_scalar",
                     "entries":{"toe":"sub_00BF60E0","vanilla":"sub_00A92A20","hof":"sub_00B8DAB0"}, "contextual":[]},
    "skin_math_one": {"source":"skin_math_native.c", "router":"void_skin_math_one_dispatch", "algorithm":"void_skin_math_one",
                      "entries":{"toe":"sub_00C68210","vanilla":"sub_008C52B0","hof":"sub_00A45B90"}, "contextual":[]},
    "skin_math_two": {"source":"skin_math_native.c", "router":"void_skin_math_two_dispatch", "algorithm":"void_skin_math_two",
                      "entries":{"toe":"sub_00C682D0","vanilla":"sub_008C5370","hof":"sub_00A45C50"}, "contextual":[]},
    "skin_math_three": {"source":"skin_math_native.c", "router":"void_skin_math_three_dispatch", "algorithm":"void_skin_math_three",
                        "entries":{"toe":"sub_00C683E0","vanilla":"sub_008C5480","hof":"sub_00A45D60"}, "contextual":[]},
    "reference_object": {"source":"object_refs_native.c", "router":"void_reference_native_object_dispatch", "algorithm":"void_reference_native_object",
                         "entries":{"toe":"sub_004FA280","vanilla":"sub_00459100","hof":"sub_0047B340"},
                         "contextual":[
                             ("reference_tile_cast",{"toe":"00C05B10","vanilla":"00A44C30","hof":"008078F0"}),
                             ("reference_tile_assign",{"toe":"00731290","vanilla":"006CD9F0","hof":"006AF170"}),
                             ("reference_release",{"toe":"00611AA0","vanilla":"00961930","hof":"00756120"}),
                             ("reference_virtual_base",{"toe":"0061F290","vanilla":"0065B5D0","hof":"004C04D0"}),
                             ("reference_hof_base",{"hof":"00456050"})]},
    "reference_tile": {"source":"object_refs_native.c", "router":"void_reference_native_tile_dispatch", "algorithm":"void_reference_native_tile",
                       "entries":{"toe":"sub_00C05AC0","vanilla":"sub_00A44BE0","hof":"sub_008078A0"}, "contextual":[]},
}
# Explicit root-admitted whitelist from the observed ToE world census. No legacy aliases.
LEAF_ENTRIES = (
    '0044FF40', '00454300', '00454360', '00454380', '0048EBF0', '004B4690', '004F88A0', '004F8BE0',
    '004FB7A0', '004FB7B0', '004FB7C0', '004FBE80', '00500C10', '00500C40', '00500D30', '00500D90',
    '00500DE0', '00500DF0', '0050E140', '00513250', '005AE110', '005AE970', '0061F290', '00620240',
    '00633CC0', '00720E90', '00724930', '00724940', '0072BEE0', '0076B5F0', '00782CF0', '007D0600',
    '007DD5A0', '00819270', '00819280', '0081AD10', '0081BF70', '008478A0', '0087B9E0', '0087B9F0',
    '0087BA00', '0087BA10', '0087BA20', '0087BA40', '0087BBE0', '00882AC0', '00885BA0', '00896CD0',
    '0089AD50', '0089B0C0', '0089B110', '0089B120', '008B1E10', '0098C470', '0098C490', '0098C4C0',
    '0098CF90', '0099E4C0', '0099E4D0', '0099E590', '009DBD80', '009FB860', '00A192B0', '00A19DB0',
    '00A19F80', '00A1A0E0', '00A367B0', '00A3A140', '00A3D220', '00A44C70', '00A4D980', '00A83AA0',
    '00A951F0', '00AC1880', '00ACB380', '00AF7E80', '00AF7F40', '00AF8160', '00AFFEB0', '00AFFEC0',
    '00B24660', '00B24670', '00B4C0F0', '00B4C370', '00B4C420', '00B5A9D0', '00B5AA30', '00B5AAD0',
    '00B5AC10', '00B5AC30', '00B5ACA0', '00B5ACE0', '00B5ACF0', '00B6BB00', '00B7F240', '00BA03D0',
    '00BC2970', '00C2FD30', '00C2FE30', '00C2FE70', '00C2FEF0', '00C37370', '00C3A590', '00C3A5A0',
    '00C3A5D0', '00C61A70', '00C61AB0', '00C61B10', '00C68520', '00C685C0', '00C98940', '00CBC7E0',
    '00CBCA20', '00CBE280', '00CBE290', '00CBE2A0', '00CBE390', '00CD8850', '00CE0810', '00CE6760',
    '00CECF10', '00CF2AA0', '00CF8A60', '00CFC430', '00D088A0', '0044D4E0', '0048EB50', '0048F160',
    '004B1540', '004BB090', '004D8AD0', '004D8F00', '004D8F50', '004D8F70', '004DDEE0', '004DDF10',
    '004DDF20', '004F8ED0', '004FB840', '004FBA20', '00500BF0', '00500C00', '00500EE0', '0050EFC0',
    '0050FF50', '0053DBC0', '00559C60', '0055B7E0', '007C32B0', '008478F0', '00847920', '0087BBD0',
    '00886CA0', '0089AD00', '0089B0A0', '008ACDC0', '008AE0C0', '008AE2C0', '008AEAF0', '008AEB30',
    '008AEB40', '008B77C0', '0093F960', '0098CFA0', '009B19E0', '009B2B60', '009B30B0', '009B30F0',
    '009D5060', '00A2D770', '00A69F00', '00A6AB80', '00A6B060', '00AE67F0', '00AF7E70', '00AF7EA0',
    '00AF7EB0', '00AF7EC0', '00AF7EE0', '00AF7F00', '00AF7F30', '00AF80E0', '00AF80F0', '00AF8100',
    '00AF8110', '00AF8120', '00AF8150', '00B096E0', '00B10A20', '00B14070', '00B26660', '00B2A1F0',
    '00B4B5C0', '00B4C0D0', '00B4C0E0', '00B4C120', '00B4CE20', '00B59EA0', '00B5A9E0', '00B5A9F0',
    '00B5AA20', '00B5AA80', '00B5ABA0', '00B5ABF0', '00B72460', '00B83860', '00B8F4E0', '00BC2940',
    '00BE6330', '00BE7B20', '00BE8400', '00BEB6C0', '00BEB700', '00BEB880', '00BF0B90', '00BF0D70',
    '00BFF420', '00C3FEC0', '00C419F0', '00C594A0', '00C594B0', '00C61AD0', '00C752D0', '00C75300',
    '00C75330', '00C75360', '00C7E7C0', '00C7E810', '00C7EBC0', '00C7EFC0', '00C7F010', '00C7F0D0',
    '00C7F1B0', '00C7F230', '00C7F4E0', '00C7F690', '00C82FB0', '00C830A0', '00C831D0', '00C83260',
    '00C97C10', '00C97C20', '00C99920', '00C99950', '00C999B0', '00C99E70', '00C99E80', '00CA6560',
    '00CAB580', '00CB7F20', '00CB7F30', '00CB94C0', '00CBE380', '00CE6750', '00CE6790', '00CF2A90',
)
NATIVE_GROUPS = (*ROUTE_GROUPS, "leaves")
NATIVE_SOURCES = frozenset([row["source"] for row in ROUTE_GROUPS.values()] + ["leaves_native.c"])
DIAGNOSTIC_MODES = frozenset(("RECOMP_TRACE","RECOMP_CALL_DIAG","RECOMP_PROTOCOL_CHECK"))
CALL_TARGET = re.compile(rb"\bRECOMP_(?:CALL_P|TAIL_P|CALL)\(\s*(sub_[0-9A-F]{8})(?=\s*[,\)])")
DISPATCH_ENTRY = re.compile(rb"\{\s*0x([0-9A-Fa-f]{8})[uU]?\s*,\s*([A-Za-z_][A-Za-z_0-9]*)\s*\}")


def algorithm_entries(edition):
    """Selected bodies only; contextual IDs do not imply global entry routing."""
    records=[]
    for group in ROUTE_GROUPS.values():
        records.append(dict(module="game",address=group["entries"][edition][4:],symbol=group["algorithm"],
                            source=group["source"],manual_algorithmic_port=True,global_route=True))
        for symbol, addresses in group["contextual"]:
            if edition not in addresses:
                continue
            records.append(dict(module="game",address=addresses[edition],symbol=symbol,
                                source=group["source"],manual_algorithmic_port=True,global_route=False))
    if edition == "toe":
        records.extend(dict(module="game",address=address,symbol="void_leaf_native_"+address,
                            source="leaves_native.c",manual_algorithmic_port=True,global_route=True)
                       for address in LEAF_ENTRIES)
    return records


def native_diagnostic_flags(host_flags, generated_flags):
    """Match trace/protocol observability; storage-model flags are not changed."""
    def mode(flag):
        match=re.fullmatch(r"-[DU]([A-Za-z_][A-Za-z_0-9]*)(?:=.*)?",flag)
        return match[1] if match else None
    return [f for f in host_flags if mode(f) not in DIAGNOSTIC_MODES] + [
        f for f in generated_flags if mode(f) in DIAGNOSTIC_MODES]


def apply_native_routes(text, edition, *, module, dispatch=False, groups=("scene",)):
    """Return (bytes, direct-call-count, dispatch-count); fail on bad table rows.

    The canonical body/prototype, masks, site IDs and x87 spill/fill code remain
    byte-identical. Only generated guest call targets or the merged table entry
    change. Passing a host module is a no-op, preserving direct original calls.
    """
    if edition not in SCENE_ENTRIES:
        raise ValueError("Unknown native-route edition: " + str(edition))
    if not isinstance(text, bytes):
        raise TypeError("Native routes require generated source bytes")
    if len(set(groups)) != len(groups) or any(name not in ROUTE_GROUPS and name != "leaves" for name in groups):
        raise ValueError("Invalid native route group selection")
    targets={ROUTE_GROUPS[name]["entries"][edition].encode():ROUTE_GROUPS[name]["router"].encode() for name in groups if name != "leaves"}
    if not dispatch:
        targets[COMBAT_DIRECT_ENTRIES[edition].encode()] = COMBAT_DIRECT_ROUTER.encode()
    if "leaves" in groups and edition == "toe":
        targets.update({("sub_"+address).encode():("void_leaf_dispatch_"+address).encode() for address in LEAF_ENTRIES})
    observed={original:[] for original in targets}
    used=set()
    calls = entries = 0
    if not dispatch and module != "host":
        def call(match):
            nonlocal calls
            if match[1] not in targets:
                return match[0]
            router=targets[match[1]]
            used.add(router)
            calls += 1
            return match[0][:match.start(1) - match.start()] + router
        text = CALL_TARGET.sub(call, text)
    if dispatch:
        def entry(match):
            nonlocal entries
            original=b"sub_"+match[1].upper()
            if original not in targets:
                return match[0]
            router=targets[original]
            observed[original].append(match[2])
            if match[2] not in (original, router):
                raise ValueError("Native route dispatch symbol differs from guest VA: " + match[0].decode())
            if match[2] == router:
                return match[0]
            entries += 1
            used.add(router)
            start = match.start(2) - match.start()
            end = match.end(2) - match.start()
            return match[0][:start] + router + match[0][end:]
        text = DISPATCH_ENTRY.sub(entry, text)
        for original,matches in observed.items():
            if len(matches) != 1:
                raise ValueError("Native route requires exactly one merged dispatch entry: " + original.decode())
    if calls or entries:
        for router in sorted(used):
            declaration = b"extern void " + router + b"(void);"
            if not re.search(rb"(?m)^\s*extern void " + re.escape(router) + rb"\(void\);\s*$", text):
                text = declaration + b"\n" + text
    return text, calls, entries
