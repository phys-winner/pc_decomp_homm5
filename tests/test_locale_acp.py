"""Exercise real Russian ACP APIs, explicit CP1252 and ANSI guest paths/resources."""
import unittest
from test_static_tls import ROOT, compile_probe
from test_user32_startup import body

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t memory[0x10000];
#define GPTR(va) (memory + (uint32_t)(va))
#define MEM8(va) (*(uint8_t *)GPTR(va))
#define MEM16(va) (*(uint16_t *)GPTR(va))
#define MEM32(va) (*(uint32_t *)GPTR(va))
static uint32_t args[8], last_error;
#define ARG(n) args[n]
#define WINAPI_EXPORT(dll,name,nargs) uint32_t name##_impl(void)
#define ERROR_INVALID_PARAMETER_ 87u
#define ERROR_INSUFFICIENT_BUFFER_ 122u
#define VLOG(...) ((void)0)
#define void_log(...) ((void)0)
static int void_verbose;
static void void_set_last_error(uint32_t e) { last_error=e; }
#include "strings.h"
#include "locale.h"
static uint32_t void_resource_find(uint32_t module, uint32_t type, uint32_t name, uint32_t *size) {
    assert(module==0x400000 && type==6 && name==1); *size=128; return 0x8000;
}
#include "resource.h"
static const uint16_t page1251[256]={/* CP1251 */};
static const uint16_t page1252[256]={/* CP1252 */};
static const uint16_t name_units[]={0x0418,0x0433,0x0440,0x043E,0x043A,0};
static const uint8_t name_ansi[]={0xC8,0xE3,0xF0,0xEE,0xEA,0};
static const char name_utf8[]="\xD0\x98\xD0\xB3\xD1\x80\xD0\xBE\xD0\xBA";
static uint32_t wide_to_bytes(uint32_t cp, uint32_t cap) {
    args[0]=cp;args[1]=0;args[2]=0x100;args[3]=UINT32_MAX;args[4]=0x200;args[5]=cap;args[6]=0;args[7]=0x300;
    return WideCharToMultiByte_impl();
}
static uint32_t bytes_to_wide(uint32_t cp) {
    args[0]=cp;args[1]=0;args[2]=0x200;args[3]=UINT32_MAX;args[4]=0x400;args[5]=32;
    return MultiByteToWideChar_impl();
}
int main(void) {
    assert(GetACP_impl()==1251 && real_cp(0)==1251 && real_cp(3)==1251);
    assert(real_cp(1252)==1252 && real_cp(65001)==65001);
    assert(GetUserDefaultLCID_impl()==0x419 && GetSystemDefaultLCID_impl()==0x419);
    assert(GetUserDefaultLangID_impl()==0x419 && GetSystemDefaultLangID_impl()==0x419 && GetThreadLocale_impl()==0x419);
    assert(canonical_lcid(0)==0x419 && canonical_lcid(0x400)==0x419 && canonical_lcid(0x800)==0x419 && canonical_lcid(0x409)==0x409);
    for(uint32_t i=0;i<256;++i) {
        uint8_t out;
        assert(void_ansi_to_u16((uint8_t)i)==page1251[i]);
        assert(void_u16_to_ansi(page1251[i],&out) && out==i);
        assert(void_cp1252_to_u16((uint8_t)i)==page1252[i]);
        assert(void_u16_to_cp1252(page1252[i],&out) && out==i);
    }
    assert(void_cp1252_to_u16(0xE9)==0xE9 && void_ansi_to_u16(0xE9)==0x439);
    assert(void_ansi_lower(0xD7)==0xF7 && void_ansi_lower(0xA8)==0xB8);
    memcpy(GPTR(0x100),name_units,sizeof name_units);
    for(uint32_t cp=0;cp<=3;cp+=3) {
        MEM32(0x300)=99;
        assert(wide_to_bytes(cp,32)==6 && !memcmp(GPTR(0x200),name_ansi,sizeof name_ansi) && MEM32(0x300)==0);
        assert(bytes_to_wide(cp)==6 && !memcmp(GPTR(0x400),name_units,sizeof name_units));
    }
    assert(wide_to_bytes(1252,32)==6 && !memcmp(GPTR(0x200),"?????",6) && MEM32(0x300)==1);
    assert(bytes_to_wide(1252)==6 && memcmp(GPTR(0x400),name_units,sizeof name_units));
    assert(wide_to_bytes(1251,0)==6 && MEM32(0x300)==0);
    assert(wide_to_bytes(1251,5)==0 && last_error==122);
    assert(wide_to_bytes(65001,32)==11 && !strcmp((char *)GPTR(0x200),name_utf8));
    assert(bytes_to_wide(65001)==6 && !memcmp(GPTR(0x400),name_units,sizeof name_units));
    MEM16(0x100)=0xE9;MEM16(0x102)=0;
    assert(wide_to_bytes(1252,32)==2 && MEM8(0x200)==0xE9 && MEM32(0x300)==0);
    assert(bytes_to_wide(1252)==2 && MEM16(0x400)==0xE9);
    args[0]=0;args[1]=0x500;assert(GetCPInfo_impl()==1 && MEM32(0x500)==1 && MEM8(0x504)=='?');
    args[0]=0x800;args[1]=0x1004;args[2]=0x600;args[3]=32;
    assert(GetLocaleInfoA_impl()==5 && !strcmp((char *)GPTR(0x600),"1251"));
    args[0]=0x409;assert(GetLocaleInfoA_impl()==5 && !strcmp((char *)GPTR(0x600),"1252"));
    args[0]=0x800;args[1]=0x40000003u;
    assert(GetLocaleInfoA_impl()==4 && !strcmp((char *)GPTR(0x600),"RUS"));
    args[1]=0x40000004u;
    assert(GetLocaleInfoA_impl()==8 && MEM8(0x600)==0xF0 && MEM8(0x606)==0xE9);
    strcpy((char *)GPTR(0x1000),"C:\\Profiles\\");
    memcpy(GPTR(0x1000+12),name_ansi,sizeof name_ansi);
    char *path=void_astr_utf8(0x1000);
    char expected[128];snprintf(expected,sizeof expected,"C:\\Profiles\\%s",name_utf8);
    assert(!strcmp(path,expected));free(path);
    assert(void_utf8_to_ga(expected,0x1200,128)==17 && !memcmp(GPTR(0x1200),GPTR(0x1000),18));
    MEM16(0x8000)=5;memcpy(GPTR(0x8002),name_units,10);
    args[0]=0x400000;args[1]=0;args[2]=0x2000;args[3]=16;
    assert(LoadStringA_impl()==5 && !memcmp(GPTR(0x2000),name_ansi,sizeof name_ansi));
    puts("PASS actual Russian ACP: 512 byte mappings, CP0/CP3, explicit1252, UTF8, sizing/default flags, locale consistency, Cyrillic paths/resources and lossy-name roundtrip");
    return 0;
}
'''


class LocaleACPTest(unittest.TestCase):
    def test_actual_bodies(self):
        kernel=(ROOT/"android/host/kernel32.c").read_text(encoding="utf-8")
        locale=kernel[kernel.index("static uint32_t real_cp"):kernel.index("WINAPI_EXPORT(K32, EnumSystemLocalesA")]
        # Keep the production UTF8 bytes even with MSVC's default source charset.
        locale="".join("".join("\\x%02X" % b for b in c.encode("utf-8")) if ord(c)>127 else c for c in locale)
        strings=(ROOT/"android/host/strings.c").read_text(encoding="utf-8").replace('#include "host.h"',"")
        user=(ROOT/"android/host/user32.c").read_text(encoding="utf-8")
        tables={}
        for page in (1251,1252):
            units=[]
            for value in range(256):
                try: units.append(ord(bytes([value]).decode("cp"+str(page))))
                except UnicodeError: units.append(value)
            tables[page]=",".join(map(str,units))
        fixture=HARNESS.replace("/* CP1251 */",tables[1251]).replace("/* CP1252 */",tables[1252])
        compile_probe("locale_acp",fixture,{"strings.h":strings,"locale.h":locale,"resource.h":body(user,"WINAPI_EXPORT(U32, LoadStringA,")})


if __name__=="__main__":
    unittest.main()
