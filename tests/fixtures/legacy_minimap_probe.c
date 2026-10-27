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
/* SCALE_HELPERS */
static float quad_x[3],quad_y[3];
static unsigned quads,render_calls,events;
static uint32_t event_position;
static int visible=1;
static void converter(void);
static void rect_body(void);
static void fixture_call(uint32_t target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#undef RECOMP_ITAIL
#define RECOMP_CALL(fn) fixture_call((uint32_t)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((uint32_t)(va))
#define RECOMP_ITAIL(va) do {assert((va)==RECT_BODY);RECOMP_FLAGS_OUT();rect_body();} while(0)
/* ACTUAL */
static void fixture_call(uint32_t target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 uint32_t a=MEM32(g_esp+4);
 if(target==CONVERT) {converter();return;}
 if(target==VISIBLE) {g_eax=visible;g_esp+=4;return;}
 if(target==PLACEMENT) {assert(g_ecx==0x2000-OBJECT_OFFSET);g_eax=0x3000;g_esp+=4;return;}
 if(target==GET_MAP) {g_eax=0x6000;g_esp+=4;return;}
 if(target==QUAD) {
  assert(quads<3);quad_x[quads]=MEMF(a);quad_y[quads]=MEMF(a+4);++quads;
  assert(fabsf(MEMF(a+8)-172)<.01f&&fabsf(MEMF(a+12)-172)<.01f);
  g_esp+=8;return;
 }
 if(target==RENDER) {assert(g_ecx==0x7000&&MEM32(g_esp+8)==3);++render_calls;g_esp+=16;return;}
 if(target==BASE_CLICK||target==BASE_DRAG||target==STRING) {g_esp+=12;return;}
 if(target==EMIT) {++events;event_position=g_edx;g_esp+=8;return;}
 if(target==BASE_DRAW) {g_esp+=8;return;}
 if(target==FREE||target==UPDATE0||target==UPDATE1||target==UPDATE2||target==CONVERT_QUADS) {g_esp+=4;return;}
 fprintf(stderr,"unexpected callback %08X\n",target);abort();
}
static void registers(void) {
 g_esp=0x10004;g_ecx=0x2000;g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;
 MEM32(g_esp)=RECOMP_RETADDR;
 fp_set_cw(0x007f);g_fp_sp=128;g_fp_top=0;
}
static void returned(uint32_t bytes) {
 assert(g_esp==0x10004+bytes&&g_ebx==0x11223344&&g_esi==0x22334455&&g_edi==0x33445566&&g_ebp==0x44556677);
 assert(g_fp_top==0&&g_fp_sp==128&&g_fpu_cw==0x007f);
}
static void draw_call(void (*fn)(void)) {
 registers();quads=render_calls=0;MEM32(g_esp+4)=0x7000;fn();returned(8);
 assert(quads==(visible?3u:0u)&&render_calls==(visible?4u:0u));
}
static void pointer_call(void (*fn)(void),float x,float y,unsigned button) {
 registers();MEMF(0x8000)=x;MEMF(0x8004)=y;
 MEM32(g_esp+4)=0x8000;MEM32(g_esp+8)=button;fn();returned(12);
}
static void reset(float resource_x,float resource_y,float window_x,float window_y) {
 memset(memory,0,sizeof memory);visible=1;events=0;
 MEM32(0x2000-BASE_OFFSET)=0x5000;MEM32(0x5008)=BASE_OFFSET;
 MEM32(0x2000)=0x5100;MEM32(0x5148)=VISIBLE;
 MEM32(0x2000-OBJECT_OFFSET)=0x5200;MEM32(0x5208)=PLACEMENT;
 MEM32(0x2000-4)=0;
 MEM32(0x2000-RESOURCE_OFFSET)=0x3000;
 MEMF(0x3088)=resource_x;MEMF(0x308c)=resource_y;
 MEMF(0x30a4)=219;MEMF(0x30a8)=221;
 /* The original CWindow::Layout stores absolute origin at CWindow+64/68.
    This oracle is independent of the custom minimap method's this adjustment. */
 MEMF(0x2000-OBJECT_OFFSET+0x64)=window_x;MEMF(0x2000-OBJECT_OFFSET+0x68)=window_y;
 MEM32(0x2000-TEXTURE_OFFSET)=0x3500;MEM32(0x3528)=215;
 MEMF(0x2000-OBJECT_OFFSET+0x84)=1;MEMF(0x2000-OBJECT_OFFSET+0x88)=1;MEMF(OPAQUE_CONST)=1;
 MEM32(0x7000)=0x7100;MEM32(0x711c)=RENDER;
 MEMF(PADDING)=25;MEMF(EDGE)=172;MEMF(RECIP)=1.0f/172;
 MEM32(0x6000+MAP_BORDER)=2;MEM32(0x6000+MAP_WIDTH)=100;MEM32(0x6000+MAP_HEIGHT)=80;
}
static void check_frame(float resource_y,float view_width,float view_height,int original) {
 float fw=fmaxf(1024,view_width),fh=fmaxf(768,view_height);
 float x=scale_native_position(0,0,fw,2,0,219);
 float y=scale_native_position(original?0:2,0,fh,resource_y,0,221);
 x+=scale_anchor_shift(0,x,219,0,fw,view_width);
 y+=scale_anchor_shift(original?0:2,y,221,0,fh,view_height);
 reset(2,resource_y,x,y);
 registers();MEM32(g_esp+4)=0x9000;public_rect();returned(8);
 assert(MEMF(0x9000)==x&&MEMF(0x9004)==y&&MEMF(0x9008)==x+219&&MEMF(0x900c)==y+221);
 draw_call(draw);
 for(unsigned n=0;n<3;++n)assert(fabsf(quad_x[n]-(x+25))<.001f&&fabsf(quad_y[n]-(y+25))<.001f);
 float px=x+25+86,py=y+25+86;
 pointer_call(click,px,py,1);assert(events==1&&event_position==(0x40000000u|(80u<<15)|100u));
 pointer_call(drag,px,py,1);assert(events==2&&event_position==(0x40000000u|(80u<<15)|100u));
 pointer_call(drag,px,py,0);assert(events==2);
 pointer_call(click,x+24,y+25+86,1);assert(events==2);
 pointer_call(click,x+25+173,y+25+86,1);assert(events==2);
 if(original) {
  draw_call(old_draw);
  for(unsigned n=0;n<3;++n)assert(fabsf(quad_x[n]-(x+25))<.001f&&fabsf(quad_y[n]-(y+25))<.001f);
  pointer_call(old_click,px,py,1);assert(events==3&&event_position==(0x40000000u|(80u<<15)|100u));
 } else {
  draw_call(old_draw);assert(fabsf(quad_y[0]-(y+25))>1);
  unsigned old_events=events;pointer_call(old_click,px,py,1);assert(events==old_events);
 }
 visible=0;draw_call(draw);
 assert(MEMF(0x3088)==2&&MEMF(0x308c)==resource_y);
}
int main(void) {
 check_frame(547,1024,768,1);
 const float scales[]={.5f,1,2};
 for(unsigned i=0;i<3;++i)check_frame(0,1707/scales[i],768/scales[i],0);
 puts("PASS actual minimap draw/click/drag+native converter: original4:3, wideUI50/100/200, frame origins, nativeworldcoordinates, bounds, ABI/x87 and oldcode negative control");
}
