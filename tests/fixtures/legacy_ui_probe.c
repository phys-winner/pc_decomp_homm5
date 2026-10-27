
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_X87_WINDOW
#define RECOMP_GENERATED_CODE
#include "runtime.h"
/* STATE */
/* ACTUAL */
static void call_coord(void (*fn)(void),float coordinate) {
 g_esp=0x10004;MEM32(g_esp)=RECOMP_RETADDR;MEMF(g_esp+4)=coordinate;
 fp_set_cw(0x007F);g_fp_sp=128;g_fp_top=0;
 fn();assert(g_esp==0x1000C&&g_fp_top==0&&g_fp_sp==128&&g_fpu_cw==0x007F);
}
int main(void) {
 const int surfaces[][2]={{2400,1080},{1919,1201},{1080,2400}};
 const int scales[]={50,100,200};
 MEMF(CONST_X)=1024;MEMF(CONST_Y)=768;MEMF(RECIP_X)=1.0f/1024;MEMF(RECIP_Y)=1.0f/768;
 for(unsigned s=0;s<3;++s)for(unsigned k=0;k<3;++k) {
  double aspect=(double)surfaces[s][0]/surfaces[s][1];
  float base=aspect>(double)1.3333334f?(float)floor(768*aspect+(double).99f):1024;
  float canvas=base*100/scales[k], physical=(float)surfaces[s][0];
  MEMF(CANVAS_X)=canvas;MEMF(CANVAS_Y)=768.0f*100/scales[k];
  MEMF(PHYSICAL_X)=physical;MEMF(PHYSICAL_Y)=(float)surfaces[s][1];
  for(unsigned n=0;n<257;++n) {
   float p=(float)((unsigned)(physical-1)*n/256);
   call_coord(inverse,p);int virtual_coordinate=(int)g_eax;
   assert(fabs((double)virtual_coordinate-p*canvas/physical)<=1.01);
   call_coord(forward,(float)virtual_coordinate);int pixel=(int)g_eax;
   assert(fabs((double)pixel-p)<=ceil(physical/canvas)+1.01);
  }
  call_coord(original_inverse,physical*.5f);int old=(int)g_eax;
  call_coord(inverse,physical*.5f);int now=(int)g_eax;
  if(canvas!=1024)assert(abs(now-old)>1);
  assert(MEMF(CONST_X)==1024&&MEMF(CONST_Y)==768&&MEMF(RECIP_X)==1.0f/1024&&MEMF(RECIP_Y)==1.0f/768);
 }
 puts("PASS actual generated UI x87: UI50/100/200 landscape/odd/portrait, input-to-visible-pixel roundtrip, unchanged fixed constants, ABI/FPU restore, unpatched negative control");
}
