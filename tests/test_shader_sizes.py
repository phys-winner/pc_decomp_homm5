"""Run the host's bounded shader scanner on real PE blobs and malformed streams."""
import json
import re
import struct
import unittest

import pefile

from test_static_tls import ROOT, compile_probe
from test_legacy_shaders import build_mojo, embedded_shaders, translate

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint8_t memory[0x2000000];
static uint64_t map_start, map_end;
static unsigned reads, checks;
static int void_vm_readable(uint32_t va, uint32_t size) {
    return va >= map_start && (uint64_t)va + size <= map_end && (uint64_t)va + size <= sizeof memory;
}
static uint32_t read_word(uint32_t va) {
    assert(void_vm_readable(va, 4)); uint32_t word; memcpy(&word, memory + va, 4); ++reads; return word;
}
#define MEM32(va) read_word(va)
#include "scanner.h"
static void fixture(const uint32_t *words, uint32_t count, uint32_t expected) {
    map_start = 0x1000; map_end = map_start + 4 * count;
    memcpy(memory + map_start, words, 4 * count);
    assert(d3d_shader_bytecode_size((uint32_t)map_start) == expected); ++checks;
}
int main(void) {
    const uint32_t empty[] = {0xFFFF0101, 0xFFFF}; fixture(empty, 2, 8);
    const uint32_t mov[] = {0xFFFE0101, 1, 0x800F0000, 0x90E40000, 0xFFFF}; fixture(mov, 5, 20);
    fixture(mov, 3, 0); fixture(mov, 4, 0);
    const uint32_t def[] = {0xFFFF0101, 0x51, 0xA00F0000, 0xFFFF, 0, UINT32_MAX, 0x1234, 0xFFFF}; fixture(def, 8, 32);
    const uint32_t comment[] = {0xFFFF0101, 0x0002FFFE, 0xFFFF, UINT32_MAX, 0xFFFF}; fixture(comment, 5, 20);
    const uint32_t truncated_comment[] = {0xFFFF0101, 0x7FFFFFFE, 0xFFFF}; fixture(truncated_comment, 3, 0);
    const uint32_t bad_comment[] = {0xFFFF0101, 0x8001FFFE, 0xFFFF, 0xFFFF}; fixture(bad_comment, 4, 0);
    const uint32_t sm14[] = {0xFFFF0104, 0xFFFD, 64, 0x800F0000, 0xB0E40000, 66, 0x800F0001, 0xB0E40001, 0xFFFF}; fixture(sm14, 9, 36);
    const uint32_t phase11[] = {0xFFFF0101, 0xFFFD, 0xFFFF}; fixture(phase11, 3, 0);
    const uint32_t reserved_length[] = {0xFFFF0101, 0x02000001, 0x800F0000, 0x90E40000, 0xFFFF}; fixture(reserved_length, 5, 0);
    const uint32_t coissue[] = {0xFFFF0101, 0x40000001, 0x800F0000, 0x90E40000, 0xFFFF}; fixture(coissue, 5, 20);
    const uint32_t sm2[] = {0xFFFF0200, 0x03000001, 0x800F0000, 0x90E42000, 0xB0000000, 0xFFFF}; fixture(sm2, 6, 24);
    const uint32_t short_sm2[] = {0xFFFF0200, 1, 0xFFFF}; fixture(short_sm2, 3, 0);
    const uint32_t sm3[] = {0xFFFF0300, 0x13000001, 0x800F0000, 0x90E40000, 0xB0001000, 0xFFFF}; fixture(sm3, 6, 24);
    const uint32_t predicated_sm2[] = {0xFFFF0200, 0x13000001, 0x800F0000, 0x90E40000, 0xB0001000, 0xFFFF}; fixture(predicated_sm2, 6, 0);
    const uint32_t sincos[] = {0xFFFE0300, 0x02000025, 0x800F0000, 0x90E40000, 0xFFFF}; fixture(sincos, 5, 20);
    const uint32_t unknown[] = {0xFFFF0101, 0x1234, 0xFFFF}; fixture(unknown, 3, 0);
    const uint32_t no_end[] = {0xFFFF0101, 0, 0, 0}; fixture(no_end, 4, 0);
    const uint32_t version[] = {0x12340101, 0xFFFF}; fixture(version, 2, 0);
    const uint32_t sm4[] = {0xFFFF0400, 0xFFFF}; fixture(sm4, 2, 0);
    reads = 0; assert(!d3d_shader_bytecode_size(UINT32_MAX - 3) && !reads);
    assert(!d3d_shader_bytecode_size(0x1001) && !d3d_shader_bytecode_size(0) && !reads);
    memset(memory + 0x1000, 0, 0x400004); map_start = 0x1000; map_end = 0x401004;
    uint32_t header = 0xFFFE0101, end = 0xFFFF;
    memcpy(memory + 0x1000, &header, 4); memcpy(memory + 0x401000, &end, 4);
    assert(!d3d_shader_bytecode_size(0x1000));
    memcpy(memory + 0x400FFC, &end, 4); assert(d3d_shader_bytecode_size(0x1000) == 0x400000);
    FILE *input = fopen(@FIXTURES@, "rb"); assert(input);
    uint32_t blobs; assert(fread(&blobs, 4, 1, input) == 1);
    for (uint32_t i = 0; i < blobs; ++i) {
        uint32_t va = 0, length = 0; assert(fread(&va, 4, 1, input) == 1 && fread(&length, 4, 1, input) == 1);
        assert((uint64_t)va + length + 16 <= sizeof memory);
        memset(memory + va, 0xFF, length + 16); assert(fread(memory + va, 1, length, input) == length);
        map_start = va; map_end = (uint64_t)va + length + 16;
        uint32_t actual = d3d_shader_bytecode_size(va);
        if (actual != length) { fprintf(stderr, "shader %08X: got%u expected%u\n", va, actual, length); return 1; }
    }
    fclose(input);
    printf("PASS shader sizes: %u real PE blobs, %u malformed/SM1-3 fixtures, readable bounds and4MiB limit\n", blobs, checks);
    return 0;
}
'''


class ShaderSizeTest(unittest.TestCase):
    def test_real_and_malformed_streams(self):
        text = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
        scanner = text[text.index("static const int8_t sm1_operands"):text.index("static void_com_class shader_class_vs")]
        rows = list(embedded_shaders())
        pe = pefile.PE(str(ROOT / "generated/input/H5_Game.exe"), fast_load=True)
        rows.append((0x00F5B998, pe.get_data(0x00F5B998 - pe.OPTIONAL_HEADER.ImageBase, 3048)))
        by_address = dict(rows)
        self.assertEqual(len(by_address[0x00F5DF30]), 228)
        self.assertEqual(len(by_address[0x00F5B998]), 3048)
        lib = build_mojo()
        for va, blob in rows:
            self.assertEqual(translate(lib, blob, profile=b"bytecode")[0], blob, hex(va))
        out = ROOT / "build/tests/shader_sizes"
        out.mkdir(parents=True, exist_ok=True)
        fixture = out / "pe_shaders.bin"
        fixture.write_bytes(struct.pack("<I", len(rows)) + b"".join(struct.pack("<II", va, len(blob)) + blob for va, blob in rows))
        harness = HARNESS.replace("@FIXTURES@", json.dumps(str(fixture)))
        compile_probe("shader_sizes", harness, {"scanner.h": scanner})

    def test_operand_counts_match_mojo(self):
        host = (ROOT / "android/host/d3d9_shader.c").read_text(encoding="utf-8")
        table = host[host.index("static const int8_t sm1_operands"):host.index("uint32_t d3d_shader_bytecode_size")]
        counts = list(map(int, re.findall(r"-?\d+", re.sub(r"/\*.*?\*/", "", table.split("{", 1)[1]))))
        vendor = (ROOT / "reference/mojoshader/mojoshader_internal.h").read_text(encoding="utf-8")
        rows = re.findall(r"^INSTRUCTION(?:_STATE)?\((\w+),\s*[^,]+,\s*\d+,\s*(\w+),", vendor, re.M)
        arity = {"NULL": 0, "D": 1, "S": 1, "SS": 2, "DS": 2, "DSS": 3, "DSSS": 4, "DSSSS": 5,
                 "DEF": 5, "DEFI": 5, "DEFB": 2, "DCL": 2, "SINCOS": 4, "TEXCRD": 1, "TEXLD": 1}
        self.assertEqual(counts, [-1 if opcode == "RESERVED" else arity[args] for opcode, args in rows])


if __name__ == "__main__":
    unittest.main()
