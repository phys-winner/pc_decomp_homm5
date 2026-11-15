/* Typed x86 D3D9 -> native ARM64 DXVK boundary: libh5dxvk.so, adapted from the sibling ut3
 * port's android/dxvk/bridge.cpp. The ToE engine opens it with dlopen only in a DXVK renderer
 * mode and hands it the host services of bridge_abi.h (the engine's own symbols are hidden).
 * Native pointers never enter guest memory: guest objects are the engine's COM wrappers, locks
 * are bounce buffers in guest memory, and a replaced Android surface is taken up as the present's
 * destination window instead of a lost device. */
#include <d3d9.h>
#include <android/native_window.h>
#include <dlfcn.h>
#include <sched.h>
#include <time.h>
#include <unistd.h>
#include <algorithm>
#include <array>
#include <atomic>
#include <condition_variable>
#include <thread>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <pthread.h>
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
/* A statistics counter with one writing thread: a relaxed load and store, no read-modify-write
 * (an outlined LSE call on arm64; per record they were 2-8 % of the threads' time). */
template<class T> inline void bump(std::atomic<T> &counter, T by = 1) {
  counter.store(counter.load(std::memory_order_relaxed) + by, std::memory_order_relaxed);
}

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
void ring_drop();
IDirect3DDevice9 *ring_device();
uint32_t ring_refs();
void worker_stats(uint64_t present_frames, double frames);

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
/* The game's thread per frame: shadow-buffer work before draws (uploads into DXVK, index scans). */
std::atomic<uint64_t> buffer_locks{}, upload_runs{}, upload_bytes{}, scanned_indices{}, skipped_scans{};
std::atomic<uint64_t> ring_draws{}, ring_sparse{}, ring_bytes{}, ring_fallbacks{};
/* VOID_DXVK_STATS=1 (in dxvk.env): every call counted by interface and slot, the busiest per frame
 * in the 5 s line (kind/slot numbers of bridge_metadata.h and d3d9.h's method order). */
bool slot_stats;
std::atomic<uint32_t> slot_counts[18][128];
uint32_t slot_seen[18][128];
std::atomic<uint64_t> addref_calls{}, release_calls{};
uint64_t addref_seen, release_seen;

/* ------------------------------------------------------------ worker cores
 * DXVK's threads (CS, submission, presenter, compiler workers) and the driver's are created
 * while the game's thread runs Direct3DCreate9/CreateDevice/Reset, and a new thread takes its
 * creator's CPU mask: the guest threads' biggest-core tier (threads.c pin_guest_thread), on a
 * phone with one prime core that core alone. There dxvk-cs, which records every Vulkan command,
 * took turns with the game. They move to the tier the GLES render thread uses (d3d9_thread.c
 * leave_game_cores): auto = the tier below the biggest on a SoC with three tiers or one biggest
 * core, else the biggest; VOID_DXVK_CORES (else VOID_RT_CORES) = auto|big|next|any picks
 * another; any = every CPU. */
struct WorkerCores { cpu_set_t mask; int count = 0; long capacity = 0; const char *policy = "auto"; };
long cpu_capacity(int cpu) {
  char path[96];
  snprintf(path, sizeof path, "/sys/devices/system/cpu/cpu%d/cpu_capacity", cpu);
  FILE *f = fopen(path, "r");
  if (!f) return -1;
  long value = -1;
  if (fscanf(f, "%ld", &value) != 1) value = -1;
  fclose(f);
  return value;
}
WorkerCores choose_worker_cores() {
  static const char *const names[] = {"auto", "big", "next", "any"};
  WorkerCores w;
  CPU_ZERO(&w.mask);
  const char *requested = getenv("VOID_DXVK_CORES");
  if (!requested || !*requested) requested = getenv("VOID_RT_CORES");
  int policy = 0;
  if (requested && *requested) {
    for (policy = 0; policy < 4 && strcmp(requested, names[policy]); ++policy) {}
    if (policy == 4) policy = 0;
  }
  w.policy = names[policy];
  long configured = sysconf(_SC_NPROCESSORS_CONF);
  int cpus = configured > 0 && configured <= CPU_SETSIZE ? int(configured) : 0;
  std::vector<long> capacity(size_t(std::max(cpus, 0)));
  long best = 0, next = 0;
  int big = 0;
  bool known = cpus > 0, third = false;
  for (int i = 0; i < cpus; ++i) { capacity[size_t(i)] = cpu_capacity(i); if (capacity[size_t(i)] <= 0) known = false; best = std::max(best, capacity[size_t(i)]); }
  if (known) {
    for (int i = 0; i < cpus; ++i) { if (capacity[size_t(i)] == best) ++big; else next = std::max(next, capacity[size_t(i)]); }
    for (int i = 0; i < cpus; ++i) if (capacity[size_t(i)] < next) third = true;
  }
  long chosen = 0;
  if (known && next && policy != 3) chosen = policy == 1 ? best : policy == 2 ? next : (third || big == 1) ? next : best;
  for (int i = 0; i < cpus; ++i) if (!chosen || capacity[size_t(i)] == chosen) CPU_SET(i, &w.mask);
  w.count = CPU_COUNT(&w.mask);
  w.capacity = chosen;
  return w;
}
const WorkerCores &worker_cores() { static const WorkerCores cores = choose_worker_cores(); return cores; }
/* Each DXVK thread as it starts (ut3_dxvk_set_callbacks_v2's worker entry). */
void worker_enter() {
  const WorkerCores &w = worker_cores();
  if (w.count) sched_setaffinity(0, sizeof w.mask, &w.mask);
}
/* Around the calls that create DXVK's and the driver's threads; the caller's mask comes back. */
struct WorkerScope {
  cpu_set_t saved;
  bool restore = false;
  WorkerScope() {
    const WorkerCores &w = worker_cores();
    if (w.count && !sched_getaffinity(0, sizeof saved, &saved)) restore = !sched_setaffinity(0, sizeof w.mask, &w.mask);
  }
  ~WorkerScope() { if (restore) sched_setaffinity(0, sizeof saved, &saved); }
  WorkerScope(const WorkerScope &) = delete;
  WorkerScope &operator=(const WorkerScope &) = delete;
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

/* The Android WSI lists only its physical mode; legacy H5 needs PC-sized windowed backbuffers too. */
uint32_t adapter_modes(Context &c) {
  auto *d3d = static_cast<IDirect3D9*>(c.self);
  D3DFORMAT format = D3DFORMAT(c.a[1]);
  bool count_only = c.slot == 6;
  if (c.a[0] >= d3d->GetAdapterCount() || (format != D3DFMT_X8R8G8B8 && format != D3DFMT_R5G6B5) ||
      FAILED(d3d->CheckDeviceType(c.a[0], D3DDEVTYPE_HAL, format, format, TRUE)))
    return count_only ? 0 : D3DERR_INVALIDCALL;
  static const uint32_t modes[][2] = {
    {640, 480}, {800, 600}, {1024, 768}, {1152, 864}, {1280, 720}, {1280, 768}, {1280, 800}, {1280, 960},
    {1280, 1024}, {1360, 768}, {1366, 768}, {1440, 900}, {1560, 720}, {1600, 900}, {1600, 1200}, {1680, 1050},
    {1920, 1080}, {2340, 1080},
  };
  uint32_t w, h, rate;
  display_mode(&w, &h, &rate);
  unsigned count = unsigned(sizeof modes / sizeof *modes);
  bool extra = true;
  for (const auto &mode : modes) if (mode[0] == w && mode[1] == h) extra = false;
  if (count_only) return count + unsigned(extra);
  unsigned index = c.a[2];
  if (index >= count + unsigned(extra) || !c.a[3]) return D3DERR_INVALIDCALL;
  *memory<D3DDISPLAYMODE>(c.a[3], 1, true) = {index < count ? modes[index][0] : w,
      index < count ? modes[index][1] : h, rate, format};
  return D3D_OK;
}

RECT aspect_destination(int width, int height, uint32_t logical_width, uint32_t logical_height) {
  double scale = std::min(double(width) / logical_width, double(height) / logical_height);
  int rw = int(std::lround(logical_width * scale)), rh = int(std::lround(logical_height * scale));
  return {LONG((width - rw) / 2), LONG((height - rh) / 2), LONG((width + rw) / 2), LONG((height + rh) / 2)};
}

/* Each device keeps a reference on the Android window it presents into. */
std::map<void*, ANativeWindow*> device_windows;
std::map<void*, std::array<uint32_t, 14>> parameters;
std::map<void*, uint32_t> focus_windows;
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
  HRESULT hr;
  {
    WorkerScope workers;
    hr = static_cast<IDirect3D9*>(c.self)->CreateDevice(c.a[0], D3DDEVTYPE(c.a[1]), next.value, c.a[3], &pp, &device);
  }
  if (SUCCEEDED(hr)) {
    save_parameters(device, c.a[4], pp);
    focus_windows[device] = c.a[2];
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
  HRESULT hr;
  if (device == ring_device()) ring_drop();
  {
    WorkerScope workers;
    hr = device->Reset(&pp);
  }
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
  HRESULT hr;
  {
    WorkerScope workers;
    hr = static_cast<IDirect3DDevice9*>(c.self)->CreateAdditionalSwapChain(&pp, &chain);
  }
  if (SUCCEEDED(hr)) { save_parameters(chain, c.a[0], pp); *out = wrap(chain); }
  return hr;
}

/* DXVK reports each accepted vkQueuePresentKHR (ut3_dxvk_set_callbacks_v2): the 5 s log counts
 * frames that reached the display queue, with the native Present cost on the game thread. */
std::mutex present_metrics_lock;
std::map<const void*, uint64_t> presented_ids;
uint64_t present_frames, sample_frames, sample_calls, sample_draws, sample_cpu, sample_wall;
uint64_t sample_locks, sample_runs, sample_bytes, sample_indices, sample_skipped;
uint64_t sample_rdraws, sample_rsparse, sample_rbytes, sample_rfall;
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
  uint64_t locks = buffer_locks.load(), runs = upload_runs.load(), bytes = upload_bytes.load(), indices = scanned_indices.load(),
           skipped = skipped_scans.load(), rdraws = ring_draws.load(), rsparse = ring_sparse.load(), rbytes = ring_bytes.load(),
           rfall = ring_fallbacks.load();
  sayf("frame %llu: per frame %.0f buffer locks, %.0f page uploads of %.1f KiB, %.0f indices scanned, %.0f clean draws; "
       "ring %.0f draws (%.0f sparse) %.1f KiB, %.0f fallbacks",
       (unsigned long long)present_frames, (locks - sample_locks) / frames, (runs - sample_runs) / frames,
       (bytes - sample_bytes) / frames / 1024.0, (indices - sample_indices) / frames, (skipped - sample_skipped) / frames,
       (rdraws - sample_rdraws) / frames, (rsparse - sample_rsparse) / frames, (rbytes - sample_rbytes) / frames / 1024.0,
       (rfall - sample_rfall) / frames);
  sample_rdraws = rdraws; sample_rsparse = rsparse; sample_rbytes = rbytes; sample_rfall = rfall;
  worker_stats(present_frames, frames);
  sample_time = now; sample_frames = present_frames; sample_calls = calls; sample_draws = draws; sample_cpu = cpu; sample_wall = wall;
  sample_locks = locks; sample_runs = runs; sample_bytes = bytes; sample_indices = indices; sample_skipped = skipped;
  if (slot_stats) {
    struct Top { uint32_t count; unsigned kind, slot; } top[12]{};
    for (unsigned k = 0; k < 18; ++k)
      for (unsigned s = 0; s < 128; ++s) {
        uint32_t now_count = slot_counts[k][s].load(std::memory_order_relaxed), delta = now_count - slot_seen[k][s];
        slot_seen[k][s] = now_count;
        for (unsigned i = 0; i < 12; ++i)
          if (delta > top[i].count) { for (unsigned j = 11; j > i; --j) top[j] = top[j - 1]; top[i] = {delta, k, s}; break; }
      }
    char text[480];
    uint64_t addrefs = addref_calls.load(), releases = release_calls.load();
    int used = snprintf(text, sizeof text, "busiest calls per frame: AddRef=%.0f Release=%.0f",
                        (addrefs - addref_seen) / frames, (releases - release_seen) / frames);
    addref_seen = addrefs; release_seen = releases;
    for (const Top &entry : top)
      if (entry.count && used < int(sizeof text) - 24)
        used += snprintf(text + used, sizeof text - size_t(used), " %u/%u=%.0f", entry.kind, entry.slot, entry.count / frames);
    say(text);
  }
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
uint32_t present(Context &c, const RECT *const *rects = nullptr) {
  if (c.a[3]) return D3DERR_INVALIDCALL; /* No nested Windows region bridge. */
  WindowLease current;
  if (!current.value) { host->window_ack(current.serial); return D3D_OK; } /* surface lost after the host's wait: skip this frame */
  IDirect3DDevice9 *owned = nullptr, *device = context_device(c, &owned);
  if (!device) return D3DERR_INVALIDCALL;
  /* HoMM5 names its own HWND on every frame; only that guest window maps to this Android surface. */
  auto target = parameters.find(c.self);
  if (target == parameters.end()) target = parameters.find(device);
  if (c.a[2] && c.a[2] != focus_windows[device] &&
      (target == parameters.end() || c.a[2] != target->second[7])) {
    if (owned) owned->Release();
    return D3DERR_INVALIDCALL;
  }
  keep_window(device, current);
  ANativeWindow *window = device_windows[device];
  if (owned) owned->Release();
  const RECT *src = rects ? rects[0] : memory<const RECT>(c.a[0]), *dst = rects ? rects[1] : memory<const RECT>(c.a[1]);
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
void forget_up_bindings(bool indexed);
uint32_t draw_up(Context &c, bool indexed) {
  forget_up_bindings(indexed);
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
  uint8_t *host = nullptr;   /* the guest copy, checked once when it is allocated */
  std::vector<uint8_t> dirty;
  uint32_t dirty_count = 0;
  bool discard = false, overwrite = false, vertex = true;
};
/* Elements of an unordered_map keep their address until erased: bindings cache them. */
std::unordered_map<void*, Shadow> shadows;
struct StreamBinding { void *buffer; uint32_t offset, stride; Shadow *shadow; };
StreamBinding streams[16];
uint32_t stream_freq[16];
void *bound_indices;
Shadow *bound_index_shadow;

void shadow_dirty(Shadow &s, uint32_t lo, uint32_t hi) {
  if (lo >= hi) return;
  for (uint32_t page = lo / kShadowPage, last = (hi - 1) / kShadowPage; page <= last; ++page)
    if (!s.dirty[page]) { s.dirty[page] = 1; ++s.dirty_count; }
}

/* The dirty pages of [lo, hi) to the native buffer, in runs of consecutive pages. */
void shadow_upload(void *buffer, Shadow &s, uint32_t lo, uint32_t hi) {
  if (!s.dirty_count || !s.host) return;
  hi = std::min(hi, s.size);
  if (lo >= hi) return;
  const uint8_t *source = s.host;
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
    bump(upload_runs);
    bump<uint64_t>(upload_bytes, to - from);
    s.discard = s.overwrite = false;
  }
}

Shadow *shadow_of(void *buffer) {
  auto it = shadows.find(buffer);
  return it == shadows.end() ? nullptr : &it->second;
}

/* DrawPrimitive (81: type, start vertex, count) and DrawIndexedPrimitive (82: type, base vertex,
 * min index, vertices, start index, count): upload what the draw reads from each bound stream.
 * A draw whose bound buffers have no dirty page costs only these checks; the indices are read
 * for the actual vertex range only when a vertex stream has dirty pages. */
void upload_for_draw(unsigned slot, const uint32_t *args) {
  bool indexed = slot == 82, instanced = false, vertex_dirty = false;
  Shadow *ib = indexed ? bound_index_shadow : nullptr;
  for (const StreamBinding &stream : streams) if (stream.shadow && stream.shadow->dirty_count) { vertex_dirty = true; break; }
  if (!vertex_dirty && !(ib && ib->dirty_count)) { bump(skipped_scans); return; }
  for (uint32_t freq : stream_freq) if (freq > 1) instanced = true;
  int64_t first = 0, last = -1;   /* vertex numbers, inclusive */
  if (!indexed) {
    first = args[1];
    last = first + int64_t(vertex_count(args[0], args[2])) - 1;
  } else {
    uint64_t count = vertex_count(args[0], args[5]), start = args[4];
    if (ib && ib->index_bytes) {
      uint64_t lo = start * ib->index_bytes, hi = (start + count) * ib->index_bytes;
      shadow_upload(bound_indices, *ib, uint32_t(std::min<uint64_t>(lo, ib->size)), uint32_t(std::min<uint64_t>(hi, ib->size)));
      if (!vertex_dirty) return;
      /* The actual vertex range: MinVertexIndex/NumVertices are hints some games get wrong. */
      if (hi <= ib->size && count) {
        const uint8_t *data = ib->host + lo;
        uint32_t low = UINT32_MAX, high = 0;
        if (ib->index_bytes == 2) {
          const uint16_t *index = reinterpret_cast<const uint16_t*>(data);
          uint16_t l = 0xFFFF, h = 0;
          for (uint64_t i = 0; i < count; ++i) { l = std::min(l, index[i]); h = std::max(h, index[i]); }
          low = l; high = h;
        } else for (uint64_t i = 0; i < count; ++i) { uint32_t v = reinterpret_cast<const uint32_t*>(data)[i]; low = std::min(low, v); high = std::max(high, v); }
        bump<uint64_t>(scanned_indices, count);
        first = int64_t(int32_t(args[1])) + low;
        last = int64_t(int32_t(args[1])) + high;
      }
    }
    if (last < first) { first = int64_t(int32_t(args[1])) + args[2]; last = first + int64_t(args[3]) - 1; }
  }
  for (const StreamBinding &stream : streams) {
    Shadow *vb = stream.shadow;
    if (!vb || !vb->dirty_count) continue;
    if (instanced || !stream.stride || first < 0) { shadow_upload(stream.buffer, *vb, 0, vb->size); continue; }
    uint64_t lo = uint64_t(stream.offset) + uint64_t(first) * stream.stride, hi = uint64_t(stream.offset) + uint64_t(last + 1) * stream.stride;
    shadow_upload(stream.buffer, *vb, uint32_t(std::min<uint64_t>(lo, vb->size)), uint32_t(std::min<uint64_t>(hi, vb->size)));
  }
}

/* SetStreamSource / SetIndices, and a shadow that comes or goes while bound. */
void bind_stream(uint32_t index, void *buffer, uint32_t offset, uint32_t stride) {
  streams[index] = {buffer, offset, stride, buffer ? shadow_of(buffer) : nullptr};
}
void bind_indices(void *buffer) {
  bound_indices = buffer;
  bound_index_shadow = buffer ? shadow_of(buffer) : nullptr;
}
void rebind_shadow(void *buffer, Shadow *shadow) {
  for (StreamBinding &stream : streams) if (stream.buffer == buffer) stream.shadow = shadow;
  if (bound_indices == buffer) bound_index_shadow = shadow;
}

void forget_buffer(void *buffer) {
  auto it = shadows.find(buffer);
  if (it == shadows.end()) return;
  if (it->second.guest) host->guest_free(it->second.guest);
  shadows.erase(it);
  for (StreamBinding &stream : streams) if (stream.buffer == buffer) stream = {};
  if (bound_indices == buffer) { bound_indices = nullptr; bound_index_shadow = nullptr; }
}

uint32_t buffer_lock(Context &c, bool unlock) {
  if (unlock) return shadows.count(c.self) ? D3D_OK : D3DERR_INVALIDCALL;
  bump(buffer_locks);
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
    s.host = memory<uint8_t>(s.guest, total, true);
    memset(s.host, 0, total);
    s.size = total; s.index_bytes = index_bytes; s.vertex = vertex;
    s.dirty.assign((total + kShadowPage - 1) / kShadowPage, 0);
    rebind_shadow(c.self, &s);
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

/* ----------------------------------------------------------- streaming ring
 * The engine's pooled vertex buffers are locked whole (0, 0, NOOVERWRITE) hundreds of times a frame
 * to change a few suballocations, so their shadows stay dirty: page uploads into the native
 * buffers moved 60+ MiB a frame on the far map view (2026-11-14). As the GLES renderer does
 * (d3d9_gl.c, draw_sparse_prepare), a draw whose vertex streams have dirty pages in the range it
 * reads instead takes its own copy from a dynamic ring: the exact vertex range [first, last], or,
 * when the indices touch few vertices of a wide range, only those vertices with indices remapped
 * into a ring index buffer. The guest's buffers stay dirty (a later draw copies what it reads);
 * clean streams are rebound at the copied range's first vertex; the guest's bindings come back
 * after the draw. Instanced draws, strides of zero and anything out of range keep the page
 * uploads above. */
bool recording_state;   /* BeginStateBlock..EndStateBlock: bindings would be recorded, not applied */
constexpr uint32_t kRingBytes = 16u << 20, kRingIndexBytes = 2u << 20, kSparseMaxIndices = 1u << 16;
struct RingBuffers {
  IDirect3DDevice9 *device = nullptr;
  IDirect3DVertexBuffer9 *vb = nullptr;
  IDirect3DIndexBuffer9 *ib[2] = {nullptr, nullptr};   /* 16- and 32-bit indices */
  uint32_t at = 0, ib_at[2] = {0, 0};
  bool failed = false;
} ring;

IDirect3DDevice9 *ring_device() { return ring.device; }
uint32_t ring_refs() { return uint32_t(ring.vb != nullptr) + uint32_t(ring.ib[0] != nullptr) + uint32_t(ring.ib[1] != nullptr); }
void ring_drop() {
  if (ring.vb) ring.vb->Release();
  for (auto *&ib : ring.ib) if (ib) { ib->Release(); ib = nullptr; }
  ring = RingBuffers{};
}

bool ring_ready(IDirect3DDevice9 *device) {
  if (ring.device == device && ring.vb) return true;
  if (ring.failed && ring.device == device) return false;
  ring_drop();
  ring.device = device;
  HRESULT hr = device->CreateVertexBuffer(kRingBytes, D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY, 0, D3DPOOL_DEFAULT, &ring.vb, nullptr);
  if (FAILED(hr) || !ring.vb) { ring.vb = nullptr; ring.failed = true; sayf("stream ring unavailable %08X", unsigned(hr)); return false; }
  ring.at = kRingBytes;   /* the first lock discards */
  ring.ib_at[0] = ring.ib_at[1] = kRingIndexBytes;
  return true;
}

/* Space in the ring: NOOVERWRITE behind the last allocation, DISCARD (DXVK renames) on wrapping. */
uint8_t *ring_lock(uint32_t bytes, uint32_t *offset) {
  if (bytes > kRingBytes) return nullptr;
  uint32_t at = (ring.at + 15u) & ~15u;
  DWORD flags = D3DLOCK_NOOVERWRITE;
  if (at > kRingBytes || bytes > kRingBytes - at) { at = 0; flags = D3DLOCK_DISCARD; }
  void *data = nullptr;
  if (FAILED(ring.vb->Lock(at, bytes, &data, flags)) || !data) return nullptr;
  ring.at = at + bytes;
  *offset = at;
  return static_cast<uint8_t*>(data);
}

IDirect3DIndexBuffer9 *ring_indices(unsigned wide, uint32_t count, const void *indices, uint32_t *start) {
  uint32_t unit = wide ? 4u : 2u, bytes = count * unit;
  if (bytes > kRingIndexBytes) return nullptr;
  auto *&ib = ring.ib[wide];
  if (!ib && FAILED(ring.device->CreateIndexBuffer(kRingIndexBytes, D3DUSAGE_DYNAMIC | D3DUSAGE_WRITEONLY,
                                                   wide ? D3DFMT_INDEX32 : D3DFMT_INDEX16, D3DPOOL_DEFAULT, &ib, nullptr))) {
    ib = nullptr;
    return nullptr;
  }
  uint32_t at = (ring.ib_at[wide] + 15u) & ~15u;
  DWORD flags = D3DLOCK_NOOVERWRITE;
  if (at > kRingIndexBytes || bytes > kRingIndexBytes - at) { at = 0; flags = D3DLOCK_DISCARD; }
  void *data = nullptr;
  if (FAILED(ib->Lock(at, bytes, &data, flags)) || !data) return nullptr;
  memcpy(data, indices, bytes);
  ib->Unlock();
  ring.ib_at[wide] = at + bytes;
  *start = at / unit;
  return ib;
}

bool shadow_range_dirty(const Shadow &s, uint64_t lo, uint64_t hi) {
  if (!s.dirty_count || lo >= hi) return false;
  for (uint64_t page = lo / kShadowPage, last = (hi - 1) / kShadowPage; page <= last; ++page)
    if (s.dirty[size_t(page)]) return true;
  return false;
}

/* The unique vertices of the indices (in first-use order) and the indices remapped to them, in the
 * index buffer's width: a slot per vertex of the draw's range [low, high], stamped with the draw's
 * number, so no table is cleared between draws (a hash table cleared per draw was 11% of the game's
 * thread on the far map view, 2026-11-14). */
constexpr uint32_t kSparseMaxSpan = 1u << 20;
std::vector<uint32_t> sparse_vertices, sparse_remap32, sparse_stamp, sparse_dense;
std::vector<uint16_t> sparse_remap16;
uint32_t sparse_generation;
template<class Index> uint32_t sparse_gather(const Index *index, uint32_t count, uint32_t low, Index *remap) {
  uint32_t found = 0, generation = sparse_generation;
  uint32_t *stamp = sparse_stamp.data(), *dense = sparse_dense.data(), *vertices = sparse_vertices.data();
  for (uint32_t i = 0; i < count; ++i) {
    uint32_t at = uint32_t(index[i]) - low;
    if (stamp[at] != generation) { stamp[at] = generation; dense[at] = found; vertices[found++] = index[i]; }
    remap[i] = Index(dense[at]);
  }
  return found;
}
bool sparse_indices(const uint8_t *data, unsigned unit, uint32_t count, uint32_t low, uint32_t high, uint32_t *unique) {
  uint64_t span = uint64_t(high) - low + 1u;
  if (high < low || span > kSparseMaxSpan) return false;
  if (sparse_stamp.size() < span) { sparse_stamp.resize(size_t(span), 0u); sparse_dense.resize(size_t(span)); }
  if (++sparse_generation == 0) { std::fill(sparse_stamp.begin(), sparse_stamp.end(), 0u); sparse_generation = 1; }
  if (sparse_vertices.size() < count) sparse_vertices.resize(count);
  if (unit == 2) {
    if (sparse_remap16.size() < count) sparse_remap16.resize(count);
    *unique = sparse_gather(reinterpret_cast<const uint16_t*>(data), count, low, sparse_remap16.data());
  } else {
    if (sparse_remap32.size() < count) sparse_remap32.resize(count);
    *unique = sparse_gather(reinterpret_cast<const uint32_t*>(data), count, low, sparse_remap32.data());
  }
  return true;
}

/* The draw through the ring (true: issued, *result its HRESULT); false: the caller uploads pages.
 * Vertex streams with dirty pages in the draw's vertex range take a copy (exact range, or sparse);
 * a dirty index range is copied too, so neither buffer is uploaded page by page for the draw. */
bool ring_draw(IDirect3DDevice9 *device, unsigned slot, const uint32_t *args, uint32_t *result) {
  bool indexed = slot == 82;
  if (recording_state) return false;
  for (uint32_t freq : stream_freq) if (freq > 1) return false;
  Shadow *ib = indexed ? bound_index_shadow : nullptr;
  bool any_vertex = false;
  for (const StreamBinding &stream : streams) if (stream.shadow && stream.shadow->dirty_count) { any_vertex = true; break; }
  bool any_index = ib && ib->dirty_count;
  if (!any_vertex && !any_index) return false;
  uint64_t count = vertex_count(args[0], indexed ? args[5] : args[2]);
  if (!count) return false;
  const uint8_t *index_data = nullptr;
  unsigned unit = 0;
  int64_t base = indexed ? int64_t(int32_t(args[1])) : 0;
  bool index_dirty = false;
  if (indexed) {
    if (!ib || !ib->index_bytes) return false;
    unit = ib->index_bytes;
    uint64_t lo = uint64_t(args[4]) * unit, hi = lo + count * unit;
    if (hi > ib->size) return false;
    index_data = ib->host + lo;
    index_dirty = any_index && shadow_range_dirty(*ib, lo, hi);
  }
  /* The vertex range, read from the indices only when a stream may need a copy. */
  int64_t first = 0, last = -1;
  uint32_t low = 0, high = 0;
  if (any_vertex) {
    if (indexed) {
      uint32_t l = UINT32_MAX, h = 0;
      if (unit == 2) {
        const uint16_t *index = reinterpret_cast<const uint16_t*>(index_data);
        uint16_t a = 0xFFFF, b = 0;
        for (uint64_t i = 0; i < count; ++i) { a = std::min(a, index[i]); b = std::max(b, index[i]); }
        l = a; h = b;
      } else for (uint64_t i = 0; i < count; ++i) { uint32_t v; memcpy(&v, index_data + i * 4, 4); l = std::min(l, v); h = std::max(h, v); }
      bump<uint64_t>(scanned_indices, count);
      low = l; high = h;
      first = base + l; last = base + h;
    } else {
      first = args[1];
      last = first + int64_t(count) - 1;
    }
    if (first < 0 || last < first || last >= int64_t(UINT32_MAX)) return false;
  }
  /* Which bound streams the draw copies. */
  struct Plan { bool bound, copy; uint32_t bytes, at; };
  Plan plan[16]{};
  bool vertex_dirty = false;
  if (any_vertex)
    for (unsigned i = 0; i < 16; ++i) {
      const StreamBinding &stream = streams[i];
      if (!stream.buffer) continue;
      if (!stream.stride || !stream.shadow) return false;
      uint64_t lo = uint64_t(stream.offset) + uint64_t(first) * stream.stride, hi = uint64_t(stream.offset) + uint64_t(last + 1) * stream.stride;
      if (hi > stream.shadow->size) return false;
      plan[i].bound = true;
      if (shadow_range_dirty(*stream.shadow, lo, hi)) { plan[i].copy = true; vertex_dirty = true; }
    }
  if (!vertex_dirty && !index_dirty) return false;
  if (!ring_ready(device)) return false;
  uint64_t span = vertex_dirty ? uint64_t(last - first + 1) : 0;
  /* Sparse: the indices touch few vertices of a wide range; every stream is gathered then. */
  uint32_t unique = 0;
  bool sparse = vertex_dirty && indexed && count <= kSparseMaxIndices && span > count * 2u &&
                sparse_indices(index_data, unit, uint32_t(count), low, high, &unique);
  uint32_t total = 0;
  if (vertex_dirty)
    for (unsigned i = 0; i < 16; ++i) {
      if (!plan[i].bound) continue;
      if (sparse) plan[i].copy = true;
      else if (!plan[i].copy && ((streams[i].offset + uint64_t(first) * streams[i].stride) & 3u)) plan[i].copy = true;
      if (!plan[i].copy) continue;
      total = (total + 15u) & ~15u;
      plan[i].at = total;
      plan[i].bytes = streams[i].stride * (sparse ? unique : uint32_t(span));
      if (uint64_t(total) + plan[i].bytes > kRingBytes) return false;
      total += plan[i].bytes;
    }
  uint32_t ring_offset = 0;
  if (total) {
    uint8_t *out = ring_lock(total, &ring_offset);
    if (!out) { bump(ring_fallbacks); return false; }
    for (unsigned i = 0; i < 16; ++i) {
      if (!plan[i].copy) continue;
      const StreamBinding &stream = streams[i];
      const uint8_t *source = stream.shadow->host + stream.offset;
      uint8_t *to = out + plan[i].at;
      uint32_t stride = stream.stride;
      if (!sparse) memcpy(to, source + size_t(first) * stride, size_t(span) * stride);
      else
        for (uint32_t v = 0; v < unique; ++v)
          memcpy(to + size_t(v) * stride, source + size_t(base + int64_t(sparse_vertices[v])) * stride, stride);
    }
    ring.vb->Unlock();
  }
  /* Indices: remapped (sparse) or copied (dirty range) through the ring index buffer. */
  uint32_t ring_start = 0;
  IDirect3DIndexBuffer9 *indices = nullptr;
  if (sparse || index_dirty) {
    const void *source = sparse ? (unit == 2 ? static_cast<const void*>(sparse_remap16.data()) : sparse_remap32.data()) : index_data;
    indices = ring_indices(unit == 4 ? 1u : 0u, uint32_t(count), source, &ring_start);
    if (!indices) { bump(ring_fallbacks); return false; }
  }
  bump(ring_draws);
  bump<uint64_t>(ring_bytes, total + (indices ? uint32_t(count) * unit : 0u));
  if (sparse) bump(ring_sparse);
  if (vertex_dirty)
    for (unsigned i = 0; i < 16; ++i) {
      if (!plan[i].bound) continue;
      const StreamBinding &stream = streams[i];
      if (plan[i].copy) device->SetStreamSource(i, ring.vb, ring_offset + plan[i].at, stream.stride);
      else device->SetStreamSource(i, static_cast<IDirect3DVertexBuffer9*>(stream.buffer), stream.offset + uint32_t(first) * stream.stride, stream.stride);
    }
  if (indices) device->SetIndices(indices);
  HRESULT hr;
  uint32_t start_index = indices ? ring_start : args[4];
  if (!indexed) hr = device->DrawPrimitive(D3DPRIMITIVETYPE(args[0]), vertex_dirty ? 0 : args[1], args[2]);
  else if (sparse) hr = device->DrawIndexedPrimitive(D3DPRIMITIVETYPE(args[0]), 0, 0, unique, start_index, args[5]);
  else if (vertex_dirty) hr = device->DrawIndexedPrimitive(D3DPRIMITIVETYPE(args[0]), INT(base - first), low, high - low + 1u, start_index, args[5]);
  else hr = device->DrawIndexedPrimitive(D3DPRIMITIVETYPE(args[0]), INT(args[1]), args[2], args[3], start_index, args[5]);
  if (vertex_dirty)
    for (unsigned i = 0; i < 16; ++i)
      if (plan[i].bound) device->SetStreamSource(i, static_cast<IDirect3DVertexBuffer9*>(streams[i].buffer), streams[i].offset, streams[i].stride);
  if (indices) device->SetIndices(static_cast<IDirect3DIndexBuffer9*>(bound_indices));
  *result = uint32_t(hr);
  return true;
}

void forget_up_bindings(bool indexed) {
  streams[0] = {};
  if (indexed) { bound_indices = nullptr; bound_index_shadow = nullptr; }
}

/* ------------------------------------------------------------ the D3D9 worker
 * DXVK's D3D9 front end, the uploads and copies above and this bridge's dispatch cost the game's
 * thread a quarter more time per frame than the OpenGL ES renderer's recording does (simpleperf,
 * far map view, 2026-11-14). As d3d9_thread.c does for OpenGL ES, the game's thread now hands the
 * device's state changes, draws, query issues, releases and presents to one worker ("dxvk-d3d9", on
 * the cores of DXVK's own threads) in order and returns D3D_OK; their pointer arguments are copied
 * into the record. Every other call (creation, Get*, GetData, texture and surface locks, D3DX
 * services) first waits until the worker has run everything queued, then runs on the game's
 * thread as before, so DXVK never runs on two threads at once. Vertex and index buffer locks stay
 * on the game's thread: they hand out the guest copy and queue its dirty range for the worker; a
 * DISCARD lock while a queued draw may still read the copy gives the guest a fresh copy (the old one
 * is freed once the worker is past it), a lock without DISCARD or NOOVERWRITE waits until the worker
 * is past the queued draws that read the buffer.
 * The game runs at most one frame ahead of the worker (as with the GLES render thread).
 * VOID_DXVK_ASYNC=0 (dxvk.env) keeps every call on the game's thread. */
enum : uint16_t { OP_SKIP, OP_DEVICE, OP_RELEASE, OP_ISSUE, OP_CONSTANTS, OP_PRESENT, OP_CREATE, OP_DIRTY, OP_RENAME,
                  OP_APPLY, OP_CAPTURE };
struct Record {
  uint32_t bytes, count;        /* record and payload size */
  uint16_t op, slot;
  uint32_t kind;
  void *native, *object[2];
  uint32_t a[14];
};
constexpr uint32_t kQueueBytes = 16u << 20;
struct Worker {
  bool enabled = false;
  std::vector<uint8_t> ring;
  std::atomic<uint64_t> head{0}, tail{0};       /* bytes written / consumed */
  std::atomic<uint64_t> queued{0}, done{0};      /* records */
  std::atomic<int> sleeping{0}, waiting{0};
  std::mutex lock;
  std::condition_variable wake_worker, wake_game;
  uint64_t last_present = 0;
  std::thread thread;
} worker;
std::atomic<uint64_t> worker_waits_ns{}, worker_busy_ns{}, worker_syncs{};
/* The call the game's thread is in when it waits for the worker: kind * 128 + slot of op_call, or
 * 18 * 128 + n for the D3DX services (1..11) and releases (12); waits and their time per call. */
constexpr unsigned kCauses = 19 * 128;
std::atomic<unsigned> wait_cause{0};
std::atomic<uint32_t> cause_waits[kCauses];
std::atomic<uint64_t> cause_wait_ns[kCauses];
std::atomic<uint64_t> buffer_renames{}, renamed_bytes{};
/* Game-side buffer locks by flags, the plain ones that waited, and event polls that waited. */
std::atomic<uint64_t> locks_discard{}, locks_nooverwrite{}, locks_plain{}, locks_readonly{}, plain_waits{}, poll_waits{};
std::atomic<uint64_t> event_answers{}, event_pending{};   /* event GetData answered complete / pending */
/* The 5 s line's worker part (presented(), DXVK's presenter thread). */
void worker_stats(uint64_t present_frames, double frames) {
  if (!worker.enabled) return;
  static uint64_t seen_waits, seen_busy, seen_records, seen_syncs;
  uint64_t waits = worker_waits_ns.load(), busy = worker_busy_ns.load(), records = worker.queued.load(std::memory_order_relaxed), syncs = worker_syncs.load();
  static uint64_t seen_renames, seen_renamed;
  uint64_t renames = buffer_renames.load(), renamed = renamed_bytes.load();
  sayf("frame %llu: per frame D3D9 worker %.2f ms busy, %.0f records, game waits %.2f ms (%.1f syncs), %.1f buffer renames of %.0f KiB",
       (unsigned long long)present_frames, (busy - seen_busy) / frames / 1e6, (records - seen_records) / frames,
       (waits - seen_waits) / frames / 1e6, (syncs - seen_syncs) / frames, (renames - seen_renames) / frames,
       (renamed - seen_renamed) / frames / 1024.0);
  seen_waits = waits; seen_busy = busy; seen_records = records; seen_syncs = syncs; seen_renames = renames; seen_renamed = renamed;
  static uint64_t seen_d, seen_no, seen_plain, seen_ro, seen_pw, seen_poll;
  uint64_t d = locks_discard.load(), no = locks_nooverwrite.load(), plain = locks_plain.load(), ro = locks_readonly.load(),
           pw = plain_waits.load(), poll = poll_waits.load();
  static uint64_t seen_answers, seen_pending_answers;
  uint64_t answers = event_answers.load(), pending_answers = event_pending.load();
  sayf("frame %llu: per frame buffer locks DISCARD %.1f, NOOVERWRITE %.1f, plain %.1f (%.1f waited), READONLY %.1f; "
       "event polls that waited %.1f; events answered %.1f complete, %.1f pending", (unsigned long long)present_frames,
       (d - seen_d) / frames, (no - seen_no) / frames, (plain - seen_plain) / frames, (pw - seen_pw) / frames, (ro - seen_ro) / frames,
       (poll - seen_poll) / frames, (answers - seen_answers) / frames, (pending_answers - seen_pending_answers) / frames);
  seen_answers = answers; seen_pending_answers = pending_answers;
  seen_d = d; seen_no = no; seen_plain = plain; seen_ro = ro; seen_pw = pw; seen_poll = poll;
  static uint32_t seen_cause_waits[kCauses];
  static uint64_t seen_cause_ns[kCauses];
  struct Top { double ms, count; unsigned cause; } top[5]{};
  for (unsigned i = 0; i < kCauses; ++i) {
    uint32_t count = cause_waits[i].load(std::memory_order_relaxed);
    uint64_t ns = cause_wait_ns[i].load(std::memory_order_relaxed);
    double ms = double(ns - seen_cause_ns[i]) / frames / 1e6, per_frame = double(count - seen_cause_waits[i]) / frames;
    seen_cause_waits[i] = count; seen_cause_ns[i] = ns;
    for (unsigned j = 0; j < 5 && ms > 0; ++j)
      if (ms > top[j].ms) { for (unsigned k = 4; k > j; --k) top[k] = top[k - 1]; top[j] = {ms, per_frame, i}; break; }
  }
  char text[400];
  int used = snprintf(text, sizeof text, "frame %llu: game waits by call (kind/slot, waits, ms per frame):", (unsigned long long)present_frames);
  for (const Top &entry : top)
    if (entry.ms > 0 && used > 0 && used < int(sizeof text) - 40)
      used += snprintf(text + used, sizeof text - size_t(used), " %u/%u %.1f %.2f", entry.cause / 128, entry.cause % 128, entry.count, entry.ms);
  say(text);
}

/* Game side: each buffer's guest copy (the worker's Shadow is its own), copies retired by a
 * rename or a release, and buffers the worker saw released (their copies go back on this thread). */
struct GameBuffer { uint32_t guest = 0, size = 0, index_bytes = 0; bool vertex = true; std::vector<uint32_t> spare;
                    uint64_t read_at = 0; };   /* the last queued draw that may read the guest copy */
std::unordered_map<void*, GameBuffer> game_buffers;
/* The buffers the game has bound, as its queued draws will find them: SetStreamSource and SetIndices
 * outside state block recording, the unbinding of UP draws, a state block's Apply read back from
 * the device. A lock renames past or waits for the queued draws that read its buffer only;
 * VOID_DXVK_READS=0 counts all queued work as a reader (the first version). */
struct GameBindings { void *streams[16]; void *indices; } game_bound{};
bool track_reads = true;
void mark_reads(uint64_t record, bool indexed) {
  auto mark = [record](void *buffer) {
    auto it = game_buffers.find(buffer);
    if (it != game_buffers.end()) it->second.read_at = record;
  };
  for (void *buffer : game_bound.streams) if (buffer) mark(buffer);
  if (indexed && game_bound.indices) mark(game_bound.indices);
}
/* Event queries (HoMM5 paces its frames with one): the game's GetData answers from what the worker
 * published, without waiting for the work queued since the Issue. Game thread: which queries are
 * events (asked once) and each event's newest Issue record; worker: the newest executed Issue of each
 * pending event, polled after a Present, every 64 records and while idle, and published complete. */
struct EventProxy { uint64_t issued = 0; std::atomic<uint64_t> signaled{0}; };
std::unordered_map<void*, EventProxy*> event_proxies;     /* game thread; nullptr: not an event */
struct PendingEvent { void *query; EventProxy *proxy; uint64_t record; };
std::vector<PendingEvent> pending_events;                 /* worker thread */
std::vector<void*> worker_events;                         /* worker thread: queries it issued as events */
std::vector<void*> released_events;                       /* worker -> game (released_lock) */
uint64_t executing_record;                                /* worker thread */
bool proxy_events = true;

/* Worker: poll the pending events; a completed (or failed) one publishes its Issue's record. */
void poll_events() {
  for (size_t i = 0; i < pending_events.size();) {
    PendingEvent &e = pending_events[i];
    BOOL value = FALSE;
    HRESULT hr = static_cast<IDirect3DQuery9*>(e.query)->GetData(&value, sizeof value, D3DGETDATA_FLUSH);
    if (hr == S_FALSE) { ++i; continue; }
    e.proxy->signaled.store(e.record, std::memory_order_release);
    pending_events[i] = pending_events.back();
    pending_events.pop_back();
  }
}

/* After a state block's Apply, with the worker idle: the device's bindings become the game's. */
void game_bindings_refresh(IDirect3DDevice9 *d) {
  for (unsigned i = 0; i < 16; ++i) {
    IDirect3DVertexBuffer9 *b = nullptr; UINT offset = 0, stride = 0;
    game_bound.streams[i] = SUCCEEDED(d->GetStreamSource(i, &b, &offset, &stride)) ? b : nullptr;
    if (b) b->Release();
  }
  IDirect3DIndexBuffer9 *ib = nullptr;
  game_bound.indices = SUCCEEDED(d->GetIndices(&ib)) ? ib : nullptr;
  if (ib) ib->Release();
}
struct Retired { void *buffer; uint32_t guest; uint64_t after; };
std::vector<Retired> retired;
std::mutex released_lock;
std::vector<std::pair<void*, uint32_t>> released;   /* buffer, guest copy */
std::atomic<bool> released_pending{false};

void worker_main();
void worker_start() {
  const char *setting = getenv("VOID_DXVK_ASYNC");
  if (worker.enabled || (setting && *setting == '0')) return;
  worker.ring.assign(kQueueBytes, 0);
  worker.enabled = true;
  const char *reads = getenv("VOID_DXVK_READS");
  track_reads = !(reads && *reads == '0');
  const char *events = getenv("VOID_DXVK_EVENTS");
  proxy_events = !(events && *events == '0');
  worker.thread = std::thread(worker_main);
  worker.thread.detach();
  sayf("D3D9 worker started: state changes, draws and presents run on dxvk-d3d9; buffer locks wait for %s",
       track_reads ? "the queued draws that read the buffer" : "all queued work");
  if (!proxy_events) say("D3D9 worker: event queries answered by DXVK after a drain (VOID_DXVK_EVENTS=0)");
}

inline void pause() { __asm__ volatile("yield" ::: "memory"); }
template<class Ready> void wait_game(Ready ready) {
  if (ready()) return;
  uint64_t start = clock_ns(CLOCK_MONOTONIC);
  for (int spin = 0; spin < 2000 && !ready(); ++spin) pause();
  if (!ready()) {
    std::unique_lock<std::mutex> guard(worker.lock);
    worker.waiting.store(1);
    while (!ready()) worker.wake_game.wait_for(guard, std::chrono::microseconds(500));
    worker.waiting.store(0);
  }
  uint64_t waited = clock_ns(CLOCK_MONOTONIC) - start;
  worker_waits_ns.fetch_add(waited, std::memory_order_relaxed);
  unsigned cause = wait_cause.load(std::memory_order_relaxed);
  if (cause >= kCauses) cause = 0;
  cause_waits[cause].fetch_add(1, std::memory_order_relaxed);
  cause_wait_ns[cause].fetch_add(waited, std::memory_order_relaxed);
}

/* Copies the worker has gone past, and the guest copies of buffers it released. */
void collect() {
  if (!retired.empty()) {
    uint64_t done = worker.done.load(std::memory_order_acquire);
    size_t kept = 0;
    for (const Retired &r : retired) {
      if (r.after > done) { retired[kept++] = r; continue; }
      /* A copy the worker is past is the buffer's next fresh copy (no allocation, pages already in). */
      auto it = game_buffers.find(r.buffer);
      if (it != game_buffers.end() && it->second.spare.size() < 2) it->second.spare.push_back(r.guest);
      else host->guest_free(r.guest);
    }
    retired.resize(kept);
  }
  if (!released_pending.load(std::memory_order_acquire)) return;
  std::vector<std::pair<void*, uint32_t>> gone;
  std::vector<void*> gone_events;
  { std::lock_guard<std::mutex> guard(released_lock); gone.swap(released); gone_events.swap(released_events);
    released_pending.store(false, std::memory_order_release); }
  for (void *query : gone_events) {
    auto it = event_proxies.find(query);
    if (it != event_proxies.end()) { delete it->second; event_proxies.erase(it); }
  }
  for (auto &entry : gone) {
    auto it = game_buffers.find(entry.first);
    if (it != game_buffers.end() && it->second.guest == entry.second) {
      for (uint32_t spare : it->second.spare) host->guest_free(spare);
      game_buffers.erase(it);
    }
    host->guest_free(entry.second);
  }
}

/* Everything queued has run; DXVK may be called on this thread until the next record. */
void drain() {
  if (!worker.enabled) return;
  uint64_t target = worker.queued.load(std::memory_order_relaxed);
  if (worker.done.load(std::memory_order_acquire) != target) {
    bump(worker_syncs);
    wait_game([target] { return worker.done.load(std::memory_order_acquire) >= target; });
  }
  collect();
}

Record *reserve(uint32_t payload) {
  uint32_t bytes = (uint32_t(sizeof(Record)) + payload + 15u) & ~15u;
  if (bytes > kQueueBytes / 4) return nullptr;
  uint64_t head = worker.head.load(std::memory_order_relaxed);
  uint32_t at = uint32_t(head % kQueueBytes);
  if (kQueueBytes - at < bytes) {
    /* Pad to the end of the ring; records never wrap. */
    uint32_t pad = kQueueBytes - at;
    wait_game([head, pad] { return head + pad - worker.tail.load(std::memory_order_acquire) <= kQueueBytes; });
    Record *skip = reinterpret_cast<Record*>(worker.ring.data() + at);
    skip->bytes = pad; skip->op = OP_SKIP;
    head += pad;
    worker.head.store(head, std::memory_order_release);
    at = 0;
  }
  wait_game([head, bytes] { return head + bytes - worker.tail.load(std::memory_order_acquire) <= kQueueBytes; });
  Record *r = reinterpret_cast<Record*>(worker.ring.data() + at);
  memset(r, 0, sizeof(Record));
  r->bytes = bytes; r->count = payload;
  return r;
}
uint8_t *payload_of(Record *r) { return reinterpret_cast<uint8_t*>(r) + sizeof(Record); }

void commit(Record *r) {
  worker.queued.store(worker.queued.load(std::memory_order_relaxed) + 1, std::memory_order_relaxed);   /* one producer */
  worker.head.store(worker.head.load(std::memory_order_relaxed) + r->bytes);   /* seq_cst: against the sleep flag */
  if (worker.sleeping.load()) { std::lock_guard<std::mutex> guard(worker.lock); worker.wake_worker.notify_one(); }
}

/* Game: the proxy of an event query (nullptr for other types); the type is asked once, drained. */
EventProxy *event_proxy(void *query) {
  auto it = event_proxies.find(query);
  if (it != event_proxies.end()) return it->second;
  drain();
  EventProxy *proxy = static_cast<IDirect3DQuery9*>(query)->GetType() == D3DQUERYTYPE_EVENT ? new EventProxy : nullptr;
  event_proxies.emplace(query, proxy);
  return proxy;
}

/* Game: Issue for the worker; an event's END becomes the Issue its GetData waits for. */
void event_issue(void *query, uint32_t flags) {
  EventProxy *proxy = proxy_events ? event_proxy(query) : nullptr;
  Record *r = reserve(0);
  r->op = OP_ISSUE; r->native = query; r->a[0] = flags; r->object[0] = proxy;
  commit(r);
  if (proxy && (flags & D3DISSUE_END)) proxy->issued = worker.queued.load(std::memory_order_relaxed);
}

/* Game: GetData of an issued event from the worker's answer; UINT32_MAX: ask DXVK (drained). */
uint32_t event_get_data(void *query, const uint32_t *args) {
  if (!proxy_events) return UINT32_MAX;
  auto it = event_proxies.find(query);
  if (it == event_proxies.end() || !it->second || !it->second->issued || (args[0] && args[1] < sizeof(BOOL))) return UINT32_MAX;
  EventProxy *proxy = it->second;
  if (proxy->signaled.load(std::memory_order_acquire) < proxy->issued) {
    bump(event_pending);
    return S_FALSE;
  }
  bump(event_answers);
  if (args[0]) *memory<BOOL>(args[0], 1, true) = TRUE;
  return D3D_OK;
}

/* Game: TestCooperativeLevel (HoMM5 asks once a frame). DXVK changes a device's lost state only in
 * Reset, which runs on this thread after a drain, and on a window focus loss Android never reports
 * to it; so the answer read after the last Reset or CreateDevice (cleared there) holds, without
 * waiting for the worker. */
std::unordered_map<void*, uint32_t> coop_states;
uint32_t coop_level(void *native) {
  auto known = coop_states.find(native);
  if (known != coop_states.end()) return known->second;
  drain();
  uint32_t state = uint32_t(static_cast<IDirect3DDevice9*>(native)->TestCooperativeLevel());
  coop_states[native] = state;
  return state;
}

/* Game: calls DXVK answers from state the worker never changes, so they need no wait for it: a
 * texture's level surfaces exist from its creation (GetSurfaceLevel / GetCubeMapSurface hand out a
 * reference to one; DXVK's reference counts are atomic) and the device's available memory is an
 * atomic estimate (GetAvailableTextureMem). Heroes V 1.6 asked for level surfaces four times a frame
 * in its busiest view (2 ms of waiting a frame, 2026-11-15). */
bool drain_free(Kind kind, unsigned slot) {
  return ((kind == Kind::IDirect3DTexture9 || kind == Kind::IDirect3DCubeTexture9) && slot == 18) ||
         (kind == Kind::IDirect3DDevice9 && slot == 4);
}

/* --- worker side */
void execute_device(Record *r) {
  auto *d = static_cast<IDirect3DDevice9*>(r->native);
  const uint32_t *a = r->a;
  const uint8_t *data = payload_of(r);
  auto *texture = static_cast<IDirect3DBaseTexture9*>(r->object[0]);
  switch (r->slot) {
    case 34: d->StretchRect(static_cast<IDirect3DSurface9*>(r->object[0]), a[1] ? reinterpret_cast<const RECT*>(data) : nullptr,
                            static_cast<IDirect3DSurface9*>(r->object[1]), a[3] ? reinterpret_cast<const RECT*>(data + 16) : nullptr,
                            D3DTEXTUREFILTERTYPE(a[4])); break;
    case 35: d->ColorFill(static_cast<IDirect3DSurface9*>(r->object[0]), a[1] ? reinterpret_cast<const RECT*>(data) : nullptr, D3DCOLOR(a[2])); break;
    case 37: d->SetRenderTarget(a[0], static_cast<IDirect3DSurface9*>(r->object[0])); break;
    case 39: d->SetDepthStencilSurface(static_cast<IDirect3DSurface9*>(r->object[0])); break;
    case 41: d->BeginScene(); break;
    case 42: d->EndScene(); break;
    case 43: { float z; memcpy(&z, &a[4], 4);
               d->Clear(a[0], a[1] ? reinterpret_cast<const D3DRECT*>(data) : nullptr, a[2], D3DCOLOR(a[3]), z, a[5]); break; }
    case 44: d->SetTransform(D3DTRANSFORMSTATETYPE(a[0]), reinterpret_cast<const D3DMATRIX*>(data)); break;
    case 47: d->SetViewport(reinterpret_cast<const D3DVIEWPORT9*>(data)); break;
    case 49: d->SetMaterial(reinterpret_cast<const D3DMATERIAL9*>(data)); break;
    case 51: d->SetLight(a[0], reinterpret_cast<const D3DLIGHT9*>(data)); break;
    case 53: d->LightEnable(a[0], BOOL(a[1])); break;
    case 55: d->SetClipPlane(a[0], reinterpret_cast<const float*>(data)); break;
    case 57: d->SetRenderState(D3DRENDERSTATETYPE(a[0]), a[1]); break;
    case 65: d->SetTexture(a[0], texture); break;
    case 67: d->SetTextureStageState(a[0], D3DTEXTURESTAGESTATETYPE(a[1]), a[2]); break;
    case 69: d->SetSamplerState(a[0], D3DSAMPLERSTATETYPE(a[1]), a[2]); break;
    case 75: d->SetScissorRect(reinterpret_cast<const RECT*>(data)); break;
    case 81: case 82: {
      uint32_t result;
      if (!ring_draw(d, r->slot, a, &result)) {
        upload_for_draw(r->slot, a);
        if (r->slot == 81) d->DrawPrimitive(D3DPRIMITIVETYPE(a[0]), a[1], a[2]);
        else d->DrawIndexedPrimitive(D3DPRIMITIVETYPE(a[0]), INT(a[1]), a[2], a[3], a[4], a[5]);
      }
      break;
    }
    case 83: forget_up_bindings(false); d->DrawPrimitiveUP(D3DPRIMITIVETYPE(a[0]), a[1], data, a[3]); break;
    case 84: forget_up_bindings(true);
             d->DrawIndexedPrimitiveUP(D3DPRIMITIVETYPE(a[0]), a[1], a[2], a[3], data, D3DFORMAT(a[5]), data + a[6], a[7]); break;
    case 87: d->SetVertexDeclaration(static_cast<IDirect3DVertexDeclaration9*>(r->object[0])); break;
    case 89: d->SetFVF(a[0]); break;
    case 92: d->SetVertexShader(static_cast<IDirect3DVertexShader9*>(r->object[0])); break;
    case 94: d->SetVertexShaderConstantF(a[0], reinterpret_cast<const float*>(data), a[2]); break;
    case 96: d->SetVertexShaderConstantI(a[0], reinterpret_cast<const int*>(data), a[2]); break;
    case 98: d->SetVertexShaderConstantB(a[0], reinterpret_cast<const BOOL*>(data), a[2]); break;
    case 100: bind_stream(a[0], r->object[0], a[2], a[3]);
              d->SetStreamSource(a[0], static_cast<IDirect3DVertexBuffer9*>(r->object[0]), a[2], a[3]); break;
    case 102: stream_freq[a[0]] = a[1] & 0x3FFFFFFFu; d->SetStreamSourceFreq(a[0], a[1]); break;
    case 104: bind_indices(r->object[0]); d->SetIndices(static_cast<IDirect3DIndexBuffer9*>(r->object[0])); break;
    case 107: d->SetPixelShader(static_cast<IDirect3DPixelShader9*>(r->object[0])); break;
    case 109: d->SetPixelShaderConstantF(a[0], reinterpret_cast<const float*>(data), a[2]); break;
    case 111: d->SetPixelShaderConstantI(a[0], reinterpret_cast<const int*>(data), a[2]); break;
    case 113: d->SetPixelShaderConstantB(a[0], reinterpret_cast<const BOOL*>(data), a[2]); break;
    default: { static unsigned warned; if (warned++ < 10) sayf("D3D9 worker: no executor for slot %u", r->slot); break; }
  }
}

/* After a state block's Apply the device's streams and indices are whatever it held. */
void refresh_bindings(IDirect3DDevice9 *d) {
  for (unsigned i = 0; i < 16; ++i) {
    IDirect3DVertexBuffer9 *b = nullptr; UINT offset = 0, stride = 0;
    if (SUCCEEDED(d->GetStreamSource(i, &b, &offset, &stride))) { bind_stream(i, b, offset, stride); if (b) b->Release(); }
    UINT freq = 1;
    if (SUCCEEDED(d->GetStreamSourceFreq(i, &freq))) stream_freq[i] = freq & 0x3FFFFFFFu;
  }
  IDirect3DIndexBuffer9 *ib = nullptr;
  if (SUCCEEDED(d->GetIndices(&ib))) { bind_indices(ib); if (ib) ib->Release(); }
}

uint32_t op_release_now(void *p);
void execute(Record *r) {
  try {
    switch (r->op) {
      case OP_DEVICE: execute_device(r); break;
      case OP_RELEASE: op_release_now(r->native); break;
      case OP_ISSUE: {
        static_cast<IDirect3DQuery9*>(r->native)->Issue(r->a[0]);
        auto *proxy = static_cast<EventProxy*>(r->object[0]);
        if (!proxy || !(r->a[0] & D3DISSUE_END)) break;
        bool found = false;
        for (PendingEvent &e : pending_events) if (e.query == r->native) { e.record = executing_record; found = true; }
        if (!found) pending_events.push_back({r->native, proxy, executing_record});
        if (std::find(worker_events.begin(), worker_events.end(), r->native) == worker_events.end()) worker_events.push_back(r->native);
        break;
      }
      case OP_CONSTANTS: {
        auto *d = static_cast<IDirect3DDevice9*>(r->native);
        const uint8_t *data = payload_of(r);
        bool pixel = r->a[0] != 0;
        switch (r->a[1]) {
          case 0: pixel ? d->SetPixelShaderConstantF(r->a[2], reinterpret_cast<const float*>(data), r->a[3])
                        : d->SetVertexShaderConstantF(r->a[2], reinterpret_cast<const float*>(data), r->a[3]); break;
          case 1: pixel ? d->SetPixelShaderConstantI(r->a[2], reinterpret_cast<const int*>(data), r->a[3])
                        : d->SetVertexShaderConstantI(r->a[2], reinterpret_cast<const int*>(data), r->a[3]); break;
          default: pixel ? d->SetPixelShaderConstantB(r->a[2], reinterpret_cast<const BOOL*>(data), r->a[3])
                         : d->SetVertexShaderConstantB(r->a[2], reinterpret_cast<const BOOL*>(data), r->a[3]); break;
        }
        break;
      }
      case OP_PRESENT: {
        Context c{Kind(r->kind), r->native, r->slot, r->a};
        const uint8_t *data = payload_of(r);
        const RECT *rects[2] = {r->a[0] ? reinterpret_cast<const RECT*>(data) : nullptr, r->a[1] ? reinterpret_cast<const RECT*>(data + 16) : nullptr};
        present(c, rects);
        if (!pending_events.empty()) poll_events();
        break;
      }
      case OP_CREATE: {
        Shadow &s = shadows[r->native];
        s.guest = r->a[0]; s.size = r->a[1]; s.index_bytes = r->a[2]; s.vertex = r->a[3] != 0;
        s.host = static_cast<uint8_t*>(r->object[0]);
        s.dirty.assign((s.size + kShadowPage - 1) / kShadowPage, 0);
        s.dirty_count = 0;
        rebind_shadow(r->native, &s);
        break;
      }
      case OP_DIRTY: {
        Shadow *s = shadow_of(r->native);
        if (!s) break;
        uint32_t flags = r->a[2];
        if (flags & D3DLOCK_DISCARD) { s->discard = true; shadow_dirty(*s, 0, s->size); }
        else if (!(flags & D3DLOCK_NOOVERWRITE)) s->overwrite = true;
        shadow_dirty(*s, r->a[0], r->a[1]);
        break;
      }
      case OP_RENAME: {
        Shadow *s = shadow_of(r->native);
        if (s) { s->guest = r->a[0]; s->host = static_cast<uint8_t*>(r->object[0]); }
        break;
      }
      case OP_APPLY: static_cast<IDirect3DStateBlock9*>(r->native)->Apply(); refresh_bindings(static_cast<IDirect3DDevice9*>(r->object[0])); break;
      case OP_CAPTURE: static_cast<IDirect3DStateBlock9*>(r->native)->Capture(); break;
      default: break;
    }
  } catch (const std::exception &e) { say(e.what()); }
}

void worker_main() {
  worker_enter();
  pthread_setname_np(pthread_self(), "dxvk-d3d9");
  uint64_t busy_since = 0;   /* when the worker last found work after running dry (0: dry) */
  for (;;) {
    uint64_t tail = worker.tail.load(std::memory_order_relaxed);
    if (worker.head.load() == tail) {
      if (busy_since) { worker_busy_ns.fetch_add(clock_ns(CLOCK_MONOTONIC) - busy_since, std::memory_order_relaxed); busy_since = 0; }
      if (!pending_events.empty()) poll_events();
      for (int spin = 0; spin < 4000 && worker.head.load(std::memory_order_acquire) == tail; ++spin) pause();
      if (worker.head.load() == tail) {
        std::unique_lock<std::mutex> guard(worker.lock);
        worker.sleeping.store(1);
        while (worker.head.load() == tail) {
          /* A pending event is polled every 100 us meanwhile (DXVK only on this thread). */
          worker.wake_worker.wait_for(guard, pending_events.empty() ? std::chrono::microseconds(2000) : std::chrono::microseconds(100));
          if (!pending_events.empty() && worker.head.load() == tail) { guard.unlock(); poll_events(); guard.lock(); }
        }
        worker.sleeping.store(0);
      }
      continue;
    }
    Record *r = reinterpret_cast<Record*>(worker.ring.data() + tail % kQueueBytes);
    if (!busy_since) busy_since = clock_ns(CLOCK_MONOTONIC);
    bool counted = r->op != OP_SKIP;
    if (counted) {
      executing_record = worker.done.load(std::memory_order_relaxed) + 1;
      execute(r);
      if (!pending_events.empty() && !(executing_record & 63)) poll_events();
    }
    worker.tail.store(tail + r->bytes, std::memory_order_release);
    if (counted) worker.done.store(executing_record);   /* seq_cst: against the game's wait flag; one writer */
    if (worker.waiting.load()) { std::lock_guard<std::mutex> guard(worker.lock); worker.wake_game.notify_all(); }
  }
}

/* --- game side */
/* The device calls the worker takes: slot -> payload bytes (-1: not deferred), from the arguments. */
int64_t deferred_payload(unsigned slot, const uint32_t *a) {
  switch (slot) {
    case 37: case 39: case 41: case 42: case 53: case 57: case 65: case 67: case 69: case 81: case 82:
    case 87: case 89: case 92: case 100: case 102: case 104: case 107: return 0;
    case 34: return 32;
    case 35: return 16;
    case 43: return a[1] ? int64_t(a[0]) * 16 : 0;
    case 44: return 64;
    case 47: return 24;
    case 49: return 68;
    case 51: return 104;
    case 55: case 75: return 16;
    case 94: case 96: case 109: case 111: return int64_t(a[2]) * 16;
    case 98: case 113: return int64_t(a[2]) * 4;
    case 83: return int64_t(vertex_count(a[0], a[1])) * a[3];
    case 84: {
      int64_t isize = a[5] == D3DFMT_INDEX16 ? 2 : a[5] == D3DFMT_INDEX32 ? 4 : -1;
      if (isize < 0) return -1;
      return ((int64_t(vertex_count(a[0], a[3])) * isize + 15) & ~int64_t(15)) + (int64_t(a[1]) + a[2]) * a[7];
    }
    default: return -1;
  }
}

/* How many stack arguments a deferred device method has (the thunk's array is exactly that long). */
unsigned deferred_arguments(unsigned slot) {
  switch (slot) {
    case 41: case 42: return 0;
    case 39: case 47: case 49: case 75: case 87: case 89: case 92: case 104: case 107: return 1;
    case 37: case 44: case 51: case 53: case 55: case 57: case 65: case 102: return 2;
    case 35: case 67: case 69: case 81: case 94: case 96: case 98: case 109: case 111: case 113: return 3;
    case 83: case 100: return 4;
    case 34: return 5;
    case 43: case 82: return 6;
    case 84: return 8;
    default: return 0;
  }
}

/* A device call for the worker: arguments by value, pointed-to data copied, objects unwrapped. */
bool defer_device(void *native, unsigned slot, const uint32_t *args) {
  int64_t payload = deferred_payload(slot, args);
  if (payload < 0 || payload > int64_t(kQueueBytes / 8)) return false;
  if ((slot == 100 || slot == 102) && args[0] >= 16) return false;
  if (slot == 102 && (args[1] & 0xC0000000u) && (args[1] & 0x3FFFFFFFu) > 1) return false;   /* instancing: keep it simple */
  Record *r = reserve(uint32_t(payload));
  if (!r) return false;
  r->op = OP_DEVICE; r->slot = uint16_t(slot); r->kind = unsigned(Kind::IDirect3DDevice9); r->native = native;
  memcpy(r->a, args, deferred_arguments(slot) * sizeof *args);
  uint8_t *data = payload_of(r);
  auto copy = [&](uint32_t va, size_t bytes, size_t at) { if (va && bytes) memcpy(data + at, memory<const uint8_t>(va, bytes), bytes); };
  switch (slot) {
    case 34: r->object[0] = host->unwrap_guest(args[0]); r->object[1] = host->unwrap_guest(args[2]);
             copy(args[1], 16, 0); copy(args[3], 16, 16); break;
    case 35: r->object[0] = host->unwrap_guest(args[0]); copy(args[1], 16, 0); break;
    case 37: r->object[0] = host->unwrap_guest(args[1]); break;
    case 39: case 87: case 92: case 107: r->object[0] = host->unwrap_guest(args[0]); break;
    case 104: r->object[0] = host->unwrap_guest(args[0]); break;
    case 65: r->object[0] = host->unwrap_guest(args[1]); break;
    case 100: r->object[0] = host->unwrap_guest(args[1]); break;
    case 43: copy(args[1], size_t(payload), 0); break;
    case 44: case 51: case 55: copy(args[1], size_t(payload), 0); break;
    case 47: case 49: case 75: copy(args[0], size_t(payload), 0); break;
    case 94: case 96: case 98: case 109: case 111: case 113: copy(args[1], size_t(payload), 0); break;
    case 83: copy(args[2], size_t(payload), 0); break;
    case 84: {
      size_t indices = vertex_count(args[0], args[3]) * (args[5] == D3DFMT_INDEX16 ? 2u : 4u);
      size_t aligned = (indices + 15) & ~size_t(15);
      copy(args[4], indices, 0);
      copy(args[6], size_t(payload) - aligned, aligned);
      r->a[6] = uint32_t(aligned);   /* the vertices' offset in the payload */
      break;
    }
    default: break;
  }
  void *object = r->object[0];
  commit(r);
  switch (slot) {
    case 100: if (!recording_state) game_bound.streams[args[0]] = object; break;
    case 104: if (!recording_state) game_bound.indices = object; break;
    case 83: game_bound.streams[0] = nullptr; break;                                  /* D3D9: UP draws unbind */
    case 84: game_bound.streams[0] = nullptr; game_bound.indices = nullptr; break;
    case 81: case 82: mark_reads(worker.queued.load(std::memory_order_relaxed), slot == 82); break;
    default: break;
  }
  return true;
}

uint32_t defer_present(Kind kind, void *native, unsigned slot, const uint32_t *args) {
  if (args[3]) return D3DERR_INVALIDCALL;
  /* At most one frame ahead of the worker. */
  uint64_t previous = worker.last_present;
  if (previous) wait_game([previous] { return worker.done.load(std::memory_order_acquire) >= previous; });
  collect();
  Record *r = reserve(32);
  r->op = OP_PRESENT; r->slot = uint16_t(slot); r->kind = unsigned(kind); r->native = native;
  memcpy(r->a, args, (kind == Kind::IDirect3DSwapChain9 ? 5u : 4u) * sizeof *args);
  uint8_t *data = payload_of(r);
  if (args[0]) memcpy(data, memory<const RECT>(args[0]), 16);
  if (args[1]) memcpy(data + 16, memory<const RECT>(args[1]), 16);
  commit(r);
  worker.last_present = worker.queued.load(std::memory_order_relaxed);
  return D3D_OK;
}

/* Vertex and index buffer Lock on the game's thread (the asynchronous counterpart of buffer_lock). */
uint32_t game_buffer_lock(Context &c, bool unlock) {
  if (unlock) return D3D_OK;
  bump(buffer_locks);
  bool vertex = c.kind == Kind::IDirect3DVertexBuffer9;
  auto *out = memory<uint32_t>(c.a[2], 1, true);
  if (!out) return D3DERR_INVALIDCALL;
  *out = 0;
  collect();
  auto found = game_buffers.find(c.self);
  if (found == game_buffers.end()) {
    drain();
    uint32_t total = 0, index_bytes = 0;
    if (vertex) { D3DVERTEXBUFFER_DESC d; HRESULT hr = static_cast<IDirect3DVertexBuffer9*>(c.self)->GetDesc(&d); if (FAILED(hr)) return hr; total = d.Size; }
    else { D3DINDEXBUFFER_DESC d; HRESULT hr = static_cast<IDirect3DIndexBuffer9*>(c.self)->GetDesc(&d); if (FAILED(hr)) return hr;
           total = d.Size; index_bytes = d.Format == D3DFMT_INDEX32 ? 4 : 2; }
    if (!total) return D3DERR_INVALIDCALL;
    uint32_t guest = host->guest_alloc(total);
    if (!guest) throw std::bad_alloc();
    uint8_t *bytes = memory<uint8_t>(guest, total, true);
    memset(bytes, 0, total);
    found = game_buffers.emplace(c.self, GameBuffer{guest, total, index_bytes, vertex}).first;
    Record *r = reserve(0);
    r->op = OP_CREATE; r->native = c.self; r->object[0] = bytes;
    r->a[0] = guest; r->a[1] = total; r->a[2] = index_bytes; r->a[3] = vertex;
    commit(r);
  }
  GameBuffer &b = found->second;
  uint32_t offset = c.a[0], length = c.a[1] ? c.a[1] : b.size - offset, flags = c.a[3];
  if (offset > b.size || length > b.size - offset) return D3DERR_INVALIDCALL;
  bump(flags & D3DLOCK_READONLY ? locks_readonly : flags & D3DLOCK_DISCARD ? locks_discard
       : flags & D3DLOCK_NOOVERWRITE ? locks_nooverwrite : locks_plain);
  if (!(flags & D3DLOCK_READONLY)) {
    uint64_t reader = track_reads ? b.read_at : worker.queued.load(std::memory_order_relaxed);
    bool pending = worker.done.load(std::memory_order_acquire) < reader;
    if ((flags & D3DLOCK_DISCARD) && pending) {
      /* Queued draws may still read this copy: the guest gets a fresh one. */
      uint32_t guest = 0;
      if (!b.spare.empty()) { guest = b.spare.back(); b.spare.pop_back(); }
      else if (!(guest = host->guest_alloc(b.size))) throw std::bad_alloc();
      retired.push_back({c.self, b.guest, worker.queued.load(std::memory_order_relaxed) + 1});
      bump(buffer_renames);
      bump<uint64_t>(renamed_bytes, b.size);
      b.guest = guest;
      b.read_at = 0;   /* queued draws read the old copy */
      Record *r = reserve(0);
      r->op = OP_RENAME; r->native = c.self; r->a[0] = guest; r->object[0] = memory<uint8_t>(guest, b.size, true);
      commit(r);
    } else if (!(flags & (D3DLOCK_DISCARD | D3DLOCK_NOOVERWRITE)) && pending) {
      /* The guest may overwrite what queued draws read: wait until the worker is past them. */
      bump(plain_waits);
      bump(worker_syncs);
      wait_game([reader] { return worker.done.load(std::memory_order_acquire) >= reader; });
      collect();
    }
    Record *r = reserve(0);
    r->op = OP_DIRTY; r->native = c.self; r->a[0] = offset; r->a[1] = offset + length; r->a[2] = flags;
    commit(r);
  }
  *out = b.guest + offset;
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
      out[0] = p.AdapterOrdinal; out[1] = p.DeviceType; out[2] = focus_windows[c.self]; out[3] = p.BehaviorFlags;
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
uint32_t op_addref(void *p) {
  bump(native_calls);
  if (slot_stats) bump(addref_calls);
  return static_cast<IUnknown*>(p)->AddRef();
}
uint32_t op_release(void *p) {
  bump(native_calls);
  wait_cause.store(18 * 128 + 12, std::memory_order_relaxed);
  if (slot_stats) bump(release_calls);
  if (worker.enabled) {
    Record *r = reserve(0);
    r->op = OP_RELEASE; r->native = p;
    commit(r);
    return 1;   /* the host returns its own count */
  }
  return op_release_now(p);
}
uint32_t op_release_now(void *p) {
  uint32_t refs = static_cast<IUnknown*>(p)->Release();
  if (refs && p == ring_device() && refs <= ring_refs()) {
    ring_drop();
    refs = 0;
  }
  if (!refs) {
    if (worker.enabled) {
      auto event = std::find(worker_events.begin(), worker_events.end(), p);
      if (event != worker_events.end()) {
        worker_events.erase(event);
        pending_events.erase(std::remove_if(pending_events.begin(), pending_events.end(),
                                            [p](const PendingEvent &e) { return e.query == p; }), pending_events.end());
        std::lock_guard<std::mutex> guard(released_lock);
        released_events.push_back(p);
        released_pending.store(true, std::memory_order_release);
      }
      auto it = shadows.find(p);
      if (it != shadows.end() && it->second.guest) {
        std::lock_guard<std::mutex> guard(released_lock);
        released.emplace_back(p, it->second.guest);
        released_pending.store(true, std::memory_order_release);
        it->second.guest = 0;   /* the game's thread frees it */
      }
    }
    forget_buffer(p);
    auto it = device_windows.find(p);
    if (it != device_windows.end()) { if (it->second) ANativeWindow_release(it->second); device_windows.erase(it); }
    parameters.erase(p);
    focus_windows.erase(p);
  }
  return refs;
}
/* The legacy editions' engines run in the app's ":vanilla" and ":hof" processes (AndroidManifest.xml). */
bool legacy_process() {
  char name[128]{};
  FILE *in = fopen("/proc/self/cmdline", "r");
  if (!in) return false;
  size_t length = fread(name, 1, sizeof name - 1, in);
  fclose(in);
  name[length] = 0;   /* the first NUL ends the process name */
  const char *colon = strrchr(name, ':');
  return colon && (!strcmp(colon, ":vanilla") || !strcmp(colon, ":hof"));
}
uint32_t op_create9(uint32_t sdk, const char *library_path, const char *turnip_dir) {
  try {
    WorkerScope workers;
    const WorkerCores &cores = worker_cores();
    if (cores.capacity) sayf("DXVK threads on %d cores of capacity %ld (policy %s)", cores.count, cores.capacity, cores.policy);
    else sayf("DXVK threads on all %d cores (policy %s)", cores.count, cores.policy);
    void *library = dlopen(library_path, RTLD_NOW | RTLD_LOCAL);
    if (!library) { say(dlerror()); return 0; }
    if (turnip_dir) {
      /* Heroes V 1.6 and Hammers of Fate (their engines run in the ":vanilla" and ":hof" processes)
       * render in system memory unless dxvk.env sets TU_DEBUG: with Turnip's tiled (GMEM) passes their
       * battle entry and loading never signalled the frame event (the GPU never finished the frame;
       * Adreno 650, 2026-11-15). Tribes of the East never hung and keeps GMEM: system memory cost it
       * 6-10 % in the adventure map. */
      if (legacy_process() && setenv("TU_DEBUG", "sysmem", 0) == 0) sayf("Turnip: TU_DEBUG=%s", getenv("TU_DEBUG"));
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
    callbacks(display_mode, presented, worker_enter);
    worker_start();
    const char *stats = getenv("VOID_DXVK_STATS");
    slot_stats = stats && *stats == '1';
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
  bump(native_calls);
  wait_cause.store(kind < 19 && slot < 128 ? kind * 128 + slot : 0, std::memory_order_relaxed);
  if (slot_stats && kind < 18 && slot < 128) bump(slot_counts[kind][slot]);
  if (Kind(kind) == Kind::IDirect3DDevice9 && ((slot >= 81 && slot <= 84) || slot == 115 || slot == 116)) bump(draw_calls);
  try {
    if (worker.enabled) {
      Kind k = Kind(kind);
      if (k == Kind::IDirect3DDevice9) {
        if (slot == 17) return defer_present(k, native, slot, args);
        if (slot == 3) return coop_level(native);
        if (slot == 16) coop_states.clear();   /* Reset: asked again afterwards */
        if (defer_device(native, slot, args)) return D3D_OK;
      } else if (k == Kind::IDirect3D9 && slot == 16) {
        coop_states.clear();                   /* CreateDevice */
      } else if (k == Kind::IDirect3DSwapChain9 && slot == 3) {
        return defer_present(k, native, slot, args);
      } else if (k == Kind::IDirect3DQuery9 && slot == 6) {
        event_issue(native, args[0]);
        return D3D_OK;
      } else if (k == Kind::IDirect3DQuery9 && slot == 7) {
        uint32_t answer = event_get_data(native, args);
        if (answer != UINT32_MAX) return answer;
      } else if ((k == Kind::IDirect3DVertexBuffer9 || k == Kind::IDirect3DIndexBuffer9) && (slot == 11 || slot == 12)) {
        Context c{k, native, slot, args};
        return game_buffer_lock(c, slot == 12);
      } else if (k == Kind::IDirect3DStateBlock9 && (slot == 4 || slot == 5)) {
        IDirect3DDevice9 *device = nullptr;
        drain();
        if (FAILED(static_cast<IDirect3DStateBlock9*>(native)->GetDevice(&device)) || !device) return D3DERR_INVALIDCALL;
        device->Release();   /* the device outlives its state blocks */
        Record *r = reserve(0);
        r->op = slot == 5 ? OP_APPLY : OP_CAPTURE; r->native = native; r->object[0] = device;
        commit(r);
        if (slot == 5 && !recording_state) { drain(); game_bindings_refresh(device); }
        return D3D_OK;
      }
      if (k == Kind::IDirect3DQuery9 && slot == 7 &&
          worker.done.load(std::memory_order_acquire) != worker.queued.load(std::memory_order_relaxed))
        bump(poll_waits);
      if (!drain_free(k, slot)) drain();
      if (k == Kind::IDirect3DDevice9 && (slot == 26 || slot == 27)) collect();
    }
    /* A pending occlusion query can be polled thousands of times: no name search for it. HoMM5
       polls its frame event without D3DGETDATA_FLUSH, which a Windows driver submits on its own in
       time; DXVK keeps the event in its unsubmitted command list and the game spins for ever. */
    if (Kind(kind) == Kind::IDirect3DQuery9 && slot == 7)
      return static_cast<IDirect3DQuery9*>(native)->GetData(memory<uint8_t>(args[0], args[1], true), args[1], args[2] | D3DGETDATA_FLUSH);
    /* Buffer Lock/Unlock (many a frame): straight to the shadow, no name search. */
    if ((Kind(kind) == Kind::IDirect3DVertexBuffer9 || Kind(kind) == Kind::IDirect3DIndexBuffer9) && (slot == 11 || slot == 12)) {
      Context c{Kind(kind), native, slot, args};
      return buffer_lock(c, slot == 12);
    }
    if (Kind(kind) == Kind::IDirect3DDevice9) {
      if (slot == 81 || slot == 82) {
        uint32_t result;
        if (ring_draw(static_cast<IDirect3DDevice9*>(native), slot, args, &result)) return result;
        upload_for_draw(slot, args);
      }
      else if (slot == 60) recording_state = true;
      else if (slot == 61) recording_state = false;
      else if (slot == 100 && args[0] < 16) bind_stream(args[0], args[1] ? host->unwrap_guest(args[1]) : nullptr, args[2], args[3]);
      else if (slot == 102 && args[0] < 16) stream_freq[args[0]] = args[1] & 0x3FFFFFFFu;
      else if (slot == 104) bind_indices(args[0] ? host->unwrap_guest(args[0]) : nullptr);
    }
    Context c{Kind(kind), native, slot, args};
    if (c.kind == Kind::IDirect3D9 && (slot == 6 || slot == 7)) return adapter_modes(c);
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
  wait_cause.store(18 * 128 + 1, std::memory_order_relaxed);
  drain();
  *out = nullptr;
  auto *d = static_cast<IDirect3DDevice9*>(device);
  if (cube) { IDirect3DCubeTexture9 *t = nullptr; HRESULT hr = d->CreateCubeTexture(w, levels, usage, D3DFORMAT(format), D3DPOOL(pool), &t, nullptr); *out = t; return hr; }
  IDirect3DTexture9 *t = nullptr; HRESULT hr = d->CreateTexture(w, h, levels, usage, D3DFORMAT(format), D3DPOOL(pool), &t, nullptr); *out = t; return hr;
}
/* Textures arrive as their own interface pointers; both derive singly from IDirect3DBaseTexture9. */
IDirect3DBaseTexture9 *base_texture(void *texture) { return static_cast<IDirect3DBaseTexture9*>(static_cast<IDirect3DTexture9*>(texture)); }
uint32_t op_texture_levels(void *texture) { wait_cause.store(18 * 128 + 2, std::memory_order_relaxed); drain(); return base_texture(texture)->GetLevelCount(); }
void op_generate_mips(void *texture) { wait_cause.store(18 * 128 + 3, std::memory_order_relaxed); drain(); base_texture(texture)->GenerateMipSubLevels(); }
void *op_texture_surface(void *texture, int cube, uint32_t face, uint32_t level) {
  wait_cause.store(18 * 128 + 4, std::memory_order_relaxed);
  drain();
  IDirect3DSurface9 *s = nullptr;
  HRESULT hr = cube ? static_cast<IDirect3DCubeTexture9*>(texture)->GetCubeMapSurface(D3DCUBEMAP_FACES(face), level, &s)
                    : static_cast<IDirect3DTexture9*>(texture)->GetSurfaceLevel(level, &s);
  return SUCCEEDED(hr) ? s : nullptr;
}
int32_t op_surface_desc(void *surface, uint32_t desc[5]) {
  wait_cause.store(18 * 128 + 5, std::memory_order_relaxed);
  drain();
  D3DSURFACE_DESC d{};
  HRESULT hr = static_cast<IDirect3DSurface9*>(surface)->GetDesc(&d);
  if (SUCCEEDED(hr)) { desc[0] = d.Width; desc[1] = d.Height; desc[2] = uint32_t(d.Format); desc[3] = d.Usage; desc[4] = uint32_t(d.Pool); }
  return hr;
}
int32_t op_surface_lock(void *surface, const int32_t *rect, uint32_t flags, void **bits, int32_t *pitch) {
  wait_cause.store(18 * 128 + 6, std::memory_order_relaxed);
  drain();
  RECT r{};
  if (rect) r = {LONG(rect[0]), LONG(rect[1]), LONG(rect[2]), LONG(rect[3])};
  D3DLOCKED_RECT lock{};
  HRESULT hr = static_cast<IDirect3DSurface9*>(surface)->LockRect(&lock, rect ? &r : nullptr, flags);
  *bits = SUCCEEDED(hr) ? lock.pBits : nullptr;
  *pitch = SUCCEEDED(hr) ? lock.Pitch : 0;
  return hr;
}
int32_t op_surface_unlock(void *surface) { wait_cause.store(18 * 128 + 7, std::memory_order_relaxed); drain(); return static_cast<IDirect3DSurface9*>(surface)->UnlockRect(); }
IDirect3DDevice9 *surface_device(void *surface) {
  IDirect3DDevice9 *device = nullptr;
  return SUCCEEDED(static_cast<IDirect3DSurface9*>(surface)->GetDevice(&device)) ? device : nullptr;
}
int32_t op_surface_copy(void *source, const int32_t *sr, void *target, const int32_t *tr, uint32_t filter) {
  wait_cause.store(18 * 128 + 8, std::memory_order_relaxed);
  drain();
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
  wait_cause.store(18 * 128 + 9, std::memory_order_relaxed);
  drain();
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
  wait_cause.store(18 * 128 + 10, std::memory_order_relaxed);
  drain();
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
  bump(native_calls);
  wait_cause.store(18 * 128 + 11, std::memory_order_relaxed);
  if (worker.enabled && count <= 4096) {
    uint32_t bytes = count * (type == 2 ? 4u : 16u);
    Record *r = reserve(bytes);
    if (r) {
      r->op = OP_CONSTANTS; r->native = device; r->a[0] = uint32_t(pixel); r->a[1] = uint32_t(type); r->a[2] = start; r->a[3] = count;
      memcpy(payload_of(r), data, bytes);
      commit(r);
      return D3D_OK;
    }
  }
  drain();
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
