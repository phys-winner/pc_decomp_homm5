import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import town_music


def music_inputs(root, originals=None):
    """Synthetic game archive: no original game resources are test fixtures."""
    if originals is None:
        originals = {name: (f'<Music><FileName>test/{name}</FileName><FadeIn>2000</FadeIn>'
                            '<FadeOut>2000</FadeOut><MinPausedTime>1000</MinPausedTime>'
                            '<MaxPausedTime>10000</MaxPausedTime></Music>').encode()
                     for name in town_music.TOWNS}
    (root / "original-game/data").mkdir(parents=True, exist_ok=True)
    (root / "config/music").mkdir(parents=True, exist_ok=True)
    (root / "port.json").write_text('{"game_directory":"original-game"}')
    (root / "config/music/manifest.json").write_text(json.dumps(
        {name: hashlib.sha256(data).hexdigest() for name, data in originals.items()}))
    with zipfile.ZipFile(root / "original-game/data/data.pak", "w") as archive:
        for name, data in originals.items():
            archive.writestr("Sounds/_(Music)/Towns/" + name, data)
    return originals


class TownMusic(unittest.TestCase):
    def test_exact_eight_resources_two_edits_and_deterministic_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = music_inputs(root)
            original_archive = (root / "original-game/data/data.pak").read_bytes()
            output, receipt = town_music.build_town_music_override(root)
            first = output.read_bytes()
            self.assertEqual(receipt["sha256"], hashlib.sha256(first).hexdigest())
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["Sounds/_(Music)/Towns/" + name for name in town_music.TOWNS])
                for member in archive.infolist():
                    name = member.filename.rsplit("/", 1)[1]
                    expected = originals[name].replace(b"<MinPausedTime>1000</MinPausedTime>", b"<MinPausedTime>0</MinPausedTime>")
                    expected = expected.replace(b"<MaxPausedTime>10000</MaxPausedTime>", b"<MaxPausedTime>0</MaxPausedTime>")
                    self.assertEqual(archive.read(member), expected)
                    self.assertEqual(member.date_time, town_music.ZIP_DATE)
                    self.assertGreater(member.date_time, (2007, 8, 3, 12, 0, 28))
            second, second_receipt = town_music.build_town_music_override(root)
            self.assertEqual(second.read_bytes(), first)
            self.assertEqual(second_receipt, receipt)
            self.assertEqual((root / "original-game/data/data.pak").read_bytes(), original_archive)

    def test_unknown_music_fields_are_rejected_even_with_updated_manifest(self):
        for change in (lambda b: b.replace(b"</Music>", b"<Loop>true</Loop></Music>"),
                       lambda b: b.replace(b"<FadeOut>2000", b"<FadeOut>0")):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                originals = music_inputs(root)
                originals["Haven.(Music).xdb"] = change(originals["Haven.(Music).xdb"])
                music_inputs(root, originals)
                with self.assertRaisesRegex(ValueError, "Unrecognized town Music schema"):
                    town_music.build_town_music_override(root)
                self.assertFalse((root / "build/data-overrides" / town_music.PAK_NAME).exists())

    def test_changed_input_or_extra_town_is_rejected_before_replacing_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            music_inputs(root)
            output, _ = town_music.build_town_music_override(root)
            original_output = output.read_bytes()
            path = root / "config/music/manifest.json"
            manifest = json.loads(path.read_text())
            manifest["a1-Renegade.xdb"] = "0" * 64
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "exactly the eight"):
                town_music.build_town_music_override(root)
            self.assertEqual(output.read_bytes(), original_output)

    def test_changed_original_is_rejected_before_replacing_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            originals = music_inputs(root)
            output, _ = town_music.build_town_music_override(root)
            original_output = output.read_bytes()
            manifest = (root / "config/music/manifest.json").read_bytes()
            originals["Haven.(Music).xdb"] += b"changed"
            music_inputs(root, originals)
            (root / "config/music/manifest.json").write_bytes(manifest)
            with self.assertRaisesRegex(ValueError, "canonical input changed"):
                town_music.build_town_music_override(root)
            self.assertEqual(output.read_bytes(), original_output)


if __name__ == "__main__":
    unittest.main()
