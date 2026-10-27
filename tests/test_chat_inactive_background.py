"""The real edition UI archives hide only the empty idle chat decoration."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from editions import game_directory
import port_ui

SHARED = "UI/MPChatInGame/ChatInputActivator.(WindowMSButtonShared).xdb"


def semantic(node):
    return node.tag, node.attrib, (node.text or "").strip(), [semantic(child) for child in node]


class InactiveChatBackgroundTest(unittest.TestCase):
    def test_actual_edition_archives_keep_chat_controls_and_active_panels(self):
        try:
            games = {edition: game_directory(edition) for edition in ("toe", "vanilla", "hof")}
        except (FileNotFoundError, ValueError):
            self.skipTest("Original edition resource configuration unavailable")
        if any(not game.is_dir() for game in games.values()):
            self.skipTest("Original edition resources unavailable")
        output = ROOT / "build/tests"
        output.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="chat-idle-final-", dir=output) as folder:
            root = Path(folder)
            (root / "port.json").write_text(json.dumps({
                "game_directory": str(games["toe"]),
                "editions": {edition: {"game_directory": str(game)} for edition, game in games.items()},
            }), encoding="utf-8")
            for edition, game in games.items():
                with self.subTest(edition=edition):
                    source = ET.fromstring(port_ui.source_resource(game, SHARED, edition)[0])
                    expected = copy.deepcopy(source)
                    idle = expected.find("VisualStates/Item/Normal/Background")
                    self.assertTrue(idle.get("href"))
                    idle.set("href", "")
                    path, _ = port_ui.build_port_ui_override(root, game, edition)
                    with zipfile.ZipFile(path) as archive:
                        actual = ET.fromstring(archive.read(SHARED))
                        self.assertEqual(semantic(actual), semantic(expected))
                        self.assertEqual(actual.find("VisualStates/Item/Normal/Background").get("href"), "")
                        self.assertEqual(actual.findtext("TriggerMode"), "BCST_ON_RELEASE")
                        # These are separate native resources. The idle-decoration
                        # patch does not replace the editor, toggle or incoming chat.
                        for name in (
                            "ChatInputActivator.(WindowMSButton).xdb",
                            "ChatInputPanel.(WindowSimple).xdb",
                            "ChatInputPanel.(WindowSimpleShared).xdb",
                            "InputBox.(WindowEditBox).xdb",
                            "ChatToggle.(WindowMSButton).xdb",
                            "ChatToggle.(WindowMSButtonShared).xdb",
                            "ChatOutputPanel.(WindowSimple).xdb",
                            "ChatOutputPanel.(WindowSimpleShared).xdb",
                        ):
                            member = "UI/MPChatInGame/" + name
                            self.assertNotIn(member.lower(), {n.lower() for n in archive.namelist()})
                            original = ET.fromstring(port_ui.source_resource(game, member, edition)[0])
                            self.assertIsNotNone(original)
                    activator = ET.fromstring(port_ui.source_resource(
                        game, "UI/MPChatInGame/ChatInputActivator.(WindowMSButton).xdb", edition)[0])
                    self.assertEqual(activator.findtext("Name"), "ChatInputActivatorBtn")
                    self.assertEqual(activator.findtext("Visible"), "true")
                    self.assertEqual(activator.findtext("Enabled"), "true")
                    self.assertEqual([activator.findtext("Placement/Size/First/" + axis) for axis in ("x", "y")], ["193", "56"])
                    reaction = activator.find("ButtonStates/Item/CommandsOnEnterState/Commands/Item")
                    self.assertEqual(reaction.get("href"), "ChatInputActivate.(UISRunReaction).xdb#xpointer(/UISRunReaction)")


if __name__ == "__main__":
    unittest.main()
