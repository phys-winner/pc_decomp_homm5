"""The DXVK bridge's D3D9 worker (android/dxvk/bridge.cpp, 'the D3D9 worker' section): the production
queue, records, executors, waits and buffer-lock renaming run on the PC against a recording fake
device on a real second thread. The device must see exactly the calls, in order, with the data the
game passed at the time of each call. A buffer lock looks only at the queued draws that read that
buffer (the game's bindings: SetStreamSource/SetIndices outside state block recording, UP draws
unbinding): without DISCARD or NOOVERWRITE it waits until the worker is past them, with DISCARD it
hands out a fresh copy and frees the old one only after the worker; a buffer no queued draw reads is
locked at once. VOID_DXVK_READS=0 (track_reads false) counts all queued work."""
import unittest

from test_static_tls import ROOT, compile_probe

HARNESS = r'''
#include <cassert>
#include <crtdbg.h>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <map>
#include <mutex>
#include <new>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
using HRESULT = int32_t; using DWORD = uint32_t; using UINT = uint32_t; using INT = int32_t; using BOOL = int32_t;
using D3DCOLOR = uint32_t;
constexpr HRESULT D3D_OK = 0, D3DERR_INVALIDCALL = HRESULT(0x8876086cu);
#define FAILED(hr) ((hr) < 0)
#define SUCCEEDED(hr) ((hr) >= 0)
enum D3DPRIMITIVETYPE { D3DPT_TRIANGLELIST = 4 };
enum D3DFORMAT { D3DFMT_INDEX16 = 101, D3DFMT_INDEX32 = 102 };
enum D3DTRANSFORMSTATETYPE { D3DTS_WORLD = 256 };
enum D3DRENDERSTATETYPE { D3DRS_ZENABLE = 7 };
enum D3DTEXTURESTAGESTATETYPE { D3DTSS_COLOROP = 1 };
enum D3DSAMPLERSTATETYPE { D3DSAMP_ADDRESSU = 1 };
enum D3DTEXTUREFILTERTYPE { D3DTEXF_LINEAR = 2 };
enum { D3DLOCK_READONLY = 0x10, D3DLOCK_DISCARD = 0x2000, D3DLOCK_NOOVERWRITE = 0x1000 };
struct RECT { int32_t left, top, right, bottom; };
struct D3DRECT { int32_t x1, y1, x2, y2; };
struct D3DMATRIX { float m[16]; };
struct D3DVIEWPORT9 { uint32_t x, y, w, h; float minz, maxz; };
struct D3DMATERIAL9 { float f[17]; };
struct D3DLIGHT9 { float f[26]; };
struct D3DVERTEXBUFFER_DESC { uint32_t Format, Type, Usage, Pool, Size, FVF; };
struct D3DINDEXBUFFER_DESC { D3DFORMAT Format; uint32_t Type, Usage, Pool, Size; };
static std::mutex log_lock;
static std::vector<std::string> calls;
static void note(const std::string &text) { std::lock_guard<std::mutex> guard(log_lock); calls.push_back(text); }
static std::string fmt(const char *f, double a = 0, double b = 0, double c = 0) { char t[128]; snprintf(t, sizeof t, f, a, b, c); return t; }
struct IDirect3DSurface9 {}; struct IDirect3DBaseTexture9 {}; struct IDirect3DVertexDeclaration9 {};
struct IDirect3DVertexShader9 {}; struct IDirect3DPixelShader9 {};
struct IDirect3DVertexBuffer9 { uint32_t size; HRESULT GetDesc(D3DVERTEXBUFFER_DESC *d) { *d = {}; d->Size = size; return D3D_OK; } uint32_t Release() { return 0; } };
struct IDirect3DIndexBuffer9 { uint32_t size; HRESULT GetDesc(D3DINDEXBUFFER_DESC *d) { *d = {}; d->Size = size; d->Format = D3DFMT_INDEX16; return D3D_OK; } uint32_t Release() { return 0; } };
struct IDirect3DDevice9;
enum D3DQUERYTYPE { D3DQUERYTYPE_EVENT = 8, D3DQUERYTYPE_OCCLUSION = 9 };
constexpr DWORD D3DISSUE_END = 1, D3DGETDATA_FLUSH = 1;
constexpr HRESULT S_FALSE = 1;
constexpr BOOL TRUE = 1, FALSE = 0;
struct IDirect3DQuery9 {
  D3DQUERYTYPE type = D3DQUERYTYPE_EVENT;
  std::atomic<int> gpu_done{0}, polls{0};   /* the test plays the GPU */
  HRESULT Issue(DWORD f) { note(fmt("Issue(%g)", f)); return D3D_OK; }
  D3DQUERYTYPE GetType() { return type; }
  HRESULT GetData(void *data, DWORD size, DWORD flags) {
    polls.fetch_add(1);
    if (!(flags & D3DGETDATA_FLUSH) || !gpu_done.load()) return S_FALSE;
    if (data && size >= sizeof(BOOL)) *static_cast<BOOL*>(data) = TRUE;
    return D3D_OK;
  }
};
struct IDirect3DStateBlock9 {
  IDirect3DDevice9 *device;
  HRESULT Apply() { note("Apply"); return D3D_OK; } HRESULT Capture() { note("Capture"); return D3D_OK; }
  HRESULT GetDevice(IDirect3DDevice9 **out) { *out = device; return D3D_OK; }
};
struct IDirect3DDevice9 {
  std::atomic<int> slow{0}, gate{1}, coop_calls{0};
  HRESULT coop_state = D3D_OK;
  HRESULT TestCooperativeLevel() { coop_calls.fetch_add(1); return coop_state; }
  uint32_t Release() { return 0; }
  HRESULT StretchRect(IDirect3DSurface9*, const RECT *s, IDirect3DSurface9*, const RECT *d, D3DTEXTUREFILTERTYPE f) { note(fmt("StretchRect(%g,%g,%g)", s ? s->right : -1, d ? d->bottom : -1, f)); return D3D_OK; }
  HRESULT ColorFill(IDirect3DSurface9*, const RECT *r, D3DCOLOR c) { note(fmt("ColorFill(%g,%g)", r ? r->right : -1, c)); return D3D_OK; }
  HRESULT SetRenderTarget(DWORD i, IDirect3DSurface9 *s) { note(fmt("SetRenderTarget(%g,%g)", i, s ? 1 : 0)); return D3D_OK; }
  HRESULT SetDepthStencilSurface(IDirect3DSurface9 *s) { note(fmt("SetDepthStencilSurface(%g)", s ? 1 : 0)); return D3D_OK; }
  HRESULT BeginScene() { note("BeginScene"); return D3D_OK; }
  HRESULT EndScene() { note("EndScene"); return D3D_OK; }
  HRESULT Clear(DWORD n, const D3DRECT *r, DWORD f, D3DCOLOR c, float z, DWORD s) { note(fmt("Clear(%g,%g,%g)", n, r ? r[n - 1].y2 : -1, z)); (void)f; (void)c; (void)s; return D3D_OK; }
  HRESULT SetTransform(D3DTRANSFORMSTATETYPE t, const D3DMATRIX *m) { note(fmt("SetTransform(%g,%g)", t, m->m[15])); return D3D_OK; }
  HRESULT SetViewport(const D3DVIEWPORT9 *v) { note(fmt("SetViewport(%g,%g)", v->w, v->maxz)); return D3D_OK; }
  HRESULT SetMaterial(const D3DMATERIAL9 *m) { note(fmt("SetMaterial(%g)", m->f[16])); return D3D_OK; }
  HRESULT SetLight(DWORD i, const D3DLIGHT9 *l) { note(fmt("SetLight(%g,%g)", i, l->f[25])); return D3D_OK; }
  HRESULT LightEnable(DWORD i, BOOL e) { note(fmt("LightEnable(%g,%g)", i, e)); return D3D_OK; }
  HRESULT SetClipPlane(DWORD i, const float *p) { note(fmt("SetClipPlane(%g,%g)", i, p[3])); return D3D_OK; }
  HRESULT SetRenderState(D3DRENDERSTATETYPE s, DWORD v) {
    if (slow.load()) std::this_thread::sleep_for(std::chrono::milliseconds(2));
    if (s == 999) while (!gate.load()) std::this_thread::yield();   /* the worker stops here until the test opens it */
    note(fmt("SetRenderState(%g,%g)", s, v)); return D3D_OK;
  }
  HRESULT SetTexture(DWORD s, IDirect3DBaseTexture9 *t) { note(fmt("SetTexture(%g,%g)", s, t ? 1 : 0)); return D3D_OK; }
  HRESULT SetTextureStageState(DWORD s, D3DTEXTURESTAGESTATETYPE t, DWORD v) { note(fmt("SetTextureStageState(%g,%g,%g)", s, t, v)); return D3D_OK; }
  HRESULT SetSamplerState(DWORD s, D3DSAMPLERSTATETYPE t, DWORD v) { note(fmt("SetSamplerState(%g,%g,%g)", s, t, v)); return D3D_OK; }
  HRESULT SetScissorRect(const RECT *r) { note(fmt("SetScissorRect(%g)", r->bottom)); return D3D_OK; }
  HRESULT DrawPrimitive(D3DPRIMITIVETYPE, UINT s, UINT n) { note(fmt("DrawPrimitive(%g,%g)", s, n)); return D3D_OK; }
  HRESULT DrawIndexedPrimitive(D3DPRIMITIVETYPE, INT b, UINT, UINT, UINT s, UINT n) { note(fmt("DrawIndexedPrimitive(%g,%g,%g)", b, s, n)); return D3D_OK; }
  HRESULT DrawPrimitiveUP(D3DPRIMITIVETYPE, UINT n, const void *v, UINT stride) {
    note(fmt("DrawPrimitiveUP(%g,%g,%g)", n, stride, static_cast<const float*>(v)[n * 3 * (stride / 4) - 1])); return D3D_OK;
  }
  HRESULT DrawIndexedPrimitiveUP(D3DPRIMITIVETYPE, UINT minv, UINT nv, UINT n, const void *i, D3DFORMAT, const void *v, UINT stride) {
    note(fmt("DrawIndexedPrimitiveUP(%g,%g,%g)", static_cast<const uint16_t*>(i)[n * 3 - 1], static_cast<const float*>(v)[(minv + nv) * (stride / 4) - 1], n)); return D3D_OK;
  }
  HRESULT SetVertexDeclaration(IDirect3DVertexDeclaration9 *d) { note(fmt("SetVertexDeclaration(%g)", d ? 1 : 0)); return D3D_OK; }
  HRESULT SetFVF(DWORD f) { note(fmt("SetFVF(%g)", f)); return D3D_OK; }
  HRESULT SetVertexShader(IDirect3DVertexShader9 *s) { note(fmt("SetVertexShader(%g)", s ? 1 : 0)); return D3D_OK; }
  HRESULT SetPixelShader(IDirect3DPixelShader9 *s) { note(fmt("SetPixelShader(%g)", s ? 1 : 0)); return D3D_OK; }
  HRESULT SetVertexShaderConstantF(UINT r, const float *d, UINT n) { note(fmt("VSConstF(%g,%g,%g)", r, d[0], d[n * 4 - 1])); return D3D_OK; }
  HRESULT SetVertexShaderConstantI(UINT r, const int *d, UINT n) { note(fmt("VSConstI(%g,%g,%g)", r, d[0], n)); return D3D_OK; }
  HRESULT SetVertexShaderConstantB(UINT r, const BOOL *d, UINT n) { note(fmt("VSConstB(%g,%g,%g)", r, d[n - 1], n)); return D3D_OK; }
  HRESULT SetPixelShaderConstantF(UINT r, const float *d, UINT n) { note(fmt("PSConstF(%g,%g,%g)", r, d[0], d[n * 4 - 1])); return D3D_OK; }
  HRESULT SetPixelShaderConstantI(UINT r, const int *d, UINT n) { note(fmt("PSConstI(%g,%g,%g)", r, d[0], n)); return D3D_OK; }
  HRESULT SetPixelShaderConstantB(UINT r, const BOOL *d, UINT n) { note(fmt("PSConstB(%g,%g,%g)", r, d[n - 1], n)); return D3D_OK; }
  HRESULT SetStreamSource(UINT i, IDirect3DVertexBuffer9 *b, UINT o, UINT s) { note(fmt("SetStreamSource(%g,%g,%g)", i, o, s)); (void)b; return D3D_OK; }
  HRESULT SetStreamSourceFreq(UINT i, UINT f) { note(fmt("SetStreamSourceFreq(%g,%g)", i, f)); return D3D_OK; }
  HRESULT SetIndices(IDirect3DIndexBuffer9 *b) { note(fmt("SetIndices(%g)", b ? 1 : 0)); return D3D_OK; }
  HRESULT GetStreamSource(UINT, IDirect3DVertexBuffer9 **b, UINT *o, UINT *s) { *b = nullptr; *o = *s = 0; return D3D_OK; }
  HRESULT GetStreamSourceFreq(UINT, UINT *f) { *f = 1; return D3D_OK; }
  HRESULT GetIndices(IDirect3DIndexBuffer9 **b) { *b = nullptr; return D3D_OK; }
} device;
enum class Kind : unsigned { IDirect3DDevice9 = 2, IDirect3DTexture9 = 5, IDirect3DCubeTexture9 = 6, IDirect3DSurface9 = 9,
                             IDirect3DVertexBuffer9 = 10, IDirect3DIndexBuffer9 = 11, IDirect3DSwapChain9 = 17 };
struct Context { Kind kind; void *self; unsigned slot; const uint32_t *a; };
/* Guest memory: one host block; guest addresses are offsets into it. */
static std::vector<uint8_t> guest_bytes(64u << 20);
static uint32_t guest_top = 0x1000;
static std::vector<uint32_t> freed;
struct Host {
  uint32_t guest_alloc(uint32_t n) { uint32_t at = guest_top; guest_top += (n + 4095u) & ~4095u; assert(guest_top < guest_bytes.size()); return at; }
  void guest_free(uint32_t va) { freed.push_back(va); }
  std::map<uint32_t, void*> handles;   /* guest handles of test objects */
  void *unwrap_guest(uint32_t va) { auto it = handles.find(va); return it != handles.end() ? it->second : va ? reinterpret_cast<void*>(uintptr_t(va)) : nullptr; }
  void *guest_memory(uint32_t va, uint32_t, int) { return guest_bytes.data() + va; }
} host_object, *host = &host_object;
template<class T> T *memory(uint32_t va, size_t = 1, bool = false) { return va ? reinterpret_cast<T*>(guest_bytes.data() + va) : nullptr; }
static void say(const char *) {}
template<class... A> static void sayf(const char*, A...) {}
static uint64_t clock_ns(int) { return uint64_t(std::chrono::steady_clock::now().time_since_epoch().count()); }
#define CLOCK_MONOTONIC 1
static void worker_enter() {}
static std::atomic<uint64_t> buffer_locks;
template<class T> inline void bump(std::atomic<T> &counter, T by = 1) {   /* as bridge.cpp */
  counter.store(counter.load(std::memory_order_relaxed) + by, std::memory_order_relaxed);
}
constexpr uint32_t kShadowPage = 4096;
struct Shadow {
  uint32_t guest = 0, size = 0, index_bytes = 0; uint8_t *host = nullptr; std::vector<uint8_t> dirty;
  uint32_t dirty_count = 0; bool discard = false, overwrite = false, vertex = true;
};
static std::unordered_map<void*, Shadow> shadows;
struct StreamBinding { void *buffer; uint32_t offset, stride; Shadow *shadow; };
static StreamBinding streams[16];
static uint32_t stream_freq[16];
static void *bound_indices;
static Shadow *bound_index_shadow;
static Shadow *shadow_of(void *b) { auto it = shadows.find(b); return it == shadows.end() ? nullptr : &it->second; }
static std::vector<std::string> dirt;
static void shadow_dirty(Shadow &s, uint32_t lo, uint32_t hi) { if (lo < hi) { std::lock_guard<std::mutex> g(log_lock); dirt.push_back(fmt("dirty(%g,%g)", lo, hi)); } (void)s; }
static void rebind_shadow(void *, Shadow *) {}
static void bind_stream(uint32_t i, void *b, uint32_t o, uint32_t s) { streams[i] = {b, o, s, b ? shadow_of(b) : nullptr}; }
static void bind_indices(void *b) { bound_indices = b; bound_index_shadow = b ? shadow_of(b) : nullptr; }
static size_t vertex_count(uint32_t type, uint32_t n) { assert(type == 4); return size_t(n) * 3; }
static bool ring_draw(IDirect3DDevice9 *, unsigned, const uint32_t *, uint32_t *) { return false; }
static void forget_up_bindings(bool) {}
static void upload_for_draw(unsigned slot, const uint32_t *) { note(fmt("upload(%g)", slot)); }
static uint32_t present(Context &c, const RECT *const *rects) { note(fmt("Present(%g,%g)", unsigned(c.kind), rects[1] ? rects[1]->right : -1)); return 0; }
static uint32_t op_release_now(void *p) { note(fmt("Release(%g)", double(uintptr_t(p)))); return 0; }
static bool recording_state;
#include "worker.h"

#define CHECK(x) do { if (!(x)) { printf("FAIL line %d: %s\n", __LINE__, #x); fflush(stdout); std::_Exit(1); } } while (0)

static uint32_t put(const void *data, size_t n) { uint32_t va = host->guest_alloc(uint32_t(n)); memcpy(guest_bytes.data() + va, data, n); return va; }
static void call(unsigned slot, std::vector<uint32_t> a) { bool queued = defer_device(&device, slot, a.data()); CHECK(queued); }
static std::vector<std::string> take() { drain(); std::lock_guard<std::mutex> g(log_lock); auto v = calls; calls.clear(); return v; }

int main() {
  worker_start();
  CHECK(worker.enabled);
  /* 1. Order and the data at call time (the guest overwrites its constants right after). */
  float c[8] = {1, 2, 3, 4, 5, 6, 7, 8};
  uint32_t cva = put(c, sizeof c);
  call(57, {7, 1});
  call(94, {3, cva, 2});
  reinterpret_cast<float*>(guest_bytes.data() + cva)[7] = 99;   /* after the call: must not reach the device */
  call(109, {0, cva, 1});
  D3DRECT rects[2] = {{0, 0, 10, 10}, {0, 0, 20, 33}};
  call(43, {2, put(rects, sizeof rects), 3, 0xFF, 0x3F800000u, 0});
  D3DMATRIX m{}; m.m[15] = 42;
  call(44, {256, put(&m, sizeof m)});
  D3DVIEWPORT9 v{0, 0, 2400, 1080, 0, 1};
  call(47, {put(&v, sizeof v)});
  call(65, {2, 0x500});
  call(100, {0, 0x600, 32, 24});
  call(104, {0x700});
  call(82, {4, 0, 0, 100, 30, 10});
  float up[9 * 6]; for (int i = 0; i < 9 * 6; ++i) up[i] = float(i);
  call(83, {4, 3, put(up, sizeof up), 24});
  uint16_t idx[6] = {0, 1, 2, 2, 1, 3};
  call(84, {4, 0, 4, 2, put(idx, sizeof idx), 101, put(up, sizeof up), 24});
  auto seen = take();
  std::vector<std::string> want = {"SetRenderState(7,1)", "VSConstF(3,1,8)", "PSConstF(0,1,4)", "Clear(2,33,1)", "SetTransform(256,42)",
    "SetViewport(2400,1)", "SetTexture(2,1)", "SetStreamSource(0,32,24)", "SetIndices(1)", "upload(82)",
    "DrawIndexedPrimitive(0,30,10)", "DrawPrimitiveUP(3,24,53)", "DrawIndexedPrimitiveUP(3,23,2)"};
  if (seen != want) { for (auto &s : seen) printf("seen %s\n", s.c_str()); fflush(stdout); std::_Exit(1); }
  /* 2. Buffer locks: the first creates the copy; DISCARD while a queued draw reads the copy renames it,
        NOOVERWRITE neither renames nor waits, a plain lock waits until the worker is past the draw. */
  IDirect3DVertexBuffer9 vb{65536};
  host->handles[0x800] = &vb;
  uint32_t out = put("\0\0\0\0", 4);
  uint32_t args[4] = {0, 0, out, D3DLOCK_DISCARD};
  Context lock{Kind::IDirect3DVertexBuffer9, &vb, 11, args};
  CHECK(game_buffer_lock(lock, false) == 0);
  uint32_t first = *memory<uint32_t>(out);
  drain();
  call(100, {0, 0x800, 0, 24});
  device.gate = 0;
  call(57, {999, 0});                                             /* the worker stops here ... */
  call(82, {4, 0, 0, 100, 0, 10});                                /* ... before a draw that reads vb */
  std::thread gate_opener([] { std::this_thread::sleep_for(std::chrono::milliseconds(60)); device.gate = 1; });
  CHECK(game_buffer_lock(lock, false) == 0);
  uint32_t second = *memory<uint32_t>(out);
  CHECK(second != first);                                         /* renamed while the draw was queued */
  CHECK(std::find(freed.begin(), freed.end(), first) == freed.end());
  args[3] = 0;   /* the queued draw reads the old copy: a plain lock of the new one goes ahead */
  auto t_plain = std::chrono::steady_clock::now();
  CHECK(game_buffer_lock(lock, false) == 0 && *memory<uint32_t>(out) == second);
  CHECK(std::chrono::steady_clock::now() - t_plain < std::chrono::milliseconds(30));
  args[3] = D3DLOCK_NOOVERWRITE;
  CHECK(game_buffer_lock(lock, false) == 0 && *memory<uint32_t>(out) == second);   /* no rename, no wait */
  CHECK(worker.done.load() + 2 <= worker.queued.load());          /* all while the worker was stopped */
  gate_opener.join();
  device.slow = 1;
  for (int i = 0; i < 10; ++i) call(57, {8, uint32_t(i)});
  call(82, {4, 0, 0, 100, 0, 10});                                /* a draw that reads the new copy */
  uint64_t reader = worker.queued.load();
  device.gate = 0;
  call(57, {999, 0});                                             /* the worker stops after that draw */
  args[3] = 0;
  CHECK(game_buffer_lock(lock, false) == 0 && *memory<uint32_t>(out) == second);
  CHECK(worker.done.load() >= reader);                            /* waited for the draw ... */
  CHECK(worker.done.load() < worker.queued.load());               /* ... and not for the work behind it */
  device.gate = 1;
  device.slow = 0;
  drain();
  collect();
  CHECK(std::find(freed.begin(), freed.end(), first) != freed.end() ||
         !game_buffers[&vb].spare.empty());                        /* the old copy: freed or kept as a spare */
  /* 2b. Only the queued draws that read a buffer count: an unbound buffer, a binding recorded into a
         state block (not applied), a stream an UP draw unbound; all queued work with track_reads off. */
  IDirect3DVertexBuffer9 va{65536}, vbB{65536};
  host->handles[0xA00] = &va; host->handles[0xB00] = &vbB;
  uint32_t out5 = put("\0\0\0\0", 4);
  auto plain_ms = [&](IDirect3DVertexBuffer9 *buffer) {
    uint32_t a5[4] = {0, 0, out5, 0};
    Context c5{Kind::IDirect3DVertexBuffer9, buffer, 11, a5};
    auto t0 = std::chrono::steady_clock::now();
    CHECK(game_buffer_lock(c5, false) == 0);
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - t0).count();
  };
  auto blocked_draw = [&]() {   /* the worker stops; a draw with the current bindings waits behind it */
    device.gate = 0;
    call(57, {999, 0});
    call(82, {4, 0, 0, 100, 0, 10});
  };
  auto open_later = []() { return std::thread([] { std::this_thread::sleep_for(std::chrono::milliseconds(60)); device.gate = 1; }); };
  plain_ms(&va); plain_ms(&vbB);                                  /* both copies exist */
  call(100, {0, 0xA00, 0, 24});
  blocked_draw();
  std::thread opener = open_later();
  CHECK(plain_ms(&vbB) < 30);                                     /* no queued draw reads vbB */
  CHECK(worker.done.load() + 2 <= worker.queued.load());          /* the worker was still stopped */
  CHECK(plain_ms(&va) >= 30);                                     /* the queued draw reads va */
  opener.join();
  take();
  call(100, {0, 0xA00, 0, 24});
  recording_state = true;
  call(100, {0, 0xB00, 0, 24});                                   /* recorded into a state block only */
  recording_state = false;
  blocked_draw();
  opener = open_later();
  CHECK(plain_ms(&vbB) < 30);
  CHECK(plain_ms(&va) >= 30);
  opener.join();
  take();
  call(100, {0, 0xA00, 0, 24});
  float up2[9 * 6] = {};
  call(83, {4, 3, put(up2, sizeof up2), 24});                     /* D3D9: stream 0 is unbound after it */
  blocked_draw();
  opener = open_later();
  CHECK(plain_ms(&va) < 30);
  opener.join();
  take();
  track_reads = false;
  blocked_draw();
  opener = open_later();
  CHECK(plain_ms(&vbB) >= 30);                                    /* the first version: any queued work */
  opener.join();
  track_reads = true;
  take();
  call(100, {0, 0xA00, 0, 24});
  game_bindings_refresh(&device);                                 /* after an Apply: the device's (none here) */
  for (void *bound : game_bound.streams) CHECK(bound == nullptr);
  CHECK(game_bound.indices == nullptr);
  /* 3. Present: one frame ahead at most; swap-chain presents carry their rects. */
  RECT dst{0, 0, 2400, 1080};
  uint32_t pa[5] = {0, put(&dst, sizeof dst), 0, 0, 0};
  CHECK(defer_present(Kind::IDirect3DDevice9, &device, 17, pa) == 0);
  device.slow = 1;
  for (int i = 0; i < 10; ++i) call(57, {9, uint32_t(i)});
  CHECK(defer_present(Kind::IDirect3DDevice9, &device, 17, pa) == 0);
  CHECK(worker.done.load() >= worker.last_present - 11);         /* the first present had run */
  device.slow = 0;
  take();
  /* 4. Thousands of records with payloads across many ring wraps keep their order and data. */
  std::vector<float> big(4 * 256);
  uint32_t bva = host->guest_alloc(uint32_t(big.size() * 4));
  for (int round = 0; round < 60000; ++round) {
    float *g = memory<float>(bva);
    g[0] = float(round); g[4 * (round % 256 + 1) - 1] = float(-round);
    call(94, {uint32_t(round % 7), bva, uint32_t(round % 256 + 1)});
  }
  seen = take();
  CHECK(seen.size() == 60000);
  for (int round = 0; round < 60000; ++round)
    if (seen[size_t(round)] != fmt("VSConstF(%g,%g,%g)", round % 7, round, -round)) { printf("record %d: %s\n", round, seen[size_t(round)].c_str()); fflush(stdout); std::_Exit(1); }
  /* 5. Event queries: GetData answers from what the worker published, without waiting for queued work. */
  IDirect3DQuery9 event, occlusion;
  occlusion.type = D3DQUERYTYPE_OCCLUSION;
  uint32_t data_va = put("\0\0\0\0", 4);
  uint32_t get[3] = {data_va, 4, 0};
  event_issue(&event, D3DISSUE_END);                              /* the type is asked once (drained) */
  CHECK(event_proxies.count(&event) && event_proxies[&event]);
  device.gate = 0;
  call(57, {999, 0});                                             /* the worker stops before the next Issue */
  event_issue(&event, D3DISSUE_END);
  auto t_event = std::chrono::steady_clock::now();
  CHECK(event_get_data(&event, get) == S_FALSE);                  /* issued behind queued work: pending at once */
  CHECK(std::chrono::steady_clock::now() - t_event < std::chrono::milliseconds(30));
  CHECK(worker.done.load() < worker.queued.load());
  device.gate = 1;
  drain();
  CHECK(event_get_data(&event, get) == S_FALSE);                  /* executed, the GPU not done yet */
  event.gpu_done = 1;
  uint32_t answer = S_FALSE;
  for (int i = 0; i < 2000 && answer == S_FALSE; ++i) {           /* the idle worker polls every 100 us */
    answer = event_get_data(&event, get);
    std::this_thread::sleep_for(std::chrono::microseconds(100));
  }
  CHECK(answer == D3D_OK && *memory<BOOL>(data_va) == TRUE);
  event.gpu_done = 0;
  event_issue(&event, D3DISSUE_END);                              /* a newer Issue is pending again */
  drain();
  CHECK(event_get_data(&event, get) == S_FALSE);
  event.gpu_done = 1;
  answer = S_FALSE;
  for (int i = 0; i < 2000 && answer == S_FALSE; ++i) { answer = event_get_data(&event, get); std::this_thread::sleep_for(std::chrono::microseconds(100)); }
  CHECK(answer == D3D_OK);
  event_issue(&occlusion, D3DISSUE_END);                          /* other query types: DXVK answers (drained) */
  CHECK(event_proxies.count(&occlusion) && !event_proxies[&occlusion]);
  CHECK(event_get_data(&occlusion, get) == UINT32_MAX);
  proxy_events = false;
  CHECK(event_get_data(&event, get) == UINT32_MAX);               /* VOID_DXVK_EVENTS=0 */
  proxy_events = true;
  take();
  /* 6. Calls answered without a drain: level surfaces and the available memory, nothing else. */
  CHECK(drain_free(Kind::IDirect3DTexture9, 18) && drain_free(Kind::IDirect3DCubeTexture9, 18) &&
        drain_free(Kind::IDirect3DDevice9, 4));
  CHECK(!drain_free(Kind::IDirect3DTexture9, 19) && !drain_free(Kind::IDirect3DSurface9, 18) &&
        !drain_free(Kind::IDirect3DDevice9, 3) && !drain_free(Kind::IDirect3DDevice9, 18));
  /* 7. TestCooperativeLevel: asked once (drained), then answered while work is queued; a Reset clears it. */
  device.coop_state = 0x88760869;                                /* D3DERR_DEVICENOTRESET */
  CHECK(coop_level(&device) == 0x88760869u && device.coop_calls.load() == 1);
  device.gate = 0;
  call(57, {999, 0});
  auto t_coop = std::chrono::steady_clock::now();
  CHECK(coop_level(&device) == 0x88760869u && device.coop_calls.load() == 1);
  CHECK(std::chrono::steady_clock::now() - t_coop < std::chrono::milliseconds(30));
  CHECK(worker.done.load() < worker.queued.load());               /* the worker was still stopped */
  device.gate = 1;
  coop_states.clear();                                            /* as op_call does for Reset */
  device.coop_state = D3D_OK;
  CHECK(coop_level(&device) == 0 && device.coop_calls.load() == 2);
  take();
  CHECK(_CrtCheckMemory());   /* debug heap guards: no record ran past the end of the ring */
  puts("PASS DXVK worker: order and call-time data of 13 deferred methods, DISCARD renaming and plain-lock waits "
       "for the queued draws that read the buffer only (bindings, state block recording, UP unbinding, Apply read-back), "
       "event queries answered from the worker without waiting for queued work, TestCooperativeLevel from its last answer, "
       "one frame of presents ahead, 60000 records across ring wraps");
  fflush(stdout);
  std::_Exit(0);   /* the detached worker still waits on its condition variable: no static destructors */
}
'''


class DxvkWorkerTest(unittest.TestCase):
    def test_worker_runs_the_game_calls_in_order_with_their_data(self):
        source = (ROOT / "android/dxvk/bridge.cpp").read_text(encoding="utf-8")
        start = source.index("/* ------------------------------------------------------------ the D3D9 worker")
        end = source.index("uint32_t texture_lock(Context &c, bool unlock) {")
        worker = source[start:end]
        worker = worker.replace('__asm__ volatile("yield" ::: "memory");', "std::this_thread::yield();")
        worker = worker.replace('pthread_setname_np(pthread_self(), "dxvk-d3d9");', "")
        compile_probe("dxvk-worker", HARNESS, {"worker.h": worker}, extra_flags=("/TP", "/EHsc", "/wd4189", "/wd4100", "/wd4244", "/wd4267", "/wd4245", "/O2", "/MTd"))


if __name__ == "__main__":
    unittest.main()
