"""Build the ARM64 Android stage: generated x86 C for all lifted modules plus
the Win32 HLE host, compiled with the NDK clang and linked into either a
command-line executable (adb shell bring-up) or the shared library for the APK.

Objects are reused only when the source, every header the generated code can
see, the compiler and the options are byte-identical (SHA-256 fingerprint).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import time
from index_region import index_region
from protocol_transform import Protocol, apply_protocol
from x87_locals import Plan as X87Plan, apply_x87
from android_tools import NDK, TOOLCHAIN, CLANG
from editions import EDITION_IDS, edition_spec, generated_root, module_manifest, build_root

ROOT = Path(__file__).resolve().parents[1]
EDITION = "toe"
GENERATED = generated_root()
MANIFEST = module_manifest()
MODULES = tuple(row["name"] for row in MANIFEST)
# Match the APK minimum; Android before 29 cannot resolve ELF TLS descriptors.
API = 26
TARGET = f"aarch64-linux-android{API}"
OUT = build_root()
COMMON = ["--target=" + TARGET, "-fno-strict-aliasing", "-fwrapv", "-fvisibility=hidden", "-fPIC",
          "-ffp-contract=off", "-fno-math-errno", "-g0", "-DRECOMP_X87_WINDOW",
          "-ffile-prefix-map=" + str(ROOT) + "=."]
GENERATED_FLAGS = COMMON + ["-O2", "-w", "-DRECOMP_GENERATED_CODE", "-Iandroid/runtime",
                            "-DRECOMP_GUEST_STATE_SEPARATE", "-mllvm", "-basic-aa-separate-storage",
                            "-DRECOMP_GUEST_PROVENANCE"]
HOST_FLAGS = COMMON + ["-O2", "-std=gnu11", "-Wall", "-Wno-unused-function", "-Wno-unused-variable",
                       "-DRECOMP_TRACE", "-Iandroid/runtime", "-Iandroid/host"]
# MojoShader (zlib), pinned in dependencies.json; only the profiles the host uses.
MOJO_DIR = "reference/mojoshader"
MOJO_SOURCES = ["mojoshader.c", "mojoshader_common.c", "mojoshader_assembler.c", "mojoshader_preprocessor.c",
                "mojoshader_lexer.c", "profiles/mojoshader_profile_common.c", "profiles/mojoshader_profile_glsl.c",
                "profiles/mojoshader_profile_d3d.c", "profiles/mojoshader_profile_bytecode.c"]
MOJO_FLAGS = COMMON + ["-O2", "-w", "-DMOJOSHADER_FLIP_RENDERTARGET", "-DMOJOSHADER_DEPTH_CLIPPING",
                       "-DSUPPORT_PROFILE_HLSL=0", "-DSUPPORT_PROFILE_ARB1=0", "-DSUPPORT_PROFILE_ARB1_NV=0",
                       "-DSUPPORT_PROFILE_METAL=0", "-DSUPPORT_PROFILE_SPIRV=0", "-DSUPPORT_PROFILE_GLSPIRV=0",
                       "-DSUPPORT_PROFILE_GLSL120=0", "-I" + MOJO_DIR, "-Iandroid/runtime"]


# Lifted functions the host implements natively (android/host/*.c). Their
# generated definitions are compiled from a patched copy as <name>_lifted, so
# every call and the dispatch table bind to the native version while the host
# can still run the lifted body for differential checks.
NATIVE_OVERRIDES = ("sub_1102BC0B", "sub_110277DD", "sub_1102B103",
                    "sub_1102B635", "sub_1102B659", "sub_1102B6BB", "sub_1102B6F8",
                    "sub_1102B716", "sub_1102B7CA", "sub_1102B844", "sub_1102B8A8",
                    "sub_1102B9C5", "sub_1102BAB5", "sub_1102BABE",
                    "sub_1102BE47", "sub_1102D53A",
                    # Touch tooltips (android/host/touch_engine.c): the CWindowScreen
                    # tooltip tracker update and the hover-timeout getter.
                    "sub_008863A0", "sub_006B92E0",
                    # UI quads render at display resolution above the scaled scene.
                    "sub_00A46BC0",
                    # Port console variables (android/host/port_settings.c): the
                    # engine's variable registration.
                    "sub_00C11400",
                    # Converted textures (android/host/texture_native.c): the DDS
                    # format code and the software texture loader.
                    "sub_00A9CDC0", "sub_00CC5F50",
                    # The NUbi network log line flush and the LAN game checksum
                    # tables (android/host/nubi_log.c).
                    "sub_008CD870", "sub_0081F500", "sub_0081F670")

FPU_MEMORY_NOOP = re.compile(rb"/\* (fnsave|fsave|frstor): FPU state is not a memory image here \*/ /\* 0x([0-9A-F]{8}): [^\r\n]*? \*/")


def guard_fpu_memory(text):
    guard_x87_window_source(text)
    # The inherited emitter silently omitted these instructions; diagnose a real caller.
    return FPU_MEMORY_NOOP.sub(lambda m: b'void_lift_trap(0x' + m[2] + b'u, "unsupported x87 ' + m[1] + b' memory image"); ' + m[0], text)


def guard_x87_window_source(text):
    # A saved window pointer, or an unsequenced pop/index, would follow the old position.
    if (re.search(rb"&\s*(?:_st|g_st|g_st_i64)\b", text)
            or re.search(rb"\b(?:double|int64_t)\s*\*\s*\w+\s*=\s*(?:_st|g_st|g_st_i64)\b", text)):
        raise ValueError("Generated x87 window pointer escapes its logical array")
    for statement in text.split(b";"):
        if b"fp_pop()" in statement and (re.search(rb"\b(?:_st|g_st|g_st_i64)\s*\[", statement)
                                           or b"fp_push(" in statement):
            raise ValueError("Generated x87 pop shares an expression with a window operand")


# With RECOMP_LOCAL_REGS a lifted body that uses the SSE file keeps it in a
# local copy as well (recomp_types.h: RECOMP_XMM_OUT/IN ride on the register
# transfers at every call, tail, yield and exit). The generated sources stay
# shared with the Windows build; these definitions go round each such body in
# the Android copy.
FUNCTION_START = re.compile(rb"^void sub_\w+\(void\) \{\r?$", re.M)   # generated files use CRLF
FUNCTION_END = re.compile(rb"\n\}\r?\n")
XMM_LOCAL = (b"#undef _xmm\n#undef RECOMP_XMM_OUT\n#undef RECOMP_XMM_IN\n#define _xmm l_xmm\n"
             b"#define RECOMP_XMM_OUT() memcpy(g_xmm, l_xmm, sizeof l_xmm)\n"
             b"#define RECOMP_XMM_IN() memcpy(l_xmm, g_xmm, sizeof l_xmm)\n")
XMM_GLOBAL = (b"#undef _xmm\n#undef RECOMP_XMM_OUT\n#undef RECOMP_XMM_IN\n#define _xmm g_xmm\n"
              b"#define RECOMP_XMM_OUT() ((void)0)\n#define RECOMP_XMM_IN() ((void)0)\n")


def localize_sse(text):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        if b"_xmm" not in text[match.end():end.end()]:
            continue
        parts += [text[pos:match.start()], XMM_LOCAL, match.group(0),
                  b"\n    xmm_t l_xmm[8]; memcpy(l_xmm, g_xmm, sizeof l_xmm);", text[match.end():end.end()], XMM_GLOBAL]
        pos = end.end()
    return b"".join(parts + [text[pos:]]) if parts else text


BACKEDGE_LOCAL = (b"#undef RECOMP_BACKEDGE_COUNTER\n#undef RECOMP_BACKEDGE_OUT\n#undef RECOMP_BACKEDGE_IN\n"
                  b"#define RECOMP_BACKEDGE_COUNTER l_backedges\n"
                  b"#define RECOMP_BACKEDGE_OUT() (g_backedges = l_backedges)\n"
                  b"#define RECOMP_BACKEDGE_IN() (l_backedges = g_backedges)\n")
BACKEDGE_GLOBAL = (b"#undef RECOMP_BACKEDGE_COUNTER\n#undef RECOMP_BACKEDGE_OUT\n#undef RECOMP_BACKEDGE_IN\n"
                   b"#define RECOMP_BACKEDGE_COUNTER g_backedges\n"
                   b"#define RECOMP_BACKEDGE_OUT() ((void)0)\n#define RECOMP_BACKEDGE_IN() ((void)0)\n")
# Broad localization added 9 MB of call-boundary transfers without a game FPS gain.
BACKEDGE_HOT_FUNCTIONS = (b"sub_008800B0", b"sub_00C362E0")


def localize_backedges(text, functions=None):
    # Guest stores alias globals; retain the exact counter in a local between transfers.
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        if functions is not None and match[0].split(b"(", 1)[0][5:] not in functions:
            continue
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        body = text[match.end():end.end()]
        if b"RECOMP_BACKEDGE();" not in body or b"uint32_t l_backedges = g_backedges;" in body:
            continue
        parts += [text[pos:match.start()], BACKEDGE_LOCAL, match.group(0),
                  b"\n    uint32_t l_backedges = g_backedges;", body, BACKEDGE_GLOBAL]
        pos = end.end()
    return b"".join(parts + [text[pos:]]) if parts else text


# APGO far owners >=0.25% sampled periods plus three confirmed inlined MMX callees.
# Whole-corpus assumptions caused excessive compiler cost; keep the measured scope.
GUEST_STATE_HOT_FUNCTIONS = (
    b"sub_004C4EA0", b"sub_004C59A0", b"sub_004C5A00", b"sub_004FA1A0",
    b"sub_0050BEB0", b"sub_00578A90", b"sub_00878FD0", b"sub_008791F0",
    b"sub_00879240", b"sub_0087E480", b"sub_008800B0", b"sub_00880BE0",
    b"sub_00896430", b"sub_00896EB0", b"sub_00899720", b"sub_008F1DA0",
    b"sub_009AE2F0", b"sub_009B8F60", b"sub_009B9050", b"sub_009BA480",
    b"sub_009BA850", b"sub_009DC210", b"sub_00A3B450", b"sub_00A3B5E0",
    b"sub_00A8D200", b"sub_00A8D440", b"sub_00A904D0", b"sub_00B10030",
    b"sub_00B1C300", b"sub_00B79D80", b"sub_00BF4E80", b"sub_00C059B0",
    b"sub_00C311F0", b"sub_00C31400", b"sub_00C341A0", b"sub_00C362E0",
    b"sub_00C48A30", b"sub_00C67B90", b"sub_00C68210", b"sub_00C682D0",
    b"sub_00C683E0", b"sub_00C687C0", b"sub_00C68F50", b"sub_00C6B0B0",
    b"sub_00CAB230", b"sub_00CEA350", b"sub_00CF7370", b"sub_00CF8B40",
    b"sub_00CF92C0", b"sub_00CF9BE0", b"sub_1103A0D5", b"sub_1301A28F",
    b"sub_50010900", b"sub_50011890", b"sub_50016F40", b"sub_50028950",
    b"sub_50028B90", b"sub_5003CE40", b"sub_5003ECC0",
)
GUEST_STATE_SEPARATE = (b"#undef RECOMP_MEM_ADDR\n"
                        b"#define RECOMP_MEM_ADDR(va) RECOMP_SEPARATE_MEM_ADDR(va)\n")
GUEST_STATE_DEFAULT = b"#undef RECOMP_MEM_ADDR\n#define RECOMP_MEM_ADDR(va) RECOMP_GUEST_PTR(va)\n"


def separate_guest_state(text, functions=GUEST_STATE_HOT_FUNCTIONS):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        if match[0].split(b"(", 1)[0][5:] not in functions:
            continue
        if text[max(0, match.start() - len(GUEST_STATE_SEPARATE)):match.start()] == GUEST_STATE_SEPARATE:
            continue
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            raise ValueError("Missing hot function boundary for guest-state separation")
        parts += [text[pos:match.start()], GUEST_STATE_SEPARATE,
                  text[match.start():end.end()], GUEST_STATE_DEFAULT]
        pos = end.end()
    return b"".join(parts + [text[pos:]]) if parts else text


# Four scalar union assignments were still lowered to four scalar instructions
# and spills in the sampled skinning loop; retain the original packed operation.
PACKED_SSE_REGISTER = re.compile(
    rb"^(    \{ [^\r\n]* \}) (/\* 0x[0-9A-F]{8}: (addps|subps|mulps) xmm([0-7]), xmm([0-7]) \*/)(\r?)$", re.M)


# `rep movsd` / `rep movsb` lift to one guest element per loop iteration.
# With DF=0 and no replicating overlap the copy is memmove (recomp_movs_fast);
# the original loop stays as the fallback, so the result is identical.
REP_MOVS = ((b"while (ecx) { MEM32(edi) = MEM32(esi); esi += _df * 4; edi += _df * 4; --ecx; }", 4),
            (b"while (ecx) { MEM8(edi) = MEM8(esi); esi += _df * 1; edi += _df * 1; --ecx; }", 1))


def fast_rep_movs(text):
    for loop, unit in REP_MOVS:
        if loop in text:
            text = text.replace(loop, b"{ if (_df > 0 && recomp_movs_fast(edi, esi, ecx, %du)) "
                                      b"{ esi += ecx * %du; edi += ecx * %du; ecx = 0; } else %s }" % (unit, unit, unit, loop))
    return text


def packed_sse(text):
    def replace(match):
        body, comment, opcode, dst, src, cr = match.groups()
        op = {b"addps": b"+", b"subps": b"-", b"mulps": b"*"}[opcode]
        reads = b" ".join(b"float _s%d = _xmm[%s].f32[%d];" % (i, src, i) for i in range(4))
        lanes = b" ".join(b"_d.f32[%d] = (float)(_d.f32[%d] %s _s%d);" % (i, i, op, i) for i in range(4))
        expected = b"    { " + reads + b" xmm_t _d = _xmm[" + dst + b"]; " + lanes + b" _xmm[" + dst + b"] = _d; }"
        if body != expected:
            return match[0]
        # C may commute operands and change NaN payloads; preserve the original
        # SSE priority, including its negative canonical NaN for invalid inputs.
        return (b"    { typedef float h5_ps4 __attribute__((vector_size(16))); h5_ps4 _s, _d; "
                b"memcpy(&_s, &_xmm[" + src + b"], sizeof _s); memcpy(&_d, &_xmm[" + dst + b"], sizeof _d);\n"
                b"#if defined(__i386__) || defined(__x86_64__)\n"
                b"    __asm__(\"" + opcode + b" %1, %0\" : \"+x\" (_d) : \"x\" (_s));\n"
                b"#else\n"
                b"    typedef uint32_t h5_pu4 __attribute__((vector_size(16))); h5_pu4 _su, _du, _ru; "
                b"memcpy(&_su, &_s, sizeof _su); memcpy(&_du, &_d, sizeof _du); "
                b"_d = _d " + op + b" _s; memcpy(&_ru, &_d, sizeof _ru); "
                b"h5_pu4 _rn = (_ru & 0x7FFFFFFFu) > 0x7F800000u; if (__builtin_reduce_or(_rn)) { "
                b"h5_pu4 _dn = (_du & 0x7FFFFFFFu) > 0x7F800000u, _sn = (_su & 0x7FFFFFFFu) > 0x7F800000u; "
                b"h5_pu4 _nan = (_dn & (_du | 0x00400000u)) | (~_dn & _sn & (_su | 0x00400000u)) | "
                b"(~(_dn | _sn) & 0xFFC00000u); _ru = (_rn & _nan) | (~_rn & _ru); memcpy(&_d, &_ru, sizeof _d); }\n"
                b"#endif\n"
                b"    memcpy(&_xmm[" + dst + b"], &_d, sizeof _d); } " + comment + cr)
    return PACKED_SSE_REGISTER.sub(replace, text)


# `jmp [reg*4 + table]` reaches its target through the body's `_ljump`
# switch over guest addresses; with a few hundred sparse cases clang emits a
# binary search (the script VM's opcode dispatch spent most of its time
# there). Each such jump gets a table of label addresses built from the jump
# table in the image the code was lifted from; an index past it, or an entry
# that is not a label of the body, still goes through the switch.
JUMP_TABLE = re.compile(rb"\{ _itail_tgt = \(uint32_t\)\(MEM32\((e[a-d]x|e[sd]i|ebp|esp) \* 4 \+ 0x([0-9A-F]{8})\)\); "
                        rb"goto _ljump; \}")
LABEL = re.compile(rb"^L_([0-9A-F]{8}):", re.M)
MODULE_IMAGES = {row["name"]: GENERATED / "input" / row["file"] for row in MANIFEST}
ACTIVE_NATIVE_OVERRIDES = None


class Image:
    """A PE image's bytes by virtual address (the lifted, possibly rebased, copy)."""
    def __init__(self, path):
        data = Path(path).read_bytes()
        pe = int.from_bytes(data[0x3C:0x40], "little")
        count = int.from_bytes(data[pe + 6:pe + 8], "little")
        optional = pe + 24
        self.base = int.from_bytes(data[optional + 28:optional + 32], "little")
        table = optional + int.from_bytes(data[pe + 20:pe + 22], "little")
        self.sections = []
        for i in range(count):
            at = table + 40 * i
            vsize, va, raw_size, raw = (int.from_bytes(data[at + o:at + o + 4], "little") for o in (8, 12, 16, 20))
            self.sections.append((self.base + va, max(vsize, raw_size), raw, raw_size))
        self.data = data
        self.sha256 = hashlib.sha256(data).hexdigest()

    def u32(self, va):
        for start, size, raw, raw_size in self.sections:
            if start <= va and va + 4 <= start + size:
                offset = va - start
                return int.from_bytes(self.data[raw + offset:raw + offset + 4], "little") if offset + 4 <= raw_size else 0
        return None


_images = {}


def module_image(module):
    """The image a generated module was lifted from, checked against its report."""
    if module not in _images:
        image = Image(MODULE_IMAGES[module])
        report = json.loads((GENERATED / f"{module}-x86/report.json").read_text())
        expected = report.get("rebased_sha256") or report.get("binary_sha256")
        if expected and expected != image.sha256:
            raise SystemExit(f"{module}: image {MODULE_IMAGES[module]} does not match report.json")
        _images[module] = image
    return _images[module]


def direct_jump_tables(text, image):
    parts, pos = [], 0
    for match in FUNCTION_START.finditer(text):
        end = FUNCTION_END.search(text, match.end())
        if not end or match.start() < pos:
            continue
        body = text[match.end():end.end()]
        if b"  _ljump:" not in body or not JUMP_TABLE.search(body):
            continue
        labels = {int(label, 16) for label in LABEL.findall(body)}
        if len(labels) > 2000:
            # Bodies labelled at nearly every instruction (the CRT's memcpy
            # family: 112 tables, ~5,000 labels) took clang over ten minutes
            # with label tables; they keep the switch.
            continue
        low, high = min(labels), max(labels)

        def table_jump(jump):
            register, table = jump.group(1), int(jump.group(2), 16)
            targets = []
            while len(targets) < 1024:
                target = image.u32(table + 4 * len(targets))
                if target is None or not low <= target <= high:
                    break
                targets.append(target)
            if not targets:
                return jump.group(0)
            entries = b", ".join(b"&&L_%08X" % t if t in labels else b"&&_ljump" for t in targets)
            return (b"{ static void *const _jt[%d] = { %s }; uint32_t _jx = %s; "
                    b"_itail_tgt = (uint32_t)(MEM32(%s * 4 + 0x%08X)); if (_jx < %du) goto *_jt[_jx]; goto _ljump; }"
                    % (len(targets), entries, register, register, table, len(targets)))

        parts += [text[pos:match.end()], JUMP_TABLE.sub(table_jump, body)]
        pos = end.end()
    return b"".join(parts + [text[pos:]]) if parts else text


_protocol = None


def call_protocol():
    """The whole-program call-boundary summary (tools/call_protocol.py)."""
    global _protocol
    if _protocol is None:
        # The UI wrapper changes only host state; its lifted body keeps the exact guest register effects.
        _protocol = Protocol(full=tuple(name for name in NATIVE_OVERRIDES if name != "sub_00A46BC0"))
    return _protocol


_x87_plan = None


def x87_plan():
    """Static x87 stack depths (tools/x87_locals.py)."""
    global _x87_plan
    if _x87_plan is None:
        _x87_plan = X87Plan()
    return _x87_plan


def configure_edition(edition):
    """Select one engine's inputs; no address summaries cross this boundary."""
    global EDITION, GENERATED, MANIFEST, MODULES, MODULE_IMAGES, OUT
    global ACTIVE_NATIVE_OVERRIDES, _protocol, _x87_plan
    EDITION = edition
    GENERATED = generated_root(edition, root=ROOT)
    MANIFEST = module_manifest(edition, root=ROOT)
    MODULES = tuple(row["name"] for row in MANIFEST)
    MODULE_IMAGES = {row["name"]: GENERATED / "input" / row["file"] for row in MANIFEST}
    OUT = build_root(edition, root=ROOT)
    ACTIVE_NATIVE_OVERRIDES = None
    _images.clear()
    _protocol = _x87_plan = None


# Without per-entry g_cur_func stores, the host's frame pump (BeginScene from
# H5's frame function 00A3FB70) is told its caller at this one call site.
FRAME_BEGIN_SCENE = re.compile(rb"^(    )(RECOMP_ICALL(?:_P)?\(MEM32\(edx \+ 0xA4\)[^\r\n]*?;)( /\* 0x00A3FCE3: call dword ptr \[edx \+ 0xa4\] \*/)", re.M)


def mark_frame_begin_scene(text):
    if b"void sub_00A3FB70(void) {" not in text:
        return text
    text, count = FRAME_BEGIN_SCENE.subn(rb"\1g_cur_func = 0x00A3FB70u; \2 g_cur_func = 0;\3", text)
    if count != 1:
        raise ValueError("H5 frame BeginScene call site not found exactly once")
    return text


# x87 arithmetic the precision and rounding fields round (Intel SDM 8.1.5):
# each generated statement assigns its destination slot first; fp_pc
# (recomp_types.h) rounds it after, as the x87 does under single precision.
# A store to a float rounds by the rounding field (fp_f32), and a control word
# load recomputes both roundings (fp_set_cw).
X87_ROUNDED = re.compile(rb"^(?P<code>[^\r\n]*?)(?P<comment>/\* 0x[0-9A-F]{8}: "
                         rb"f(?:i?(?:add|sub|subr|mul|div|divr)p?|sqrt)\b[^\r\n]*?\*/)", re.M)
X87_DESTINATION = re.compile(rb"((?:_h5_fp\.st|_st)\[\d\])\s*[-+*/]?=(?!=)")
X87_FLOAT_STORE = re.compile(rb"^(?P<code>[^\r\n]*?)(?P<comment>/\* 0x[0-9A-F]{8}: fstp? dword ptr [^\r\n]*?\*/)", re.M)
X87_FLOAT_CAST = re.compile(rb"float _v = \(float\)([^;]+);")
X87_CONTROL_LOAD = re.compile(rb"^(?P<code>[^\r\n]*?)(?P<comment>/\* 0x[0-9A-F]{8}: fldcw [^\r\n]*?\*/)", re.M)
X87_CONTROL_SET = re.compile(rb"_fpu_cw = ([^;]+);")


def round_x87_precision(text):
    def rounded(match):
        code = match["code"]
        target = X87_DESTINATION.search(code)
        if not target:
            raise ValueError("x87 arithmetic without a destination slot: " + match[0].decode(errors="replace"))
        slot = target[1]
        return code.rstrip() + b" %s = fp_pc(%s); " % (slot, slot) + match["comment"]

    def stored(match):
        code, count = X87_FLOAT_CAST.subn(rb"float _v = fp_f32(\1);", match["code"])
        if count != 1:
            raise ValueError("x87 float store of an unknown form: " + match[0].decode(errors="replace"))
        return code + match["comment"]

    def controlled(match):
        code, count = X87_CONTROL_SET.subn(rb"fp_set_cw(\1);", match["code"])
        if count != 1:
            raise ValueError("x87 fldcw of an unknown form: " + match[0].decode(errors="replace"))
        return code + match["comment"]
    text = X87_FLOAT_STORE.sub(stored, X87_ROUNDED.sub(rounded, text))
    return X87_CONTROL_LOAD.sub(controlled, text)


def cutscene_projection(text):
    # Only the legacy animated cutscene camera lacks the engine's Hor+ conversion.
    original = b"    edx = MEM32(esi + 0x14); /* 0x007D210A: mov edx, dword ptr [esi + 0x14] */"
    if original not in text:
        return text
    if text.count(original) != 1:
        raise ValueError("Legacy cutscene FOV load is not unique")
    declaration = b"uint32_t void_cutscene_fov(uint32_t camera, uint32_t viewport, uint32_t fov, uint32_t stack);\n"
    replacement = b"    edx = void_cutscene_fov(esi, MEM32(esp + 0x4C), MEM32(esi + 0x14), esp); /* 0x007D210A: legacy cutscene Hor+ */"
    return text.replace(b"void sub_007D20E0(void) {", declaration + b"void sub_007D20E0(void) {", 1).replace(original, replacement)


def override_source(source, local_xmm):
    """The file to compile for a generated source and its extra flags: a
    patched copy under build/ when a transform changes it: x87 precision
    rounding, one of NATIVE_OVERRIDES, or (with local_xmm) a body that uses SSE
    or backedges, with packed arithmetic and direct jump tables."""
    original = source.read_bytes()
    text = round_x87_precision(guard_fpu_memory(original))
    if EDITION == "toe":
        text = cutscene_projection(text)
    elif source.name != "recomp_dispatch.c":
        from port_patches import adapt_generated_source
        text = adapt_generated_source(text, source.parent.name[:-len("-x86")], EDITION)
    names = ACTIVE_NATIVE_OVERRIDES
    if names is None:
        from port_patches import native_overrides
        names = native_overrides(EDITION, NATIVE_OVERRIDES)
    for name in names:
        text = text.replace(b"\nvoid %s(void) {" % name.encode(), b"\nvoid %s_lifted(void) {" % name.encode(), 1)
    if source.name != "recomp_dispatch.c":
        module = source.parent.name[:-len("-x86")]
        if b"goto _ljump; }" in text:
            text = direct_jump_tables(text, module_image(module))
        text = packed_sse(text)
        text = fast_rep_movs(text)
        if local_xmm:
            if EDITION == "toe":
                text = index_region(text)
            text = localize_sse(text)
            if EDITION == "toe":
                text = localize_backedges(text, BACKEDGE_HOT_FUNCTIONS)
                text = separate_guest_state(text)
                text = apply_protocol(text, call_protocol(), module)
                text = apply_x87(text, x87_plan())
        if EDITION == "toe":
            text = mark_frame_begin_scene(text)
    if text == original:
        return source, []
    patched = OUT / "patched" / source.parent.name / source.name
    patched.parent.mkdir(parents=True, exist_ok=True)
    if not patched.is_file() or patched.read_bytes() != text:
        patched.write_bytes(text)
    return patched, ["-I" + source.parent.relative_to(ROOT).as_posix()]


def sha_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def available_modules():
    """Generated stages present on disk (PhysX joins once tools/lift_physx.py has run)."""
    return [m for m in MODULES if (GENERATED / f"{m}-x86/report.json").exists()
            and json.loads((GENERATED / f"{m}-x86/report.json").read_text()).get("status") == "GENERATED"]


def generated_sources():
    sources = []
    modules = available_modules()
    for name in modules:
        report = json.loads((GENERATED / f"{name}-x86/report.json").read_text())
        files = report.get("sources")
        if not isinstance(files, list) or not files:
            raise SystemExit(f"{name}: report.json has no source list")
        sources += [GENERATED / f"{name}-x86" / f for f in files]
    if not modules:
        raise ValueError(EDITION + ": no generated modules")
    sources.append(GENERATED / f"{modules[-1]}-x86/recomp_dispatch.c")
    return sources


def module_compile_flags(module):
    # FMOD's x87 decode batches have no native calls between loop edges. A
    # smaller-than-default handoff interval keeps render progress while giving
    # the decoder enough work per FIFO round to refill before playback catches it.
    # HoF's loading transition needs more decode work per contended round.
    # Other modules keep the runtime default. Flags join each object's digest.
    edges = 32768 if EDITION == "hof" else 16384
    return [f"-DRECOMP_YIELD_EVERY={edges}u"] if module == "fmod-x86" else []


def host_sources():
    return sorted((ROOT / "android/host").glob("*.c"))


def header_digest(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(sha_file(path).encode())
    return digest.hexdigest()


def edition_descriptor(out, edition):
    """Keep module selection private even when engines build concurrently."""
    spec = edition_spec(edition, root=ROOT)
    out.mkdir(parents=True, exist_ok=True)
    include = out / "modules.inc"
    declarations = ["/* Generated from " + spec["modules"] + "; do not edit. */"]
    for row in module_manifest(edition, root=ROOT):
        declarations.append('{%s, %s, %su, %d, %d},' %
            (json.dumps(row["file"]), json.dumps(row["file"]), row["base"],
             row.get("exe", False), row.get("optional", False)))
    header = out / "edition.h"
    definitions = {"HOMM5_EDITION": edition, "HOMM5_BIN": spec["bin"],
                   "HOMM5_PROFILE_SUFFIX": spec["profile_suffix"],
                   "HOMM5_MODULES_INCLUDE": include.resolve().as_posix()}
    if edition != "toe":
        definitions["HOMM5_LEGACY_UI"] = 1
    for path, text in ((include, "\n".join(declarations) + "\n"),
                       (header, "\n".join("#define " + key + " " + json.dumps(value)
                                          for key, value in definitions.items()) + "\n")):
        if not path.exists() or path.read_text() != text:
            path.write_text(text, encoding="utf-8")
    return header, include


def compile_one(source, obj, flags, fingerprint, cache):
    rel = source.relative_to(ROOT).as_posix()
    entry = cache.get(rel)
    if entry and entry.get("fingerprint") == fingerprint and obj.is_file() and sha_file(obj) == entry.get("object_sha256"):
        return rel, "reused", 0.0, entry
    obj.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    command = [str(CLANG)] + flags + ["-c", str(source), "-o", str(obj)]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.time() - start
    if result.returncode:
        raise RuntimeError(f"{rel}: clang failed ({result.returncode})\n{result.stderr[-4000:]}")
    if result.stderr.strip():
        print(f"[warn] {rel}:\n{result.stderr.strip()[-3000:]}", flush=True)
    return rel, "compiled", elapsed, {"fingerprint": fingerprint, "object_sha256": sha_file(obj)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=EDITION_IDS, default="toe")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 4))
    parser.add_argument("--host-only", action="store_true", help="Recompile host sources and relink only")
    parser.add_argument("--shared", action="store_true", help="Link libhomm5.so for the APK instead of the executable")
    parser.add_argument("--global-regs", action="store_true",
                        help="Keep the integer registers in globals (upstream model) instead of RECOMP_LOCAL_REGS")
    parser.add_argument("--volatile-memory", action="store_true",
                        help="Volatile guest memory accesses (upstream) instead of RECOMP_PLAIN_MEMORY")
    parser.add_argument("--pgo-generate", action="store_true",
                        help="Instrument the generated code for a profile (build/arm64-pgogen; LLVM_PROFILE_FILE "
                             "names the output, the script command 'profile' writes it)")
    parser.add_argument("--pgo-use", metavar="PROFDATA", default=None,
                        help="Optimise the generated code with a merged profile (llvm-profdata merge); "
                             "default build/pgo/homm5.profdata when it exists")
    parser.add_argument("--no-pgo", action="store_true", help="Build without the profile")
    parser.add_argument("--thinlto", action="store_true",
                        help="Compile all sources as ThinLTO bitcode in a separate output directory")
    parser.add_argument("--thinlto-jobs", type=int, default=None, metavar="N",
                        help="ThinLTO backend workers (default 4; requires --thinlto)")
    parser.add_argument("--protocol-check", action="store_true",
                        help="Validation build (build/arm64-check): full state at every transfer, callee-saved "
                             "and x87 window checks logged as [protocol] / [x87]")
    args = parser.parse_args()
    configure_edition(args.edition)
    if args.thinlto_jobs is not None and (not args.thinlto or args.thinlto_jobs < 1):
        parser.error("--thinlto-jobs must be positive and requires --thinlto")
    if not CLANG.is_file():
        parser.error("NDK clang is missing; install NDK 27.2.12479018 or set ANDROID_NDK")
    missing = sorted(set(MODULES) - set(available_modules()))
    if missing:
        parser.error("Static generation is incomplete: " + ", ".join(missing))
    # The first location gains ~12% (42-51 fps against 38-45) from the
    # profile, the map's settled phase more; a build without it is an explicit
    # choice, since it recompiles every generated object.
    profile_dir = "pgo" if EDITION == "toe" else "pgo-" + EDITION
    default_profile = ROOT / "build" / profile_dir / "homm5.profdata"
    if args.pgo_use is None and not args.no_pgo and not args.pgo_generate and default_profile.is_file():
        args.pgo_use = str(default_profile)
    if args.no_pgo:
        args.pgo_use = None
    if (EDITION != "toe" and args.pgo_use and
            Path(args.pgo_use).resolve() == (ROOT / "build/pgo/homm5.profdata").resolve()):
        parser.error("The ToE PGO profile cannot be used with another engine")
    # The default generated code keeps registers in locals and accesses guest
    # memory plainly (first location on the Redmi Note 8 Pro: 37-43 fps against
    # 33-39 with both off). The upstream modes build in their own directories
    # (build/arm64-globalregs, build/arm64-volatilemem, ...) for A/B runs.
    global OUT, GENERATED_FLAGS, ACTIVE_NATIVE_OVERRIDES
    GENERATED_FLAGS = (GENERATED_FLAGS + ([] if args.global_regs else ["-DRECOMP_LOCAL_REGS"]) +
                       ([] if args.volatile_memory else ["-DRECOMP_PLAIN_MEMORY"]))
    upstream = [name for name, on in (("globalregs", args.global_regs), ("volatilemem", args.volatile_memory),
                                      ("pgogen", args.pgo_generate), ("thinlto", args.thinlto),
                                      ("check", args.protocol_check)) if on]
    if args.protocol_check:
        GENERATED_FLAGS = GENERATED_FLAGS + ["-DRECOMP_PROTOCOL_CHECK"]
    OUT = build_root(EDITION, upstream, root=ROOT)
    if args.pgo_generate:
        GENERATED_FLAGS = GENERATED_FLAGS + ["-fprofile-instr-generate"]
    if args.pgo_use:
        profile = Path(args.pgo_use).resolve()
        # The profile's digest joins the flags, so objects follow a new profile.
        # -w suppresses even fatal frontend profile diagnostics.
        GENERATED_FLAGS = [flag for flag in GENERATED_FLAGS if flag != "-w"] + [
            "-Werror=profile-instr-out-of-date", "-Werror=profile-instr-unprofiled",
            "-fprofile-instr-use=" + profile.as_posix(), "-DVOID_PGO_PROFILE_" + sha_file(profile)[:16]]
    lto_compile_flags = ["-flto=thin"] if args.thinlto else []
    GENERATED_FLAGS = GENERATED_FLAGS + lto_compile_flags
    mojo_flags = MOJO_FLAGS + lto_compile_flags
    # Missing or stale native seams must stop before any compiler job starts.
    from port_patches import (validate_native_inputs, native_overrides,
                              adapt_host_source, finalize_native_receipt)
    validate_native_inputs(EDITION)
    ACTIVE_NATIVE_OVERRIDES = native_overrides(EDITION, NATIVE_OVERRIDES)
    descriptor, include = edition_descriptor(OUT, EDITION)
    os.chdir(ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    cache_path = OUT / "objects.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    compiler_sha = sha_file(CLANG)
    runtime_headers = [ROOT / "android/runtime/recomp_types.h"]
    # A module's sources see the runtime and their own headers; the merged
    # dispatch table (last module) sees every module's headers.
    module_digest = {name: header_digest(runtime_headers + sorted((GENERATED / f"{name}-x86").glob("*.h")))
                     for name in available_modules()}
    gen_digest = header_digest(runtime_headers + sorted(p for name in available_modules()
                                                        for p in (GENERATED / f"{name}-x86").glob("*.h")))
    host_digest = header_digest(runtime_headers + sorted((ROOT / "android/host").glob("*.h")) +
                                [descriptor, include] +
                                [ROOT / "reference/dlmalloc/malloc.c"])
    jobs, generated_objects = [], []
    for source in generated_sources():
        module = source.parent.name
        obj = OUT / "obj" / module / (source.stem + ".o")
        digest = gen_digest if source.name == "recomp_dispatch.c" else module_digest[module[:-len("-x86")]]
        source, extra = override_source(source, local_xmm=not args.global_regs)
        flags = GENERATED_FLAGS + module_compile_flags(module) + extra
        fp = hashlib.sha256(json.dumps([sha_file(source), digest, compiler_sha, flags]).encode()).hexdigest()
        if args.host_only:
            entry = cache.get(source.relative_to(ROOT).as_posix())
            if (not entry or entry.get("fingerprint") != fp or not obj.is_file() or
                    entry.get("object_sha256") != sha_file(obj)):
                raise SystemExit("--host-only: generated object is missing or stale: " + str(obj) +
                                 "; run a full build without --host-only")
            generated_objects.append(obj)
        else:
            jobs.append((source, obj, flags, fp))
    for name in MOJO_SOURCES:
        source = ROOT / MOJO_DIR / name
        obj = OUT / "obj/mojoshader" / (source.stem + ".o")
        fp = hashlib.sha256(json.dumps([sha_file(source), header_digest(sorted((ROOT / MOJO_DIR).glob("*.h"))),
                                        compiler_sha, mojo_flags]).encode()).hexdigest()
        jobs.append((source, obj, mojo_flags, fp))
    host_flags = HOST_FLAGS + ["-include", str(descriptor)] + lto_compile_flags + (["-DVOID_ANDROID_APP"] if args.shared else [])
    host_dir = "obj/host-app" if args.shared else "obj/host"
    for source in host_sources():
        obj = OUT / host_dir / (source.stem + ".o")
        source, extra = adapt_host_source(source, OUT, EDITION)
        flags = host_flags + extra
        fp = hashlib.sha256(json.dumps([sha_file(source), host_digest, compiler_sha, flags]).encode()).hexdigest()
        jobs.append((source, obj, flags, fp))
    # Largest first keeps the pool busy at the end.
    jobs.sort(key=lambda j: -j[0].stat().st_size)
    start = time.time()
    compiled = reused = 0
    failures = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(compile_one, s, o, f, fp, cache) for s, o, f, fp in jobs]
        for future in as_completed(futures):
            try:
                rel, status, elapsed, entry = future.result()
            except RuntimeError as error:
                failures.append(str(error))
                print(str(error), flush=True)
                continue
            cache[rel] = entry
            if status == "compiled":
                compiled += 1
                if elapsed > 20:
                    print(f"[slow] {rel}: {elapsed:.1f}s", flush=True)
            else:
                reused += 1
            if (compiled + reused) % 50 == 0:
                print(f"[progress] {compiled + reused}/{len(jobs)} ({time.time() - start:.0f}s)", flush=True)
                cache_path.write_text(json.dumps(cache, indent=1))
    cache_path.write_text(json.dumps(cache, indent=1))
    print(f"compiled {compiled}, reused {reused}, failed {len(failures)} in {time.time() - start:.0f}s", flush=True)
    if failures:
        sys.exit(1)
    objects = [str(o) for o in generated_objects] + [str(o) for _, o, _, _ in jobs]
    response = OUT / "link.rsp"
    response.write_text("\n".join(o.replace("\\", "/") for o in objects))
    library = edition_spec(EDITION, root=ROOT)["library"]
    output = OUT / ("lib" + library + ".so" if args.shared else library.replace("_", "-") + "-arm64")
    link = [str(CLANG), "--target=" + TARGET, "-fuse-ld=lld", "-Wl,--no-undefined", "-Wl,--gc-sections", "-Wl,-z,nostart-stop-gc", "-Wl,-z,max-page-size=16384",
            "-Wl,--build-id=sha1", "@" + str(response), "-o", str(output), "-lm", "-llog", "-ldl", "-lEGL", "-lGLESv3", "-lz"]
    link += ["-shared", "-landroid", "-lOpenSLES", "-laaudio"] if args.shared else ["-pie"]
    if args.pgo_generate:
        link.append("-fprofile-instr-generate")
    if args.thinlto:
        link += ["-flto=thin", "-Wl,--lto-O2", "-Wl,-mllvm,-basic-aa-separate-storage",
                 "-Wl,--thinlto-jobs=" + str(args.thinlto_jobs or 4),
                 "-Wl,--thinlto-cache-dir=" + (OUT / "thin-cache").as_posix(),
                 "-Wl,--thinlto-cache-policy=cache_size=0%:cache_size_bytes=4g:prune_interval=0s"]
    start = time.time()
    result = subprocess.run(link, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        print(result.stderr[-6000:])
        sys.exit(1)
    finalize_native_receipt(EDITION, output)
    print(f"linked {output} ({output.stat().st_size / 1e6:.1f} MB) in {time.time() - start:.0f}s")


if __name__ == "__main__":
    main()
