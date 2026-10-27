#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define HOMM5_LEGACY_UI 1
static unsigned char memory[0x1100000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEMF(a) (*(float *)GPTR(a))
static uint32_t viewport_scratch;
static int callbacks, cycle;
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100&&(uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n) {return void_vm_readable(a,n);}
static uint32_t void_galloc(uint32_t size) {assert(size==16);return 0x32000;}
static uint32_t void_call_guest(uint32_t address,int n,const uint32_t *args,int pops) {
 if(address==GET_SCREEN){assert(!n&&!args&&pops);return 0x20000;}
 assert(address==DYNAMIC_CAST&&n==5&&args[0]==0x20024&&!pops);return 0x22000;
}
static uint32_t void_call_guest_this(uint32_t address,uint32_t object,int n,const uint32_t *args) {
 unsigned phase=(unsigned)callbacks++%4;
 if(phase==0){assert(address==LAYOUT&&object==0x300F8&&n==1&&args[0]==viewport_scratch);}
 else if(phase==1){assert(address==INVALIDATE&&object==0x3010C&&!n&&!args);}
 else if(phase==2){assert(address==CHILDREN&&object==0x30000&&!n&&!args);}
 else {assert(address==NEXT_SCREEN&&object==0x20000&&!n&&!args);return cycle?0x20000:0;}
 return 0;
}
/* ACTUAL */
int main(void) {
 MEM32(0x20004)=0x21000;MEM32(0x21004)=0x20;
 MEM32(0x22000+0x98)=0x300F8;MEM32(0x22000+0x144)=0x23000;MEM32(0x23000)=0x23000;
 MEM32(0x300F8)=0x24000;MEM32(0x24000+0x48)=LAYOUT;MEM32(0x24000+0x4C)=0;
 assert(scale_is_root(0x30000));
 MEM32(0x300F8+0xC8)=0x31000;
 const int scales[]={50,100,200};
 for(unsigned scale=0;scale<3;++scale)for(unsigned x=0;x<4;++x)for(unsigned y=0;y<4;++y) {
  float width=1706.0f*100/scales[scale],height=768.0f*100/scales[scale];
  MEMF(CANVAS_X)=width;MEMF(CANVAS_Y)=height;
  MEM32(0x310FC)=x;MEM32(0x31100)=y;
  void_touch_legacy_root_rect(0x300F8,0x32000);
  float *r=(float *)GPTR(0x32000);
  assert(r[0]==0&&r[1]==0&&r[2]==width&&r[3]==height);
 }
 void_touch_legacy_relayout();assert(callbacks==4&&viewport_scratch==0x32000);
 cycle=1;void_touch_legacy_relayout();assert(callbacks==8);
 cycle=0;void_touch_legacy_resize(2399,1080);assert(callbacks==12);
 assert(MEMF(PHYSICAL_X)==2399&&MEMF(PHYSICAL_Y)==1080&&MEMF(CANVAS_X)==1706&&MEMF(CANVAS_Y)==768);
 void_touch_legacy_resize(0,1080);assert(callbacks==12);
 puts("PASS actual legacy UI root: full parent canvas atUI50/100/200, absentToEresourcefields ignored, original three-call layout ABI, removedToEslot unused, screenlistcycle guard, native resize");
}
