"""Run the UUID adapter with deterministic entropy and guest bounds checks."""
import unittest
from test_static_tls import ROOT, compile_probe


class UuidTest(unittest.TestCase):
    def test_layout_entropy_and_invalid_destination(self):
        source = (ROOT / "android/host/rpc.c").read_text()
        body = source[source.index('WINAPI_EXPORT("rpcrt4.dll", UuidCreate, 1)'):]
        compile_probe("rpc_uuid", r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static uint8_t memory[64];
static uint32_t destination;
static unsigned calls;
#define ARG(i) destination
#define GPTR(a) (memory + (a))
#define WINAPI_EXPORT(dll,name,nargs) uint32_t name(void)
static int void_vm_writable(uint32_t a,uint32_t n) { return a >= 16 && a <= sizeof memory - n; }
static void arc4random_buf(void *p,size_t n) {
    assert(n == 16); ++calls;
    for(size_t i=0;i<n;++i) ((uint8_t *)p)[i]=(uint8_t)(0xE0+i+calls);
}
''' + body + r'''
int main(void) {
    memset(memory,0xAA,sizeof memory);
    destination=0; assert(UuidCreate()==87 && calls==0);
    destination=49; assert(UuidCreate()==87 && calls==0);
    destination=16; assert(UuidCreate()==0 && calls==1);
    for(unsigned i=0;i<16;++i) {
        uint8_t expected=(uint8_t)(0xE1+i);
        if(i==7) expected=(expected & 15)|0x40;
        if(i==8) expected=(expected & 63)|0x80;
        assert(memory[16+i]==expected);
        assert(memory[i]==0xAA && memory[32+i]==0xAA);
    }
    destination=32; assert(UuidCreate()==0 && calls==2);
    assert(memcmp(memory+16,memory+32,16));
    puts("PASS UUID: bounded destination, fresh entropy, little-endian v4 GUID layout");
    return 0;
}
''', {})


if __name__ == "__main__":
    unittest.main()
