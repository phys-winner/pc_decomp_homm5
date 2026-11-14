/* World-space battlefield routes, projected by the game's existing render worker. */
typedef struct { unsigned count; float points[COMBAT_ROUTE_FLOATS]; } combat_route_snapshot;
static combat_route_snapshot combat_route_game;
static GLuint combat_route_program;
static int combat_route_failed;
static GLint combat_route_corners, combat_route_metrics, combat_route_target, combat_route_style, combat_route_tint;
enum { COMBAT_ROUTE_BATCH = 32 };

/* Game thread only; Present copies this bounded payload into its render command. */
void d3d_gl_combat_route(const float *route, unsigned count)
{
    combat_route_game.count = 0;
    if (!route || count < 23 || count > COMBAT_ROUTE_FLOATS) return;
    for (unsigned i = 0; i < count; ++i) if (!isfinite(route[i])) return;
    if ((route[0] != 0 && route[0] != 1 && route[0] != 2) ||
        route[1] < 0 || route[1] > COMBAT_ROUTE_MAX_POINTS ||
        (route[2] != 0 && route[2] != 1 && route[2] != 4) ||
        route[3] < 0 || route[3] > COMBAT_ROUTE_MAX_TARGETS) return;
    unsigned points = (unsigned)route[1], quads = (unsigned)route[2], arrows = (unsigned)route[3];
    if ((float)points != route[1] || (float)arrows != route[3] ||
        (!!points != (route[0] != 0)) || (!points && quads) || (!points && !arrows) ||
        count != 20 + 3*(points + 4*quads + (arrows ? arrows + 1 : 0))) return;
    memcpy(combat_route_game.points, route, count * sizeof(float));
    combat_route_game.count = count;
}

static GLuint combat_route_shader(GLenum type, const char *source)
{
    GLuint shader = glCreateShader(type);
    glShaderSource(shader, 1, &source, NULL);
    glCompileShader(shader);
    GLint ok = 0; glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[1024]; glGetShaderInfoLog(shader, sizeof log, NULL, log);
        void_log("[combat-route] shader failed: %s", log);
        glDeleteShader(shader); return 0;
    }
    return shader;
}

static GLuint combat_route_link(void)
{
    if (combat_route_program || combat_route_failed) return combat_route_program;
    const char *vertex = "#version 310 es\nprecision highp float;\n"
        "uniform vec2 corners[128],metrics[32],target;out vec2 position,uv;flat out vec2 segment;"
        "void main(){const int order[6]=int[6](0,1,3,3,1,2);int item=gl_VertexID/6;int corner=order[gl_VertexID%6];"
        "position=corners[item*4+corner];segment=metrics[item];uv=vec2(corner==1||corner==2?1.0:0.0,corner>=2?1.0:0.0);"
        "gl_Position=vec4(position/target*vec2(2.0,-2.0)+vec2(-1.0,1.0),0.0,1.0);}";
    const char *fragment = "#version 310 es\nprecision highp float;\n"
        "uniform vec2 corners[128];uniform vec4 style,tint;in vec2 position,uv;flat in vec2 segment;layout(location=0)out vec4 color;"
        "float edge(vec2 a,vec2 b){vec2 d=b-a;return abs(d.x*(position.y-a.y)-d.y*(position.x-a.x))/max(length(d),0.001);}"
        "void main(){if(style.x>0.0){float head=min(segment.x*0.45,14.0*style.w),base=segment.x-head;"
        "vec2 p=vec2(uv.x*segment.x,(uv.y-0.5)*2.0*segment.y);"
        "float shaft=min(min(p.x,base+head*0.68-p.x),segment.y*0.32-abs(p.y));"
        "float tip=min(p.x-base,(head*(segment.y-abs(p.y))-segment.y*(p.x-base))/length(vec2(head,segment.y)));"
        "float d=max(shaft,tip),aa=max(fwidth(d),0.5),border=0.65*style.w;"
        "color=vec4(mix(vec3(0.055,0.035,0.012),tint.rgb,smoothstep(border-aa*0.5,border+aa*0.5,d)),"
        "tint.a*smoothstep(-aa*0.5,aa*0.5,d));}"
        "else if(segment.x<0.0){float d=min(min(edge(corners[0],corners[1]),edge(corners[1],corners[2])),"
        "min(edge(corners[2],corners[3]),edge(corners[3],corners[0])));"
        "color=mix(vec4(0.451,0.780,0.698,0.141),tint,1.0-smoothstep(style.w,style.w+1.0,d));}"
        "else{float p=mod(segment.y+uv.x*segment.x-style.y,15.0*style.w);"
        "float a=smoothstep(0.0,0.75,p)*(1.0-smoothstep(8.0*style.w-0.75,8.0*style.w,p));"
        "a*=1.0-smoothstep(style.z-0.75,style.z,abs(uv.y-0.5)*2.0*style.z);color=vec4(tint.rgb,tint.a*a);}}";
    GLuint vs = combat_route_shader(GL_VERTEX_SHADER, vertex), fs = combat_route_shader(GL_FRAGMENT_SHADER, fragment);
    GLuint program = vs && fs ? glCreateProgram() : 0;
    if (program) {
        glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
        GLint ok = 0; glGetProgramiv(program, GL_LINK_STATUS, &ok);
        if (!ok) {
            char log[1024]; glGetProgramInfoLog(program, sizeof log, NULL, log);
            void_log("[combat-route] link failed: %s", log);
            glDeleteProgram(program); program = 0;
        }
    }
    if (vs) glDeleteShader(vs);
    if (fs) glDeleteShader(fs);
    combat_route_failed = !program;
    if (program) {
        combat_route_corners = glGetUniformLocation(program, "corners");
        combat_route_metrics = glGetUniformLocation(program, "metrics");
        combat_route_target = glGetUniformLocation(program, "target");
        combat_route_style = glGetUniformLocation(program, "style");
        combat_route_tint = glGetUniformLocation(program, "tint");
    }
    return combat_route_program = program;
}

/* Bounded miters give neighbouring segments the same corners, without spikes on sharp bends. */
static void combat_route_miters(const float points[][2], unsigned count, float miters[][2])
{
    for (unsigned i = 0; i < count; ++i) {
        unsigned a = i ? i-1 : i, b = i+1 < count ? i+1 : i;
        float px = points[i][0]-points[a][0], py = points[i][1]-points[a][1], pl = hypotf(px, py);
        float nx = points[b][0]-points[i][0], ny = points[b][1]-points[i][1], nl = hypotf(nx, ny);
        if (!pl) { px = nx; py = ny; pl = nl; }
        if (!nl) { nx = px; ny = py; nl = pl; }
        float x = -py/pl - ny/nl, y = px/pl + nx/nl;
        float length = hypotf(x, y), divisor = length > .001f ? (x*(-ny/nl) + y*(nx/nl)) : 0;
        float factor = divisor > .001f ? fminf(1/divisor, 2.5f/length) : 0;
        miters[i][0] = factor ? x*factor : -ny/nl;
        miters[i][1] = factor ? y*factor : nx/nl;
    }
}

static void combat_route_batch_draw(const float *corners, const float *metrics, unsigned count)
{
    glUniform2fv(combat_route_corners, (GLsizei)(4*count), corners);
    glUniform2fv(combat_route_metrics, (GLsizei)count, metrics);
    glDrawArrays(GL_TRIANGLES, 0, (GLsizei)(6*count)); ++draw_calls;
}

/* The immutable packet contains no guest addresses and needs no game-thread calls. */
static int combat_route_project(const combat_route_snapshot *route, float xy[][2])
{
    const float *m = route->points + 4, *world = route->points + 20;
    unsigned count = (route->count - 20) / 3;
    for (unsigned i = 0; i < count; ++i) {
        const float *p = world + 3*i;
        float w = m[12]*p[0] + m[13]*p[1] + m[14]*p[2] + m[15];
        if (!isfinite(w) || w <= 0) return 0;
        float x = .5f * (1 + (m[0]*p[0] + m[1]*p[1] + m[2]*p[2] + m[3]) / w);
        float y = .5f * (1 - (m[4]*p[0] + m[5]*p[1] + m[6]*p[2] + m[7]) / w);
        if (!isfinite(x) || !isfinite(y) || x < -1 || x > 2 || y < -1 || y > 2) return 0;
        xy[i][0] = x; xy[i][1] = y;
    }
    return 1;
}

static void combat_route_draw(d3d_device *dev, const combat_route_snapshot *route, int x, int y, int w, int h)
{
    float projected[COMBAT_ROUTE_WORLD_POINTS][2];
    if (!route->count || w <= 0 || h <= 0 || !combat_route_project(route, projected) || !combat_route_link()) return;
    /* The complete frame blit erases old dashes even when the game reuses its scene. */
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    glDisable(GL_DEPTH_TEST); glDisable(GL_STENCIL_TEST); glDisable(GL_SCISSOR_TEST);
    glDisable(GL_CULL_FACE); glDisable(GL_POLYGON_OFFSET_FILL); glEnable(GL_BLEND);
    glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD);
    glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
    glViewport(x, y, w, h);
    glUseProgram(combat_route_program);
    float width = (float)w, height = (float)h;
    float scale = fminf(4, fmaxf(.75f, height / 360)), half_width = 1.05f*scale + .5f;
    glUniform2f(combat_route_target, width, height);
    const float *p = route->points;
    float corners[COMBAT_ROUTE_BATCH*8], metrics[COMBAT_ROUTE_BATCH*2];
    unsigned path_count = (unsigned)p[1], footprint_end = path_count + 4*(unsigned)p[2];
    for (unsigned i = path_count; i < footprint_end; i += 4) {
        for (unsigned j = 0; j < 4; ++j) {
            corners[2*j] = projected[i+j][0]*width; corners[2*j+1] = projected[i+j][1]*height;
        }
        metrics[0] = -1; metrics[1] = 0;
        glUniform4f(combat_route_style, -1, 0, 0, 1.25f*scale);
        glUniform4f(combat_route_tint, 240/255.0f, 213/255.0f, 154/255.0f, 184/255.0f);
        combat_route_batch_draw(corners, metrics, 1);
    }
    float points[COMBAT_ROUTE_MAX_POINTS][2], miters[COMBAT_ROUTE_MAX_POINTS][2];
    unsigned count = 0;
    for (unsigned i = 0; i < path_count; ++i) {
        float px = projected[i][0]*width, py = projected[i][1]*height;
        if (count && hypotf(px-points[count-1][0], py-points[count-1][1]) < .5f) continue;
        points[count][0] = px; points[count++][1] = py;
    }
    if (count > 1) combat_route_miters(points, count, miters);
    float phase = (float)(void_perf_now_ns() % 750000000ull) / 750000000.0f * 15*scale;
    unsigned lines = p[0] == 2 ? 2 : 1;
    for (unsigned i = 0; i < lines && count > 1; ++i) {
        float offset = lines == 2 ? 3*scale : 0, direction = i ? -1.0f : 1.0f, travelled = 0;
        unsigned batch = 0;
        glUniform4f(combat_route_style, 0, phase, half_width, scale);
        if (i) glUniform4f(combat_route_tint, 153/255.0f, 215/255.0f, 203/255.0f, 217/255.0f);
        else glUniform4f(combat_route_tint, 244/255.0f, 219/255.0f, 157/255.0f, 232/255.0f);
        for (unsigned segment = 0; segment+1 < count; ++segment) {
            unsigned a = i ? count-1-segment : segment, b = i ? a-1 : a+1;
            float ax = points[a][0] + direction*offset*miters[a][0], ay = points[a][1] + direction*offset*miters[a][1];
            float bx = points[b][0] + direction*offset*miters[b][0], by = points[b][1] + direction*offset*miters[b][1];
            float length = hypotf(bx-ax, by-ay);
            if (length < .5f) continue;
            for (unsigned corner = 0; corner < 4; ++corner) {
                unsigned at = corner == 1 || corner == 2 ? b : a;
                float side = offset + (corner < 2 ? -half_width : half_width);
                corners[8*batch+2*corner] = points[at][0] + direction*side*miters[at][0];
                corners[8*batch+2*corner+1] = points[at][1] + direction*side*miters[at][1];
            }
            metrics[2*batch] = length; metrics[2*batch+1] = travelled; travelled += length;
            if (++batch == COMBAT_ROUTE_BATCH) { combat_route_batch_draw(corners, metrics, batch); batch = 0; }
        }
        if (batch) combat_route_batch_draw(corners, metrics, batch);
    }
    unsigned arrows = (unsigned)p[3], batch = 0;
    glUniform4f(combat_route_style, 1, 0, 0, scale);
    glUniform4f(combat_route_tint, 1.0f, .62f, .24f, .94f);
    for (unsigned i = 0; i < arrows; ++i) {
        float ax = projected[footprint_end][0]*width, ay = projected[footprint_end][1]*height;
        float bx = projected[footprint_end+1+i][0]*width, by = projected[footprint_end+1+i][1]*height;
        float dx = bx-ax, dy = by-ay, length = hypotf(dx, dy);
        if (length < 2*scale) continue;
        dx /= length; dy /= length;
        float gap = fminf(5*scale, length*.15f), half = fminf(5*scale, length*.18f);
        ax += dx*gap; ay += dy*gap; bx -= dx*gap; by -= dy*gap;
        for (unsigned j = 0; j < 4; ++j) {
            int end = j == 1 || j == 2;
            float side = j < 2 ? -half : half;
            corners[8*batch+2*j] = (end ? bx : ax) - dy*side;
            corners[8*batch+2*j+1] = (end ? by : ay) + dx*side;
        }
        metrics[2*batch] = length - 2*gap;
        metrics[2*batch+1] = half;
        if (++batch == COMBAT_ROUTE_BATCH) { combat_route_batch_draw(corners, metrics, batch); batch = 0; }
    }
    if (batch) combat_route_batch_draw(corners, metrics, batch);
    d3d_gl_filter_done(dev);
}

static void combat_route_reset(void)
{
    if (combat_route_program) glDeleteProgram(combat_route_program);
    combat_route_program = 0; combat_route_failed = 0;
}
