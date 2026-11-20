/* A shadow region that does not change when the camera turns (ToE 3.1 addresses; the fit,
 * its caller and globals are the same code in 1.6 and 2.1, mapped in config/{vanilla,hof}.patches.json).
 *
 * The engine's light-space fit 0x00471F60 (called from 0x00C46180 for the adventure map,
 * towns and combat) clips the camera frustum to the map box and the caster height slab,
 * projects the corners of that region along the light onto two fixed axes across it,
 * L x X and L x Y, and maps their bounding box onto the shadow textures
 * (gfx_depth_tex_resolution, 0x00F7ACF8) with 5% margins and hysteresis: bounds
 * 0x00F2D3AC..B8, rows 0x00FD285C..78, refit flag +0x80 of the fit (0x010D8890). The bounding
 * box of a turning trapezoid changes its size with the yaw. On a 2400x1080 phone the mapped
 * region jumped between 35 and 88 world units per axis within one turn, and each refit
 * renders the static shadow texture (0x00C450F0: white clear, black caster silhouettes)
 * again at another scale and texel phase, so the leafy shadows of trees change their shape
 * and density while the camera turns.
 *
 * Here the region is a square whose side bounds the region's extent at every yaw (its
 * horizontal diameter and height range do not change while the camera turns; shadow_fit.h),
 * taken from a 2^(1/8) ladder with hysteresis, and whose corner is snapped to whole texels,
 * so moving the square keeps every texel's footprint on the ground. A minimal enclosing
 * circle of the projected points is not enough: the slab's top corners are offset along the
 * light by ~13 units, and that circle changed its size by up to 19% within a turn.
 * The engine's refit flag is replaced by this decision: the static texture is drawn again
 * when the square moves or resizes, when the engine forces a refit (counter
 * 0x00F2D3A8, its caller's flag), or when the engine loads deferred textures. Rows, bounds and the engine's
 * hysteresis state are written where the engine writes them, so the caster and receiver
 * constants (0x009B8F60: c24..c27) and the cloud mapping follow unchanged.
 * <data>/shadow-fit-original containing 1 keeps the engine's own fit. */
#include "host.h"
#include "native_mode.h"
#include "touch.h"
#include <math.h>
#include <string.h>
#include "shadow_fit.h"

/* The caller's refit request, the fit's eighth stack argument in ToE 3.1 and 1.6. The 2.1 fit
 * takes seven arguments and only its counter forces a refit: config/hof.patches.json sets 0. */
#define SHADOW_FIT_REQUEST 0x1Cu

static struct {
    int active, overflow, forced;
    uint32_t fit, count;
    float light[3];
    float points[SHADOW_FIT_POINTS * 3];
} pass;

static shadow_square square;
static void_native_mode_cache engine_mode = VOID_NATIVE_MODE_CACHE_INIT;

static int shadow_textures_changed;   /* DDS and fit hooks both hold the guest machine lock */

void void_shadow_texture_loaded(void)
{
    shadow_textures_changed = 1;
}

/* ECX is the engine's fit (0x010D8810); the arguments are still on the stack: the
 * light direction at +8, the caller's refit request at SHADOW_FIT_REQUEST. */
void void_shadow_fit_begin(uint32_t fit, uint32_t esp)
{
    pass.active = 0;
    if (!void_port_shadow_fix() ||
        void_native_mode_get(&engine_mode, "shadow-fit-original", "[shadow] force engine fit %d")) {
        if (square.valid && (int32_t)MEM32(0x00F2D3A8u) < 1)
            MEM32(0x00F2D3A8u) = 1;   /* Restore the stock projection on the next fit. */
        square.valid = 0;
        return;
    }
    if (!MEM8(0x00F44E06u)) return;     /* the logarithmic warp mapping keeps the engine's fit */
    if (!void_vm_readable(esp, 0x20) || !void_vm_writable(fit, 0x84)) return;
    uint32_t light = MEM32(esp + 8);
    if (!void_vm_readable(light, 12)) return;
    memcpy(pass.light, GPTR(light), sizeof pass.light);
    pass.forced = (int32_t)MEM32(0x00F2D3A8u) > 0;
#if SHADOW_FIT_REQUEST
    if (MEM8(esp + SHADOW_FIT_REQUEST)) pass.forced = 1;
#endif
    pass.fit = fit;
    pass.count = 0;
    pass.overflow = 0;
    pass.active = 1;
}

/* Each distinct corner of the clipped region as the engine adds it to its set (0x00473D90). */
void void_shadow_fit_point(uint32_t esp)
{
    if (!pass.active) return;
    uint32_t point = MEM32(esp);
    if (pass.count >= SHADOW_FIT_POINTS || !void_vm_readable(point, 12)) { pass.overflow = 1; return; }
    memcpy(pass.points + 3u * pass.count++, GPTR(point), 12);
}

static void put_float(uint32_t va, double value)
{
    float f = (float)value;
    memcpy(GPTR(va), &f, sizeof f);
}

static void put_row(uint32_t va, const double row[4])
{
    for (int i = 0; i < 4; ++i) put_float(va + 4u * (uint32_t)i, row[i]);
}

void void_shadow_fit_end(void)
{
    if (!pass.active) return;
    pass.active = 0;
    uint32_t fit = pass.fit, texels = MEM32(0x00F7ACF8u);
    /* No region (no light, nothing visible) or an unexpected one: the engine's result stays. */
    if (!pass.count || pass.overflow || texels < 16 || texels > 8192) { square.valid = 0; return; }
    shadow_fit_input in = { pass.points, pass.count, { pass.light[0], pass.light[1], pass.light[2] },
                            texels, pass.forced, fit };
    shadow_fit_output out;
    if (!shadow_fit_solve(&square, &in, &out)) { square.valid = 0; return; }
    put_float(0x00F2D3B4u, out.u0);
    put_float(0x00F2D3B8u, out.u0 + out.side);
    put_float(0x00F2D3ACu, out.v0);
    put_float(0x00F2D3B0u, out.v0 + out.side);
    put_row(0x00FD286Cu, out.row_u);
    put_row(0x00FD285Cu, out.row_v);
    put_row(fit + 0x40, out.row_u);
    put_row(fit + 0x50, out.row_v);
    put_float(fit + 0x60, out.u0);
    put_float(fit + 0x64, out.u0 + out.side);
    put_float(fit + 0x68, out.v0);
    put_float(fit + 0x6C, out.v0 + out.side);
    int redraw = out.changed != 0;
    /* The first pass can see opaque placeholders while the foliage DDS data is pending. */
    redraw |= shadow_textures_changed;
    shadow_textures_changed = 0;
    MEM8(fit + 0x80) = (uint8_t)redraw;
    /* Menus and combat force a refit every frame and their cameras keep moving: log each new
     * side, and moves of the square at most once a second. */
    static double logged_side;
    static uint64_t logged_at;
    uint64_t now = void_perf_now_ns();
    if (void_verbose && out.changed && (out.side != logged_side || now - logged_at >= 1000000000ull)) {
        logged_side = out.side;
        logged_at = now;
        void_log("[shadow] square %s: side %.2f (step %d) for extent %.2f, corner %.3f,%.3f, %u points",
                 out.changed == 2 ? "refit" : "moved", out.side, square.step, out.extent, out.u0, out.v0, pass.count);
    }
}
