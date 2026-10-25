"""Relocate PE32 images without rewriting import tables or unrelated bytes."""
import hashlib
import struct

import pefile



def sha256(data):
    return hashlib.sha256(data).hexdigest()


def relocation_sites(raw):
    """Parse only relocations: full pefile write also rewrites import thunks."""
    pe = pefile.PE(data=raw, fast_load=True)
    if pe.FILE_HEADER.Machine != 0x14C or pe.OPTIONAL_HEADER.Magic != 0x10B:
        raise ValueError("Relocation requires a PE32 i386 image")
    pe.parse_data_directories(directories=[5])
    if not hasattr(pe, "DIRECTORY_ENTRY_BASERELOC"):
        raise ValueError("Missing relocation directory")
    sites, padding = [], 0
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            if entry.type == 0:
                padding += 1
                continue
            if entry.type != 3:
                raise ValueError(f"Unsupported PE32 relocation type {entry.type}")
            section = pe.get_section_by_rva(entry.rva)
            if section is None or entry.rva + 4 > section.VirtualAddress + section.SizeOfRawData:
                raise ValueError("Relocation target is not backed by four section bytes")
            offset = pe.get_offset_from_rva(entry.rva)
            if offset + 4 > len(raw):
                raise ValueError("Truncated relocation target")
            sites.append((entry.rva, offset))
    offsets = sorted(offset for _, offset in sites)
    if any(a + 4 > b for a, b in zip(offsets, offsets[1:])):
        raise ValueError("Duplicate or overlapping relocation targets")
    return pe, sites, padding


def rebase_image(raw, new_base):
    pe, sites, padding = relocation_sites(raw)
    old_base = pe.OPTIONAL_HEADER.ImageBase
    span = pe.OPTIONAL_HEADER.SizeOfImage
    if type(new_base) is not int or new_base < 0 or new_base & 0xFFFF or new_base + span > 0x100000000:
        raise ValueError("Private base must be aligned to 64 KiB and fit PE32")
    output = bytearray(raw)
    delta = new_base - old_base
    for rva, offset in sites:
        value = struct.unpack_from("<I", raw, offset)[0]
        struct.pack_into("<I", output, offset, (value + delta) & 0xFFFFFFFF)
    base_offset = pe.OPTIONAL_HEADER.get_field_absolute_offset("ImageBase")
    struct.pack_into("<I", output, base_offset, new_base)
    return bytes(output), {"original_base": hex(old_base), "base": hex(new_base),
        "span": hex(span), "delta": delta, "highlow_fixups": len(sites),
        "absolute_padding": padding, "imagebase_file_offset": base_offset,
        "original_sha256": sha256(raw), "rebased_sha256": sha256(output)}
