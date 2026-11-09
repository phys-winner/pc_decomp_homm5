cmake_minimum_required(VERSION 3.22)
project(heroes_gog LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
get_filename_component(PORT_ROOT "${CMAKE_CURRENT_LIST_DIR}/../.." ABSOLUTE)
set(BOOST "${PORT_ROOT}/reference/boost_1_84_0")
set(INNO "${PORT_ROOT}/reference/innoextract")
set(BZIP "${PORT_ROOT}/reference/bzip2")

set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
add_subdirectory("${PORT_ROOT}/reference/xz" xz EXCLUDE_FROM_ALL)
add_library(bzip2 STATIC "${BZIP}/blocksort.c" "${BZIP}/huffman.c" "${BZIP}/crctable.c"
    "${BZIP}/randtable.c" "${BZIP}/compress.c" "${BZIP}/decompress.c" "${BZIP}/bzlib.c")
target_compile_definitions(bzip2 PRIVATE _FILE_OFFSET_BITS=64)

file(GLOB FILESYSTEM "${BOOST}/libs/filesystem/src/*.cpp")
list(FILTER FILESYSTEM EXCLUDE REGEX "windows_file_codecvt.cpp$")
file(GLOB OPTIONS "${BOOST}/libs/program_options/src/*.cpp")
add_library(boost_support STATIC ${FILESYSTEM} ${OPTIONS}
    "${BOOST}/libs/iostreams/src/zlib.cpp" "${BOOST}/libs/iostreams/src/bzip2.cpp")
target_include_directories(boost_support PUBLIC "${BOOST}" "${BZIP}")
target_compile_definitions(boost_support PRIVATE BOOST_FILESYSTEM_SOURCE BOOST_FILESYSTEM_STATIC_LINK BOOST_FILESYSTEM_NO_CXX20_ATOMIC_REF
    BOOST_FILESYSTEM_DISABLE_COPY_FILE_RANGE BOOST_FILESYSTEM_DISABLE_STATX BOOST_FILESYSTEM_DISABLE_GETRANDOM)
target_link_libraries(boost_support PUBLIC bzip2 z)

foreach(FEATURE ISATTY IOCTL TIMEGM GMTIME_R UTIMENSAT AT_FDCWD UTIMES BUILTIN_BSWAP16 BUILTIN_BSWAP32
        BUILTIN_BSWAP64 ALIGNOF STD_CODECVT_UTF8_UTF16 STD_UNIQUE_PTR ARC4 LZMA BUILTIN_CONV
        UNISTD_ENVIRON FORK EXECVP WAITPID)
    set(INNOEXTRACT_HAVE_${FEATURE} 1)
endforeach()
configure_file("${INNO}/src/configure.hpp.in" "configure.hpp")
file(READ "${INNO}/LICENSE" LICENSE_TEXT)
string(REPLACE "\\" "\\\\" LICENSE_TEXT "${LICENSE_TEXT}")
string(REPLACE "\"" "\\\"" LICENSE_TEXT "${LICENSE_TEXT}")
string(REPLACE "\n" "\\n\"\n\"" LICENSE_TEXT "${LICENSE_TEXT}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/release.cpp"
    "#include \"release.hpp\"\nconst char innoextract_name[]=\"innoextract\";\n"
    "const char innoextract_version[]=\"1.9 (Heroes V Android build)\";\n"
    "const char innosetup_versions[]=\"1.2.10 to 6.0.5\";\n"
    "const char innoextract_bugs[]=\"https://github.com/dscharrer/innoextract/issues\";\n"
    "const char innoextract_copyright[]=\"Copyright (C) 2011-2020 Daniel Scharrer\";\n"
    "const char innoextract_license[]=\"${LICENSE_TEXT}\";\n")
file(GLOB_RECURSE INNO_SOURCES "${INNO}/src/*.cpp")
list(FILTER INNO_SOURCES EXCLUDE REGEX "/(util/windows|cli/debug).cpp$")
# The pinned reader's BIN-magic loop lacks its upper bound; keep that fix local.
file(READ "${INNO}/src/stream/slice.cpp" SLICE_SOURCE)
set(SLICE_OLD "for(size_t i = 0; boost::size(slice_ids); i++)")
string(REPLACE "${SLICE_OLD}" "" SLICE_WITHOUT_MATCH "${SLICE_SOURCE}")
string(LENGTH "${SLICE_SOURCE}" SLICE_LENGTH)
string(LENGTH "${SLICE_WITHOUT_MATCH}" SLICE_WITHOUT_LENGTH)
string(LENGTH "${SLICE_OLD}" SLICE_NEEDLE_LENGTH)
math(EXPR SLICE_MATCHED_BYTES "${SLICE_LENGTH} - ${SLICE_WITHOUT_LENGTH}")
if(NOT SLICE_MATCHED_BYTES EQUAL SLICE_NEEDLE_LENGTH)
    message(FATAL_ERROR "Pinned innoextract BIN-magic loop changed or is duplicated")
endif()
string(REPLACE "${SLICE_OLD}" "for(size_t i = 0; i < boost::size(slice_ids); i++)" SLICE_CHECKED "${SLICE_SOURCE}")
file(WRITE "${CMAKE_CURRENT_BINARY_DIR}/slice_checked.cpp" "// Android local adaptation: bound the BIN-magic loop.\n${SLICE_CHECKED}")
list(FILTER INNO_SOURCES EXCLUDE REGEX "/stream/slice\\.cpp$")
list(APPEND INNO_SOURCES "${CMAKE_CURRENT_BINARY_DIR}/slice_checked.cpp")
set_source_files_properties("${INNO}/src/cli/main.cpp" PROPERTIES COMPILE_DEFINITIONS "main=inno_main")
add_executable(innoextract ${INNO_SOURCES} "${CMAKE_CURRENT_BINARY_DIR}/release.cpp" inspect.cpp)
target_include_directories(innoextract PRIVATE "${CMAKE_CURRENT_BINARY_DIR}" "${INNO}/src" "${PORT_ROOT}/reference/xz/src/liblzma/api")
target_link_libraries(innoextract PRIVATE boost_support liblzma)
target_link_options(innoextract PRIVATE "-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384")
set_target_properties(innoextract PROPERTIES OUTPUT_NAME libinnoextract SUFFIX .so)

