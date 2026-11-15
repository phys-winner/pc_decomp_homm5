/* The rotation-stable shadow square of shadow_fit.c, free of guest state so the
 * unit tests compile it on the PC (tests/test_shadow_fit.py). */
#ifndef VOID_SHADOW_FIT_H
#define VOID_SHADOW_FIT_H
#include <math.h>
#include <stdint.h>
#include <string.h>

/* Room for the region to move before the square is recentred, and how many 2^(1/8)
 * ladder steps the region must shrink before the square follows. */
#define SHADOW_FIT_SLACK 0.06
#define SHADOW_FIT_SHRINK 3
#define SHADOW_FIT_POINTS 1024

typedef struct {
    int valid, step;               /* side = 2^(step / 8) world units */
    uint32_t fit, texels;
    float light[3];
    double u0, v0;                 /* the corner, a whole number of texels from the axes' origin */
} shadow_square;

typedef struct {
    const float *points;           /* x, y, z of each corner of the clipped region */
    uint32_t count;
    float light[3];
    uint32_t texels;               /* the shadow textures' width */
    int forced;
    uint32_t fit;
} shadow_fit_input;

typedef struct {
    double row_u[4], row_v[4];     /* world point -> [0, 1] along each axis */
    double u0, v0, side, extent;
    int changed;                   /* 0 kept, 1 moved, 2 resized or forced */
} shadow_fit_output;

/* The axes are the engine's (0x00471F60): normalize(L x X) = (0, Lz, -Ly) for the rows at
 * 0x00FD286C and normalize(L x Y) = (-Lz, 0, Lx) for 0x00FD285C.
 *
 * Turning the camera turns its region about a vertical axis, so the region's horizontal
 * diameter D and its height range H (the caster slab) do not change. Along an axis a, two
 * points differ by at most |a.xy| D + |a.z| H, which bounds the region's extent along both
 * axes at every yaw: that bound, not the region's current box, sizes the square.
 * Returns 0 when the input cannot be fitted; the caller then keeps the engine's result. */
static int shadow_fit_solve(shadow_square *s, const shadow_fit_input *in, shadow_fit_output *out)
{
    if (!in->count || in->count > SHADOW_FIT_POINTS || in->texels < 16) return 0;
    double lx = in->light[0], ly = in->light[1], lz = in->light[2];
    double au[3] = { 0.0, lz, -ly }, av[3] = { -lz, 0.0, lx };
    double nu = sqrt(au[1] * au[1] + au[2] * au[2]), nv = sqrt(av[0] * av[0] + av[2] * av[2]);
    if (!(nu > 1e-12) || !(nv > 1e-12) || !isfinite(nu) || !isfinite(nv)) return 0;
    for (int k = 0; k < 3; ++k) { au[k] /= nu; av[k] /= nv; }
    double umin = INFINITY, umax = -INFINITY, vmin = INFINITY, vmax = -INFINITY;
    double zmin = INFINITY, zmax = -INFINITY, diameter2 = 0.0;
    for (uint32_t i = 0; i < in->count; ++i) {
        const float *p = in->points + 3u * i;
        if (!isfinite(p[0]) || !isfinite(p[1]) || !isfinite(p[2])) return 0;
        double u = au[0] * p[0] + au[1] * p[1] + au[2] * p[2];
        double v = av[0] * p[0] + av[1] * p[1] + av[2] * p[2];
        umin = fmin(umin, u); umax = fmax(umax, u);
        vmin = fmin(vmin, v); vmax = fmax(vmax, v);
        zmin = fmin(zmin, p[2]); zmax = fmax(zmax, p[2]);
        for (uint32_t j = 0; j < i; ++j) {
            const float *q = in->points + 3u * j;
            double dx = (double)p[0] - q[0], dy = (double)p[1] - q[1];
            diameter2 = fmax(diameter2, dx * dx + dy * dy);
        }
    }
    double diameter = sqrt(diameter2), height = zmax - zmin;
    double extent = fmax(sqrt(au[0] * au[0] + au[1] * au[1]) * diameter + fabs(au[2]) * height,
                         sqrt(av[0] * av[0] + av[1] * av[1]) * diameter + fabs(av[2]) * height);
    double want = fmax(extent * (1.0 + SHADOW_FIT_SLACK), 1.0);
    int need = (int)ceil(8.0 * log2(want) - 1e-9);
    if (need > 8 * 16) return 0;                 /* 65536 world units across: not a scene */
    int same = s->valid && s->fit == in->fit && s->texels == in->texels &&
               !memcmp(s->light, in->light, sizeof s->light) && !in->forced;
    int step = same ? s->step : need, changed = same ? 0 : 2;
    double side = exp2(step / 8.0), texel = side / in->texels;
    if (same && (extent + texel > side || need <= step - SHADOW_FIT_SHRINK)) {
        step = need;
        changed = 2;
        side = exp2(step / 8.0);
        texel = side / in->texels;
    }
    double u0 = s->u0, v0 = s->v0;
    if (changed || umin < u0 || umax > u0 + side || vmin < v0 || vmax > v0 + side) {
        if (!changed) changed = 1;
        u0 = floor((0.5 * (umin + umax - side)) / texel + 0.5) * texel;
        v0 = floor((0.5 * (vmin + vmax - side)) / texel + 0.5) * texel;
    }
    s->valid = 1;
    s->fit = in->fit;
    s->texels = in->texels;
    memcpy(s->light, in->light, sizeof s->light);
    s->step = step;
    s->u0 = u0;
    s->v0 = v0;
    double inv = 1.0 / side;
    for (int k = 0; k < 3; ++k) {
        out->row_u[k] = au[k] * inv;
        out->row_v[k] = av[k] * inv;
    }
    out->row_u[3] = -u0 * inv;
    out->row_v[3] = -v0 * inv;
    out->u0 = u0;
    out->v0 = v0;
    out->side = side;
    out->extent = extent;
    out->changed = changed;
    return 1;
}
#endif
