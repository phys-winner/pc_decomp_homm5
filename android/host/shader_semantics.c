/* Which Direct3D 9 semantics the vendored MojoShader gives the Shader Model 1
 * texture-matrix opcodes (reference/mojoshader/profiles/mojoshader_profile_glsl.c,
 * make_GLSL_texm_source and the TEXM3X3SPEC reflection helper).
 *
 * Upstream drops the source modifier of the normal register (`texm3x2pad t1, t0_bx2`),
 * so an unsigned normal map is used as if it were signed, and builds the
 * TEXM3X3SPEC/VSPEC reflection 2(N.E)/(N.N)N - E from component-wise products, which
 * reduces it to the eye ray. The adventure-map water (0x008988B0, PS 0x00F63A08:
 * texm3x2pad/texm3x2tex over a 4x4 animated normal map, VS 0x00F55DC8 rows
 * (0.1 sx, 0, sx) and (0, 0.1 sy, sy)) reads its screen-space texture through this
 * lookup: without the modifier a flat normal (0.5, 0.5, 1) scales the lookup by 1.05
 * away from the screen origin and the ripples lose their sign, so the texture slides
 * against the water as the view changes. PS 0x00F63868 is the texm3x3vspec case.
 *
 * Every edition uses the Direct3D 9 semantics: 1.6 and 2.1 embed the same water and
 * texm3x3vspec shaders byte for byte (1.6 PS 0x00F4D078/0x00F4CED8 with VS 0x00F3F430,
 * 2.1 PS 0x00F14C48/0x00F14AA8 with VS 0x00F07008; tests/test_texm_semantics.py). The
 * switch stays so the tests can still render MojoShader's former output. */
#include "host.h"

int void_mojoshader_texm_semantics(void)
{
    return 1;
}
