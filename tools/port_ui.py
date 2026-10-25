"""Build the Android port's UI override archive; never edit game archives.

The game's options pages are data (UI/uiconsts.(UIGameConstsH5).xdb): each
option names a console variable. The override adds the port's settings as
native scrollers bound to the port's variables (android/host/port_settings.c):

    Additional: render scale, interface scale, frame limit, camera sensitivity

and makes the tooltip delay's "Standard" value instant. Texts are UTF-16
files beside the game's own (UI/Consts/GameOptions/Port*). The archive is
a .pak in the overlay's data folder: H5 loads every data/*.pak, later names
taking precedence.
"""
import hashlib
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
PAK_NAME = "z_homm5_android_ui.pak"
ZIP_DATE = (2026, 10, 21, 0, 0, 0)
UICONSTS = "UI/uiconsts.(UIGameConstsH5).xdb"
TEXTS = "Consts/GameOptions"

# (id, variable, after option id, name, tooltip, low label, high label, values, default index)
OPTIONS = (
    ("port_render_scale", "port_render_scale", "ScreenResolution",
     "Масштаб рендера",
     "Разрешение трёхмерной картинки относительно экрана. Меньший масштаб повышает частоту кадров и снижает "
     "чёткость; интерфейс остаётся чётким.",
     "25%", "100%", (0.25, 0.35, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0), 7),
    ("port_ui_scale", "port_ui_scale", "port_render_scale",
     "Масштаб интерфейса",
       "Размер текста, кнопок и панелей. 100% — исходный размер. Большие окна автоматически "
       "уменьшаются до размера экрана.",
     "50%", "200%", (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0), 2),
    ("port_fps_limit", "port_fps_limit", "port_ui_scale",
     "Частота кадров",
     "Предел частоты кадров: меньшее значение снижает нагрузку на процессор и расход батареи. "
     "60 кадров/с — обычный режим; «Частота экрана» снимает дополнительное ограничение.",
     "30", "Экран", (30.0, 45.0, 60.0, 0.0), 2),
    ("port_camera_sensitivity", "port_camera_sensitivity", "adv_camera_mode",
     "Чувствительность камеры",
     "Скорость поворота, приближения и наклона камеры жестами двумя пальцами.",
     "Низкая", "Высокая", (0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0), 3),
)


def utf16(text):
    return b"\xff\xfe" + text.encode("utf-16-le")


def percent(value):
    return f"{round(value * 100)}%"


def option_xml(option, indent="\t\t\t\t\t\t\t"):
    identifier, variable, _, _, _, _, _, values, default = option
    folder = f"{TEXTS}/Port_{identifier}"
    t = indent
    lines = [f"{t}<Item>",
             f"{t}\t<ID>{identifier}</ID>",
             f"{t}\t<Type>OPTION_SCROLLER</Type>",
             f'{t}\t<NameFileRef href="{folder}/Name.txt"/>',
             f'{t}\t<TooltipFileRef href="{folder}/Tooltip.txt"/>',
             f"{t}\t<Items>"]
    for index, value in enumerate(values):
        lines += [f"{t}\t\t<Item>",
                  f'{t}\t\t\t<NameFileRef href="{folder}/Item{index:02d}.txt"/>',
                  f"{t}\t\t\t<Value>{value:g}</Value>",
                  f"{t}\t\t</Item>"]
    lines += [f"{t}\t</Items>",
              f"{t}\t<ItemsGlobalVar/>",
              f"{t}\t<UseItemNameAsValue>false</UseItemNameAsValue>",
              f"{t}\t<GlobalVar1>{variable}</GlobalVar1>",
              f"{t}\t<GlobalVar2/>",
              f"{t}\t<DefaultValue1>{default}</DefaultValue1>",
              f"{t}\t<DefaultValue2>0</DefaultValue2>",
              f"{t}\t<OptionToDisableID/>",
              f"{t}\t<OptionDisableByValue1>0</OptionDisableByValue1>",
              f"{t}\t<OptionToDisableValue1>0</OptionToDisableValue1>",
              f"{t}\t<DisableByCodeGlobalVar/>",
              f"{t}\t<LabelsFileRef>",
              f'{t}\t\t<Item href="{folder}/Label00.txt"/>',
              f'{t}\t\t<Item href="{folder}/Label01.txt"/>',
              f"{t}\t</LabelsFileRef>",
              f"{t}\t<Hide>false</Hide>",
              f"{t}\t<Global>false</Global>",
              f"{t}\t<Group/>",
              f"{t}\t<Preview>false</Preview>",
              f"{t}</Item>"]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def patch_uiconsts(data):
    for option in OPTIONS:
        if f"<ID>{option[0]}</ID>".encode() in data:
            raise ValueError(f"uiconsts already has {option[0]}")
    end = data.index(b"</Categories>", data.index(b"<GameOptions>"))
    category = b'''<Item>
      <ID>port_additional</ID>
      <MenuButtonNameFileRef href="Consts/GameOptions/PortAdditional.txt"/>
      <NameFileRef href="Consts/GameOptions/PortAdditional.txt"/>
      <TooltipFileRef href="Consts/GameOptions/PortAdditionalTooltip.txt"/>
      <Pages>'''
    for identifier, name, options in (("port_video", "PortVideo", OPTIONS[:3]),
                                      ("port_controls", "PortControls", OPTIONS[3:])):
        category += (f'<Item><ID>{identifier}</ID><NameFileRef href="Consts/GameOptions/{name}.txt"/>'
                     '<TooltipFileRef href="Consts/GameOptions/PortAdditionalTooltip.txt"/><Options>').encode()
        category += b"".join(option_xml(option) for option in options) + b"</Options></Item>"
    category += b"</Pages><Enabled>true</Enabled></Item>"
    data = data[:end] + category + data[end:]
    # The tooltip delay's Standard value: instant (item 0, value 0).
    at = data.find(b"<ID>tooltip_delay</ID>")
    default = re.compile(rb"<DefaultValue1>\d+</DefaultValue1>")
    match = default.search(data, at)
    if at < 0 or not match or match.start() > data.find(b"</Item>\r\n\t\t\t\t\t\t\t<Item>", at):
        raise ValueError("tooltip_delay default not found")
    return data[:match.start()] + b"<DefaultValue1>0</DefaultValue1>" + data[match.end():]


def texts():
    out = {f"UI/{TEXTS}/PortAdditional.txt": utf16("Дополнительные"),
           f"UI/{TEXTS}/PortVideo.txt": utf16("Изображение"),
           f"UI/{TEXTS}/PortControls.txt": utf16("Управление"),
           f"UI/{TEXTS}/PortAdditionalTooltip.txt": utf16("Настройки Android-порта и переход в лаунчер."),
           "UI/PortLauncher.txt": utf16("В лаунчер"),
           "UI/PortLauncherTooltip.txt": utf16("Завершить игру и открыть лаунчер. Сначала сохраните игру."),
           "UI/ExitGameQuestion/Header.txt": utf16("Выход из игры"),
           "UI/ExitGameQuestion/Question.txt": utf16("Завершить игру? Несохранённый прогресс будет потерян.")}
    for identifier, _, _, name, tooltip, low, high, values, _ in OPTIONS:
        folder = f"UI/{TEXTS}/Port_{identifier}"
        out[f"{folder}/Name.txt"] = utf16(name)
        out[f"{folder}/Tooltip.txt"] = utf16(tooltip)
        out[f"{folder}/Label00.txt"] = utf16(low)
        out[f"{folder}/Label01.txt"] = utf16(high)
        for index, value in enumerate(values):
            label = (f"{value:g} кадров/с" if value else "Частота экрана") if identifier == "port_fps_limit" else percent(value)
            out[f"{folder}/Item{index:02d}.txt"] = utf16(label)
    return out


def source_resource(game_dir, name):
    data_dir = Path(game_dir) / "data"
    for pak in ("a2p1-data.pak", "data.pak"):
        path = data_dir / pak
        if path.is_file():
            with zipfile.ZipFile(path) as archive:
                if name in archive.namelist():
                    return archive.read(name), pak
    raise FileNotFoundError(f"{name} not found in {data_dir}")


def loading_logo(game_dir):
    """Keep the original art, scaled above the map description instead of behind it."""
    folder = "UI/pwlscreen/"
    name = folder + "Logo.(WindowSimple).xdb"
    original, _ = source_resource(game_dir, name)
    window = ET.fromstring(original)
    for key, value in {"Position/First/x": "0", "Position/First/y": "-144",
                       "Size/First/x": "640", "Size/First/y": "480"}.items():
        element = window.find("Placement/" + key)
        if element is None:
            raise ValueError(f"loading logo lacks {key}")
        element.text = value
    shared_name = folder + "Logo.(WindowSimpleShared).xdb"
    original, _ = source_resource(game_dir, shared_name)
    shared = ET.fromstring(original)
    shared.find("Background").set("href", "PortLogo.(BackgroundSimpleScallingTexture).xdb#xpointer(/BackgroundSimpleScallingTexture)")
    background = b'''<?xml version="1.0" encoding="UTF-8"?>
<BackgroundSimpleScallingTexture>
  <ClassTypeID>285694784</ClassTypeID>
  <Texture href="FrontA2.(Texture).xdb#xpointer(/Texture)"/>
  <Color>-1</Color><Size><x>1024</x><y>768</y></Size>
</BackgroundSimpleScallingTexture>'''
    return {name: ET.tostring(window, encoding="utf-8", xml_declaration=True),
            shared_name: ET.tostring(shared, encoding="utf-8", xml_declaration=True),
            folder + "PortLogo.(BackgroundSimpleScallingTexture).xdb": background}


def launcher_buttons(game_dir):
    """Reuse the game's menu button, including its native input and rendering."""
    original, _ = source_resource(game_dir, "UI/GameOptions/Accept.(WindowMSButton).xdb")
    members = {}
    for name, parent, x, y, centered in (
        ("PortOptionsLauncher", "UI/GameOptions/CategoryPanel.(WindowSimpleShared).xdb", 252, 490, False),
        ("PortExitLauncher", "UI/ExitGameQuestion.(WindowScreenShared).xdb", 0, 90, True),
    ):
        button = ET.fromstring(original)
        button.attrib.pop("ObjectRecordID", None)
        button.find("Name").text = name
        button.find("Visible").text = "true" if centered else "false"
        button.find("Priority").text = "1000"
        button.find("GameMessageReactions").clear()
        button.find("TextFileRef").set("href", "/UI/PortLauncher.txt")
        button.find("TooltipFileRef").set("href", "/UI/PortLauncherTooltip.txt")
        for field, value in {"Position/First/x": x, "Position/First/y": y,
                             "Size/First/x": 122, "Size/First/y": 34}.items():
            button.find("Placement/" + field).text = str(value)
        button.find("Placement/Size/Second").text = "true"
        for axis in ("HorAllign", "VerAllign"):
            button.find(f"Placement/{axis}/First").text = "ERA_CENTER" if centered else "EPA_LOW_END"
        for margin in ("LowerMargin", "UpperMargin"):
            button.find(f"Placement/{margin}/Second").text = "false"
        command = button.find("ButtonStates/Item/CommandsOnEnterState/Commands/Item")
        command.set("href", "/UI/PortLauncher.(UISDirectRunReaction).xdb#xpointer(/UISDirectRunReaction)")
        path = f"UI/{name}.(WindowMSButton).xdb"
        members[path] = ET.tostring(button, encoding="utf-8", xml_declaration=True)
        original, _ = source_resource(game_dir, parent)
        shared = ET.fromstring(original)
        ET.SubElement(shared.find("Children"), "Item", href=f"/{path}#xpointer(/WindowMSButton)")
        members[parent] = ET.tostring(shared, encoding="utf-8", xml_declaration=True)
        original, _ = source_resource(game_dir, "UI/GameOptions/Accept.(WindowMSButton).xdb")
    members["UI/PortLauncher.(UISDirectRunReaction).xdb"] = b'''<UISDirectRunReaction>
      <ClassTypeID>554457792</ClassTypeID><SUIStateBaseFakeField>0</SUIStateBaseFakeField>
      <ReactionForward href="/UI/PortLauncher.(ARSendGameMessage).xdb#xpointer(/ARSendGameMessage)"/>
      <ReactionBackward/></UISDirectRunReaction>'''
    members["UI/PortLauncher.(ARSendGameMessage).xdb"] = b'''<ARSendGameMessage>
      <ClassTypeID>352859136</ClassTypeID><EventName>port_launcher</EventName><IntParam>0</IntParam>
      </ARSendGameMessage>'''
    # One more category needs one more row above the original menu buttons.
    for name in ("MenuPanel.(WindowSimple).xdb", "Template.(WindowMSButton).xdb",
                 "CombatReplay.(WindowMSButton).xdb", "Back.(WindowMSButton).xdb"):
        path = "UI/GameOptions/" + name
        original, _ = source_resource(game_dir, path)
        window = ET.fromstring(original)
        field = "Size" if name.startswith("MenuPanel.") else "Position"
        y = window.find(f"Placement/{field}/First/y")
        y.text = str(int(y.text) + 40)
        members[path] = ET.tostring(window, encoding="utf-8", xml_declaration=True)
    path = "UI/GameOptions/MenuPanel.(WindowSimpleShared).xdb"
    original, _ = source_resource(game_dir, path)
    shared = ET.fromstring(original)
    shared.find("Background").set("href", "PortMenu.(BackgroundSimpleScallingTexture).xdb#xpointer(/BackgroundSimpleScallingTexture)")
    members[path] = ET.tostring(shared, encoding="utf-8", xml_declaration=True)
    members["UI/GameOptions/PortMenu.(BackgroundSimpleScallingTexture).xdb"] = b'''<BackgroundSimpleScallingTexture>
      <ClassTypeID>285694784</ClassTypeID><Texture href="MenuPanel.(Texture).xdb#xpointer(/Texture)"/>
      <Color>-1</Color><Size><x>328</x><y>240</y></Size></BackgroundSimpleScallingTexture>'''
    return members


def gamepad_button(game_dir):
    """Sixth native menu row fits the original panel's unused bottom space."""
    original, _ = source_resource(game_dir, "UI/MainMenu2/SingleGame.(WindowMSButton).xdb")
    button = ET.fromstring(original)
    button.attrib.pop("ObjectRecordID", None)
    button.find("Name").text = "PortGamepad"
    button.find("Placement/Position/First/y").text = "180"
    button.find("TextFileRef").set("href", "/UI/PortGamepad.txt")
    button.find("TooltipFileRef").set("href", "/UI/PortGamepadTooltip.txt")
    command = button.find("ButtonStates/Item/CommandsOnEnterState/Commands/Item")
    command.set("href", "/UI/PortGamepad.(UISDirectRunReaction).xdb#xpointer(/UISDirectRunReaction)")
    path = "UI/MainMenu2/PortGamepad.(WindowMSButton).xdb"
    members = {path: ET.tostring(button, encoding="utf-8", xml_declaration=True),
               "UI/PortGamepad.txt": utf16("Геймпад"),
               "UI/PortGamepadTooltip.txt": utf16("Курсор, камера и кнопки геймпада. Открыть справку."),
               "UI/PortGamepad.(UISDirectRunReaction).xdb": b'''<UISDirectRunReaction>
                 <ClassTypeID>554457792</ClassTypeID><SUIStateBaseFakeField>0</SUIStateBaseFakeField>
                 <ReactionForward href="/UI/PortGamepad.(ARSendGameMessage).xdb#xpointer(/ARSendGameMessage)"/>
                 <ReactionBackward/></UISDirectRunReaction>''',
               "UI/PortGamepad.(ARSendGameMessage).xdb": b'''<ARSendGameMessage>
                 <ClassTypeID>352859136</ClassTypeID><EventName>port_gamepad</EventName><IntParam>0</IntParam>
                 </ARSendGameMessage>'''}
    parent = "UI/MainMenu2/Menu.(WindowSimpleShared).xdb"
    original, _ = source_resource(game_dir, parent)
    shared = ET.fromstring(original)
    ET.SubElement(shared.find("Children"), "Item", href="/" + path + "#xpointer(/WindowMSButton)")
    members[parent] = ET.tostring(shared, encoding="utf-8", xml_declaration=True)
    quit_path = "UI/MainMenu2/Quit.(WindowMSButton).xdb"
    original, _ = source_resource(game_dir, quit_path)
    button = ET.fromstring(original)
    button.find("Placement/Position/First/y").text = "216"
    members[quit_path] = ET.tostring(button, encoding="utf-8", xml_declaration=True)
    return members


def build_port_ui_override(root=ROOT, game_dir=None):
    root = Path(root)
    if game_dir is None:
        game_dir = json.loads((root / "port.json").read_text(encoding="utf-8"))["game_directory"]
    game_dir = root / game_dir
    original, source = source_resource(game_dir, UICONSTS)
    patched = patch_uiconsts(original)
    members = {UICONSTS: patched, **texts(), **loading_logo(game_dir), **launcher_buttons(game_dir),
               **gamepad_button(game_dir)}
    output = root / "build/data-overrides" / PAK_NAME
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".pak.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, ZIP_DATE)
            info.create_system = 0
            info.external_attr = 0x20
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, members[name], compresslevel=9)
    temporary.replace(output)
    receipt = {
        "pak": PAK_NAME, "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "size": output.stat().st_size, "source": source,
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "options": [option[0] for option in OPTIONS],
    }
    (output.parent / (PAK_NAME[:-4] + ".json")).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return output, receipt


if __name__ == "__main__":
    path, receipt = build_port_ui_override()
    print(path)
    print(json.dumps(receipt, indent=2, ensure_ascii=False))
