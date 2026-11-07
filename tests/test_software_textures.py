"""The production CPU texture hook must hand decoded BGRA to the original loader."""
import unittest
from test_static_tls import ROOT, compile_probe


HARNESS = r'''
#define __ANDROID__ 1
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t memory[0x40000], source_before[0x1000];
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t *)GPTR(a))
#define FOURCC(a,b,c,d) ((uint32_t)(a)|((uint32_t)(b)<<8)|((uint32_t)(c)<<16)|((uint32_t)(d)<<24))
static uint32_t g_ecx,g_eax,g_esp;
typedef struct {uint32_t fourcc;} d3d_native_format;
static d3d_native_format fixture_native={FOURCC('H','5','A','4')};
static int fail_alloc,fail_decode,allocs,frees,calls,expected_raw,decode_calls;
static int void_vm_readable(uint32_t a,uint32_t n) {return a>=0x100 && (uint64_t)a+n<=sizeof memory;}
static uint32_t void_galloc(uint32_t n) {if(fail_alloc)return 0;assert(n<0x10000);allocs++;memset(GPTR(0x10000),0,n);return 0x10000;}
static void void_gfree(uint32_t a) {assert(a==0x10000);frees++;}
static void void_log(const char *s,...) {(void)s;}
static const d3d_native_format *d3d_native_find(uint32_t f) {return f==fixture_native.fourcc?&fixture_native:NULL;}
static int d3d_native_supported(const d3d_native_format *n) {return n!=NULL;}
static int decode(const uint8_t *dds,uint64_t size,uint32_t level,uint8_t *rgba) {
    assert(dds==GPTR(0x4000) && size==208 && level<4);decode_calls++;
    if(fail_decode)return -1;
    unsigned w=8>>level,h=4>>level;if(!w)w=1;if(!h)h=1;
    for(unsigned i=0;i<w*h;i++){rgba[4*i]=(uint8_t)(10+level);rgba[4*i+1]=20;rgba[4*i+2]=30;rgba[4*i+3]=40;}
    return 0;
}
#define RTLD_NOW 2
#define RTLD_LOCAL 0
static void *dlopen(const char *name,int flags) {assert(!strcmp(name,"libtexconv.so"));(void)flags;return (void *)1;}
static void *dlsym(void *lib,const char *name) {assert(lib==(void *)1 && !strcmp(name,"texconv_decode_converted"));return (void *)decode;}
static void sub_00A9CDC0_lifted(void) {g_eax=6;g_esp+=4;}
static void sub_00CC5F50_lifted(void) {
    calls++;assert(g_ecx==0x1000 && g_esp==0x3000);
    uint32_t io=0x201c,begin=MEM32(io+4),end=MEM32(io+12);
    if(expected_raw) {
        assert(begin!=0x4000 && end-begin==300);
        assert(MEM32(begin+80)==0x41 && !MEM32(begin+84) && MEM32(begin+88)==32);
        assert(MEM32(begin+92)==0xff0000 && MEM32(begin+96)==0xff00 && MEM32(begin+100)==0xff && MEM32(begin+104)==0xff000000);
        assert(!MEM32(begin+36) && MEM32(begin+28)==4);
        unsigned at=128;
        for(unsigned level=0;level<4;level++) {
            unsigned w=8>>level,h=4>>level;if(!w)w=1;if(!h)h=1;
            for(unsigned i=0;i<w*h;i++,at+=4) {
                uint8_t *p=GPTR(begin+at);assert(p[0]==30 && p[1]==20 && p[2]==10+level && p[3]==40);
            }
        }
        assert(at==300);
    } else assert(begin==0x4000 && end-begin==208);
    MEM32(io+16)=end;g_eax=0xabcdef;g_ecx=0x123456;g_esp+=4;
}
/* PRODUCTION */
static void setup(void) {
    memset(memory,0,sizeof memory);g_ecx=0x1000;g_esp=0x3000;
    MEM32(0x103c)=0x2000;
    for(unsigned i=4;i<=16;i+=4)MEM32(0x201c+i)=i==4||i==16?0x4000:0x40d0;
    uint32_t h=0x4000;MEM32(h)=FOURCC('D','D','S',' ');MEM32(h+4)=124;
    MEM32(h+8)=0xa1007;MEM32(h+12)=4;MEM32(h+16)=8;MEM32(h+28)=4;
    MEM32(h+36)=FOURCC('H','5','T','C');MEM32(h+40)=2;MEM32(h+44)=FOURCC('D','X','T','5');MEM32(h+48)=4;
    MEM32(h+76)=32;MEM32(h+80)=4;MEM32(h+84)=fixture_native.fourcc;MEM32(h+108)=0x401008;
    fail_alloc=fail_decode=decode_calls=0;expected_raw=1;
    memcpy(source_before,GPTR(h),208);
}
static void run(void) {
    sub_00CC5F50();assert(g_esp==0x3004 && g_eax==0xabcdef && g_ecx==0x123456);
    assert(!memcmp(source_before,GPTR(0x4000),208));
    assert(MEM32(0x2020)==0x4000 && MEM32(0x2024)==0x40d0 && MEM32(0x2028)==0x40d0 && MEM32(0x202c)==0x40d0);
    assert(allocs==frees);
}
int main(void) {
    setup();run();assert(decode_calls==4);
    setup();fail_alloc=1;expected_raw=0;run();assert(!decode_calls);
    setup();fail_decode=1;expected_raw=0;run();assert(decode_calls==1);
    setup();MEM32(0x4024)=0;memcpy(source_before,GPTR(0x4000),208);expected_raw=0;run();assert(!decode_calls);
    setup();MEM32(0x4010)=0xffffffff;memcpy(source_before,GPTR(0x4000),208);expected_raw=0;run();assert(!decode_calls);
    puts("PASS software converted DDS: all mips/tiny levels, BGRA, original loader/stream/guest ABI, unchanged source, OOM/decode failure/native fallback");
    return 0;
}
'''


class SoftwareTexturesTest(unittest.TestCase):
    def test_converted_dds_reaches_original_cpu_loader_as_bgra(self):
        source = (ROOT / "android/host/texture_native.c").read_text()
        source = "\n".join(line for line in source.splitlines() if not line.startswith("#include"))
        compile_probe("software-textures", HARNESS.replace("/* PRODUCTION */", source), {})

    def test_legacy_cpu_loader_keeps_its_current_path(self):
        source = (ROOT / "android/host/texture_native.c").read_text()
        source = "\n".join(line for line in source.splitlines() if not line.startswith("#include"))
        harness = HARNESS[:HARNESS.index("int main(void) {")] + r'''
int main(void) {
    setup();expected_raw=0;run();assert(!decode_calls);
    puts("PASS legacy CPU texture loader unchanged");return 0;
}
'''
        compile_probe("software-textures-legacy", "#define HOMM5_LEGACY_UI 1\n" + harness.replace("/* PRODUCTION */", source), {})


if __name__ == "__main__":
    unittest.main()
