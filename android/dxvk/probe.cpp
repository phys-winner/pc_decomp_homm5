/* The launcher's renderer check, part of libh5dxvk.so: RendererProbe.java calls it in the
 * short-lived process :probe, once for the system Vulkan driver and once (Adreno only) for the
 * app-local Turnip driver, so a driver that crashes takes only that process down. It creates a
 * Vulkan instance, queries the first GPU and reports what DXVK would refuse
 * (vulkan_requirements.h) as key=value lines that RendererPolicy.java turns into the
 * launcher's reasons. No device, surface or swapchain is created. */
#include <jni.h>
#include <dlfcn.h>
#include <cstring>
#include <string>
#include <vector>
#include "turnip.h"
#include "vulkan_requirements.h"

namespace {
std::string version(uint32_t v) {
  return std::to_string(VK_API_VERSION_MAJOR(v)) + "." + std::to_string(VK_API_VERSION_MINOR(v)) + "." + std::to_string(VK_API_VERSION_PATCH(v));
}
std::string hex(uint32_t v) { char text[16]; snprintf(text, sizeof text, "%04x", v); return text; }
/* Values travel as one Modified UTF-8 line each. */
std::string clean(const char *text) {
  std::string out;
  for (const char *p = text; p && *p; ++p) out += (*p >= 0x20 && *p < 0x7f) ? *p : ' ';
  return out;
}
bool has_extension(const std::vector<VkExtensionProperties> &list, const char *name) {
  for (auto &e : list) if (!strcmp(e.extensionName, name)) return true;
  return false;
}

std::string probe(PFN_vkGetInstanceProcAddr gipa, const char *prefix, bool turnip) {
  std::string out;
  auto line = [&](const char *key, const std::string &value) { out += std::string(prefix) + "." + key + "=" + value + "\n"; };
  auto instance_version = reinterpret_cast<PFN_vkEnumerateInstanceVersion>(gipa(nullptr, "vkEnumerateInstanceVersion"));
  auto instance_extensions = reinterpret_cast<PFN_vkEnumerateInstanceExtensionProperties>(gipa(nullptr, "vkEnumerateInstanceExtensionProperties"));
  auto create = reinterpret_cast<PFN_vkCreateInstance>(gipa(nullptr, "vkCreateInstance"));
  if (!instance_extensions || !create) { line("status", "error"); line("error", "incomplete Vulkan loader"); return out; }
  uint32_t loader = VK_API_VERSION_1_0;
  if (instance_version) instance_version(&loader);
  uint32_t count = 0;
  instance_extensions(nullptr, &count, nullptr);
  std::vector<VkExtensionProperties> available(count);
  if (count) instance_extensions(nullptr, &count, available.data());
  available.resize(count);
  homm5_vk_caps caps{};
  caps.android_surface = has_extension(available, VK_KHR_SURFACE_EXTENSION_NAME) && has_extension(available, "VK_KHR_android_surface");
  std::vector<const char*> enabled;
  if (caps.android_surface) { enabled.push_back(VK_KHR_SURFACE_EXTENSION_NAME); enabled.push_back("VK_KHR_android_surface"); }
  VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
  app.pApplicationName = "Heroes V renderer check";
  app.apiVersion = loader >= VK_API_VERSION_1_1 ? VK_API_VERSION_1_3 : VK_API_VERSION_1_0;
  VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
  info.pApplicationInfo = &app;
  info.enabledExtensionCount = uint32_t(enabled.size());
  info.ppEnabledExtensionNames = enabled.data();
  VkInstance instance{};
  VkResult result = create(&info, nullptr, &instance);
  if (result != VK_SUCCESS) { line("status", "error"); line("error", "vkCreateInstance failed " + std::to_string(result)); return out; }
  auto get = [&](const char *name) { return gipa(instance, name); };
  auto destroy = reinterpret_cast<PFN_vkDestroyInstance>(get("vkDestroyInstance"));
  auto enumerate = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(get("vkEnumeratePhysicalDevices"));
  auto properties = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(get("vkGetPhysicalDeviceProperties"));
  auto properties2 = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties2>(get("vkGetPhysicalDeviceProperties2"));
  auto features = reinterpret_cast<PFN_vkGetPhysicalDeviceFeatures>(get("vkGetPhysicalDeviceFeatures"));
  auto features2 = reinterpret_cast<PFN_vkGetPhysicalDeviceFeatures2>(get("vkGetPhysicalDeviceFeatures2"));
  auto device_extensions = reinterpret_cast<PFN_vkEnumerateDeviceExtensionProperties>(get("vkEnumerateDeviceExtensionProperties"));
  auto formats = reinterpret_cast<PFN_vkGetPhysicalDeviceFormatProperties>(get("vkGetPhysicalDeviceFormatProperties"));
  if (app.apiVersion < VK_API_VERSION_1_1) properties2 = nullptr, features2 = nullptr;
  VkPhysicalDevice devices[8];
  count = 8;
  VkPhysicalDevice chosen = VK_NULL_HANDLE;
  VkPhysicalDeviceProperties p{};
  if (enumerate && properties && enumerate(instance, &count, devices) >= VK_SUCCESS)
    for (uint32_t i = 0; i < count && i < 8; ++i) {
      properties(devices[i], &p);
      /* DXVK skips CPU adapters when a GPU exists; a phone has one GPU. */
      if (p.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU || !chosen) chosen = devices[i];
      if (p.deviceType != VK_PHYSICAL_DEVICE_TYPE_CPU) break;
    }
  if (!chosen || !features || !device_extensions || !formats) {
    line("status", "error"); line("error", "no Vulkan GPU");
    if (destroy) destroy(instance, nullptr);
    return out;
  }
  properties(chosen, &p);
  caps.api_version = p.apiVersion;
  count = 0;
  device_extensions(chosen, nullptr, &count, nullptr);
  std::vector<VkExtensionProperties> extensions(count);
  if (count) device_extensions(chosen, nullptr, &count, extensions.data());
  extensions.resize(count);
  caps.swapchain = has_extension(extensions, VK_KHR_SWAPCHAIN_EXTENSION_NAME);
  caps.robustness2 = has_extension(extensions, VK_EXT_ROBUSTNESS_2_EXTENSION_NAME);
  std::string driver;
  if (properties2 && p.apiVersion >= VK_API_VERSION_1_2) {
    VkPhysicalDeviceDriverProperties d{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DRIVER_PROPERTIES};
    VkPhysicalDeviceProperties2 p2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, &d};
    properties2(chosen, &p2);
    driver = clean(d.driverName) + " " + clean(d.driverInfo);
  }
  /* Structures of a version the device lacks must not be chained. */
  VkPhysicalDeviceVulkan12Features v12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
  VkPhysicalDeviceVulkan13Features v13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
  VkPhysicalDeviceRobustness2FeaturesEXT r2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT};
  VkPhysicalDeviceFeatures2 f2{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
  void **next = &f2.pNext;
  if (p.apiVersion >= VK_API_VERSION_1_2) { *next = &v12; next = &v12.pNext; }
  if (p.apiVersion >= VK_API_VERSION_1_3) { *next = &v13; next = &v13.pNext; }
  if (caps.robustness2) { *next = &r2; next = &r2.pNext; }
  if (features2 && p.apiVersion >= VK_API_VERSION_1_1) features2(chosen, &f2);
  else features(chosen, &f2.features);
  caps.core = f2.features;
  caps.sampler_mirror_clamp_to_edge = v12.samplerMirrorClampToEdge; caps.vulkan_memory_model = v12.vulkanMemoryModel;
  caps.host_query_reset = v12.hostQueryReset; caps.timeline_semaphore = v12.timelineSemaphore;
  caps.shader_demote_to_helper_invocation = v13.shaderDemoteToHelperInvocation; caps.synchronization2 = v13.synchronization2;
  caps.dynamic_rendering = v13.dynamicRendering; caps.maintenance4 = v13.maintenance4;
  caps.robust_buffer_access2 = r2.robustBufferAccess2; caps.null_descriptor = r2.nullDescriptor;
  int *bc[3] = {&caps.bc1, &caps.bc2, &caps.bc3};
  const VkFormat bc_formats[3] = {VK_FORMAT_BC1_RGBA_UNORM_BLOCK, VK_FORMAT_BC2_UNORM_BLOCK, VK_FORMAT_BC3_UNORM_BLOCK};
  for (int i = 0; i < 3; ++i) {
    VkFormatProperties fp{};
    formats(chosen, bc_formats[i], &fp);
    *bc[i] = (fp.optimalTilingFeatures & VK_FORMAT_FEATURE_SAMPLED_IMAGE_BIT) != 0;
  }
  char missing[1024];
  int gaps = homm5_vk_missing(&caps, missing, sizeof missing);
  std::string list = missing;
  if (turnip && !(p.vendorID == 0x5143 && strstr(p.deviceName, "Turnip"))) { list += gaps++ ? ",notTurnip" : "notTurnip"; }
  line("status", gaps ? "missing" : "ok");
  line("device", clean(p.deviceName));
  line("vendor", hex(p.vendorID));
  line("deviceId", hex(p.deviceID));
  line("api", version(p.apiVersion));
  line("loader", version(loader));
  if (!driver.empty()) line("driver", driver);
  line("missing", list);
  if (destroy) destroy(instance, nullptr);
  return out;
}
}

/* turnip false: the system driver (libvulkan.so); true: Turnip from the native library directory. */
extern "C" JNIEXPORT jstring JNICALL Java_org_homm5_port_RendererProbe_nativeProbe(JNIEnv *env, jclass, jstring directory, jboolean turnip) {
  std::string report;
  if (!turnip) {
    void *vulkan = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    auto gipa = vulkan ? reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(vulkan, "vkGetInstanceProcAddr")) : nullptr;
    report = gipa ? probe(gipa, "stock", false) : "stock.status=error\nstock.error=no system Vulkan loader\n";
  } else {
    const char *dir = directory ? env->GetStringUTFChars(directory, nullptr) : nullptr;
    char error[512]{};
    auto gipa = homm5_open_turnip(dir, error, sizeof error);
    if (dir) env->ReleaseStringUTFChars(directory, dir);
    report = gipa ? probe(gipa, "turnip", true) : "turnip.status=error\nturnip.error=" + clean(error) + "\n";
  }
  return env->NewStringUTF(report.c_str());
}
