#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x1100000];
#define VOID_GUEST_BASE ((uintptr_t)memory)
#define RECOMP_GENERATED_CODE
#define RECOMP_X87_WINDOW
#include "runtime.h"
/* STATE */
static int anchor_y,back_y;
static unsigned count,created;
static float ys[8];
static void registry(void){assert(g_ecx==0x1109BC00);g_eax=0x60000;g_esp+=4;}
static void resource(void){assert(g_ecx==0x60000);g_eax=0x70000;g_esp+=4;}
static void cast(void){assert(MEM32(g_esp+4)==0x70000);g_eax=0x70000;g_esp+=4;}
static void builder(void){
 assert(g_ecx==0x20000&&created<count&&MEM32(g_esp+4)==0x80000+0x44*created);
 ys[created++]=MEMF(g_esp+8);g_esp+=12;
}
static void position(void){
 assert(g_ecx==0x30020||g_ecx==0x40020);uint32_t out=MEM32(g_esp+8);assert(out);
 MEM32(out)=g_ecx==0x30020?(uint32_t)anchor_y:(uint32_t)back_y;g_esp+=20;
}
recomp_func_t void_resolve(uint32_t va){if(va==0xF0001)return resource;assert(va==0xF0002);return position;}
/* GENERATED */
static void check(int a,int b,unsigned n,const float *expected){
 anchor_y=a;back_y=b;count=n;created=0;MEM32(0x700D8)=0x80000;MEM32(0x700DC)=0x80000+68*n;
 g_ecx=0x20000;g_esp=0x10004;MEM32(g_esp)=RECOMP_RETADDR;
 ORIGINAL();assert(g_esp==0x10008&&created==n&&g_fp_sp==128&&g_fp_top==0);
 for(unsigned i=0;i<n;++i)assert(ys[i]==expected[i]);
}
int main(void){
 MEM32(0x20000+ANCHOR)=0x30000;MEM32(0x20000+BACK)=0x40000;
 MEM32(0x30004)=MEM32(0x40004)=0x50000;MEM32(0x50008)=0x1C;
 MEM32(0x30020)=MEM32(0x40020)=0x50100;MEM32(0x50150)=0xF0002;
 MEM32(0x60000)=0x60100;MEM32(0x60120)=0xF0001;
 g_fp_sp=128;g_fp_top=0;fp_set_cw(0x007F);
#ifdef VANILLA
 const float original[]={33,68};check(ORIGINAL_ANCHOR_Y,ORIGINAL_BACK_Y,2,original);
 const float broken[]={-122,-47,28};check(ORIGINAL_ANCHOR_Y,PATCHED_BACK_Y,3,broken);
 const float fixed[]={38,73,108};check(PATCHED_ANCHOR_Y,PATCHED_BACK_Y,3,fixed);
 puts("PASS Vanilla original33/68, broken-122/-47/28, fixed38/73/108; native CombatReplay anchor143 +Back178, real RET0/x87 ABI");
#else
 const float original[]={36,72};check(ORIGINAL_ANCHOR_Y,ORIGINAL_BACK_Y,2,original);
 const float fixed[]={40,76,112};check(PATCHED_ANCHOR_Y,PATCHED_BACK_Y,3,fixed);
 puts("PASS HoF original36/72, fixed40/76/112; native Template anchor112 +Back148, real RET0/x87 ABI");
#endif
 return 0;
}
