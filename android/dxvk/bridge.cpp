/* Typed x86 D3D9 -> native ARM64 DXVK boundary: libh5dxvk.so, adapted from the sibling ut3
 * port's android/dxvk/bridge.cpp. The ToE engine opens it with dlopen only in a DXVK renderer
 * mode and hands it the host services of bridge_abi.h (the engine's own symbols are hidden).
 * Native pointers never enter guest memory: guest objects are the engine's COM wrappers, locks
 * are bounce buffers in guest memory, and a replaced Android surface is taken up as the present's
 * destination window instead of a lost device. */
#include <d3d9.h>
#include <android/native_window.h>
#include <dlfcn.h>
#include <time.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <mutex>
#include <stdexcept>
#include <tuple>
#include <type_traits>
#include <unordered_map>
#include <vector>
#include "bridge_abi.h"
#include "turnip.h"
#include "bridge_metadata.h"

#define EXPORT extern "C" __attribute__((visibility("default")))

namespace {
const homm5_dxvk_host *host;
/* The reused libdxvk_d3d9.so (built by the ut3 port's tools/build_dxvk.py, see dependencies.json
 * "dxvk") exports its embedding hooks under these names; the WSI and loader they feed are
 * game-agnostic. */
constexpr const char *kSetCallbacks = "ut3_dxvk_set_callbacks_v2", *kSetLoader = "ut3_dxvk_set_vulkan_loader";

void say(const char *text) { if (host) host->log(text); }
template<class... A> void sayf(const char *format, A... args) { char text[512]; snprintf(text, sizeof text, format, args...); say(text); }

template<class T> T *memory(uint32_t va, size_t count = 1, bool write = false) {
  if (!va) return nullptr;
  if (count > UINT32_MAX / sizeof(T)) throw std::runtime_error("guest span overflow");
  return static_cast<T*>(host->guest_memory(va, uint32_t(count * sizeof(T)), write));
}
template<class T> T &ref(uint32_t va, bool write = false) {
  if (!va) throw std::runtime_error("NULL required guest pointer");
  return *memory<T>(va, 1, write);
}
uint32_t narrow_size(uint64_t n) { if (n > UINT32_MAX) throw std::runtime_error("guest size overflow"); return uint32_t(n); }
template<class T> uint32_t wrap(T *p) {
  if (!p) return 0;
  /* The D3D9 interfaces derive singly: a base pointer is the derived object's pointer. */
  if constexpr (std::is_same_v<T, IDirect3DBaseTexture9> || std::is_same_v<T, IDirect3DResource9>) {
    switch (p->GetType()) {
      case D3DRTYPE_TEXTURE: return host->wrap_native(unsigned(Kind::IDirect3DTexture9), p);
      case D3DRTYPE_CUBETEXTURE: return host->wrap_native(unsigned(Kind::IDirect3DCubeTexture9), p);
      case D3DRTYPE_VOLUMETEXTURE: return host->wrap_native(unsigned(Kind::IDirect3DVolumeTexture9), p);
      case D3DRTYPE_SURFACE: return host->wrap_native(unsigned(Kind::IDirect3DSurface9), p);
      case D3DRTYPE_VERTEXBUFFER: return host->wrap_native(unsigned(Kind::IDirect3DVertexBuffer9), p);
      case D3DRTYPE_INDEXBUFFER: return host->wrap_native(unsigned(Kind::IDirect3DIndexBuffer9), p);
      default: throw std::runtime_error("unknown D3D9 resource type");
    }
  }
  return host->wrap_native(unsigned(KindOf<T>::value), p);
}
template<class T> T *object(uint32_t va) { return static_cast<T*>(host->unwrap_guest(va)); }
struct Context { Kind kind; void *self; unsigned slot; const uint32_t *a; };

std::atomic<uint64_t> native_calls{}, draw_calls{}, present_cpu_ns{}, present_wall_ns{};
uint64_t clock_ns(clockid_t clock) {
  struct timespec t{};
  if (clock_gettime(clock, &t)) return 0;
  return uint64_t(t.tv_sec) * 1000000000ull + uint64_t(t.tv_nsec);
}
struct PresentTime {
  uint64_t cpu = clock_ns(CLOCK_THREAD_CPUTIME_ID), wall = clock_ns(CLOCK_MONOTONIC);
  ~PresentTime() {
    present_cpu_ns.fetch_add(clock_ns(CLOCK_THREAD_CPUTIME_ID) - cpu, std::memory_order_relaxed);
    present_wall_ns.fetch_add(clock_ns(CLOCK_MONOTONIC) - wall, std::memory_order_relaxed);
  }
};

/* The backbuffer touch input maps onto, and the one display mode the Android WSI exposes:
 * the physical display (as the GLES renderer's GetAdapterDisplayMode), else the backbuffer. */
std::atomic<uint32_t> backbuffer_width{1280}, backbuffer_height{720};
int display_mode(uint32_t *w, uint32_t *h, uint32_t *rate) {
  int dw = 0, dh = 0;
  if (host && host->display_size(&dw, &dh) && dw > 0 && dh > 0) { *w = uint32_t(std::max(dw, dh)); *h = uint32_t(std::min(dw, dh)); }
  else { *w = backbuffer_width.load(); *h = backbuffer_height.load(); }
  *rate = 60;
  return 1;
}
RECT aspect_destination(int width, int height, uint32_t logical_width, uint32_t logical_height) {
  double scale = std::min(double(width) / logical_width, double(height) / logical_height);
  int rw = int(std::lround(logical_width * scale)), rh = int(std::lround(logical_height * scale));
  return {LONG((width - rw) / 2), LONG((height - rh) / 2), LONG((width + rw) / 2), LONG((height + rh) / 2)};
}

/* Each device keeps a reference on the Android window it presents into. */
std::map<void*, ANativeWindow*> device_windows;
std::map<void*, std::array<uint32_t, 14>> parameters;
struct WindowLease {
  ANativeWindow *value;
  uint32_t serial = 0;
  WindowLease() : value(static_cast<ANativeWindow*>(host->window_acquire(&serial))) {}
  ~WindowLease() { if (value) ANativeWindow_release(value); }
  ANativeWindow *take() { auto *p = value; value = nullptr; return p; }
};
IDirect3DDevice9 *context_device(const Context &c, IDirect3DDevice9 **owned) {
  *owned = nullptr;
  if (c.kind == Kind::IDirect3DDevice9) return static_cast<IDirect3DDevice9*>(c.self);
  IDirect3DDevice9 *device = nullptr;
  if (FAILED(static_cast<IDirect3DSwapChain9*>(c.self)->GetDevice(&device)) || !device) return nullptr;
  return *owned = device;
}
void keep_window(void *device, WindowLease &lease) {
  auto &slot = device_windows[device];
  if (slot == lease.value) return;
  if (slot) { ANativeWindow_release(slot); say("presenting into a new Android surface"); }
  slot = lease.take();
}

size_t elements(const Context &c, const char *method, size_t index) {
  if (index == 1 && c.kind == Kind::IDirect3DDevice9 && (c.slot == 94 || c.slot == 109)) return size_t(c.a[2]) * 4;
  if ((strstr(method, "ShaderConstantF") || strstr(method, "ShaderConstantI")) && index == 1) return size_t(c.a[2]) * 4;
  if (strstr(method, "ShaderConstantB") && index == 1) return c.a[2];
  if ((!strcmp(method, "SetClipPlane") || !strcmp(method, "GetClipPlane")) && index == 1) return 4;
  if ((!strcmp(method, "SetPaletteEntries") || !strcmp(method, "GetPaletteEntries")) && index == 1) return 256;
  if (!strcmp(method, "Clear") && index == 1) return c.a[0];
  if (!strcmp(method, "GetDeclaration") && index == 0) return ref<UINT>(c.a[1]);
  return 1;
}
template<class T, class = void> struct IsInterface : std::false_type {};
template<class T> struct IsInterface<T, std::void_t<decltype(KindOf<std::remove_cv_t<T>>::value)>> : std::true_type {};
template<class T, class Enable = void> struct Argument {
  T value;
  Argument(const Context &c, size_t i, const char*) {
    if constexpr (std::is_same_v<T, float>) memcpy(&value, &c.a[i], 4);
    else value = T(c.a[i]);
  }
  operator T() { return value; }
  void finish(bool) {}
};
template<class T> struct Argument<T*, std::enable_if_t<!IsInterface<T>::value && !std::is_pointer_v<T>>> {
  T *value;
  Argument(const Context &c, size_t i, const char *name) : value(memory<T>(c.a[i], elements(c, name, i), !std::is_const_v<T>)) {}
  operator T*() { return value; }
  void finish(bool) {}
};
template<class T> struct Argument<T*, std::enable_if_t<IsInterface<T>::value>> {
  T *value;
  Argument(const Context &c, size_t i, const char*) : value(object<T>(c.a[i])) {}
  operator T*() { return value; }
  void finish(bool) {}
};
template<class T> struct Argument<T**, std::enable_if_t<IsInterface<T>::value>> {
  T *value = nullptr; uint32_t *out;
  Argument(const Context &c, size_t i, const char*) : out(memory<uint32_t>(c.a[i], 1, true)) {}
  operator T**() { return out ? &value : nullptr; }
  void finish(bool ok) { if (out) { *out = ok ? wrap(value) : 0; if (!ok && value) value->Release(); } }
};
template<class T> struct Argument<const T&, void> {
  const T &value;
  Argument(const Context &c, size_t i, const char*) : value(ref<T>(c.a[i])) {}
  operator const T&() { return value; }
  void finish(bool) {}
};
template<> struct Argument<void**, void> {
  void **value = nullptr;
  Argument(const Context &c, size_t i, const char*) { if (c.a[i]) throw std::runtime_error("shared Windows handle unsupported"); }
  operator void**() { return value; }
  void finish(bool) {}
};
template<class R> uint32_t returned(R value) {
  if constexpr (std::is_same_v<R, float>) { uint32_t out; memcpy(&out, &value, 4); return out; }
  else return uint32_t(value);
}
template<class O, class R, class... A, size_t... I>
uint32_t invoke_impl(Context &c, R (O::*method)(A...), const char *name, std::index_sequence<I...>) {
  std::tuple<Argument<A>...> args{Argument<A>(c, I, name)...};
  if constexpr (std::is_void_v<R>) {
    (static_cast<O*>(c.self)->*method)(static_cast<A>(std::get<I>(args))...);
    (std::get<I>(args).finish(true), ...);
    return 0;
  } else {
    R result = (static_cast<O*>(c.self)->*method)(static_cast<A>(std::get<I>(args))...);
    bool ok = true;
    if constexpr (std::is_same_v<R, HRESULT>) ok = SUCCEEDED(result);
    (std::get<I>(args).finish(ok), ...);
    return returned(result);
  }
}
template<class O, class R, class... A> uint32_t invoke(Context &c, R (O::*method)(A...), const char *name) { return invoke_impl(c, method, name, std::index_sequence_for<A...>{}); }
template<class O, class R, class... A> uint32_t create_resource(Context &c, R (O::*method)(A...), const char *name) { return invoke(c, method, name); }

D3DPRESENT_PARAMETERS native_parameters(uint32_t va, ANativeWindow *window) {
  auto *p = memory<uint32_t>(va, 14, true);
  if (!p) throw std::runtime_error("NULL presentation parameters");
  if (!window) throw std::runtime_error("Android surface unavailable");
  D3DPRESENT_PARAMETERS v{};
  v.BackBufferWidth = p[0]; v.BackBufferHeight = p[1]; v.BackBufferFormat = D3DFORMAT(p[2]); v.BackBufferCount = p[3];
  v.MultiSampleType = D3DMULTISAMPLE_TYPE(p[4]); v.MultiSampleQuality = p[5]; v.SwapEffect = D3DSWAPEFFECT(p[6]); v.hDeviceWindow = window;
  /* The Android WSI has no exclusive mode: always windowed into the fullscreen surface. */
  v.Windowed = TRUE; v.EnableAutoDepthStencil = p[9]; v.AutoDepthStencilFormat = D3DFORMAT(p[10]); v.Flags = p[11];
  v.FullScreen_RefreshRateInHz = 0; v.PresentationInterval = p[13];
  uint32_t w = v.BackBufferWidth ? v.BackBufferWidth : uint32_t(std::max(1, ANativeWindow_getWidth(window)));
  uint32_t h = v.BackBufferHeight ? v.BackBufferHeight : uint32_t(std::max(1, ANativeWindow_getHeight(window)));
  backbuffer_width = w; backbuffer_height = h;
  /* Touch coordinates use the size of the image being presented (as make_backbuffer, d3d9_device.c). */
  host->input_screen_size(int(w), int(h));
  return v;
}
void save_parameters(void *key, uint32_t va, const D3DPRESENT_PARAMETERS &p) {
  auto *original = memory<uint32_t>(va, 14, true);
  std::array<uint32_t, 14> copy;
  std::copy(original, original + 14, copy.begin());
  copy[0] = p.BackBufferWidth; copy[1] = p.BackBufferHeight; copy[2] = p.BackBufferFormat; copy[3] = p.BackBufferCount;
  std::copy(copy.begin(), copy.end(), original);
  parameters[key] = copy;
}
uint32_t create_device(Context &c) {
  auto *out = memory<uint32_t>(c.a[5], 1, true);
  if (!out) return D3DERR_INVALIDCALL;
  *out = 0;
  WindowLease next;
  if (!next.value) { host->window_ack(next.serial); return D3DERR_NOTAVAILABLE; }
  D3DPRESENT_PARAMETERS pp = native_parameters(c.a[4], next.value);
  IDirect3DDevice9 *device = nullptr;
  HRESULT hr = static_cast<IDirect3D9*>(c.self)->CreateDevice(c.a[0], D3DDEVTYPE(c.a[1]), next.value, c.a[3], &pp, &device);
  if (SUCCEEDED(hr)) {
    save_parameters(device, c.a[4], pp);
    device_windows[device] = next.take();
    *out = wrap(device);
    sayf("D3D9 device %ux%u created on the Android surface (windowed WSI; guest parameters kept)", pp.BackBufferWidth, pp.BackBufferHeight);
  } else sayf("CreateDevice failed %08X", unsigned(hr));
  host->window_ack(next.serial);
  return hr;
}
uint32_t reset(Context &c) {
  WindowLease next;
  auto *device = static_cast<IDirect3DDevice9*>(c.self);
  ANativeWindow *window = next.value ? next.value : device_windows[device];
  D3DPRESENT_PARAMETERS pp = native_parameters(c.a[0], window);
  HRESULT hr = device->Reset(&pp);
  if (SUCCEEDED(hr)) {
    save_parameters(device, c.a[0], pp);
    if (next.value) keep_window(device, next);
  } else sayf("Reset %ux%u failed %08X", pp.BackBufferWidth, pp.BackBufferHeight, unsigned(hr));
  return hr;
}
uint32_t additional_swapchain(Context &c) {
  auto *out = memory<uint32_t>(c.a[1], 1, true);
  if (!out) return D3DERR_INVALIDCALL;
  *out = 0;
  auto *window = device_windows[c.self];
  if (!window) return D3DERR_INVALIDCALL;
  D3DPRESENT_PARAMETERS pp = native_parameters(c.a[0], window);
  IDirect3DSwapChain9 *chain = nullptr;
  HRESULT hr = static_cast<IDirect3DDevice9*>(c.self)->CreateAdditionalSwapChain(&pp, &chain);
  if (SUCCEEDED(hr)) { save_parameters(chain, c.a[0], pp); *out = wrap(chain); }
  return hr;
}

/* DXVK reports each accepted vkQueuePresentKHR (ut3_dxvk_set_callbacks_v2): the 5 s log counts
 * frames that reached the display queue, with the native Present cost on the game thread. */
std::mutex present_metrics_lock;
std::map<const void*, uint64_t> presented_ids;
uint64_t present_frames, sample_frames, sample_calls, sample_draws, sample_cpu, sample_wall;
auto sample_time = std::chrono::steady_clock::now();
void presented(const void *presenter, uint64_t id, int32_t result) {
  std::lock_guard<std::mutex> guard(present_metrics_lock);
  if (!id) { presented_ids.erase(presenter); return; }
  if ((result != 0 && result != 1000001003) || id <= presented_ids[presenter]) return;
  presented_ids[presenter] = id;
  auto now = std::chrono::steady_clock::now();
  if (!present_frames++) { sample_time = now; return; }
  double seconds = std::chrono::duration<double>(now - sample_time).count();
  if (seconds < 5) return;
  double frames = double(present_frames - sample_frames);
  uint64_t calls = native_calls.load(), draws = draw_calls.load(), cpu = present_cpu_ns.load(), wall = present_wall_ns.load();
  sayf("frame %llu: %.1f fps presented; per frame %.0f calls, %.0f draws, native Present %.2f ms cpu / %.2f ms wall",
       (unsigned long long)present_frames, frames / seconds, (calls - sample_calls) / frames, (draws - sample_draws) / frames,
       (cpu - sample_cpu) / frames / 1e6, (wall - sample_wall) / frames / 1e6);
  sample_time = now; sample_frames = present_frames; sample_calls = calls; sample_draws = draws; sample_cpu = cpu; sample_wall = wall;
}
/* The window the device's swap chain was created or last reset with. */
ANativeWindow *device_present_window(IDirect3DDevice9 *device) {
  IDirect3DSwapChain9 *chain = nullptr;
  if (FAILED(device->GetSwapChain(0, &chain)) || !chain) return nullptr;
  D3DPRESENT_PARAMETERS p{};
  HRESULT hr = chain->GetPresentParameters(&p);
  chain->Release();
  return SUCCEEDED(hr) ? reinterpret_cast<ANativeWindow*>(p.hDeviceWindow) : nullptr;
}
uint32_t present(Context &c) {
  if (c.a[2] || c.a[3]) return D3DERR_INVALIDCALL; /* No HWND override or dirty region from the guest. */
  WindowLease current;
  if (!current.value) { host->window_ack(current.serial); return D3D_OK; } /* surface lost after the host's wait: skip this frame */
  IDirect3DDevice9 *owned = nullptr, *device = context_device(c, &owned);
  if (!device) return D3DERR_INVALIDCALL;
  keep_window(device, current);
  ANativeWindow *window = device_windows[device];
  if (owned) owned->Release();
  const RECT *src = memory<const RECT>(c.a[0]), *dst = memory<const RECT>(c.a[1]);
  RECT aspect{};
  /* Fit with the original aspect ratio, as the GLES present does (d3d9_gl.c, map_touch_point). */
  if (!dst) { aspect = aspect_destination(ANativeWindow_getWidth(window), ANativeWindow_getHeight(window), backbuffer_width.load(), backbuffer_height.load()); dst = &aspect; }
  HRESULT hr;
  {
    PresentTime time;
    /* The device's own window unless the activity replaced the surface: DXVK keeps a presenter per
     * destination window, and naming the device window as an override after a Reset presented into
     * a second, never-acquired presenter (black screen, frame events never signalled). */
    HWND override = window == device_present_window(device) ? nullptr : reinterpret_cast<HWND>(window);
    hr = c.kind == Kind::IDirect3DSwapChain9
        ? static_cast<IDirect3DSwapChain9*>(c.self)->Present(src, dst, override, nullptr, c.a[4])
        : device->Present(src, dst, override, nullptr);
  }
  host->window_ack(current.serial);
  if (FAILED(hr)) { static unsigned warned; if (warned++ < 20) sayf("Present failed %08X", unsigned(hr)); }
  return hr;
}
uint32_t shader_bytes(uint32_t va) {
  uint32_t version = ref<uint32_t>(va);
  if ((version >> 16) != 0xfffe && (version >> 16) != 0xffff) throw std::runtime_error("invalid shader version token");
  uint32_t offset = 4;
  while (offset < (16u << 20)) {
    uint32_t token = ref<uint32_t>(va + offset);
    if ((token & 0xffff) == 0xffff) return offset + 4;
    /* SM1 instruction tokens carry no length (Heroes V has ps_1_x shaders): walk their parameter
     * tokens, which have bit 31 set, except def's four float literals. */
    uint32_t length;
    if ((token & 0xffff) == 0xfffe) length = (token >> 16) & 0x7fff;
    else if (((version >> 8) & 255) >= 2) length = (token >> 24) & 15;
    else if ((token & 0xffff) == 0x51) length = 5;
    else { length = 0; while (ref<uint32_t>(va + offset + 4 * (length + 1)) & 0x80000000u) ++length; }
    offset = narrow_size(uint64_t(offset) + 4u * (length + 1));
  }
  throw std::runtime_error("unterminated shader");
}
uint32_t create_shader(Context &c, bool pixel) {
  auto *code = memory<const DWORD>(c.a[0], shader_bytes(c.a[0]) / 4);
  auto *out = memory<uint32_t>(c.a[1], 1, true);
  if (!out) return D3DERR_INVALIDCALL;
  *out = 0;
  auto *device = static_cast<IDirect3DDevice9*>(c.self);
  if (pixel) { IDirect3DPixelShader9 *p = nullptr; HRESULT hr = device->CreatePixelShader(code, &p); if (SUCCEEDED(hr)) *out = wrap(p); return hr; }
  IDirect3DVertexShader9 *p = nullptr; HRESULT hr = device->CreateVertexShader(code, &p); if (SUCCEEDED(hr)) *out = wrap(p); return hr;
}
uint32_t create_declaration(Context &c) {
  uint32_t count = 0;
  for (; count < 65; ++count) if (ref<D3DVERTEXELEMENT9>(c.a[0] + count * 8).Stream == 0xff) break;
  if (count == 65) return D3DERR_INVALIDCALL;
  auto *input = memory<const D3DVERTEXELEMENT9>(c.a[0], count + 1);
  auto *out = memory<uint32_t>(c.a[1], 1, true);
  if (!out) return D3DERR_INVALIDCALL;
  *out = 0;
  IDirect3DVertexDeclaration9 *p = nullptr;
  HRESULT hr = static_cast<IDirect3DDevice9*>(c.self)->CreateVertexDeclaration(input, &p);
  if (SUCCEEDED(hr)) *out = wrap(p);
  return hr;
}
size_t vertex_count(uint32_t type, uint32_t count) {
  switch (type) {
    case 1: return count; case 2: return size_t(count) * 2; case 3: return size_t(count) + 1; case 4: return size_t(count) * 3;
    case 5: case 6: return size_t(count) + 2; default: throw std::runtime_error("invalid primitive topology");
  }
}
uint32_t draw_up(Context &c, bool indexed) {
  auto *d = static_cast<IDirect3DDevice9*>(c.self);
  if (!indexed) return d->DrawPrimitiveUP(D3DPRIMITIVETYPE(c.a[0]), c.a[1], memory<const uint8_t>(c.a[2], vertex_count(c.a[0], c.a[1]) * c.a[3]), c.a[3]);
  size_t isize = c.a[5] == D3DFMT_INDEX16 ? 2 : c.a[5] == D3DFMT_INDEX32 ? 4 : 0;
  if (!isize) return D3DERR_INVALIDCALL;
  return d->DrawIndexedPrimitiveUP(D3DPRIMITIVETYPE(c.a[0]), c.a[1], c.a[2], c.a[3], memory<const uint8_t>(c.a[4], vertex_count(c.a[0], c.a[3]) * isize),
                                   D3DFORMAT(c.a[5]), memory<const uint8_t>(c.a[6], (size_t(c.a[1]) + c.a[2]) * c.a[7]), c.a[7]);
}
struct Mapping { uint32_t guest; uint8_t *native; uint32_t row_pitch, slice_pitch, row_bytes, rows, slices; bool readonly; };
std::map<std::pair<void*, uint32_t>, Mapping> mappings;
bool block_format(D3DFORMAT f) { return f == D3DFMT_DXT1 || f == D3DFMT_DXT2 || f == D3DFMT_DXT3 || f == D3DFMT_DXT4 || f == D3DFMT_DXT5; }
uint32_t rows_for(D3DFORMAT f, uint32_t h) { return block_format(f) ? (h + 3) / 4 : h; }
uint32_t row_bytes(D3DFORMAT f, uint32_t w) {
  switch (f) {
    case D3DFMT_DXT1: return ((w + 3) / 4) * 8;
    case D3DFMT_DXT2: case D3DFMT_DXT3: case D3DFMT_DXT4: case D3DFMT_DXT5: return ((w + 3) / 4) * 16;
    case D3DFMT_A8: case D3DFMT_L8: case D3DFMT_P8: case D3DFMT_R3G3B2: case D3DFMT_A4L4: return w;
    case D3DFMT_R5G6B5: case D3DFMT_X1R5G5B5: case D3DFMT_A1R5G5B5: case D3DFMT_A4R4G4B4: case D3DFMT_X4R4G4B4: case D3DFMT_A8R3G3B2:
    case D3DFMT_A8L8: case D3DFMT_A8P8: case D3DFMT_V8U8: case D3DFMT_L6V5U5: case D3DFMT_L16: case D3DFMT_R16F: case D3DFMT_CxV8U8:
    case D3DFMT_D16: case D3DFMT_D16_LOCKABLE: case D3DFMT_D15S1: return narrow_size(uint64_t(w) * 2);
    case D3DFMT_R8G8B8: return narrow_size(uint64_t(w) * 3);
    case D3DFMT_A8R8G8B8: case D3DFMT_X8R8G8B8: case D3DFMT_A8B8G8R8: case D3DFMT_X8B8G8R8: case D3DFMT_A2R10G10B10: case D3DFMT_A2B10G10R10:
    case D3DFMT_G16R16: case D3DFMT_V16U16: case D3DFMT_Q8W8V8U8: case D3DFMT_X8L8V8U8: case D3DFMT_A2W10V10U10: case D3DFMT_G16R16F:
    case D3DFMT_R32F: case D3DFMT_D32: case D3DFMT_D24S8: case D3DFMT_D24X8: case D3DFMT_D24X4S4: case D3DFMT_D32F_LOCKABLE:
    case D3DFMT_D24FS8: case D3DFMT_D32_LOCKABLE: return narrow_size(uint64_t(w) * 4);
    case D3DFMT_A16B16G16R16: case D3DFMT_A16B16G16R16F: case D3DFMT_G32R32F: case D3DFMT_Q16W16V16U16: return narrow_size(uint64_t(w) * 8);
    case D3DFMT_A32B32G32R32F: return narrow_size(uint64_t(w) * 16);
    case D3DFMT_UYVY: case D3DFMT_YUY2: return narrow_size(((uint64_t(w) + 1) / 2) * 4);
    default: throw std::runtime_error("native locked format has no checked guest row layout");
  }
}
Mapping map_memory(void *native, uint32_t pitch, uint32_t slice, uint32_t bytes, uint32_t rows, uint32_t slices, uint32_t flags) {
  if (!native || !bytes || !rows || !slices || pitch < bytes || slice < uint64_t(pitch) * (rows - 1) + bytes) throw std::runtime_error("invalid native lock geometry");
  uint32_t length = narrow_size(uint64_t(slice) * (slices - 1) + uint64_t(pitch) * (rows - 1) + bytes), guest = host->guest_alloc(length);
  if (!guest) throw std::bad_alloc();
  Mapping m{guest, static_cast<uint8_t*>(native), pitch, slice, bytes, rows, slices, (flags & D3DLOCK_READONLY) != 0};
  /* DISCARD leaves the whole locked contents undefined: the guest writes them all, nothing to read. */
  if (!(flags & D3DLOCK_DISCARD)) try {
    auto *destination = memory<uint8_t>(guest, length, true);
    for (uint32_t z = 0; z < slices; ++z)
      for (uint32_t y = 0; y < rows; ++y)
        memcpy(destination + size_t(z) * slice + size_t(y) * pitch, m.native + size_t(z) * slice + size_t(y) * pitch, bytes);
  } catch (...) { host->guest_free(guest); throw; }
  return m;
}
void retain_mapping(const std::pair<void*, uint32_t> &key, const Mapping &m) {
  try { if (!mappings.emplace(key, m).second) throw std::runtime_error("duplicate native lock"); }
  catch (...) { host->guest_free(m.guest); throw; }
}
void flush_mapping(const Mapping &m) {
  if (m.readonly) return;
  auto *source = memory<const uint8_t>(m.guest, size_t(m.slice_pitch) * (m.slices - 1) + size_t(m.row_pitch) * (m.rows - 1) + m.row_bytes);
  for (uint32_t z = 0; z < m.slices; ++z)
    for (uint32_t y = 0; y < m.rows; ++y)
      memcpy(m.native + size_t(z) * m.slice_pitch + size_t(y) * m.row_pitch, source + size_t(z) * m.slice_pitch + size_t(y) * m.row_pitch, m.row_bytes);
}
/* Vertex and index buffers keep one guest copy (shadow) for their life, as the OpenGL ES backend
 * does (d3d9_resource.c): the guest is their only writer, so a lock returns the shadow with no
 * native lock, read-back or allocation, and marks its pages dirty. The engine's pooled allocator
 * locks whole buffers (0, 0, NOOVERWRITE) many times a frame to change a few suballocations; a
 * bounce buffer per lock copied every byte both ways. Before each draw, only the dirty pages the
 * draw reads (its vertex range from the actual indices, its index range) go to DXVK: the first
 * upload after a DISCARD lock renames the buffer, a lock without NOOVERWRITE uploads unsynchronised
 * no more than D3D9 allows, the rest as NOOVERWRITE. */
constexpr uint32_t kShadowPage = 4096;
struct Shadow {
  uint32_t guest = 0, size = 0, index_bytes = 0;
  std::vector<uint8_t> dirty;
  uint32_t dirty_count = 0;
  bool discard = false, overwrite = false, vertex = true;
};
std::unordered_map<void*, Shadow> shadows;
struct StreamBinding { void *buffer; uint32_t offset, stride; };
StreamBinding streams[16];
uint32_t stream_freq[16];
void *bound_indices;

void shadow_dirty(Shadow &s, uint32_t lo, uint32_t hi) {
  if (lo >= hi) return;
  for (uint32_t page = lo / kShadowPage, last = (hi - 1) / kShadowPage; page <= last; ++page)
    if (!s.dirty[page]) { s.dirty[page] = 1; ++s.dirty_count; }
}

/* The dirty pages of [lo, hi) to the native buffer, in runs of consecutive pages. */
void shadow_upload(void *buffer, Shadow &s, uint32_t lo, uint32_t hi) {
  if (!s.dirty_count || !s.guest) return;
  hi = std::min(hi, s.size);
  if (lo >= hi) return;
  const uint8_t *source = memory<const uint8_t>(s.guest, s.size);
  for (uint32_t page = lo / kShadowPage, last = (hi - 1) / kShadowPage; page <= last;) {
    if (!s.dirty[page]) { ++page; continue; }
    uint32_t first = page;
    while (page <= last && s.dirty[page]) { s.dirty[page] = 0; --s.dirty_count; ++page; }
    uint32_t from = first * kShadowPage, to = std::min(page * kShadowPage, s.size);
    DWORD flags = s.discard ? D3DLOCK_DISCARD : s.overwrite ? 0 : D3DLOCK_NOOVERWRITE;
    void *target = nullptr;
    HRESULT hr = s.vertex ? static_cast<IDirect3DVertexBuffer9*>(buffer)->Lock(from, to - from, &target, flags)
                          : static_cast<IDirect3DIndexBuffer9*>(buffer)->Lock(from, to - from, &target, flags);
    if (FAILED(hr) || !target) { static unsigned warned; if (warned++ < 20) sayf("buffer upload lock failed %08X", unsigned(hr)); continue; }
    memcpy(target, source + from, to - from);
    if (s.vertex) static_cast<IDirect3DVertexBuffer9*>(buffer)->Unlock(); else static_cast<IDirect3DIndexBuffer9*>(buffer)->Unlock();
    s.discard = s.overwrite = false;
  }
}

Shadow *shadow_of(void *buffer) {
  auto it = shadows.find(buffer);
  return it == shadows.end() ? nullptr : &it->second;
}

/* DrawPrimitive (81: type, start vertex, count) and DrawIndexedPrimitive (82: type, base vertex,
 * min index, vertices, start index, count): upload what the draw reads from each bound stream. */
void upload_for_draw(unsigned slot, const uint32_t *args) {
  bool indexed = slot == 82, instanced = false;
  for (uint32_t freq : stream_freq) if (freq > 1) instanced = true;
  int64_t first = 0, last = -1;   /* vertex numbers, inclusive */
  if (!indexed) {
    first = args[1];
    last = first + int64_t(vertex_count(args[0], args[2])) - 1;
  } else {
    Shadow *ib = bound_indices ? shadow_of(bound_indices) : nullptr;
    uint64_t count = vertex_count(args[0], args[5]), start = args[4];
    if (ib && ib->index_bytes) {
      uint64_t lo = start * ib->index_bytes, hi = (start + count) * ib->index_bytes;
      shadow_upload(bound_indices, *ib, uint32_t(std::min<uint64_t>(lo, ib->size)), uint32_t(std::min<uint64_t>(hi, ib->size)));
      /* The actual vertex range: MinVertexIndex/NumVertices are hints some games get wrong. */
      if (hi <= ib->size && count) {
        const uint8_t *data = memory<const uint8_t>(ib->guest, ib->size) + lo;
        uint32_t low = UINT32_MAX, high = 0;
        if (ib->index_bytes == 2) for (uint64_t i = 0; i < count; ++i) { uint32_t v = reinterpret_cast<const uint16_t*>(data)[i]; low = std::min(low, v); high = std::max(high, v); }
        else for (uint64_t i = 0; i < count; ++i) { uint32_t v = reinterpret_cast<const uint32_t*>(data)[i]; low = std::min(low, v); high = std::max(high, v); }
        first = int64_t(int32_t(args[1])) + low;
        last = int64_t(int32_t(args[1])) + high;
      }
    }
    if (last < first) { first = int64_t(int32_t(args[1])) + args[2]; last = first + int64_t(args[3]) - 1; }
  }
  for (const StreamBinding &stream : streams) {
    if (!stream.buffer) continue;
    Shadow *vb = shadow_of(stream.buffer);
    if (!vb || !vb->dirty_count) continue;
    if (instanced || !stream.stride || first < 0) { shadow_upload(stream.buffer, *vb, 0, vb->size); continue; }
    uint64_t lo = uint64_t(stream.offset) + uint64_t(first) * stream.stride, hi = uint64_t(stream.offset) + uint64_t(last + 1) * stream.stride;
    shadow_upload(stream.buffer, *vb, uint32_t(std::min<uint64_t>(lo, vb->size)), uint32_t(std::min<uint64_t>(hi, vb->size)));
  }
}

void forget_buffer(void *buffer) {
  auto it = shadows.find(buffer);
  if (it == shadows.end()) return;
  if (it->second.guest) host->guest_free(it->second.guest);
  shadows.erase(it);
  for (StreamBinding &stream : streams) if (stream.buffer == buffer) stream = {};
  if (bound_indices == buffer) bound_indices = nullptr;
}

uint32_t buffer_lock(Context &c, bool unlock) {
  if (unlock) return shadows.count(c.self) ? D3D_OK : D3DERR_INVALIDCALL;
  bool vertex = c.kind == Kind::IDirect3DVertexBuffer9;
  auto *out = memory<uint32_t>(c.a[2], 1, true);
  if (!out) return D3DERR_INVALIDCALL;
  *out = 0;
  Shadow &s = shadows[c.self];
  if (!s.guest) {
    uint32_t total = 0, index_bytes = 0;
    if (vertex) { D3DVERTEXBUFFER_DESC d; HRESULT hr = static_cast<IDirect3DVertexBuffer9*>(c.self)->GetDesc(&d); if (FAILED(hr)) { shadows.erase(c.self); return hr; } total = d.Size; }
    else { D3DINDEXBUFFER_DESC d; HRESULT hr = static_cast<IDirect3DIndexBuffer9*>(c.self)->GetDesc(&d); if (FAILED(hr)) { shadows.erase(c.self); return hr; }
           total = d.Size; index_bytes = d.Format == D3DFMT_INDEX32 ? 4 : 2; }
    if (!total) { shadows.erase(c.self); return D3DERR_INVALIDCALL; }
    s.guest = host->guest_alloc(total);
    if (!s.guest) { shadows.erase(c.self); throw std::bad_alloc(); }
    memset(memory<uint8_t>(s.guest, total, true), 0, total);
    s.size = total; s.index_bytes = index_bytes; s.vertex = vertex;
    s.dirty.assign((total + kShadowPage - 1) / kShadowPage, 0);
  }
  uint32_t offset = c.a[0], length = c.a[1] ? c.a[1] : s.size - offset, flags = c.a[3];
  if (offset > s.size || length > s.size - offset) return D3DERR_INVALIDCALL;
  if (!(flags & D3DLOCK_READONLY)) {
    if (flags & D3DLOCK_DISCARD) { s.discard = true; shadow_dirty(s, 0, s.size); }
    else if (!(flags & D3DLOCK_NOOVERWRITE)) s.overwrite = true;
    shadow_dirty(s, offset, offset + length);
  }
  *out = s.guest + offset;
  return D3D_OK;
}
uint32_t texture_lock(Context &c, bool unlock) {
  bool texture = c.kind == Kind::IDirect3DTexture9, cube = c.kind == Kind::IDirect3DCubeTexture9;
  uint32_t face = cube ? c.a[0] : 0, level = texture ? c.a[0] : cube ? c.a[1] : 0, sub = (face << 16) | level;
  auto key = std::make_pair(c.self, sub);
  auto native_unlock = [&] {
    return texture ? static_cast<IDirect3DTexture9*>(c.self)->UnlockRect(level)
         : cube ? static_cast<IDirect3DCubeTexture9*>(c.self)->UnlockRect(D3DCUBEMAP_FACES(face), level)
         : static_cast<IDirect3DSurface9*>(c.self)->UnlockRect();
  };
  if (unlock) {
    auto it = mappings.find(key);
    if (it == mappings.end()) return D3DERR_INVALIDCALL;
    flush_mapping(it->second);
    HRESULT hr = native_unlock();
    if (SUCCEEDED(hr)) { host->guest_free(it->second.guest); mappings.erase(it); }
    return hr;
  }
  if (mappings.count(key)) return D3DERR_INVALIDCALL;
  uint32_t shift = texture ? 1 : cube ? 2 : 0;
  auto *out = memory<uint32_t>(c.a[shift], 2, true);
  if (!out) return D3DERR_INVALIDCALL;
  auto *rect = memory<const RECT>(c.a[shift + 1]);
  uint32_t flags = c.a[shift + 2];
  D3DSURFACE_DESC desc{};
  HRESULT hr = texture ? static_cast<IDirect3DTexture9*>(c.self)->GetLevelDesc(level, &desc)
             : cube ? static_cast<IDirect3DCubeTexture9*>(c.self)->GetLevelDesc(level, &desc)
             : static_cast<IDirect3DSurface9*>(c.self)->GetDesc(&desc);
  if (FAILED(hr)) return hr;
  uint32_t w = desc.Width, h = desc.Height;
  if (rect) {
    if (rect->left < 0 || rect->top < 0 || rect->right <= rect->left || rect->bottom <= rect->top || uint32_t(rect->right) > w || uint32_t(rect->bottom) > h) return D3DERR_INVALIDCALL;
    w = rect->right - rect->left; h = rect->bottom - rect->top;
  }
  D3DLOCKED_RECT lock{};
  hr = texture ? static_cast<IDirect3DTexture9*>(c.self)->LockRect(level, &lock, rect, flags)
     : cube ? static_cast<IDirect3DCubeTexture9*>(c.self)->LockRect(D3DCUBEMAP_FACES(face), level, &lock, rect, flags)
     : static_cast<IDirect3DSurface9*>(c.self)->LockRect(&lock, rect, flags);
  if (SUCCEEDED(hr)) {
    try {
      uint32_t rows = rows_for(desc.Format, h), bytes = row_bytes(desc.Format, w);
      auto m = map_memory(lock.pBits, uint32_t(lock.Pitch), narrow_size(uint64_t(lock.Pitch) * rows), bytes, rows, 1, flags);
      retain_mapping(key, m); out[0] = lock.Pitch; out[1] = m.guest;
    } catch (...) { if (FAILED(native_unlock())) say("native texture Unlock rollback failed"); throw; }
  }
  return hr;
}
uint32_t volume_lock(Context &c, bool unlock) {
  bool texture = c.kind == Kind::IDirect3DVolumeTexture9;
  uint32_t level = texture ? c.a[0] : 0;
  auto key = std::make_pair(c.self, level);
  auto native_unlock = [&] { return texture ? static_cast<IDirect3DVolumeTexture9*>(c.self)->UnlockBox(level) : static_cast<IDirect3DVolume9*>(c.self)->UnlockBox(); };
  if (unlock) {
    auto it = mappings.find(key);
    if (it == mappings.end()) return D3DERR_INVALIDCALL;
    flush_mapping(it->second);
    HRESULT hr = native_unlock();
    if (SUCCEEDED(hr)) { host->guest_free(it->second.guest); mappings.erase(it); }
    return hr;
  }
  if (mappings.count(key)) return D3DERR_INVALIDCALL;
  unsigned shift = texture ? 1 : 0;
  auto *out = memory<uint32_t>(c.a[shift], 3, true);
  if (!out) return D3DERR_INVALIDCALL;
  auto *box = memory<const D3DBOX>(c.a[shift + 1]);
  uint32_t flags = c.a[shift + 2];
  D3DVOLUME_DESC desc{};
  HRESULT hr = texture ? static_cast<IDirect3DVolumeTexture9*>(c.self)->GetLevelDesc(level, &desc) : static_cast<IDirect3DVolume9*>(c.self)->GetDesc(&desc);
  if (FAILED(hr)) return hr;
  uint32_t w = desc.Width, h = desc.Height, z = desc.Depth;
  if (box) {
    if (box->Right <= box->Left || box->Bottom <= box->Top || box->Back <= box->Front || box->Right > w || box->Bottom > h || box->Back > z) return D3DERR_INVALIDCALL;
    w = box->Right - box->Left; h = box->Bottom - box->Top; z = box->Back - box->Front;
  }
  D3DLOCKED_BOX lock{};
  hr = texture ? static_cast<IDirect3DVolumeTexture9*>(c.self)->LockBox(level, &lock, box, flags) : static_cast<IDirect3DVolume9*>(c.self)->LockBox(&lock, box, flags);
  if (SUCCEEDED(hr)) {
    try {
      auto m = map_memory(lock.pBits, lock.RowPitch, lock.SlicePitch, row_bytes(desc.Format, w), rows_for(desc.Format, h), z, flags);
      retain_mapping(key, m); out[0] = lock.RowPitch; out[1] = lock.SlicePitch; out[2] = m.guest;
    } catch (...) { if (FAILED(native_unlock())) say("native volume Unlock rollback failed"); throw; }
  }
  return hr;
}
uint32_t query_interface(Context &c, bool container) {
  auto &iid = ref<GUID>(c.a[0]);
  auto *out = memory<uint32_t>(c.a[1], 1, true);
  if (!out) return E_POINTER;
  *out = 0;
  Kind kind = kind_for_iid(iid);
  if (kind == Kind::Count) return E_NOINTERFACE;
  void *native = nullptr;
  HRESULT hr;
  if (container) {
    if (c.kind == Kind::IDirect3DSurface9) hr = static_cast<IDirect3DSurface9*>(c.self)->GetContainer(iid, &native);
    else hr = static_cast<IDirect3DVolume9*>(c.self)->GetContainer(iid, &native);
  } else hr = static_cast<IUnknown*>(c.self)->QueryInterface(iid, &native);
  if (SUCCEEDED(hr)) {
    if (kind == Kind::IDirect3DBaseTexture9) *out = wrap(static_cast<IDirect3DBaseTexture9*>(native));
    else if (kind == Kind::IDirect3DResource9) *out = wrap(static_cast<IDirect3DResource9*>(native));
    else *out = host->wrap_native(unsigned(kind), native);
  }
  return hr;
}
uint32_t special(Context &c, const char *name) {
  if (!strcmp(name, "QueryInterface")) return query_interface(c, false);
  if (!strcmp(name, "GetContainer")) return query_interface(c, true);
  if (!strcmp(name, "CreateDevice")) return create_device(c);
  if (!strcmp(name, "Reset")) return reset(c);
  if (!strcmp(name, "CreateAdditionalSwapChain")) return additional_swapchain(c);
  if (!strcmp(name, "Present")) return present(c);
  if (!strcmp(name, "GetAdapterIdentifier")) {
    D3DADAPTER_IDENTIFIER9 id{};
    auto *out = memory<uint8_t>(c.a[2], 1100, true);
    HRESULT hr = static_cast<IDirect3D9*>(c.self)->GetAdapterIdentifier(c.a[0], c.a[1], &id);
    /* Win32 packs it to 4 (1100 bytes); natively only tail padding follows WHQLLevel. */
    static_assert(offsetof(D3DADAPTER_IDENTIFIER9, DriverVersion) == 1056 && offsetof(D3DADAPTER_IDENTIFIER9, WHQLLevel) == 1096,
                  "D3DADAPTER_IDENTIFIER9 keeps the 32-bit field offsets");
    if (SUCCEEDED(hr) && out) memcpy(out, &id, 1100);
    return out ? hr : D3DERR_INVALIDCALL;
  }
  if (!strcmp(name, "GetAdapterMonitor")) return static_cast<IDirect3D9*>(c.self)->GetAdapterMonitor(c.a[0]) ? 0x70001 : 0;
  if (!strcmp(name, "GetPresentParameters")) {
    auto *out = memory<uint32_t>(c.a[0], 14, true);
    if (!out) return D3DERR_INVALIDCALL;
    auto it = parameters.find(c.self);
    if (it != parameters.end()) { memcpy(out, it->second.data(), 56); return D3D_OK; }
    D3DPRESENT_PARAMETERS p{};
    HRESULT hr = static_cast<IDirect3DSwapChain9*>(c.self)->GetPresentParameters(&p);
    if (FAILED(hr)) return hr;
    std::array<uint32_t, 14> v = {p.BackBufferWidth, p.BackBufferHeight, uint32_t(p.BackBufferFormat), p.BackBufferCount, uint32_t(p.MultiSampleType),
                                  p.MultiSampleQuality, uint32_t(p.SwapEffect), 0, 1, uint32_t(p.EnableAutoDepthStencil), uint32_t(p.AutoDepthStencilFormat),
                                  p.Flags, 0, p.PresentationInterval};
    memcpy(out, v.data(), 56);
    return D3D_OK;
  }
  if (!strcmp(name, "GetCreationParameters")) {
    D3DDEVICE_CREATION_PARAMETERS p{};
    HRESULT hr = static_cast<IDirect3DDevice9*>(c.self)->GetCreationParameters(&p);
    if (SUCCEEDED(hr)) {
      auto *out = memory<uint32_t>(c.a[0], 4, true);
      if (!out) return D3DERR_INVALIDCALL;
      out[0] = p.AdapterOrdinal; out[1] = p.DeviceType; out[2] = parameters.count(c.self) ? parameters[c.self][7] : 0; out[3] = p.BehaviorFlags;
    }
    return hr;
  }
  if (!strcmp(name, "CreateVertexShader")) return create_shader(c, false);
  if (!strcmp(name, "CreatePixelShader")) return create_shader(c, true);
  if (!strcmp(name, "CreateVertexDeclaration")) return create_declaration(c);
  if (!strcmp(name, "DrawPrimitiveUP")) return draw_up(c, false);
  if (!strcmp(name, "DrawIndexedPrimitiveUP")) return draw_up(c, true);
  if (!strcmp(name, "Lock") || !strcmp(name, "Unlock")) return buffer_lock(c, name[0] == 'U');
  if (!strcmp(name, "LockRect") || !strcmp(name, "UnlockRect")) return texture_lock(c, name[0] == 'U');
  if (!strcmp(name, "LockBox") || !strcmp(name, "UnlockBox")) return volume_lock(c, name[0] == 'U');
  if (!strcmp(name, "GetFunction")) {
    auto *size = memory<UINT>(c.a[1], 1, true);
    if (!size) return D3DERR_INVALIDCALL;
    void *out = memory<uint8_t>(c.a[0], *size, true);
    return c.kind == Kind::IDirect3DVertexShader9 ? static_cast<IDirect3DVertexShader9*>(c.self)->GetFunction(out, size)
                                                  : static_cast<IDirect3DPixelShader9*>(c.self)->GetFunction(out, size);
  }
  if (!strcmp(name, "GetData")) return static_cast<IDirect3DQuery9*>(c.self)->GetData(memory<uint8_t>(c.a[0], c.a[1], true), c.a[1], c.a[2] | D3DGETDATA_FLUSH);
  if (!strcmp(name, "GetDC") || !strcmp(name, "ReleaseDC") || !strcmp(name, "RegisterSoftwareDevice")) return D3DERR_INVALIDCALL;
  return 0xffffffff;
}
template<class T> uint32_t private_data(Context &c, T *p, const char *name) {
  auto &guid = ref<GUID>(c.a[0]);
  if (!strcmp(name, "FreePrivateData")) return p->FreePrivateData(guid);
  if (!strcmp(name, "SetPrivateData")) {
    if (c.a[3] & D3DSPD_IUNKNOWN) return D3DERR_INVALIDCALL;
    return p->SetPrivateData(guid, memory<const uint8_t>(c.a[1], c.a[2]), c.a[2], c.a[3]);
  }
  auto *length = memory<DWORD>(c.a[2], 1, true);
  if (!length) return D3DERR_INVALIDCALL;
  return p->GetPrivateData(guid, memory<uint8_t>(c.a[1], *length, true), length);
}

/* ------------------------------------------------------------- operations */
uint32_t op_addref(void *p) { native_calls.fetch_add(1, std::memory_order_relaxed); return static_cast<IUnknown*>(p)->AddRef(); }
uint32_t op_release(void *p) {
  native_calls.fetch_add(1, std::memory_order_relaxed);
  uint32_t refs = static_cast<IUnknown*>(p)->Release();
  if (!refs) {
    forget_buffer(p);
    auto it = device_windows.find(p);
    if (it != device_windows.end()) { if (it->second) ANativeWindow_release(it->second); device_windows.erase(it); }
    parameters.erase(p);
  }
  return refs;
}
uint32_t op_create9(uint32_t sdk, const char *library_path, const char *turnip_dir) {
  try {
    void *library = dlopen(library_path, RTLD_NOW | RTLD_LOCAL);
    if (!library) { say(dlerror()); return 0; }
    if (turnip_dir) {
      char error[512]{};
      auto loader = homm5_open_turnip(turnip_dir, error, sizeof error);
      using SetLoader = void (*)(PFN_vkGetInstanceProcAddr);
      auto set_loader = reinterpret_cast<SetLoader>(dlsym(library, kSetLoader));
      if (!loader || !set_loader) { say(loader ? "DXVK custom Vulkan loader hook unavailable" : error); return 0; }
      set_loader(loader);
      say("Turnip Vulkan 1.3 driver loaded through adrenotools; the system driver stays in place");
    }
    using Callbacks = void (*)(int (*)(uint32_t*, uint32_t*, uint32_t*), void (*)(const void*, uint64_t, int32_t), void (*)());
    auto callbacks = reinterpret_cast<Callbacks>(dlsym(library, kSetCallbacks));
    if (!callbacks) { say(dlerror()); return 0; }
    callbacks(display_mode, presented, [] {});
    using Create = IDirect3D9 *(*)(UINT);
    auto create = reinterpret_cast<Create>(dlsym(library, "Direct3DCreate9"));
    if (!create) { say(dlerror()); return 0; }
    IDirect3D9 *d3d = create(sdk);
    if (!d3d) { say("DXVK Direct3DCreate9 failed (no Vulkan 1.3 adapter?)"); return 0; }
    /* An adapter that fails DXVK's filter is not enumerated: fall back before the game sees it. */
    if (!d3d->GetAdapterCount()) { say("DXVK found no usable Vulkan 1.3 adapter"); d3d->Release(); return 0; }
    D3DADAPTER_IDENTIFIER9 id{};
    if (SUCCEEDED(d3d->GetAdapterIdentifier(0, 0, &id))) sayf("adapter %s (vendor %04X device %04X)", id.Description, unsigned(id.VendorId), unsigned(id.DeviceId));
    return wrap(d3d);
  } catch (const std::exception &e) { say(e.what()); return 0; }
}
uint32_t op_call(unsigned kind, void *native, unsigned slot, const uint32_t *args) {
  native_calls.fetch_add(1, std::memory_order_relaxed);
  if (Kind(kind) == Kind::IDirect3DDevice9 && ((slot >= 81 && slot <= 84) || slot == 115 || slot == 116)) draw_calls.fetch_add(1, std::memory_order_relaxed);
  try {
    /* A pending occlusion query can be polled thousands of times: no name search for it. HoMM5
       polls its frame event without D3DGETDATA_FLUSH, which a Windows driver submits on its own in
       time; DXVK keeps the event in its unsubmitted command list and the game spins for ever. */
    if (Kind(kind) == Kind::IDirect3DQuery9 && slot == 7)
      return static_cast<IDirect3DQuery9*>(native)->GetData(memory<uint8_t>(args[0], args[1], true), args[1], args[2] | D3DGETDATA_FLUSH);
    if (Kind(kind) == Kind::IDirect3DDevice9) {
      if (slot == 81 || slot == 82) upload_for_draw(slot, args);
      else if (slot == 100 && args[0] < 16) streams[args[0]] = {args[1] ? host->unwrap_guest(args[1]) : nullptr, args[2], args[3]};
      else if (slot == 102 && args[0] < 16) stream_freq[args[0]] = args[1] & 0x3FFFFFFFu;
      else if (slot == 104) bound_indices = args[0] ? host->unwrap_guest(args[0]) : nullptr;
    }
    Context c{Kind(kind), native, slot, args};
    const char *name = nullptr;
    switch (c.kind) {
#include "bridge_special_names.h"
      default: break;
    }
    if (name) { uint32_t result = special(c, name); if (result != 0xffffffff) return result; }
    switch (c.kind) {
#include "bridge_dispatch.h"
      default: break;
    }
    sayf("unsupported DXVK COM slot %u/%u", kind, slot);
    return E_NOTIMPL;
  } catch (const std::bad_alloc &e) { say(e.what()); return E_OUTOFMEMORY; }
  catch (const std::exception &e) { say(e.what()); return D3DERR_INVALIDCALL; }
}
int32_t op_create_texture(void *device, int cube, uint32_t w, uint32_t h, uint32_t levels, uint32_t usage, uint32_t format, uint32_t pool, void **out) {
  *out = nullptr;
  auto *d = static_cast<IDirect3DDevice9*>(device);
  if (cube) { IDirect3DCubeTexture9 *t = nullptr; HRESULT hr = d->CreateCubeTexture(w, levels, usage, D3DFORMAT(format), D3DPOOL(pool), &t, nullptr); *out = t; return hr; }
  IDirect3DTexture9 *t = nullptr; HRESULT hr = d->CreateTexture(w, h, levels, usage, D3DFORMAT(format), D3DPOOL(pool), &t, nullptr); *out = t; return hr;
}
/* Textures arrive as their own interface pointers; both derive singly from IDirect3DBaseTexture9. */
IDirect3DBaseTexture9 *base_texture(void *texture) { return static_cast<IDirect3DBaseTexture9*>(static_cast<IDirect3DTexture9*>(texture)); }
uint32_t op_texture_levels(void *texture) { return base_texture(texture)->GetLevelCount(); }
void op_generate_mips(void *texture) { base_texture(texture)->GenerateMipSubLevels(); }
void *op_texture_surface(void *texture, int cube, uint32_t face, uint32_t level) {
  IDirect3DSurface9 *s = nullptr;
  HRESULT hr = cube ? static_cast<IDirect3DCubeTexture9*>(texture)->GetCubeMapSurface(D3DCUBEMAP_FACES(face), level, &s)
                    : static_cast<IDirect3DTexture9*>(texture)->GetSurfaceLevel(level, &s);
  return SUCCEEDED(hr) ? s : nullptr;
}
int32_t op_surface_desc(void *surface, uint32_t desc[5]) {
  D3DSURFACE_DESC d{};
  HRESULT hr = static_cast<IDirect3DSurface9*>(surface)->GetDesc(&d);
  if (SUCCEEDED(hr)) { desc[0] = d.Width; desc[1] = d.Height; desc[2] = uint32_t(d.Format); desc[3] = d.Usage; desc[4] = uint32_t(d.Pool); }
  return hr;
}
int32_t op_surface_lock(void *surface, const int32_t *rect, uint32_t flags, void **bits, int32_t *pitch) {
  RECT r{};
  if (rect) r = {LONG(rect[0]), LONG(rect[1]), LONG(rect[2]), LONG(rect[3])};
  D3DLOCKED_RECT lock{};
  HRESULT hr = static_cast<IDirect3DSurface9*>(surface)->LockRect(&lock, rect ? &r : nullptr, flags);
  *bits = SUCCEEDED(hr) ? lock.pBits : nullptr;
  *pitch = SUCCEEDED(hr) ? lock.Pitch : 0;
  return hr;
}
int32_t op_surface_unlock(void *surface) { return static_cast<IDirect3DSurface9*>(surface)->UnlockRect(); }
IDirect3DDevice9 *surface_device(void *surface) {
  IDirect3DDevice9 *device = nullptr;
  return SUCCEEDED(static_cast<IDirect3DSurface9*>(surface)->GetDevice(&device)) ? device : nullptr;
}
int32_t op_surface_copy(void *source, const int32_t *sr, void *target, const int32_t *tr, uint32_t filter) {
  IDirect3DDevice9 *device = surface_device(target);
  if (!device) return D3DERR_INVALIDCALL;
  RECT s{}, t{};
  if (sr) s = {LONG(sr[0]), LONG(sr[1]), LONG(sr[2]), LONG(sr[3])};
  if (tr) t = {LONG(tr[0]), LONG(tr[1]), LONG(tr[2]), LONG(tr[3])};
  HRESULT hr = device->StretchRect(static_cast<IDirect3DSurface9*>(source), sr ? &s : nullptr, static_cast<IDirect3DSurface9*>(target), tr ? &t : nullptr, D3DTEXTUREFILTERTYPE(filter));
  device->Release();
  return hr;
}
void *op_surface_staging(void *like, int read) {
  D3DSURFACE_DESC d{};
  if (FAILED(static_cast<IDirect3DSurface9*>(like)->GetDesc(&d))) return nullptr;
  IDirect3DDevice9 *device = surface_device(like);
  if (!device) return nullptr;
  IDirect3DSurface9 *staging = nullptr;
  HRESULT hr = device->CreateOffscreenPlainSurface(d.Width, d.Height, d.Format, D3DPOOL_SYSTEMMEM, &staging, nullptr);
  if (SUCCEEDED(hr) && read) hr = device->GetRenderTargetData(static_cast<IDirect3DSurface9*>(like), staging);
  device->Release();
  if (FAILED(hr) && staging) { staging->Release(); staging = nullptr; }
  return staging;
}
int32_t op_surface_upload(void *staging, void *target, const int32_t *rect) {
  IDirect3DDevice9 *device = surface_device(target);
  if (!device) return D3DERR_INVALIDCALL;
  RECT r{};
  POINT at{};
  if (rect) { r = {LONG(rect[0]), LONG(rect[1]), LONG(rect[2]), LONG(rect[3])}; at = {LONG(rect[0]), LONG(rect[1])}; }
  HRESULT hr = device->UpdateSurface(static_cast<IDirect3DSurface9*>(staging), rect ? &r : nullptr, static_cast<IDirect3DSurface9*>(target), rect ? &at : nullptr);
  device->Release();
  return hr;
}
int32_t op_constants(void *device, int pixel, int type, uint32_t start, const void *data, uint32_t count) {
  native_calls.fetch_add(1, std::memory_order_relaxed);
  auto *d = static_cast<IDirect3DDevice9*>(device);
  switch (type) {
    case 0: return pixel ? d->SetPixelShaderConstantF(start, static_cast<const float*>(data), count) : d->SetVertexShaderConstantF(start, static_cast<const float*>(data), count);
    case 1: return pixel ? d->SetPixelShaderConstantI(start, static_cast<const int*>(data), count) : d->SetVertexShaderConstantI(start, static_cast<const int*>(data), count);
    default: return pixel ? d->SetPixelShaderConstantB(start, static_cast<const BOOL*>(data), count) : d->SetVertexShaderConstantB(start, static_cast<const BOOL*>(data), count);
  }
}
const homm5_dxvk_bridge operations = {
  HOMM5_DXVK_ABI, sizeof(homm5_dxvk_bridge), kSlotsDigest,
  op_create9, op_call, op_addref, op_release,
  op_create_texture, op_texture_levels, op_generate_mips, op_texture_surface,
  op_surface_desc, op_surface_lock, op_surface_unlock, op_surface_copy, op_surface_staging, op_surface_upload,
  op_constants,
};
}

EXPORT const homm5_dxvk_bridge *homm5_dxvk_bridge_open(const homm5_dxvk_host *services) {
  if (!services || services->abi != HOMM5_DXVK_ABI || services->size != sizeof(homm5_dxvk_host) || services->slots_digest != kSlotsDigest) return nullptr;
  host = services;
  return &operations;
}
