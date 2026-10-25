"""Execute real shader/FF teardown helpers with tracked allocations and GL IDs."""
import unittest
from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned GLuint;
typedef int GLint;
typedef struct void_com_object { int unused; } void_com_object;
typedef struct d3d_shader { void_com_object com; GLuint gl_plain; void *parse; uint8_t *bytecode, *parse_code; char *source; } d3d_shader;
static void *allocations[1024];
static unsigned next_allocation, alive;
static void *tracked_calloc(size_t count, size_t size) {
    void *p = calloc(count, size); assert(p && next_allocation < 1024);
    allocations[next_allocation++] = p; ++alive; return p;
}
static void tracked_free(void *pointer) {
    if (!pointer) return;
    for (unsigned i = next_allocation; i; --i) if (allocations[i - 1] == pointer) {
        allocations[i - 1] = NULL; --alive; free(pointer); return;
    }
    assert(!"untracked or double free");
}
#define calloc tracked_calloc
#define free tracked_free
static unsigned deleted_programs[1024], deleted_shaders[1024], unbound;
static void glDeleteProgram(GLuint program);
static void glDeleteShader(GLuint shader) { assert(shader && shader < 1024); ++deleted_shaders[shader]; }
static void glUseProgram(GLuint program) { assert(program == 0); ++unbound; }
#include "ff.h"
#include "programs.h"
static void MOJOSHADER_freeParseData(void *data) { tracked_free(data); }
#include "shader_destroy.h"
static void glDeleteProgram(GLuint program) {
    assert(program && program < 1024);
    for (ff_locs *p = locs_table[program & 63]; p; p = p->next) assert(p->program != program);
    ++deleted_programs[program];
}
static void add_locations(GLuint program) {
    ff_locs *p = calloc(1, sizeof *p); p->program = program; p->wvp = 123;
    p->next = locs_table[program & 63]; locs_table[program & 63] = p;
}
static d3d_shader *shader(GLuint plain) {
    d3d_shader *s = calloc(1, sizeof *s); s->gl_plain = plain;
    s->parse = calloc(1, 1); s->bytecode = calloc(1, 4); s->parse_code = calloc(1, 4); s->source = calloc(1, 4);
    return s;
}
static program_t *program(GLuint id, d3d_shader *vs, d3d_shader *ps) {
    program_t *p = calloc(1, sizeof *p); p->gl = id; p->vs = vs; p->ps = ps;
    p->vs_f = calloc(1, 16); p->ps_f = calloc(1, 16);
    p->vs_i = calloc(1, 16); p->ps_i = calloc(1, 16);
    p->vs_b = calloc(1, 4); p->ps_b = calloc(1, 4);
    p->vs_f_loc = calloc(1, 4); p->ps_f_loc = calloc(1, 4);
    add_locations(id); return p;
}
int main(void) {
    d3d_shader *va = shader(401), *vb = shader(402), *pa = shader(301), *pb = shader(302);
    program_t *a = program(100, va, pa), *b = program(101, va, pb), *c = program(102, vb, pb);
    a->owns_vs = 1; a->vs_gl = 201; a->ps_gl = 301;
    b->owns_ps = 1; b->ps_gl = 202; b->vs_gl = 401;
    a->next = c; c->next = b; programs[7] = a; current_program = a;
    add_locations(164);                /* same FF cache bucket as program100 */
    forget_shader(va);
    assert(programs[7] == c && c->next == NULL && current_program == NULL && unbound == 1);
    assert(deleted_programs[100] == 1 && deleted_programs[101] == 1 && !deleted_programs[102]);
    assert(deleted_shaders[201] == 1 && deleted_shaders[202] == 1);
    assert(!deleted_shaders[301] && !deleted_shaders[401]);  /* shader-owned plain stages */
    assert(locs_table[100 & 63] && locs_table[100 & 63]->program == 164);
    add_locations(100);                /* GL may reuse a deleted program name */
    assert(locs_table[100 & 63]->program == 100);
    d3d_shader_reset();
    assert(!programs[7] && deleted_programs[102] == 1 && d3d_constant_generation == 2);
    prog_cache = calloc(1, sizeof *prog_cache); prog_cache->gl = 150; add_locations(150);
    vs_cache = calloc(1, sizeof *vs_cache); vs_cache->gl = 501;
    fs_cache = calloc(1, sizeof *fs_cache); fs_cache->gl = 502;
    next_id = 99;
    d3d_ff_reset();
    assert(!prog_cache && !vs_cache && !fs_cache && next_id == 1);
    for (unsigned i = 0; i < 64; ++i) assert(!locs_table[i]);
    assert(deleted_programs[150] == 1 && deleted_shaders[501] == 1 && deleted_shaders[502] == 1);
    shader_destroy(&va->com); shader_destroy(&vb->com); shader_destroy(&pa->com); shader_destroy(&pb->com);
    assert(deleted_shaders[401] == 1 && deleted_shaders[402] == 1 && deleted_shaders[301] == 1 && deleted_shaders[302] == 1);
    d3d_shader_reset(); d3d_ff_reset();
    assert(!alive && deleted_programs[100] == 1 && deleted_shaders[201] == 1);
    printf("PASS D3D cache lifetime: %u allocations freed exactly once, shader ownership, program unlink, FF GLuint reuse, idempotent reset\n", next_allocation);
    return 0;
}
'''


def function(text, name):
    start = text.index(name)
    start = text.rfind("\n", 0, start) + 1
    body = text.index("{", start)
    depth, end = 1, body + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end] + "\n"


class D3DLifecycleTest(unittest.TestCase):
    def test_shader_cache_ownership(self):
        shaders = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
        ff = (ROOT / "android/host/d3d9_ff.c").read_text(encoding="utf-8")
        self.assertNotIn("caller frame key", shaders)
        ff_helpers = ff[ff.index("typedef struct {\n    uint32_t inputs"):ff.index("#define APPEND")]
        programs = shaders[shaders.index("typedef struct { int type, index, count; }"):shaders.index("static GLuint compile(")]
        compile_probe("d3d_lifecycle", HARNESS, {"ff.h": ff_helpers, "programs.h": programs,
                                              "shader_destroy.h": function(shaders, "static void shader_destroy(")})


if __name__ == "__main__":
    unittest.main()
