#!/usr/bin/env python3
"""List and extract the resources baked into a PE's `.rsrc` section.

A Win32 game keeps real content in its executable: the splash screen, the
cursor set, the dialog templates, every string it shows you. A recompile needs
them, because the lifted code will call `LoadBitmap`, `LoadCursor` and
`LoadString` and expect them to be there -- and reading them out of the binary
beats shipping a copy of the game's art.

    python tools/pe/rsrc.py game.exe                 # what is in there
    python tools/pe/rsrc.py game.exe -o out/         # get it out

BITMAP needs a header put back on
---------------------------------
A `BITMAP` resource is a `.bmp` with the 14-byte `BITMAPFILEHEADER` removed --
the loader knows where it is, so the file does not have to say. Written out
raw, nothing will open it. Rebuilding that header means computing where the
pixels start, which means knowing the palette size, which the header only
states sometimes: `biClrUsed` is 0 for "all of them", so for <= 8bpp the real
count is `1 << biBitCount`. Get that wrong and the image opens, and is
diagonally sheared garbage.

Force Commander's `Focom.exe` carries exactly one: 640x480, 8bpp, 308,264
bytes, which is 307,200 pixels + a 40-byte header + a 1,024-byte palette. It
is the loading screen.

ICON and CURSOR are the same idea one level further -- each entry is a
headerless DIB, and the matching `GROUP_ICON` / `GROUP_CURSOR` holds the
directory that pairs them with sizes and hotspots. Those are written out raw:
rebuilding `.ico` is a separate job and a recomp usually wants the pixels
rather than the container.
"""
import argparse
import os
import struct
import sys

TYPES = {1: "CURSOR", 2: "BITMAP", 3: "ICON", 4: "MENU", 5: "DIALOG",
         6: "STRING", 7: "FONTDIR", 8: "FONT", 9: "ACCELERATOR",
         10: "RCDATA", 11: "MESSAGETABLE", 12: "GROUP_CURSOR",
         14: "GROUP_ICON", 16: "VERSION", 17: "DLGINCLUDE",
         19: "PLUGPLAY", 20: "VXD", 21: "ANICURSOR", 22: "ANIICON",
         23: "HTML", 24: "MANIFEST"}


def _sections(d):
    pe = struct.unpack_from('<I', d, 0x3C)[0]
    if d[pe:pe + 4] != b'PE\x00\x00':
        raise ValueError("not a PE")
    nsec = struct.unpack_from('<H', d, pe + 6)[0]
    optsz = struct.unpack_from('<H', d, pe + 20)[0]
    out = []
    for i in range(nsec):
        o = pe + 24 + optsz + i * 40
        name = d[o:o + 8].rstrip(b'\x00').decode('latin1')
        vsz, va, rsz, ro = struct.unpack_from('<IIII', d, o + 8)
        out.append((name, va, vsz, ro, rsz))
    return out


def _walk(d, rsrc_off, node, path=()):
    """Every leaf under a resource directory node, as (path, rva, size)."""
    nnamed, nid = struct.unpack_from('<HH', d, node + 12)
    for i in range(nnamed + nid):
        e = node + 16 + i * 8
        name, child = struct.unpack_from('<II', d, e)
        key = ("#%d" % (name & 0x7FFFFFFF)) if (name & 0x80000000) else name
        if child & 0x80000000:
            yield from _walk(d, rsrc_off, rsrc_off + (child & 0x7FFFFFFF),
                             path + (key,))
        else:
            rva, size = struct.unpack_from('<II', d, rsrc_off + child)[:2]
            yield path + (key,), rva, size


def bitmap_file_header(body):
    """The 14 bytes a BITMAP resource is missing, or None if it is not one."""
    if len(body) < 40:
        return None
    hdr_size, = struct.unpack_from('<I', body, 0)
    if hdr_size < 12 or hdr_size > 124:
        return None
    if hdr_size >= 16:
        bpp, = struct.unpack_from('<H', body, 14)
    else:
        bpp = 0
    clr_used, = struct.unpack_from('<I', body, 32) if hdr_size >= 36 else (0,)
    # biClrUsed == 0 means "every colour the depth allows". Assuming it is
    # really zero puts the pixel offset before the palette, and the image
    # opens as a diagonal smear rather than failing outright.
    if clr_used == 0 and 0 < bpp <= 8:
        clr_used = 1 << bpp
    offbits = 14 + hdr_size + clr_used * 4
    return b'BM' + struct.pack('<IHHI', 14 + len(body), 0, 0, offbits)


def strings(body):
    """A STRING resource is 16 length-prefixed UTF-16 strings, blanks included."""
    out, off = [], 0
    while off + 2 <= len(body):
        n, = struct.unpack_from('<H', body, off)
        off += 2
        out.append(body[off:off + n * 2].decode('utf-16-le', 'replace'))
        off += n * 2
    return out


def read(path):
    """[(type_name, path, bytes)] for every resource in the file."""
    with open(path, 'rb') as f:
        d = f.read()
    secs = _sections(d)
    rsrc = next((s for s in secs if s[0] == '.rsrc'), None)
    if not rsrc:
        return []
    _, _, _, ro, _ = rsrc

    def to_off(rva):
        for _n, va, vsz, fo, _rs in secs:
            if va <= rva < va + vsz:
                return fo + (rva - va)
        return None

    out = []
    for p, rva, size in _walk(d, ro, ro):
        fo = to_off(rva)
        if fo is None or fo + size > len(d):
            continue
        tname = TYPES.get(p[0], f"type{p[0]}") if isinstance(p[0], int) else str(p[0])
        out.append((tname, p, d[fo:fo + size]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("exe", nargs="?")
    ap.add_argument("-o", "--out", help="directory to extract into")
    ap.add_argument("--strings", action="store_true",
                    help="print the STRING tables instead of writing them")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        demo()
        return 0
    if not args.exe:
        ap.error("an executable is required (or --selftest)")

    res = read(args.exe)
    if not res:
        print("no .rsrc section, or nothing in it")
        return 0

    by_type = {}
    for tname, _p, body in res:
        n, total = by_type.get(tname, (0, 0))
        by_type[tname] = (n + 1, total + len(body))
    print(f"{os.path.basename(args.exe)}: {len(res)} resources")
    for t in sorted(by_type, key=lambda k: -by_type[k][1]):
        n, total = by_type[t]
        print(f"   {t:<14} {n:>4}   {total:>10,} bytes")

    if args.strings:
        for tname, p, body in res:
            if tname != "STRING":
                continue
            block = p[1] if len(p) > 1 else 0
            for i, s in enumerate(strings(body)):
                if s.strip():
                    print(f"   {tname} {block}:{i}  {s!r}")

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        n = 0
        for tname, p, body in res:
            stem = f"{tname}_" + "_".join(str(x) for x in p[1:])
            if tname == "BITMAP":
                h = bitmap_file_header(body)
                if h:
                    body, stem = h + body, stem + ".bmp"
            with open(os.path.join(args.out, stem), "wb") as f:
                f.write(body)
            n += 1
        print(f"wrote {n} files to {args.out}")
    return 0


def demo():
    """One runnable check: the header maths that makes a BITMAP openable."""
    # 8bpp with biClrUsed == 0 -- the case that shears the image if believed.
    hdr = struct.pack('<IiiHHIIiiII', 40, 4, 4, 1, 8, 0, 0, 0, 0, 0, 0)
    body = hdr + b'\x00' * (256 * 4) + b'\x00' * 16
    fh = bitmap_file_header(body)
    assert fh[:2] == b'BM'
    offbits, = struct.unpack_from('<I', fh, 10)
    assert offbits == 14 + 40 + 256 * 4, offbits
    assert struct.unpack_from('<I', fh, 2)[0] == 14 + len(body)

    # 24bpp has no palette at all, so the pixels start right after the header.
    hdr24 = struct.pack('<IiiHHIIiiII', 40, 4, 4, 1, 24, 0, 0, 0, 0, 0, 0)
    fh24 = bitmap_file_header(hdr24 + b'\x00' * 48)
    assert struct.unpack_from('<I', fh24, 10)[0] == 14 + 40

    # An explicit biClrUsed is believed rather than recomputed.
    hdr16 = struct.pack('<IiiHHIIiiII', 40, 4, 4, 1, 8, 0, 0, 0, 0, 16, 0)
    fh16 = bitmap_file_header(hdr16 + b'\x00' * 64)
    assert struct.unpack_from('<I', fh16, 10)[0] == 14 + 40 + 16 * 4

    # Not a DIB header at all.
    assert bitmap_file_header(b'\x01\x00\x00\x00' + b'\x00' * 40) is None
    assert bitmap_file_header(b'short') is None

    # STRING blocks are 16 length-prefixed UTF-16 runs; empty slots are real.
    blk = struct.pack('<H', 0) + struct.pack('<H', 2) + "hi".encode('utf-16-le')
    assert strings(blk) == ["", "hi"], strings(blk)

    print("rsrc.py self-test OK")


if __name__ == "__main__":
    sys.exit(main())
