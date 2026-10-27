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
import math
from contextlib import ExitStack
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
    ("port_cursor_offset_x", "port_cursor_offset_x", "port_camera_sensitivity",
     "Курсор: сдвиг по горизонтали",
     "Смещение точки действия относительно пальца в процентах короткой стороны экрана. "
     "Отрицательное значение — влево, положительное — вправо. Применяется к касанию, удержанию и перетаскиванию.",
     "Влево", "Вправо", (-0.2, -0.15, -0.1, -0.05, 0.0, 0.05, 0.1, 0.15, 0.2), 4),
    ("port_cursor_offset_y", "port_cursor_offset_y", "port_cursor_offset_x",
     "Курсор: сдвиг по вертикали",
     "Смещение точки действия относительно пальца в процентах короткой стороны экрана. "
     "Отрицательное значение — вверх, положительное — вниз. У края экрана курсор остаётся внутри поля.",
     "Вверх", "Вниз", (-0.2, -0.15, -0.1, -0.05, 0.0, 0.05, 0.1, 0.15, 0.2), 4),
    ("port_touch_cursor", "port_touch_cursor", "port_cursor_offset_y",
     "Показывать сенсорный курсор",
     "Показывать игровой курсор, пока палец касается экрана. Действие выполняется в позиции этого курсора, "
     "с учётом заданного смещения. Жесты камеры не перемещают курсор.",
     "Выкл.", "Вкл.", (0.0, 1.0), 0),
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
            if identifier == "port_fps_limit":
                label = f"{value:g} кадров/с" if value else "Частота экрана"
            elif identifier == "port_touch_cursor":
                label = "Вкл." if value else "Выкл."
            else:
                label = percent(value)
            out[f"{folder}/Item{index:02d}.txt"] = utf16(label)
    return out


def resource_archives(edition="toe"):
    from editions import edition_spec
    edition_spec(edition)
    base = ("data/p3c-data.pak", "data/p2-data.pak", "data/p1-data.pak", "data/p0-data.pak", "data/data.pak")
    return (("data/a2p1-data.pak", "data/data.pak") if edition == "toe" else
            ("dataa1/a1p1-data.pak", "dataa1/a1-data.pak", *base) if edition == "hof" else
            ("DataLS/p6-data.pak", "DataLS/p5-data.pak", *base))


def source_resource(game_dir, name, edition="toe"):
    for pak in resource_archives(edition):
        path = Path(game_dir) / pak
        if path.is_file():
            with zipfile.ZipFile(path) as archive:
                if name in archive.namelist():
                    return archive.read(name), Path(pak).name if edition == "toe" else pak
    raise FileNotFoundError(f"{edition}: {name} not found in {game_dir}")


def loading_logo(game_dir, edition="toe"):
    """Keep the original art, scaled above the map description instead of behind it."""
    folder = "UI/pwlscreen/"
    name = folder + "Logo.(WindowSimple).xdb"
    original, _ = source_resource(game_dir, name, edition)
    window = ET.fromstring(original)
    for key, value in {"Position/First/x": "0", "Position/First/y": "-144",
                       "Size/First/x": "640", "Size/First/y": "480"}.items():
        element = window.find("Placement/" + key)
        if element is None:
            raise ValueError(f"loading logo lacks {key}")
        element.text = value
    shared_name = folder + "Logo.(WindowSimpleShared).xdb"
    original, _ = source_resource(game_dir, shared_name, edition)
    shared = ET.fromstring(original)
    shared.find("Background").set("href", "PortLogo.(BackgroundSimpleScallingTexture).xdb#xpointer(/BackgroundSimpleScallingTexture)")
    background = b'''<?xml version="1.0" encoding="UTF-8"?>
<BackgroundSimpleScallingTexture>
  <ClassTypeID>285694784</ClassTypeID>
  <Texture href="FrontA2.(Texture).xdb#xpointer(/Texture)"/>
  <Color>-1</Color><Size><x>1024</x><y>768</y></Size>
</BackgroundSimpleScallingTexture>'''
    background = background.replace(b"FrontA2", {"toe": b"FrontA2", "vanilla": b"Front", "hof": b"FrontA1"}[edition])
    members = {shared_name: ET.tostring(shared, encoding="utf-8", xml_declaration=True),
               folder + "PortLogo.(BackgroundSimpleScallingTexture).xdb": background}
    if edition != "toe":
        # Older screens have no ALIGN_SCREEN field. Span the root, then center
        # its original 4:3 content frame; the artwork keeps the ToE thumbnail size.
        for axis in ("HorAllign", "VerAllign"):
            window.find("Placement/" + axis + "/First").text = "ERA_CENTER"
            window.find("Placement/" + axis + "/Second").text = "true"
        for path in ("UI/PWLScreen.(WindowScreen).xdb", "UI/PWLScreen.(WindowScreenShared).xdb",
                     folder + "Main.(WindowSimple).xdb", folder + "Main.(WindowSimpleShared).xdb"):
            node = ET.fromstring(source_resource(game_dir, path, edition)[0])
            placement = node.find("Placement")
            is_root = path.startswith("UI/PWLScreen.")
            placement.find("HorAllign/First").text = "EPA_MARGIN" if is_root else "ERA_CENTER"
            placement.find("HorAllign/Second").text = "true"
            for margin in ("LowerMargin", "UpperMargin"):
                placement.find(margin + "/First/x").text = "0"
                placement.find(margin + "/Second").text = "true"
            if not is_root:
                placement.find("Position/First/x").text = "0"
                placement.find("Position/Second").text = "true"
                placement.find("Size/First/x").text = "1024"
                placement.find("Size/First/y").text = "768"
                placement.find("Size/Second").text = "true"
            members[path] = ET.tostring(node, encoding="utf-8", xml_declaration=True)
    members[name] = ET.tostring(window, encoding="utf-8", xml_declaration=True)
    return members


def launcher_buttons(game_dir, edition="toe"):
    """Reuse the game's menu button, including its native input and rendering."""
    original, _ = source_resource(game_dir, "UI/GameOptions/Accept.(WindowMSButton).xdb", edition)
    members = {}
    for name, parent, x, y, centered in (
        ("PortOptionsLauncher", "UI/GameOptions/CategoryPanel.(WindowSimpleShared).xdb", 252, 490, False),
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
        original, _ = source_resource(game_dir, parent, edition)
        shared = ET.fromstring(original)
        ET.SubElement(shared.find("Children"), "Item", href=f"/{path}#xpointer(/WindowMSButton)")
        members[parent] = ET.tostring(shared, encoding="utf-8", xml_declaration=True)
        original, _ = source_resource(game_dir, "UI/GameOptions/Accept.(WindowMSButton).xdb", edition)
    members["UI/PortLauncher.(UISDirectRunReaction).xdb"] = b'''<UISDirectRunReaction>
      <ClassTypeID>554457792</ClassTypeID><SUIStateBaseFakeField>0</SUIStateBaseFakeField>
      <ReactionForward href="/UI/PortLauncher.(ARSendGameMessage).xdb#xpointer(/ARSendGameMessage)"/>
      <ReactionBackward/></UISDirectRunReaction>'''
    members["UI/PortLauncher.(ARSendGameMessage).xdb"] = b'''<ARSendGameMessage>
      <ClassTypeID>352859136</ClassTypeID><EventName>port_launcher</EventName><IntParam>0</IntParam>
      </ARSendGameMessage>'''
    # One more category needs one more row above the original menu buttons.
    menu_rows = ("MenuPanel.(WindowSimple).xdb", "Template.(WindowMSButton).xdb",
                 "Back.(WindowMSButton).xdb")
    if edition in ("toe", "vanilla"):
        menu_rows += ("CombatReplay.(WindowMSButton).xdb",)
    for name in menu_rows:
        path = "UI/GameOptions/" + name
        original, _ = source_resource(game_dir, path, edition)
        window = ET.fromstring(original)
        field = "Size" if name.startswith("MenuPanel.") else "Position"
        y = window.find(f"Placement/{field}/First/y")
        y.text = str(int(y.text) + 40)
        members[path] = ET.tostring(window, encoding="utf-8", xml_declaration=True)
    path = "UI/GameOptions/MenuPanel.(WindowSimpleShared).xdb"
    original, _ = source_resource(game_dir, path, edition)
    shared = ET.fromstring(original)
    shared.find("Background").set("href", "PortMenu.(BackgroundSimpleScallingTexture).xdb#xpointer(/BackgroundSimpleScallingTexture)")
    members[path] = ET.tostring(shared, encoding="utf-8", xml_declaration=True)
    members["UI/GameOptions/PortMenu.(BackgroundSimpleScallingTexture).xdb"] = b'''<BackgroundSimpleScallingTexture>
      <ClassTypeID>285694784</ClassTypeID><Texture href="MenuPanel.(Texture).xdb#xpointer(/Texture)"/>
      <Color>-1</Color><Size><x>328</x><y>240</y></Size></BackgroundSimpleScallingTexture>'''
    return members


def gamepad_button(game_dir, edition="toe"):
    """Use the taller single-player scroll for the seven native menu rows."""
    original, _ = source_resource(game_dir, "UI/MainMenu2/SingleGame.(WindowMSButton).xdb", edition)
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
               "UI/PortGamepad.txt": utf16("Управление"),
               "UI/PortGamepadTooltip.txt": utf16("Сенсорные жесты, разделение армий, курсор и геймпад. Открыть справку."),
               "UI/PortGamepad.(UISDirectRunReaction).xdb": b'''<UISDirectRunReaction>
                 <ClassTypeID>554457792</ClassTypeID><SUIStateBaseFakeField>0</SUIStateBaseFakeField>
                 <ReactionForward href="/UI/PortGamepad.(ARSendGameMessage).xdb#xpointer(/ARSendGameMessage)"/>
                 <ReactionBackward/></UISDirectRunReaction>''',
               "UI/PortGamepad.(ARSendGameMessage).xdb": b'''<ARSendGameMessage>
                 <ClassTypeID>352859136</ClassTypeID><EventName>port_gamepad</EventName><IntParam>0</IntParam>
                 </ARSendGameMessage>'''}
    parent = "UI/MainMenu2/Menu.(WindowSimpleShared).xdb"
    original, _ = source_resource(game_dir, parent, edition)
    shared = ET.fromstring(original)
    children = shared.find("Children")
    quit_item = next(item for item in children if "Quit.(WindowMSButton).xdb" in item.get("href", ""))
    children.remove(quit_item)
    ET.SubElement(children, "Item", href="/" + path + "#xpointer(/WindowMSButton)")
    switch = ET.fromstring(ET.tostring(button))
    switch.find("Name").text = "PortSwitchGame"
    switch.find("Placement/Position/First/y").text = "216"
    switch.find("TextFileRef").set("href", "/UI/PortSwitchGame.txt")
    switch.find("TooltipFileRef").set("href", "/UI/PortSwitchGameTooltip.txt")
    switch.find("ButtonStates/Item/CommandsOnEnterState/Commands/Item").set(
        "href", "/UI/PortSwitchGame.(UISDirectRunReaction).xdb#xpointer(/UISDirectRunReaction)")
    switch_path = "UI/MainMenu2/PortSwitchGame.(WindowMSButton).xdb"
    members[switch_path] = ET.tostring(switch, encoding="utf-8", xml_declaration=True)
    members["UI/PortSwitchGame.txt"] = utf16("Переключить игру")
    members["UI/PortSwitchGameTooltip.txt"] = utf16("Выбрать установленную игру или открыть лаунчер.")
    members["UI/PortSwitchGame.(UISDirectRunReaction).xdb"] = members[
        "UI/PortGamepad.(UISDirectRunReaction).xdb"].replace(b"PortGamepad", b"PortSwitchGame")
    members["UI/PortSwitchGame.(ARSendGameMessage).xdb"] = members[
        "UI/PortGamepad.(ARSendGameMessage).xdb"].replace(b"port_gamepad", b"port_switch_game")
    ET.SubElement(children, "Item", href="/" + switch_path + "#xpointer(/WindowMSButton)")
    children.append(quit_item)
    if edition != "hof":
        shared.find("Background").set("href",
            "/UI/MainMenu2/SinglePlayer/SinglePlayerBack.(BackgroundSimpleTexture).xdb#xpointer(/BackgroundSimpleTexture)")
    else:
        shared.find("Background").set("href", "PortMenu.(BackgroundSimpleScallingTexture).xdb#xpointer(/BackgroundSimpleScallingTexture)")
        members["UI/MainMenu2/PortMenu.(BackgroundSimpleScallingTexture).xdb"] = b'''<BackgroundSimpleScallingTexture>
          <ClassTypeID>285694784</ClassTypeID><Texture href="/UI/MainMenu2/Menu.(Texture).xdb#xpointer(/Texture)"/>
          <Color>-1</Color><Size><x>327</x><y>327</y></Size></BackgroundSimpleScallingTexture>'''
    members[parent] = ET.tostring(shared, encoding="utf-8", xml_declaration=True)
    menu_path = "UI/MainMenu2/Menu.(WindowSimple).xdb"
    original, _ = source_resource(game_dir, menu_path, edition)
    menu = ET.fromstring(original)
    menu.find("Placement/Size/First/y").text = "327"
    menu.find("Placement/Size/Second").text = "true"
    menu.find("Placement/Position/First/y").text = "-22" if edition == "toe" else "419"
    members[menu_path] = ET.tostring(menu, encoding="utf-8", xml_declaration=True)
    quit_path = "UI/MainMenu2/Quit.(WindowMSButton).xdb"
    original, _ = source_resource(game_dir, quit_path, edition)
    button = ET.fromstring(original)
    button.find("Placement/Position/First/y").text = "252"
    members[quit_path] = ET.tostring(button, encoding="utf-8", xml_declaration=True)
    return members


def inactive_chat_background(game_dir, edition="toe"):
    """Keep the chat activator clickable without painting its empty idle box."""
    name = "UI/MPChatInGame/ChatInputActivator.(WindowMSButtonShared).xdb"
    window = ET.fromstring(source_resource(game_dir, name, edition)[0])
    background = window.find("VisualStates/Item/Normal/Background")
    if background is None:
        raise ValueError("The native chat activator's idle background is missing")
    background.set("href", "")
    return {name: ET.tostring(window, encoding="utf-8", xml_declaration=True)}


def cutscene_horplus(game_dir, edition="toe"):
    """Expose the existing wide 3D viewport without scaling actors or fonts."""
    members = {}

    def resource(name):
        return ET.fromstring(source_resource(game_dir, name, edition)[0])

    def put(name, window):
        members[name] = ET.tostring(window, encoding="utf-8", xml_declaration=True)

    def horizontal(window, low=0, high=0):
        placement = window.find("Placement")
        placement.find("HorAllign/First").text = "EPA_MARGIN"
        placement.find("HorAllign/Second").text = "true"
        for name, value in (("LowerMargin", low), ("UpperMargin", high)):
            placement.find(name + "/First/x").text = str(value)
            placement.find(name + "/Second").text = "true"

    def bottom(window, height):
        placement = window.find("Placement")
        placement.find("VerAllign/First").text = "EPA_HIGH_END"
        placement.find("VerAllign/Second").text = "true"
        y = placement.find("Position/First/y")
        y.text = str(int(y.text) + height - 768)
        placement.find("Position/Second").text = "true"

    for screen, shared in (("DialogueScreen", "DialogueScreen"),
                           ("CutsceneScreen", "CusceneScreen")):
        name = f"UI/{screen}.(WindowScreen).xdb"
        window = resource(name)
        # 1.6/2.1 use Placement; the separate screen-alignment fields arrived in 3.1.
        for axis in ("HorAlign", "VerAlign"):
            alignment = window.find(axis)
            if alignment is not None:
                alignment.text = "ALIGN_SCREEN"
        horizontal(window)
        window.find("Placement/VerAllign/First").text = "EPA_MARGIN"
        window.find("Placement/VerAllign/Second").text = "true"
        put(name, window)
        name = f"UI/{shared}.(WindowScreenShared).xdb"
        window = resource(name)
        horizontal(window)
        window.find("Placement/VerAllign/First").text = "EPA_MARGIN"
        window.find("Placement/VerAllign/Second").text = "true"
        children = window.find("Children")
        for child in list(children):
            if child.get("href", "").startswith("Common/BlackBorder/"):
                children.remove(child)
        put(name, window)

    for panel, height in (("DialogueTop", 64), ("DialoguePanel", 256)):
        name = f"UI/DialogueScreen/{panel}.(WindowSimple).xdb"
        window = resource(name)
        horizontal(window)
        if panel == "DialoguePanel":
            bottom(window, height)
        put(name, window)
        name = f"UI/DialogueScreen/{panel}.(WindowSimpleShared).xdb"
        window = resource(name)
        background_name = f"Port{panel}.(BackgroundSimpleScallingTexture).xdb"
        window.find("Background").set("href", background_name + "#xpointer(/BackgroundSimpleScallingTexture)")
        put(name, window)
        members[f"UI/DialogueScreen/{background_name}"] = (
            '<BackgroundSimpleScallingTexture><ClassTypeID>285694784</ClassTypeID>'
            f'<Texture href="{panel}.(Texture).xdb#xpointer(/Texture)"/>'
            f'<Color>-1</Color><Size><x>1024</x><y>{height}</y></Size>'
            '</BackgroundSimpleScallingTexture>').encode()

    name = "UI/DialogueScreen/SkipScene.(WindowMSButton).xdb"
    window = resource(name)
    window.find("Placement/HorAllign/First").text = "EPA_HIGH_END"
    window.find("Placement/HorAllign/Second").text = "true"
    window.find("Placement/Position/First/x").text = "-36"
    bottom(window, 49)
    put(name, window)
    for label, height in (("HeroName", 31), ("HeroText", 84)):
        name = f"UI/DialogueScreen/{label}.(WindowTextView).xdb"
        window = resource(name)
        horizontal(window, 51, 188)
        bottom(window, height)
        put(name, window)
    name = "UI/DialogueScreen/HeroFace.(WindowSimple).xdb"
    window = resource(name)
    bottom(window, 128)
    put(name, window)
    name = "UI/CutsceneScreen/SubtitlesArea.(WindowStaticText).xdb"
    window = resource(name)
    horizontal(window)
    put(name, window)
    return members


def legacy_widescreen(game_dir, reference_dir, edition, members):
    """Use the later game's anchor policy with each old screen's own geometry.

    At 1024x768 every rebased control keeps its old position and size. Wider
    parents move edge groups and centres; their icons, fonts and native actions
    remain original. Only children of a full-span screen/container are rebased.
    """
    if edition == "toe":
        return {}
    import posixpath
    modes = {"EPA_LOW_END": 0, "ERA_CENTER": 1, "EPA_HIGH_END": 2, "EPA_MARGIN": 3}
    aligns = {"ALIGN_LOW_END": 0, "ALIGN_CENTER": 1, "ALIGN_HIGH_END": 2, "ALIGN_SCREEN": 3}
    changed = {}
    with ExitStack() as stack:
        def index(folder, version):
            result = {}
            for pak in reversed(resource_archives(version)):
                path = Path(folder) / pak
                if not path.is_file():
                    continue
                archive = stack.enter_context(zipfile.ZipFile(path))
                for name in archive.namelist():
                    if name.lower().startswith("ui/") and name.lower().endswith(".xdb"):
                        result[name.lower()] = (name, archive)
            return result
        originals, reference = index(game_dir, edition), index(reference_dir, "toe")
        critical = ("AdventureScreen-Heavy", "TownScreen", "HeroScreen3", "CombatScreen-Heavy",
                    "MainMenu2", "GameOptions", "SetFirstProfileName/SetFirstProfileName")
        for screen in critical:
            name = ("UI/" + screen + ".(WindowScreen).xdb").lower()
            if name not in originals or name not in reference:
                raise ValueError(edition + ": required widescreen reference resource is missing: " + name)
        cache = {}
        overlay = {name.lower(): name for name in members}

        def load(name, guide=False):
            key = (guide, name.lower())
            if key not in cache:
                actual, archive = (reference if guide else originals)[name.lower()]
                data = members[overlay[name.lower()]] if not guide and name.lower() in overlay else archive.read(actual)
                cache[key] = ET.fromstring(data)
            return cache[key]

        def linked(name, href):
            path = href.split("#", 1)[0]
            return path.lstrip("/") if path.startswith("/") else posixpath.normpath(posixpath.dirname(name) + "/" + path)

        def field(name, label, guide=False, seen=()):
            if name.lower() in seen:
                raise ValueError("Cyclic UI Shared resource: " + name)
            node = load(name, guide)
            own = node.find("Placement/" + label)
            shared = node.find("Shared")
            if own is not None and (own.findtext("Second") == "true" or shared is None or not shared.get("href")):
                return own.find("First")
            if shared is not None and shared.get("href"):
                return field(linked(name, shared.get("href")), label, guide, (*seen, name.lower()))
            return own.find("First") if own is not None else None

        def value(name, label):
            node = field(name, label)
            return [float(node.findtext(axis)) for axis in ("x", "y")]

        def put(name):
            actual = originals[name.lower()][0]
            changed[overlay.get(name.lower(), actual)] = ET.tostring(load(name), encoding="utf-8", xml_declaration=True)

        def set_mode(name, axis, mode):
            label = ("HorAllign", "VerAllign")[axis]
            node = load(name).find("Placement/" + label)
            node.find("First").text = tuple(modes)[mode]
            node.find("Second").text = "true"

        def set_vector(name, label, values):
            node = load(name).find("Placement/" + label)
            for axis, number in zip(("x", "y"), values):
                node.find("First/" + axis).text = format(number, ".9g")
            node.find("Second").text = "true"

        def children(name):
            node = load(name)
            shared = node.find("Shared")
            result = children(linked(name, shared.get("href"))) if shared is not None and shared.get("href") else []
            return list(dict.fromkeys(result + [linked(name, child.get("href")) for child in node.findall("Children/Item")]))

        def migrate(name, span, seen, policies=None):
            if name.lower() in seen or name.lower() not in originals or name.lower() not in reference:
                return
            seen.add(name.lower())
            node = load(name)
            if node.find("Placement") is None:
                return
            before = ET.tostring(node)
            position, size = value(name, "Position"), value(name, "Size")
            lower, upper = value(name, "LowerMargin"), value(name, "UpperMargin")
            full = []
            for axis, label in enumerate(("HorAllign", "VerAllign")):
                old = modes[field(name, label).text]
                new = policies[axis] if policies is not None else modes[field(name, label, True).text]
                extent = span[axis] - lower[axis] - upper[axis] if old == 3 else size[axis]
                origin = (lower[axis] if old == 3 else position[axis] +
                          math.trunc((span[axis] - math.trunc(extent)) * .5) if old == 1 else
                          position[axis] + span[axis] - extent if old == 2 else position[axis])
                if old != new:
                    set_mode(name, axis, new)
                    if new == 3:
                        lower[axis], upper[axis] = origin, span[axis] - origin - extent
                    else:
                        position[axis] = origin - (math.trunc((span[axis] - math.trunc(extent)) * .5) if new == 1 else
                                                  span[axis] - extent if new == 2 else 0)
                        size[axis] = extent
                full.append(new == 3 and abs(origin) < 1 and abs(extent - span[axis]) < 1)
            if ET.tostring(node) != before:
                set_vector(name, "Position", position)
                set_vector(name, "Size", size)
                set_vector(name, "LowerMargin", lower)
                set_vector(name, "UpperMargin", upper)
                put(name)
            if all(full):
                for child in children(name):
                    migrate(child, span, seen)

        for key, (name, _) in originals.items():
            if not key.endswith(".(windowscreen).xdb") or key not in reference:
                continue
            # These have their own reviewed art/caption/skip placement above.
            if key in ("ui/pwlscreen.(windowscreen).xdb", "ui/dialoguescreen.(windowscreen).xdb", "ui/cutscenescreen.(windowscreen).xdb"):
                continue
            guide = load(name, True)
            policies = [guide.findtext(label) for label in ("HorAlign", "VerAlign")]
            if any(policy not in aligns for policy in policies):
                if any(key == ("UI/" + screen + ".(WindowScreen).xdb").lower() for screen in critical):
                    raise ValueError(edition + ": unrecognized ToE widescreen screen policy: " + name)
                continue
            migrate(name, (1024, 768), set(), [aligns[policy] for policy in policies])
        # Its ToE resource also retains the old left anchor; native town-name text uses this window.
        migrate("UI/TownScreen/BuildingDesc.(WindowStaticText).xdb", (1024, 768), set(), [1, 0])
        # UIGameRoot creates this five-button hero dial separately from the screen's children.
        migrate("UI/Common/JogDial/JogDial.xdb", (1024, 768), set())
    return changed


def build_port_ui_override(root=ROOT, game_dir=None, edition="toe"):
    root = Path(root)
    if game_dir is None:
        from editions import game_directory
        game_dir = game_directory(edition, root)
    game_dir = root / game_dir
    original, source = source_resource(game_dir, UICONSTS, edition)
    patched = patch_uiconsts(original)
    members = {UICONSTS: patched, **texts(), **loading_logo(game_dir, edition), **launcher_buttons(game_dir, edition),
               **gamepad_button(game_dir, edition)}
    if edition != "toe":
        from editions import game_directory
        members.update(legacy_widescreen(game_dir, game_directory("toe", root), edition, members))
    # Apply custom scene geometry after the shared ToE anchor migration.
    members.update(cutscene_horplus(game_dir, edition))
    members.update(inactive_chat_background(game_dir, edition))
    output = root / ("build/data-overrides" + ("-" + edition if edition != "toe" else "")) / PAK_NAME
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
        "edition": edition,
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
