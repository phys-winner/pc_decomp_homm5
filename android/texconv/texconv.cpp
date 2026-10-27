/* Texture converter (texconv.h). Portable C++17: built into libtexconv.so for
 * the launcher and natively on the PC for tests (tests/test_texconv.py). */
#include "texconv.h"

#include <zlib.h>

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <condition_variable>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "../../reference/astcenc/astcenc.h"
#include "../../reference/etcpak/Decode.hpp"
#include "../../reference/etcpak/ProcessRGB.hpp"

#ifdef _WIN32
#  define WIN32_LEAN_AND_MEAN
#  include <windows.h>
#  include <direct.h>
#else
#  include <dirent.h>
#  include <fcntl.h>
#  include <sys/stat.h>
#  include <sys/statvfs.h>
#  include <unistd.h>
#endif

namespace {

/* ------------------------------------------------------------- progress */

std::mutex progress_lock;
texconv_progress progress_state;
std::atomic<bool> cancelled{false};
std::atomic<int64_t> done_textures{0}, done_bytes{0};

void set_state(int state)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    progress_state.state = state;
}

int fail(const char *format, ...)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    va_list args;
    va_start(args, format);
    vsnprintf(progress_state.message, sizeof progress_state.message, format, args);
    va_end(args);
    progress_state.state = TEXCONV_FAILED;
    return -1;
}

void begin(int state, int64_t total, int64_t bytes)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    progress_state = texconv_progress{};
    progress_state.state = state;
    progress_state.total = total;
    progress_state.bytes_total = bytes;
    done_textures = 0;
    done_bytes = 0;
}

void set_totals(int64_t total, int64_t bytes)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    progress_state.total = total;
    progress_state.bytes_total = bytes;
}

/* ----------------------------------------------------------------- files */

struct File {
#ifdef _WIN32
    HANDLE handle = INVALID_HANDLE_VALUE;
#else
    int fd = -1;
#endif
    File() = default;
    File(const File &) = delete;
    File &operator=(const File &) = delete;
    ~File() { close(); }

    bool open_read(const std::string &path)
    {
#ifdef _WIN32
        handle = CreateFileA(path.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                             OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        return handle != INVALID_HANDLE_VALUE;
#else
        fd = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
        return fd >= 0;
#endif
    }

    bool create(const std::string &path)
    {
#ifdef _WIN32
        handle = CreateFileA(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        return handle != INVALID_HANDLE_VALUE;
#else
        fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
        return fd >= 0;
#endif
    }

    /* Positional read of exactly `size` bytes (thread-safe). */
    bool read_at(void *buffer, size_t size, uint64_t offset) const
    {
        uint8_t *out = static_cast<uint8_t *>(buffer);
        while (size) {
#ifdef _WIN32
            OVERLAPPED at{};
            at.Offset = static_cast<DWORD>(offset);
            at.OffsetHigh = static_cast<DWORD>(offset >> 32);
            DWORD got = 0, want = size > 0x40000000u ? 0x40000000u : static_cast<DWORD>(size);
            if (!ReadFile(handle, out, want, &got, &at) || !got) return false;
#else
            ssize_t got = ::pread(fd, out, size > 0x40000000u ? 0x40000000u : size, static_cast<off_t>(offset));
            if (got < 0 && errno == EINTR) continue;
            if (got <= 0) return false;
#endif
            out += got;
            size -= static_cast<size_t>(got);
            offset += static_cast<uint64_t>(got);
        }
        return true;
    }

    bool write(const void *buffer, size_t size)
    {
        const uint8_t *in = static_cast<const uint8_t *>(buffer);
        while (size) {
#ifdef _WIN32
            DWORD put = 0, want = size > 0x40000000u ? 0x40000000u : static_cast<DWORD>(size);
            if (!WriteFile(handle, in, want, &put, nullptr) || !put) return false;
#else
            ssize_t put = ::write(fd, in, size > 0x40000000u ? 0x40000000u : size);
            if (put < 0 && errno == EINTR) continue;
            if (put <= 0) return false;
#endif
            in += put;
            size -= static_cast<size_t>(put);
        }
        return true;
    }

    uint64_t size() const
    {
#ifdef _WIN32
        LARGE_INTEGER value;
        return GetFileSizeEx(handle, &value) ? static_cast<uint64_t>(value.QuadPart) : 0;
#else
        struct stat st;
        return fstat(fd, &st) ? 0 : static_cast<uint64_t>(st.st_size);
#endif
    }

    bool sync()
    {
#ifdef _WIN32
        return FlushFileBuffers(handle) != 0;
#else
        return fsync(fd) == 0;
#endif
    }

    bool close()
    {
        bool ok = true;
#ifdef _WIN32
        if (handle != INVALID_HANDLE_VALUE) ok = CloseHandle(handle) != 0;
        handle = INVALID_HANDLE_VALUE;
#else
        if (fd >= 0) ok = ::close(fd) == 0;
        fd = -1;
#endif
        return ok;
    }
};

bool exists(const std::string &path)
{
#ifdef _WIN32
    return GetFileAttributesA(path.c_str()) != INVALID_FILE_ATTRIBUTES;
#else
    struct stat st;
    return stat(path.c_str(), &st) == 0;
#endif
}

bool remove_file(const std::string &path)
{
#ifdef _WIN32
    return DeleteFileA(path.c_str()) != 0 || GetLastError() == ERROR_FILE_NOT_FOUND;
#else
    return unlink(path.c_str()) == 0 || errno == ENOENT;
#endif
}

bool replace_file(const std::string &from, const std::string &to)
{
#ifdef _WIN32
    return MoveFileExA(from.c_str(), to.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH) != 0;
#else
    return rename(from.c_str(), to.c_str()) == 0;
#endif
}

int64_t free_space(const std::string &dir)
{
#ifdef _WIN32
    ULARGE_INTEGER available;
    return GetDiskFreeSpaceExA(dir.c_str(), &available, nullptr, nullptr) ? static_cast<int64_t>(available.QuadPart) : -1;
#else
    struct statvfs st;
    return statvfs(dir.c_str(), &st) ? -1 : static_cast<int64_t>(st.f_bavail) * static_cast<int64_t>(st.f_frsize);
#endif
}

std::string lower(std::string text)
{
    for (char &c : text) if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return text;
}

bool ends_with(const std::string &text, const char *suffix)
{
    size_t n = strlen(suffix);
    return text.size() >= n && lower(text.substr(text.size() - n)) == suffix;
}

/* *.pak in a directory, in name order (the order Win32 FindFirstFile lists an
 * NTFS directory, which breaks ties between equally dated entries). */
std::vector<std::string> paks_in(const std::string &dir)
{
    std::vector<std::string> names;
#ifdef _WIN32
    WIN32_FIND_DATAA found;
    HANDLE find = FindFirstFileA((dir + "\\*.pak").c_str(), &found);
    if (find != INVALID_HANDLE_VALUE) {
        do if (!(found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) names.push_back(found.cFileName);
        while (FindNextFileA(find, &found));
        FindClose(find);
    }
#else
    if (DIR *d = opendir(dir.c_str())) {
        while (struct dirent *e = readdir(d))
            if (ends_with(e->d_name, ".pak")) names.push_back(e->d_name);
        closedir(d);
    }
#endif
    std::sort(names.begin(), names.end(), [](const std::string &a, const std::string &b) { return lower(a) < lower(b); });
    return names;
}

uint16_t le16(const uint8_t *p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }
uint32_t le32(const uint8_t *p) { return static_cast<uint32_t>(p[0] | (p[1] << 8) | (p[2] << 16) | (static_cast<uint32_t>(p[3]) << 24)); }
uint64_t le64(const uint8_t *p) { return le32(p) | (static_cast<uint64_t>(le32(p + 4)) << 32); }
void put16(std::vector<uint8_t> &out, uint32_t v) { out.push_back(static_cast<uint8_t>(v)); out.push_back(static_cast<uint8_t>(v >> 8)); }
void put32(std::vector<uint8_t> &out, uint32_t v) { put16(out, v & 0xFFFFu); put16(out, v >> 16); }
void set32(uint8_t *p, uint32_t v) { p[0] = static_cast<uint8_t>(v); p[1] = static_cast<uint8_t>(v >> 8); p[2] = static_cast<uint8_t>(v >> 16); p[3] = static_cast<uint8_t>(v >> 24); }

/* ------------------------------------------------------------------- zip */

struct ZipEntry {
    std::string name;            /* as stored */
    uint32_t dostime = 0;        /* date << 16 | time: what 0x0047BC50 compares */
    uint16_t method = 0, flags = 0;
    uint32_t crc = 0, attributes = 0;
    uint64_t csize = 0, usize = 0, lho = 0;
    size_t central = 0, central_size = 0;   /* its record in Zip::central */
    bool directory = false;
};

struct Zip {
    std::string path;
    File file;
    uint64_t size = 0, cd_offset = 0, cd_size = 0;
    std::vector<uint8_t> central;
    std::vector<ZipEntry> entries;
    int priority = 0;

    bool open(const std::string &where)
    {
        path = where;
        if (!file.open_read(path)) return false;
        size = file.size();
        if (size < 22) return false;
        size_t tail = static_cast<size_t>(std::min<uint64_t>(size, 65557));
        std::vector<uint8_t> end(tail);
        if (!file.read_at(end.data(), tail, size - tail)) return false;
        size_t at = tail - 22 + 1;
        while (at-- > 0) if (le32(&end[at]) == 0x06054B50u) break;
        if (at == SIZE_MAX) return false;
        cd_size = le32(&end[at + 12]);
        cd_offset = le32(&end[at + 16]);
        uint32_t count16 = le16(&end[at + 10]);
        /* Zip64, if present; H5's own archives wrap the 16-bit count instead. */
        if (at >= 20 && le32(&end[at - 20]) == 0x07064B50u) {
            uint64_t record = le64(&end[at - 20 + 8]);
            uint8_t z[56];
            if (file.read_at(z, sizeof z, record) && le32(z) == 0x06064B50u) {
                cd_size = le64(z + 40);
                cd_offset = le64(z + 48);
            }
        }
        (void)count16;
        if (cd_offset + cd_size > size || cd_size > (512u << 20)) return false;
        central.resize(static_cast<size_t>(cd_size));
        if (cd_size && !file.read_at(central.data(), central.size(), cd_offset)) return false;
        for (size_t p = 0; p + 46 <= central.size();) {
            const uint8_t *r = &central[p];
            if (le32(r) != 0x02014B50u) break;
            ZipEntry e;
            e.flags = le16(r + 8);
            e.method = le16(r + 10);
            e.dostime = (static_cast<uint32_t>(le16(r + 14)) << 16) | le16(r + 12);
            e.crc = le32(r + 16);
            e.attributes = le32(r + 38);
            e.csize = le32(r + 20);
            e.usize = le32(r + 24);
            uint16_t name = le16(r + 28), extra = le16(r + 30), comment = le16(r + 32);
            e.lho = le32(r + 42);
            size_t record = 46u + name + extra + comment;
            if (p + record > central.size()) return false;
            e.name.assign(reinterpret_cast<const char *>(r + 46), name);
            const uint8_t *x = r + 46 + name, *xe = x + extra;
            while (x + 4 <= xe) {
                uint16_t id = le16(x), len = le16(x + 2);
                if (x + 4 + len > xe) break;
                if (id == 1) {
                    const uint8_t *v = x + 4, *ve = v + len;
                    if (e.usize == 0xFFFFFFFFu && v + 8 <= ve) { e.usize = le64(v); v += 8; }
                    if (e.csize == 0xFFFFFFFFu && v + 8 <= ve) { e.csize = le64(v); v += 8; }
                    if (e.lho == 0xFFFFFFFFu && v + 8 <= ve) { e.lho = le64(v); v += 8; }
                }
                x += 4 + len;
            }
            e.directory = (le32(r + 38) & 0x10u) != 0 || (!e.name.empty() && (e.name.back() == '/' || e.name.back() == '\\'));
            e.central = p;
            e.central_size = record;
            entries.push_back(std::move(e));
            p += record;
        }
        return true;
    }

    bool data_offset(const ZipEntry &e, uint64_t &offset) const
    {
        uint8_t local[30];
        if (!file.read_at(local, sizeof local, e.lho) || le32(local) != 0x04034B50u) return false;
        offset = e.lho + 30 + le16(local + 26) + le16(local + 28);
        return offset + e.csize <= size;
    }

    /* The entry's bytes, at most `limit` of them (inflating only that far). */
    bool read(const ZipEntry &e, std::vector<uint8_t> &out, uint64_t limit = UINT64_MAX) const
    {
        uint64_t offset;
        if (!data_offset(e, offset)) return false;
        uint64_t want = std::min(e.usize, limit);
        if (e.method == 0) {
            out.resize(static_cast<size_t>(want));
            return !want || file.read_at(out.data(), out.size(), offset);
        }
        if (e.method != 8) return false;
        out.resize(static_cast<size_t>(want));
        z_stream z{};
        if (inflateInit2(&z, -15) != Z_OK) return false;
        std::vector<uint8_t> chunk(want == e.usize ? std::min<uint64_t>(e.csize, 1u << 20) : std::min<uint64_t>(e.csize, 4096));
        uint64_t read = 0;
        int status = Z_OK;
        z.next_out = out.data();
        z.avail_out = static_cast<uInt>(out.size());
        while (z.avail_out && status != Z_STREAM_END) {
            if (!z.avail_in) {
                size_t n = static_cast<size_t>(std::min<uint64_t>(chunk.size(), e.csize - read));
                if (!n || !file.read_at(chunk.data(), n, offset + read)) break;
                read += n;
                z.next_in = chunk.data();
                z.avail_in = static_cast<uInt>(n);
            }
            status = inflate(&z, Z_NO_FLUSH);
            if (status != Z_OK && status != Z_STREAM_END) break;
        }
        bool ok = !z.avail_out;
        inflateEnd(&z);
        return ok;
    }
};

/* DOS date/time plus two seconds (its resolution), with carries. */
uint32_t dos_later(uint32_t value)
{
    uint32_t date = value >> 16, time = value & 0xFFFFu;
    uint32_t year = (date >> 9) + 1980, month = (date >> 5) & 15, day = date & 31;
    uint32_t hour = time >> 11, minute = (time >> 5) & 63, sec2 = time & 31;
    static const uint8_t days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
    if (++sec2 >= 30) {
        sec2 = 0;
        if (++minute >= 60) {
            minute = 0;
            if (++hour >= 24) {
                hour = 0;
                uint32_t length = month >= 1 && month <= 12 ? days[month - 1] : 31;
                if (month == 2 && year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)) length = 29;
                if (++day > length) {
                    day = 1;
                    if (++month > 12) { month = 1; ++year; }
                }
            }
        }
    }
    if (year > 2107) return value;   /* the last DOS second: nothing later exists */
    return (((year - 1980) << 9 | month << 5 | day) << 16) | (hour << 11 | minute << 5 | sec2);
}

/* ------------------------------------------------------------------- DDS */

constexpr uint32_t DXT1 = TEXCONV_FOURCC('D', 'X', 'T', '1'), DXT2 = TEXCONV_FOURCC('D', 'X', 'T', '2'),
                   DXT3 = TEXCONV_FOURCC('D', 'X', 'T', '3'), DXT4 = TEXCONV_FOURCC('D', 'X', 'T', '4'),
                   DXT5 = TEXCONV_FOURCC('D', 'X', 'T', '5');

struct Dds {
    uint32_t width = 0, height = 0, mips = 1, fourcc = 0, faces = 1;
};

bool is_dxt(uint32_t fourcc) { return fourcc == DXT1 || fourcc == DXT2 || fourcc == DXT3 || fourcc == DXT4 || fourcc == DXT5; }

uint32_t levels_of(uint32_t w, uint32_t h)
{
    uint32_t n = 1;
    while (w > 1 || h > 1) { w = w > 1 ? w / 2 : 1; h = h > 1 ? h / 2 : 1; ++n; }
    return n;
}

void level_dims(const Dds &d, uint32_t level, uint32_t &w, uint32_t &h)
{
    w = d.width >> level; h = d.height >> level;
    if (!w) w = 1;
    if (!h) h = 1;
}

uint64_t dxt_size(uint32_t fourcc, uint32_t w, uint32_t h)
{
    return static_cast<uint64_t>((w + 3) / 4) * ((h + 3) / 4) * (fourcc == DXT1 ? 8u : 16u);
}

/* A DXT 2D or cube texture, with all its stored levels present. */
bool parse_dds(const uint8_t *data, uint64_t size, Dds &d)
{
    if (size < 128 || memcmp(data, "DDS ", 4) || le32(data + 4) != 124) return false;
    const uint8_t *h = data + 4;
    d.height = le32(h + 8);
    d.width = le32(h + 12);
    d.mips = le32(h + 24) ? le32(h + 24) : 1;
    if (!(le32(h + 76) & 4u)) return false;           /* DDPF_FOURCC */
    d.fourcc = le32(h + 80);
    uint32_t caps2 = le32(h + 108);
    if (caps2 & 0x200000u) return false;                /* volume */
    d.faces = (caps2 & 0x200u) ? 6 : 1;
    if (d.faces == 6 && (caps2 & 0xFC00u) != 0xFC00u) return false;   /* partial cube */
    if (!d.width || !d.height || d.width > 16384 || d.height > 16384 || d.mips > levels_of(d.width, d.height)) return false;
    return true;
}

uint64_t dxt_payload(const Dds &d)
{
    uint64_t total = 0;
    for (uint32_t l = 0; l < d.mips; ++l) {
        uint32_t w, h;
        level_dims(d, l, w, h);
        total += dxt_size(d.fourcc, w, h);
    }
    return total * d.faces;
}

/* ------------------------------------------------------------ DXT decode */

void rgb565(uint32_t c, uint8_t *out)
{
    uint32_t r = (c >> 11) & 31, g = (c >> 5) & 63, b = c & 31;
    out[0] = static_cast<uint8_t>((r << 3) | (r >> 2));
    out[1] = static_cast<uint8_t>((g << 2) | (g >> 4));
    out[2] = static_cast<uint8_t>((b << 3) | (b >> 2));
}

/* The same decode as the port's runtime fallback (android/host/d3d9_format.c). */
void color_block(const uint8_t *block, uint8_t out[16][4], bool four)
{
    uint32_t c0 = le16(block), c1 = le16(block + 2), bits = le32(block + 4);
    uint8_t pal[4][4];
    rgb565(c0, pal[0]);
    rgb565(c1, pal[1]);
    pal[0][3] = pal[1][3] = 255;
    if (c0 > c1 || four) {
        for (int k = 0; k < 3; ++k) {
            pal[2][k] = static_cast<uint8_t>((2 * pal[0][k] + pal[1][k] + 1) / 3);
            pal[3][k] = static_cast<uint8_t>((pal[0][k] + 2 * pal[1][k] + 1) / 3);
        }
        pal[2][3] = pal[3][3] = 255;
    } else {
        for (int k = 0; k < 3; ++k) pal[2][k] = static_cast<uint8_t>((pal[0][k] + pal[1][k]) / 2);
        pal[2][3] = 255;
        pal[3][0] = pal[3][1] = pal[3][2] = pal[3][3] = 0;
    }
    for (int i = 0; i < 16; ++i) memcpy(out[i], pal[(bits >> (2 * i)) & 3], 4);
}

void alpha_block(const uint8_t *block, uint8_t out[16])
{
    uint32_t a0 = block[0], a1 = block[1];
    uint64_t bits = 0;
    for (int i = 0; i < 6; ++i) bits |= static_cast<uint64_t>(block[2 + i]) << (8 * i);
    uint8_t pal[8];
    pal[0] = static_cast<uint8_t>(a0);
    pal[1] = static_cast<uint8_t>(a1);
    if (a0 > a1) {
        for (uint32_t i = 1; i < 7; ++i) pal[1 + i] = static_cast<uint8_t>(((7 - i) * a0 + i * a1 + 3) / 7);
    } else {
        for (uint32_t i = 1; i < 5; ++i) pal[1 + i] = static_cast<uint8_t>(((5 - i) * a0 + i * a1 + 2) / 5);
        pal[6] = 0;
        pal[7] = 255;
    }
    for (int i = 0; i < 16; ++i) out[i] = pal[(bits >> (3 * i)) & 7];
}

void decode_dxt(uint32_t fourcc, const uint8_t *src, uint32_t width, uint32_t height, uint8_t *rgba)
{
    uint32_t bw = (width + 3) / 4, bh = (height + 3) / 4, step = fourcc == DXT1 ? 8 : 16;
    for (uint32_t by = 0; by < bh; ++by)
        for (uint32_t bx = 0; bx < bw; ++bx) {
            const uint8_t *block = src + (static_cast<size_t>(by) * bw + bx) * step;
            uint8_t texels[16][4], alpha[16];
            if (fourcc == DXT1) {
                color_block(block, texels, false);
            } else if (fourcc == DXT2 || fourcc == DXT3) {
                color_block(block + 8, texels, true);
                for (int i = 0; i < 16; ++i) texels[i][3] = static_cast<uint8_t>(((block[i / 2] >> (4 * (i & 1))) & 15) * 17);
            } else {
                color_block(block + 8, texels, true);
                alpha_block(block, alpha);
                for (int i = 0; i < 16; ++i) texels[i][3] = alpha[i];
            }
            for (uint32_t y = 0; y < 4 && by * 4 + y < height; ++y)
                for (uint32_t x = 0; x < 4 && bx * 4 + x < width; ++x)
                    memcpy(rgba + ((static_cast<size_t>(by) * 4 + y) * width + bx * 4 + x) * 4, texels[y * 4 + x], 4);
        }
}

/* -------------------------------------------------------------- encoders */

struct AstcContexts {
    astcenc_context *contexts[3] = {nullptr, nullptr, nullptr};   /* 4x4, 5x5, 6x6 */
    ~AstcContexts() { for (astcenc_context *c : contexts) if (c) astcenc_context_free(c); }

    astcenc_context *get(uint32_t block)
    {
        int slot = block == 4 ? 0 : block == 5 ? 1 : 2;
        if (contexts[slot]) return contexts[slot];
        astcenc_config config;
        /* 4x4 carries the textures with alpha: their colour matters where they show. */
        unsigned flags = ASTCENC_FLG_USE_DECODE_UNORM8 | (block == 4 ? ASTCENC_FLG_USE_ALPHA_WEIGHT : 0u);
        if (astcenc_config_init(ASTCENC_PRF_LDR, block, block, 1, ASTCENC_PRE_FAST, flags, &config) != ASTCENC_SUCCESS)
            return nullptr;
        if (astcenc_context_alloc(&config, 1, &contexts[slot], nullptr) != ASTCENC_SUCCESS) contexts[slot] = nullptr;
        return contexts[slot];
    }
};

thread_local AstcContexts astc_contexts;

uint32_t astc_block(uint32_t fourcc) { return fourcc == TEXCONV_ASTC_4x4 ? 4 : fourcc == TEXCONV_ASTC_5x5 ? 5 : 6; }

uint64_t converted_size(uint32_t fourcc, uint32_t w, uint32_t h)
{
    if (fourcc == TEXCONV_ETC2_RGB) return static_cast<uint64_t>((w + 3) / 4) * ((h + 3) / 4) * 8;
    if (fourcc == TEXCONV_ETC2_RGBA) return static_cast<uint64_t>((w + 3) / 4) * ((h + 3) / 4) * 16;
    uint32_t b = astc_block(fourcc);
    return static_cast<uint64_t>((w + b - 1) / b) * ((h + b - 1) / b) * 16;
}

bool encode_level(uint32_t fourcc, const std::vector<uint8_t> &rgba, uint32_t w, uint32_t h, bool opaque, uint8_t *out)
{
    if (fourcc == TEXCONV_ETC2_RGB || fourcc == TEXCONV_ETC2_RGBA) {
        /* etcpak: whole 4x4 blocks of BGRA, rows of the padded width. */
        uint32_t pw = (w + 3) & ~3u, ph = (h + 3) & ~3u;
        std::vector<uint32_t> bgra(static_cast<size_t>(pw) * ph);
        for (uint32_t y = 0; y < ph; ++y)
            for (uint32_t x = 0; x < pw; ++x) {
                const uint8_t *p = &rgba[(static_cast<size_t>(std::min(y, h - 1)) * w + std::min(x, w - 1)) * 4];
                bgra[static_cast<size_t>(y) * pw + x] = static_cast<uint32_t>(p[2]) | (static_cast<uint32_t>(p[1]) << 8) |
                                                      (static_cast<uint32_t>(p[0]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
            }
        uint32_t blocks = (pw / 4) * (ph / 4);
        if (fourcc == TEXCONV_ETC2_RGB) CompressEtc2Rgb(bgra.data(), reinterpret_cast<uint64_t *>(out), blocks, pw, true);
        else CompressEtc2Rgba(bgra.data(), reinterpret_cast<uint64_t *>(out), blocks, pw, true);
        return true;
    }
    astcenc_context *context = astc_contexts.get(astc_block(fourcc));
    if (!context) return false;
    astcenc_image image{};
    image.dim_x = w;
    image.dim_y = h;
    image.dim_z = 1;
    image.data_type = ASTCENC_TYPE_U8;
    void *slices[] = {const_cast<uint8_t *>(rgba.data())};
    image.data = slices;
    /* An opaque image spends no bits on alpha. */
    const astcenc_swizzle swizzle{ASTCENC_SWZ_R, ASTCENC_SWZ_G, ASTCENC_SWZ_B, opaque ? ASTCENC_SWZ_1 : ASTCENC_SWZ_A};
    astcenc_error status = astcenc_compress_image(context, &image, &swizzle, out, converted_size(fourcc, w, h), 0);
    astcenc_compress_reset(context);
    return status == ASTCENC_SUCCESS;
}

/* The converted file for one DXT DDS: 1, or 0 when it stays as it is (a DXT1
 * with transparency: no GPU format fits its 8-byte slots with alpha), or -1
 * with `why`. The levels keep the original layout (texconv.h). */
int convert_dds(const uint8_t *data, uint64_t size, int format, std::vector<uint8_t> &out, std::string &why)
{
    Dds d;
    if (!parse_dds(data, size, d) || !is_dxt(d.fourcc)) { why = "not a DXT texture"; return -1; }
    uint64_t payload = dxt_payload(d);
    if (128 + payload > size) { why = "truncated texture"; return -1; }
    std::vector<std::vector<uint8_t>> levels(static_cast<size_t>(d.faces) * d.mips);
    bool opaque = true;
    const uint8_t *src = data + 128;
    for (uint32_t f = 0; f < d.faces; ++f)
        for (uint32_t l = 0; l < d.mips; ++l) {
            uint32_t w, h;
            level_dims(d, l, w, h);
            std::vector<uint8_t> &level = levels[f * d.mips + l];
            level.resize(static_cast<size_t>(w) * h * 4);
            decode_dxt(d.fourcc, src, w, h, level.data());
            src += dxt_size(d.fourcc, w, h);
            for (size_t i = 3; i < level.size() && opaque; i += 4) opaque = level[i] == 255;
        }
    bool small_slots = d.fourcc == DXT1;
    if (small_slots && !opaque) return 0;
    uint32_t fourcc = small_slots || (opaque && format == TEXCONV_ETC2) ? TEXCONV_ETC2_RGB
                    : format == TEXCONV_ETC2 ? TEXCONV_ETC2_RGBA : TEXCONV_ASTC_4x4;
    out.assign(static_cast<size_t>(128 + payload), 0);
    memcpy(out.data(), data, 128);
    set32(out.data() + 84, fourcc);
    set32(out.data() + 36, TEXCONV_MARKER);
    set32(out.data() + 40, TEXCONV_VERSION);
    set32(out.data() + 44, d.fourcc);
    set32(out.data() + 48, d.mips);
    set32(out.data() + 52, opaque ? 1u : 0u);
    uint8_t *dst = out.data() + 128;
    for (uint32_t f = 0; f < d.faces; ++f)
        for (uint32_t l = 0; l < d.mips; ++l) {
            uint32_t w, h;
            level_dims(d, l, w, h);
            uint64_t slot = dxt_size(d.fourcc, w, h);
            if (converted_size(fourcc, w, h) > slot) { why = "converted level exceeds its slot"; return -1; }
            if (!encode_level(fourcc, levels[f * d.mips + l], w, h, opaque, dst)) { why = "encoder failed"; return -1; }
            dst += slot;
        }
    return 1;
}

/* -------------------------------------------------------- the inventory */

constexpr const char *OUTPUT = "zz_port_textures.pak";
constexpr const char *LEGACY_OUTPUT = "zz_port_textures_v2.pak";
constexpr const char *MANIFEST = "zz_port_textures.json";
constexpr uint32_t LEGACY_ATTRIBUTES = 0x48540000u;

bool legacy_priority(uint32_t attributes, int &priority)
{
    if ((attributes & 0xFFFF00FFu) != LEGACY_ATTRIBUTES || ((attributes >> 8) & 255u) > 5u) return false;
    priority = static_cast<int>((attributes >> 8) & 255u) - 1;
    return true;
}

bool native_newer(int old_priority, uint32_t old_time, int priority, uint32_t time)
{
    return old_priority != priority && old_priority != -1 && priority != -1
           ? old_priority < priority : old_time < time;
}

uint32_t texture_crc(const std::vector<uint8_t> &bytes)
{
    uint32_t crc = crc32(0L, Z_NULL, 0);
    for (size_t at = 0; at < bytes.size();) {
        size_t n = std::min<size_t>(bytes.size() - at, 1u << 20);
        crc = crc32(crc, bytes.data() + at, static_cast<uInt>(n));
        at += n;
    }
    return crc;
}

struct Source {
    size_t pak;                  /* index in Inventory::paks */
    size_t entry;                /* in that pak */
    Dds dds;
    uint64_t dxt_bytes;          /* its DXT payload */
};

struct Inventory {
    std::string data_dir;
    std::vector<std::unique_ptr<Zip>> paks;
    std::vector<Source> sources;  /* the winning DXT originals */
    int64_t bytes = 0;
};

std::string data_dir_of(const char *game_dir)
{
    std::string dir = game_dir;
    while (!dir.empty() && (dir.back() == '/' || dir.back() == '\\')) dir.pop_back();
#ifdef _WIN32
    return dir + "\\data";
#else
    return dir + "/data";
#endif
}

std::string join(const std::string &dir, const std::string &name)
{
#ifdef _WIN32
    return dir + "\\" + name;
#else
    return dir + "/" + name;
#endif
}

bool known_bank(const std::string &bank)
{
    return lower(bank) == "data" || lower(bank) == "datals" || lower(bank) == "dataa1";
}

bool bank_directory(const char *game_dir, const char *bank, std::string &out)
{
    if (!game_dir || !*game_dir || !bank || !known_bank(bank)) {
        fail("Unknown texture data bank");
        return false;
    }
    out = join(game_dir, bank);  // Preserve the installation's actual case on Android.
#ifdef _WIN32
    DWORD attributes = GetFileAttributesA(out.c_str());
    bool directory = attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY);
#else
    struct stat st;
    bool directory = !stat(out.c_str(), &st) && S_ISDIR(st.st_mode);
#endif
    if (!directory) { fail("Texture data bank is missing: %s", bank); return false; }
    return true;
}

std::string bank_name(const std::string &directory)
{
    size_t slash = directory.find_last_of("/\\");
    return lower(directory.substr(slash == std::string::npos ? 0 : slash + 1));
}

const char *output_name(const std::string &directory)
{
    return bank_name(directory) == "data" ? OUTPUT : LEGACY_OUTPUT;
}

/* Native secondary-bank mount order and per-archive priority, from 1.6
 * AF03F0 and 2.1 7B09B0. Those banks do not enumerate arbitrary *.pak files. */
std::vector<std::pair<std::string, int>> mounted_paks(const std::string &directory)
{
    static const std::pair<const char *, int> datals[] = {
        {"p5-texts.pak", -1}, {"p5-data.pak", 1}, {"p6-texts.pak", -1}, {"p6-data.pak", 2},
        {"p7-texts.pak", -1}, {"p7-data.pak", 3}, {"p8-texts.pak", -1}, {"p8-data.pak", 4}};
    static const std::pair<const char *, int> dataa1[] = {
        {"texts.pak", -1}, {"p0-data.pak", 1}, {"p1-data.pak", 1}, {"p2-data.pak", 1}, {"p3-data.pak", 1},
        {"p0-texts.pak", -1}, {"p1-texts.pak", -1}, {"p2-texts.pak", -1}, {"p3-texts.pak", -1},
        {"a1-texts.pak", 2}, {"a1-sound.pak", 2}, {"a1-data.pak", 2}, {"a1p1-data.pak", 3},
        {"a1p1-texts.pak", -1}, {"a1p1-sound.pak", 3}};
    std::vector<std::pair<std::string, int>> result;
    std::vector<std::string> names = paks_in(directory);
    std::string bank = bank_name(directory);
    if (bank == "data") {
        for (const std::string &name : names)
            if (lower(name) != OUTPUT && lower(name) != LEGACY_OUTPUT) result.emplace_back(name, 0);
    } else {
        auto append = [&](const auto &entries) {
            for (const auto &entry : entries)
                for (const std::string &name : names)
                    if (lower(name) == entry.first) { result.emplace_back(name, entry.second); break; }
        };
        if (bank == "datals") append(datals);
        else if (bank == "dataa1") append(dataa1);
    }
    return result;
}

/* Native ZIP hash/equality use a shared byte-normalization table. */
std::string key_of(const std::string &name)
{
    std::string key = name;
    /* Native byte table: ASCII case-fold, either slash, other bytes unchanged. */
    for (char &c : key) {
        if (c == '\\') c = '/';
        else if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
    }
    return key;
}

/* Every pak but the conversion, the winner of each path, its DXT sources. */
bool take_inventory(const std::string &data_dir, Inventory &inv, bool sources)
{
    inv.data_dir = data_dir;
    struct Winner { size_t pak, entry; uint32_t time; int priority; };
    std::map<std::string, Winner> winners;
    for (const auto &[name, priority] : mounted_paks(inv.data_dir)) {
        auto zip = std::make_unique<Zip>();
        if (!zip->open(join(inv.data_dir, name))) { fail("Cannot read the archive %s", name.c_str()); return false; }
        zip->priority = priority;
        size_t index = inv.paks.size();
        for (size_t i = 0; i < zip->entries.size(); ++i) {
            const ZipEntry &e = zip->entries[i];
            if (e.directory || !ends_with(e.name, ".dds")) continue;
            Winner candidate{index, i, e.dostime, priority};
            auto found = winners.find(key_of(e.name));
            if (found == winners.end()) winners.emplace(key_of(e.name), candidate);
            /* Exact native fold (HoF 92A070): -1 compares DOS time with
             * every priority. This is not a sortable priority/time tuple. */
            else if (native_newer(found->second.priority, found->second.time, priority, e.dostime))
                found->second = candidate;   /* ties: the first loaded stays */
        }
        inv.paks.push_back(std::move(zip));
    }
    if (!sources) return true;
    std::vector<uint8_t> head;
    for (auto &[key, w] : winners) {
        if (cancelled) return false;
        const Zip &zip = *inv.paks[w.pak];
        const ZipEntry &e = zip.entries[w.entry];
        if (e.usize < 128 || !zip.read(e, head, 128)) continue;
        Source s{w.pak, w.entry, {}, 0};
        if (!parse_dds(head.data(), head.size(), s.dds) || !is_dxt(s.dds.fourcc)) continue;
        s.dxt_bytes = dxt_payload(s.dds);
        if (128 + s.dxt_bytes > e.usize) continue;
        inv.bytes += static_cast<int64_t>(s.dxt_bytes);
        inv.sources.push_back(s);
    }
    return true;
}

/* Leave every cross-bank DDS collision on the native path, including unconverted DXT1,
 * so no timestamp bump changes the engines' different bank priorities. */
bool keep_bank_priority(const char *game_dir, Inventory &inventory)
{
    std::vector<std::string> banks;
#ifdef _WIN32
    WIN32_FIND_DATAA found;
    HANDLE find = FindFirstFileA(join(game_dir, "*").c_str(), &found);
    if (find == INVALID_HANDLE_VALUE) { fail("Cannot inspect texture data banks"); return false; }
    do if ((found.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) && known_bank(found.cFileName))
        banks.push_back(found.cFileName);
    while (FindNextFileA(find, &found));
    FindClose(find);
#else
    DIR *directory = opendir(game_dir);
    if (!directory) { fail("Cannot inspect texture data banks"); return false; }
    while (struct dirent *entry = readdir(directory))
        if (known_bank(entry->d_name)) banks.push_back(entry->d_name);
    closedir(directory);
#endif
    std::map<std::string, bool> paths;
    for (const std::string &bank : banks) {
        if (lower(bank) == bank_name(inventory.data_dir)) continue;
        Inventory other;
        if (!take_inventory(join(game_dir, bank), other, false)) return false;
        for (const auto &pak : other.paks)
            for (const ZipEntry &entry : pak->entries)
                if (!entry.directory && ends_with(entry.name, ".dds"))
                    paths[key_of(entry.name)] = true;
    }
    inventory.sources.erase(std::remove_if(inventory.sources.begin(), inventory.sources.end(), [&](const Source &source) {
        const ZipEntry &entry = inventory.paks[source.pak]->entries[source.entry];
        if (paths.count(key_of(entry.name))) {
            inventory.bytes -= static_cast<int64_t>(source.dxt_bytes);
            return true;
        }
        return false;
    }), inventory.sources.end());
    return true;
}

/* ------------------------------------------------------------- manifest */

struct Manifest {
    int format = 0, version = 1;
    int64_t textures = 0, bytes = 0;
    bool originals_removed = false;
    std::vector<std::string> paths;   /* the converted entries' names (for removal) */
};

std::string json_escape(const std::string &text)
{
    std::string out;
    for (char c : text) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (static_cast<unsigned char>(c) < 0x20) { char buf[8]; snprintf(buf, sizeof buf, "\\u%04x", c); out += buf; }
        else out += c;
    }
    return out;
}

bool write_manifest(const std::string &data_dir, const Manifest &m)
{
    std::string text = "{\n  \"version\": " + std::string(bank_name(data_dir) == "data" ? "1" : "2") +
                       ",\n  \"bank\": \"" + bank_name(data_dir) + "\",\n  \"format\": \"";
    text += m.format == TEXCONV_ASTC ? "astc" : "etc2";
    char numbers[160];
    snprintf(numbers, sizeof numbers, "\",\n  \"textures\": %lld,\n  \"bytes\": %lld,\n  \"originals_removed\": %s,\n  \"paths\": [",
             static_cast<long long>(m.textures), static_cast<long long>(m.bytes), m.originals_removed ? "true" : "false");
    text += numbers;
    for (size_t i = 0; i < m.paths.size(); ++i) {
        text += i ? ",\n    \"" : "\n    \"";
        text += json_escape(m.paths[i]);
        text += '"';
    }
    text += "\n  ]";
    if (bank_name(data_dir) != "data") text += ",\n  \"metadata_policy\": \"native-priority-time-crc-v1\"";
    text += "\n}\n";
    std::string path = join(data_dir, MANIFEST), temporary = path + ".tmp";
    File out;
    if (!out.create(temporary) || !out.write(text.data(), text.size()) || !out.sync() || !out.close()) {
        remove_file(temporary);
        return false;
    }
    if (!replace_file(temporary, path)) { remove_file(temporary); return false; }
    return true;
}

/* The few fields this module writes, read back without a JSON library. */
bool read_manifest(const std::string &data_dir, Manifest &m)
{
    File in;
    if (!in.open_read(join(data_dir, MANIFEST))) return false;
    uint64_t size = in.size();
    if (!size || size > (64u << 20)) return false;
    std::string text(static_cast<size_t>(size), '\0');
    if (!in.read_at(&text[0], text.size(), 0)) return false;
    size_t bank = text.find("\"bank\": \"");
    if (bank == std::string::npos) {
        if (bank_name(data_dir) != "data") return false;  // Existing ToE manifests.
    } else {
        bank += 9;
        size_t end = text.find('"', bank);
        if (end == std::string::npos || text.substr(bank, end - bank) != bank_name(data_dir)) return false;
    }
    auto number = [&](const char *name) -> int64_t {
        size_t at = text.find(std::string("\"") + name + "\":");
        return at == std::string::npos ? -1 : strtoll(text.c_str() + at + strlen(name) + 3, nullptr, 10);
    };
    m.version = static_cast<int>(number("version"));
    if (m.version != (bank_name(data_dir) == "data" ? 1 : 2)) return false;
    if (bank_name(data_dir) != "data" && text.find("\"metadata_policy\": \"native-priority-time-crc-v1\"") == std::string::npos)
        return false;
    m.format = text.find("\"format\": \"astc\"") != std::string::npos ? TEXCONV_ASTC
             : text.find("\"format\": \"etc2\"") != std::string::npos ? TEXCONV_ETC2 : 0;
    m.textures = number("textures");
    m.bytes = number("bytes");
    m.originals_removed = text.find("\"originals_removed\": true") != std::string::npos;
    size_t at = text.find("\"paths\": [");
    if (at == std::string::npos) return false;
    at += 10;
    while (true) {
        size_t open = text.find('"', at);
        size_t close_bracket = text.find(']', at);
        if (open == std::string::npos || (close_bracket != std::string::npos && close_bracket < open)) break;
        std::string path;
        size_t p = open + 1;
        for (; p < text.size() && text[p] != '"'; ++p) {
            if (text[p] == '\\' && p + 1 < text.size()) {
                ++p;
                if (text[p] == 'u' && p + 4 < text.size()) { path += static_cast<char>(strtol(text.substr(p + 1, 4).c_str(), nullptr, 16)); p += 4; }
                else path += text[p];
            } else path += text[p];
        }
        m.paths.push_back(path);
        at = p + 1;
    }
    return m.format != 0 && m.textures >= 0 && m.bytes >= 0 &&
           static_cast<uint64_t>(m.textures) == m.paths.size();
}

/* A bank's manifest must name exactly its archive's valid converted DDSs.
   Destructive removal additionally checks every stored byte's CRC before
   rewriting any original archive. Ordinary status scans only read headers. */
bool verify_conversion(const Zip &zip, const Manifest &manifest, bool payload)
{
    if (zip.entries.size() != manifest.paths.size()) return false;
    std::map<std::string, bool> expected;
    for (const std::string &path : manifest.paths) expected[key_of(path)] = true;
    std::vector<uint8_t> header, chunk(payload ? 1u << 20 : 0);
    for (const ZipEntry &entry : zip.entries) {
        Dds d;
        if (!expected.erase(key_of(entry.name)) || entry.method != 0 || entry.csize != entry.usize ||
            !zip.read(entry, header, 128) || !parse_dds(header.data(), header.size(), d) ||
            le32(header.data() + 36) != TEXCONV_MARKER || le32(header.data() + 40) != TEXCONV_VERSION)
            return false;
        int priority;
        if (manifest.version == 2 && !legacy_priority(entry.attributes, priority)) return false;
        bool etc = d.fourcc == TEXCONV_ETC2_RGB || d.fourcc == TEXCONV_ETC2_RGBA;
        bool astc = d.fourcc == TEXCONV_ASTC_4x4 || d.fourcc == TEXCONV_ASTC_5x5 || d.fourcc == TEXCONV_ASTC_6x6;
        if (!(manifest.format == TEXCONV_ETC2 ? etc : d.fourcc == TEXCONV_ETC2_RGB || astc)) return false;
        d.fourcc = le32(header.data() + 44);
        if (!is_dxt(d.fourcc) || 128 + dxt_payload(d) != entry.usize) return false;
        if (payload) {
            uint64_t offset;
            if (!zip.data_offset(entry, offset)) return false;
            uint32_t crc = crc32(0L, Z_NULL, 0);
            for (uint64_t at = 0; at < entry.usize;) {
                if (cancelled) return false;
                size_t n = static_cast<size_t>(std::min<uint64_t>(chunk.size(), entry.usize - at));
                if (!zip.file.read_at(chunk.data(), n, offset + at)) return false;
                crc = crc32(crc, chunk.data(), static_cast<uInt>(n));
                at += n;
            }
            if (crc != entry.crc) return false;
        }
    }
    return expected.empty();
}

bool original_paths_present(const Inventory &inventory, const Manifest &manifest)
{
    std::map<std::string, bool> originals;
    for (const auto &zip : inventory.paks)
        for (const ZipEntry &entry : zip->entries)
            if (!entry.directory) originals[key_of(entry.name)] = true;
    for (const std::string &path : manifest.paths)
        if (!originals.count(key_of(path))) return false;
    return true;
}

/* -------------------------------------------------------- the zip writer */

struct Written {
    std::string name;
    uint32_t dostime, crc;
    uint64_t size, offset;
    uint32_t attributes;
};

bool write_local(File &out, uint64_t &position, const std::string &name, uint32_t dostime, const std::vector<uint8_t> &data,
                 std::vector<Written> &written, uint32_t attributes = 0x20u)
{
    uint32_t crc = static_cast<uint32_t>(crc32(0L, data.data(), static_cast<uInt>(data.size())));
    std::vector<uint8_t> header;
    put32(header, 0x04034B50u);
    put16(header, 10);                   /* version needed: stored */
    put16(header, 0);                    /* flags */
    put16(header, 0);                    /* stored */
    put16(header, dostime & 0xFFFFu);
    put16(header, dostime >> 16);
    put32(header, crc);
    put32(header, static_cast<uint32_t>(data.size()));
    put32(header, static_cast<uint32_t>(data.size()));
    put16(header, static_cast<uint32_t>(name.size()));
    put16(header, 0);
    header.insert(header.end(), name.begin(), name.end());
    if (!out.write(header.data(), header.size()) || !out.write(data.data(), data.size())) return false;
    written.push_back({name, dostime, crc, data.size(), position, attributes});
    position += header.size() + data.size();
    return position < 0xFFFFFFFFull;
}

bool write_central(File &out, uint64_t position, const std::vector<Written> &written)
{
    std::vector<uint8_t> central;
    for (const Written &w : written) {
        put32(central, 0x02014B50u);
        put16(central, 20);              /* made by: MS-DOS, 2.0 */
        put16(central, 10);
        put16(central, 0);
        put16(central, 0);
        put16(central, w.dostime & 0xFFFFu);
        put16(central, w.dostime >> 16);
        put32(central, w.crc);
        put32(central, static_cast<uint32_t>(w.size));
        put32(central, static_cast<uint32_t>(w.size));
        put16(central, static_cast<uint32_t>(w.name.size()));
        put16(central, 0);
        put16(central, 0);
        put16(central, 0);
        put16(central, 0);
        put32(central, w.attributes);
        put32(central, static_cast<uint32_t>(w.offset));
        central.insert(central.end(), w.name.begin(), w.name.end());
    }
    std::vector<uint8_t> end;
    put32(end, 0x06054B50u);
    put16(end, 0);
    put16(end, 0);
    put16(end, static_cast<uint32_t>(written.size() & 0xFFFFu));
    put16(end, static_cast<uint32_t>(written.size() & 0xFFFFu));
    put32(end, static_cast<uint32_t>(central.size()));
    put32(end, static_cast<uint32_t>(position));
    put16(end, 0);
    return out.write(central.data(), central.size()) && out.write(end.data(), end.size());
}

/* ------------------------------------------------------------ conversion */

int hardware_threads()
{
    unsigned n = std::thread::hardware_concurrency();
    return n ? static_cast<int>(n) : 4;
}

int convert(const std::string &data_dir, int format, int threads, const char *game_dir = nullptr)
{
    cancelled = false;
    begin(TEXCONV_SCANNING, 0, 0);
    if (format != TEXCONV_ETC2 && format != TEXCONV_ASTC) return fail("Unknown texture format %d", format);
    Inventory inv;
    if (!take_inventory(data_dir, inv, true)) {
        if (cancelled) { set_state(TEXCONV_CANCELLED); return -1; }
        return -1;
    }
    Manifest previous;
    bool has_manifest = read_manifest(inv.data_dir, previous);
    if ((exists(join(data_dir, MANIFEST)) || exists(join(data_dir, output_name(data_dir)))) && !has_manifest)
        return fail("Invalid texture conversion manifest in %s", data_dir.c_str());
    if (has_manifest && (previous.originals_removed || !original_paths_present(inv, previous)))
        return fail("The original textures were removed; restore the game files to convert again");
    if (inv.sources.empty()) return fail("No DXT textures found in %s", inv.data_dir.c_str());
    if (game_dir && !keep_bank_priority(game_dir, inv)) return -1;
    set_totals(static_cast<int64_t>(inv.sources.size()), inv.bytes);
    /* Larger textures first: the slowest ones do not end the run alone. */
    std::sort(inv.sources.begin(), inv.sources.end(), [](const Source &a, const Source &b) { return a.dxt_bytes > b.dxt_bytes; });
    int64_t estimate = 0;
    for (const Source &s : inv.sources) estimate += static_cast<int64_t>(s.dxt_bytes);
    int64_t space = free_space(inv.data_dir);
    if (space >= 0 && space < estimate + estimate / 4 + (64 << 20))
        return fail("Not enough free space: %lld MB needed, %lld MB free", static_cast<long long>((estimate + estimate / 4) >> 20),
                    static_cast<long long>(space >> 20));
    set_state(TEXCONV_CONVERTING);

    std::string output = join(inv.data_dir, output_name(inv.data_dir)), temporary = output + ".tmp";
    File out;
    if (!out.create(temporary)) return fail("Cannot create %s", temporary.c_str());
    uint64_t position = 0;
    std::vector<Written> written;

    /* Workers convert; this thread writes in completion order. The queue is
     * bounded so a fast converter cannot outrun the storage by much. */
    std::mutex lock;
    std::condition_variable ready, room;
    std::deque<std::pair<size_t, std::vector<uint8_t>>> finished;
    size_t queued_bytes = 0, next = 0;
    int running = 0;
    std::string failure;
    const size_t limit = 96u << 20;
    if (threads <= 0) threads = hardware_threads();
    threads = std::max(1, std::min(threads, 16));
    auto worker = [&]() {
        std::vector<uint8_t> original, converted;
        while (true) {
            size_t index;
            {
                std::unique_lock<std::mutex> hold(lock);
                if (next >= inv.sources.size() || cancelled || !failure.empty()) break;
                index = next++;
            }
            const Source &s = inv.sources[index];
            const Zip &zip = *inv.paks[s.pak];
            const ZipEntry &e = zip.entries[s.entry];
            std::string why;
            int result = zip.read(e, original) ? convert_dds(original.data(), original.size(), format, converted, why) : -1;
            if (result >= 0 && bank_name(inv.data_dir) != "data") {
                if (texture_crc(original) != e.crc) { result = -1; why = "original texture checksum mismatch"; }
            }
            if (result < 0 && why.empty()) why = "read failed";
            std::unique_lock<std::mutex> hold(lock);
            if (result < 0) {
                if (failure.empty()) failure = e.name + ": " + why;
                break;
            }
            if (result == 0) converted.clear();   /* kept as it is: counted, not written */
            room.wait(hold, [&]() { return queued_bytes < limit || cancelled || !failure.empty(); });
            queued_bytes += converted.size();
            finished.emplace_back(index, std::move(converted));
            converted = std::vector<uint8_t>();
            ready.notify_one();
        }
        std::lock_guard<std::mutex> hold(lock);
        --running;
        ready.notify_one();
    };
    std::vector<std::thread> pool;
    running = threads;
    for (int i = 0; i < threads; ++i) pool.emplace_back(worker);
    Manifest manifest;
    manifest.format = format;
    bool write_failed = false;
    while (true) {
        std::pair<size_t, std::vector<uint8_t>> item;
        {
            std::unique_lock<std::mutex> hold(lock);
            ready.wait(hold, [&]() { return !finished.empty() || running == 0; });
            if (finished.empty()) break;
            item = std::move(finished.front());
            finished.pop_front();
            queued_bytes -= item.second.size();
            room.notify_all();
        }
        const Source &s = inv.sources[item.first];
        const ZipEntry &e = inv.paks[s.pak]->entries[s.entry];
        if (!write_failed && !cancelled && !item.second.empty()) {
            bool secondary = bank_name(inv.data_dir) != "data";
            if (secondary) set32(item.second.data() + 60, e.crc);
            uint32_t attributes = secondary ? LEGACY_ATTRIBUTES | (static_cast<uint32_t>(inv.paks[s.pak]->priority + 1) << 8) : 0x20u;
            if (!write_local(out, position, e.name, secondary ? e.dostime : dos_later(e.dostime), item.second, written, attributes)) {
                write_failed = true;
                std::lock_guard<std::mutex> hold(lock);
                if (failure.empty()) failure = "Cannot write the converted archive (storage full?)";
                room.notify_all();
            } else {
                manifest.paths.push_back(e.name);
                manifest.bytes += static_cast<int64_t>(item.second.size());
            }
        }
        ++done_textures;
        done_bytes += static_cast<int64_t>(s.dxt_bytes);
    }
    for (std::thread &t : pool) t.join();
    if (cancelled || !failure.empty()) {
        out.close();
        remove_file(temporary);
        if (cancelled) { set_state(TEXCONV_CANCELLED); return -1; }
        return fail("%s", failure.c_str());
    }
    set_state(TEXCONV_FINISHING);
    manifest.textures = static_cast<int64_t>(written.size());
    if (!write_central(out, position, written) || !out.sync() || !out.close()) {
        remove_file(temporary);
        return fail("Cannot finish the converted archive (storage full?)");
    }
    /* The archive is complete and synced before it is published; a crash before
       the manifest leaves a working archive the launcher offers to delete. */
    remove_file(join(inv.data_dir, MANIFEST));
    if (!replace_file(temporary, output) || !write_manifest(inv.data_dir, manifest)) {
        remove_file(temporary);
        remove_file(output);
        return fail("Cannot publish the converted archive");
    }
    set_state(TEXCONV_DONE);
    return 0;
}

/* Rewrites one source pak without the given entries: raw copies of the rest. */
bool rewrite_without(Zip &zip, const std::vector<bool> &drop, std::string &why)
{
    std::string temporary = zip.path + ".tmp";
    File out;
    if (!out.create(temporary)) { why = "cannot create " + temporary; return false; }
    std::vector<uint8_t> central, buffer(4u << 20);
    uint64_t position = 0;
    size_t kept = 0;
    for (size_t i = 0; i < zip.entries.size(); ++i) {
        if (drop[i]) continue;
        if (cancelled) { out.close(); remove_file(temporary); why = "cancelled"; return false; }
        const ZipEntry &e = zip.entries[i];
        uint64_t data;
        if (!zip.data_offset(e, data)) { why = "damaged entry " + e.name; break; }
        /* Local header, data and an optional data descriptor, as they are. */
        uint64_t end = data + e.csize;
        if (e.flags & 8u) {
            uint8_t sig[4];
            end += zip.file.read_at(sig, 4, end) && le32(sig) == 0x08074B50u ? 16 : 12;
        }
        size_t record_offset = central.size();
        central.insert(central.end(), zip.central.begin() + static_cast<std::ptrdiff_t>(e.central),
                       zip.central.begin() + static_cast<std::ptrdiff_t>(e.central + e.central_size));
        if (position >= 0xFFFFFFFFull || le32(&zip.central[e.central + 42]) == 0xFFFFFFFFu) { why = "archive too large"; break; }
        set32(&central[record_offset + 42], static_cast<uint32_t>(position));
        for (uint64_t at = e.lho; at < end;) {
            size_t n = static_cast<size_t>(std::min<uint64_t>(buffer.size(), end - at));
            if (!zip.file.read_at(buffer.data(), n, at) || !out.write(buffer.data(), n)) { why = "copy failed"; break; }
            at += n;
        }
        if (!why.empty()) break;
        position += end - e.lho;
        ++kept;
    }
    std::vector<uint8_t> tail;
    if (why.empty()) {
        put32(tail, 0x06054B50u);
        put16(tail, 0);
        put16(tail, 0);
        put16(tail, static_cast<uint32_t>(kept & 0xFFFFu));   /* wrapped like H5's own archives */
        put16(tail, static_cast<uint32_t>(kept & 0xFFFFu));
        put32(tail, static_cast<uint32_t>(central.size()));
        put32(tail, static_cast<uint32_t>(position));
        put16(tail, 0);
        if (position + central.size() >= 0xFFFFFFFFull) why = "archive too large";
    }
    if (!why.empty() || !out.write(central.data(), central.size()) || !out.write(tail.data(), tail.size()) || !out.sync() || !out.close()) {
        if (why.empty()) why = "write failed (storage full?)";
        out.close();
        remove_file(temporary);
        return false;
    }
    zip.file.close();
    if (!replace_file(temporary, zip.path)) { remove_file(temporary); why = "cannot replace " + zip.path; return false; }
    return true;
}

int remove_originals(const std::string &data_dir)
{
    cancelled = false;
    begin(TEXCONV_SCANNING, 0, 0);
    Inventory inv;
    if (!take_inventory(data_dir, inv, false)) return -1;
    Manifest manifest;
    if (!read_manifest(inv.data_dir, manifest) || !exists(join(inv.data_dir, output_name(inv.data_dir))))
        return fail("There is no texture conversion to keep");
    Zip converted;
    if (!converted.open(join(inv.data_dir, output_name(inv.data_dir)))) return fail("The converted archive cannot be read");
    if (!verify_conversion(converted, manifest, true)) {
        if (cancelled) { set_state(TEXCONV_CANCELLED); return -1; }
        return fail("The converted archive does not match its manifest or checksum");
    }
    std::map<std::string, uint32_t> replaced;   /* key -> the converted entry's time */
    for (const ZipEntry &e : converted.entries) replaced[key_of(e.name)] = e.dostime;
    struct Covered { uint32_t time, crc; int priority; };
    std::map<std::string, Covered> covered;
    if (manifest.version == 2) {
        std::vector<uint8_t> header;
        for (const ZipEntry &entry : converted.entries) {
            int priority;
            if (!legacy_priority(entry.attributes, priority) || !converted.read(entry, header, 128))
                return fail("Invalid original texture metadata");
            covered.emplace(key_of(entry.name), Covered{entry.dostime, le32(header.data() + 60), priority});
        }
        struct Winner { const Zip *zip; const ZipEntry *entry; };
        std::map<std::string, Winner> winners;
        for (const auto &zip : inv.paks) for (const ZipEntry &entry : zip->entries) {
            if (entry.directory) continue;
            std::string key = key_of(entry.name);
            if (!covered.count(key)) continue;
            auto found = winners.find(key);
            if (found == winners.end() || native_newer(found->second.zip->priority, found->second.entry->dostime,
                                                       zip->priority, entry.dostime))
                winners[key] = {zip.get(), &entry};
        }
        for (auto it = covered.begin(); it != covered.end();) {
            const Covered &metadata = it->second;
            auto found = winners.find(it->first);
            if (found == winners.end() || found->second.zip->priority != metadata.priority ||
                found->second.entry->dostime != metadata.time || found->second.entry->crc != metadata.crc) {
                if (!manifest.originals_removed)
                    return fail("An original texture changed since conversion: %s", it->first.c_str());
                it = covered.erase(it);  // A previous partial removal may have exposed an older loser.
            } else ++it;
        }
    }
    /* Secondary banks remove only the exact covered source; data keeps its existing date policy. */
    std::vector<std::vector<bool>> drops;
    int64_t total = 0, freed = 0;
    for (auto &zip : inv.paks) {
        std::vector<bool> drop(zip->entries.size(), false);
        for (size_t i = 0; i < zip->entries.size(); ++i) {
            const ZipEntry &entry = zip->entries[i];
            std::string key = key_of(entry.name);
            auto found = replaced.find(key);
            bool drop_entry = found != replaced.end() && entry.dostime < found->second;
            if (manifest.version == 2) {
                auto matched = covered.find(key);
                drop_entry = !entry.directory && matched != covered.end() && zip->priority == matched->second.priority &&
                             entry.dostime == matched->second.time && entry.crc == matched->second.crc;
                if (drop_entry) {
                    std::vector<uint8_t> original;
                    if (!zip->read(entry, original) || texture_crc(original) != matched->second.crc)
                        return fail("An original texture checksum changed: %s", entry.name.c_str());
                    if (cancelled) { set_state(TEXCONV_CANCELLED); return -1; }
                }
            }
            if (drop_entry) {
                drop[i] = true;
                freed += static_cast<int64_t>(zip->entries[i].csize);
            }
        }
        if (std::find(drop.begin(), drop.end(), true) != drop.end()) total += static_cast<int64_t>(zip->size);
        drops.push_back(std::move(drop));
    }
    int64_t space = free_space(inv.data_dir), largest = 0;
    for (size_t p = 0; p < inv.paks.size(); ++p)
        if (std::find(drops[p].begin(), drops[p].end(), true) != drops[p].end())
            largest = std::max<int64_t>(largest, static_cast<int64_t>(inv.paks[p]->size));
    if (space >= 0 && space < largest + (64 << 20))
        return fail("Not enough free space to rewrite the archives: %lld MB needed, %lld MB free",
                    static_cast<long long>((largest + (64 << 20)) >> 20), static_cast<long long>(space >> 20));
    set_totals(static_cast<int64_t>(inv.paks.size()), total);
    set_state(TEXCONV_REMOVING);
    /* Commit the only-copy guard before the first archive can be replaced.
       A partial rewrite/cancel remains resumable; undo cannot delete the
       sole converted copy after a later filesystem or manifest failure. */
    if (!manifest.originals_removed && !manifest.paths.empty()) {
        manifest.originals_removed = true;
        if (!write_manifest(inv.data_dir, manifest)) return fail("Cannot protect the conversion before removing originals");
    }
    for (size_t p = 0; p < inv.paks.size(); ++p) {
        Zip &zip = *inv.paks[p];
        if (std::find(drops[p].begin(), drops[p].end(), true) != drops[p].end()) {
            std::string why;
            if (!rewrite_without(zip, drops[p], why)) {
                if (cancelled) { set_state(TEXCONV_CANCELLED); return -1; }
                return fail("%s: %s", zip.path.c_str(), why.c_str());
            }
            done_bytes += static_cast<int64_t>(zip.size);
        }
        ++done_textures;
    }
    (void)freed;
    set_state(TEXCONV_DONE);
    return 0;
}

}  // namespace

/* ------------------------------------------------------------------ API */

static int scan_bank(const std::string &data_dir, texconv_status *out)
{
    cancelled = false;
    begin(TEXCONV_SCANNING, 0, 0);
    *out = texconv_status{};
    Inventory inv;
    if (!take_inventory(data_dir, inv, true)) return -1;
    out->textures = static_cast<int64_t>(inv.sources.size());
    out->bytes = inv.bytes;
    /* Converted sizes: ETC2 keeps the DXT size for alpha textures and halves
     * opaque DXT3; ASTC 4x4/5x5 lands near it. Opacity is not scanned here. */
    out->estimate_etc2 = inv.bytes;
    out->estimate_astc = inv.bytes;
    Manifest m;
    std::string output = join(inv.data_dir, output_name(inv.data_dir));
    bool manifest = read_manifest(inv.data_dir, m), archive = exists(output);
    if ((exists(join(inv.data_dir, MANIFEST)) && !manifest) || manifest != archive)
        return fail("Incomplete texture conversion in %s", inv.data_dir.c_str());
    if (manifest && archive) {
        Zip converted;
        if (!converted.open(output) || !verify_conversion(converted, m, false))
            return fail("The converted archive does not match its manifest");
        out->converted_format = m.format;
        out->converted_textures = m.textures;
        out->converted_bytes = m.bytes;
        out->originals_removed = m.originals_removed || !original_paths_present(inv, m) ? 1 : 0;
        std::map<std::string, bool> names;
        for (const std::string &p : m.paths) names[key_of(p)] = true;
        for (const Source &s : inv.sources) {
            const ZipEntry &e = inv.paks[s.pak]->entries[s.entry];
            if (names.count(key_of(e.name))) out->removable_bytes += static_cast<int64_t>(e.csize);
        }
    }
    set_state(TEXCONV_DONE);
    return 0;
}

extern "C" int texconv_scan(const char *game_dir, texconv_status *out)
{
    return scan_bank(data_dir_of(game_dir), out);
}

extern "C" int texconv_convert(const char *game_dir, int format, int threads)
{
    return convert(data_dir_of(game_dir), format, threads);
}

extern "C" int texconv_remove_originals(const char *game_dir)
{
    return remove_originals(data_dir_of(game_dir));
}

static int remove_converted(const std::string &data_dir)
{
    begin(TEXCONV_FINISHING, 0, 0);
    Manifest m;
    bool manifest = read_manifest(data_dir, m);
    if ((exists(join(data_dir, MANIFEST)) || exists(join(data_dir, output_name(data_dir)))) && !manifest)
        return fail("Invalid texture conversion manifest in %s", data_dir.c_str());
    Inventory originals;
    if (manifest && !take_inventory(data_dir, originals, false)) return -1;
    if (manifest && (m.originals_removed || !original_paths_present(originals, m)))
        return fail("The original textures were removed: the converted ones are the only copy");
    if (!remove_file(join(data_dir, output_name(data_dir))) || !remove_file(join(data_dir, MANIFEST)))
        return fail("Cannot delete the converted textures");
    set_state(TEXCONV_DONE);
    return 0;
}

extern "C" int texconv_remove_converted(const char *game_dir)
{
    return remove_converted(data_dir_of(game_dir));
}

extern "C" int texconv_scan_bank(const char *game_dir, const char *bank, texconv_status *out)
{
    if (!out) return fail("Texture status is missing");
    *out = texconv_status{};
    std::string directory;
    return bank_directory(game_dir, bank, directory) ? scan_bank(directory, out) : -1;
}

extern "C" int texconv_convert_bank(const char *game_dir, const char *bank, int format, int threads)
{
    std::string directory;
    return bank_directory(game_dir, bank, directory) ? convert(directory, format, threads, game_dir) : -1;
}

extern "C" int texconv_remove_originals_bank(const char *game_dir, const char *bank)
{
    std::string directory;
    return bank_directory(game_dir, bank, directory) ? remove_originals(directory) : -1;
}

extern "C" int texconv_remove_converted_bank(const char *game_dir, const char *bank)
{
    std::string directory;
    return bank_directory(game_dir, bank, directory) ? remove_converted(directory) : -1;
}

extern "C" void texconv_cancel(void) { cancelled = true; }

extern "C" void texconv_get_progress(texconv_progress *out)
{
    std::lock_guard<std::mutex> lock(progress_lock);
    *out = progress_state;
    out->done = done_textures;
    out->bytes_done = done_bytes;
}

extern "C" int texconv_convert_dds(const uint8_t *dds, uint64_t size, int format, uint8_t **out, uint64_t *out_size)
{
    std::vector<uint8_t> converted;
    std::string why;
    int result = convert_dds(dds, size, format, converted, why);
    if (result <= 0) return result < 0 ? -1 : 1;   /* 1: kept as it is */
    *out = static_cast<uint8_t *>(malloc(converted.size()));
    if (!*out) return -1;
    memcpy(*out, converted.data(), converted.size());
    *out_size = converted.size();
    return 0;
}

extern "C" void texconv_free(void *pointer) { free(pointer); }

extern "C" int texconv_decode_dxt(uint32_t fourcc, const uint8_t *blocks, uint32_t width, uint32_t height, uint8_t *rgba)
{
    if (!is_dxt(fourcc)) return -1;
    decode_dxt(fourcc, blocks, width, height, rgba);
    return 0;
}

/* One level of a converted DDS back to RGBA (tests and quality checks). */
extern "C" int texconv_decode_converted(const uint8_t *dds, uint64_t size, uint32_t level, uint8_t *rgba)
{
    Dds d;
    if (size < 128 || memcmp(dds, "DDS ", 4) || le32(dds + 36) != TEXCONV_MARKER) return -1;
    d.height = le32(dds + 12);
    d.width = le32(dds + 16);
    d.fourcc = le32(dds + 84);
    uint32_t original = le32(dds + 44), levels = le32(dds + 48);
    if (level >= levels || !is_dxt(original)) return -1;
    uint64_t offset = 128;
    for (uint32_t l = 0; l < level; ++l) {
        uint32_t w, h;
        level_dims(d, l, w, h);
        offset += dxt_size(original, w, h);
    }
    uint32_t w, h;
    level_dims(d, level, w, h);
    if (offset + converted_size(d.fourcc, w, h) > size) return -1;
    const uint8_t *src = dds + offset;
    if (d.fourcc == TEXCONV_ETC2_RGB || d.fourcc == TEXCONV_ETC2_RGBA) {
        uint32_t pw = (w + 3) & ~3u, ph = (h + 3) & ~3u;
        std::vector<uint32_t> bgra(static_cast<size_t>(pw) * ph);   /* decoded RGBA, despite the name */
        std::vector<uint64_t> blocks(converted_size(d.fourcc, w, h) / 8);
        memcpy(blocks.data(), src, blocks.size() * 8);
        if (d.fourcc == TEXCONV_ETC2_RGB) DecodeRGB(blocks.data(), bgra.data(), static_cast<int32_t>(pw), static_cast<int32_t>(ph));
        else DecodeRGBA(blocks.data(), bgra.data(), static_cast<int32_t>(pw), static_cast<int32_t>(ph));
        for (uint32_t y = 0; y < h; ++y)
            for (uint32_t x = 0; x < w; ++x) {
                /* etcpak encodes BGRA input but decodes to RGBA. */
                uint32_t v = bgra[static_cast<size_t>(y) * pw + x];
                uint8_t *p = rgba + (static_cast<size_t>(y) * w + x) * 4;
                p[0] = static_cast<uint8_t>(v);
                p[1] = static_cast<uint8_t>(v >> 8);
                p[2] = static_cast<uint8_t>(v >> 16);
                p[3] = d.fourcc == TEXCONV_ETC2_RGB ? 255 : static_cast<uint8_t>(v >> 24);
            }
        return 0;
    }
    astcenc_context *context = astc_contexts.get(astc_block(d.fourcc));
    if (!context) return -1;
    astcenc_image image{};
    image.dim_x = w;
    image.dim_y = h;
    image.dim_z = 1;
    image.data_type = ASTCENC_TYPE_U8;
    void *slices[] = {rgba};
    image.data = slices;
    const astcenc_swizzle swizzle{ASTCENC_SWZ_R, ASTCENC_SWZ_G, ASTCENC_SWZ_B, ASTCENC_SWZ_A};
    astcenc_error status = astcenc_decompress_image(context, src, converted_size(d.fourcc, w, h), &image, &swizzle, 0);
    astcenc_decompress_reset(context);
    return status == ASTCENC_SUCCESS ? 0 : -1;
}
