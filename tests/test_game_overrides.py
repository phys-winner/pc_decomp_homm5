"""Legacy loose resources must match the reviewed archives and stay in data/."""
from pathlib import Path
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from editions import override_files


class GameOverridesTest(unittest.TestCase):
    def archive(self, root, names):
        path = root / 'port.pak'
        with warnings.catch_warnings(), zipfile.ZipFile(path, 'w') as archive:
            warnings.simplefilter('ignore', UserWarning)
            for name, contents in names:
                info = zipfile.ZipInfo(name)
                info.filename = name
                archive.writestr(info, contents)
        return path

    def test_legacy_loose_resources_are_exact_and_toe_keeps_its_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.archive(Path(directory), [('UI/options.xdb', b'<Options/>'),
                ('UI/Name.txt', b'\xff\xfeN\0'), ('Sounds/Town.xdb', b'<Music/>')])
            packed = {'data/port.pak': path.read_bytes()}
            self.assertEqual(override_files('toe', path), packed)
            for edition in ('vanilla', 'hof'):
                self.assertEqual(override_files(edition, path), dict(packed, **{
                    'data/UI/options.xdb': b'<Options/>', 'data/UI/Name.txt': b'\xff\xfeN\0',
                    'data/Sounds/Town.xdb': b'<Music/>'}))
            with self.assertRaisesRegex(ValueError, 'Unknown'):
                override_files('other', path)

    def test_resource_paths_and_case_collisions_cannot_escape_or_shadow(self):
        for names in ([('../outside', b'bad')], [('/absolute', b'bad')],
                      [('UI\\bad.xdb', b'bad')], [('C:/bad', b'bad')],
                      [('UI//bad', b'bad')], [('./bad', b'bad')],
                      [('UI/A', b'one'), ('ui/a', b'two')],
                      [('UI/A', b'one'), ('UI/A', b'two')], [('port.pak', b'shadow')]):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = self.archive(root, names)
                for edition in ('vanilla', 'hof'):
                    with self.assertRaisesRegex(ValueError, 'Invalid|Duplicate'):
                        override_files(edition, path)
                self.assertEqual(list(root.iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
