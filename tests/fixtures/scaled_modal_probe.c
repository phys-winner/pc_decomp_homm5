#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned char memory[0x20000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define MEMF(a) (*(float *)GPTR(a))
#define MEM8(a) (*(uint8_t *)GPTR(a))
#define VLOG(...) ((void)0)
static struct {uint32_t screen;int requested,percent;} fit;
static struct {uint32_t screen;} viewport;
static uint32_t viewport_scratch;
static int void_vm_readable(uint32_t a,uint32_t n){return a>=0x100&&(uint64_t)a+n<=sizeof memory;}
static int void_vm_writable(uint32_t a,uint32_t n){return void_vm_readable(a,n);}
static int void_dispatch_find(uint32_t a){(void)a;assert(0);return 0;}
static uint32_t void_call_guest_this(uint32_t a,uint32_t self,int n,const uint32_t *args){
    (void)a;(void)self;(void)n;(void)args;assert(0);return 0;
}
static void void_touch_combat_frame(uint32_t s,float w,float h,float hud,float t,float b){
    (void)s;(void)w;(void)h;(void)hud;(void)t;(void)b;assert(0);
}
static void void_touch_adventure_frame(uint32_t s,float h,float t,float b){
    (void)s;(void)h;(void)t;(void)b;assert(0);
}
/* ACTUAL */
int main(void){
    /* The original CWindow placement getter and IScreen layout slots. */
    static const unsigned char getter[]={0x8B,0x81,0x40,0x01,0,0,0xC3};
    memcpy(GPTR(0x7000),getter,sizeof getter);
    MEM32(0x6008)=0x7000;
    MEM32(0x1000)=MEM32(0x3000)=0x6000;
    MEM32(0x1140)=0x2000;MEM32(0x3140)=0x4000;
    MEM32(0x10F8)=0x5000;MEM32(0x5048)=ROOT_LAYOUT;
    MEM32(0x504C)=ROOT_REPOSITION;
    MEM32(0x3028)=0x1000;
    MEM32(0x10A4)=0x8000;MEM32(0x10A8)=0x8004;MEM32(0x8000)=0x3000;
    MEM8(0x2070)=MEM8(0x4070)=1;
    MEMF(0x20A4)=1024;MEMF(0x20A8)=768;
    MEMF(0x40A4)=526;MEMF(0x40A8)=465;
    MEM32(0x4094)=MEM32(0x409C)=1;
    MEMF(0x3064)=168;MEMF(0x3068)=0;
    fit.screen=0x9000;MEM32(0x9000+MODAL_HEAD)=0xA000;MEM32(0xA000)=0xA004;
    assert(scale_fits(0x1000,0,862,384,1724,768,200)==165);
    for(int i=0;i<120;++i)
        assert(scale_fits(0x1000,0,172400.0f/165,76800.0f/165,1724,768,200)==165);
    MEM32(0xA000)=0xA000;
    assert(scale_fits(0x1000,0,172400.0f/165,76800.0f/165,1724,768,200)==200);
    /* ChangeProfile and its SetupPanel keep their native 16-unit gap. */
    MEMF(0x40A4)=498;MEMF(0x40A8)=464;MEM32(0x409C)=0;MEM32(0x4094)=2;MEMF(0x408C)=-220;
    MEMF(0x3064)=MEMF(0x3068)=0;
    assert(scale_fits(0x1000,0,862,384,1724,768,200)==112);
    float top=84+scale_anchor_shift(2,84,464,0,768,76800.0f/112);
    MEMF(0x3068)=top;
    assert(scale_fits(0x1000,0,172400.0f/112,76800.0f/112,1724,768,200)==112);
    float setup=564+scale_anchor_shift(2,564,113,0,768,76800.0f/112);
    assert(top>=0&&setup-(top+464)==16);
    /* HoF ChangeProfile's bottom inset, with far-edge artwork overdraw retained. */
    assert(84+scale_anchor_shift(2,84,464,0,768,76800.0f/165)==0);
    assert(scale_anchor_shift(2,774,256,0,1024,985)==-39);
    puts("PASS actual edition modal fit: stable 165 across 120 frames, native modal-head layout, close restores 200, profile visible and HUD overdraw retained");
    return 0;
}
