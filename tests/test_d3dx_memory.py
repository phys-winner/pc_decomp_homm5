"""Actual D3DX export, format decoder/encoder and system-memory surface writer."""
import os
from pathlib import Path
import re
import subprocess
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from android_tools import NDK

ROOT = Path(__file__).resolve().parents[1]

HEADER = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <GLES3/gl32.h>
#include <GLES2/gl2ext.h>
#define FOURCC(a,b,c,d) ((uint32_t)(a) | ((uint32_t)(b)<<8) | ((uint32_t)(c)<<16) | ((uint32_t)(d)<<24))
#define D3DUSAGE_RENDERTARGET 1
#define D3D_OK 0u
#define D3DERR_INVALIDCALL 0x8876086Cu
#define E_OUTOFMEMORY_ 0x8007000Eu
#define E_NOTIMPL_ 0x80004001u
#define D3DX "d3dx9_25.dll"
#define VOID_SHIM_SECTION
typedef void (*void_fn)(void);
typedef struct { const char *dll, *name; uint32_t ordinal; void_fn fn; } void_shim;
static uint8_t memory[0x40000];
static uint32_t g_esp, g_eax;
#define GPTR(a) (memory+(uint32_t)(a))
#define MEM32(a) (*(uint32_t*)GPTR(a))
#define ARG(i) MEM32(g_esp+4+4*(i))
static int void_vm_readable(uint32_t address, uint32_t size) {
    return address >= 0x100 && (uint64_t)address + size <= sizeof memory &&
        !((uint64_t)address < 0x21000 && (uint64_t)address + size > 0x20000);
}
static uint32_t void_galloc(uint32_t size) { assert(size < 0x1000); return 0x30000; }
static void void_gfree(uint32_t address) { (void)address; }
typedef struct { const char *name; } object_class;
typedef struct { object_class *cls; } object_header;
typedef struct { uint32_t *sysmem, levels; } texture;
/* FORMAT_TYPES */
/* GL_LIMITS_TYPE */
static d3d_gl_limits_t d3d_gl_limits;
typedef struct {
    object_header com;
    uint32_t width, height, format, pitch, sysmem, face, level;
    const d3d_format *fmt;
    texture *container;
} d3d_surface;
static object_class surface_class={"IDirect3DSurface9"};
static d3d_surface surface;
static void *void_com_host(uint32_t address) { assert(address==0x100); return &surface; }
static void surface_upload_rect(d3d_surface *s, uint32_t mem, const uint32_t *rect) { (void)s; (void)mem; (void)rect; assert(0); }
/* No DXVK surface here (android/host/d3d9_dxvk.c): the GLES branch is the one under test. */
static void *void_dxvk_native(uint32_t guest) { (void)guest; return NULL; }
static uint32_t void_dxvk_surface_desc(void *s, uint32_t desc[5]) { (void)s; (void)desc; assert(0); return 0; }
/* REAL_CODE */
static int fail_alloc;
static void *checked_malloc(size_t n) { return fail_alloc ? NULL : malloc(n); }
static int dxvk_write_rgba(void *s, const d3d_format *f, const uint32_t *rect, const float *rgba) { (void)s; (void)f; (void)rect; (void)rgba; assert(0); return 0; }
#define malloc checked_malloc
/* REAL_EXPORT */
#undef malloc
static void rect(uint32_t address, uint32_t x, uint32_t y, uint32_t right, uint32_t bottom) {
    MEM32(address)=x; MEM32(address+4)=y; MEM32(address+8)=right; MEM32(address+12)=bottom;
}
static void setup(uint32_t w, uint32_t h, uint32_t format) {
    memset(memory,0,sizeof memory); memset(&surface,0,sizeof surface);
    surface.com.cls=&surface_class; surface.width=w; surface.height=h;
    surface.format=format; surface.fmt=d3d_format_find(format); surface.sysmem=0x8000;
    surface.pitch=d3d_format_pitch(surface.fmt,w); g_esp=0x1000;
    ARG(0)=0x100; ARG(3)=0x4000; ARG(4)=21; ARG(5)=w*4; ARG(7)=0x2000; ARG(8)=1;
    rect(0x2000,0,0,w,h); MEM32(0x102c)=0xdeadbeef; fail_alloc=0;
}
static uint32_t run(void) {
    g_esp=0x1000; D3DXLoadSurfaceFromMemory_entry();
    assert(g_esp==0x102c && MEM32(0x102c)==0xdeadbeef); g_esp=0x1000; return g_eax;
}
static void reject(uint32_t hr) {
    uint8_t before[0x1000]; memcpy(before,GPTR(0x8000),sizeof before);
    assert(run()==hr && !memcmp(before,GPTR(0x8000),sizeof before));
}
int main(void) {
    setup(2,2,21);
    assert(!strcmp(D3DXLoadSurfaceFromMemory_shim.dll,"d3dx9_25.dll"));
    uint32_t colors[4]={0xff112233,0x80445566,0xff778899,0xffabcdef};
    memcpy(GPTR(0x4000),colors,sizeof colors);
    assert(run()==0 && !memcmp(GPTR(0x8000),colors,sizeof colors));
    setup(2,2,21); ARG(5)=20; rect(0x2000,1,1,3,3);
    for(uint32_t y=0;y<3;y++) for(uint32_t x=0;x<5;x++) MEM32(0x4000+y*20+x*4)=0xff000000|y*16|x;
    assert(run()==0 && MEM32(0x8000)==0xff000011 && MEM32(0x800c)==0xff000022);
    setup(4,4,21); ARG(2)=0x2020; ARG(5)=8; rect(0x2020,1,1,3,3); rect(0x2000,0,0,2,2);
    memcpy(GPTR(0x4000),colors,sizeof colors); memset(GPTR(0x8000),0xa5,64);
    assert(run()==0 && MEM32(0x8014)==colors[0] && MEM32(0x8028)==colors[3] && MEM32(0x8000)==0xa5a5a5a5);
    setup(3,3,21); ARG(5)=8; rect(0x2000,0,0,2,2); memcpy(GPTR(0x4000),colors,sizeof colors);
    assert(run()==0 && MEM32(0x8000)==colors[0] && MEM32(0x8010)==colors[3] && MEM32(0x8014)==0 && MEM32(0x8020)==0);
    setup(2,1,21); MEM32(0x4000)=0xff112233; MEM32(0x4004)=0x00112233; ARG(9)=0xff112233;
    assert(run()==0 && MEM32(0x8000)==0 && MEM32(0x8004)==0x00112233);
    setup(2,1,23); ARG(4)=22; MEM32(0x4000)=0xff0000; MEM32(0x4004)=0x00ff00;
    assert(run()==0 && *(uint16_t*)GPTR(0x8000)==0xf800 && *(uint16_t*)GPTR(0x8002)==0x07e0);
    setup(2,2,21); ARG(4)=FOURCC('D','X','T','1'); ARG(5)=8; rect(0x2000,1,1,3,3);
    *(uint16_t*)GPTR(0x4000)=0xf800;
    assert(run()==0 && MEM32(0x8000)==0xffff0000 && MEM32(0x800c)==0xffff0000);
    setup(1,1,21); ARG(5)=8; ARG(8)=2; rect(0x2000,0,0,2,2); memcpy(GPTR(0x4000),colors,sizeof colors);
    assert(run()==0 && MEM32(0x8000)==colors[3]);
    setup(1,1,21); ARG(5)=8; ARG(8)=5; rect(0x2000,0,0,2,2);
    MEM32(0x4000)=0xffff0000; MEM32(0x4004)=0xff00ff00; MEM32(0x4008)=0xff0000ff; MEM32(0x400c)=0xffffffff;
    assert(run()==0 && MEM32(0x8000)==0xff808080);
    setup(2,2,21); ARG(0)=0; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(3)=0; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(7)=0; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(7)=sizeof memory-8; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(2)=sizeof memory-8; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); rect(0x2000,UINT32_MAX,0,2,2); reject(D3DERR_INVALIDCALL);
    setup(2,2,21); rect(0x2000,0,0,0,2); reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(5)=7; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(5)=0; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(3)=0x1fff8; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(3)=UINT32_MAX-10; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(5)=UINT32_MAX; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(2)=0x2020; rect(0x2020,0,0,3,2); reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(4)=41; reject(E_NOTIMPL_);
    setup(2,2,21); ARG(4)=0; reject(D3DERR_INVALIDCALL);
    setup(2,2,21); ARG(4)=75; reject(D3DERR_INVALIDCALL);
    setup(2,2,FOURCC('D','X','T','1')); reject(E_NOTIMPL_);
    setup(2,2,21); ARG(8)=3; reject(E_NOTIMPL_);
    setup(2,2,21); ARG(8)=5; reject(E_NOTIMPL_);
    setup(2,2,21); fail_alloc=1; reject(E_OUTOFMEMORY_);
    /* GPU-native formats of converted textures: ETC2 always, ASTC only with the extension. */
    static const struct { uint32_t fourcc, internal, block, bytes, astc; } natives[] = {
        {FOURCC('H','5','E','1'),GL_COMPRESSED_RGB8_ETC2,4,8,0},{FOURCC('H','5','E','2'),GL_COMPRESSED_RGBA8_ETC2_EAC,4,16,0},
        {FOURCC('H','5','A','4'),GL_COMPRESSED_RGBA_ASTC_4x4_KHR,4,16,1},{FOURCC('H','5','A','5'),GL_COMPRESSED_RGBA_ASTC_5x5_KHR,5,16,1},
        {FOURCC('H','5','A','6'),GL_COMPRESSED_RGBA_ASTC_6x6_KHR,6,16,1}};
    for(unsigned i=0;i<5;i++) {
        const d3d_native_format *n=d3d_native_find(natives[i].fourcc);
        assert(n && n->fourcc==natives[i].fourcc && n->internal==natives[i].internal && n->astc==(int)natives[i].astc);
        assert(n->block_w==natives[i].block && n->block_h==natives[i].block && n->block_bytes==natives[i].bytes);
        uint32_t b=natives[i].block;
        assert(d3d_native_size(n,13,7)==((13+b-1)/b)*((7+b-1)/b)*natives[i].bytes && d3d_native_size(n,b,b)==natives[i].bytes);
        d3d_gl_limits.astc_ldr=0; assert(d3d_native_supported(n)==!natives[i].astc);
        d3d_gl_limits.astc_ldr=1; assert(d3d_native_supported(n));
    }
    assert(!d3d_native_find(FOURCC('D','X','T','1')) && !d3d_native_find(FOURCC('H','5','T','C')) && !d3d_native_supported(NULL));
    assert(!d3d_format_find(FOURCC('H','5','E','1')));
    puts("PASS actual D3DX: stdcall40, pitched/cropped BGRA, destination rect, NONE padding, alpha color key, RGB565, cropped DXT, POINT, BOX, invalid memory/rect/pitch, unsupported modes, allocation failure; native ETC2/ASTC block formats");
    return 0;
}
'''


class D3dxMemoryTest(unittest.TestCase):
    def test_actual_code(self):
        out = ROOT / "build/tests/d3dx_memory"
        out.mkdir(parents=True, exist_ok=True)
        host = (ROOT / "android/host/host.h").read_text()
        macro = host[host.index("#define WINAPI_EXPORT(dll,"):host.index("/* Same but exported only by ordinal")]
        internal = (ROOT / "android/host/d3d9_internal.h").read_text()
        # The format table types and the converted textures' native block formats.
        types = internal[internal.index("enum {\n    CONV_NONE"):internal.index("/* Guest pitch of one row")]
        limits = re.search(r"^typedef struct \{[^}]*\} d3d_gl_limits_t;$", internal, re.M)[0]
        real = "\n".join((ROOT / f"android/host/{name}.c").read_text().replace('#include "d3d9_internal.h"', "") for name in ("d3d9_format", "d3d9_texel"))
        resource = (ROOT / "android/host/d3d9_resource.c").read_text()
        real += resource[resource.index("int d3d_surface_write_rgba("):resource.index("COM_METHOD(surf, UnlockRect")]
        d3dx = (ROOT / "android/host/d3dx9.c").read_text()
        export = d3dx[d3dx.index("WINAPI_EXPORT(D3DX, D3DXLoadSurfaceFromMemory,"):d3dx.index("WINAPI_EXPORT(D3DX, D3DXLoadSurfaceFromSurface,")]
        fixture = HEADER.replace("/* FORMAT_TYPES */", types).replace("/* GL_LIMITS_TYPE */", limits)
        fixture = fixture.replace("/* REAL_CODE */", macro + real).replace("/* REAL_EXPORT */", export)
        (out / "probe.c").write_text(fixture)
        vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
        installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"], text=True).strip())
        msvc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
        sdk = Path(r"C:\Program Files (x86)\Windows Kits\10")
        version = sorted((sdk / "Lib").iterdir())[-1].name
        compiler = msvc / "bin/Hostx64/x64/cl.exe"
        env = os.environ.copy()
        env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
        env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk / f"Include/{version}/ucrt", sdk / f"Include/{version}/shared", sdk / f"Include/{version}/um", NDK / "toolchains/llvm/prebuilt/windows-x86_64/sysroot/usr/include"]))
        env["LIB"] = ";".join(map(str, [msvc / "lib/x64", sdk / f"Lib/{version}/ucrt/x64", sdk / f"Lib/{version}/um/x64"]))
        compiled = subprocess.run([str(compiler), "/nologo", "/W3", "/std:c11", "/D_CRT_SECURE_NO_WARNINGS", "probe.c", "/Fe:probe.exe"], cwd=out, env=env, text=True, capture_output=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        tested = subprocess.run([str(out / "probe.exe")], text=True, capture_output=True, timeout=10)
        self.assertEqual(tested.returncode, 0, tested.stdout + tested.stderr)
        print(tested.stdout.strip())


if __name__ == "__main__":
    unittest.main()
