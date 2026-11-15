/* Spatial filters shared by the scene presenter and native UI texture draws. */
#ifndef HOMM5_D3D9_FILTER_H
#define HOMM5_D3D9_FILTER_H
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fsr1.h"

static const char d3d_cubic_glsl[] =
"#ifndef VP_FILTER_OPAQUE\n#define VP_FILTER_OPAQUE 0\n#endif\n"
"float vpCubic(float x){x=abs(x);return x<1.0?1.5*x*x*x-2.5*x*x+1.0:x<2.0?-.5*x*x*x+2.5*x*x-4.0*x+2.0:0.0;}\n"
"vec4 vpCubicSample(highp sampler2D image,highp vec2 uv){\n"
" vec2 size=vec2(textureSize(image,0)),p=uv*size-.5,f=floor(p);vec4 sum=vec4(0.0);\n"
" for(int y=-1;y<=2;++y)for(int x=-1;x<=2;++x){vec2 o=vec2(x,y);\n"
"  vec4 c=texture(image,(f+o+.5)/size);\n"
"#if VP_FILTER_OPAQUE\n c.a=1.0;\n#endif\n"
" c.rgb*=c.a;sum+=c*vpCubic(p.x-f.x-o.x)*vpCubic(p.y-f.y-o.y);}\n"
" sum=clamp(sum,0.0,1.0);sum.rgb=sum.a>0.00001?clamp(sum.rgb/sum.a,0.0,1.0):vec3(0.0);return sum;}\n";

/* Rewrites only ordinary texture lookups; explicit LOD/gradient/depth reads keep their D3D meaning. */
static inline char *d3d_ui_filter_source(const char *source)
{
    const char *main = strstr(source, "void main(");
    if (!main) {
        char *copy = (char *)malloc(strlen(source) + 1);
        if (copy) strcpy(copy, source);
        return copy;
    }
    const char *macros =
        "\nuniform int vpUiFilter;\nuniform highp vec4 vpUiBlur,vpUiBlurRect;\n"
        "#define FSR_ALPHA 1\n"
        "#define FSR_EASU_BASE(fp) ivec2 vpBase=ivec2(fp);\n"
        "#define T(x,y) vpPremulTexel(image,vpBase+ivec2(x,y))\n"
        "vec4 vpPremulTexel(highp sampler2D image,ivec2 p){vec4 c=texelFetch(image,clamp(p,ivec2(0),textureSize(image,0)-1),0);c.rgb*=c.a;return c;}\n";
    const char *signature = "vec4 FsrEasuH(highp vec2 src)";
    const char *at = strstr(fsr1_easu_glsl, signature);
    if (!at) return NULL;
    const char *replacement = "vec4 vpEasu(highp sampler2D image,highp vec2 src)";
    const char *samples =
        "\n#undef T\n#undef FSR_EASU_BASE\n"
        /* 4: a battle-transition layer (d3d9_gl.c, xt_layers). d is the step to the neighbouring
         * layer; the layer covers the box from half a step back to half a step on: n taps evenly
         * along it (two, up to six for steps over 128 texels), each on the mip level whose texels
         * span 1/n of the step, never sharper than the screen footprint. Copies a step apart then
         * merge without gaps, and long steps streak instead of turning into blobs. The layer fades
         * out over one step inside its own edges (vpUiBlurRect, uv; +-1e4 where an edge is the
         * viewport's), so the edges of the shrinking layers leave no straight seams. */
        "vec4 vpZoomBlur(highp sampler2D image,highp vec2 uv){\n"
        " highp vec2 size=vec2(textureSize(image,0)),d=vpUiBlur.xy*uv+vpUiBlur.zw,dx=dFdx(uv)*size,dy=dFdy(uv)*size;\n"
        " highp float base=0.5*log2(max(max(dot(dx,dx),dot(dy,dy)),1e-8)),len=length(d*size);\n"
        " highp vec2 e=min(uv-vpUiBlurRect.xy,vpUiBlurRect.zw-uv)/max(abs(d),1.0/size);float f=clamp(min(e.x,e.y),0.0,1.0);\n"
        " vec4 sum=vec4(0.0);\n"
        " if(len<2.0)sum=textureLod(image,uv,base);\n"
        " else{int n=int(clamp(ceil(len/64.0),2.0,6.0));highp float lod=max(base,log2(len/float(n)));\n"
        "  for(int i=0;i<6;++i){if(i>=n)break;sum+=textureLod(image,uv+d*((float(i)+0.5)/float(n)-0.5),lod);}\n"
        "  sum/=float(n);}\n"
        " sum.a*=f;return sum;}\n"
        "vec4 vpTexture(highp sampler2D image,highp vec2 uv){\n"
        " if(vpUiFilter<0||vpUiFilter==1)return texture(image,uv);\n"
        " if(vpUiFilter==4)return vpZoomBlur(image,uv);\n"
        " vec2 size=vec2(textureSize(image,0));\n"
        " if(vpUiFilter==0)return texture(image,(floor(uv*size)+.5)/size);\n"
        " if(vpUiFilter==2)return vpCubicSample(image,uv);\n"
        " vec4 c=vpEasu(image,uv*size);c.rgb=c.a>0.00001?clamp(c.rgb/c.a,0.0,1.0):vec3(0.0);return c;}\n"
        "vec4 vpTexture(highp sampler2D image,highp vec2 uv,float bias){return vpUiFilter<0?texture(image,uv,bias):vpTexture(image,uv);}\n"
        "vec4 vpTexture(highp samplerCube image,highp vec3 uv){return texture(image,uv);}\n"
        "vec4 vpTexture(highp samplerCube image,highp vec3 uv,float bias){return texture(image,uv,bias);}\n"
        "vec4 vpTexture(highp sampler3D image,highp vec3 uv){return texture(image,uv);}\n"
        "vec4 vpTexture(highp sampler3D image,highp vec3 uv,float bias){return texture(image,uv,bias);}\n";
    size_t capacity = strlen(source) * 2 + strlen(macros) + strlen(d3d_cubic_glsl) +
                      strlen(fsr1_easu_glsl) + strlen(replacement) + strlen(samples) + 1;
    char *out = (char *)malloc(capacity), *w = out;
    if (!out) return NULL;
    size_t head = (size_t)(main - source), easu_head = (size_t)(at - fsr1_easu_glsl);
    memcpy(w, source, head); w += head;
    w += sprintf(w, "%s%s%.*s%s%s%s", macros, d3d_cubic_glsl, (int)easu_head, fsr1_easu_glsl,
                 replacement, at + strlen(signature), samples);
    for (const char *p = main; *p;) {
        /* MojoShader's GLES 3 profile keeps texture2D( in main and #defines it to texture. */
        if (!strncmp(p, "texture2D(", 10)) { memcpy(w, "vpTexture(", 10); w += 10; p += 10; }
        else if (!strncmp(p, "texture(", 8)) { memcpy(w, "vpTexture(", 10); w += 10; p += 8; }
        else *w++ = *p++;
    }
    *w = 0;
    return out;
}
#endif
