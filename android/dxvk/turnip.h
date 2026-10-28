/* The app-local Mesa Turnip driver through adrenotools (adapted from the sibling ut3 port's
 * turnip.inc). The libraries come from the APK's extracted native library directory
 * (android:extractNativeLibs="true" is what adrenotools requires): its hooks load the driver
 * in a linker namespace of its own, so the system Vulkan driver stays untouched and loaded.
 * The returned loader lives for the process; it is accepted only once it exposes a real
 * Qualcomm Turnip device with Vulkan 1.3, the version DXVK 2.4 needs. */
#pragma once
#include <vulkan/vulkan.h>
#include <dlfcn.h>
#include <cstdio>
#include <cstring>
#include <string>

#define HOMM5_TURNIP_DRIVER "libh5turnip.so"

inline PFN_vkGetInstanceProcAddr homm5_open_turnip(const char *directory, char *error, size_t error_size) {
  if (!directory || !*directory) { snprintf(error, error_size, "Turnip: no native library directory"); return nullptr; }
  static PFN_vkGetInstanceProcAddr opened;
  if (opened) return opened;
  std::string path = std::string(directory) + "/";
  void *helper = dlopen((path + "libadrenotools.so").c_str(), RTLD_NOW | RTLD_LOCAL);
  using Open = void *(*)(int, int, const char *, const char *, const char *, const char *, const char *, void **);
  auto open = helper ? reinterpret_cast<Open>(dlsym(helper, "adrenotools_open_libvulkan")) : nullptr;
  /* 1 = ADRENOTOOLS_DRIVER_CUSTOM; hooks and driver both from nativeLibraryDir; no temporary
   * directory (API 29+ uses memfd), no file redirection, no GPU mapping import. */
  void *loader = open ? open(RTLD_NOW | RTLD_LOCAL, 1, nullptr, path.c_str(), path.c_str(), HOMM5_TURNIP_DRIVER, nullptr, nullptr) : nullptr;
  auto get = loader ? reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(loader, "vkGetInstanceProcAddr")) : nullptr;
  if (!get) {
    const char *detail = dlerror();
    snprintf(error, error_size, "Turnip: adrenotools returned no driver (%s)", detail ? detail : helper ? "no custom driver" : "libadrenotools.so missing");
    return nullptr;
  }
  auto create = reinterpret_cast<PFN_vkCreateInstance>(get(nullptr, "vkCreateInstance"));
  VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};
  app.pApplicationName = "Heroes V driver check";
  app.apiVersion = VK_API_VERSION_1_3;
  VkInstanceCreateInfo info{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};
  info.pApplicationInfo = &app;
  VkInstance instance{};
  VkResult result = create ? create(&info, nullptr, &instance) : VK_ERROR_INITIALIZATION_FAILED;
  if (result != VK_SUCCESS) { snprintf(error, error_size, "Turnip: vkCreateInstance(1.3) failed %d", result); return nullptr; }
  auto enumerate = reinterpret_cast<PFN_vkEnumeratePhysicalDevices>(get(instance, "vkEnumeratePhysicalDevices"));
  auto properties = reinterpret_cast<PFN_vkGetPhysicalDeviceProperties>(get(instance, "vkGetPhysicalDeviceProperties"));
  auto destroy = reinterpret_cast<PFN_vkDestroyInstance>(get(instance, "vkDestroyInstance"));
  bool supported = false;
  uint32_t count = 8;
  VkPhysicalDevice devices[8];
  char seen[VK_MAX_PHYSICAL_DEVICE_NAME_SIZE] = "no device";
  if (enumerate && properties && destroy && enumerate(instance, &count, devices) >= VK_SUCCESS)
    for (unsigned i = 0; i < count && i < 8; ++i) {
      VkPhysicalDeviceProperties p{};
      properties(devices[i], &p);
      snprintf(seen, sizeof seen, "%s", p.deviceName);
      supported |= p.apiVersion >= VK_API_VERSION_1_3 && p.vendorID == 0x5143 && strstr(p.deviceName, "Turnip");
    }
  if (destroy) destroy(instance, nullptr);
  if (!supported) { snprintf(error, error_size, "Turnip: no Qualcomm Vulkan 1.3 Turnip device (%s)", seen); return nullptr; }
  opened = get;
  return get;
}
