"""Cache sampled call-free x87 blocks without changing their operations.

The exact baseline text is pinned so a changed generator cannot silently apply a
stale region transform. Runtime helpers and other functions remain untouched.
"""
import hashlib
import re
from pathlib import Path

SYMBOL = "void sub_00BF4E80(void) {"
ENTRY = "L_00BF59AC:\n"
END_ADDRESS = "/* 0x00BF5D24:"
BASELINE_SHA256 = "7fc0d77e208e23542caf3ac1db53cb1b2a7b8a345c70ebf06003c81d803c2a07"
BEGIN = "    { /* H5_FPU_CACHE_BEGIN 00BF59AC..00BF5D24 */\n"
BODY = "        /* H5_FPU_CACHED_BODY */\n"
COMMIT = "        /* H5_FPU_CACHED_COMMIT */\n"
END = "    } /* H5_FPU_CACHE_END */\n"
GRANNY_SYMBOL = "void sub_50011890(void) {"
GRANNY_ENTRY = "L_50011890:\n"
GRANNY_BASELINE_SHA256 = "3a434ce228d5e78f7062fd745631d5f42296ebb4870ecfed9e0f801416dd6752"
GRANNY_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 50011890..500119A0 */\n"
GRANNY_END = "    } /* H5_FPU_CACHE_END 50011890 */\n"
MATRIX_SYMBOL = "void sub_007CC7C0(void) {"
MATRIX_ENTRY = "L_007CC7C0:\n"
MATRIX_BASELINE_SHA256 = "06ae59d5f46bc5e7ea7cf50dff4114ecc710f7a92a6220f98728c9ba6e5ef183"
MATRIX_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 007CC7C0..007CC9C8 */\n"
MATRIX_END = "    } /* H5_FPU_CACHE_END 007CC7C0 */\n"
INVERSE_SYMBOL = "void sub_00CF60A0(void) {"
INVERSE_ENTRY = "L_00CF60A0:\n"
INVERSE_BASELINE_SHA256 = "35a16e4e68d63245a94177da078a6e91c01d548dffe1e0602b0d5505680c24b2"
INVERSE_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 00CF60A0..00CF642E */\n"
INVERSE_END = "    } /* H5_FPU_CACHE_END 00CF60A0 */\n"
_GRANNY = (GRANNY_SYMBOL, GRANNY_ENTRY, "    RECOMP_FLAGS_OUT();", GRANNY_BASELINE_SHA256, GRANNY_BEGIN, GRANNY_END)
_MATRIX = (MATRIX_SYMBOL, MATRIX_ENTRY, "    RECOMP_FLAGS_OUT();", MATRIX_BASELINE_SHA256, MATRIX_BEGIN, MATRIX_END)
_INVERSE = (INVERSE_SYMBOL, INVERSE_ENTRY, "    RECOMP_FLAGS_OUT();", INVERSE_BASELINE_SHA256, INVERSE_BEGIN, INVERSE_END)
AFFINE_SYMBOL = "void sub_00465940(void) {"
AFFINE_ENTRY = "L_00465940:\n"
AFFINE_BASELINE_SHA256 = "822cfd41165c13a61906aa3e538df6025ca34f5d2653c8ed1131b717b40d5866"
AFFINE_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 00465940..00465996 */\n"
AFFINE_END = "    } /* H5_FPU_CACHE_END 00465940 */\n"
_AFFINE = (AFFINE_SYMBOL, AFFINE_ENTRY, "    RECOMP_FLAGS_OUT();", AFFINE_BASELINE_SHA256, AFFINE_BEGIN, AFFINE_END)
POSE_SYMBOL = "void sub_50028B90(void) {"
# The previous three scopes are retained only to validate/recover B1 sources
# before applying the larger C1 scope. A fresh lift has none of these markers.
POSE_REGIONS = {
    "load4": {"start": "L_50028CA8:\n", "stop": "    fp_push(_st[2]); /* 0x50028CB4:",
              "sha256": "cc564256d07828726c244c0098e3497250bd9a88ae3f98f76db403570d7260f0",
              "begin": "    { /* H5_FPU_CACHE_BEGIN 50028CA8..50028CB4 */\n",
              "end": "    } /* H5_FPU_CACHE_END 50028CA8 */\n"},
    "approx": {"start": "L_50028CF8:\n", "stop": "L_50028D1A:\n",
               "sha256": "1c55d4e6c77dfac4c1631b950bec249c91b6cda56d34dbdf29d0c612dbc96b7a",
               "begin": "    { /* H5_FPU_CACHE_BEGIN 50028CF8..50028D1A */\n",
               "end": "    } /* H5_FPU_CACHE_END 50028CF8 */\n"},
    "scale4": {"start": "L_50028D1A:\n", "stop": "    goto L_50028D61;",
               "sha256": "51f189d117a54e4ce712134db9eae97579516306e302efe6f784d4b6718ed307",
               "begin": "    { /* H5_FPU_CACHE_BEGIN 50028D1A..50028D38 */\n",
               "end": "    } /* H5_FPU_CACHE_END 50028D1A */\n"},
}
POSE_CFG_ENTRY = "L_50028C34:\n"
POSE_CFG_STOP = "L_50028D3A:\n"
POSE_CFG_BASELINE_SHA256 = "ce3c977e9857e248842e15eb6a493bd38380aaf4a70e116bbfba8e803ea772e8"
POSE_CFG_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 50028C34..50028D38 */\n"
POSE_CFG_BODY = "        /* H5_POSE_CFG_BODY */\n"
POSE_CFG_END = "    } /* H5_FPU_CACHE_END 50028C34 */\n"
_POSE_INIT = ("        memcpy(_h5_fp.st, g_st, sizeof _h5_fp.st);\n"
              "        memcpy(_h5_fp.i64, g_st_i64, sizeof _h5_fp.i64);\n"
              "        _h5_fp.top = g_fp_top;\n")
_POSE_COMMIT = ("        memcpy(g_st, _h5_fp.st, sizeof _h5_fp.st);\n"
                "        memcpy(g_st_i64, _h5_fp.i64, sizeof _h5_fp.i64);\n"
                "        g_fp_top = _h5_fp.top;\n")
THREE_BLOCK_SPECS = {
    "search127c1": {"source":"generated/granny2-x86/granny2_0004.c", "symbol":"void sub_500127B0(void) {",
                    "start":"L_500127C1:\n", "stop":"/* 0x500127D6:",
                    "digest":"67ec4e8841d5b180b41c66a5d4431e5cb2d37f0264f2adf359af42d3450a72ac",
                    "begin":"    { /* H5_FPU_CACHE_BEGIN 500127C1..500127D4 */\n",
                    "end":"    } /* H5_FPU_CACHE_END 500127C1 */\n"},
    "search127ea": {"source":"generated/granny2-x86/granny2_0004.c", "symbol":"void sub_500127B0(void) {",
                    "start":"L_500127EA:\n", "stop":"/* 0x500127F4:",
                    "digest":"baffd3c5d20d3be5886bb1ba9d3f1fccabc56357442506a9fd8f1895af6a8abf",
                    "begin":"    { /* H5_FPU_CACHE_BEGIN 500127EA..500127F2 */\n",
                    "end":"    } /* H5_FPU_CACHE_END 500127EA */\n"},
    "projectc866f7": {"source":"generated/game-x86/game_0664.c", "symbol":"void sub_00C86660(void) {",
                      "start":"/* 0x00C866F7:", "stop":"/* 0x00C86775:",
                      "digest":"6bef01a0352e51c8a0869acae66d849ea23c9ae274d0106287eb4b7f93d59409",
                      "begin":"    { /* H5_FPU_CACHE_BEGIN 00C866F7..00C86773 */\n",
                      "end":"    } /* H5_FPU_CACHE_END 00C866F7 */\n"},
    "edgec867e9": {"source":"generated/game-x86/game_0664.c", "symbol":"void sub_00C86660(void) {",
                   "start":"/* 0x00C867E9:", "stop":"/* 0x00C86810:",
                   "digest":"1df313a4423ce920a09db69fe81372750da739c891d43d0c4bd2427cced7b6db",
                   "begin":"    { /* H5_FPU_CACHE_BEGIN 00C867E9..00C8680D */\n",
                   "end":"    } /* H5_FPU_CACHE_END 00C867E9 */\n"},
}
POSE_ACCUM_SYMBOL = "void sub_50028950(void) {"
POSE_ACCUM_ENTRY = "L_50028950:\n"
POSE_ACCUM_BASELINE_SHA256 = "ca497e078e55e12315f7b61ec4e7d2bbad284a43231c3a643082f3d2239bb486"
POSE_ACCUM_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 50028950..50028B86 */\n"
POSE_ACCUM_BODY = "        /* H5_POSE_ACCUM_BODY */\n"
POSE_ACCUM_END = "    } /* H5_FPU_CACHE_END 50028950 */\n"
GUARDED_VECTOR_SYMBOL = "void sub_00BA2270(void) {"
GUARDED_VECTOR_ENTRY = "L_00BA2270:\n"
GUARDED_VECTOR_BASELINE_SHA256 = "58e5d18419185e7fb722c88957a4fcd0d8f62ce32141382b26021c48366e5d8b"
GUARDED_VECTOR_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 00BA2270..00BA22E9 guarded */\n"
GUARDED_VECTOR_END = "    } /* H5_FPU_CACHE_END 00BA2270 */\n"
_VECTOR_BASELINE = "        /* H5_VECTOR_BASELINE */\n"
_VECTOR_FAST = "    } else { /* H5_VECTOR_FINITE */\n"
CF_NORM_SYMBOL = "void sub_00CF6E50(void) {"
CF_NORM_ENTRY = "L_00CF6E50:\n"
CF_NORM_BASELINE_SHA256 = "717a44d04fee172862cd0338cfda36f19d77d63886bd80a19e68a1ce539794e7"
CF_NORM_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 00CF6E50..00CF6F4A guarded */\n"
CF_NORM_END = "    } /* H5_FPU_CACHE_END 00CF6E50 */\n"
_NORM_BASELINE = "        /* H5_NORM_BASELINE */\n"
_NORM_FAST = "    } else { /* H5_NORM_BOUNDED */\n"
NORM_GUARD_HELPER = r'''/* H5_NORM_GUARD: keep the live squared norm finite and its bits exact. */
static int h5_bounded_norm_inputs(uint32_t shape, uint32_t axes, uint32_t stack) {
    /* All twelve operands are unconditionally read by the original. Reject
     * ranges that wrap or can be overwritten by its 28-byte scratch frame. */
    if (stack < 0x1Cu || shape > UINT32_MAX - 0x1Cu || axes > UINT32_MAX - 0x2Cu)
        return 0;
    uint32_t bottom = stack - 0x1Cu;
    if ((shape + 0x10u < stack && shape + 0x1Cu > bottom) ||
        (axes < stack && axes + 0x2Cu > bottom))
        return 0;
    /* |input| <= 2^63: each product <= 2^126, each accumulated
     * component <= 3*2^126 < FLT_MAX, and its norm < 2^257 < DBL_MAX.
     * Larger/nonfinite or aliased inputs retain the literal original path. */
    for (unsigned i = 0; i < 3; ++i)
        if ((MEM32(shape + 0x10u + i * 4u) & 0x7FFFFFFFu) > 0x5F000000u)
            return 0;
    for (unsigned row = 0; row < 3; ++row)
        for (unsigned i = 0; i < 3; ++i)
            if ((MEM32(axes + row * 0x10u + i * 4u) & 0x7FFFFFFFu) > 0x5F000000u)
                return 0;
    return 1;
}

'''
PLANE_SYMBOL = "void sub_00CF7450(void) {"
PLANE_ENTRY = "L_00CF74AA:\n"
PLANE_STOP = "/* 0x00CF74DB:"
PLANE_BASELINE_SHA256 = "d619228763018d952fe600fc85a2f6461daebbca1290df72a706b4ceb675a205"
PLANE_BEGIN = "    { /* H5_FPU_CACHE_BEGIN 00CF74AA..00CF74D8 */\n"
PLANE_END = "    } /* H5_FPU_CACHE_END 00CF74AA */\n"
_PLANE = (PLANE_SYMBOL, PLANE_ENTRY, PLANE_STOP, PLANE_BASELINE_SHA256, PLANE_BEGIN, PLANE_END)
HELPERS = r'''/* H5_FPU_CACHE_HELPERS: only the sampled call-free particle math block. */
typedef struct {
    double st[8];
    int64_t i64[8];
    int top;
} h5_fpu_cache;
static inline void h5_fpu_cache_push(h5_fpu_cache *f, double value) {
    f->st[7] = f->st[6]; f->i64[7] = f->i64[6];
    f->st[6] = f->st[5]; f->i64[6] = f->i64[5];
    f->st[5] = f->st[4]; f->i64[5] = f->i64[4];
    f->st[4] = f->st[3]; f->i64[4] = f->i64[3];
    f->st[3] = f->st[2]; f->i64[3] = f->i64[2];
    f->st[2] = f->st[1]; f->i64[2] = f->i64[1];
    f->st[1] = f->st[0]; f->i64[1] = f->i64[0];
    f->st[0] = value; f->i64[0] = 0; ++f->top;
}
static inline double h5_fpu_cache_pop(h5_fpu_cache *f) {
    double value = f->st[0];
    f->st[0] = f->st[1]; f->i64[0] = f->i64[1];
    f->st[1] = f->st[2]; f->i64[1] = f->i64[2];
    f->st[2] = f->st[3]; f->i64[2] = f->i64[3];
    f->st[3] = f->st[4]; f->i64[3] = f->i64[4];
    f->st[4] = f->st[5]; f->i64[4] = f->i64[5];
    f->st[5] = f->st[6]; f->i64[5] = f->i64[6];
    f->st[6] = f->st[7]; f->i64[6] = f->i64[7];
    f->st[7] = 0.0; f->i64[7] = 0; --f->top;
    return value;
}
static inline void h5_fpu_cache_xch(h5_fpu_cache *f, int i) {
    double value = f->st[0]; f->st[0] = f->st[i]; f->st[i] = value;
    int64_t shadow = f->i64[0]; f->i64[0] = f->i64[i]; f->i64[i] = shadow;
}

'''


def baseline_region(source):
    """Read the unoptimized operations from either canonical source form."""
    if SYMBOL in source:
        function_start = source.index(SYMBOL)
        function_end = source.find("\nvoid sub_", function_start + 1)
        source = source[function_start:function_end if function_end >= 0 else len(source)]
    start = source.index(ENTRY) + len(ENTRY)
    if source.startswith(BEGIN, start):
        left = source.index(BODY, start) + len(BODY)
        right = source.index(COMMIT, left)
        region = "".join(line[4:] for line in source[left:right].splitlines(keepends=True))
        region = region.replace("_h5_fp.st", "_st")
        region = region.replace("_h5_fp.i64", "g_st_i64")
        region = region.replace("h5_fpu_cache_push(&_h5_fp, ", "fp_push(")
        region = region.replace("h5_fpu_cache_pop(&_h5_fp)", "fp_pop()")
        region = region.replace("h5_fpu_cache_xch(&_h5_fp, ", "fp_xch(")
        return region
    end = source.rfind("\n", start, source.index(END_ADDRESS, start)) + 1
    return source[start:end]


def cached_region(region):
    if hashlib.sha256(region.encode()).hexdigest() != BASELINE_SHA256:
        raise ValueError("Particle x87 cache: original generated region changed; review before reapplying")
    if re.search(r"\b(goto|return|RECOMP_\w+)\b|^L_", region, re.M):
        raise ValueError("Particle x87 cache: region is not call-free single-entry code")
    if set(re.findall(r"\b(fp_\w+)\(", region)) != {"fp_push", "fp_pop", "fp_xch", "fp_to_int"}:
        raise ValueError("Particle x87 cache: unreviewed FPU helper")
    operations = region.replace("_st[", "_h5_fp.st[")
    operations = operations.replace("g_st_i64[", "_h5_fp.i64[")
    operations = operations.replace("fp_push(", "h5_fpu_cache_push(&_h5_fp, ")
    operations = operations.replace("fp_pop()", "h5_fpu_cache_pop(&_h5_fp)")
    operations = operations.replace("fp_xch(", "h5_fpu_cache_xch(&_h5_fp, ")
    return (BEGIN +
            "        h5_fpu_cache _h5_fp;\n"
            "        memcpy(_h5_fp.st, g_st, sizeof _h5_fp.st);\n"
            "        memcpy(_h5_fp.i64, g_st_i64, sizeof _h5_fp.i64);\n"
            "        _h5_fp.top = g_fp_top;\n" + BODY +
            "".join("    " + line for line in operations.splitlines(keepends=True)) + COMMIT +
            "        memcpy(g_st, _h5_fp.st, sizeof _h5_fp.st);\n"
            "        memcpy(g_st_i64, _h5_fp.i64, sizeof _h5_fp.i64);\n"
            "        g_fp_top = _h5_fp.top;\n" + END)


def cache_particle_math_source(source):
    # Keep the existing lift_homm5.finalize_sources entry point: it visits every
    # module, so a fresh Granny lift receives the same pinned transform too.
    source = cache_granny_math_source(source)
    source = _cache_leaf_source(source, _MATRIX)
    source = _cache_leaf_source(source, _INVERSE, forward_cfg=True)
    source = _cache_leaf_source(source, _AFFINE)
    for name in THREE_BLOCK_SPECS:
        source = _cache_leaf_source(source, _scoped_spec(name))
    source = cache_pose_accum_source(source)
    source = cache_pose_cfg_source(source)
    source = cache_guarded_vector_source(source)
    source = cache_norm_guard_source(source)
    source = _cache_leaf_source(source, _PLANE)
    if SYMBOL not in source:
        return source
    if source.count(SYMBOL) != 1:
        raise ValueError("Particle x87 cache: source function is not unique")
    function_start = source.index(SYMBOL)
    function_end = source.find("\nvoid sub_", function_start + 1)
    function_end = len(source) if function_end < 0 else function_end
    function = source[function_start:function_end]
    if function.count(ENTRY) != 1:
        raise ValueError("Particle x87 cache: function entry is not unique")
    region = baseline_region(function)
    replacement = cached_region(region)
    start = function.index(ENTRY) + len(ENTRY)
    if function.startswith(BEGIN, start):
        end = function.index(END, start) + len(END)
        if function[start:end] != replacement or source.count(HELPERS) != 1:
            raise ValueError("Particle x87 cache: existing transformed source changed")
        return source
    end = start + len(region)
    function = function[:start] + replacement + function[end:]
    return source[:function_start] + HELPERS + function + source[function_end:]


def _leaf_baseline_region(source, spec):
    """Recover the pinned call-free operations, excluding unchanged transfers."""
    symbol, entry, stop, _, begin, _ = spec
    if symbol in source:
        start = source.index(symbol)
        end = source.find("\nvoid sub_", start + 1)
        source = source[start:end if end >= 0 else len(source)]
    if begin in source:
        start = source.index(begin)
        left = source.index(BODY, start) + len(BODY)
        right = source.index(COMMIT, left)
        region = "".join(line[4:] for line in source[left:right].splitlines(keepends=True))
        return (region.replace("_h5_fp.st", "_st").replace("_h5_fp.i64", "g_st_i64")
                .replace("h5_fpu_cache_push(&_h5_fp, ", "fp_push(")
                .replace("h5_fpu_cache_pop(&_h5_fp)", "fp_pop()")
                .replace("h5_fpu_cache_xch(&_h5_fp, ", "fp_xch("))
    start = _region_boundary(source, entry, after=True)
    return source[start:_region_boundary(source, stop, start=start)]


def _region_boundary(source, marker, after=False, start=0):
    position = source.index(marker, start)
    if marker.startswith("/* 0x"):
        return source.rfind("\n", 0, position) + 1
    return position + len(marker) if after else position


def _leaf_cached_region(region, spec, forward_cfg=False):
    symbol, _, _, digest, begin, end = spec
    if hashlib.sha256(region.encode()).hexdigest() != digest:
        raise ValueError(f"{symbol}: original generated x87 block changed; review before reapplying")
    if forward_cfg:
        # Only this pinned whole function has internal branches. They all move
        # forward within the cache scope; no caller can enter its interior, and
        # no transfer exposes a partially computed local FPU stack.
        labels={m[1]:m.start() for m in re.finditer(r"^(L_[0-9A-F]+):",region,re.M)}
        jumps=list(re.finditer(r"\bgoto (L_[0-9A-F]+);",region))
        if (spec != _INVERSE or set(labels) != {"L_00CF63A5","L_00CF63A9","L_00CF63AF"}
                or len(jumps) != 2 or any(labels.get(m[1],-1)<=m.start() for m in jumps)
                or re.search(r"\b(?:goto|return|RECOMP_(?!PF\b)\w+)\b",re.sub(r"\bgoto L_[0-9A-F]+;","",region))):
            raise ValueError(f"{symbol}: unreviewed x87 control-flow graph")
    elif re.search(r"\b(goto|return|RECOMP_\w+)\b|^L_", region, re.M):
        raise ValueError(f"{symbol}: x87 block is not call-free single-entry code")
    if not set(re.findall(r"\b(fp_\w+)\(", region)) <= {"fp_push", "fp_pop", "fp_xch"}:
        raise ValueError(f"{symbol}: unreviewed x87 helper")
    operations = (region.replace("_st[", "_h5_fp.st[").replace("g_st_i64[", "_h5_fp.i64[")
                  .replace("fp_push(", "h5_fpu_cache_push(&_h5_fp, ")
                  .replace("fp_pop()", "h5_fpu_cache_pop(&_h5_fp)")
                  .replace("fp_xch(", "h5_fpu_cache_xch(&_h5_fp, "))
    return (begin +
            "        h5_fpu_cache _h5_fp;\n"
            "        memcpy(_h5_fp.st, g_st, sizeof _h5_fp.st);\n"
            "        memcpy(_h5_fp.i64, g_st_i64, sizeof _h5_fp.i64);\n"
            "        _h5_fp.top = g_fp_top;\n" + BODY +
            "".join("    " + line for line in operations.splitlines(keepends=True)) + COMMIT +
            "        memcpy(g_st, _h5_fp.st, sizeof _h5_fp.st);\n"
            "        memcpy(g_st_i64, _h5_fp.i64, sizeof _h5_fp.i64);\n"
            "        g_fp_top = _h5_fp.top;\n" + end)


def _cache_leaf_source(source, spec, forward_cfg=False):
    symbol, entry, _, _, begin, end_marker = spec
    if symbol not in source:
        return source
    if source.count(symbol) != 1:
        raise ValueError(f"{symbol}: source function is not unique")
    start = source.index(symbol)
    end = source.find("\nvoid sub_", start + 1)
    end = len(source) if end < 0 else end
    function = source[start:end]
    if function.count(entry) != 1:
        raise ValueError(f"{symbol}: x87 block entry is not unique")
    region = _leaf_baseline_region(function, spec)
    replacement = _leaf_cached_region(region, spec, forward_cfg)
    if begin in function:
        left = function.index(begin)
        right = function.index(end_marker, left) + len(end_marker)
        if function[left:right] != replacement or source.count(HELPERS) != 1:
            raise ValueError(f"{symbol}: existing transformed x87 block changed")
        return source
    left = _region_boundary(function, entry, after=True)
    function = function[:left] + replacement + function[left + len(region):]
    return source[:start] + ("" if HELPERS in source else HELPERS) + function + source[end:]


def granny_baseline_region(source):
    return _leaf_baseline_region(source, _GRANNY)


def granny_cached_region(region):
    return _leaf_cached_region(region, _GRANNY)


def cache_granny_math_source(source):
    return _cache_leaf_source(source, _GRANNY)


def matrix_baseline_region(source):
    return _leaf_baseline_region(source, _MATRIX)


def matrix_cached_region(region):
    return _leaf_cached_region(region, _MATRIX)


def inverse_baseline_region(source):
    return _leaf_baseline_region(source, _INVERSE)


def inverse_cached_region(region):
    return _leaf_cached_region(region, _INVERSE, forward_cfg=True)


def affine_baseline_region(source):
    return _leaf_baseline_region(source, _AFFINE)


def affine_cached_region(region):
    return _leaf_cached_region(region, _AFFINE)


def _scoped_spec(name):
    spec = THREE_BLOCK_SPECS[name]
    return spec["symbol"],spec["start"],spec["stop"],spec["digest"],spec["begin"],spec["end"]


def scoped_baseline_region(source, name):
    return _leaf_baseline_region(source, _scoped_spec(name))


def scoped_cached_region(region, name):
    return _leaf_cached_region(region, _scoped_spec(name))


def plane_baseline_region(source):
    return _leaf_baseline_region(source, _PLANE)


def plane_cached_region(region):
    return _leaf_cached_region(region, _PLANE)


def norm_guard_baseline_region(source):
    if CF_NORM_SYMBOL in source:
        left = source.index(CF_NORM_SYMBOL)
        right = source.find("\nvoid sub_", left + 1)
        source = source[left:right if right >= 0 else len(source)]
    start = source.index(CF_NORM_ENTRY) + len(CF_NORM_ENTRY)
    if source.startswith(CF_NORM_BEGIN, start):
        left = source.index(_NORM_BASELINE, start) + len(_NORM_BASELINE)
        original = source[left:source.index(_NORM_FAST, left)]
        return original.replace("L_H5_NORM_BASE_", "L_")
    return source[start:source.index("    RECOMP_FLAGS_OUT();", start)]


def norm_guard_cached_region(region):
    if hashlib.sha256(region.encode()).hexdigest() != CF_NORM_BASELINE_SHA256:
        raise ValueError("Guarded norm: original generated operations changed")
    labels = {m[1]: m.start() for m in re.finditer(r"^(L_[0-9A-F]+):", region, re.M)}
    jumps = list(re.finditer(r"\bgoto (L_[0-9A-F]+);", region))
    if (set(labels) != {"L_00CF6E97", "L_00CF6E9E", "L_00CF6EFE", "L_00CF6F05"}
            or len(jumps) != 2 or any(labels.get(m[1], -1) <= m.start() for m in jumps)
            or re.search(r"\b(?:goto|return|RECOMP_(?!PF\b)\w+)\b",
                         re.sub(r"\bgoto L_[0-9A-F]+;", "", region))
            or set(re.findall(r"\b(fp_\w+)\(", region)) != {"fp_push", "fp_pop", "fp_xch"}
            or region.count("fp_push(") != region.count("fp_pop()") + 1):
        raise ValueError("Guarded norm: unreviewed control flow or helper")
    operations = (region.replace("_st[", "_h5_fp.st[").replace("g_st_i64[", "_h5_fp.i64[")
                  .replace("fp_push(", "h5_fpu_cache_push(&_h5_fp, ")
                  .replace("fp_pop()", "h5_fpu_cache_pop(&_h5_fp)")
                  .replace("fp_xch(", "h5_fpu_cache_xch(&_h5_fp, "))
    # The fallback is the literal original arithmetic/global-stack body. Only
    # its internal labels are renamed: C labels have function-wide scope.
    fallback = re.sub(r"\bL_([0-9A-F]+)\b", r"L_H5_NORM_BASE_\1", region)
    return (CF_NORM_BEGIN + "    if (!h5_bounded_norm_inputs(ecx, edx, esp)) {\n" +
            _NORM_BASELINE + fallback + _NORM_FAST +
            "        h5_fpu_cache _h5_fp;\n" + _POSE_INIT + operations + _POSE_COMMIT +
            "    }\n" + CF_NORM_END)


def cache_norm_guard_source(source):
    if CF_NORM_SYMBOL not in source:
        return source
    if source.count(CF_NORM_SYMBOL) != 1:
        raise ValueError("Guarded norm: source function is not unique")
    start = source.index(CF_NORM_SYMBOL)
    end = source.find("\nvoid sub_", start + 1)
    end = len(source) if end < 0 else end
    function = source[start:end]
    if function.count(CF_NORM_ENTRY) != 1:
        raise ValueError("Guarded norm: function entry is not unique")
    base = norm_guard_baseline_region(function)
    replacement = norm_guard_cached_region(base)
    left = function.index(CF_NORM_ENTRY) + len(CF_NORM_ENTRY)
    if function.startswith(CF_NORM_BEGIN, left):
        right = function.index(CF_NORM_END, left) + len(CF_NORM_END)
        if (function[left:right] != replacement or source.count(HELPERS) != 1
                or source.count(NORM_GUARD_HELPER) != 1
                or source.count("static int h5_bounded_norm_inputs(") != 1):
            raise ValueError("Guarded norm: changed applied cache body or guard")
    else:
        right = left + len(base)
        if "H5_NORM_GUARD" in source or "h5_bounded_norm_inputs" in source:
            raise ValueError("Guarded norm: unexpected existing guard helper")
    # No original branch may enter the middle of a local-stack scope.
    internal = set(re.findall(r"^(L_[0-9A-F]+):", base, re.M))
    if any(m[1] in internal for m in re.finditer(r"\bgoto (L_[0-9A-F]+);",
                                               function[:left] + function[right:])):
        raise ValueError("Guarded norm: unreviewed external entry")
    function = function[:left] + replacement + function[right:]
    source = source[:start] + function + source[end:]
    if NORM_GUARD_HELPER not in source:
        start = source.index(CF_NORM_SYMBOL)
        source = source[:start] + NORM_GUARD_HELPER + source[start:]
    if HELPERS not in source or source.index(HELPERS) > source.index(CF_NORM_SYMBOL):
        source = source.replace(HELPERS, "", 1)
        start = source.index(CF_NORM_SYMBOL)
        source = source[:start] + HELPERS + source[start:]
    return source


def pose_accum_baseline_region(source):
    if POSE_ACCUM_SYMBOL in source:
        start = source.index(POSE_ACCUM_SYMBOL)
        end = source.find("\nvoid sub_", start + 1)
        source = source[start:end if end >= 0 else len(source)]
    start = source.index(POSE_ACCUM_ENTRY) + len(POSE_ACCUM_ENTRY)
    if source.startswith(POSE_ACCUM_BEGIN, start):
        left = source.index(POSE_ACCUM_BODY, start) + len(POSE_ACCUM_BODY)
        right = source.index(POSE_ACCUM_END, left)
        region = source[left:right].replace(_POSE_COMMIT + "    RECOMP_FLAGS_OUT();", "    RECOMP_FLAGS_OUT();")
        return (region.replace("_h5_fp.st", "_st").replace("_h5_fp.i64", "g_st_i64")
                .replace("h5_fpu_cache_push(&_h5_fp, ", "fp_push(")
                .replace("h5_fpu_cache_pop(&_h5_fp)", "fp_pop()"))
    return source[start:source.rindex("    RECOMP_REGS_OUT();")]


def pose_accum_cached_region(region):
    if hashlib.sha256(region.encode()).hexdigest() != POSE_ACCUM_BASELINE_SHA256:
        raise ValueError("Granny pose accumulation: original generated operations changed")
    labels = {m[1]:m.start() for m in re.finditer(r"^(L_[0-9A-F]+):",region,re.M)}
    jumps = list(re.finditer(r"\bgoto (L_[0-9A-F]+);",region))
    returns = re.findall(r"^    RECOMP_FLAGS_OUT\(\); esp \+= 4; \{ RECOMP_REGS_OUT\(\); return; \} /\* 0x[0-9A-F]+: ret  \*/$",region,re.M)
    if (len(labels) != 12 or len(jumps) != 8 or len(returns) != 2 or region.count("return;") != 2
            or any(labels.get(m[1],-1)<=m.start() for m in jumps)
            or re.search(r"\bRECOMP_(?!(?:PF|FLAGS_OUT|REGS_OUT)\b)\w+",region)
            or set(re.findall(r"\b(fp_\w+)\(",region)) != {"fp_push","fp_pop"}):
        raise ValueError("Granny pose accumulation: unreviewed control flow or helper")
    operations = (region.replace("_st[", "_h5_fp.st[").replace("g_st_i64[", "_h5_fp.i64[")
                  .replace("fp_push(", "h5_fpu_cache_push(&_h5_fp, ")
                  .replace("fp_pop()", "h5_fpu_cache_pop(&_h5_fp)"))
    operations = operations.replace("    RECOMP_FLAGS_OUT();", _POSE_COMMIT + "    RECOMP_FLAGS_OUT();")
    return POSE_ACCUM_BEGIN + "        h5_fpu_cache _h5_fp;\n" + _POSE_INIT + POSE_ACCUM_BODY + operations + POSE_ACCUM_END


def cache_pose_accum_source(source):
    if POSE_ACCUM_SYMBOL not in source:
        return source
    if source.count(POSE_ACCUM_SYMBOL) != 1:
        raise ValueError("Granny pose accumulation: source function is not unique")
    start = source.index(POSE_ACCUM_SYMBOL)
    end = source.find("\nvoid sub_",start+1)
    end = len(source) if end<0 else end
    function = source[start:end]
    base = pose_accum_baseline_region(function)
    replacement = pose_accum_cached_region(base)
    left = function.index(POSE_ACCUM_ENTRY)+len(POSE_ACCUM_ENTRY)
    if function.startswith(POSE_ACCUM_BEGIN,left):
        right = function.index(POSE_ACCUM_END,left)+len(POSE_ACCUM_END)
        if function[left:right] != replacement or source.count(HELPERS) != 1:
            raise ValueError("Granny pose accumulation: changed applied body")
    else:
        right = left+len(base)
    function = function[:left]+replacement+function[right:]
    source = source[:start]+function+source[end:]
    # This function precedes the pose-normalization function in the same chunk.
    # Move its existing shared helpers upward rather than defining them twice.
    if HELPERS not in source or source.index(HELPERS)>source.index(POSE_ACCUM_SYMBOL):
        source = source.replace(HELPERS,"",1)
        start = source.index(POSE_ACCUM_SYMBOL)
        source = source[:start]+HELPERS+source[start:]
    return source


def guarded_vector_baseline_region(source):
    if GUARDED_VECTOR_SYMBOL in source:
        left = source.index(GUARDED_VECTOR_SYMBOL)
        right = source.find("\nvoid sub_",left+1)
        source = source[left:right if right>=0 else len(source)]
    start = source.index(GUARDED_VECTOR_ENTRY)+len(GUARDED_VECTOR_ENTRY)
    if source.startswith(GUARDED_VECTOR_BEGIN,start):
        left = source.index(_VECTOR_BASELINE,start)+len(_VECTOR_BASELINE)
        return source[left:source.index(_VECTOR_FAST,left)]
    return source[start:source.index("    RECOMP_FLAGS_OUT();",start)]


def guarded_vector_cached_region(region):
    if hashlib.sha256(region.encode()).hexdigest() != GUARDED_VECTOR_BASELINE_SHA256:
        raise ValueError("Guarded vector: original generated operations changed")
    if re.search(r"\b(goto|return|RECOMP_\w+)\b|^L_",region,re.M):
        raise ValueError("Guarded vector: unreviewed control flow")
    operations = (region.replace("_st[","_h5_fp.st[").replace("g_st_i64[","_h5_fp.i64[")
                  .replace("fp_push(","h5_fpu_cache_push(&_h5_fp, ")
                  .replace("fp_pop()","h5_fpu_cache_pop(&_h5_fp)")
                  .replace("fp_xch(","h5_fpu_cache_xch(&_h5_fp, "))
    # These seven operands are unconditionally read before the first guest
    # store. Finite float32 operands yield a finite float64 fourth-component
    # sum (three products plus translation, magnitude <2^260). Its float32
    # checkpoint can overflow to infinity, but cannot become a NaN whose bits
    # are then copied by the original integer/GPR path. All nonfinite cases
    # retain the verbatim original global-stack body, with no NaN tolerance.
    operands = ["ecx + 0x30","ecx + 0x34","ecx + 0x38","ecx + 0x3C",
                "_h5_vector_input","_h5_vector_input + 4","_h5_vector_input + 8"]
    guard = " ||\n        ".join("(MEM32("+operand+") & 0x7F800000u) == 0x7F800000u" for operand in operands)
    return (GUARDED_VECTOR_BEGIN + "    uint32_t _h5_vector_input = MEM32(esp + 8);\n"
            "    if ("+guard+") {\n" + _VECTOR_BASELINE + region + _VECTOR_FAST +
            "        h5_fpu_cache _h5_fp;\n" + _POSE_INIT + operations + _POSE_COMMIT +
            "    }\n" + GUARDED_VECTOR_END)


def cache_guarded_vector_source(source):
    if GUARDED_VECTOR_SYMBOL not in source:
        return source
    if source.count(GUARDED_VECTOR_SYMBOL) != 1:
        raise ValueError("Guarded vector: source function is not unique")
    start = source.index(GUARDED_VECTOR_SYMBOL)
    end = source.find("\nvoid sub_",start+1)
    end = len(source) if end<0 else end
    function = source[start:end]
    base = guarded_vector_baseline_region(function)
    replacement = guarded_vector_cached_region(base)
    left = function.index(GUARDED_VECTOR_ENTRY)+len(GUARDED_VECTOR_ENTRY)
    if function.startswith(GUARDED_VECTOR_BEGIN,left):
        right = function.index(GUARDED_VECTOR_END,left)+len(GUARDED_VECTOR_END)
        if function[left:right] != replacement or source.count(HELPERS) != 1:
            raise ValueError("Guarded vector: changed applied body")
    else:
        right = left+len(base)
    function = function[:left]+replacement+function[right:]
    return source[:start]+("" if HELPERS in source else HELPERS)+function+source[end:]


def _pose_spec(name):
    spec = POSE_REGIONS[name]
    return POSE_SYMBOL, spec["start"], spec["stop"], spec["sha256"], spec["begin"], spec["end"]


def pose_baseline_region(source, name):
    return _leaf_baseline_region(source, _pose_spec(name))


def pose_cached_region(region, name):
    return _leaf_cached_region(region, _pose_spec(name))


def pose_cfg_baseline_region(source):
    if POSE_SYMBOL in source:
        left = source.index(POSE_SYMBOL)
        right = source.find("\nvoid sub_", left + 1)
        source = source[left:right if right >= 0 else len(source)]
    start = source.index(POSE_CFG_ENTRY) + len(POSE_CFG_ENTRY)
    if not source.startswith(POSE_CFG_BEGIN, start):
        return source[start:source.index(POSE_CFG_STOP, start)]
    left = source.index(POSE_CFG_BODY, start) + len(POSE_CFG_BODY)
    right = source.index(POSE_CFG_END, left)
    region = source[left:right]
    region = region.replace("    goto L_H5_POSE_SCALE4;\nL_50028D1A:\n" + _POSE_INIT + "L_H5_POSE_SCALE4:\n", "L_50028D1A:\n")
    region = re.sub(r"(    if \([^\n]+\)) \{\n" + re.escape(_POSE_COMMIT) +
                    r"        goto L_50028D3A;\n    \}", r"\1 goto L_50028D3A;", region)
    region = region.replace(_POSE_COMMIT + "    goto L_50028D61;", "    goto L_50028D61;")
    return (region.replace("_h5_fp.st", "_st").replace("_h5_fp.i64", "g_st_i64")
            .replace("h5_fpu_cache_push(&_h5_fp, ", "fp_push(")
            .replace("h5_fpu_cache_pop(&_h5_fp)", "fp_pop()"))


def pose_cfg_cached_region(region):
    if hashlib.sha256(region.encode()).hexdigest() != POSE_CFG_BASELINE_SHA256:
        raise ValueError("Granny pose CFG: original generated operations changed; review before reapplying")
    labels = re.findall(r"^(L_[0-9A-F]+):", region, re.M)
    jumps = re.findall(r"\bgoto (L_[0-9A-F]+);", region)
    if (labels != ["L_50028C3A","L_50028C43","L_50028CA8","L_50028CE7","L_50028CF8","L_50028D1A"]
            or jumps != ["L_50028C43","L_50028CA8","L_50028D3A","L_50028D3A","L_50028D61"]
            or re.search(r"\b(?:return|RECOMP_(?!PF\b)\w+)\b", region)
            or set(re.findall(r"\b(fp_\w+)\(",region)) != {"fp_push","fp_pop"}):
        raise ValueError("Granny pose CFG: unreviewed control flow or FPU helper")
    operations = (region.replace("_st[", "_h5_fp.st[").replace("g_st_i64[", "_h5_fp.i64[")
                  .replace("fp_push(", "h5_fpu_cache_push(&_h5_fp, ")
                  .replace("fp_pop()", "h5_fpu_cache_pop(&_h5_fp)"))
    operations, count = re.subn(r"(    if \([^\n]+\)) goto L_50028D3A;",
                               r"\1 {\n" + _POSE_COMMIT + "        goto L_50028D3A;\n    }", operations)
    if count != 2 or operations.count("L_50028D1A:\n") != 1 or operations.count("    goto L_50028D61;") != 1:
        raise ValueError("Granny pose CFG: changed entry/exit boundaries")
    # The approximation already owns the cache. The original D42 backedge
    # enters at D1A and must reload changes made while the machine yielded.
    operations = operations.replace("L_50028D1A:\n", "    goto L_H5_POSE_SCALE4;\nL_50028D1A:\n" + _POSE_INIT + "L_H5_POSE_SCALE4:\n")
    operations = operations.replace("    goto L_50028D61;", _POSE_COMMIT + "    goto L_50028D61;")
    return POSE_CFG_BEGIN + "        h5_fpu_cache _h5_fp;\n" + _POSE_INIT + POSE_CFG_BODY + operations + POSE_CFG_END


def cache_pose_cfg_source(source):
    if POSE_SYMBOL not in source:
        return source
    if source.count(POSE_SYMBOL) != 1:
        raise ValueError("Granny pose CFG: source function is not unique")
    # Validate the exact B1 bodies before replacing them. Do not carry two
    # independent cache scopes across the same guest instructions.
    for name, spec in POSE_REGIONS.items():
        if spec["begin"] in source:
            base = pose_baseline_region(source, name)
            old = pose_cached_region(base, name)
            if source.count(old) != 1:
                raise ValueError("Granny pose CFG: changed B1 cache body")
            source = source.replace(old, base, 1)
    start = source.index(POSE_SYMBOL)
    end = source.find("\nvoid sub_", start + 1)
    end = len(source) if end < 0 else end
    function = source[start:end]
    if function.count(POSE_CFG_ENTRY) != 1 or function.count(POSE_CFG_STOP) != 1:
        raise ValueError("Granny pose CFG: changed region boundaries")
    base = pose_cfg_baseline_region(function)
    replacement = pose_cfg_cached_region(base)
    left = function.index(POSE_CFG_ENTRY) + len(POSE_CFG_ENTRY)
    if function.startswith(POSE_CFG_BEGIN, left):
        right = function.index(POSE_CFG_END, left) + len(POSE_CFG_END)
        if function[left:right] != replacement or source.count(HELPERS) != 1:
            raise ValueError("Granny pose CFG: changed applied cache body")
    else:
        right = left + len(base)
    raw_function = function[:left] + base + function[right:]
    if "L_H5_POSE_SCALE4" in raw_function:
        raise ValueError("Granny pose CFG: unreviewed internal cache-label reference")
    inside = set(re.findall(r"^(L_[0-9A-F]+):", base, re.M))
    external_entries = []
    for jump in re.finditer(r"\bgoto (L_[0-9A-F]+);[^\n]*", raw_function):
        if jump[1] in inside and not left <= jump.start() < left + len(base):
            external_entries.append(jump[0])
    if external_entries != ["goto L_50028D1A; /* 0x50028D42: jmp 0x50028d1a */"]:
        raise ValueError("Granny pose CFG: unreviewed external entry")
    function = function[:left] + replacement + function[right:]
    return source[:start] + ("" if HELPERS in source else HELPERS) + function + source[end:]


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    original = args.source.read_text(encoding="utf-8")
    transformed = cache_particle_math_source(original)
    if transformed != original:
        temporary = args.source.with_suffix(".c.tmp")
        temporary.write_text(transformed, encoding="utf-8")
        temporary.replace(args.source)
    print("Cached sampled x87 block:" if transformed != original else "Sampled x87 block already cached:", args.source)
