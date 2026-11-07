/* AMD FidelityFX Super Resolution 1.0 (EASU upscaling + RCAS sharpening) as
 * GLSL ES 3.00 sources for the presenter (ddraw_present.c). A port of the
 * packed 16-bit paths FsrEasuH() and FsrRcasH() of ffx_fsr1.h
 * v1.20210629 (https://github.com/GPUOpen-Effects/FidelityFX-FSR), keeping
 * AMD's structure, constants and names. Differences, all forced by GLSL ES:
 * - inputs arrive through T(x,y) (texel at an offset from 'f') and L(x,y)
 *   (EASU output at an offset from the pixel) instead of gather/load
 *   callbacks; the includer defines them;
 * - 16-bit bit-pattern approximations (APrxLo*H1) become exact rcp/rsq,
 *   with denominators kept away from zero where AMD's packed path relies
 *   on saturate(0*inf)=0, which GLSL leaves undefined;
 * - FSR_ALPHA carries a fourth, premultiplied alpha channel through both
 *   filters (UI layers): the same EASU weights and dering clamp, and the
 *   same RCAS lobe with alpha included in its clipping limits.
 *
 * Original notice of ffx_fsr1.h:
 *
 * Copyright (c) 2021 Advanced Micro Devices, Inc. All rights reserved.
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files(the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and / or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions :
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */
#ifndef STRONGHOLD_FSR1_H
#define STRONGHOLD_FSR1_H
#include <math.h>

/* FsrRcasCon(): sharpness in stops, 0 = maximum, each stop halves it. */
static inline float fsr1_rcas_con(float stops) { return exp2f(-stops); }

/* EASU. Needs mediump float default precision, T(x,y) returning the source
 * texel (vec4) at integer offset (x,y) from 'f' (the texel left-above the
 * sample position) and FSR_EASU_BASE(fp), declaring what T() uses. Source
 * coordinates are in texels, texel i spanning [i,i+1). */
static const char fsr1_easu_glsl[] =
"#define FSR_FLAT (1.0/512.0)\n"
"float FsrRcpH1(float x){return 1.0/x;}\n"
"vec2 FsrRcpH2(vec2 x){return 1.0/max(x,vec2(1.0/16384.0));}\n"
/* This runs 2 taps in parallel. */
"void FsrEasuTapH(inout vec2 aCR,inout vec2 aCG,inout vec2 aCB,inout vec2 aCA,inout vec2 aW,\n"
" vec2 offX,vec2 offY,vec2 dir,vec2 len,float lob,float clp,vec2 cR,vec2 cG,vec2 cB,vec2 cA){\n"
" vec2 vX,vY;\n"
" vX=offX*  dir.xx +offY*dir.yy;\n"
" vY=offX*(-dir.yy)+offY*dir.xx;\n"
" vX*=len.x;vY*=len.y;\n"
" vec2 d2=vX*vX+vY*vY;\n"
" d2=min(d2,vec2(clp));\n"
" vec2 wB=vec2(2.0/5.0)*d2+vec2(-1.0);\n"
" vec2 wA=vec2(lob)*d2+vec2(-1.0);\n"
" wB*=wB;\n"
" wA*=wA;\n"
" wB=vec2(25.0/16.0)*wB+vec2(-(25.0/16.0-1.0));\n"
" vec2 w=wB*wA;\n"
" aCR+=cR*w;aCG+=cG*w;aCB+=cB*w;\n"
"#if FSR_ALPHA\n"
" aCA+=cA*w;\n"
"#endif\n"
" aW+=w;}\n"
/* This runs 2 taps in parallel. */
"void FsrEasuSetH(inout vec2 dirPX,inout vec2 dirPY,inout vec2 lenP,vec2 pp,bool biST,bool biUV,\n"
" vec2 lA,vec2 lB,vec2 lC,vec2 lD,vec2 lE){\n"
" vec2 w=vec2(0.0);\n"
" if(biST)w=(vec2(1.0,0.0)+vec2(-pp.x,pp.x))*vec2(1.0-pp.y);\n"
" if(biUV)w=(vec2(1.0,0.0)+vec2(-pp.x,pp.x))*vec2(     pp.y);\n"
" vec2 dc=lD-lC;\n"
" vec2 cb=lC-lB;\n"
" vec2 lenX=max(abs(dc),abs(cb));\n"
" lenX=FsrRcpH2(lenX);\n"
" vec2 dirX=lD-lB;\n"
" dirPX+=dirX*w;\n"
" lenX=clamp(abs(dirX)*lenX,0.0,1.0);\n"
" lenX*=lenX;\n"
" lenP+=lenX*w;\n"
" vec2 ec=lE-lC;\n"
" vec2 ca=lC-lA;\n"
" vec2 lenY=max(abs(ec),abs(ca));\n"
" lenY=FsrRcpH2(lenY);\n"
" vec2 dirY=lE-lA;\n"
" dirPY+=dirY*w;\n"
" lenY=clamp(abs(dirY)*lenY,0.0,1.0);\n"
" lenY*=lenY;\n"
" lenP+=lenY*w;}\n"
"vec4 FsrEasuH(highp vec2 src){\n"
" highp vec2 pp=src-vec2(0.5);\n"
" highp vec2 fp=floor(pp);\n"
" pp-=fp;\n"
" vec2 ppp=vec2(pp);\n"
" FSR_EASU_BASE(fp)\n"
/* 12-tap kernel.
 *    b c
 *  e f g h
 *  i j k l
 *    n o
 * The output is clamped to the 4 nearest; when they are equal within
 * FSR_FLAT (always exactly equal for RGB565 input) any value inside that
 * range is within FSR_FLAT of EASU, so the bilinear one is returned. */
" vec4 f=T(0,0),g=T(1,0),j=T(0,1),k=T(1,1);\n"
" if(all(lessThanEqual(max(max(f,g),max(j,k))-min(min(f,g),min(j,k)),vec4(FSR_FLAT))))\n"
"  return mix(mix(f,g,ppp.x),mix(j,k,ppp.x),ppp.y);\n"
" vec4 b=T(0,-1),c=T(1,-1),e=T(-1,0),h=T(2,0),i=T(-1,1),l=T(2,1),n=T(0,2),o=T(1,2);\n"
/* Simplest multi-channel approximate luma possible (luma times 2, in 2 FMA/MAD). */
" float bL=b.b*0.5+(b.r*0.5+b.g);\n"
" float cL=c.b*0.5+(c.r*0.5+c.g);\n"
" float iL=i.b*0.5+(i.r*0.5+i.g);\n"
" float jL=j.b*0.5+(j.r*0.5+j.g);\n"
" float fL=f.b*0.5+(f.r*0.5+f.g);\n"
" float eL=e.b*0.5+(e.r*0.5+e.g);\n"
" float kL=k.b*0.5+(k.r*0.5+k.g);\n"
" float lL=l.b*0.5+(l.r*0.5+l.g);\n"
" float hL=h.b*0.5+(h.r*0.5+h.g);\n"
" float gL=g.b*0.5+(g.r*0.5+g.g);\n"
" float oL=o.b*0.5+(o.r*0.5+o.g);\n"
" float nL=n.b*0.5+(n.r*0.5+n.g);\n"
/* This part is different, accumulating 2 taps in parallel. */
" vec2 dirPX=vec2(0.0);\n"
" vec2 dirPY=vec2(0.0);\n"
" vec2 lenP=vec2(0.0);\n"
" FsrEasuSetH(dirPX,dirPY,lenP,ppp,true, false,vec2(bL,cL),vec2(eL,fL),vec2(fL,gL),vec2(gL,hL),vec2(jL,kL));\n"
" FsrEasuSetH(dirPX,dirPY,lenP,ppp,false,true ,vec2(fL,gL),vec2(iL,jL),vec2(jL,kL),vec2(kL,lL),vec2(nL,oL));\n"
" highp vec2 dir=vec2(dirPX.r+dirPX.g,dirPY.r+dirPY.g);\n"
" float len=lenP.r+lenP.g;\n"
/* Normalize, and cleanup close to zero (high precision: 1/32768 is below
 * the normal half-float range). */
" highp vec2 dir2=dir*dir;\n"
" highp float dirR=dir2.x+dir2.y;\n"
" bool zro=dirR<(1.0/32768.0);\n"
" dirR=inversesqrt(zro?1.0:dirR);\n"
" dir.x=zro?1.0:dir.x;\n"
" dir*=vec2(dirR);\n"
/* Transform from {0 to 2} to {0 to 1} range, and shape with square. */
" len=len*0.5;\n"
" len*=len;\n"
/* Stretch kernel {1.0 vert|horz, to sqrt(2.0) on diagonal}. */
" vec2 hdir=vec2(dir);\n"
" float stretch=(hdir.x*hdir.x+hdir.y*hdir.y)*FsrRcpH1(max(abs(hdir.x),abs(hdir.y)));\n"
/* Anisotropic length after rotation, x := 1.0 lerp to 'stretch' on edges,
 * y := 1.0 lerp to 2x on edges. */
" vec2 len2=vec2(1.0+(stretch-1.0)*len,1.0+(-0.5)*len);\n"
/* Based on the amount of 'edge', the window shifts from +/-{sqrt(2.0) to slightly beyond 2.0}. */
" float lob=0.5+((1.0/4.0-0.04)-0.5)*len;\n"
/* Set distance^2 clipping point to the end of the adjustable window. */
" float clp=FsrRcpH1(lob);\n"
/* FP16 is different, using packed trick to do min and max in same operation. */
" vec2 bothR=max(max(vec2(-f.r,f.r),vec2(-g.r,g.r)),max(vec2(-j.r,j.r),vec2(-k.r,k.r)));\n"
" vec2 bothG=max(max(vec2(-f.g,f.g),vec2(-g.g,g.g)),max(vec2(-j.g,j.g),vec2(-k.g,k.g)));\n"
" vec2 bothB=max(max(vec2(-f.b,f.b),vec2(-g.b,g.b)),max(vec2(-j.b,j.b),vec2(-k.b,k.b)));\n"
" vec2 bothA=max(max(vec2(-f.a,f.a),vec2(-g.a,g.a)),max(vec2(-j.a,j.a),vec2(-k.a,k.a)));\n"
/* This part is different for FP16, working pairs of taps at a time. */
" vec2 pR=vec2(0.0);\n"
" vec2 pG=vec2(0.0);\n"
" vec2 pB=vec2(0.0);\n"
" vec2 pA=vec2(0.0);\n"
" vec2 pW=vec2(0.0);\n"
" FsrEasuTapH(pR,pG,pB,pA,pW,vec2( 0.0, 1.0)-ppp.xx,vec2(-1.0,-1.0)-ppp.yy,hdir,len2,lob,clp,vec2(b.r,c.r),vec2(b.g,c.g),vec2(b.b,c.b),vec2(b.a,c.a));\n"
" FsrEasuTapH(pR,pG,pB,pA,pW,vec2(-1.0, 0.0)-ppp.xx,vec2( 1.0, 1.0)-ppp.yy,hdir,len2,lob,clp,vec2(i.r,j.r),vec2(i.g,j.g),vec2(i.b,j.b),vec2(i.a,j.a));\n"
" FsrEasuTapH(pR,pG,pB,pA,pW,vec2( 0.0,-1.0)-ppp.xx,vec2( 0.0, 0.0)-ppp.yy,hdir,len2,lob,clp,vec2(f.r,e.r),vec2(f.g,e.g),vec2(f.b,e.b),vec2(f.a,e.a));\n"
" FsrEasuTapH(pR,pG,pB,pA,pW,vec2( 1.0, 2.0)-ppp.xx,vec2( 1.0, 1.0)-ppp.yy,hdir,len2,lob,clp,vec2(k.r,l.r),vec2(k.g,l.g),vec2(k.b,l.b),vec2(k.a,l.a));\n"
" FsrEasuTapH(pR,pG,pB,pA,pW,vec2( 2.0, 1.0)-ppp.xx,vec2( 0.0, 0.0)-ppp.yy,hdir,len2,lob,clp,vec2(h.r,g.r),vec2(h.g,g.g),vec2(h.b,g.b),vec2(h.a,g.a));\n"
" FsrEasuTapH(pR,pG,pB,pA,pW,vec2( 1.0, 0.0)-ppp.xx,vec2( 2.0, 2.0)-ppp.yy,hdir,len2,lob,clp,vec2(o.r,n.r),vec2(o.g,n.g),vec2(o.b,n.b),vec2(o.a,n.a));\n"
" vec4 aC=vec4(pR.x+pR.y,pG.x+pG.y,pB.x+pB.y,pA.x+pA.y);\n"
" float aW=pW.x+pW.y;\n"
/* Slightly different for FP16 version due to combined min and max. */
" vec4 pix=min(vec4(bothR.y,bothG.y,bothB.y,bothA.y),max(-vec4(bothR.x,bothG.x,bothB.x,bothA.x),aC*vec4(FsrRcpH1(aW))));\n"
"#if FSR_ALPHA\n"
" pix.rgb=min(pix.rgb,pix.aaa);\n"
"#else\n"
" pix.a=1.0;\n"
"#endif\n"
" return pix;}\n";

/* RCAS. Needs L(x,y) returning the EASU output (vec4) at an integer offset
 * from the pixel, FSR_RCAS_BASE declaring what L() uses, and con from
 * FsrRcasCon(). FSR_RCAS_DENOISE stays off, as AMD suggests. */
static const char fsr1_rcas_glsl[] =
"#define FSR_RCAS_LIMIT (0.25-(1.0/16.0))\n"
"vec3 FsrRcasRcp3(vec3 x){return 1.0/max(x,vec3(1.0/16384.0));}\n"
"vec3 FsrRcasRcpNeg3(vec3 x){return 1.0/min(x,vec3(-1.0/16384.0));}\n"
"vec4 FsrRcasH(float con){\n"
" FSR_RCAS_BASE\n"
/* Sharpening algorithm uses minimal 3x3 pixel neighborhood.
 *    b
 *  d e f
 *    h */
" vec4 b=L(0,-1);\n"
" vec4 d=L(-1,0);\n"
" vec4 e=L(0,0);\n"
" vec4 f=L(1,0);\n"
" vec4 h=L(0,1);\n"
/* Min and max of ring. */
" vec4 mn4=min(min(b,d),min(f,h));\n"
" vec4 mx4=max(max(b,d),max(f,h));\n"
/* Immediate constants for peak range. */
" vec2 peakC=vec2(1.0,-1.0*4.0);\n"
/* Limiters, these need to be high precision RCPs. */
" vec3 hitMin=min(mn4.rgb,e.rgb)*FsrRcasRcp3(vec3(4.0)*mx4.rgb);\n"
" vec3 hitMax=(peakC.x-max(mx4.rgb,e.rgb))*FsrRcasRcpNeg3(vec3(4.0)*mn4.rgb+peakC.y);\n"
" vec3 lobeRGB=max(-hitMin,hitMax);\n"
" float lobeM=max(lobeRGB.r,max(lobeRGB.g,lobeRGB.b));\n"
"#if FSR_ALPHA\n"
" float hitMinA=min(mn4.a,e.a)/max(4.0*mx4.a,1.0/16384.0);\n"
" float hitMaxA=(peakC.x-max(mx4.a,e.a))/min(4.0*mn4.a+peakC.y,-1.0/16384.0);\n"
" lobeM=max(lobeM,max(-hitMinA,hitMaxA));\n"
"#endif\n"
" float lobe=max(-FSR_RCAS_LIMIT,min(lobeM,0.0))*con;\n"
/* Resolve, which needs the medium precision rcp approximation to avoid visible tonality changes. */
" float rcpL=1.0/(4.0*lobe+1.0);\n"
"#if FSR_ALPHA\n"
" vec4 pix=(lobe*b+lobe*d+lobe*h+lobe*f+e)*rcpL;\n"
" pix.rgb=min(pix.rgb,pix.aaa);\n"
" return pix;}\n"
"#else\n"
" return vec4((lobe*b.rgb+lobe*d.rgb+lobe*h.rgb+lobe*f.rgb+e.rgb)*rcpL,1.0);}\n"
"#endif\n";

#endif
