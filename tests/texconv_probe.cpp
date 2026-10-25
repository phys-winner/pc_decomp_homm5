// PC driver of android/texconv for tests/test_texconv.py.
//   texconv_probe scan <game>
//   texconv_probe convert <game> etc2|astc [threads]
//   texconv_probe remove-originals <game>
//   texconv_probe remove-converted <game>
//   texconv_probe quality <dds>...        level-0 PSNR and time per format
//   texconv_probe decode <converted.dds> <level> <out.rgba>
#include "../android/texconv/texconv.h"

#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

static std::vector<uint8_t> load(const char *path)
{
    std::vector<uint8_t> data;
    FILE *f = fopen(path, "rb");
    if (!f) return data;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    data.resize(static_cast<size_t>(size));
    if (size && fread(data.data(), 1, data.size(), f) != data.size()) data.clear();
    fclose(f);
    return data;
}

static uint32_t le32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | (static_cast<uint32_t>(p[3]) << 24); }

static int report(int result)
{
    texconv_progress p;
    texconv_get_progress(&p);
    printf("result %d state %d done %lld/%lld bytes %lld/%lld message \"%s\"\n", result, p.state, static_cast<long long>(p.done),
           static_cast<long long>(p.total), static_cast<long long>(p.bytes_done), static_cast<long long>(p.bytes_total), p.message);
    return result == 0 ? 0 : 2;
}

/* PSNR of RGB over all texels and of alpha, against the DXT decode. */
static void psnr(const std::vector<uint8_t> &a, const std::vector<uint8_t> &b, double &rgb, double &alpha)
{
    double se_rgb = 0, se_a = 0;
    size_t n = a.size() / 4;
    for (size_t i = 0; i < n; ++i) {
        for (int c = 0; c < 3; ++c) { double d = double(a[i * 4 + c]) - b[i * 4 + c]; se_rgb += d * d; }
        double d = double(a[i * 4 + 3]) - b[i * 4 + 3];
        se_a += d * d;
    }
    double mse_rgb = se_rgb / (n * 3.0), mse_a = se_a / n;
    rgb = mse_rgb > 0 ? 10 * log10(255.0 * 255.0 / mse_rgb) : 99;
    alpha = mse_a > 0 ? 10 * log10(255.0 * 255.0 / mse_a) : 99;
}

static int quality(int argc, char **argv)
{
    double total_ms[3] = {0, 0, 0};
    long long texels = 0;
    for (int i = 2; i < argc; ++i) {
        std::vector<uint8_t> dds = load(argv[i]);
        if (dds.size() < 128) { printf("skip %s\n", argv[i]); continue; }
        uint32_t height = le32(&dds[12]), width = le32(&dds[16]), fourcc = le32(&dds[84]);
        std::vector<uint8_t> reference(static_cast<size_t>(width) * height * 4);
        if (texconv_decode_dxt(fourcc, &dds[128], width, height, reference.data())) { printf("skip %s\n", argv[i]); continue; }
        texels += static_cast<long long>(width) * height;
        printf("%s %ux%u %.4s", argv[i], width, height, reinterpret_cast<const char *>(&fourcc));
        for (int format = TEXCONV_ETC2; format <= TEXCONV_ASTC; ++format) {
            uint8_t *out = nullptr;
            uint64_t size = 0;
            auto start = std::chrono::steady_clock::now();
            int result = texconv_convert_dds(dds.data(), dds.size(), format, &out, &size);
            if (result) { printf(result > 0 ? " | kept" : " | convert-failed"); continue; }
            double ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
            total_ms[format] += ms;
            std::vector<uint8_t> back(reference.size());
            double rgb = 0, alpha = 0;
            if (texconv_decode_converted(out, size, 0, back.data())) printf(" decode-failed");
            else psnr(reference, back, rgb, alpha);
            printf(" | %s %.4s %.2f dB rgb %.2f dB a %.0f ms %llu bytes", format == TEXCONV_ETC2 ? "etc2" : "astc",
                   reinterpret_cast<const char *>(out + 84), rgb, alpha, ms, static_cast<unsigned long long>(size));
            texconv_free(out);
        }
        printf("\n");
    }
    printf("total %.1f Mtexel: etc2 %.0f ms (%.1f Mtexel/s), astc %.0f ms (%.1f Mtexel/s)\n", texels / 1e6, total_ms[1],
           texels / 1e3 / (total_ms[1] + 1e-9), total_ms[2], texels / 1e3 / (total_ms[2] + 1e-9));
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: see the source\n"); return 1; }
    std::string command = argv[1];
    if (command == "scan") {
        texconv_status s;
        int result = texconv_scan(argv[2], &s);
        printf("scan textures %lld bytes %lld converted %d %lld %lld removed %d removable %lld\n",
               static_cast<long long>(s.textures), static_cast<long long>(s.bytes), s.converted_format,
               static_cast<long long>(s.converted_textures), static_cast<long long>(s.converted_bytes), s.originals_removed,
               static_cast<long long>(s.removable_bytes));
        return report(result);
    }
    if (command == "convert" && argc >= 4) {
        int format = !strcmp(argv[3], "astc") ? TEXCONV_ASTC : !strcmp(argv[3], "etc2") ? TEXCONV_ETC2 : 0;
        return report(texconv_convert(argv[2], format, argc >= 5 ? atoi(argv[4]) : 0));
    }
    if (command == "remove-originals") return report(texconv_remove_originals(argv[2]));
    if (command == "remove-converted") return report(texconv_remove_converted(argv[2]));
    if (command == "quality") return quality(argc, argv);
    if (command == "decode" && argc >= 5) {
        std::vector<uint8_t> dds = load(argv[2]);
        uint32_t height = le32(&dds[12]), width = le32(&dds[16]), level = static_cast<uint32_t>(atoi(argv[3]));
        uint32_t w = width >> level ? width >> level : 1, h = height >> level ? height >> level : 1;
        std::vector<uint8_t> rgba(static_cast<size_t>(w) * h * 4);
        if (texconv_decode_converted(dds.data(), dds.size(), level, rgba.data())) return 3;
        FILE *f = fopen(argv[4], "wb");
        if (!f) return 4;
        fwrite(rgba.data(), 1, rgba.size(), f);
        fclose(f);
        return 0;
    }
    fprintf(stderr, "unknown command\n");
    return 1;
}
