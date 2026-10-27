"""Fail closed when an original engine lacks a required, pinned port patch."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile

from editions import ROOT, edition_spec, generated_root, module_manifest

REQUIRED_FEATURES = (
    "army", "touch", "camera", "cursor", "combobox", "ui_scale", "render_scale",
    "cutscene_horplus", "shadows", "alpha_test", "textures", "audio", "lan", "profile", "telemetry_disabled", "widescreen_ui",
)

TEXTURE_GENERATED_HOOKS = {
    "vanilla": {"sub_00AF03F0": 1, "sub_00A61460": 1, "sub_00A614C0": 2,
                **{name: 4 for name in ("sub_00A61CE0", "sub_00A61D30", "sub_00A61DA6", "sub_00A61EBE",
                                        "sub_00A61EC5", "sub_00A61EDB", "sub_00A627F0")}},
    "hof": {"sub_007B09B0": 1, "sub_0092A010": 1, "sub_0092A070": 2,
            **{name: 4 for name in ("sub_0092A8B0", "sub_0092A900", "sub_0092A976", "sub_0092AA8E",
                                    "sub_0092AA95", "sub_0092AAAB", "sub_0092B3C0")}},
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_digest(path):
    # Git may check out the same reviewed text with Windows line endings.
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def contract_path(edition, root=ROOT):
    edition_spec(edition, root)
    return Path(root) / ("config/" + edition + ".patches.json")


def load_contract(edition, root=ROOT):
    path = contract_path(edition, root)
    if not path.is_file():
        raise ValueError(edition + ": mandatory port patch manifest is missing")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("edition") != edition or set(data.get("features", {})) != set(REQUIRED_FEATURES):
        raise ValueError(edition + ": mandatory port patch coverage is incomplete")
    return data


def legacy_ui_branch(text, enabled):
    """Resolve this edition guard; other C preprocessor choices stay intact."""
    frames, output = [], []
    active = lambda: all(frame is None or frame for frame in frames)
    for line in text.splitlines(keepends=True):
        directive = re.match(rb"\s*#\s*(if|ifdef|ifndef|else|elif|endif)\b(.*)", line)
        if not directive:
            if active():
                output.append(line)
            continue
        command, expression = directive.groups()
        expression = expression.strip()
        if command in (b"if", b"ifdef", b"ifndef"):
            parent = active()
            if command == b"if":
                choice = (enabled if expression == b"HOMM5_LEGACY_UI" else
                          not enabled if expression == b"!HOMM5_LEGACY_UI" else None)
            else:
                choice = ((enabled if command == b"ifdef" else not enabled)
                          if expression == b"HOMM5_LEGACY_UI" else None)
            if choice is None and parent:
                output.append(line)
            frames.append(choice)
        elif not frames:
            raise ValueError("Unbalanced legacy UI preprocessor guard")
        elif command == b"endif":
            choice = frames.pop()
            if choice is None and active():
                output.append(line)
        elif frames[-1] is None:
            if active():
                output.append(line)
        elif command == b"else":
            frames[-1] = not frames[-1]
        else:
            raise ValueError("Unsupported elif in legacy UI edition guard")
    if frames:
        raise ValueError("Unbalanced legacy UI preprocessor guard")
    return b"".join(output)


def _layout_blocks(text, data, relative, edition):
    replacements = []
    for index, patch in enumerate(data.get("layout_patches", {}).get(relative, ())):
        before, after = patch["old"].encode(), patch["new"].encode()
        if text.count(before) != patch["count"]:
            raise ValueError(edition + ": native layout anchor changed: " + relative)
        marker = ("/* HOMM5_EDITION_LAYOUT_" + str(index) + " */").encode()
        text = text.replace(before, marker)
        if not patch.get("mapped", False):
            after = re.sub(rb"(0x|sub_)([0-9A-Fa-f]{8})(?![0-9A-Fa-f])",
                           lambda m: m[1] + data["addresses"].get(m[2].decode().upper(), m[2].decode()).encode(), after)
        replacements.append((marker, after))
    return text, replacements


def validate_native_inputs(edition, root=ROOT):
    root = Path(root)
    data = load_contract(edition, root)
    if data.get("pending_features"):
        raise ValueError(edition + ": required patches are not implemented: " + ", ".join(data["pending_features"]))
    modules = module_manifest(edition, root)
    engine = next(m for m in modules if m.get("exe"))
    if data.get("engine_sha256") != engine["sha256"]:
        raise ValueError(edition + ": patches belong to a different original engine")
    reports = {}
    for module in modules:
        report_path = generated_root(edition, root) / (module["name"] + "-x86/report.json")
        if not report_path.is_file():
            raise ValueError(edition + ": static generation is incomplete: " + module["name"])
        report = json.loads(report_path.read_text())
        reports[module["name"]] = report
        image = generated_root(edition, root) / "input" / module["file"]
        if (report.get("status") != "GENERATED" or report.get("binary_sha256") != module["sha256"]
                or not image.is_file() or digest(image) != report.get("rebased_sha256")):
            raise ValueError(edition + ": generated image identity mismatch: " + module["name"])
    sources = data.get("sources", {})
    for feature in REQUIRED_FEATURES:
        files = data["features"][feature]
        if not isinstance(files, list) or not files or any(f not in sources for f in files):
            raise ValueError(edition + ": required patch has no pinned implementation: " + feature)
    for relative, expected in sources.items():
        path = root / relative
        if not path.is_file() or source_digest(path) != expected:
            raise ValueError(edition + ": required patch implementation changed: " + relative)
    if edition != "toe":
        addresses = data.get("addresses", {})
        for relative, required in data.get("reference_addresses", {}).items():
            active = legacy_ui_branch((root / relative).read_bytes().replace(b"\r\n", b"\n"), True)
            active, replacements = _layout_blocks(active, data, relative, edition)
            active += b"\n" + b"\n".join(value for _, value in replacements)
            active = re.sub(rb"/\*.*?\*/|//[^\r\n]*", b"", active, flags=re.S)
            used = {m[1].decode().upper() for m in re.finditer(rb"(?:0x|sub_)([0-9A-Fa-f]{8})(?![0-9A-Fa-f])", active)}
            if any(address in used and address not in addresses for address in required):
                raise ValueError(edition + ": unmapped native hooks in " + relative)
        if not data.get("reference_addresses") or not data.get("generated_patches"):
            raise ValueError(edition + ": engine-specific patch anchors are missing")
        for function, count in TEXTURE_GENERATED_HOOKS[edition].items():
            hooks = [patch for patch in data["generated_patches"]
                     if patch["module"] == "game" and patch["function"] == function and
                     any(marker in patch["new"] for marker in
                         ("/zz_port_textures_v2.pak", "0x40000000u", "0x80000000u"))]
            if len(hooks) != count:
                raise ValueError(edition + ": mandatory texture hooks are missing: " + function)
        from build_android import guard_fpu_memory, round_x87_precision
        for module in {patch["module"] for patch in data["generated_patches"]}:
            seams = [patch for patch in data["generated_patches"] if patch["module"] == module]
            declarations = re.compile(rb"(?m)^void (" + b"|".join(
                re.escape(name.encode()) for name in sorted({patch["function"] for patch in seams})) + rb")\(void\) \{")
            seen = [0] * len(seams)
            sources = reports.get(module, {}).get("sources", ())
            for name in sources:
                text = (generated_root(edition, root) / (module + "-x86") / name).read_bytes()
                for match in declarations.finditer(text):
                    end = re.search(rb"\n\}\r?\n", text[match.start():])
                    if end is None:
                        raise ValueError(edition + ": generated function boundary changed: " + match[1].decode())
                    body = round_x87_precision(guard_fpu_memory(text[match.start():match.start() + end.end()]))
                    for index, patch in enumerate(seams):
                        if patch["function"].encode() != match[1]:
                            continue
                        if body.count(patch["old"].encode()) != 1:
                            raise ValueError(edition + ": generated hook anchor changed: " + patch["function"])
                        seen[index] += 1
            if any(count != 1 for count in seen):
                raise ValueError(edition + ": required generated hook is missing or duplicated: " + module)
    return dict(edition=edition, features=list(REQUIRED_FEATURES), engine_sha256=engine["sha256"],
                contract_sha256=digest(contract_path(edition, root)), sources=sources)


def native_overrides(edition, names, root=ROOT):
    if edition == "toe":
        return tuple(names)
    addresses = load_contract(edition, root)["addresses"]
    return tuple("sub_" + addresses[name[4:]] for name in names)


def adapt_host_source(source, out, edition, root=ROOT):
    source, out, root = Path(source), Path(out), Path(root)
    if edition == "toe":
        return source, []
    data = load_contract(edition, root)
    relative = source.relative_to(root).as_posix()
    text = legacy_ui_branch(source.read_bytes().replace(b"\r\n", b"\n"), True)
    addresses = data["addresses"]
    required = set(data["reference_addresses"].get(relative, ()))
    text, replacements = _layout_blocks(text, data, relative, edition)

    def mapped(match):
        address = match[2].decode().upper()
        return match[1] + addresses[address].encode() if address in required and address in addresses else match[0]

    text = re.sub(rb"(0x|sub_)([0-9A-Fa-f]{8})(?![0-9A-Fa-f])", mapped, text)
    for marker, after in replacements:
        text = text.replace(marker, after)
    destination = out / "host-edition" / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.read_bytes() != text:
        destination.write_bytes(text)
    return destination, ["-I" + str(source.parent)]


def adapt_generated_source(text, module, edition, root=ROOT):
    if edition == "toe":
        return text
    for patch in load_contract(edition, root)["generated_patches"]:
        declaration = ("void " + patch["function"] + "(void) {").encode()
        if patch["module"] != module or declaration not in text:
            continue
        start = text.index(declaration)
        end = re.search(rb"\n\}\r?\n", text[start:])
        if end is None:
            raise ValueError(edition + ": generated function boundary changed: " + patch["function"])
        stop = start + end.end()
        body = text[start:stop]
        before, after = patch["old"].encode(), patch["new"].encode()
        if body.count(before) != 1:
            raise ValueError(edition + ": generated hook anchor changed: " + patch["function"])
        text = text[:start] + body.replace(before, after) + text[stop:]
    return text


def finalize_native_receipt(edition, library, root=ROOT):
    library = Path(library)
    receipt = validate_native_inputs(edition, root)
    receipt["library_sha256"] = digest(library)
    path = library.with_suffix(".patches.json")
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def validate_packaged_native(edition, library, root=ROOT):
    library = Path(library)
    expected = validate_native_inputs(edition, root)
    path = library.with_suffix(".patches.json")
    if not library.is_file() or not path.is_file():
        raise ValueError(edition + ": required patched native library/receipt is missing")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if any(receipt.get(k) != v for k, v in expected.items()) or receipt.get("library_sha256") != digest(library):
        raise ValueError(edition + ": patched native library receipt is stale")
    return receipt


def validate_overlay(edition, folder, root=ROOT):
    from port_ui import OPTIONS, PAK_NAME, UICONSTS
    from town_music import PAK_NAME as MUSIC_PAK, TOWNS_BY_EDITION, ZIP_DATE as MUSIC_DATE
    folder = Path(folder)
    archive_path = folder / "data" / PAK_NAME
    if not archive_path.is_file():
        raise ValueError(edition + ": required UI overlay is missing")
    with zipfile.ZipFile(archive_path) as archive:
        constants = archive.read(UICONSTS)
        name = "UI/MPChatInGame/ChatInputActivator.(WindowMSButtonShared).xdb"
        if name not in archive.namelist():
            raise ValueError(edition + ": required inactive chat background override is missing")
        backgrounds = ET.fromstring(archive.read(name)).findall("VisualStates/Item/Normal/Background")
        if len(backgrounds) != 1 or backgrounds[0].get("href") != "":
            raise ValueError(edition + ": inactive chat background must be empty")
        for option in OPTIONS:
            if constants.count(("<ID>" + option[0] + "</ID>").encode()) != 1:
                raise ValueError(edition + ": UI patch is missing or duplicated: " + option[0])
        for name in ("UI/DialogueScreen.(WindowScreenShared).xdb",
                     "UI/CutsceneScreen/SubtitlesArea.(WindowStaticText).xdb"):
            if name not in archive.namelist():
                raise ValueError(edition + ": required Hor+ resource is missing: " + name)
        for name in ("UI/DialogueScreen.(WindowScreenShared).xdb", "UI/CusceneScreen.(WindowScreenShared).xdb"):
            shared = ET.fromstring(archive.read(name))
            if any(child.get("href", "").startswith("Common/BlackBorder/") for child in shared.findall("Children/Item")):
                raise ValueError(edition + ": Hor+ border removal is missing")
        for panel in ("DialogueTop", "DialoguePanel"):
            name = "UI/DialogueScreen/" + panel + ".(WindowSimple).xdb"
            if name not in archive.namelist():
                raise ValueError(edition + ": required Hor+ panel is missing: " + name)
            window = ET.fromstring(archive.read(name))
            if (window.findtext("Placement/HorAllign/First") != "EPA_MARGIN" or
                    window.findtext("Placement/HorAllign/Second") != "true" or
                    (panel == "DialoguePanel" and (
                        window.findtext("Placement/VerAllign/First") != "EPA_HIGH_END" or
                        window.findtext("Placement/VerAllign/Second") != "true" or
                        window.findtext("Placement/Position/First/y") != "0"))):
                raise ValueError(edition + ": required Hor+ panel anchors are missing: " + name)
        help_action = ET.fromstring(archive.read("UI/PortGamepad.(ARSendGameMessage).xdb"))
        if help_action.findtext("EventName") != "port_gamepad":
            raise ValueError(edition + ": army/control guide action is missing")
        switch_path = "UI/PortSwitchGame.(ARSendGameMessage).xdb"
        if switch_path not in archive.namelist() or ET.fromstring(archive.read(switch_path)).findtext("EventName") != "port_switch_game":
            raise ValueError(edition + ": game switching action is missing")
        if any("PortExitLauncher" in name for name in archive.namelist()):
            raise ValueError(edition + ": exit dialog must not contain a launcher button")
        menu_path = "UI/MainMenu2/Menu.(WindowSimple).xdb"
        if menu_path not in archive.namelist() or ET.fromstring(archive.read(menu_path)).findtext("Placement/Size/First/y") != "327":
            raise ValueError(edition + ": taller main menu scroll is missing")
        if edition != "toe":
            for screen in ("AdventureScreen-Heavy", "TownScreen", "HeroScreen3", "CombatScreen-Heavy",
                           "MainMenu2", "GameOptions", "SetFirstProfileName/SetFirstProfileName"):
                name = "UI/" + screen + ".(WindowScreen).xdb"
                if name not in archive.namelist():
                    raise ValueError(edition + ": required widescreen resource is missing: " + name)
                window = ET.fromstring(archive.read(name))
                expected = "ERA_CENTER" if screen.startswith("SetFirstProfileName/") else "EPA_MARGIN"
                if (window.findtext("Placement/HorAllign/First") != expected or
                        window.findtext("Placement/HorAllign/Second") != "true"):
                    raise ValueError(edition + ": required widescreen anchor is missing: " + name)
            name = "UI/Common/JogDial/JogDial.xdb"
            if name not in archive.namelist():
                raise ValueError(edition + ": required hero dial is missing")
            window = ET.fromstring(archive.read(name))
            if any(window.findtext("Placement/" + axis + "/First") != "EPA_HIGH_END" or
                   window.findtext("Placement/" + axis + "/Second") != "true"
                   for axis in ("HorAllign", "VerAllign")):
                raise ValueError(edition + ": required hero dial anchors are missing")
    music_path = folder / "data" / MUSIC_PAK
    if not music_path.is_file():
        raise ValueError(edition + ": required town music overlay is missing")
    manifest_name = "manifest.json" if edition == "toe" else edition + ".json"
    music_hashes = json.loads((Path(root) / "config/music" / manifest_name).read_text(encoding="utf-8"))
    towns = TOWNS_BY_EDITION[edition]
    if set(music_hashes) != set(towns):
        raise ValueError(edition + ": town music manifest coverage is incomplete")
    with zipfile.ZipFile(music_path) as music:
        names = ["Sounds/_(Music)/Towns/" + name for name in towns]
        if sorted(music.namelist()) != sorted(names):
            raise ValueError(edition + ": town music resources are missing, duplicated or from another edition")
        for name in names:
            original = music.read(name)
            for field, value in (("MinPausedTime", "1000"), ("MaxPausedTime", "10000")):
                patched = ("<" + field + ">0</" + field + ">").encode()
                if original.count(patched) != 1:
                    raise ValueError(edition + ": town music pause patch is missing: " + name)
                original = original.replace(patched, ("<" + field + ">" + value + "</" + field + ">").encode())
            if (hashlib.sha256(original).hexdigest() != music_hashes[name.rsplit("/", 1)[1]] or
                    music.getinfo(name).date_time != MUSIC_DATE):
                raise ValueError(edition + ": town music canonical content or override timestamp changed: " + name)
    suffix = edition_spec(edition, root)["profile_suffix"]
    profiles = ("profiles/autoexec" + suffix + ".cfg", "profiles/default_profile/user" + suffix + ".cfg")
    for relative in profiles:
        if not (folder / relative).is_file():
            raise ValueError(edition + ": required profile overlay is missing: " + relative)
    auto = (folder / profiles[0]).read_bytes()
    variable = rb"(?m)^[ \t]*setvar[ \t]+ubi_tracking_tool_enabled[ \t]*=[ \t]*([^\r\n]*)"
    assignments = re.findall(variable, auto)
    user_assignments = re.findall(variable, (folder / profiles[1]).read_bytes())
    if (not auto.startswith((b"setvar ubi_tracking_tool_enabled = 0\n", b"setvar ubi_tracking_tool_enabled = 0\r\n"))
            or assignments != [b"0"] or any(value != b"0" for value in user_assignments)):
        raise ValueError(edition + ": telemetry must be disabled before startup and cannot be re-enabled by the overlay")
    loose_hashes = {}
    if edition != "toe":
        from editions import override_files
        for archive in (archive_path, music_path):
            for relative, contents in override_files(edition, archive).items():
                if relative == "data/" + archive.name:
                    continue
                loose = folder / relative
                if not loose.is_file() or loose.read_bytes() != contents:
                    raise ValueError(edition + ": required loose override is missing or stale: " + relative)
                loose_hashes[relative] = hashlib.sha256(contents).hexdigest()
    return dict(edition=edition, features=["profile", "ui_scale", "render_scale", "camera", "cursor", "cutscene_horplus", "audio", "telemetry_disabled", "widescreen_ui"],
                overlay_sha256=digest(archive_path), town_music_sha256=digest(music_path),
                loose_sha256=loose_hashes,
                profile_sha256={relative: digest(folder / relative) for relative in profiles})
