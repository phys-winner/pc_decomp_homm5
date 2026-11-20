"""Build the optional static mods for all three Heroes V editions."""

from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from editions import game_directory
from port_ui import ROOT, source_resource


EDITIONS = ("vanilla", "hof", "toe")
ARENA = "Arenas/Interface/MainMenu/MainMenu.(ArenaDesc).xdb"
MENU = "UI/MainMenu2/Main.(WindowSimpleShared).xdb"
FILL_TEMPLATE = "UI/AfterGameSplash/back.(BackgroundSimpleScallingTexture).xdb"
MENU_FILL = "UI/MainMenu2/StaticMenuFill.(BackgroundSimpleScallingTexture).xdb"
HEROES = "_(Model)/Heroes/"
STOCK_SYMBOLS = (
    "DemonLord_Path/Symbol.(Model).xdb", "Knight_Path/Symbol.(Model).xdb",
    "Necromancer_Path/Symbol.xdb", "Orc_Warrior_Path/Symbol.xdb",
    "Ranger_Path/Symbol.xdb", "RuneMage_Path/Symbol.xdb",
    "Warlock_Path/Symbol.xdb", "Wizard_Path/Symbol.xdb",
)


def read_xml(path, edition):
    return ET.fromstring(source_resource(game_directory(edition), path, edition)[0])


def xml_bytes(node):
    return ET.tostring(node, encoding="utf-8", xml_declaration=True)


def static_menu():
    arena = read_xml(ARENA, "toe")
    for tag in ("ExpScene", "ExpSrcClipFolder", "objects", "lights", "effects",
                "sounds", "AmbientLights"):
        arena.find(tag).clear()
    # The legacy menu setup dereferences its camera role even with an empty scene.
    camera = arena.find("cameraFlyupRole/AnimSet")
    camera.set("href", "Camera.(AnimSet).xdb#xpointer(/AnimSet)")

    menu = read_xml(MENU, "toe")
    for edition in EDITIONS:
        read_xml("Arenas/Interface/MainMenu/Camera.(AnimSet).xdb", edition)
        original = read_xml(MENU, edition)
        if xml_bytes(original) != xml_bytes(menu):
            raise ValueError(f"Unexpected main menu layout in {edition}")
    fill = read_xml(FILL_TEMPLATE, "toe")
    if fill.find("Texture").attrib or len(fill.find("Texture")):
        raise ValueError("The menu background template must be an untextured fill")
    # The brown at the top of the ToE loading screen, as signed ARGB.
    fill.find("Color").text = str(0xFF5E4A47 - (1 << 32))
    menu.find("Background").set("href", f"/{MENU_FILL}#xpointer(/BackgroundSimpleScallingTexture)")
    return {ARENA: xml_bytes(arena), MENU: xml_bytes(menu), MENU_FILL: xml_bytes(fill)}


def static_hero_markers():
    members = {}
    for edition in EDITIONS:
        for symbol in STOCK_SYMBOLS:
            if symbol.startswith("Orc_") and edition != "toe":
                continue
            if symbol.startswith("RuneMage_") and edition == "vanilla":
                continue
            path = HEROES + symbol
            node = read_xml(path, edition)
            material = node.find("Materials/Item/Material")
            if material is None:
                href = node.find("Materials/Item").get("href").split("#", 1)[0]
                path = (PurePosixPath(path).parent / href).as_posix()
                node = material = read_xml(path, edition)
            speed = material.find("FloatParam")
            if material.findtext("AlphaMode") != "AM_OVERLAY" or speed.text not in {"1", "-1"}:
                raise ValueError(f"Unexpected hero marker material in {edition}: {path}")
            speed.text = "0"
            data = xml_bytes(node)
            if members.setdefault(path, data) != data:
                raise ValueError(f"Incompatible hero marker material in {edition}: {path}")
    return members


def write_mod(path, members):
    with ZipFile(path, "w") as archive:
        for name, data in sorted(members.items()):
            archive.writestr(ZipInfo(name, (2026, 11, 19, 0, 0, 0)), data, ZIP_DEFLATED)
    with ZipFile(path) as archive:
        if archive.testzip() or {name: archive.read(name) for name in archive.namelist()} != members:
            raise ValueError(f"Failed to verify {path}")


def main():
    output = ROOT / "pub/mods"
    output.mkdir(parents=True, exist_ok=True)
    # Maps/*.h5m is the archive scan shared by all three stock engines.
    write_mod(output / "zzzz_h5_static_main_menu.h5m", static_menu())
    write_mod(output / "zzzz_h5_static_hero_markers.h5m", static_hero_markers())


if __name__ == "__main__":
    main()
