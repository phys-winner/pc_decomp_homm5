"""Build the Android-only town music pause override; never edit game archives."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PAK_NAME = "z_homm5_android_town_music.pak"
ZIP_DATE = (2026, 10, 17, 0, 0, 0)
TOWNS = (
    "a1-Fortress.xdb", "a2_Stronghold.xdb", "Academy.(Music).xdb",
    "Dungeon.(Music).xdb", "Haven.(Music).xdb", "Inferno.(Music).xdb",
    "Necropolis.(Music).xdb", "Sylvan.(Music).xdb",
)


def build_town_music_override(root=ROOT, game_dir=None):
    root = Path(root)
    inputs = root / "config/music"
    manifest = json.loads((inputs / "manifest.json").read_text(encoding="utf-8"))
    if set(manifest) != set(TOWNS):
        raise ValueError("Town music manifest must contain exactly the eight town resources")
    if game_dir is None:
        game_dir = json.loads((root / "port.json").read_text(encoding="utf-8"))["game_directory"]
    with zipfile.ZipFile(root / game_dir / "data/data.pak") as archive:
        originals = {name: archive.read("Sounds/_(Music)/Towns/" + name) for name in TOWNS}
    entries = []
    for name in TOWNS:
        original = originals[name]
        digest = hashlib.sha256(original).hexdigest()
        if digest != manifest[name]:
            raise ValueError(f"Town music canonical input changed: {name}")
        music = ET.fromstring(original)
        expected = {"FadeIn": "2000", "FadeOut": "2000", "MinPausedTime": "1000", "MaxPausedTime": "10000"}
        if (music.tag != "Music" or set(music.attrib) - {"ObjectRecordID"}
                or [child.tag for child in music] != ["FileName", *expected]
                or not music.findtext("FileName")
                or any(child.attrib or list(child) for child in music)
                or any(music.findtext(key) != value for key, value in expected.items())):
            raise ValueError(f"Unrecognized town Music schema: {name}")
        patched = original
        for field, value in (("MinPausedTime", "1000"), ("MaxPausedTime", "10000")):
            before = f"<{field}>{value}</{field}>".encode("ascii")
            if patched.count(before) != 1:
                raise ValueError(f"Ambiguous town music pause field: {name}")
            patched = patched.replace(before, f"<{field}>0</{field}>".encode("ascii"))
        entries.append(("Sounds/_(Music)/Towns/" + name, patched, digest))
    output = root / "build/data-overrides" / PAK_NAME
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".pak.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data, _ in entries:
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.create_system = 0
            info.external_attr = 0x20
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)
    temporary.replace(output)
    receipt = {
        "pak": PAK_NAME, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "size": output.stat().st_size, "zip_date": list(ZIP_DATE),
        "members": [{"name": name, "original_sha256": original_sha,
                     "sha256": hashlib.sha256(data).hexdigest()} for name, data, original_sha in entries],
        "runtime_verification": "pending: loaded town MusicDB+0x54 and +0x58 must both be zero",
    }
    output.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return output, receipt


if __name__ == "__main__":
    path, details = build_town_music_override()
    print(path)
    print(details["sha256"])
