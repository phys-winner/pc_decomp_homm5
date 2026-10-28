"""The DXVK renderer's native boundary: generated tables, the Vulkan requirement check, and strict
NDK compiles of the bridge (android/dxvk) and of the host glue in every edition build."""
import re
import subprocess
import sys
import unittest

from test_static_tls import ROOT, compile_probe

sys.path.insert(0, str(ROOT / "tools"))
import build_android
import generate_dxvk_bridge
from android_tools import TOOLCHAIN
from port_patches import legacy_ui_branch

HEADER = ROOT / "reference/dxvk/include/native/directx/d3d9.h"
VULKAN = TOOLCHAIN / "sysroot/usr/include/vulkan"


class DxvkBridgeTest(unittest.TestCase):
    def test_committed_tables_are_generated_from_the_pinned_header(self):
        if not HEADER.is_file():
            self.skipTest("DXVK headers are not imported (tools/build_dxvk.py)")
        generated, methods = generate_dxvk_bridge.outputs(HEADER)
        for relative, data in generated.items():
            self.assertEqual((ROOT / relative).read_bytes().replace(b"\r\n", b"\n"), data, relative)
        self.assertEqual(sum(len(items) for items in methods.values()), 328)

    def test_host_and_bridge_agree_on_kinds_slots_and_digest(self):
        host = (ROOT / "android/host/dxvk_methods.h").read_text(encoding="utf-8")
        metadata = (ROOT / "android/dxvk/bridge_metadata.h").read_text(encoding="utf-8")
        digest = re.search(r"#define DXVK_SLOTS_DIGEST (0x[0-9A-F]{8})u", host)[1]
        self.assertIn(f"kSlotsDigest = {digest}u", metadata)
        classes = re.findall(r'\{"DXVK::(\w+)", (\d+), dxvk_methods_(\d+), 0\}', host)
        kinds = metadata[metadata.index("enum class Kind : unsigned {") + 28:metadata.index(",Count};")].split(",")
        self.assertEqual([name for name, _, _ in classes], kinds)
        self.assertEqual([int(kind) for _, _, kind in classes], list(range(len(kinds))))
        glue = (ROOT / "android/host/d3d9_dxvk.c").read_text(encoding="utf-8")
        enum = dict(re.findall(r"KIND_(\w+) = (\d+)", glue))
        names = {"D3D9": "IDirect3D9", "DEVICE": "IDirect3DDevice9", "TEXTURE": "IDirect3DTexture9",
                 "CUBE": "IDirect3DCubeTexture9", "SURFACE": "IDirect3DSurface9", "QUERY": "IDirect3DQuery9",
                 "SWAPCHAIN": "IDirect3DSwapChain9"}
        self.assertEqual({key: kinds[int(value)] for key, value in enum.items()}, names)
        # The slots d3d9_dxvk.c hooks: as d3d9.h numbers them, with their stack sizes.
        thunk = lambda kind, slot: re.search(rf"static void dxvk_{kind}_{slot}\(void\) \{{ uint32_t a\[(\d+)\].*?g_esp \+= (\d+)u; \}}", host)
        for kind, slot, popped in ((1, 16, 32), (2, 16, 12), (2, 17, 24), (2, 41, 8), (2, 42, 8), (2, 60, 8), (2, 61, 12),
                                   (17, 3, 28), (16, 7, 20)):
            self.assertEqual(int(thunk(kind, slot)[2]), popped, (kind, slot))

    def test_vulkan_requirements_name_what_dxvk_refuses(self):
        out = ROOT / "build/tests/dxvk-requirements"
        (out / "vulkan").mkdir(parents=True, exist_ok=True)
        for name in ("vulkan_core.h", "vk_platform.h"):
            (out / "vulkan" / name).write_bytes((VULKAN / name).read_bytes())
        (out / "vk_video").mkdir(exist_ok=True)
        for path in (VULKAN.parent / "vk_video").glob("*.h"):
            (out / "vk_video" / path.name).write_bytes(path.read_bytes())
        compile_probe("dxvk-requirements", r'''
#include <assert.h>
#include <stdio.h>
#include "vulkan_requirements.h"
static homm5_vk_caps complete(void) {
    homm5_vk_caps c; memset(&c, 0, sizeof c);
    c.api_version = VK_API_VERSION_1_3; c.swapchain = c.robustness2 = c.android_surface = 1;
    VkBool32 *core = (VkBool32 *)&c.core;
    for (size_t i = 0; i < sizeof c.core / sizeof *core; ++i) core[i] = VK_TRUE;
    c.sampler_mirror_clamp_to_edge = c.vulkan_memory_model = c.host_query_reset = c.timeline_semaphore = VK_TRUE;
    c.shader_demote_to_helper_invocation = c.synchronization2 = c.dynamic_rendering = c.maintenance4 = VK_TRUE;
    c.robust_buffer_access2 = c.null_descriptor = VK_TRUE; c.bc1 = c.bc2 = c.bc3 = 1;
    return c;
}
int main(void) {
    char out[256];
    homm5_vk_caps c = complete();
    assert(homm5_vk_missing(&c, out, sizeof out) == 0 && !out[0]);
    /* The Adreno 650 test phone's system driver: Vulkan 1.1, no robustness2; the 1.2/1.3 structures were not queried. */
    c = complete(); c.api_version = VK_MAKE_API_VERSION(0, 1, 1, 128); c.robustness2 = 0;
    c.vulkan_memory_model = c.synchronization2 = VK_FALSE;
    assert(homm5_vk_missing(&c, out, sizeof out) == 2 && !strcmp(out, "vulkan13,robustness2"));
    /* Without BC formats (Mali) and with a missing D3D9 feature. */
    c = complete(); c.bc2 = 0; c.core.geometryShader = VK_FALSE;
    assert(homm5_vk_missing(&c, out, sizeof out) == 2 && !strcmp(out, "geometryShader,bcTextures"));
    c = complete(); c.null_descriptor = VK_FALSE; c.maintenance4 = VK_FALSE;
    assert(homm5_vk_missing(&c, out, sizeof out) == 2 && !strcmp(out, "nullDescriptor,maintenance4"));
    /* A short buffer keeps counting and stays terminated. */
    c = complete(); c.api_version = VK_API_VERSION_1_0; c.android_surface = c.swapchain = 0;
    assert(homm5_vk_missing(&c, out, 12) == 3 && strlen(out) < 12 && !strncmp(out, "vulkan13,an", 11));
    assert(homm5_vk_missing(&c, out, 0) == 3);
    puts("PASS Vulkan requirements: complete device, Vulkan 1.1 without robustness2, BC and D3D9 features, robustness2 parts, short buffers");
    return 0;
}
''', {"vulkan_requirements.h": (ROOT / "android/dxvk/vulkan_requirements.h").read_text(encoding="utf-8")}, ["/I."])

    def test_bridge_compiles_strictly_for_android(self):
        if not HEADER.is_file():
            self.skipTest("DXVK headers are not imported (tools/build_dxvk.py)")
        import build_dxvk
        out = ROOT / "build/tests/dxvk-bridge"
        out.mkdir(parents=True, exist_ok=True)
        flags = ["--target=" + build_dxvk.TARGET, "-std=c++17", "-O2", "-fPIC", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror",
                 "-Wno-missing-field-initializers", "-Wno-unused-parameter",
                 "-I" + str(ROOT / "reference/dxvk/include/native/windows"), "-I" + str(ROOT / "reference/dxvk/include/native/directx"),
                 "-I" + str(ROOT / "android/dxvk")]
        for source in build_dxvk.BRIDGE_SOURCES:
            result = subprocess.run([str(TOOLCHAIN / "bin/clang++.exe"), *flags, "-c", str(ROOT / source), "-o", str(out / "bridge.o")],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, source + "\n" + result.stderr[-4000:])

    def test_host_glue_compiles_in_every_edition_build(self):
        """ToE with and without the activity; Vanilla through its adapted copy (legacy_ui_branch),
        where none of the DXVK code may remain."""
        out = ROOT / "build/tests/dxvk-host"
        out.mkdir(parents=True, exist_ok=True)
        (out / "modules.inc").write_text("\n")
        for edition in ("toe", "vanilla"):
            header = out / f"edition-{edition}.h"
            header.write_text(f'#define HOMM5_EDITION "{edition}"\n#define HOMM5_BIN "bin"\n#define HOMM5_PROFILE_SUFFIX ""\n'
                              f'#define HOMM5_MODULES_INCLUDE "{(out / "modules.inc").as_posix()}"\n'
                              + ("" if edition == "toe" else "#define HOMM5_LEGACY_UI 1\n"))
            for name in ("d3d9_dxvk.c", "d3d9_device.c", "d3dx9.c", "android_main.c"):
                source, extra = ROOT / "android/host" / name, []
                if edition != "toe":
                    adapted = legacy_ui_branch(source.read_bytes().replace(b"\r\n", b"\n"), True)
                    code = re.sub(rb"/\*.*?\*/|//[^\n]*", b"", adapted, flags=re.S).replace(b'#include "dxvk.h"', b"")
                    self.assertNotIn(b"dxvk", code.lower(), name)
                    source = out / f"{edition}-{name}"
                    source.write_bytes(adapted)
                    extra = ["-I" + str(ROOT / "android/host")]
                for app in ((True, False) if edition == "toe" else (True,)):
                    command = [str(build_android.CLANG), *build_android.HOST_FLAGS, "-include", str(header),
                               *(["-DVOID_ANDROID_APP"] if app else []), *extra, "-Werror", "-c", str(source), "-o", str(out / "host.o")]
                    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, f"{edition} {name} app={app}\n{result.stderr[-4000:]}")


if __name__ == "__main__":
    unittest.main()
