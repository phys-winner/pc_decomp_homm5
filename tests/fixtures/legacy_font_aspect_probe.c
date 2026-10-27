#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
static void coords(void);
#ifdef TOE
static void virtual_size(void);
static void float_min(void);
#endif
static unsigned width,height,selected,requests;
static void fixture_call(uint32_t target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#define RECOMP_CALL(fn) fixture_call((uint32_t)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((uint32_t)(va))
/* ACTUAL */
static void fixture_call(uint32_t target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 if(target==COORDS) {coords();return;}
#ifdef TOE
 if(target==VIRTUAL_SIZE) {virtual_size();return;}
 if(target==MIN_FLOAT) {float_min();return;}
#endif
 if(target==SERVICE) {assert(g_ecx==0x1109bc00);g_eax=0x4000;g_esp+=4;return;}
 if(target==CONTROLLER) {assert(g_ecx==0x4000);g_eax=0x5000;g_esp+=4;return;}
 if(target==PHYSICAL_SIZE) {
  assert(g_ecx==0x5000);MEM32(MEM32(g_esp+4))=width;MEM32(MEM32(g_esp+8))=height;g_esp+=12;return;
 }
 if(target==STRING) {g_esp+=12;return;}
 if(target==FONT_BANK) {g_eax=0x6000;g_esp+=4;return;}
 if(target==FONT_REQUEST) {
  assert(g_ecx==0x6000);uint32_t p=MEM32(g_esp+4);selected=MEM32(p);++requests;g_eax=0x7000;g_esp+=8;return;
 }
 if(target==UNWRAP) {assert(MEM32(g_ecx)==0x8000);g_esp+=4;return;}
 if(target==FREE) {assert(MEM32(g_esp+4)==0);g_esp+=4;return;}
 fprintf(stderr,"unexpected font callback %08X\n",target);abort();
}
static void reset(unsigned w,unsigned h,float canvas_w,float canvas_h,unsigned flags,unsigned minsize) {
 memset(memory,0,sizeof memory);width=w;height=h;selected=requests=0;
 MEMF(CANVAS_X)=canvas_w;MEMF(CANVAS_Y)=canvas_h;
 MEMF(PHYSICAL_X)=(float)w;MEMF(PHYSICAL_Y)=(float)h;
 MEMF(RECIP_X)=1.0f/1024;MEMF(RECIP_Y)=1.0f/768;
 MEMF(ASPECT)=4.0f/3;MEMF(ONE)=1;
 MEM32(0x4000)=0x4100;MEM32(0x4130)=CONTROLLER;
 MEM32(0x5000)=0x5100;MEM32(0x5100+SIZE_SLOT)=PHYSICAL_SIZE;
 MEM32(0x6000)=0x6100;MEM32(0x611c)=FONT_REQUEST;
 MEM32(0x7008)=2;MEM32(0x7020)=0x8000;
 MEM32(0x8004)=2;MEM32(0x8014)=0x9000;
 /* Independent native bitmap line metrics: ascent20 minus descender2. */
 MEM32(0x903c)=20;MEM32(0x9044)=2;
 MEM32(0x2000)=flags|18;
 g_eax=minsize;g_ecx=0x2000;g_ebx=0x2000;g_esi=0x22334455;g_ebp=0x33445566;
#ifdef TOE
 g_edi=0x3000;
#else
 g_edi=0x44556677;
#endif
 g_esp=0x10004;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x3000;
 fp_set_cw(0x007f);g_fp_sp=128;g_fp_top=0;
}
static void returned(void) {
 assert(g_ebx==0x2000&&g_esi==0x22334455&&g_ebp==0x33445566);
#ifdef TOE
 assert(g_esp==0x10008&&g_edi==0x3000);
#else
 assert(g_esp==0x1000c&&g_edi==0x44556677);
#endif
 assert(g_fp_top==0&&g_fp_sp==128&&g_fpu_cw==0x007f&&requests==1);
}
int main(void) {
 const unsigned surfaces[][2]={{1024,768},{1600,1200},{2340,1080},{2400,1080},{1919,1201}};
 const float scales[]={.5f,1,2};
 const unsigned styles[]={0,0x10000000,0x20000000,0x40000000,0x50000000,0x60000000};
 for(unsigned s=0;s<5;++s)for(unsigned k=0;k<3;++k)for(unsigned f=0;f<6;++f) {
  unsigned w=surfaces[s][0],h=surfaces[s][1];
  float base=(float)floor(768.0*w/h+.99),cw=base/scales[k],ch=768/scales[k];
  reset(w,h,cw,ch,styles[f],1);resolver();returned();
  float x=MEMF(0x3000),y=MEMF(0x3004);unsigned chosen=selected;
  assert(chosen>=1&&x>0&&isfinite(x)&&x==y&&fabsf(x-(float)chosen/18)<.00001f);
  if(styles[f]&0x20000000)assert(chosen==(unsigned)(18.0f*w/cw));
  else assert(chosen==18);
#ifndef TOE
  reset(w,h,cw,ch,styles[f],1);old_resolver();returned();
  assert(selected==chosen&&MEMF(0x3000)==x);
  if(w*3==h*4 || styles[f]&0x40000000)assert(fabsf(MEMF(0x3004)-y)<.00001f);
  else assert(fabsf(MEMF(0x3004)/y-(4.0f/3)*h/w)<.00001f&&MEMF(0x3004)<y*.9f);
#endif
 }
 reset(2340,1080,1664,768,0x20000000,60);resolver();returned();assert(selected==60&&MEMF(0x3000)==MEMF(0x3004));
 puts("PASS actual native font resolver:4:3+wideUI50/100/200,styleflags,bitmapmetrics,X/choicepreserved,equalXY,minsize,ESP/x87 and original squash negativecontrol");
}
