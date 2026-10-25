"""Deploy the ARM64 executable and private copies of the licensed game assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from town_music import build_town_music_override

ROOT = Path(__file__).resolve().parents[1]
PORT = json.loads((ROOT / "port.json").read_text(encoding="utf-8")) if (ROOT / "port.json").exists() else {}
DEVICE_ROOT = "/sdcard/HeroesV"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.environ.get("HOMM5_SERIAL") or os.environ.get("ANDROID_SERIAL") or PORT.get("device"))
    parser.add_argument("--data", action="store_true", help="Copy game data (about 2 GB)")
    args = parser.parse_args()
    music_override = build_town_music_override(ROOT, PORT["game_directory"]) if args.data else None
    adb = ["adb", *(["-s", args.serial] if args.serial else [])]

    def run(*command):
        subprocess.run(adb + list(command), check=True)

    def shell(command):
        run("shell", command)

    verified = {}

    def verify(source, destination):
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        output = subprocess.check_output(adb + ["shell", "sha256sum " + shlex.quote(destination)], text=True)
        if not output.split() or output.split()[0] != expected:
            raise RuntimeError(f"Device SHA-256 mismatch: {destination}")
        verified[destination] = expected

    shell(f"mkdir -p {DEVICE_ROOT}/game {DEVICE_ROOT}/userdata {DEVICE_ROOT}/lifted /data/local/tmp/homm5")
    if args.data:
        game = ROOT / PORT["game_directory"]
        for name in ("bin", "data", "music", "video", "profiles", "Maps", "UserCampaigns", "UserMODs", "hwcursors", "DuelPresets"):
            source = game / name
            if source.is_dir():
                run("push", "--sync", str(source), DEVICE_ROOT + "/game/")
        run("push", str(ROOT / "config/profiles/autoexec_a2.cfg"), DEVICE_ROOT + "/game/profiles/autoexec_a2.cfg")
        run("push", str(ROOT / "config/profiles/default_profile/user_a2.cfg"),
            DEVICE_ROOT + "/game/profiles/default_profile/user_a2.cfg")
        run("push", str(ROOT / "config/video/intro_a1.xml"), DEVICE_ROOT + "/game/video/intro_a1.xml")
        music_path, _ = music_override
        music_destination = DEVICE_ROOT + "/game/data/" + music_path.name
        run("push", str(music_path), music_destination)
        verify(music_path, music_destination)
    for spec in json.loads((ROOT / "config/modules.json").read_text(encoding="utf-8")):
        source = ROOT / "generated/input" / spec["file"]
        destination = DEVICE_ROOT + "/lifted/" + spec["file"]
        run("push", "--sync", str(source), destination)
        verify(source, destination)
    executable = ROOT / "build/arm64/homm5-arm64"
    if executable.exists():
        header = executable.read_bytes()[:64]
        if header[:4] != b"\x7fELF" or header[4:6] != b"\x02\x01" or header[18:20] != b"\xb7\x00":
            raise ValueError("The Android executable must be a little-endian ARM64 ELF")
        # A running executable cannot be overwritten: upload then rename atomically.
        temporary = "/data/local/tmp/homm5/homm5-arm64.new"
        run("push", str(executable), temporary)
        shell(f"chmod 755 {temporary} && mv {temporary} /data/local/tmp/homm5/homm5-arm64")
        verify(executable, "/data/local/tmp/homm5/homm5-arm64")
    (ROOT / "build").mkdir(exist_ok=True)
    receipt = {"serial": args.serial, "verified_sha256": verified}
    if music_override:
        receipt["town_music_override"] = music_override[1]
    (ROOT / "build/deploy-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Deployed to", args.serial, DEVICE_ROOT)


if __name__ == "__main__":
    main()
