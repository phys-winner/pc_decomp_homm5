/* The Direct3D 9 fixed-function pipeline as generated GLSL ES 3.10.
 *
 * The vertex and pixel halves are generated separately, so either can stand
 * in for a missing shader: no shaders at all, a pixel shader fed by
 * fixed-function vertex processing (pre-transformed post-processing quads),
 * or a vertex shader feeding the texture stage cascade. The halves talk
 * through MojoShader's varying names, io_<usage>_<index>: diffuse io_10_0,
 * specular io_10_1, texture coordinate n io_5_n. Coordinates follow the
 * MojoShader path: targets rendered Y-flipped, D3D depth range, D3D9
 * half-pixel offset. */
#include "d3d9_internal.h"
#include <math.h>

enum { IN_POS = 1, IN_POST = 2, IN_NORMAL = 4, IN_DIFFUSE = 8, IN_SPECULAR = 16 };
enum { SAMPLER_2D, SAMPLER_CUBE, SAMPLER_3D };
enum { TCI_PASSTHRU, TCI_NORMAL, TCI_POSITION, TCI_REFLECTION, TCI_SPHEREMAP };

/* Vertex half: everything its generated shader depends on. */
typedef struct {
    uint32_t inputs, bgra;            /* IN_*; bit 0 diffuse, bit 1 specular stored as D3DCOLOR */
    uint32_t tex_dims[8];             /* components of each texcoord set in the vertex, 0 if absent */
    uint32_t tc_set[8], tc_mode[8], tc_flags[8];   /* per output coordinate: TEXCOORDINDEX and transform flags */
    uint32_t lighting, lights, diffuse_from_vertex;
    uint32_t outputs[16];             /* varyings written: usage << 8 | index */
    uint32_t output_count;
} ff_vkey;

/* Pixel half. */
typedef struct {
    uint32_t stages[8][6];            /* colorop, arg1, arg2, alphaop, arg1, arg2 */
    uint32_t sampler[8];              /* SAMPLER_* */
    uint32_t project[8];              /* component the coordinate is divided by (1..4), 0 for none */
    uint32_t stage_count;
    uint32_t specular;
    uint32_t available;               /* varyings provided: bit 0 diffuse, 1 specular, 2 + n texcoord n */
} ff_fkey;

typedef struct ff_vs { ff_vkey key; GLuint gl; uint32_t id; struct ff_vs *next; } ff_vs;
typedef struct ff_fs { ff_fkey key; GLuint gl; uint32_t id; struct ff_fs *next; } ff_fs;
typedef struct ff_prog { uint32_t vid, fid; GLuint gl; struct ff_prog *next; } ff_prog;
typedef struct ff_locs {
    GLuint program;
    GLint wvp, world_view, vp, half, material, ambient, light_dir, light_diffuse, tex_matrix;
    GLint tfactor, alpha_func, alpha_ref;
    struct ff_locs *next;
} ff_locs;

static ff_vs *vs_cache;
static ff_fs *fs_cache;
static ff_prog *prog_cache;
static ff_locs *locs_table[64];
static uint32_t next_id = 1;

void d3d_ff_forget_program(GLuint program)
{
    ff_locs **slot = &locs_table[program & 63];
    while (*slot) {
        ff_locs *p = *slot;
        if (p->program == program) { *slot = p->next; free(p); }
        else slot = &p->next;
    }
}

void d3d_ff_reset(void)
{
    while (prog_cache) {
        ff_prog *p = prog_cache; prog_cache = p->next;
        d3d_ff_forget_program(p->gl); glDeleteProgram(p->gl); free(p);
    }
    while (vs_cache) {
        ff_vs *p = vs_cache; vs_cache = p->next;
        glDeleteShader(p->gl); free(p);
    }
    while (fs_cache) {
        ff_fs *p = fs_cache; fs_cache = p->next;
        glDeleteShader(p->gl); free(p);
    }
    for (int i = 0; i < 64; ++i) {
        while (locs_table[i]) { ff_locs *p = locs_table[i]; locs_table[i] = p->next; free(p); }
    }
    next_id = 1;
}

#define APPEND(buf, n, ...) ((n) += (size_t)snprintf((buf) + (n), sizeof(buf) - (n), __VA_ARGS__))

/* ------------------------------------------------------------ helpers */
static GLuint compile_ff(GLenum type, const char *src)
{
    GLuint sh = glCreateShader(type);
    glShaderSource(sh, 1, &src, NULL);
    glCompileShader(sh);
    GLint ok = 0;
    glGetShaderiv(sh, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024];
        glGetShaderInfoLog(sh, sizeof log, NULL, log);
        void_log("[ff] GLSL compile failed: %s\n%s", log, src);
        glDeleteShader(sh);
        return 0;
    }
    return sh;
}

static void mul(const float *a, const float *b, float *r)
{
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) {
        float s = 0;
        for (int k = 0; k < 4; ++k) s += a[i * 4 + k] * b[k * 4 + j];
        r[i * 4 + j] = s;
    }
}

static uint32_t decl_dims(uint8_t type)
{
    switch (type) {
    case 0: return 1;                                     /* FLOAT1 */
    case 1: case 6: case 9: case 11: case 15: return 2;   /* FLOAT2, SHORT2, SHORT2N, USHORT2N, FLOAT16_2 */
    case 2: return 3;                                     /* FLOAT3 */
    default: return 4;
    }
}

/* The io_<usage>_<index> varyings a MojoShader GLSL source declares with
 * the given qualifier ("in" for a pixel shader, "out" for a vertex shader). */
static uint32_t scan_varyings(const char *src, const char *qualifier, uint32_t *list, uint32_t cap)
{
    char pattern[32];
    snprintf(pattern, sizeof pattern, "%s highp vec4 io_", qualifier);
    uint32_t count = 0;
    for (const char *p = src ? strstr(src, pattern) : NULL; p && count < cap; p = strstr(p + 1, pattern)) {
        unsigned usage, index;
        if (sscanf(p + strlen(pattern), "%u_%u", &usage, &index) == 2) list[count++] = usage << 8 | index;
    }
    return count;
}

/* ------------------------------------------------------- vertex half */
static int vertex_inputs(d3d_device *d, ff_vkey *k)
{
    d3d_decl *decl = (d3d_decl *)d->st.decl;
    if (!decl) return 0;
    for (int i = 0; i < decl->count; ++i) {
        const d3d_vertex_element *e = &decl->elements[i];
        if (e->type >= 17) continue;
        switch (e->usage) {
        case 0: if (e->usage_index == 0) k->inputs |= IN_POS; break;
        case 9: if (e->usage_index == 0) k->inputs |= IN_POST; break;
        case 3: if (e->usage_index == 0) k->inputs |= IN_NORMAL; break;
        case 10:
            if (e->usage_index == 0) { k->inputs |= IN_DIFFUSE; if (e->type == 4) k->bgra |= 1; }
            else if (e->usage_index == 1) { k->inputs |= IN_SPECULAR; if (e->type == 4) k->bgra |= 2; }
            break;
        case 5: if (e->usage_index < 8) k->tex_dims[e->usage_index] = decl_dims(e->type); break;
        default: break;
        }
    }
    if (!(k->inputs & (IN_POS | IN_POST))) return 0;
    if (k->inputs & IN_POST) k->inputs &= ~(uint32_t)(IN_POS | IN_NORMAL);
    return 1;
}

static int vertex_key(d3d_device *d, ff_vkey *k, const uint32_t *outputs, uint32_t output_count)
{
    memset(k, 0, sizeof *k);
    if (!vertex_inputs(d, k)) return 0;
    int post = (k->inputs & IN_POST) != 0;
    k->lighting = d->st.rs[137] && !post;                          /* D3DRS_LIGHTING */
    if (k->lighting) {
        for (int i = 0; i < 8; ++i) if (d->st.light_enable[i]) ++k->lights;
        /* COLORVERTEX with DIFFUSEMATERIALSOURCE = COLOR1 */
        k->diffuse_from_vertex = (k->inputs & IN_DIFFUSE) && d->st.rs[141] && d->st.rs[145] == 1;
    }
    for (uint32_t i = 0; i < output_count && i < 16; ++i) {
        k->outputs[k->output_count++] = outputs[i];
        if (outputs[i] >> 8 != 5 || (outputs[i] & 0xFF) >= 8) continue;
        uint32_t n = outputs[i] & 0xFF, tci = d->st.tss[n][11], flags = d->st.tss[n][24];
        k->tc_set[n] = tci & 7;
        k->tc_mode[n] = post ? TCI_PASSTHRU : (tci >> 16) & 0xF;
        if (k->tc_mode[n] > TCI_SPHEREMAP) k->tc_mode[n] = TCI_PASSTHRU;
        /* Transformed vertices and COUNT1 take no matrix (as Wine's compute_texture_matrix). */
        uint32_t count = flags & 0xFF;
        k->tc_flags[n] = (post || count < 2) ? 0 : (flags & 0x1FF);
        if (k->tc_mode[n] != TCI_PASSTHRU && !(k->inputs & IN_NORMAL) && k->tc_mode[n] != TCI_POSITION)
            k->tc_mode[n] = TCI_PASSTHRU;
    }
    return 1;
}

static GLuint vertex_shader(const ff_vkey *k)
{
    char src[16384];
    size_t n = 0;
    APPEND(src, n, "#version 310 es\nprecision highp float;\n"
        "uniform mat4 ff_wvp;\nuniform mat4 ff_world_view;\nuniform vec4 ff_vp;\nuniform vec2 ff_half;\n"
        "uniform vec4 ff_material[4];\nuniform vec4 ff_ambient;\nuniform vec4 ff_light_dir[8];\n"
        "uniform vec4 ff_light_diffuse[8];\nuniform mat4 ff_tex_matrix[8];\n"
        "layout(location = 0) in vec4 ff_a_pos;\n");
    if (k->inputs & IN_NORMAL) APPEND(src, n, "layout(location = 1) in vec3 ff_a_normal;\n");
    if (k->inputs & IN_DIFFUSE) APPEND(src, n, "layout(location = 2) in vec4 ff_a_diffuse;\n");
    if (k->inputs & IN_SPECULAR) APPEND(src, n, "layout(location = 3) in vec4 ff_a_specular;\n");
    for (uint32_t i = 0; i < 8; ++i)
        if (k->tex_dims[i]) APPEND(src, n, "layout(location = %u) in vec4 ff_a_tex%u;\n", 4 + i, i);
    for (uint32_t i = 0; i < k->output_count; ++i)
        APPEND(src, n, "out highp vec4 io_%u_%u;\n", k->outputs[i] >> 8, k->outputs[i] & 0xFF);
    APPEND(src, n, "void main() {\n");
    int camera = 0;
    for (uint32_t i = 0; i < k->output_count; ++i) {
        uint32_t o = k->outputs[i];
        if (o >> 8 == 5 && (o & 0xFF) < 8 && k->tc_mode[o & 0xFF] != TCI_PASSTHRU) camera = 1;
    }
    if (k->inputs & IN_POST) {
        /* Pre-transformed: screen pixels, D3D depth and 1/w. */
        APPEND(src, n,
            "\tfloat w = ff_a_pos.w != 0.0 ? 1.0 / ff_a_pos.w : 1.0;\n"
            "\tgl_Position = vec4((ff_a_pos.x - ff_vp.x) / ff_vp.z * 2.0 - 1.0,\n"
            "\t                   1.0 - (ff_a_pos.y - ff_vp.y) / ff_vp.w * 2.0, ff_a_pos.z, 1.0) * w;\n");
    } else {
        /* D3D row vectors: the matrices are uploaded row-major untransposed, so M * v here is v * M there. */
        APPEND(src, n, "\tgl_Position = ff_wvp * vec4(ff_a_pos.xyz, 1.0);\n");
        if (camera || k->lighting) {
            APPEND(src, n, "\tvec4 ec_pos = ff_world_view * vec4(ff_a_pos.xyz, 1.0);\n");
            if (k->inputs & IN_NORMAL)
                APPEND(src, n, "\tvec3 ec_normal = normalize((ff_world_view * vec4(ff_a_normal, 0.0)).xyz);\n");
        }
    }
    /* D3D -> GL: flip into D3D-ordered targets, depth range, half pixel. */
    APPEND(src, n,
        "\tgl_Position.y = -gl_Position.y;\n"
        "\tgl_Position.z = gl_Position.z * 2.0 - gl_Position.w;\n"
        "\tgl_Position.xy += ff_half * gl_Position.w;\n");
    const char *diffuse_in = (k->inputs & IN_DIFFUSE) ? ((k->bgra & 1) ? "ff_a_diffuse.bgra" : "ff_a_diffuse") : "vec4(1.0)";
    const char *specular_in = (k->inputs & IN_SPECULAR) ? ((k->bgra & 2) ? "ff_a_specular.bgra" : "ff_a_specular") : "vec4(0.0)";
    if (k->lighting) {
        /* Directional lights; without a normal only emissive and ambient remain. */
        APPEND(src, n, "\tvec4 md = %s;\n", k->diffuse_from_vertex ? diffuse_in : "ff_material[0]");
        APPEND(src, n, "\tvec4 lit = ff_material[3] + ff_ambient * ff_material[1];\n");
        if (k->inputs & IN_NORMAL)
            for (uint32_t i = 0; i < k->lights; ++i)
                APPEND(src, n, "\tlit += ff_light_diffuse[%u] * md * max(0.0, dot(ec_normal, -ff_light_dir[%u].xyz));\n", i, i);
        APPEND(src, n, "\tlit.a = md.a;\n\tvec4 diffuse = clamp(lit, 0.0, 1.0);\n\tvec4 specular = vec4(0.0);\n");
    } else {
        APPEND(src, n, "\tvec4 diffuse = %s;\n\tvec4 specular = %s;\n", diffuse_in, specular_in);
    }
    for (uint32_t i = 0; i < k->output_count; ++i) {
        uint32_t usage = k->outputs[i] >> 8, index = k->outputs[i] & 0xFF;
        if (usage == 10 && index < 2) {
            APPEND(src, n, "\tio_10_%u = %s;\n", index, index ? "specular" : "diffuse");
            continue;
        }
        if (usage != 5 || index >= 8) {
            APPEND(src, n, "\tio_%u_%u = vec4(0.0);\n", usage, index);
            continue;
        }
        uint32_t set = k->tc_set[index], dims = k->tex_dims[set];
        char in[160];
        switch (k->tc_mode[index]) {
        case TCI_NORMAL: snprintf(in, sizeof in, "vec4(ec_normal, 1.0)"); break;
        case TCI_POSITION: snprintf(in, sizeof in, "vec4(ec_pos.xyz, 1.0)"); break;
        case TCI_REFLECTION: snprintf(in, sizeof in, "vec4(reflect(normalize(ec_pos.xyz), ec_normal), 1.0)"); break;
        case TCI_SPHEREMAP:
            snprintf(in, sizeof in, "ff_sphere(reflect(normalize(ec_pos.xyz), ec_normal))");
            break;
        default:
            if (!dims) snprintf(in, sizeof in, "vec4(0.0, 0.0, 0.0, 1.0)");
            else if (!k->tc_flags[index]) snprintf(in, sizeof in, "ff_a_tex%u", set);
            /* D3D pads a short coordinate with 1.0 right after its last component. */
            else if (dims == 1) snprintf(in, sizeof in, "vec4(ff_a_tex%u.x, 1.0, 0.0, 0.0)", set);
            else if (dims == 2) snprintf(in, sizeof in, "vec4(ff_a_tex%u.xy, 1.0, 0.0)", set);
            else if (dims == 3) snprintf(in, sizeof in, "vec4(ff_a_tex%u.xyz, 1.0)", set);
            else snprintf(in, sizeof in, "ff_a_tex%u", set);
            break;
        }
        if (k->tc_flags[index] && k->tc_mode[index] != TCI_SPHEREMAP)
            APPEND(src, n, "\tio_5_%u = ff_tex_matrix[%u] * %s;\n", index, index, in);
        else
            APPEND(src, n, "\tio_5_%u = %s;\n", index, in);
    }
    APPEND(src, n, "}\n");
    if (strstr(src, "ff_sphere(")) {
        /* Sphere map: r.xy / (2 |r + (0,0,1)|) + 0.5, declared ahead of main. */
        char full[17000];
        const char *mainp = strstr(src, "void main()");
        size_t head = (size_t)(mainp - src);
        memcpy(full, src, head);
        snprintf(full + head, sizeof full - head,
            "vec4 ff_sphere(vec3 r) { float m = 2.0 * sqrt(r.x * r.x + r.y * r.y + (r.z + 1.0) * (r.z + 1.0));\n"
            "\treturn vec4(r.x / m + 0.5, r.y / m + 0.5, 0.0, 1.0); }\n%s", mainp);
        return compile_ff(GL_VERTEX_SHADER, full);
    }
    return compile_ff(GL_VERTEX_SHADER, src);
}

static ff_vs *vertex_half(const ff_vkey *k)
{
    for (ff_vs *v = vs_cache; v; v = v->next) if (!memcmp(&v->key, k, sizeof *k)) return v;
    GLuint gl = vertex_shader(k);
    if (!gl) return NULL;
    ff_vs *v = (ff_vs *)calloc(1, sizeof *v);
    v->key = *k;
    v->gl = gl;
    v->id = next_id++;
    v->next = vs_cache;
    vs_cache = v;
    void_log("[ff] vertex half %u: inputs %X lighting %u lights %u outputs %u", v->id, k->inputs, k->lighting,
        k->lights, k->output_count);
    return v;
}

/* -------------------------------------------------------- pixel half */
/* A texture stage argument (D3DTA_*) as a vec4 expression. */
static void arg_expr(char *out, size_t cap, uint32_t arg, uint32_t stage)
{
    const char *base;
    switch (arg & 0xF) {
    case 0: base = "v_diffuse"; break;                     /* DIFFUSE */
    case 2: base = "t"; break;                             /* TEXTURE */
    case 3: base = "ff_tfactor"; break;                    /* TFACTOR */
    case 4: base = "v_specular"; break;                    /* SPECULAR */
    case 5: base = "temp"; break;                          /* TEMP */
    default: base = stage ? "current" : "v_diffuse"; break; /* CURRENT (stage 0: diffuse) */
    }
    char inner[64];
    if (arg & 0x20) snprintf(inner, sizeof inner, "vec4(%s.a)", base);      /* ALPHAREPLICATE */
    else snprintf(inner, sizeof inner, "%s", base);
    if (arg & 0x10) snprintf(out, cap, "(vec4(1.0) - %s)", inner);       /* COMPLEMENT */
    else snprintf(out, cap, "%s", inner);
}

/* A texture stage operation (D3DTOP_*) as a vec4 expression. */
static void op_expr(char *out, size_t cap, uint32_t op, const char *a1, const char *a2, uint32_t stage)
{
    const char *cur = stage ? "current" : "v_diffuse";
    switch (op) {
    case 2: snprintf(out, cap, "%s", a1); break;                                       /* SELECTARG1 */
    case 3: snprintf(out, cap, "%s", a2); break;                                       /* SELECTARG2 */
    case 4: snprintf(out, cap, "%s * %s", a1, a2); break;                              /* MODULATE */
    case 5: snprintf(out, cap, "%s * %s * 2.0", a1, a2); break;                        /* MODULATE2X */
    case 6: snprintf(out, cap, "%s * %s * 4.0", a1, a2); break;                        /* MODULATE4X */
    case 7: snprintf(out, cap, "%s + %s", a1, a2); break;                              /* ADD */
    case 8: snprintf(out, cap, "%s + %s - 0.5", a1, a2); break;                        /* ADDSIGNED */
    case 9: snprintf(out, cap, "(%s + %s - 0.5) * 2.0", a1, a2); break;                /* ADDSIGNED2X */
    case 10: snprintf(out, cap, "%s - %s", a1, a2); break;                             /* SUBTRACT */
    case 11: snprintf(out, cap, "%s + %s * (vec4(1.0) - %s)", a1, a2, a1); break;      /* ADDSMOOTH */
    case 12: snprintf(out, cap, "mix(%s, %s, v_diffuse.a)", a2, a1); break;            /* BLENDDIFFUSEALPHA */
    case 13: snprintf(out, cap, "mix(%s, %s, t.a)", a2, a1); break;                    /* BLENDTEXTUREALPHA */
    case 14: snprintf(out, cap, "mix(%s, %s, ff_tfactor.a)", a2, a1); break;           /* BLENDFACTORALPHA */
    case 15: snprintf(out, cap, "%s + %s * (1.0 - t.a)", a1, a2); break;               /* BLENDTEXTUREALPHAPM */
    case 16: snprintf(out, cap, "mix(%s, %s, %s.a)", a2, a1, cur); break;              /* BLENDCURRENTALPHA */
    case 18: snprintf(out, cap, "%s + vec4(%s.a) * %s", a1, a1, a2); break;            /* MODULATEALPHA_ADDCOLOR */
    case 19: snprintf(out, cap, "vec4((%s * %s).rgb, (%s).a + (%s).a)", a1, a2, a1, a2); break; /* MODULATECOLOR_ADDALPHA */
    case 20: snprintf(out, cap, "%s + vec4(1.0 - (%s).a) * %s", a1, a1, a2); break;   /* MODULATEINVALPHA_ADDCOLOR */
    case 21: snprintf(out, cap, "vec4(((vec4(1.0) - %s) * %s).rgb, (%s).a + (%s).a)", a1, a2, a1, a2); break;
    case 24: snprintf(out, cap, "vec4(clamp(dot((%s).rgb - 0.5, (%s).rgb - 0.5) * 4.0, 0.0, 1.0))", a1, a2); break;
    default: snprintf(out, cap, "%s * %s", a1, a2); break;
    }
}

/* available: the varyings the vertex half provides (ff_fkey.available bits). */
static void pixel_key(d3d_device *d, ff_fkey *k, uint32_t available, int vertex_shader_set)
{
    memset(k, 0, sizeof *k);
    k->available = available;
    k->specular = d->st.rs[29] != 0;                               /* D3DRS_SPECULARENABLE */
    for (uint32_t s = 0; s < 8; ++s) {
        const uint32_t *t = d->st.tss[s];
        if (t[1] == 1) break;                                      /* COLOROP DISABLE ends the cascade */
        k->stages[s][0] = t[1]; k->stages[s][1] = t[2]; k->stages[s][2] = t[3];
        k->stages[s][3] = t[4]; k->stages[s][4] = t[5]; k->stages[s][5] = t[6];
        d3d_texture *tex = (d3d_texture *)d->st.textures[s];
        k->sampler[s] = !tex ? SAMPLER_2D : tex->rtype == D3DRTYPE_CUBETEXTURE ? SAMPLER_CUBE
                      : tex->rtype == D3DRTYPE_VOLUMETEXTURE ? SAMPLER_3D : SAMPLER_2D;
        uint32_t flags = t[24], count = flags & 0xFF;
        if ((flags & 0x100) && count >= 2 && count <= 4) k->project[s] = count;
        else if ((flags & 0x100) && vertex_shader_set) k->project[s] = 4;
        k->stage_count = s + 1;
    }
    if (!(available & 2)) k->specular = 0;
}

static GLuint pixel_shader(const ff_fkey *k)
{
    char src[16384];
    size_t n = 0;
    APPEND(src, n, "#version 310 es\nprecision highp float;\nprecision highp sampler2D;\n"
        "precision highp samplerCube;\nprecision highp sampler3D;\n"
        "uniform vec4 ff_tfactor;\nuniform int vpAlphaFunc;\nuniform float vpAlphaRef;\n"
        "layout(location = 0) out highp vec4 ff_color;\n");
    if (k->available & 1) APPEND(src, n, "in highp vec4 io_10_0;\n");
    if (k->available & 2) APPEND(src, n, "in highp vec4 io_10_1;\n");
    for (uint32_t s = 0; s < k->stage_count; ++s) {
        static const char *const kinds[3] = { "sampler2D", "samplerCube", "sampler3D" };
        if (k->available & (4u << s)) APPEND(src, n, "in highp vec4 io_5_%u;\n", s);
        APPEND(src, n, "uniform %s ff_s%u;\n", kinds[k->sampler[s]], s);
    }
    APPEND(src, n, "void main() {\n\tvec4 v_diffuse = %s;\n\tvec4 v_specular = %s;\n",
        (k->available & 1) ? "io_10_0" : "vec4(1.0)", (k->available & 2) ? "io_10_1" : "vec4(0.0)");
    APPEND(src, n, "\tvec4 current = v_diffuse;\n\tvec4 temp = vec4(0.0);\n\tvec4 t = vec4(0.0);\n\tvec4 tc;\n");
    for (uint32_t s = 0; s < k->stage_count; ++s) {
        const uint32_t *st = k->stages[s];
        if (k->available & (4u << s)) APPEND(src, n, "\ttc = io_5_%u;\n", s);
        else APPEND(src, n, "\ttc = vec4(0.0, 0.0, 0.0, 1.0);\n");
        if (k->project[s]) APPEND(src, n, "\ttc.xyz /= tc.%c;\n", "xyzw"[k->project[s] - 1]);
        if (k->sampler[s] == SAMPLER_2D) APPEND(src, n, "\tt = texture(ff_s%u, tc.xy);\n", s);
        else APPEND(src, n, "\tt = texture(ff_s%u, tc.xyz);\n", s);
        char a1[128], a2[128], color[512], alpha[512];
        arg_expr(a1, sizeof a1, st[1], s);
        arg_expr(a2, sizeof a2, st[2], s);
        op_expr(color, sizeof color, st[0], a1, a2, s);
        if (st[3] == 1) {
            snprintf(alpha, sizeof alpha, "current");              /* ALPHAOP DISABLE: alpha passes through */
        } else {
            arg_expr(a1, sizeof a1, st[4], s);
            arg_expr(a2, sizeof a2, st[5], s);
            op_expr(alpha, sizeof alpha, st[3], a1, a2, s);
        }
        APPEND(src, n, "\t{ vec4 c = %s; vec4 a = %s; current = clamp(vec4(c.rgb, a.a), 0.0, 1.0); }\n", color, alpha);
    }
    if (k->specular) APPEND(src, n, "\tcurrent.rgb = clamp(current.rgb + v_specular.rgb, 0.0, 1.0);\n");
    APPEND(src, n,
        "\tfloat a = floor(clamp(current.a, 0.0, 1.0) * 255.0 + 0.5);\n\tbool pass = true;\n"
        "\tif (vpAlphaFunc == 1) pass = false; else if (vpAlphaFunc == 2) pass = a < vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 3) pass = a == vpAlphaRef; else if (vpAlphaFunc == 4) pass = a <= vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 5) pass = a > vpAlphaRef; else if (vpAlphaFunc == 6) pass = a != vpAlphaRef;\n"
        "\telse if (vpAlphaFunc == 7) pass = a >= vpAlphaRef;\n"
        "\tif (!pass) discard;\n\tff_color = current;\n}\n");
    return compile_ff(GL_FRAGMENT_SHADER, src);
}

static ff_fs *pixel_half(const ff_fkey *k)
{
    for (ff_fs *f = fs_cache; f; f = f->next) if (!memcmp(&f->key, k, sizeof *k)) return f;
    GLuint gl = pixel_shader(k);
    if (!gl) return NULL;
    ff_fs *f = (ff_fs *)calloc(1, sizeof *f);
    f->key = *k;
    f->gl = gl;
    f->id = next_id++;
    f->next = fs_cache;
    fs_cache = f;
    void_log("[ff] pixel half %u: stages %u available %X", f->id, k->stage_count, k->available);
    return f;
}

/* ---------------------------------------------------------- uniforms */
/* Uniform locations of a program holding a generated half. The program must
 * be current: samplers are assigned their units on first use. */
static ff_locs *locations(GLuint program)
{
    ff_locs **slot = &locs_table[program & 63];
    for (ff_locs *l = *slot; l; l = l->next) if (l->program == program) return l;
    ff_locs *l = (ff_locs *)calloc(1, sizeof *l);
    l->program = program;
    l->wvp = glGetUniformLocation(program, "ff_wvp");
    l->world_view = glGetUniformLocation(program, "ff_world_view");
    l->vp = glGetUniformLocation(program, "ff_vp");
    l->half = glGetUniformLocation(program, "ff_half");
    l->material = glGetUniformLocation(program, "ff_material");
    l->ambient = glGetUniformLocation(program, "ff_ambient");
    l->light_dir = glGetUniformLocation(program, "ff_light_dir");
    l->light_diffuse = glGetUniformLocation(program, "ff_light_diffuse");
    l->tex_matrix = glGetUniformLocation(program, "ff_tex_matrix");
    l->tfactor = glGetUniformLocation(program, "ff_tfactor");
    l->alpha_func = glGetUniformLocation(program, "vpAlphaFunc");
    l->alpha_ref = glGetUniformLocation(program, "vpAlphaRef");
    for (int s = 0; s < 8; ++s) {
        char name[8];
        snprintf(name, sizeof name, "ff_s%d", s);
        GLint loc = glGetUniformLocation(program, name);
        if (loc >= 0) glUniform1i(loc, s);
    }
    l->next = *slot;
    *slot = l;
    return l;
}

static void vertex_uniforms(d3d_device *d, const ff_locs *l)
{
    if (l->wvp >= 0 || l->world_view >= 0) {
        float world_view[16], wvp[16];
        mul(d->st.transforms[256], d->st.transforms[2], world_view);   /* WORLD * VIEW */
        mul(world_view, d->st.transforms[3], wvp);                     /* * PROJECTION */
        if (l->wvp >= 0) glUniformMatrix4fv(l->wvp, 1, GL_FALSE, wvp);
        if (l->world_view >= 0) glUniformMatrix4fv(l->world_view, 1, GL_FALSE, world_view);
    }
    if (l->vp >= 0) glUniform4f(l->vp, (float)d->st.viewport[0], (float)d->st.viewport[1],
        d->st.viewport[2] ? (float)d->st.viewport[2] : 1.0f, d->st.viewport[3] ? (float)d->st.viewport[3] : 1.0f);
    if (l->half >= 0) glUniform2f(l->half, d->st.viewport[2] ? 1.0f / (float)d->st.viewport[2] : 0.0f,
        d->st.viewport[3] ? 1.0f / (float)d->st.viewport[3] : 0.0f);
    if (l->tex_matrix >= 0) glUniformMatrix4fv(l->tex_matrix, 8, GL_FALSE, d->st.transforms[16]);
    if (l->material >= 0) {
        /* D3DMATERIAL9: Diffuse, Ambient, Specular, Emissive (then Power). */
        glUniform4fv(l->material, 4, d->st.material);
        uint32_t amb = d->st.rs[139];
        if (l->ambient >= 0) glUniform4f(l->ambient, ((amb >> 16) & 255) / 255.0f, ((amb >> 8) & 255) / 255.0f,
            (amb & 255) / 255.0f, (amb >> 24) / 255.0f);
        float dirs[32] = {0}, diffuse[32] = {0};
        int n = 0;
        for (int i = 0; i < 8 && n < 8; ++i) {
            if (!d->st.light_enable[i]) continue;
            /* D3DLIGHT9: Type, Diffuse[4], Specular[4], Ambient[4], Position[3], Direction[3], ... */
            const float *lt = d->st.lights[i];
            memcpy(&diffuse[4 * n], &lt[1], 16);
            float dir[4] = { lt[16], lt[17], lt[18], 0.0f }, v[4] = {0};
            for (int c = 0; c < 4; ++c) for (int r = 0; r < 4; ++r) v[c] += dir[r] * d->st.transforms[2][r * 4 + c];
            float len = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]);
            for (int c = 0; c < 3; ++c) dirs[4 * n + c] = len > 0 ? v[c] / len : 0;
            ++n;
        }
        if (l->light_dir >= 0) glUniform4fv(l->light_dir, 8, dirs);
        if (l->light_diffuse >= 0) glUniform4fv(l->light_diffuse, 8, diffuse);
    }
}

static void pixel_uniforms(d3d_device *d, const ff_locs *l, int alpha_test)
{
    uint32_t tf = d->st.rs[60];                                    /* D3DRS_TEXTUREFACTOR */
    if (l->tfactor >= 0) glUniform4f(l->tfactor, ((tf >> 16) & 255) / 255.0f, ((tf >> 8) & 255) / 255.0f,
        (tf & 255) / 255.0f, (tf >> 24) / 255.0f);
    if (alpha_test) {
        if (l->alpha_func >= 0) glUniform1i(l->alpha_func, d->st.rs[15] ? (int)d->st.rs[25] : 8);
        if (l->alpha_ref >= 0) glUniform1f(l->alpha_ref, (float)(d->st.rs[24] & 0xFF));
    }
}

/* ------------------------------------------------------------ public */
/* Attribute locations of the vertex half: 0 position, 1 normal, 2 diffuse,
 * 3 specular, 4.. texcoord sets. POSITION falls back to POSITIONT. */
void d3d_ff_attributes(int *attr_count, int *usage, int *index)
{
    int count = 0;
    usage[count] = 0; index[count] = 0; ++count;
    usage[count] = 3; index[count] = 0; ++count;
    usage[count] = 10; index[count] = 0; ++count;
    usage[count] = 10; index[count] = 1; ++count;
    for (int i = 0; i < 8; ++i) { usage[count] = 5; index[count] = i; ++count; }
    *attr_count = count;
}

void d3d_shader_forget_current(void);

/* No shaders: both halves generated. */
int d3d_ff_bind(d3d_device *d, int *attr_count, int *usage, int *index, uint32_t *stage_mask)
{
    ff_fkey fk;
    pixel_key(d, &fk, 0, 0);
    uint32_t outputs[10], count = 0, available = 3;
    outputs[count++] = 10u << 8; outputs[count++] = 10u << 8 | 1u;
    for (uint32_t s = 0; s < fk.stage_count; ++s) { outputs[count++] = 5u << 8 | s; available |= 4u << s; }
    ff_vkey vk;
    if (!vertex_key(d, &vk, outputs, count)) return 0;
    pixel_key(d, &fk, available, 0);
    ff_vs *v = vertex_half(&vk);
    ff_fs *f = v ? pixel_half(&fk) : NULL;
    if (!f) return 0;
    ff_prog *p = prog_cache;
    while (p && !(p->vid == v->id && p->fid == f->id)) p = p->next;
    if (!p) {
        GLuint gl = glCreateProgram();
        glAttachShader(gl, v->gl);
        glAttachShader(gl, f->gl);
        glLinkProgram(gl);
        GLint ok = 0;
        glGetProgramiv(gl, GL_LINK_STATUS, &ok);
        if (!ok) {
            char log[1024];
            glGetProgramInfoLog(gl, sizeof log, NULL, log);
            void_log("[ff] link failed: %s", log);
            glDeleteProgram(gl);
            return 0;
        }
        p = (ff_prog *)calloc(1, sizeof *p);
        p->vid = v->id; p->fid = f->id; p->gl = gl;
        p->next = prog_cache;
        prog_cache = p;
    }
    d3d_shader_forget_current();
    glUseProgram(p->gl);
    const ff_locs *l = locations(p->gl);
    vertex_uniforms(d, l);
    pixel_uniforms(d, l, 1);
    d3d_ff_attributes(attr_count, usage, index);
    *stage_mask = (1u << fk.stage_count) - 1u;
    return 1;
}

/* A vertex half for the pixel shader whose GLSL is `ps_source`: it writes
 * every io_ varying the pixel shader reads. Returns the shader object and an
 * id naming it (0 when the state cannot be drawn). */
GLuint d3d_ff_vertex_stage(d3d_device *d, const char *ps_source, uint32_t *id)
{
    uint32_t outputs[16];
    uint32_t count = scan_varyings(ps_source, "in", outputs, 16);
    ff_vkey vk;
    *id = 0;
    if (!vertex_key(d, &vk, outputs, count)) return 0;
    ff_vs *v = vertex_half(&vk);
    if (!v) return 0;
    *id = v->id;
    return v->gl;
}

/* A pixel half fed by the vertex shader whose GLSL is `vs_source`. */
GLuint d3d_ff_pixel_stage(d3d_device *d, const char *vs_source, uint32_t *id, uint32_t *stage_mask)
{
    uint32_t outputs[32];
    uint32_t count = scan_varyings(vs_source, "out", outputs, 32), available = 0;
    for (uint32_t i = 0; i < count; ++i) {
        uint32_t usage = outputs[i] >> 8, index = outputs[i] & 0xFF;
        if (usage == 10 && index < 2) available |= 1u << index;
        else if (usage == 5 && index < 8) available |= 4u << index;
    }
    ff_fkey fk;
    pixel_key(d, &fk, available, 1);
    ff_fs *f = pixel_half(&fk);
    *id = 0;
    if (!f) return 0;
    *id = f->id;
    *stage_mask = (1u << fk.stage_count) - 1u;
    return f->gl;
}

/* Per-draw uniforms of the generated half (halves) of the current program. */
void d3d_ff_uniforms(d3d_device *d, GLuint program, int vertex, int pixel)
{
    const ff_locs *l = locations(program);
    if (vertex) vertex_uniforms(d, l);
    if (pixel) pixel_uniforms(d, l, 0);
}
