"""android/texconv on the PC: the launcher's texture conversion end to end.

Synthetic archives check the archive logic (which original wins, the
converted entries' dates, stored data, the manifest, removing originals with
raw copies and H5's wrapped entry count, refusals). The installed game, when
present, checks quality: every format against the DXT decode of real textures.
"""
import json
import os
import random
import struct
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/tests/texconv"
GAME_DATA = (ROOT / os.environ.get("HOMM5_GAME", "originals/tribes-of-the-east")) / "data"
DXT1, DXT3, DXT5 = b"DXT1", b"DXT3", b"DXT5"


def msvc_env():
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    installation = Path(subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
                                                text=True).strip())
    msvc = sorted((installation / "VC/Tools/MSVC").iterdir())[-1]
    sdk = Path(r"C:\Program Files (x86)\Windows Kits\10")
    version = sorted((sdk / "Lib").iterdir())[-1].name
    compiler = msvc / "bin/Hostx64/x64/cl.exe"
    env = os.environ.copy()
    env["PATH"] = str(compiler.parent) + os.pathsep + env["PATH"]
    env["INCLUDE"] = ";".join(map(str, [msvc / "include", sdk / f"Include/{version}/ucrt", sdk / f"Include/{version}/shared",
                                        sdk / f"Include/{version}/um"]))
    env["LIB"] = ";".join(map(str, [msvc / "lib/x64", sdk / f"Lib/{version}/ucrt/x64", sdk / f"Lib/{version}/um/x64"]))
    return compiler, env


def build_probe():
    """texconv_probe.exe from the Android sources; objects are reused while current."""
    compiler, env = msvc_env()
    objects = OUT / "obj"
    objects.mkdir(parents=True, exist_ok=True)
    astc = ["/DASTCENC_SSE=41", "/DASTCENC_POPCNT=1", "/DASTCENC_AVX=0", "/DASTCENC_NEON=0", "/DASTCENC_SVE=0", "/DASTCENC_F16C=0"]
    units = [(p, ["/std:c++17", "/EHsc", *astc]) for p in sorted((ROOT / "reference/astcenc").glob("*.cpp"))]
    units += [(ROOT / "reference/etcpak" / n, ["/std:c++17", "/EHsc", "/DBCDEC_STATIC", "/DBCDEC_IMPLEMENTATION"])
              for n in ("ProcessRGB.cpp", "Tables.cpp", "Dither.cpp", "Decode.cpp")]
    units += [(ROOT / "reference/zlib" / n, []) for n in ("adler32.c", "crc32.c", "inflate.c", "inftrees.c", "inffast.c", "zutil.c")]
    zlib = "/I" + str(ROOT / "reference/zlib")
    units += [(ROOT / "android/texconv/texconv.cpp", ["/std:c++17", "/EHsc", "/W4", "/WX", zlib, *astc]),
              (ROOT / "tests/texconv_probe.cpp", ["/std:c++17", "/EHsc", "/W4", "/WX", "/D_CRT_SECURE_NO_WARNINGS"])]
    built = []
    headers = max(p.stat().st_mtime for p in [ROOT / "android/texconv/texconv.h", *(ROOT / "reference/astcenc").glob("*.h"),
                                                *(ROOT / "reference/etcpak").glob("*.hpp")])
    for source, flags in units:
        obj = objects / (source.stem + ".obj")
        if not obj.exists() or obj.stat().st_mtime < max(source.stat().st_mtime, headers):
            result = subprocess.run([str(compiler), "/nologo", "/c", "/O2", "/MT", "/DNOMINMAX", "/D_CRT_SECURE_NO_WARNINGS", *flags,
                                     str(source), "/Fo" + str(obj)], env=env, text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
        built.append(str(obj))
    exe = OUT / "texconv_probe.exe"
    result = subprocess.run([str(compiler), "/nologo", "/MT", *built, "/Fe" + str(exe)], env=env, text=True, capture_output=True,
                            cwd=objects)
    assert result.returncode == 0, result.stdout + result.stderr
    return exe


def run(exe, *args, expect=0):
    result = subprocess.run([str(exe), *map(str, args)], text=True, capture_output=True, timeout=600)
    assert result.returncode == expect, f"{args}: {result.returncode}\n{result.stdout}\n{result.stderr}"
    return result.stdout


# ------------------------------------------------------------------ fixtures

def dds(width, height, fourcc, levels, blocks_for, cube=False):
    """A DDS whose levels' blocks come from blocks_for(fourcc, count)."""
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<IIIIIII", header, 4, 124, 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000 | (0x20000 if levels > 1 else 0),
                     height, width, 0, 0, levels)
    struct.pack_into("<II4s", header, 76, 32, 4, fourcc)
    struct.pack_into("<II", header, 108, 0x1000 | (0x400008 if levels > 1 else 0), 0xFE00 if cube else 0)
    payload = bytearray()
    for _ in range(6 if cube else 1):
        for level in range(levels):
            w, h = max(1, width >> level), max(1, height >> level)
            payload += blocks_for(fourcc, ((w + 3) // 4) * ((h + 3) // 4))
    return bytes(header) + bytes(payload)


def blocks(kind):
    rng = random.Random(kind)

    def make(fourcc, count):
        out = bytearray()
        for _ in range(count):
            a, b = rng.randrange(1, 65536), rng.randrange(0, 65536)
            hi, lo = max(a, b), min(a, b)
            if hi == lo:
                hi, lo = min(hi + 1, 65535), max(lo - 1, 0)
            indices = rng.getrandbits(32)
            if fourcc == DXT1:
                if kind == "alpha":
                    out += struct.pack("<HHI", lo, hi, indices | 3)        # 3-colour mode, texel 0 transparent
                else:
                    out += struct.pack("<HHI", hi, lo, indices)
                continue
            if fourcc == DXT3:
                out += b"\xff" * 8 if kind == "opaque" else rng.getrandbits(64).to_bytes(8, "little")
            else:
                out += bytes([255, 255, 0, 0, 0, 0, 0, 0]) if kind == "opaque" else rng.getrandbits(64).to_bytes(8, "little")
            out += struct.pack("<HHI", hi, lo, indices)
        return bytes(out)
    return make


def zinfo(name, date_time, method=zipfile.ZIP_DEFLATED):
    info = zipfile.ZipInfo(name, date_time)
    info.compress_type = method
    return info


def later(date_time):
    import datetime
    return (datetime.datetime(*date_time) + datetime.timedelta(seconds=2)).timetuple()[:6]


def make_game(root, many=False):
    """data/data.pak (2007), a2p1-data.pak (2008, a newer duplicate), aaa.pak (an older one)."""
    data = root / "data"
    data.mkdir(parents=True)
    textures = {
        "Textures/Opaque1.dds": dds(64, 32, DXT1, 7, blocks("opaque")),
        "Textures/Alpha1.dds": dds(30, 18, DXT1, 1, blocks("alpha")),
        "Textures/Alpha3.dds": dds(16, 16, DXT3, 5, blocks("alpha")),
        "Textures/Opaque3.dds": dds(8, 8, DXT3, 4, blocks("opaque")),
        "Textures/Five.dds": dds(4, 4, DXT5, 3, blocks("alpha")),
        "Textures/Cube.dds": dds(8, 8, DXT1, 4, blocks("opaque"), cube=True),
        "Textures/Dup.dds": dds(8, 8, DXT1, 1, blocks("opaque")),
    }
    base_time = (2007, 8, 3, 23, 59, 58)        # +2 s carries into the next day
    with zipfile.ZipFile(data / "data.pak", "w") as z:
        z.writestr(zinfo("Textures/", base_time), b"")
        for name, payload in textures.items():
            z.writestr(zinfo(name, base_time), payload)
        z.writestr(zinfo("Text/readme.txt", base_time), b"keep me" * 100)
        z.writestr(zinfo("Textures/Plain.dds", base_time), dds(4, 4, b"\x15\x00\x00\x00", 1, lambda f, n: b"\0" * 64))
        z.writestr(zinfo("Stored/data.bin", base_time, zipfile.ZIP_STORED), bytes(range(256)) * 9)
        if many:
            for i in range(66000):
                z.writestr(zinfo(f"Many/{i:05d}.txt", base_time, zipfile.ZIP_STORED), b"x")
    newer = dds(8, 8, DXT3, 4, blocks("alpha"))
    with zipfile.ZipFile(data / "a2p1-data.pak", "w") as z:
        z.writestr(zinfo("Textures/Dup.dds", (2008, 8, 3, 12, 0, 0)), newer)
    with zipfile.ZipFile(data / "aaa.pak", "w") as z:
        z.writestr(zinfo("Textures\\Opaque3.dds", (2006, 1, 1, 0, 0, 0)), dds(8, 8, DXT1, 1, blocks("opaque")))
    textures["Textures/Dup.dds"] = newer
    return textures, base_time


def header_fields(data):
    marker, version, original, stored, flags = struct.unpack_from("<5I", data, 36)
    return {"fourcc": data[84:88], "marker": marker, "version": version, "original": struct.pack("<I", original),
            "stored": stored, "flags": flags, "mips": struct.unpack_from("<I", data, 28)[0],
            "size": struct.unpack_from("<II", data, 12)}


class TexconvTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = build_probe()

    def fresh(self, name, many=False):
        root = OUT / name
        if root.exists():
            import shutil
            shutil.rmtree(root)
        textures, base_time = make_game(root, many)
        return root, textures, base_time

    def test_etc2_conversion_and_removal(self):
        root, textures, base_time = self.fresh("game-etc2", many=True)
        scan = run(self.exe, "scan", root)
        self.assertIn("scan textures 7 ", scan)
        run(self.exe, "convert", root, "etc2", 3)
        data = root / "data"
        manifest = json.loads((data / "zz_port_textures.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["format"], manifest["textures"], manifest["originals_removed"]), ("etc2", 6, False))
        with zipfile.ZipFile(data / "zz_port_textures.pak") as z:
            self.assertIsNone(z.testzip())
            infos = {i.filename: i for i in z.infolist()}
            self.assertEqual(set(infos), set(textures) - {"Textures/Alpha1.dds"})   # a transparent DXT1 stays
            expected = {
                "Textures/Opaque1.dds": (b"H5E1", DXT1, 7),
                "Textures/Alpha3.dds": (b"H5E2", DXT3, 5),
                "Textures/Opaque3.dds": (b"H5E1", DXT3, 4),
                "Textures/Five.dds": (b"H5E2", DXT5, 3),
                "Textures/Cube.dds": (b"H5E1", DXT1, 4),
                "Textures/Dup.dds": (b"H5E2", DXT3, 4),
            }
            for name, (fourcc, original, stored) in expected.items():
                info = infos[name]
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED, name)
                winner = (2008, 8, 3, 12, 0, 2) if name == "Textures/Dup.dds" else later(base_time)
                self.assertEqual(info.date_time, tuple(winner), name)
                converted = z.read(name)
                fields = header_fields(converted)
                self.assertEqual((fields["fourcc"], fields["original"], fields["stored"]), (fourcc, original, stored), name)
                self.assertEqual((fields["marker"], fields["version"]), (0x43543548, 2), name)
                source = textures[name]
                # The original's header and layout: only the FourCC and the port fields differ.
                self.assertEqual(converted[:36], source[:36], name)
                self.assertEqual(converted[56:84] + converted[88:128], source[56:84] + source[88:128], name)
                self.assertEqual(len(converted), len(source), name)
                self.assertEqual(fields["mips"], stored, name)
                self.assertEqual(fields["flags"] & 1, 1 if fourcc == b"H5E1" else 0, name)
                # Each level's converted blocks start its DXT slot; the rest of the slot is zero.
                w, h = fields["size"][1], fields["size"][0]
                block, slot_block = (8 if fourcc == b"H5E1" else 16), (8 if original == DXT1 else 16)
                at = 128
                for _ in range(6 if name == "Textures/Cube.dds" else 1):
                    for l in range(stored):
                        blocks = ((max(1, w >> l) + 3) // 4) * ((max(1, h >> l) + 3) // 4)
                        self.assertEqual(converted[at + blocks * block:at + blocks * slot_block],
                                         bytes(blocks * (slot_block - block)), (name, l))
                        at += blocks * slot_block
                self.assertEqual(at, len(converted), name)
            # Every level decodes back; the opaque top level stays close to its DXT source.
            path = OUT / "decoded.rgba"
            sample = OUT / "converted.dds"
            sample.write_bytes(z.read("Textures/Opaque1.dds"))
            for level in range(7):
                run(self.exe, "decode", sample, level, path)
                self.assertEqual(len(path.read_bytes()), max(1, 64 >> level) * max(1, 32 >> level) * 4)
            run(self.exe, "decode", sample, 7, path, expect=3)
        scan = run(self.exe, "scan", root)
        self.assertIn("converted 1 6 ", scan)
        # Removing the originals: the shadowed DDS entries go, everything else is copied as it was.
        before = {p.name: zipfile.ZipFile(p) for p in data.glob("*.pak") if p.name != "zz_port_textures.pak"}
        raw = {name: {i.filename: z.read(i) for i in z.infolist()} for name, z in before.items()}
        for z in before.values():
            z.close()
        run(self.exe, "remove-originals", root)
        with zipfile.ZipFile(data / "data.pak") as z:
            names = set(z.namelist())
            self.assertFalse(names & {"Textures/Opaque1.dds", "Textures/Alpha3.dds", "Textures/Five.dds",
                                      "Textures/Cube.dds", "Textures/Dup.dds", "Textures/Opaque3.dds"})
            for name in names:
                self.assertEqual(z.read(name), raw["data.pak"][name], name)
            self.assertIn("Textures/Plain.dds", names)
            self.assertIn("Textures/Alpha1.dds", names)   # never converted, so kept
            self.assertEqual(len(names), len(raw["data.pak"]) - 6)
        tail = (data / "data.pak").read_bytes()[-22:]
        self.assertEqual(struct.unpack_from("<HH", tail, 8), ((len(raw["data.pak"]) - 6) & 0xFFFF,) * 2)   # wrapped as H5's own
        with zipfile.ZipFile(data / "a2p1-data.pak") as z:
            self.assertEqual(z.namelist(), [])
        with zipfile.ZipFile(data / "aaa.pak") as z:
            self.assertEqual(z.namelist(), [])          # older than the converted copy too
        manifest = json.loads((data / "zz_port_textures.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["originals_removed"])
        out = run(self.exe, "remove-converted", root, expect=2)
        self.assertIn("only copy", out)
        out = run(self.exe, "convert", root, "astc", expect=2)
        self.assertIn("removed", out)

    def test_astc_conversion_and_undo(self):
        root, textures, _ = self.fresh("game-astc")
        run(self.exe, "convert", root, "astc")
        data = root / "data"
        with zipfile.ZipFile(data / "zz_port_textures.pak") as z:
            kinds = {name: header_fields(z.read(name))["fourcc"] for name in z.namelist()}
        self.assertEqual(kinds["Textures/Opaque1.dds"], b"H5E1")   # DXT1 slots take ETC2 only
        self.assertEqual(kinds["Textures/Alpha3.dds"], b"H5A4")
        self.assertEqual(kinds["Textures/Opaque3.dds"], b"H5A4")
        self.assertNotIn("Textures/Alpha1.dds", kinds)
        run(self.exe, "remove-converted", root)
        self.assertFalse((data / "zz_port_textures.pak").exists() or (data / "zz_port_textures.json").exists())
        self.assertEqual(len(zipfile.ZipFile(data / "data.pak").namelist()), 11)

    @unittest.skipUnless((GAME_DATA / "data.pak").exists(), "no installed game")
    def test_real_texture_quality(self):
        samples = OUT / "samples"
        samples.mkdir(parents=True, exist_ok=True)
        rng = random.Random(5)
        with zipfile.ZipFile(GAME_DATA / "data.pak") as z:
            names = [i for i in z.infolist() if i.filename.lower().endswith(".dds") and 64 * 1024 < i.file_size < 3 * 2**20]
            picked = []
            for info in rng.sample(names, 200):
                data = z.read(info)
                if data[84:88] in (DXT1, DXT3) and len(picked) < 16:
                    path = samples / f"{len(picked):02d}.dds"
                    path.write_bytes(data)
                    picked.append(path)
        out = run(self.exe, "quality", *picked)
        print(out)
        rows = [line for line in out.splitlines() if " | etc2 " in line]
        self.assertGreaterEqual(len(rows), len(picked) - 4)   # transparent DXT1s are kept
        for row in rows:
            etc2, astc = row.split(" | ")[1:3]
            self.assertGreater(float(etc2.split()[2]), 28.0, row)
            self.assertGreater(float(astc.split()[2]), 28.0, row)


if __name__ == "__main__":
    unittest.main()
