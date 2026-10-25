"""Find why the Android port's LAN game checksum differs from the original's.

The checksum a LAN client must share with the host is adler32 over the
CalcCheckSum of fourteen GameMechanics reference tables, xor the map's (see
android/host/nubi_log.c). Every NDb object caches its CalcCheckSum at +0x40, so
the object graphs of two installations can be compared without recomputing
anything: this walks the same tables in the running original game (read-only,
ReadProcessMemory) and in a guest memory dump of the port (verbose logging plus
a "dump_guest" file in the user data, written at the checksum mismatch), and
descends through every pointer to an object or array whose cached checksums
differ, down to the words that differ.

    python -X utf8 tools/lan_checksum_diff.py --pid PID --dump guest_rw.dump
"""
import argparse
import bisect
import ctypes as c
from ctypes import wintypes as w
import struct

TABLES = {
    0xE58E68: "ArenaBuildingsStats", 0xE91C98: "CombatArenaTypes", 0xE8D930: "CampaignBonus",
    0xE4F2D0: "CombatLog", 0xE179A0: "GhostMode/Skills", 0xE179CC: "GhostMode/Classes",
    0xE7974C: "Creatures", 0xE79778: "WarMachines", 0xE4BEE0: "UndividedSpells",
    0xE797A4: "MicroArtifactEffects", 0xE4BE88: "Artifacts", 0xE4BF50: "Skills",
    0xE4BF0C: "CombatAbilities", 0xE0CA3C: "TownTypesInfo",
}
RDATA = (0xE00000, 0xF80000)        # H5_Game.exe vtables


class Live:
    """The original game's memory, read-only."""
    def __init__(self, pid):
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        self.k.OpenProcess.restype = w.HANDLE
        self.k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        self.handle = self.k.OpenProcess(0x0400 | 0x0010, False, pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())

    def read(self, address, size):
        buffer, got = c.create_string_buffer(size), c.c_size_t()
        if not self.k.ReadProcessMemory(self.handle, c.c_void_p(address), buffer, size, c.byref(got)):
            return None
        return buffer.raw[:got.value] if got.value == size else None

    def regions(self):
        class MBI(c.Structure):
            _fields_ = [("BaseAddress", c.c_void_p), ("AllocationBase", c.c_void_p), ("AllocationProtect", w.DWORD),
                        ("PartitionId", w.WORD), ("RegionSize", c.c_size_t), ("State", w.DWORD),
                        ("Protect", w.DWORD), ("Type", w.DWORD)]
        self.k.VirtualQueryEx.argtypes = [w.HANDLE, c.c_void_p, c.POINTER(MBI), c.c_size_t]
        self.k.VirtualQueryEx.restype = c.c_size_t
        address = 0x10000
        while address < 0x7FFF0000:
            mbi = MBI()
            if not self.k.VirtualQueryEx(self.handle, c.c_void_p(address), c.byref(mbi), c.sizeof(mbi)):
                return
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == 0x1000 and mbi.Protect & 0x44 and not mbi.Protect & 0x100 and mbi.Type != 0x1000000:
                for offset in range(0, size, 1 << 22):
                    data = self.read(base + offset, min(1 << 22, size - offset))
                    if data:
                        yield base + offset, data
            address = base + size


class Dump:
    """A guest memory dump: records of {base, size, bytes} (android/host/memory.c void_vm_dump)."""
    def __init__(self, path):
        data = open(path, "rb").read()
        self.bases, self.blocks, at = [], [], 0
        while at + 8 <= len(data):
            base, size = struct.unpack_from("<II", data, at)
            self.bases.append(base)
            self.blocks.append(memoryview(data)[at + 8:at + 8 + size])
            at += 8 + size

    def read(self, address, size):
        i = bisect.bisect_right(self.bases, address) - 1
        if i < 0 or address + size > self.bases[i] + len(self.blocks[i]):
            return None
        return bytes(self.blocks[i][address - self.bases[i]:address - self.bases[i] + size])

    def regions(self):
        for base, block in zip(self.bases, self.blocks):
            if base >= 0x01100000:                 # past the game image's data
                yield base, bytes(block)


def u32(memory, address):
    data = memory.read(address, 4)
    return struct.unpack("<I", data)[0] if data else None


def find_tables(memory):
    """The fourteen table objects, by vtable, preferring the one with a computed checksum."""
    found = {}
    needles = {struct.pack("<I", v): v for v in TABLES}
    for base, data in memory.regions():
        for needle, vtable in needles.items():
            at = data.find(needle)
            while at >= 0:
                if at % 4 == 0:
                    cached = struct.unpack_from("<I", data, at + 0x40)[0] if at + 0x44 <= len(data) else 0
                    if cached and (vtable not in found or not found[vtable][1]):
                        found[vtable] = (base + at, cached)
                    elif vtable not in found:
                        found[vtable] = (base + at, cached)
                at = data.find(needle, at + 1)
    return found


def is_object(memory, address):
    vtable = u32(memory, address) if address else None
    return vtable is not None and RDATA[0] <= vtable < RDATA[1] and vtable % 4 == 0


class Walker:
    def __init__(self, original, port, depth):
        self.original, self.port, self.depth, self.seen = original, port, depth, set()

    def object(self, a, b, path, level):
        if (a, b) in self.seen or level > self.depth:
            return
        self.seen.add((a, b))
        va, vb = u32(self.original, a), u32(self.port, b)
        ca, cb = u32(self.original, a + 0x40), u32(self.port, b + 0x40)
        if None in (va, vb, ca, cb):
            return
        if va != vb:
            print(f"{'  ' * level}{path}: different types {va:08X} / {vb:08X}")
            return
        if ca == cb:
            return
        print(f"{'  ' * level}{path}: object vt {va:08X} checksum {ca:08X} / {cb:08X} (original {a:08X}, port {b:08X})")
        self.words(a, b, 0x44, 0x400, path, level + 1)

    def words(self, a, b, start, end, path, level):
        """Compare words, following pointers present on both sides."""
        for offset in range(start, end, 4):
            wa, wb = u32(self.original, a + offset), u32(self.port, b + offset)
            if wa is None or wb is None:
                return
            if wa == wb:
                continue
            here = f"{path}+{offset:X}"
            pa, pb = self.pointer(self.original, wa), self.pointer(self.port, wb)
            if pa and pb:
                if is_object(self.original, wa) and is_object(self.port, wb):
                    if u32(self.original, wa) == 0 or wa in (a,):
                        continue
                    self.object(wa, wb, here, level)
                    continue
                # A vector {begin, end, capacity}: compare the elements.
                ea, eb = u32(self.original, a + offset + 4), u32(self.port, b + offset + 4)
                if ea is not None and eb is not None and 0 <= ea - wa < 0x10000 and ea - wa == eb - wb:
                    if (wa, wb) not in self.seen:
                        self.seen.add((wa, wb))
                        self.array(wa, wb, ea - wa, here, level)
                continue
            if pa != pb or not pa:
                print(f"{'  ' * level}{here}: {wa:08X} / {wb:08X}{self.as_float(wa, wb)}")

    def array(self, a, b, size, path, level):
        for offset in range(0, size, 4):
            wa, wb = u32(self.original, a + offset), u32(self.port, b + offset)
            if wa == wb or wa is None or wb is None:
                continue
            here = f"{path}[{offset:X}]"
            if self.pointer(self.original, wa) and self.pointer(self.port, wb):
                if is_object(self.original, wa) and is_object(self.port, wb):
                    self.object(wa, wb, here, level)
                continue
            print(f"{'  ' * level}{here}: {wa:08X} / {wb:08X}{self.as_float(wa, wb)}")

    @staticmethod
    def pointer(memory, value):
        return 0x10000 <= value < 0xFFFF0000 and value % 4 == 0 and memory.read(value, 4) is not None

    @staticmethod
    def as_float(wa, wb):
        fa, fb = struct.unpack("<f", struct.pack("<I", wa))[0], struct.unpack("<f", struct.pack("<I", wb))[0]
        return f"  ({fa!r} / {fb!r})" if all(abs(x) < 1e9 and (x == 0 or abs(x) > 1e-9) for x in (fa, fb)) else ""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pid", type=int, required=True, help="the original H5_Game.exe")
    parser.add_argument("--dump", required=True, help="the port's guest_rw.dump")
    parser.add_argument("--depth", type=int, default=8)
    args = parser.parse_args()
    original, port = Live(args.pid), Dump(args.dump)
    tables_a, tables_b = find_tables(original), find_tables(port)
    walker = Walker(original, port, args.depth)
    for vtable, name in TABLES.items():
        (a, ca), (b, cb) = tables_a.get(vtable, (0, 0)), tables_b.get(vtable, (0, 0))
        print(f"{name}: {ca:08X} / {cb:08X}{'' if ca == cb else '  DIFFERENT'}")
        if ca == cb or not a or not b:
            continue
        # Entries {cached checksum, id, ...}, of a size per table: compared word by word.
        begin_a, end_a = u32(original, a + 0x44), u32(original, a + 0x48)
        begin_b, end_b = u32(port, b + 0x44), u32(port, b + 0x48)
        if end_a - begin_a != end_b - begin_b:
            print(f"  entries {end_a - begin_a} / {end_b - begin_b} bytes")
            continue
        walker.array(begin_a, begin_b, end_a - begin_a, name, 1)


if __name__ == "__main__":
    main()
