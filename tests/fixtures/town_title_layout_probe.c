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
/* SCALE */
static void axis_layout(void);
static void fixture_call(uint32_t target);
#undef RECOMP_CALL
#undef RECOMP_ICALL
#undef RECOMP_ITAIL
#define RECOMP_CALL(fn) fixture_call((uint32_t)strtoul(&(#fn)[4],NULL,16))
#define RECOMP_ICALL(va) fixture_call((uint32_t)(va))
#define RECOMP_ITAIL(va) do {fprintf(stderr,"unexpected tail %08X\n",(uint32_t)(va));abort();} while(0)
/* ACTUAL */
static unsigned invalidations;
static void fixture_call(uint32_t target) {
 PUSH32(g_esp,RECOMP_RETADDR);
 if(target==AXIS){axis_layout();return;}
 if(target==VISIBLE){assert(g_ecx==0x20F8);g_eax=1;g_esp+=4;return;}
 if(target==PLACEMENT){assert(g_ecx==0x2000);g_eax=0x3000;g_esp+=4;return;}
 if(target==INVALIDATE){assert(g_ecx==0x2000&&MEM32(g_esp+4)==0);++invalidations;g_esp+=8;return;}
 fprintf(stderr,"unexpected callback %08X\n",target);abort();
}
static void place(const float row[10],float parent_x,float width,float height,float result[4]) {
 memset(memory,0,sizeof memory);invalidations=0;
 MEM32(0x2000)=0x5200;MEM32(0x5208)=PLACEMENT;
 MEM32(0x2010)=0x5000;MEM32(0x5008)=0xE8;
 MEM32(0x20F8)=0x5100;MEM32(0x5148)=VISIBLE;
 MEM32(0x309C)=(uint32_t)row[0];MEM32(0x3094)=(uint32_t)row[1];
 MEMF(0x3088)=row[2];MEMF(0x308C)=row[3];MEMF(0x30A4)=row[4];MEMF(0x30A8)=row[5];
 MEMF(0x30B0)=row[6];MEMF(0x30B4)=row[7];MEMF(0x30BC)=row[8];MEMF(0x30C0)=row[9];
 MEMF(0x8000)=parent_x;MEMF(0x8004)=0;MEMF(0x8008)=parent_x+width;MEMF(0x800C)=height;
 MEMF(HALF)=.5f;
 const uint32_t jump[4]={LOW,CENTER,HIGH,MARGIN};memcpy(GPTR(JUMP),jump,sizeof jump);
 g_esp=0x10004;g_ecx=0x2000;MEM32(g_esp)=RECOMP_RETADDR;MEM32(g_esp+4)=0x8000;
 g_ebx=0x11223344;g_esi=0x22334455;g_edi=0x33445566;g_ebp=0x44556677;
 fp_set_cw(0x007F);g_fp_sp=128;g_fp_top=0;
 window_layout();
 assert(g_esp==0x1000C&&g_ebx==0x11223344&&g_esi==0x22334455&&g_edi==0x33445566&&g_ebp==0x44556677);
 assert(g_fp_top==0&&g_fp_sp==128&&g_fpu_cw==0x007F&&invalidations==1);
 result[0]=MEMF(0x2064);result[1]=MEMF(0x2068);result[2]=MEMF(0x30A4);result[3]=MEMF(0x30A8);
}
static const float original[10]={/* ORIGINAL */};
static const float centered[10]={/* CENTERED */};
int main(void) {
 float old[4],now[4];place(original,0,1024,768,old);place(centered,0,1024,768,now);
 for(unsigned n=0;n<4;++n)assert(old[n]==now[n]);
 assert(old[0]==271&&old[1]==58&&old[2]==512&&old[3]==51);
 const float scales[]={.5f,1,2};
 for(unsigned n=0;n<3;++n){
  float view=1707/scales[n],height=768/scales[n],frame=fmaxf(1024,view),fh=fmaxf(768,height);
  place(centered,0,frame,fh,now);
  float shift=scale_anchor_shift(1,now[0],now[2],0,frame,view);
  place(centered,shift,frame,fh,now);
  assert(fabsf(now[0]-(271+(view-1024)*.5f))<=.51f);
  assert(now[1]==58&&now[2]==512&&now[3]==51);
  /* The old left anchor stays at271 when a wide viewport grows. */
  place(original,0,frame,fh,old);
  if(view>1024)assert(fabsf(old[0]-now[0])>100);
 }
 puts("PASS actual native TownName parent CWindow::Layout+axis helper: unchanged4:3, wideUI50/100/200, originaltextbinding/windowsize, oldLOW negativecontrol, RET4/x87/registers");
}
