package org.homm5.port;

import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** The renderers of Tribes of the East and why one is or is not available here, from the driver
 *  check's report (RendererProbe; android/dxvk/probe.cpp: "stock.*" for the system Vulkan driver,
 *  "turnip.*" for the app-local Turnip). Plain Java, run on the PC by tests/test_renderers.py.
 *
 *  The best mode follows what the sibling ut3 port verified on devices: Turnip first (on its Adreno
 *  650 the system driver offers only Vulkan 1.1 and Turnip ran DXVK in gameplay; Mesa's Turnip is
 *  the Adreno driver DXVK is routinely run on), then DXVK on the system driver only on Adreno (its
 *  Adreno 735 driver passed the complete DXVK capability audit), else OpenGL ES. On other GPUs the
 *  system-driver DXVK can be chosen by hand but is never picked by itself (ut3 measured ~9 FPS with
 *  it on a PowerVR GPU). */
final class RendererPolicy {
    /** DXVK/Turnip support is commented out (2026-10-29: Turnip stays black after the startup Reset, see
     *  STATE.md): no driver check, no launcher card, no first-start offer, every start renders with
     *  OpenGL ES. With true, the APK needs tools/build_game_apk.py --dxvk and the engine HOMM5_DXVK
     *  (android/host/d3d9_dxvk.c). */
    static final boolean ENABLED = false;
    static final String GLES = "gles", DXVK = "dxvk", TURNIP = "turnip";
    static final String[] MODES = {GLES, DXVK, TURNIP};
    /** Android 11: adrenotools' level, and the persistent SurfaceView lifecycle the DXVK modes present into. */
    static final int MIN_SDK = 30;
    static final int QUALCOMM = 0x5143;
    static final String[] DXVK_LIBRARIES = {"libh5dxvk.so", "libdxvk_d3d9.so", "libc++_shared.so"};
    static final String[] TURNIP_LIBRARIES = {"libadrenotools.so", "libhook_impl.so", "libmain_hook.so",
        "libfile_redirect_hook.so", "libgsl_alloc_hook.so", "libh5turnip.so"};

    private RendererPolicy() { }

    static final class Status {
        final String mode, reason;
        final boolean available;
        Status(String mode, boolean available, String reason) { this.mode = mode; this.available = available; this.reason = reason; }
    }

    static boolean valid(String mode) { return GLES.equals(mode) || DXVK.equals(mode) || TURNIP.equals(mode); }

    /** android/dxvk/bridge_abi.h: HOMM5_RENDERER_GLES / _DXVK / _TURNIP. */
    static final int GLES_NATIVE = 0;
    static int nativeMode(String mode) { return DXVK.equals(mode) ? 1 : TURNIP.equals(mode) ? 2 : GLES_NATIVE; }

    static Map<String, String> parse(String report) {
        Map<String, String> values = new HashMap<>();
        if (report == null) return values;
        for (String line : report.split("\n")) {
            int equals = line.indexOf('=');
            if (equals > 0) values.put(line.substring(0, equals).trim(), line.substring(equals + 1).trim());
        }
        return values;
    }

    static int vendor(Map<String, String> report, String driver) {
        try { return Integer.parseInt(report.getOrDefault(driver + ".vendor", ""), 16); }
        catch (NumberFormatException e) { return 0; }
    }

    /** The Adreno model of the system driver's GPU name ("Adreno (TM) 650" -> 650); 0 if none. */
    static int adreno(Map<String, String> report) {
        if (vendor(report, "stock") != QUALCOMM) return 0;
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("(\\d{3})").matcher(report.getOrDefault("stock.device", ""));
        return m.find() ? Integer.parseInt(m.group(1)) : 0;
    }

    /** report null: the driver check has not finished yet. */
    static Status[] evaluate(int sdk, Set<String> libraries, Map<String, String> report, boolean ru) {
        Status dxvk = vulkan(DXVK, "stock", sdk, libraries, report, ru);
        Status turnip = vulkan(TURNIP, "turnip", sdk, libraries, report, ru);
        return new Status[] {new Status(GLES, true, null), dxvk, turnip};
    }

    private static Status vulkan(String mode, String driver, int sdk, Set<String> libraries, Map<String, String> report, boolean ru) {
        if (sdk < MIN_SDK) return new Status(mode, false, String.format(Locale.ROOT, ru
            ? "нужен Android 11 или новее (здесь API %d)" : "needs Android 11 or newer (this is API %d)", sdk));
        Set<String> missing = new LinkedHashSet<>();
        for (String name : DXVK_LIBRARIES) if (!libraries.contains(name)) missing.add(name);
        if (TURNIP.equals(mode)) for (String name : TURNIP_LIBRARIES) if (!libraries.contains(name)) missing.add(name);
        if (!missing.isEmpty()) return new Status(mode, false, (ru ? "в этой сборке нет библиотек: " : "this build lacks: ")
            + String.join(", ", missing));
        if (report == null) return new Status(mode, false, ru ? "видеодрайвер ещё проверяется…" : "checking the graphics driver…");
        if (TURNIP.equals(mode)) {
            String stockStatus = report.getOrDefault("stock.status", "");
            if (vendor(report, "stock") != QUALCOMM) {
                String gpu = report.getOrDefault("stock.device", "");
                return new Status(mode, false, (ru ? "Turnip работает только на видеочипах Adreno (Qualcomm)" : "Turnip runs on Adreno (Qualcomm) GPUs only")
                    + (gpu.isEmpty() ? (stockStatus.equals("crash") ? "" : ru ? "; видеочип не определён" : "; no GPU found") : (ru ? "; здесь " : "; this is ") + gpu));
            }
            int model = adreno(report);
            if (model < 600 || model >= 800) return new Status(mode, false, String.format(Locale.ROOT, ru
                ? "встроенный Turnip (Mesa 26.0 R8) поддерживает Adreno 6xx и 7xx, здесь Adreno %d"
                : "the bundled Turnip (Mesa 26.0 R8) supports Adreno 6xx and 7xx; this is Adreno %d", model));
        }
        String status = report.getOrDefault(driver + ".status", "");
        if (status.equals("ok")) return new Status(mode, true, null);
        if (status.equals("crash")) return new Status(mode, false, ru ? "проверка драйвера завершилась сбоем" : "the driver check crashed");
        if (status.equals("error")) return new Status(mode, false, (ru ? "Vulkan недоступен: " : "Vulkan is unavailable: ")
            + report.getOrDefault(driver + ".error", "?"));
        if (status.equals("missing")) return new Status(mode, false, reasons(report.getOrDefault(driver + ".missing", ""),
            report.getOrDefault(driver + ".api", "?"), ru));
        return new Status(mode, false, ru ? "драйвер не проверен" : "the driver was not checked");
    }

    /** The probe's missing-requirement tokens (vulkan_requirements.h) as the player reads them. */
    static String reasons(String tokens, String api, boolean ru) {
        Set<String> parts = new LinkedHashSet<>(), features = new LinkedHashSet<>();
        for (String token : tokens.split(",")) {
            switch (token.trim()) {
            case "": break;
            case "vulkan13": parts.add(String.format(Locale.ROOT, ru ? "драйвер даёт Vulkan %s, а DXVK нужен Vulkan 1.3"
                : "the driver offers Vulkan %s; DXVK needs Vulkan 1.3", api)); break;
            case "robustness2": case "robustBufferAccess2": case "nullDescriptor":
                parts.add(ru ? "нет VK_EXT_robustness2 (robustBufferAccess2, nullDescriptor)" : "no VK_EXT_robustness2 (robustBufferAccess2, nullDescriptor)"); break;
            case "bcTextures": parts.add(ru ? "видеочип не читает сжатие BC (DXT), в котором хранятся текстуры игры"
                : "the GPU cannot sample BC (DXT) compression, the format of the game's textures"); break;
            case "swapchain": case "androidSurface": parts.add(ru ? "драйвер не выводит Vulkan на экран Android"
                : "the driver cannot present Vulkan to an Android surface"); break;
            case "notTurnip": parts.add(ru ? "adrenotools загрузил не Turnip" : "adrenotools did not load Turnip"); break;
            default: features.add(token.trim());
            }
        }
        if (!features.isEmpty()) parts.add((ru ? "нет возможностей Vulkan, нужных DXVK: " : "missing Vulkan features DXVK needs: ") + String.join(", ", features));
        return parts.isEmpty() ? (ru ? "драйвер не подходит" : "the driver does not qualify") : String.join("; ", parts);
    }

    static Status status(Status[] statuses, String mode) {
        for (Status s : statuses) if (s.mode.equals(mode)) return s;
        return statuses[0];
    }

    /** The mode a first start picks by itself (see the class comment). */
    /* Not chosen automatically until a mode is seen rendering the game on a device: on the Adreno 650
       test phone (2026-10-29) DXVK on Turnip starts, creates its swap chain and plays the music, but
       after the startup Reset the GPU stays busy, the frame event never completes and the screen
       stays black. Both DXVK modes can still be chosen by hand. */
    static final boolean DXVK_VERIFIED = false;

    static String best(Status[] statuses, Map<String, String> report) {
        if (!DXVK_VERIFIED) return GLES;
        if (status(statuses, TURNIP).available) return TURNIP;
        if (status(statuses, DXVK).available && report != null && vendor(report, "stock") == QUALCOMM) return DXVK;
        return GLES;
    }

    /** A chosen mode this device cannot run any more falls back to OpenGL ES for the start. */
    static String effective(String chosen, Status[] statuses) {
        return valid(chosen) && status(statuses, chosen).available ? chosen : GLES;
    }

    static String title(String mode) {
        return TURNIP.equals(mode) ? "DXVK (Turnip)" : DXVK.equals(mode) ? "DXVK (Vulkan)" : "OpenGL ES";
    }

    static String description(String mode, boolean ru) {
        String experimental = DXVK_VERIFIED ? "" : ru
            ? " Экспериментально: на Adreno 650 пока чёрный экран после запуска; если игра не показывает меню, выберите OpenGL ES."
            : " Experimental: on an Adreno 650 the screen still stays black after the start; if the menu does not appear, choose OpenGL ES.";
        if (TURNIP.equals(mode)) return (ru
            ? "DXVK на драйвере Mesa Turnip из приложения (через adrenotools) вместо системного драйвера Adreno: Vulkan 1.3 даже там, где системный драйвер старше. Только Adreno 6xx/7xx и Android 11+."
            : "DXVK on the Mesa Turnip driver shipped with the app (through adrenotools) instead of the system Adreno driver: Vulkan 1.3 even where the system driver is older. Adreno 6xx/7xx and Android 11+ only.") + experimental;
        if (DXVK.equals(mode)) return (ru
            ? "DXVK 2.4 переводит Direct3D 9 игры в Vulkan на системном драйвере видеочипа. Нужны Android 11+, Vulkan 1.3, VK_EXT_robustness2 и сжатие текстур BC (DXT)."
            : "DXVK 2.4 translates the game's Direct3D 9 to Vulkan on the GPU's system driver. Needs Android 11+, Vulkan 1.3, VK_EXT_robustness2 and BC (DXT) texture compression.") + experimental;
        return ru
            ? "Собственный рендерер порта: Direct3D 9 игры в OpenGL ES 3.2. Работает на любом устройстве; интерфейс при уменьшенном масштабе рендера остаётся чётким, читает сконвертированные текстуры и распаковывает DXT процессором."
            : "The port's own renderer: the game's Direct3D 9 on OpenGL ES 3.2. Works on every device; keeps the interface sharp at a reduced render scale, reads converted textures and unpacks DXT on the processor.";
    }

    /** What the DXVK modes do not have yet (readme.md, "Renderers"). */
    static String limits(boolean ru) {
        return ru
            ? "В режимах DXVK масштаб рендера уменьшает и интерфейс, а сконвертированные текстуры не читаются. Режим применяется при следующем запуске игры."
            : "In the DXVK modes the render scale also lowers the interface, and converted textures cannot be read. A mode applies from the next game start.";
    }
}
