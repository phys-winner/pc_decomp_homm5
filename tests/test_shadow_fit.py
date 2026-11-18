"""The rotation-stable shadow square (android/host/shadow_fit.h) and its generated seams.

A synthetic camera region shaped like the engine's (a ground trapezoid and the corners of
the caster height slab, light as on the save_6 map) is turned about its anchor: the engine's
bounding box and the projected region's minimal enclosing circle change size, the square
does not, and its corner stays on the texel grid.

All three engines carry the seams: 1.6's fit and caller are ToE's code with other addresses
(and a smaller caller frame), 2.1's fit takes seven arguments instead of eight and has no
refit request from its caller. The adapted shadow_fit.c of every edition runs against a
synthetic guest memory and must write that edition's globals only."""
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
from build_android import guard_fpu_memory, round_x87_precision
from editions import generated_root
from port_patches import adapt_generated_source, adapt_host_source, load_contract

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include "shadow_fit.h"

static int failures;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); ++failures; } } while (0)

/* The engine's region at yaw a: ground trapezoid (near 30, far 70 wide, 45 deep) and the
 * slab top, closer to the camera, all turned about the anchor. */
static int region(double a, double ax, double ay, float *out)
{
    static const double q[][3] = {
        {-15, 6, 0.5}, {15, 6, 0.5}, {35, 51, -1.0}, {-35, 51, 2.0},
        {-12, 0, 21.0}, {12, 0, 21.0}, {25, 30, 21.0}, {-25, 30, 21.0}, {0, 51, 1.0},
    };
    int n = (int)(sizeof q / sizeof q[0]);
    double c = cos(a), s = sin(a);
    for (int i = 0; i < n; ++i) {
        out[3 * i + 0] = (float)(ax + c * q[i][0] - s * q[i][1]);
        out[3 * i + 1] = (float)(ay + s * q[i][0] + c * q[i][1]);
        out[3 * i + 2] = (float)q[i][2];
    }
    return n;
}

/* The minimal enclosing circle's radius, by brute force over pairs and triples. */
static double mec_radius(const double *u, const double *v, int n)
{
    double best = 1e300;
    for (int i = 0; i < n; ++i) for (int j = i + 1; j < n; ++j) for (int k = j; k < n; ++k) {
        double cx, cy, r2;
        if (k == j) {
            cx = 0.5 * (u[i] + u[j]); cy = 0.5 * (v[i] + v[j]);
        } else {
            double bx = u[j] - u[i], by = v[j] - v[i], qx = u[k] - u[i], qy = v[k] - v[i];
            double d = 2 * (bx * qy - by * qx);
            if (fabs(d) < 1e-12) continue;
            double b2 = bx * bx + by * by, q2 = qx * qx + qy * qy;
            cx = u[i] + (qy * b2 - by * q2) / d; cy = v[i] + (bx * q2 - qx * b2) / d;
        }
        r2 = (u[i] - cx) * (u[i] - cx) + (v[i] - cy) * (v[i] - cy);
        int all = 1;
        for (int m = 0; m < n && all; ++m)
            all = (u[m] - cx) * (u[m] - cx) + (v[m] - cy) * (v[m] - cy) <= r2 * (1 + 1e-9) + 1e-9;
        if (all && r2 < best) best = r2;
    }
    return sqrt(best);
}

int main(void)
{
    float light[3] = {0.4419f, 0.3707f, -0.8172f};       /* save_6: rows (0, -.9116, -.4103), (.8813, 0, .4727) */
    float points[64 * 3];
    shadow_square square = {0};
    double aabb_min = 1e300, aabb_max = 0, first_side = 0, mec_min = 1e300, mec_max = 0, wus[64], wvs[64];
    int resized = 0, moved = 0, frames = 0;
    for (int degree = 0; degree <= 720; degree += 2, ++frames) {
        double a = degree * 3.14159265358979323846 / 180;
        int n = region(a, 150.0 + 0.01 * degree, 120.0, points);
        shadow_fit_input in = { points, (uint32_t)n, {light[0], light[1], light[2]}, 512, 0, 0x010D8810u };
        shadow_fit_output out;
        CHECK(shadow_fit_solve(&square, &in, &out), "solve at %d", degree);
        if (!degree) { CHECK(out.changed == 2, "first fit %d", out.changed); first_side = out.side; }
        else if (out.changed == 2) ++resized;
        if (out.changed == 1) ++moved;
        CHECK(out.side == first_side, "side %.4f at %d degrees after %.4f", out.side, degree, first_side);
        double texel = out.side / 512;
        CHECK(fabs(out.u0 / texel - floor(out.u0 / texel + 0.5)) < 1e-6, "corner u %.9f off the grid", out.u0);
        CHECK(fabs(out.v0 / texel - floor(out.v0 / texel + 0.5)) < 1e-6, "corner v %.9f off the grid", out.v0);
        double lo_u = 1e300, hi_u = -1e300, lo_v = 1e300, hi_v = -1e300;
        for (int i = 0; i < n; ++i) {
            const float *p = points + 3 * i;
            double tu = out.row_u[0] * p[0] + out.row_u[1] * p[1] + out.row_u[2] * p[2] + out.row_u[3];
            double tv = out.row_v[0] * p[0] + out.row_v[1] * p[1] + out.row_v[2] * p[2] + out.row_v[3];
            CHECK(tu >= 0 && tu <= 1 && tv >= 0 && tv <= 1, "point %d at (%.4f, %.4f), %d degrees", i, tu, tv, degree);
            double wu = tu * out.side + out.u0, wv = tv * out.side + out.v0;
            wus[i] = wu; wvs[i] = wv;
            if (wu < lo_u) lo_u = wu; if (wu > hi_u) hi_u = wu;
            if (wv < lo_v) lo_v = wv; if (wv > hi_v) hi_v = wv;
        }
        /* What the engine maps: the bounding box, +10% */
        double extent = (hi_u - lo_u > hi_v - lo_v ? hi_u - lo_u : hi_v - lo_v) * 1.1;
        if (extent < aabb_min) aabb_min = extent;
        if (extent > aabb_max) aabb_max = extent;
        double radius = mec_radius(wus, wvs, n);
        if (radius < mec_min) mec_min = radius;
        if (radius > mec_max) mec_max = radius;
    }
    CHECK(resized == 0, "%d resizes while turning", resized);
    CHECK(moved > 0 && moved < frames / 2, "%d moves in %d frames", moved, frames);
    CHECK(aabb_max / aabb_min > 1.25, "the engine's box varied only %.3fx", aabb_max / aabb_min);
    CHECK(mec_max / mec_min > 1.1, "the enclosing circle varied only %.3fx", mec_max / mec_min);
    CHECK(first_side < 1.25 * aabb_max, "square %.2f against the engine's largest box %.2f", first_side, aabb_max);

    /* A texel keeps its ground footprint when the square moves: texel coordinates of a fixed
     * point differ by whole texels between two corners. */
    {
        shadow_square s = {0};
        float p0[64 * 3], q0[64 * 3];
        int n = region(0.3, 150, 120, p0);
        shadow_fit_input in = { p0, (uint32_t)n, {light[0], light[1], light[2]}, 512, 0, 1 };
        shadow_fit_output a, b;
        shadow_fit_solve(&s, &in, &a);
        int m = region(0.3, 190, 160, q0);
        in.points = q0; in.count = (uint32_t)m;
        shadow_fit_solve(&s, &in, &b);
        CHECK(b.changed == 1 && b.side == a.side, "move changed %d side %.3f/%.3f", b.changed, a.side, b.side);
        const float w[3] = {171.25f, 133.5f, 3.75f};
        double ta = (a.row_u[0] * w[0] + a.row_u[1] * w[1] + a.row_u[2] * w[2] + a.row_u[3]) * 512;
        double tb = (b.row_u[0] * w[0] + b.row_u[1] * w[1] + b.row_u[2] * w[2] + b.row_u[3]) * 512;
        CHECK(fabs((ta - tb) - floor(ta - tb + 0.5)) < 1e-6, "texel phase %.9f", ta - tb);
    }

    /* Hysteresis: a 10% smaller region keeps the side, 40% smaller shrinks it; a forced
     * refit, another light or texture size refit. */
    {
        shadow_square s = {0};
        float p[64 * 3];
        int n = region(0, 0, 0, p);
        shadow_fit_input in = { p, (uint32_t)n, {light[0], light[1], light[2]}, 512, 0, 1 };
        shadow_fit_output out;
        shadow_fit_solve(&s, &in, &out);
        double side = out.side;
        for (int i = 0; i < 3 * n; ++i) p[i] *= 0.9f;
        shadow_fit_solve(&s, &in, &out);
        CHECK(out.changed != 2 && out.side == side, "10%% smaller: changed %d side %.3f", out.changed, out.side);
        for (int i = 0; i < 3 * n; ++i) p[i] *= 0.6f / 0.9f;
        shadow_fit_solve(&s, &in, &out);
        CHECK(out.changed == 2 && out.side < side, "40%% smaller: changed %d side %.3f", out.changed, out.side);
        in.forced = 1;
        shadow_fit_solve(&s, &in, &out);
        CHECK(out.changed == 2, "forced: changed %d", out.changed);
        in.forced = 0; in.light[0] = 0.5f;
        shadow_fit_solve(&s, &in, &out);
        CHECK(out.changed == 2, "light: changed %d", out.changed);
        in.texels = 1024;
        shadow_fit_solve(&s, &in, &out);
        CHECK(out.changed == 2, "texels: changed %d", out.changed);
        float flat[3] = {1, 0, 0};
        shadow_fit_input bad = { p, (uint32_t)n, {flat[0], flat[1], flat[2]}, 512, 0, 1 };
        CHECK(!shadow_fit_solve(&s, &bad, &out), "a horizontal light along X has no U axis");
        p[0] = NAN;
        CHECK(!shadow_fit_solve(&s, &in, &out), "NaN point");
    }
    printf("shadow fit: %d frames, %d moves, engine box %.1f..%.1f, circle %.1f..%.1f, square %.1f\n",
           frames, moved, aabb_min, aabb_max, 2 * mec_min, 2 * mec_max, first_side);
    return failures != 0;
}
"""

# The fit's caller and the fit itself in each engine: begin and end around the caller's call,
# one point per corner the fit adds to its set.
SEAM_FUNCTIONS = {
    "toe": {"caller": "sub_00C46180", "fit": "sub_00471F60", "arguments": 8},
    "vanilla": {"caller": "sub_0098E8C0", "fit": "sub_00A66950", "arguments": 8},
    "hof": {"caller": "sub_00C03730", "fit": "sub_00A31BC0", "arguments": 7},
}
BEGIN, END, POINT = "void_shadow_fit_begin(ecx, esp);", "void_shadow_fit_end();", "void_shadow_fit_point(esp);"
# The ToE globals shadow_fit.c names; the legacy contracts map each of them.
GLOBALS = ("00F44E06", "00F2D3A8", "00F2D3AC", "00F2D3B0", "00F2D3B4", "00F2D3B8", "00FD285C", "00FD286C", "00F7ACF8")


def seams(edition):
    functions = SEAM_FUNCTIONS[edition]
    return {functions["caller"]: (BEGIN, END), functions["fit"]: (POINT,)}


def function_bodies(edition, names):
    """The contract-patched and the plain x87-rounded generated bodies of `names` in one engine."""
    folder = generated_root(edition) / "game-x86"
    report = json.loads((folder / "report.json").read_text())
    bodies = {}
    for name in report["sources"]:
        text = (folder / name).read_bytes()
        if not any(b"void %s(void) {" % f.encode() in text for f in names):
            continue
        rounded = round_x87_precision(guard_fpu_memory(text))
        patched = adapt_generated_source(rounded, "game", edition)
        for function in names:
            declaration = b"void %s(void) {" % function.encode()
            start = patched.find(declaration)
            if start >= 0:
                original = rounded[rounded.index(declaration):]
                bodies[function] = (patched[start:patched.index(b"\n}", start)],
                                    original[:original.index(b"\n}")])
    return bodies


ADAPTED_HOST = r"""
#ifndef PROBE_HOST_H
#define PROBE_HOST_H
#include <stdint.h>
#include <string.h>
extern uint8_t *guest;
#define GPTR(a) ((void *)(guest + (uint32_t)(a)))
#define MEM8(a) (*(uint8_t *)GPTR(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
int void_vm_readable(uint32_t address, uint32_t size);
int void_vm_writable(uint32_t address, uint32_t size);
uint64_t void_perf_now_ns(void);
void void_log(const char *format, ...);
extern int void_verbose;
#endif
"""

ADAPTED_MODE = r"""
#ifndef PROBE_NATIVE_MODE_H
#define PROBE_NATIVE_MODE_H
typedef int void_native_mode_cache;
#define VOID_NATIVE_MODE_CACHE_INIT (-1)
extern int probe_engine_fit;
static int void_native_mode_get(void_native_mode_cache *cache, const char *file, const char *format)
{
    (void)cache; (void)file; (void)format;
    return probe_engine_fit;
}
#endif
"""

ADAPTED_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include "host.h"
#define GUEST_SIZE 0x02000000u
uint8_t *guest;
int void_verbose, probe_engine_fit;
int void_vm_readable(uint32_t address, uint32_t size) { return address >= 0x1000u && (uint64_t)address + size <= GUEST_SIZE; }
int void_vm_writable(uint32_t address, uint32_t size) { return void_vm_readable(address, size); }
uint64_t void_perf_now_ns(void) { return 0; }
void void_log(const char *format, ...) { (void)format; }
#include "shadow_fit_adapted.c"

static int failures;
#define CHECK(c, ...) do { if (!(c)) { printf("FAIL %d: ", __LINE__); printf(__VA_ARGS__); printf("\n"); ++failures; } } while (0)

static float getf(uint32_t va) { float f; memcpy(&f, GPTR(va), 4); return f; }

static const uint32_t esp = 0x01800000u, light_va = 0x01810000u, fit = 0x01820000u,
                      point_va = 0x01830000u, point_esp = 0x01840000u;
static float points[9 * 3];

/* One engine pass: the caller's begin, the fit's corners, the caller's end. */
static void pass_once(int n)
{
    void_shadow_fit_begin(fit, esp);
    for (int i = 0; i < n; ++i) {
        memcpy(GPTR(point_va), points + 3 * i, 12);
        MEM32(point_esp) = point_va;
        void_shadow_fit_point(point_esp);
    }
    void_shadow_fit_end();
}

int main(void)
{
    static const double q[][3] = {
        {-15, 6, 0.5}, {15, 6, 0.5}, {35, 51, -1.0}, {-35, 51, 2.0},
        {-12, 0, 21.0}, {12, 0, 21.0}, {25, 30, 21.0}, {-25, 30, 21.0}, {0, 51, 1.0},
    };
    const int n = 9;
    for (int i = 0; i < n; ++i) {
        points[3 * i] = (float)(150 + 0.8 * q[i][0] - 0.6 * q[i][1]);
        points[3 * i + 1] = (float)(120 + 0.6 * q[i][0] + 0.8 * q[i][1]);
        points[3 * i + 2] = (float)q[i][2];
    }
    float light[3] = {0.4419f, 0.3707f, -0.8172f};
    guest = (uint8_t *)calloc(1, GUEST_SIZE);
    if (!guest) return 2;
    memcpy(GPTR(light_va), light, 12);
    MEM32(esp + 8) = light_va;
    MEM8(LINEAR) = 1;
    MEM32(TEXELS) = 512;

    shadow_square reference = {0};
    shadow_fit_input in = { points, (uint32_t)n, {light[0], light[1], light[2]}, 512, 0, fit };
    shadow_fit_output want;
    CHECK(shadow_fit_solve(&reference, &in, &want), "reference square");

    pass_once(n);
    CHECK(getf(U0) == (float)want.u0 && getf(U1) == (float)(want.u0 + want.side), "u bounds %.4f..%.4f", getf(U0), getf(U1));
    CHECK(getf(V0) == (float)want.v0 && getf(V1) == (float)(want.v0 + want.side), "v bounds %.4f..%.4f", getf(V0), getf(V1));
    for (int k = 0; k < 4; ++k) {
        CHECK(getf(ROW_U + 4u * (uint32_t)k) == (float)want.row_u[k], "row u %d", k);
        CHECK(getf(ROW_V + 4u * (uint32_t)k) == (float)want.row_v[k], "row v %d", k);
        CHECK(getf(fit + 0x40 + 4u * (uint32_t)k) == (float)want.row_u[k], "fit row u %d", k);
        CHECK(getf(fit + 0x50 + 4u * (uint32_t)k) == (float)want.row_v[k], "fit row v %d", k);
    }
    CHECK(getf(fit + 0x60) == getf(U0) && getf(fit + 0x64) == getf(U1) &&
          getf(fit + 0x68) == getf(V0) && getf(fit + 0x6C) == getf(V1), "fit bounds");
    CHECK(MEM8(fit + 0x80) == 1, "first square refits: %d", MEM8(fit + 0x80));

    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 0, "the same region keeps the texture: %d", MEM8(fit + 0x80));

    float stable_u0 = getf(U0), stable_v0 = getf(V0);
    void_shadow_texture_loaded();
    void_shadow_texture_loaded();
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 1, "deferred textures refresh the same shadow region");
    CHECK(getf(U0) == stable_u0 && getf(V0) == stable_v0, "texture loads keep the shadow projection");
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 0, "the loads are consumed by one shadow pass");

    /* ToE 3.1 and 1.6: the caller's eighth argument forces a refit; 2.1 has no such argument. */
    MEM8(esp + 0x1C) = 1;
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == REQUEST_FORCES, "caller request: %d", MEM8(fit + 0x80));
    MEM8(esp + 0x1C) = 0;
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 0, "request cleared: %d", MEM8(fit + 0x80));

    /* The engine's own counter forces a refit in every edition. */
    MEM32(COUNTER) = 1;
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 1, "counter: %d", MEM8(fit + 0x80));
    MEM32(COUNTER) = 0;

    /* The engine's fit stays with shadow-fit-original and in the warp mapping. */
    float u0 = getf(U0);
    probe_engine_fit = 1;
    MEM8(fit + 0x80) = 0x5A;
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 0x5A && getf(U0) == u0, "shadow-fit-original keeps the engine's result");
    probe_engine_fit = 0;
    MEM8(LINEAR) = 0;
    pass_once(n);
    CHECK(MEM8(fit + 0x80) == 0x5A && getf(U0) == u0, "warp mapping keeps the engine's result");
    MEM8(LINEAR) = 1;

#if CHECK_TOE_UNTOUCHED
    /* ToE's globals are other data in this engine. */
    for (uint32_t va = 0x00F2D3A8u; va < 0x00F2D3BCu; ++va) CHECK(MEM8(va) == 0, "ToE bounds %08X written", va);
    for (uint32_t va = 0x00FD285Cu; va < 0x00FD2880u; ++va) CHECK(MEM8(va) == 0, "ToE rows %08X written", va);
#endif
    printf("adapted shadow fit (%s): side %.2f corner %.3f,%.3f\n", EDITION_NAME, want.side, want.u0, want.v0);
    return failures != 0;
}
"""


class ShadowFitTest(unittest.TestCase):
    def test_square_is_rotation_stable(self):
        header = (ROOT / "android/host/shadow_fit.h").read_text(encoding="utf-8")
        compile_probe("shadow_fit", HARNESS, {"shadow_fit.h": header})

    def test_seams_are_plain_calls_in_every_contract(self):
        for edition in SEAM_FUNCTIONS:
            with self.subTest(edition=edition):
                contract = load_contract(edition)
                expected = seams(edition)
                patches = [p for p in contract["generated_patches"] if p["function"] in expected]
                self.assertEqual(sorted(p["function"] for p in patches),
                                 sorted(name for name, calls in expected.items() for _ in calls))
                calls = [call for p in patches for call in expected[p["function"]] if call in p["new"]]
                self.assertEqual(len(calls), 3)
                for patch in patches:
                    added = patch["new"].replace(patch["old"], "")
                    # PGO profile hashes count control flow; the seams add only declarations and calls.
                    self.assertIsNone(re.search(r"\b(if|for|while|do|switch|goto|return)\b|\?|&&|\|\|", added), added)
                    self.assertIn(patch["old"], patch["new"])
                for name in ("android/host/shadow_fit.c", "android/host/shadow_fit.h", "android/host/shader_semantics.c"):
                    self.assertIn(name, contract["sources"])
                    self.assertIn(name, contract["features"]["shadows"])
                if edition != "toe":
                    self.assertEqual(sorted(contract["reference_addresses"]["android/host/shadow_fit.c"]), sorted(GLOBALS))
                    self.assertTrue(all(address in contract["addresses"] for address in GLOBALS))

    def test_seams_apply_once_to_the_generated_bodies(self):
        for edition in SEAM_FUNCTIONS:
            with self.subTest(edition=edition):
                expected = seams(edition)
                bodies = function_bodies(edition, expected)
                found = {name: [body.count(call.encode()) for call in expected[name]]
                         for name, (body, _) in bodies.items()}
                self.assertEqual(found, {name: [1] * len(calls) for name, calls in expected.items()})
                functions = SEAM_FUNCTIONS[edition]
                original = bodies[functions["caller"]][1]
                fit = bodies[functions["fit"]][1]
                # The fit's stack arguments: ret 0x20 in ToE/1.6, ret 0x1c in 2.1 (no caller request).
                returns = set(re.findall(rb": ret (0x[0-9a-f]+) \*/", fit))
                self.assertEqual(returns, {b"0x%x" % (4 * functions["arguments"])})
                # The caller pushes exactly those arguments after copying the light direction
                # (+0x60 of its object); the third from the top is the copy's address (lea esp+N).
                call = original.index(b"RECOMP_CALL(" + functions["fit"].encode() + b");")
                window = original[original.rindex(b"[esi + 0x60] */", 0, call):call]
                pushes = re.findall(rb"PUSH32\(esp, (\w+)\);", window)
                self.assertEqual(len(pushes), functions["arguments"])
                light = pushes[-3]
                before = window[:[m.start() for m in re.finditer(rb"PUSH32\(esp, (\w+)\);", window)][-3]]
                assignments = re.findall(rb"(?m)^    (\w+) = ([^;]*);", before)
                last = [value for name, value in assignments if name == light][-1]
                self.assertRegex(last.decode(), r"^esp \+ 0x[0-9A-F]+u?$")

    def test_adapted_host_writes_each_editions_globals(self):
        header = (ROOT / "android/host/shadow_fit.h").read_text(encoding="utf-8")
        for edition in SEAM_FUNCTIONS:
            with self.subTest(edition=edition):
                out = Path(tempfile.mkdtemp(prefix="shadow-fit-" + edition + "-"))
                try:
                    source, _ = adapt_host_source(ROOT / "android/host/shadow_fit.c", out, edition)
                    adapted = source.read_text(encoding="utf-8")
                finally:
                    shutil.rmtree(out, ignore_errors=True)
                addresses = load_contract(edition)["addresses"] if edition != "toe" else {}
                mapped = {name: int(addresses.get(name, name), 16) for name in GLOBALS}
                if edition != "toe":
                    self.assertNotIn("HOMM5_LEGACY_UI", adapted)
                for value in mapped.values():
                    self.assertIn("0x%08X" % value, adapted)
                defines = {"LINEAR": mapped["00F44E06"], "COUNTER": mapped["00F2D3A8"],
                           "V0": mapped["00F2D3AC"], "V1": mapped["00F2D3B0"], "U0": mapped["00F2D3B4"],
                           "U1": mapped["00F2D3B8"], "ROW_V": mapped["00FD285C"], "ROW_U": mapped["00FD286C"],
                           "TEXELS": mapped["00F7ACF8"]}
                prefix = "".join("#define %s 0x%08Xu\n" % item for item in defines.items())
                prefix += '#define EDITION_NAME "%s"\n' % edition
                prefix += "#define REQUEST_FORCES %d\n" % int(SEAM_FUNCTIONS[edition]["arguments"] == 8)
                prefix += "#define CHECK_TOE_UNTOUCHED %d\n" % int(edition != "toe")
                compile_probe("shadow-fit-adapted-" + edition, prefix + ADAPTED_HARNESS,
                              {"shadow_fit.h": header, "host.h": ADAPTED_HOST, "native_mode.h": ADAPTED_MODE,
                               "shadow_fit_adapted.c": adapted})


if __name__ == "__main__":
    unittest.main()
