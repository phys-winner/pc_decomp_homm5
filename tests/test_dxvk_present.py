"""Execute the production DXVK Present boundary with native-window spies."""
import unittest

from test_static_tls import ROOT, compile_probe


def function(source, signature):
    start = source.index(signature)
    end = source.index("{", start)
    depth = 1
    while depth:
        end += 1
        depth += (source[end] == "{") - (source[end] == "}")
    return source[start:end + 1]


HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cmath>
#include <algorithm>
#include <array>
#include <atomic>
#include <map>
using HRESULT = int32_t;
using LONG = int32_t;
struct ANativeWindow { int width, height; } old_window{2400,1080}, new_window{2400,1080};
using HWND = ANativeWindow*;
struct RECT { LONG left, top, right, bottom; } source_rect{0,0,1024,768};
constexpr uint32_t D3D_OK = 0, D3DERR_INVALIDCALL = 0x8876086cu;
#define FAILED(hr) ((hr) < 0)
enum class Kind { IDirect3DDevice9, IDirect3DSwapChain9 };
struct IDirect3DDevice9 {
  int calls=0, releases=0; HWND destination=nullptr; RECT rect{};
  const RECT *source=nullptr;
  HRESULT Present(const RECT *src, const RECT *dst, HWND window, const void *dirty) {
    assert(!dirty); ++calls; destination=window; rect=*dst; source=src; return D3D_OK;
  }
  void Release() { ++releases; }
} test_device;
struct IDirect3DSwapChain9 {
  uint32_t flags=0;
  HRESULT Present(const RECT *src,const RECT *dst,HWND window,const void *dirty,uint32_t f) {
    flags=f; return test_device.Present(src,dst,window,dirty);
  }
} chain;
struct Context { Kind kind; void *self; unsigned slot; const uint32_t *a; };
static std::map<void*, ANativeWindow*> device_windows;
static std::map<void*, std::array<uint32_t,14>> parameters;
static std::map<void*, uint32_t> focus_windows;
static std::atomic<uint32_t> backbuffer_width{1024},backbuffer_height{768};
static ANativeWindow *current_window=&old_window;
static int acknowledgements;
struct Host { void (*window_ack)(uint32_t); } services{[](uint32_t serial){assert(serial==7);++acknowledgements;}};
static Host *host=&services;
struct WindowLease { ANativeWindow *value=current_window; uint32_t serial=7; };
static IDirect3DDevice9 *context_device(const Context &c,IDirect3DDevice9 **owned) {
  *owned=c.kind==Kind::IDirect3DSwapChain9?&test_device:nullptr;return &test_device;
}
static void keep_window(void *d,WindowLease &lease) { device_windows[d]=lease.value; }
static ANativeWindow *device_present_window(IDirect3DDevice9*) { return &old_window; }
static int ANativeWindow_getWidth(ANativeWindow *w){return w->width;}
static int ANativeWindow_getHeight(ANativeWindow *w){return w->height;}
template<class T> T *memory(uint32_t va) { assert(!va || va==0x100);return va?&source_rect:nullptr; }
struct PresentTime { PresentTime() {} ~PresentTime() {} };
template<class... A> static void sayf(const char*,A...) {}
#include "present.h"
int main() {
  parameters[&test_device][7]=0x10010;
  focus_windows[&test_device]=0x10020;
  uint32_t a[5]={0,0,0,0,0};
  Context c{Kind::IDirect3DDevice9,&test_device,17,a};
  assert(present(c)==0 && test_device.calls==1 && !test_device.destination);
  assert(test_device.rect.left==480 && test_device.rect.right==1920 && test_device.rect.bottom==1080);
  a[2]=0x10010; assert(present(c)==0 && test_device.calls==2 && !test_device.destination);
  a[2]=0x10020; assert(present(c)==0 && test_device.calls==3 && !test_device.destination);
  a[2]=0xDEADBEEF; assert(present(c)==uint32_t(D3DERR_INVALIDCALL) && test_device.calls==3);
  a[2]=0x10010; a[3]=0x100; assert(present(c)==uint32_t(D3DERR_INVALIDCALL) && test_device.calls==3);
  a[3]=0; a[0]=0x100; a[1]=0x100;
  current_window=&new_window;
  assert(present(c)==0 && test_device.calls==4 && test_device.destination==&new_window && test_device.source==&source_rect);
  assert(test_device.rect.right==1024 && test_device.rect.bottom==768);
  c.kind=Kind::IDirect3DSwapChain9;c.self=&chain;a[4]=8;
  assert(present(c)==0 && test_device.calls==5 && chain.flags==8 && test_device.releases==1);
  a[2]=0xDEADBEEF;
  assert(present(c)==uint32_t(D3DERR_INVALIDCALL) && test_device.calls==5 && test_device.releases==2);
  current_window=nullptr;a[2]=0;
  assert(present(c)==0 && test_device.calls==5 && acknowledgements>0);
  puts("PASS DXVK Present: default/test_device/focus windows, foreign HWND and dirty region rejected, aspect/rects, replaced surface, swapchain refs/flags");
}
'''


class DxvkPresentTest(unittest.TestCase):
    def test_pc_backbuffers_and_physical_display_modes(self):
        source = (ROOT / "android/dxvk/bridge.cpp").read_text(encoding="utf-8")
        fixture = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using HRESULT=int32_t;
enum D3DFORMAT { D3DFMT_X8R8G8B8=22,D3DFMT_R5G6B5=23 };
enum { D3DDEVTYPE_HAL=1,TRUE=1 };
constexpr uint32_t D3D_OK=0,D3DERR_INVALIDCALL=0x8876086cu;
#define FAILED(hr) ((hr)<0)
struct D3DDISPLAYMODE {uint32_t Width,Height,RefreshRate;D3DFORMAT Format;} output;
struct IDirect3D9 {
 bool supported=true;
 unsigned GetAdapterCount(){return 1;}
 HRESULT CheckDeviceType(unsigned adapter,int type,D3DFORMAT a,D3DFORMAT b,int windowed){
  assert(!adapter&&type==1&&a==b&&windowed);return supported?0:-1;
 }
} test_d3d;
struct Context {int kind;void *self;unsigned slot;const uint32_t *a;};
static uint32_t physical_w=2400,physical_h=1080;
static int display_mode(uint32_t *w,uint32_t *h,uint32_t *rate){*w=physical_w;*h=physical_h;*rate=60;return 1;}
template<class T> T *memory(uint32_t address,size_t count,bool write){assert(address==0x100&&count==1&&write);return &output;}
#include "modes.h"
int main(){
 uint32_t a[4]={0,22,0,0x100};Context c{1,&test_d3d,6,a};
 unsigned count=adapter_modes(c);assert(count==19);
 bool found_default=false,found_physical=false;
 c.slot=7;
 for(unsigned i=0;i<count;++i){a[2]=i;assert(adapter_modes(c)==0&&output.RefreshRate==60&&output.Format==22);
  found_default|=output.Width==1024&&output.Height==768;found_physical|=output.Width==2400&&output.Height==1080;}
 assert(found_default&&found_physical);
 a[2]=count;assert(adapter_modes(c)==D3DERR_INVALIDCALL);
 a[2]=0;a[3]=0;assert(adapter_modes(c)==D3DERR_INVALIDCALL);a[3]=0x100;
 physical_w=1920;physical_h=1080;c.slot=6;assert(adapter_modes(c)==18);
 a[1]=23;assert(adapter_modes(c)==18);c.slot=7;assert(adapter_modes(c)==0&&output.Format==23);
 a[0]=1;assert(adapter_modes(c)==D3DERR_INVALIDCALL);c.slot=6;assert(!adapter_modes(c));
 a[0]=0;a[1]=21;assert(!adapter_modes(c));a[1]=22;test_d3d.supported=false;assert(!adapter_modes(c));
 puts("PASS DXVK modes: PC 1024x768 and native display, no duplicates, 16/32-bit formats, adapter/format/caps/index/NULL validation");
}
'''
        compile_probe("dxvk-modes", fixture, {"modes.h": function(source, "uint32_t adapter_modes(")},
                      extra_flags=("/TP", "/EHsc"))

    def test_game_hwnd_and_android_surface(self):
        source = (ROOT / "android/dxvk/bridge.cpp").read_text(encoding="utf-8")
        helpers = "\n".join(function(source, name) for name in
                            ("RECT aspect_destination(", "uint32_t present(Context &c)"))
        compile_probe("dxvk-present", HARNESS, {"present.h": helpers},
                      extra_flags=("/TP", "/EHsc", "/wd4189"))


if __name__ == "__main__":
    unittest.main()
