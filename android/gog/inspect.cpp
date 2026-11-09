// Heroes V Android metadata adapter; the pinned innoextract sources remain unmodified.
#include "loader/offsets.hpp"
#include "setup/info.hpp"
#include "setup/data.hpp"
#include "setup/file.hpp"
#include "cli/gog.hpp"
#include "cli/goggalaxy.hpp"
#include "stream/slice.hpp"
#include <boost/filesystem/path.hpp>
#include <algorithm>
#include <cctype>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <string>

int inno_main(int, char **);

static std::string app_path(std::string name)
{
    std::replace(name.begin(), name.end(), '\\', '/');
    if (!name.compare(0, 6, "{app}/")) name.erase(0, 6);
    else if (!name.compare(0, 4, "app/")) name.erase(0, 4); // GOG Galaxy's recovered filenames.
    else if (name.empty() || name.front() == '{') return {};
    if (name.empty() || name.size() > 2048 || name.front() == '/' || name.find(':') != std::string::npos ||
        std::any_of(name.begin(), name.end(), [](unsigned char c) { return c < 32 || c == 127 || c == '"'; }))
        throw std::runtime_error("Invalid installer path");
    size_t start = 0;
    while (start < name.size()) {
        const size_t end = name.find('/', start);
        const std::string part = name.substr(start, end == std::string::npos ? end : end - start);
        if (part.empty() || part == "." || part == "..") throw std::runtime_error("Invalid installer path component");
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return name;
}

static bool needed(const std::string &name)
{
    std::string root = name.substr(0, name.find('/'));
    std::transform(root.begin(), root.end(), root.begin(), [](unsigned char c) { return std::tolower(c); });
    static const std::set<std::string> roots = {"bin", "bina1", "data", "dataa1", "datals", "music", "video", "profiles",
        "maps", "usercampaigns", "usermods", "hwcursors", "duelpresets"};
    return roots.count(root) != 0;
}

static int inspect(const char *path)
{
    std::ifstream input(path, std::ios::binary);
    if (!input) throw std::runtime_error("Installer is unreadable");
    loader::offsets offsets; offsets.load(input); input.seekg(offsets.header_offset);
    setup::info info;
    info.load(input, setup::info::Files | setup::info::DataEntries | setup::info::RegistryEntries |
                     setup::info::Languages | setup::info::NoUnknownVersion);
    gog::parse_galaxy_files(info, false);
    const std::string id = gog::get_game_id(info);
    if (id.empty() || id.find_first_not_of("0123456789") != std::string::npos)
        throw std::runtime_error("This is not a GOG offline installer");
    if (info.files.size() > 100000) throw std::runtime_error("Installer contains too many files");
    uint64_t total = 0;
    std::map<std::string, uint64_t> files;
    std::set<std::string> names;
    std::set<unsigned> slices;
    for (const auto &file : info.files) {
        const std::string name = app_path(file.destination);
        if (name.empty() || !needed(name) || (file.options & setup::file_entry::DeleteAfterInstall)) continue;
        uint64_t bytes = 0;
        auto add = [&](unsigned location) {
            if (location >= info.data_entries.size()) throw std::runtime_error("External file in installer");
            const auto &data = info.data_entries[location];
            if (data.chunk.encryption != stream::Plaintext || data.chunk.compression == stream::UnknownCompression)
                throw std::runtime_error("Unsupported installer compression or encryption");
            if (data.chunk.last_slice >= 1024 || data.chunk.first_slice > data.chunk.last_slice)
                throw std::runtime_error("Invalid installer BIN index");
            for (unsigned i = data.chunk.first_slice; i <= data.chunk.last_slice; ++i) slices.insert(i);
            bytes += data.uncompressed_size;
            if (bytes > uint64_t(32) * 1024 * 1024 * 1024) throw std::runtime_error("Installer file exceeds 32 GiB");
        };
        add(file.location);
        for (const auto location : file.additional_locations) add(location);
        std::string lower = name;
        std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c) { return std::tolower(c); });
        if (!names.insert(lower).second) throw std::runtime_error("Ambiguous duplicate installer path: " + name);
        files.emplace(name, bytes); total += bytes;
        if (total > uint64_t(32) * 1024 * 1024 * 1024) throw std::runtime_error("Installer exceeds 32 GiB");
    }
    if (files.empty()) throw std::runtime_error("No game files in installer");
    if (!offsets.data_offset) {
        const boost::filesystem::path setup(path);
        std::string alternate = info.header.base_filename;
        std::replace(alternate.begin(), alternate.end(), '/', '_');
        std::replace(alternate.begin(), alternate.end(), '\\', '_');
        stream::slice_reader reader(setup.parent_path(), setup.stem().string(), alternate, info.header.slices_per_disk);
        // Validate every required BIN header and its declared length before offering installation.
        for (const auto slice : slices) if (!reader.seek(slice, 0)) throw std::runtime_error("Invalid installer BIN");
    }
    std::cout << "GOG2\t" << id << '\t' << files.size() << '\t' << total << '\t' << (offsets.data_offset == 0) << '\n';
    for (const auto &file : files) std::cout << "FILE\t" << file.second << '\t' << file.first << '\n';
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 3 || std::string(argv[1]) != "--port-info") return inno_main(argc, argv);
    try { return inspect(argv[2]); }
    catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 2; }
}
