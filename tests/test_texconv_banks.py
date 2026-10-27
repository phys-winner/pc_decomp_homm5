"""Actual isolated PAK conversion/removal for the three installed data banks."""
import hashlib
import json
from pathlib import Path
import struct
import os
import stat
import tempfile
import unittest
import zipfile
import zlib

from test_texconv import ROOT, OUT, build_probe, dds, DXT1, DXT3, later, run


def pak_path(root, bank):
    return root / bank / {'data': 'base.pak', 'DataLS': 'p6-data.pak', 'dataa1': 'a1p1-data.pak'}[bank]


def image_name(bank):
    return 'Textures/' + bank + '.dds'


def converted_path(root, bank):
    return root / bank / ('zz_port_textures.pak' if bank == 'data' else 'zz_port_textures_v2.pak')


class TextureBankTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exe = build_probe()

    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix='banks-', dir=OUT)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for day, (bank, color) in enumerate((('data', 0xF800), ('DataLS', 0x001F), ('dataa1', 0x07E0)), 2):
            directory = root / bank
            directory.mkdir()
            image = dds(4, 4, DXT3, 1, lambda _, n: (b'\xff' * 8 + struct.pack('<HHI', color, color, 0)) * n)
            with zipfile.ZipFile(pak_path(root, bank), 'w', zipfile.ZIP_DEFLATED) as archive:
                info = zipfile.ZipInfo(image_name(bank), (2008, 1, day, 3, 4, 6))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, image)
                archive.writestr('keep.txt', bank.encode())
        (root / 'unrelated').mkdir()
        (root / 'unrelated/keep.txt').write_text('untouched')
        return root

    @staticmethod
    def snapshot(root):
        return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in root.rglob('*') if path.is_file()}

    def test_banks_keep_distinct_payloads_formats_timestamps_and_removal(self):
        root = self.fixture()
        payloads = []
        for day, (bank, format) in enumerate((('data', 'etc2'), ('DataLS', 'astc'), ('dataa1', 'etc2')), 2):
            self.assertIn('scan textures 1 ', run(self.exe, 'scan-bank', root, bank))
            run(self.exe, 'convert-bank', root, bank, format, 2)
            manifest = json.loads((root / bank / 'zz_port_textures.json').read_text())
            self.assertEqual((manifest['bank'], manifest['format'], manifest['originals_removed']),
                             (bank.lower(), format, False))
            with zipfile.ZipFile(converted_path(root, bank)) as archive:
                self.assertEqual(archive.namelist(), [image_name(bank)])
                original_date = (2008, 1, day, 3, 4, 6)
                self.assertEqual(archive.getinfo(image_name(bank)).date_time,
                                 later(original_date) if bank == 'data' else original_date)
                if bank != 'data':
                    priority = 2 if bank == 'DataLS' else 3
                    self.assertEqual(archive.getinfo(image_name(bank)).external_attr, 0x48540000 | ((priority + 1) << 8))
                    with zipfile.ZipFile(pak_path(root, bank)) as original:
                        crc = zlib.crc32(original.read(image_name(bank)))
                    self.assertEqual(struct.unpack_from('<I', archive.read(image_name(bank)), 60)[0], crc)
                payloads.append(archive.read(image_name(bank)))
        self.assertEqual(len(set(payloads)), 3)
        # The old API still sees only the original data bank.
        self.assertIn('converted 1 1 ', run(self.exe, 'scan', root))
        before = self.snapshot(root)
        run(self.exe, 'remove-originals-bank', root, 'DataLS')
        after = self.snapshot(root)
        for name in before:
            if not name.startswith('DataLS/'):
                self.assertEqual(after[name], before[name], name)
        with zipfile.ZipFile(pak_path(root, 'DataLS')) as archive:
            self.assertEqual(archive.namelist(), ['keep.txt'])
            self.assertEqual(archive.read('keep.txt'), b'DataLS')
        only_copy = self.snapshot(root)
        run(self.exe, 'remove-converted-bank', root, 'DataLS', expect=2)
        run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1, expect=2)
        self.assertEqual(self.snapshot(root), only_copy)

    def test_unknown_or_missing_bank_never_changes_files(self):
        root = self.fixture()
        before = self.snapshot(root)
        for bank in ('', '../data', 'data/..', 'bin', 'dataa2'):
            for operation in ('scan-bank', 'convert-bank', 'remove-originals-bank', 'remove-converted-bank'):
                with self.subTest(bank=bank, operation=operation):
                    args = ('etc2', 1) if operation == 'convert-bank' else ()
                    run(self.exe, operation, root, bank, *args, expect=2)
                    self.assertEqual(self.snapshot(root), before)
        (root / 'DataLS').rename(root / 'absent')
        before = self.snapshot(root)
        run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1, expect=2)
        self.assertEqual(self.snapshot(root), before)

    def test_wrong_bank_manifest_and_corrupt_payload_preserve_originals(self):
        root = self.fixture()
        run(self.exe, 'convert-bank', root, 'data', 'etc2', 1)
        run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1)
        manifest = root / 'DataLS/zz_port_textures.json'
        original_manifest = manifest.read_bytes()
        manifest.write_bytes((root / 'data/zz_port_textures.json').read_bytes())
        before = self.snapshot(root)
        for operation in ('scan-bank', 'remove-originals-bank', 'remove-converted-bank'):
            run(self.exe, operation, root, 'DataLS', expect=2)
            self.assertEqual(self.snapshot(root), before)
        manifest.write_bytes(original_manifest)
        pak = converted_path(root, 'DataLS')
        original_pak = pak.read_bytes()
        with zipfile.ZipFile(pak) as archive:
            info = archive.getinfo(image_name('DataLS'))
            at = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + info.file_size - 1
        corrupted = bytearray(original_pak)
        corrupted[at] ^= 1
        pak.write_bytes(corrupted)
        before = self.snapshot(root)
        run(self.exe, 'remove-originals-bank', root, 'DataLS', expect=2)
        self.assertEqual(self.snapshot(root), before)
        pak.write_bytes(original_pak)
        run(self.exe, 'remove-originals-bank', root, 'DataLS')

    def test_orphan_conversion_is_preserved_and_legacy_data_manifest_still_loads(self):
        root = self.fixture()
        run(self.exe, 'convert', root, 'etc2', 1)
        manifest = root / 'data/zz_port_textures.json'
        text = json.loads(manifest.read_text())
        del text['bank']
        manifest.write_text(json.dumps(text, indent=2) + '\n')
        self.assertIn('converted 1 1 ', run(self.exe, 'scan', root))
        manifest.unlink()
        before = self.snapshot(root)
        for operation in ('scan-bank', 'remove-originals-bank', 'remove-converted-bank'):
            run(self.exe, operation, root, 'data', expect=2)
            self.assertEqual(self.snapshot(root), before)
        run(self.exe, 'convert-bank', root, 'data', 'etc2', 1, expect=2)
        self.assertEqual(self.snapshot(root), before)

    def test_only_copy_guard_precedes_archive_replacement_and_is_resumable(self):
        root = self.fixture()
        run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1)
        pak = pak_path(root, 'DataLS')
        manifest = root / 'DataLS/zz_port_textures.json'
        original = pak.read_bytes()
        os.chmod(manifest, stat.S_IREAD)
        try:
            before = self.snapshot(root)
            run(self.exe, 'remove-originals-bank', root, 'DataLS', expect=2)
            self.assertEqual(self.snapshot(root), before, 'Manifest publication must fail before changing any original')
        finally:
            os.chmod(manifest, stat.S_IREAD | stat.S_IWRITE)
        os.chmod(pak, stat.S_IREAD)
        try:
            run(self.exe, 'remove-originals-bank', root, 'DataLS', expect=2)
            self.assertEqual(pak.read_bytes(), original)
            self.assertTrue(json.loads(manifest.read_text())['originals_removed'])
            guarded = self.snapshot(root)
            run(self.exe, 'remove-converted-bank', root, 'DataLS', expect=2)
            self.assertEqual(self.snapshot(root), guarded)
        finally:
            os.chmod(pak, stat.S_IREAD | stat.S_IWRITE)
        run(self.exe, 'remove-originals-bank', root, 'DataLS')
        with zipfile.ZipFile(pak) as archive:
            self.assertEqual(archive.namelist(), ['keep.txt'])

    def test_missing_original_without_a_flag_cannot_destroy_its_only_conversion(self):
        root = self.fixture()
        run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1)
        # A manual/external removal must be detected even if the manifest still
        # says false; both re-conversion and undo would otherwise lose the copy.
        (pak_path(root, 'DataLS')).unlink()
        before = self.snapshot(root)
        self.assertIn('removed 1 ', run(self.exe, 'scan-bank', root, 'DataLS'))
        run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1, expect=2)
        run(self.exe, 'remove-converted-bank', root, 'DataLS', expect=2)
        self.assertEqual(self.snapshot(root), before)

    def test_two_second_and_equal_date_collisions_keep_the_original_cross_bank_winner(self):
        for equal in (False, True):
            with self.subTest(equal=equal):
                root = self.fixture()
                data_time = (2008, 1, 2, 3, 4, 6)
                overlay_time = data_time if equal else later(data_time)
                alpha = dds(4, 4, DXT1, 1, lambda _, n: struct.pack('<HHI', 0, 0xFFFF, 0xFFFFFFFF) * n)
                with zipfile.ZipFile(pak_path(root, 'DataLS'), 'w') as archive:
                    archive.writestr(zipfile.ZipInfo('Textures/Shared.dds', overlay_time), alpha)
                with zipfile.ZipFile(pak_path(root, 'data')) as archive:
                    original = archive.read(image_name('data'))
                with zipfile.ZipFile(pak_path(root, 'data'), 'w') as archive:
                    archive.writestr(zipfile.ZipInfo('Textures/Shared.dds', data_time), original)
                originals = {bank: pak_path(root, bank).read_bytes() for bank in ('data', 'DataLS')}

                def winner():
                    result = None
                    for bank in ('data', 'DataLS'):
                        for pak in sorted((root / bank).glob('*.pak')):
                            with zipfile.ZipFile(pak) as archive:
                                if 'Textures/Shared.dds' in archive.namelist():
                                    info = archive.getinfo('Textures/Shared.dds')
                                    if result is None or info.date_time > result[0]:
                                        result = info.date_time, archive.read(info)
                    return result

                before = winner()
                run(self.exe, 'convert-bank', root, 'data', 'etc2', 1)
                self.assertEqual(winner(), before, 'Even partial conversion must not promote a base-bank loser')
                run(self.exe, 'convert-bank', root, 'DataLS', 'etc2', 1)
                self.assertEqual(winner(), before)
                with zipfile.ZipFile(root / 'data/zz_port_textures.pak') as archive:
                    self.assertEqual(archive.namelist(), [])
                for bank in ('data', 'DataLS'):
                    run(self.exe, 'remove-originals-bank', root, bank)
                    self.assertEqual(pak_path(root, bank).read_bytes(), originals[bank])
                self.assertEqual(winner(), before)

    def test_native_secondary_archive_order_priority_and_neutral_timestamp_fold(self):
        for bank, first, second, neutral in (
                ('DataLS', 'p5-data.pak', 'p6-data.pak', 'p7-texts.pak'),
                ('dataa1', 'a1-data.pak', 'a1p1-data.pak', 'a1p1-texts.pak')):
            with self.subTest(bank=bank):
                temporary = tempfile.TemporaryDirectory(prefix='native-winner-', dir=OUT)
                self.addCleanup(temporary.cleanup)
                root = Path(temporary.name)
                directory = root / bank
                directory.mkdir()
                def write(name, color, year, path='Textures/Winner.dds'):
                    pixels = dds(4, 4, DXT3, 1, lambda _, n:
                                 (b'\xff' * 8 + struct.pack('<HHI', color, color, 0)) * n)
                    with zipfile.ZipFile(directory / name, 'w') as archive:
                        archive.writestr(zipfile.ZipInfo(path, (year, 1, 2, 3, 4, 6)), pixels)
                # Higher native priority wins even with an older DOS timestamp.
                write(first, 0xF800, 2020)
                write(second, 0x001F, 2008)
                (directory / 'custom-unmounted.pak').write_bytes(b'not a ZIP, and never mounted by this engine')
                # Neither old unsafe output nor a foreign versioned output is an original.
                (directory / 'zz_port_textures.pak').write_bytes(b'old conversion is not an input archive')
                for expected, with_neutral in ((2, False), (1, True)):
                    if with_neutral:
                        write(neutral, 0x07E0, 2009, 'textures\\WINNER.dds')
                    run(self.exe, 'convert-bank', root, bank, 'etc2', 1)
                    manifest = json.loads((directory / 'zz_port_textures.json').read_text())
                    self.assertEqual(manifest['version'], 2)
                    with zipfile.ZipFile(converted_path(root, bank)) as archive:
                        self.assertEqual(len(archive.namelist()), 1, 'Native case/slash aliases are one resource')
                        payload = archive.read(archive.namelist()[0])
                    image = root / ('converted-' + str(expected) + '.dds')
                    image.write_bytes(payload)
                    rgba = root / ('converted-' + str(expected) + '.rgba')
                    run(self.exe, 'decode', image, 0, rgba)
                    pixel = rgba.read_bytes()[:4]
                    self.assertGreater(pixel[expected], 200)
                    self.assertTrue(all(pixel[c] < 30 for c in range(3) if c != expected), pixel)
                # Every cross-bank collision stays on the original path, even
                # when dates differ by years and native priorities disagree.
                (root / 'data').mkdir()
                with zipfile.ZipFile(root / 'data/base.pak', 'w') as archive:
                    archive.writestr(zipfile.ZipInfo('Textures/Winner.dds', (2024, 1, 2, 3, 4, 6)), b'original DDS path')
                run(self.exe, 'convert-bank', root, bank, 'etc2', 1)
                with zipfile.ZipFile(converted_path(root, bank)) as archive:
                    self.assertEqual(archive.namelist(), [])
                before = self.snapshot(root)
                run(self.exe, 'remove-originals-bank', root, bank)
                after = self.snapshot(root)
                for name in before:
                    if name.endswith('.pak'):
                        self.assertEqual(before[name], after[name], name)

    def test_old_secondary_policy_cannot_be_activated_or_remove_originals(self):
        root = self.fixture()
        bank = 'DataLS'
        run(self.exe, 'convert-bank', root, bank, 'etc2', 1)
        manifest = root / bank / 'zz_port_textures.json'
        data = json.loads(manifest.read_text())
        data['version'] = 1
        manifest.write_text(json.dumps(data, indent=2) + '\n')
        converted_path(root, bank).rename(root / bank / 'zz_port_textures.pak')
        before = self.snapshot(root)
        for operation in ('scan-bank', 'remove-originals-bank', 'remove-converted-bank', 'convert-bank'):
            args = ('etc2', 1) if operation == 'convert-bank' else ()
            run(self.exe, operation, root, bank, *args, expect=2)
            self.assertEqual(self.snapshot(root), before)
        self.assertFalse(converted_path(root, bank).exists(), 'Only the v2 filename may be mounted by the new native seam')

    def test_secondary_removal_checks_source_bytes_and_metadata_before_any_write(self):
        for defect in ('changed_source', 'corrupt_source', 'source_crc', 'priority', 'marker', 'policy'):
            with self.subTest(defect=defect):
                root = self.fixture()
                bank = 'DataLS'
                source = pak_path(root, bank)
                with zipfile.ZipFile(source) as archive:
                    entries = [(entry, archive.read(entry)) for entry in archive.infolist()]
                # Stored source permits a payload corruption with an unchanged ZIP CRC.
                with zipfile.ZipFile(source, 'w') as archive:
                    for entry, payload in entries:
                        entry.compress_type = zipfile.ZIP_STORED
                        archive.writestr(entry, payload)
                run(self.exe, 'convert-bank', root, bank, 'etc2', 1)
                if defect == 'changed_source':
                    with zipfile.ZipFile(source, 'w') as archive:
                        for entry, payload in entries:
                            if entry.filename == image_name(bank):
                                payload = bytearray(payload)
                                payload[-1] ^= 1
                            archive.writestr(entry, payload)
                elif defect == 'corrupt_source':
                    raw = bytearray(source.read_bytes())
                    with zipfile.ZipFile(source) as archive:
                        entry = archive.getinfo(image_name(bank))
                    local = entry.header_offset
                    name_len, extra_len = struct.unpack_from('<HH', raw, local + 26)
                    raw[local + 30 + name_len + extra_len + 128] ^= 1
                    source.write_bytes(raw)
                elif defect == 'policy':
                    path = root / bank / 'zz_port_textures.json'
                    data = json.loads(path.read_text())
                    del data['metadata_policy']
                    path.write_text(json.dumps(data))
                else:
                    path = converted_path(root, bank)
                    with zipfile.ZipFile(path) as archive:
                        entry = archive.infolist()[0]
                        payload = bytearray(archive.read(entry))
                    if defect == 'source_crc':
                        payload[60] ^= 1  # Rewriting ZIP recomputes the converted CRC, so source validation must reject it.
                    elif defect == 'priority':
                        entry.external_attr = 0x48540400
                    else:
                        entry.external_attr = 0x20
                    with zipfile.ZipFile(path, 'w') as archive:
                        archive.writestr(entry, payload)
                before = self.snapshot(root)
                run(self.exe, 'remove-originals-bank', root, bank, expect=2)
                self.assertEqual(self.snapshot(root), before)

    def test_secondary_removal_preserves_older_losers_and_can_resume(self):
        for bank, lower in (('DataLS', 'p5-data.pak'), ('dataa1', 'a1-data.pak')):
            with self.subTest(bank=bank):
                root = self.fixture()
                source = pak_path(root, bank)
                with zipfile.ZipFile(source) as archive:
                    original = archive.read(image_name(bank))
                loser = bytearray(original)
                loser[-1] ^= 1
                lower_path = root / bank / lower
                with zipfile.ZipFile(lower_path, 'w') as archive:
                    archive.writestr(zipfile.ZipInfo(image_name(bank), (2020, 1, 2, 3, 4, 6)), loser)
                lower_before = lower_path.read_bytes()
                run(self.exe, 'convert-bank', root, bank, 'etc2', 1)
                run(self.exe, 'remove-originals-bank', root, bank)
                with zipfile.ZipFile(source) as archive:
                    self.assertNotIn(image_name(bank), archive.namelist())
                self.assertEqual(lower_path.read_bytes(), lower_before)
                before = self.snapshot(root)
                run(self.exe, 'remove-originals-bank', root, bank)
                self.assertEqual(self.snapshot(root), before)
                run(self.exe, 'remove-converted-bank', root, bank, expect=2)
                self.assertEqual(self.snapshot(root), before)


if __name__ == '__main__':
    unittest.main()
