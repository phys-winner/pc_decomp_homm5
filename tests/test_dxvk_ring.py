"""The DXVK bridge's streaming ring (android/dxvk/bridge.cpp, ring_draw): the production functions run
against a fake D3D9 device that fetches vertices as a GPU would. Every draw through the ring must
fetch byte for byte what the guest's draw on its own buffers would, and leave the guest's bindings
in place afterwards."""
import unittest

from test_static_tls import ROOT, compile_probe
from test_dxvk_present import function

HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <algorithm>
#include <atomic>
#include <unordered_map>
#include <vector>
using HRESULT = int32_t; using DWORD = uint32_t; using INT = int32_t; using UINT = uint32_t;
constexpr HRESULT D3D_OK = 0;
#define FAILED(hr) ((hr) < 0)
enum D3DPRIMITIVETYPE { D3DPT_TRIANGLELIST = 4 };
enum D3DFORMAT { D3DFMT_INDEX16 = 101, D3DFMT_INDEX32 = 102 };
enum D3DPOOL { D3DPOOL_DEFAULT = 0 };
enum { D3DUSAGE_DYNAMIC = 0x200, D3DUSAGE_WRITEONLY = 8, D3DLOCK_DISCARD = 0x2000, D3DLOCK_NOOVERWRITE = 0x1000 };
struct Buffer {
  std::vector<uint8_t> data; bool index32 = false; int locks = 0, discards = 0;
  HRESULT Lock(uint32_t offset, uint32_t size, void **out, DWORD flags) {
    assert(offset + size <= data.size()); ++locks; if (flags & D3DLOCK_DISCARD) ++discards;
    *out = data.data() + offset; return D3D_OK;
  }
  HRESULT Unlock() { return D3D_OK; }
  uint32_t Release() { return 0; }
};
struct IDirect3DVertexBuffer9 : Buffer {};
struct IDirect3DIndexBuffer9 : Buffer {};
/* What the draws read: every fetched vertex's bytes of every bound stream, in index order. */
struct Device {
  IDirect3DVertexBuffer9 *stream[16] = {}; uint32_t offset[16] = {}, stride[16] = {};
  IDirect3DIndexBuffer9 *indices = nullptr;
  std::vector<uint8_t> fetched; int draws = 0, sets = 0;
  HRESULT CreateVertexBuffer(uint32_t size, DWORD, DWORD, D3DPOOL, IDirect3DVertexBuffer9 **out, void*) {
    *out = new IDirect3DVertexBuffer9; (*out)->data.resize(size); return D3D_OK;
  }
  HRESULT CreateIndexBuffer(uint32_t size, DWORD, D3DFORMAT format, D3DPOOL, IDirect3DIndexBuffer9 **out, void*) {
    *out = new IDirect3DIndexBuffer9; (*out)->data.resize(size); (*out)->index32 = format == D3DFMT_INDEX32; return D3D_OK;
  }
  HRESULT SetStreamSource(uint32_t i, IDirect3DVertexBuffer9 *b, uint32_t o, uint32_t s) { stream[i] = b; offset[i] = o; stride[i] = s; ++sets; return D3D_OK; }
  HRESULT SetIndices(IDirect3DIndexBuffer9 *b) { indices = b; ++sets; return D3D_OK; }
  void fetch(int64_t vertex) {
    for (int s = 0; s < 16; ++s) if (stream[s]) {
      int64_t at = int64_t(offset[s]) + vertex * stride[s];
      assert(at >= 0 && at + stride[s] <= int64_t(stream[s]->data.size()));
      fetched.insert(fetched.end(), stream[s]->data.begin() + at, stream[s]->data.begin() + at + stride[s]);
    }
  }
  HRESULT DrawPrimitive(D3DPRIMITIVETYPE, uint32_t start, uint32_t triangles) {
    ++draws; for (uint32_t i = 0; i < triangles * 3; ++i) fetch(int64_t(start) + i); return D3D_OK;
  }
  HRESULT DrawIndexedPrimitive(D3DPRIMITIVETYPE, INT base, uint32_t, uint32_t, uint32_t start, uint32_t triangles) {
    ++draws;
    for (uint32_t i = 0; i < triangles * 3; ++i) {
      uint32_t index;
      if (indices->index32) memcpy(&index, indices->data.data() + (start + i) * 4, 4);
      else { uint16_t v; memcpy(&v, indices->data.data() + (start + i) * 2, 2); index = v; }
      fetch(int64_t(base) + index);
    }
    return D3D_OK;
  }
};
using IDirect3DDevice9 = Device;
template<class... A> static void sayf(const char*, A...) {}
static std::atomic<uint64_t> upload_runs, upload_bytes, scanned_indices, ring_draws, ring_sparse, ring_bytes, ring_fallbacks;
template<class T> inline void bump(std::atomic<T> &counter, T by = 1) {   /* as bridge.cpp */
  counter.store(counter.load(std::memory_order_relaxed) + by, std::memory_order_relaxed);
}
constexpr uint32_t kShadowPage = 4096;
struct Shadow {
  uint32_t guest = 0, size = 0, index_bytes = 0; uint8_t *host = nullptr; std::vector<uint8_t> dirty;
  uint32_t dirty_count = 0; bool discard = false, overwrite = false, vertex = true;
};
struct StreamBinding { void *buffer; uint32_t offset, stride; Shadow *shadow; };
static StreamBinding streams[16];
static uint32_t stream_freq[16];
static void *bound_indices;
static Shadow *bound_index_shadow;
static size_t vertex_count(uint32_t type, uint32_t count) { assert(type == 4); return size_t(count) * 3; }
#include "ring.h"

/* A guest buffer: its shadow (all pages dirty) and the stale native copy the device holds. */
struct GuestBuffer {
  Shadow shadow; std::vector<uint8_t> memory; IDirect3DVertexBuffer9 native; IDirect3DIndexBuffer9 native_ib;
  GuestBuffer(uint32_t size, uint32_t seed, uint32_t index_bytes = 0) {
    memory.resize(size);
    for (uint32_t i = 0; i < size; ++i) memory[i] = uint8_t(i * 7u + seed * 13u + (i >> 8));
    shadow.size = size; shadow.host = memory.data(); shadow.index_bytes = index_bytes; shadow.vertex = !index_bytes;
    shadow.dirty.assign((size + kShadowPage - 1) / kShadowPage, uint8_t(1)); shadow.dirty_count = uint32_t(shadow.dirty.size());
    native.data.assign(size, uint8_t(0xEE)); native_ib.data = memory;
  }
  void clean() { std::fill(shadow.dirty.begin(), shadow.dirty.end(), uint8_t(0)); shadow.dirty_count = 0; native.data = memory; native_ib.data = memory; }
};

/* The guest's draw as a D3D9 device would run it on up-to-date buffers. */
static std::vector<uint8_t> expected(GuestBuffer **vb, unsigned streams_bound, GuestBuffer *ib, bool index32, const uint32_t *args, bool indexed) {
  Device reference;
  for (unsigned s = 0; s < streams_bound; ++s) {
    vb[s]->native.data = vb[s]->memory;
    reference.SetStreamSource(s, &vb[s]->native, streams[s].offset, streams[s].stride);
  }
  if (indexed) {
    ib->native_ib.data = ib->memory; ib->native_ib.index32 = index32; reference.SetIndices(&ib->native_ib);
    reference.DrawIndexedPrimitive(D3DPT_TRIANGLELIST, INT(args[1]), args[2], args[3], args[4], args[5]);
  } else reference.DrawPrimitive(D3DPT_TRIANGLELIST, args[1], args[2]);
  return reference.fetched;
}

static void bind(Device &device, GuestBuffer **vb, unsigned count, const uint32_t *offsets, const uint32_t *strides, GuestBuffer *ib) {
  for (unsigned s = 0; s < 16; ++s) streams[s] = {};
  for (unsigned s = 0; s < count; ++s) {
    streams[s] = {&vb[s]->native, offsets[s], strides[s], &vb[s]->shadow};
    device.SetStreamSource(s, &vb[s]->native, offsets[s], strides[s]);
  }
  bound_indices = ib ? &ib->native_ib : nullptr; bound_index_shadow = ib ? &ib->shadow : nullptr;
  device.SetIndices(ib ? &ib->native_ib : nullptr);
}

static void check_restored(Device &device, unsigned count) {
  for (unsigned s = 0; s < count; ++s)
    assert(device.stream[s] == streams[s].buffer && device.offset[s] == streams[s].offset && device.stride[s] == streams[s].stride);
  assert(device.indices == bound_indices);
}

int main() {
  Device device;
  /* 1. Exact range: a dirty pooled stream (stride 32) and a clean static one (stride 8), 16-bit indices. */
  GuestBuffer pool(1u << 20, 1), uvs(1u << 18, 2), ib16(1u << 16, 3, 2);
  uvs.clean();
  uint16_t *index = reinterpret_cast<uint16_t*>(ib16.memory.data());
  for (int i = 0; i < 300; ++i) index[100 + i] = uint16_t(5000 + (i * 37) % 280);
  ib16.clean();
  GuestBuffer *vbs[2] = {&pool, &uvs};
  uint32_t offsets[2] = {64, 0}, strides[2] = {32, 8};
  bind(device, vbs, 2, offsets, strides, &ib16);
  uint32_t args[6] = {4, uint32_t(-4000), 0, 2000, 100, 100};   /* base -4000: vertices 1000..1279 */
  std::vector<uint8_t> want = expected(vbs, 2, &ib16, false, args, true);
  pool.native.data.assign(pool.native.data.size(), uint8_t(0xEE));
  bind(device, vbs, 2, offsets, strides, &ib16);
  device.fetched.clear();
  uint32_t result = 1;
  assert(ring_draw(&device, 82, args, &result) && result == 0);
  assert(device.fetched == want && ring_sparse.load() == 0 && ring_draws.load() == 1);
  check_restored(device, 2);
  assert(pool.shadow.dirty_count == pool.shadow.dirty.size());   /* the guest buffer stays dirty */
  /* 2. Sparse: a wide range with few vertices; 32-bit indices; both streams gathered. */
  GuestBuffer ib32(1u << 16, 4, 4);
  uint32_t *wide = reinterpret_cast<uint32_t*>(ib32.memory.data());
  for (int i = 0; i < 30; ++i) wide[i] = uint32_t((i % 3) * 9000 + i / 3);
  ib32.clean();
  bind(device, vbs, 2, offsets, strides, &ib32);
  uint32_t sparse_args[6] = {4, 10, 0, 30000, 0, 10};
  want = expected(vbs, 2, &ib32, true, sparse_args, true);
  pool.native.data.assign(pool.native.data.size(), uint8_t(0xEE));
  bind(device, vbs, 2, offsets, strides, &ib32);
  device.fetched.clear();
  assert(ring_draw(&device, 82, sparse_args, &result) && result == 0);
  assert(device.fetched == want && ring_sparse.load() == 1);
  check_restored(device, 2);
  /* 3. Non-indexed from a dirty stream. */
  bind(device, vbs, 2, offsets, strides, nullptr);
  uint32_t list_args[3] = {4, 777, 50};
  want = expected(vbs, 2, nullptr, false, list_args, false);
  pool.native.data.assign(pool.native.data.size(), uint8_t(0xEE));
  bind(device, vbs, 2, offsets, strides, nullptr);
  device.fetched.clear();
  assert(ring_draw(&device, 81, list_args, &result) && result == 0 && device.fetched == want);
  check_restored(device, 2);
  /* 4. Clean range of a dirty buffer, instancing, out of range: the page path (false). */
  GuestBuffer partial(1u << 20, 5);
  std::fill(partial.shadow.dirty.begin(), partial.shadow.dirty.end(), uint8_t(0)); partial.shadow.dirty[200] = 1; partial.shadow.dirty_count = 1;
  GuestBuffer *one[1] = {&partial};
  uint32_t one_offset[1] = {0}, one_stride[1] = {16};
  bind(device, one, 1, one_offset, one_stride, nullptr);
  uint32_t clean_args[3] = {4, 0, 10};
  assert(!ring_draw(&device, 81, clean_args, &result));
  stream_freq[1] = 4;
  bind(device, vbs, 2, offsets, strides, &ib16);
  assert(!ring_draw(&device, 82, args, &result));
  stream_freq[1] = 0;
  uint32_t outside[3] = {4, 40000, 100};
  bind(device, vbs, 2, offsets, strides, nullptr);
  assert(!ring_draw(&device, 81, outside, &result));
  /* 5. The ring wraps with DISCARD and keeps answering correctly. */
  int discards = ring.vb->discards;
  for (int round = 0; round < 100; ++round) {
    bind(device, vbs, 2, offsets, strides, &ib16);
    uint32_t big[6] = {4, uint32_t(-4000), 0, 2000, 100, 100};
    want = expected(vbs, 2, &ib16, false, big, true);
    bind(device, vbs, 2, offsets, strides, &ib16);
    device.fetched.clear();
    uint32_t list[3] = {4, uint32_t((round % 40) * 512), 2000};   /* 6000 dirty vertices of 32 bytes a round */
    assert(ring_draw(&device, 81, list, &result));
    device.fetched.clear();
    assert(ring_draw(&device, 82, big, &result) && device.fetched == want);
  }
  assert(ring.vb->discards > discards);
  puts("PASS DXVK ring: exact range with a rebound clean stream, sparse 32-bit gather, non-indexed, page-path cases, DISCARD wrap; bindings restored");
  return 0;
}
'''


class DxvkRingTest(unittest.TestCase):
    def test_ring_draw_fetches_what_the_guest_draw_would(self):
        source = (ROOT / "android/dxvk/bridge.cpp").read_text(encoding="utf-8")
        start = source.index("bool recording_state;")
        end = source.index("void forget_up_bindings(bool indexed) {")
        ring = source[start:end]
        helpers = "\n".join(function(source, name) for name in ("void shadow_upload(",))
        compile_probe("dxvk-ring", HARNESS, {"ring.h": helpers + "\n" + ring}, extra_flags=("/TP", "/EHsc", "/wd4189", "/wd4100"))


if __name__ == "__main__":
    unittest.main()
