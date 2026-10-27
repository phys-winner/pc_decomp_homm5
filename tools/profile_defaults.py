"""Keep each original engine's bootstrap, changing only the port's defaults."""
from pathlib import Path
import re

from editions import ROOT, edition_spec, game_directory


def bootstrap_profiles(root=ROOT, edition="toe"):
    root = Path(root)
    suffix = edition_spec(edition, root)["profile_suffix"]
    paths = ("profiles/autoexec" + suffix + ".cfg", "profiles/default_profile/user" + suffix + ".cfg")
    original = root / "config" if edition == "toe" else game_directory(edition, root)
    result = {relative: (original / relative).read_bytes() for relative in paths}

    def setvar(relative, name, value, optional=False):
        data = result[relative]
        pattern = rb"(?m)^([ \t]*setvar[ \t]+" + re.escape(name.encode()) + rb"[ \t]*=[ \t]*)[^\r\n]*"
        data, count = re.subn(pattern, lambda m: m[1] + value.encode(), data)
        if count == 0 and optional:
            return
        if count != 1:
            raise ValueError(edition + ": bootstrap variable is missing or ambiguous: " + name)
        result[relative] = data

    auto = result[paths[0]]
    newline = b"\r\n" if b"\r\n" in auto else b"\n"
    # The lazy tracking worker reads this once; disable it before any startup command.
    auto, count = re.subn(rb"(?m)^[ \t]*setvar[ \t]+ubi_tracking_tool_enabled[ \t]*=[^\r\n]*(?:\r?\n|$)", b"", auto)
    if count > 1:
        raise ValueError(edition + ": bootstrap telemetry variable is ambiguous")
    result[paths[0]] = b"setvar ubi_tracking_tool_enabled = 0" + newline + auto
    if re.search(rb"(?m)^[ \t]*setvar[ \t]+ubi_tracking_tool_enabled[ \t]*=", result[paths[1]]):
        setvar(paths[1], "ubi_tracking_tool_enabled", "0")
    if edition == "toe":
        return result
    for name, value in {
        "Options.Tooltips.HoverTimeout": "0", "app_always_active": "1",
        "gfx_dynamic_lights": "0", "gfx_noshadows": "1", "gfx_resolution": "1280x800",
        "gfx_water_reflection": "0",
    }.items():
        setvar(paths[1], name, value)
    setvar(paths[1], "town_enable_flyby", "0", optional=True)
    return result
