"""The three original engines, with isolated inputs and writable profiles."""
import io
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
EDITION_IDS = ("toe", "vanilla", "hof")


def edition_spec(edition="toe", root=ROOT):
    if edition not in EDITION_IDS:
        raise ValueError("Unknown Heroes V edition: " + str(edition))
    return json.loads((Path(root) / "config/editions.json").read_text(encoding="utf-8"))[edition]


def generated_root(edition="toe", root=ROOT):
    return Path(root) / edition_spec(edition, root)["generated"]


def module_manifest(edition="toe", root=ROOT):
    path = Path(root) / edition_spec(edition, root)["modules"]
    return json.loads(path.read_text(encoding="utf-8"))


def game_directory(edition="toe", root=ROOT):
    root = Path(root)
    settings = json.loads((root / "port.json").read_text(encoding="utf-8"))
    configured = settings.get("editions", {}).get(edition, {}).get("game_directory")
    if not configured and edition == "toe":
        configured = settings.get("game_directory")
    if not configured:
        raise ValueError("port.json: editions." + edition + ".game_directory is required")
    return root / configured


def build_root(edition="toe", modes=(), root=ROOT):
    edition_spec(edition, root)
    suffix = ([edition] if edition != "toe" else []) + list(modes)
    return Path(root) / ("build/arm64" + ("-" + "-".join(suffix) if suffix else ""))


def override_files(edition, archive):
    if edition not in EDITION_IDS:
        raise ValueError("Unknown Heroes V edition: " + str(edition))
    archive = Path(archive)
    payload = archive.read_bytes()
    files = {"data/" + archive.name: payload}
    if edition == "toe":
        return files
    # The older expansion banks override base PAKs; loose resources take precedence.
    seen = {name.casefold() for name in files}
    with zipfile.ZipFile(io.BytesIO(payload)) as packed:
        for item in packed.infolist():
            name = item.orig_filename
            if (not name or name.startswith("/") or "\\" in name or ":" in name or "\x00" in name or
                    any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))):
                raise ValueError("Invalid override resource path: " + name)
            if item.is_dir():
                continue
            relative = "data/" + name
            if relative.casefold() in seen:
                raise ValueError("Duplicate override resource: " + name)
            seen.add(relative.casefold())
            files[relative] = packed.read(item)
    return files
