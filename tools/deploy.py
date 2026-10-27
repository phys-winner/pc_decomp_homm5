"""Deploy the ARM64 executable and private copies of the licensed game assets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from town_music import build_town_music_override
from port_ui import build_port_ui_override
from port_patches import validate_packaged_native, validate_overlay
from editions import EDITION_IDS, edition_spec, generated_root, module_manifest, game_directory, build_root, override_files
from profile_defaults import bootstrap_profiles

ROOT = Path(__file__).resolve().parents[1]
PORT = json.loads((ROOT / "port.json").read_text(encoding="utf-8")) if (ROOT / "port.json").exists() else {}
DEVICE_ROOT = "/sdcard/HeroesV"


def source_directory(game, name):
    matches = [path for path in game.iterdir() if path.is_dir() and path.name.casefold() == name.casefold()]
    if len(matches) > 1:
        raise ValueError("Ambiguous game directory: " + name)
    if not matches:
        return None
    canonical = game / name
    return canonical if canonical.is_dir() else matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=EDITION_IDS, default="toe")
    parser.add_argument("--serial", default=os.environ.get("HOMM5_SERIAL") or os.environ.get("ANDROID_SERIAL") or PORT.get("device"))
    parser.add_argument("--data", action="store_true", help="Copy the selected edition's resource banks and shared assets")
    args = parser.parse_args()
    spec = edition_spec(args.edition, ROOT)
    suffix = spec["assets_suffix"]
    device_game = DEVICE_ROOT + "/game" + suffix
    device_data = DEVICE_ROOT + "/" + spec["userdata"]
    device_images = DEVICE_ROOT + "/lifted" + suffix
    executable_directory = "/data/local/tmp/homm5" + suffix
    executable_destination = executable_directory + "/homm5-arm64"
    stage = ROOT / ("build/deploy" + suffix)
    executable = build_root(args.edition, root=ROOT) / (spec["library"].replace("_", "-") + "-arm64")
    native_receipt = validate_packaged_native(args.edition, executable, root=ROOT)
    header = executable.read_bytes()[:64]
    if header[:4] != b"\x7fELF" or header[4:6] != b"\x02\x01" or header[18:20] != b"\xb7\x00":
        raise ValueError("The Android executable must be a little-endian ARM64 ELF")
    music_override, ui_override, directories, profiles, overrides = None, None, [], {}, {}
    overlay_receipt = None
    if args.data:
        game = game_directory(args.edition, ROOT)
        music_override = build_town_music_override(ROOT, game, edition=args.edition)
        ui_override = build_port_ui_override(ROOT, game, edition=args.edition)
        names = set()
        for archive, _ in (music_override, ui_override):
            for relative, contents in override_files(args.edition, archive).items():
                if relative.casefold() in names:
                    raise ValueError("Conflicting deploy override resource: " + relative)
                names.add(relative.casefold())
                overrides[relative] = contents
        profiles = bootstrap_profiles(ROOT, args.edition)
        required = [spec["bin"], *spec["data"]]
        for name in [*required, "music", "video", "profiles", "Maps", "UserCampaigns", "UserMODs", "hwcursors", "DuelPresets"]:
            source = source_directory(game, name)
            if source is None and name in required:
                raise ValueError(args.edition + ": missing original game directory: " + name)
            if source is not None:
                directories.append(source)
        for relative, contents in {**profiles, **overrides}.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
        intro = ROOT / "config/video/intro_a1.xml"
        if not intro.is_file():
            raise FileNotFoundError(intro)
        overlay_receipt = validate_overlay(args.edition, stage, root=ROOT)
    images = [(generated_root(args.edition, ROOT) / "input" / row["file"], device_images + "/" + row["file"])
              for row in module_manifest(args.edition, ROOT)]
    for source, _ in images:
        if not source.is_file():
            raise FileNotFoundError(source)
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

    shell("mkdir -p " + " ".join(shlex.quote(path) for path in (device_game, device_data, device_images, executable_directory)))
    if args.data:
        for source in directories:
            run("push", "--sync", str(source), device_game + "/")
        parents = {"profiles/default_profile", "video", *(Path(name).parent.as_posix() for name in overrides)}
        shell("mkdir -p " + " ".join(shlex.quote(device_game + "/" + name) for name in sorted(parents)))
        for relative in profiles:
            run("push", str(stage / relative), device_game + "/" + relative)
        intro_name = "intro.xml" if args.edition == "vanilla" else "intro_a1.xml"
        run("push", str(intro), device_game + "/video/" + intro_name)
        for relative in overrides:
            source, destination = stage / relative, device_game + "/" + relative
            run("push", str(source), destination)
            verify(source, destination)
    for source, destination in images:
        run("push", "--sync", str(source), destination)
        verify(source, destination)
    # Recheck after a potentially long asset copy, before transferring native code.
    validate_packaged_native(args.edition, executable, root=ROOT)
    # A running executable cannot be overwritten: upload then rename atomically.
    temporary = executable_destination + ".new"
    run("push", str(executable), temporary)
    shell(f"chmod 755 {shlex.quote(temporary)} && mv {shlex.quote(temporary)} {shlex.quote(executable_destination)}")
    verify(executable, executable_destination)
    (ROOT / "build").mkdir(exist_ok=True)
    command = [executable_destination, "--game", device_game, "--data", device_data, "--images", device_images]
    receipt = {"edition": args.edition, "serial": args.serial, "verified_sha256": verified,
               "game": device_game, "userdata": device_data, "images": device_images, "command": command,
               "native_patches": native_receipt}
    if music_override:
        receipt["town_music_override"] = music_override[1]
        receipt["ui_override"] = ui_override[1]
        receipt["overlay_patches"] = overlay_receipt
    (ROOT / ("build/deploy-receipt" + suffix + ".json")).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Deployed", args.edition, "to", args.serial, device_game)
    print("Run:", shlex.join(adb + ["shell", shlex.join(command)]))


if __name__ == "__main__":
    main()
