"""A stale, missing or incomplete patch must stop native/APK preflight."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import warnings
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import port_patches as patches


class PatchContractTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.save("config/editions.json", json.loads((ROOT / "config/editions.json").read_text()))
        self.source = self.root / "android/host/required.c"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b"unsigned required_hook = 0x00401234u;\nvoid required_patch(void) {}\n")
        self.original = b"original engine fixture"
        sha = hashlib.sha256(self.original).hexdigest()
        self.save("config/vanilla.modules.json", [dict(name="game", file="game.exe", exe=True, sha256=sha)])
        image = self.root / "generated/vanilla/input/game.exe"
        image.parent.mkdir(parents=True)
        image.write_bytes(self.original)
        self.save("generated/vanilla/game-x86/report.json", dict(status="GENERATED", binary_sha256=sha,
                  rebased_sha256=sha, sources=["game.c"]))
        (self.root / "generated/vanilla/game-x86/game.c").write_bytes(b"void sub_00405678(void) {\nold\n}\n")
        relative = "android/host/required.c"
        self.contract = dict(
            edition="vanilla", engine_sha256=sha,
            features={feature: [relative] for feature in patches.REQUIRED_FEATURES},
            sources={relative: patches.digest(self.source)},
            reference_addresses={relative: ["00401234"]}, addresses={"00401234": "00405678"},
            generated_patches=[dict(module="game", function="sub_00405678", old="old", new="new")])
        generated = self.root / "generated/vanilla/game-x86/game.c"
        bodies = [generated.read_text()]
        for function, count in patches.TEXTURE_GENERATED_HOOKS['vanilla'].items():
            lines = []
            for index in range(count):
                old = 'texture_old_' + str(index) + ';'
                lines.append(old)
                self.contract['generated_patches'].append(dict(module='game', function=function, old=old,
                    new='/* /zz_port_textures_v2.pak 0x40000000u 0x80000000u */ texture_new_' + str(index) + ';'))
            bodies.append('void ' + function + '(void) {\n' + '\n'.join(lines) + '\n}\n')
        generated.write_text(''.join(bodies))
        self.save_contract()
        self.library = self.root / "build/arm64-vanilla/libhomm5_vanilla.so"
        self.library.parent.mkdir(parents=True)
        self.library.write_bytes(b"linked fixture")

    def save(self, path, data):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(data), encoding="utf-8")

    def save_contract(self):
        self.save("config/vanilla.patches.json", self.contract)

    def validate(self):
        return patches.validate_native_inputs("vanilla", self.root)

    def test_omitting_each_required_patch_or_its_pin_fails(self):
        original = copy.deepcopy(self.contract)
        for feature in patches.REQUIRED_FEATURES:
            with self.subTest(feature=feature):
                self.contract = copy.deepcopy(original)
                del self.contract["features"][feature]
                self.save_contract()
                with self.assertRaisesRegex(ValueError, "coverage"):
                    self.validate()
        self.contract = original
        self.contract["sources"] = {}
        self.save_contract()
        with self.assertRaisesRegex(ValueError, "pinned implementation"):
            self.validate()

    def test_changed_source_wrong_engine_or_incomplete_mapping_fails(self):
        self.validate()
        raw = self.source.read_bytes()
        self.source.write_bytes(b"void required_patch(void) { return; }\n")
        with self.assertRaisesRegex(ValueError, "implementation changed"):
            self.validate()

        self.source.write_bytes(raw)
        self.contract["engine_sha256"] = "0" * 64
        self.save_contract()
        with self.assertRaisesRegex(ValueError, "different original engine"):
            self.validate()
        self.contract["engine_sha256"] = hashlib.sha256(self.original).hexdigest()
        self.contract["addresses"] = {}
        self.save_contract()
        with self.assertRaisesRegex(ValueError, "unmapped"):
            self.validate()

    def test_git_line_endings_preserve_reviewed_source_identity(self):
        self.source.write_bytes(self.source.read_bytes().replace(b"\n", b"\r\n"))
        self.validate()

    def test_receipt_binds_library_source_and_manifest(self):
        with self.assertRaisesRegex(ValueError, "receipt is missing"):
            patches.validate_packaged_native("vanilla", self.library, self.root)
        patches.finalize_native_receipt("vanilla", self.library, self.root)
        patches.validate_packaged_native("vanilla", self.library, self.root)
        self.library.write_bytes(b"another edition or stale library")
        with self.assertRaisesRegex(ValueError, "receipt is stale"):
            patches.validate_packaged_native("vanilla", self.library, self.root)

    def test_generated_patch_requires_its_exact_anchor(self):
        original = b"void sub_00405678(void) {\nold\n}\n"
        replacement = b"void sub_00405678(void) {\nnew\n}\n"
        self.assertEqual(patches.adapt_generated_source(original, "game", "vanilla", self.root), replacement)
        other = b"void sub_00408000(void) {\nRECOMP_CALL(sub_00405678); old;\n}\n"
        self.assertEqual(patches.adapt_generated_source(other, "game", "vanilla", self.root), other)
        self.assertEqual(patches.adapt_generated_source(original + other, "game", "vanilla", self.root), replacement + other)
        with self.assertRaisesRegex(ValueError, "anchor changed"):
            patches.adapt_generated_source(original.replace(b"old", b"changed"), "game", "vanilla", self.root)

    def test_each_texture_mount_metadata_and_alias_hook_is_required(self):
        original = copy.deepcopy(self.contract)
        for index in range(1, len(original['generated_patches'])):
            with self.subTest(hook=index):
                self.contract = copy.deepcopy(original)
                del self.contract['generated_patches'][index]
                self.save_contract()
                with self.assertRaisesRegex(ValueError, 'mandatory texture hooks'):
                    self.validate()

    def test_generation_image_cannot_be_substituted(self):
        image = self.root / "generated/vanilla/input/game.exe"
        image.write_bytes(b"another original engine")
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.validate()

    def test_missing_duplicated_or_changed_generated_hook_stops_preflight(self):
        source = self.root / "generated/vanilla/game-x86/game.c"
        original = source.read_bytes()
        for changed in (original.replace(b"sub_00405678", b"sub_00408000"), original + original,
                        original.replace(b"old", b"changed")):
            with self.subTest(changed=changed):
                source.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, "generated hook"):
                    self.validate()

    def test_edition_guard_excludes_only_its_inactive_branch(self):
        source = b'''#ifndef OTHER
#if HOMM5_LEGACY_UI
old_engine();
#ifdef APP
app();
#endif
#else
toe_only();
#endif
#if !HOMM5_LEGACY_UI
toe_second();
#else
legacy_second();
#endif
#ifdef HOMM5_LEGACY_UI
legacy_third();
#endif
#ifndef HOMM5_LEGACY_UI
toe_third();
#endif
#endif
'''
        legacy = patches.legacy_ui_branch(source, True)
        toe = patches.legacy_ui_branch(source, False)
        self.assertIn(b"old_engine();", legacy)
        self.assertIn(b"legacy_second();", legacy)
        self.assertIn(b"legacy_third();", legacy)
        self.assertNotIn(b"toe_third();", legacy)
        self.assertNotIn(b"toe_only();", legacy)
        self.assertNotIn(b"toe_second();", legacy)
        self.assertIn(b"#ifndef OTHER", legacy)
        self.assertIn(b"#ifdef APP", legacy)
        self.assertIn(b"toe_only();", toe)
        self.assertIn(b"toe_second();", toe)
        self.assertIn(b"toe_third();", toe)
        self.assertNotIn(b"legacy_third();", toe)
        self.assertNotIn(b"old_engine();", toe)
        for invalid in (b"#if HOMM5_LEGACY_UI\n", b"#endif\n", b"#if HOMM5_LEGACY_UI\n#elif OTHER\n#endif\n"):
            with self.assertRaises(ValueError):
                patches.legacy_ui_branch(invalid, True)


class OverlayContractTest(unittest.TestCase):
    def fixture(self, edition, root):
        import port_ui
        import town_music
        (root / 'config/music').mkdir(parents=True)
        (root / 'config/editions.json').write_bytes((ROOT / 'config/editions.json').read_bytes())
        folder = root / 'overlay'
        (folder / 'data').mkdir(parents=True)
        suffix = patches.edition_spec(edition, root)['profile_suffix']
        for relative in ('profiles/autoexec' + suffix + '.cfg',
                         'profiles/default_profile/user' + suffix + '.cfg'):
            file = folder / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text('setvar ubi_tracking_tool_enabled = 0\n' if '/autoexec' in relative else 'test profile')
        with zipfile.ZipFile(folder / 'data' / port_ui.PAK_NAME, 'w') as ui:
            ui.writestr('UI/MPChatInGame/ChatInputActivator.(WindowMSButtonShared).xdb',
                '<WindowMSButtonShared><VisualStates><Item><Normal><Background href=""/>'
                '</Normal></Item></VisualStates></WindowMSButtonShared>')
            ui.writestr(port_ui.UICONSTS, '<Root>' + ''.join('<ID>' + row[0] + '</ID>' for row in port_ui.OPTIONS) + '</Root>')
            for name in ('UI/DialogueScreen.(WindowScreenShared).xdb',
                         'UI/CusceneScreen.(WindowScreenShared).xdb',
                         'UI/CutsceneScreen/SubtitlesArea.(WindowStaticText).xdb'):
                ui.writestr(name, '<WindowScreenShared><Children/></WindowScreenShared>')
            for panel in ('DialogueTop', 'DialoguePanel'):
                ui.writestr('UI/DialogueScreen/' + panel + '.(WindowSimple).xdb',
                    '<WindowSimple><Placement><HorAllign><First>EPA_MARGIN</First><Second>true</Second></HorAllign>'
                    '<VerAllign><First>EPA_HIGH_END</First><Second>true</Second></VerAllign>'
                    '<Position><First><x>0</x><y>0</y></First><Second>true</Second></Position></Placement></WindowSimple>')
            ui.writestr('UI/PortGamepad.(ARSendGameMessage).xdb',
                        '<ARSendGameMessage><EventName>port_gamepad</EventName></ARSendGameMessage>')
            ui.writestr('UI/PortSwitchGame.(ARSendGameMessage).xdb',
                        '<ARSendGameMessage><EventName>port_switch_game</EventName></ARSendGameMessage>')
            ui.writestr('UI/MainMenu2/Menu.(WindowSimple).xdb',
                        '<WindowSimple><Placement><Size><First><y>327</y></First></Size></Placement></WindowSimple>')
            if edition != 'toe':
                ui.writestr('UI/Common/JogDial/JogDial.xdb',
                    '<WindowSimple><Placement><HorAllign><First>EPA_HIGH_END</First><Second>true</Second></HorAllign>'
                    '<VerAllign><First>EPA_HIGH_END</First><Second>true</Second></VerAllign></Placement></WindowSimple>')
                for screen in ('AdventureScreen-Heavy', 'TownScreen', 'HeroScreen3', 'CombatScreen-Heavy',
                               'MainMenu2', 'GameOptions', 'SetFirstProfileName/SetFirstProfileName'):
                    mode = 'ERA_CENTER' if screen.startswith('SetFirstProfileName/') else 'EPA_MARGIN'
                    ui.writestr('UI/' + screen + '.(WindowScreen).xdb',
                        '<WindowScreen><Placement><HorAllign><First>' + mode +
                        '</First><Second>true</Second></HorAllign></Placement></WindowScreen>')
        originals = {name: ('<Music><FileName>test/' + edition + '/' + name + '</FileName>'
            '<FadeIn>2000</FadeIn><FadeOut>2000</FadeOut><MinPausedTime>1000</MinPausedTime>'
            '<MaxPausedTime>10000</MaxPausedTime></Music>').encode() for name in town_music.TOWNS_BY_EDITION[edition]}
        manifest = 'manifest.json' if edition == 'toe' else edition + '.json'
        (root / 'config/music' / manifest).write_text(json.dumps(
            {name: hashlib.sha256(data).hexdigest() for name, data in originals.items()}))
        entries = [('Sounds/_(Music)/Towns/' + name,
            data.replace(b'<MinPausedTime>1000', b'<MinPausedTime>0').replace(b'<MaxPausedTime>10000', b'<MaxPausedTime>0'),
            town_music.ZIP_DATE) for name, data in originals.items()]
        music = folder / 'data' / town_music.PAK_NAME
        self.write_music(music, entries)
        if edition != 'toe':
            for packed in (folder / 'data' / port_ui.PAK_NAME, music):
                with zipfile.ZipFile(packed) as archive:
                    for name in archive.namelist():
                        target = folder / 'data' / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.read(name))
        return folder, music, entries

    def write_music(self, path, entries):
        with warnings.catch_warnings(), zipfile.ZipFile(path, 'w') as archive:
            warnings.simplefilter('ignore', UserWarning)  # Deliberate duplicate-member negative case.
            for name, payload, date in entries:
                archive.writestr(zipfile.ZipInfo(name, date), payload)

    def test_complete_music_is_bound_to_overlay_receipt_for_each_edition(self):
        for edition in ('toe', 'vanilla', 'hof'):
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                folder, music, _ = self.fixture(edition, root)
                result = patches.validate_overlay(edition, folder, root)
                self.assertEqual(result['town_music_sha256'], patches.digest(music))
                self.assertIn('audio', result['features'])

    def test_missing_incomplete_stale_or_altered_music_stops_overlay_preflight(self):
        cases = ('missing_archive', 'missing_town', 'duplicate_town', 'extra_town',
                 'minimum_pause', 'maximum_pause', 'file_name', 'fade', 'timestamp', 'wrong_manifest')
        for edition in ('toe', 'vanilla', 'hof'):
            for case in cases:
                with self.subTest(edition=edition, case=case), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    folder, music, entries = self.fixture(edition, root)
                    name, payload, date = entries[0]
                    if case == 'missing_archive':
                        music.unlink()
                    elif case == 'missing_town':
                        self.write_music(music, entries[1:])
                    elif case == 'duplicate_town':
                        self.write_music(music, entries + entries[:1])
                    elif case == 'extra_town':
                        self.write_music(music, entries + [('Sounds/_(Music)/Towns/another-edition.xdb', payload, date)])
                    elif case == 'wrong_manifest':
                        manifest = root / 'config/music' / ('manifest.json' if edition == 'toe' else edition + '.json')
                        contents = json.loads(manifest.read_text())
                        contents.pop(name.rsplit('/', 1)[1])
                        manifest.write_text(json.dumps(contents))
                    else:
                        if case == 'minimum_pause':
                            payload = payload.replace(b'<MinPausedTime>0', b'<MinPausedTime>1000')
                        elif case == 'maximum_pause':
                            payload = payload.replace(b'<MaxPausedTime>0', b'<MaxPausedTime>10000')
                        elif case == 'file_name':
                            payload = payload.replace(b'<FileName>test/', b'<FileName>changed/')
                        elif case == 'fade':
                            payload = payload.replace(b'<FadeIn>2000', b'<FadeIn>0')
                        else:
                            date = (2007, 1, 1, 0, 0, 0)
                        self.write_music(music, [(name, payload, date)] + entries[1:])
                    with self.assertRaisesRegex(ValueError, 'town music'):
                        patches.validate_overlay(edition, folder, root)

    def test_telemetry_cannot_be_missing_enabled_late_or_overridden(self):
        for edition in ('toe', 'vanilla', 'hof'):
            for case in ('missing', 'enabled', 'late', 'override', 'duplicate', 'user_override'):
                with self.subTest(edition=edition, case=case), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    folder, _, _ = self.fixture(edition, root)
                    suffix = patches.edition_spec(edition, root)['profile_suffix']
                    auto = folder / ('profiles/autoexec' + suffix + '.cfg')
                    disabled = b'setvar ubi_tracking_tool_enabled = 0\n'
                    if case == 'missing': auto.write_bytes(b'mainmenu\n')
                    elif case == 'enabled': auto.write_bytes(disabled.replace(b'= 0', b'= 1'))
                    elif case == 'late': auto.write_bytes(b'mainmenu\n' + disabled)
                    elif case == 'override': auto.write_bytes(disabled + disabled.replace(b'= 0', b'= 1'))
                    elif case == 'duplicate': auto.write_bytes(disabled * 2)
                    else:
                        (folder / ('profiles/default_profile/user' + suffix + '.cfg')).write_bytes(disabled.replace(b'= 0', b'= 1'))
                    with self.assertRaisesRegex(ValueError, 'telemetry'):
                        patches.validate_overlay(edition, folder, root)

    def test_missing_or_changed_loose_resources_stop_legacy_overlay_preflight(self):
        import port_ui
        for edition in ('vanilla', 'hof'):
            for resource in (port_ui.UICONSTS, 'UI/AdventureScreen-Heavy.(WindowScreen).xdb',
                             'Sounds/_(Music)/Towns/Haven.(Music).xdb'):
                for defect in ('missing', 'stale'):
                    with self.subTest(edition=edition, resource=resource, defect=defect), tempfile.TemporaryDirectory() as temp:
                        root = Path(temp)
                        folder, _, _ = self.fixture(edition, root)
                        target = folder / 'data' / resource
                        if defect == 'missing': target.unlink()
                        else: target.write_bytes(b'stale original bank resource')
                        with self.assertRaisesRegex(ValueError, 'loose override'):
                            patches.validate_overlay(edition, folder, root)

    def test_missing_or_overwritten_horplus_panel_stops_packaging(self):
        import port_ui
        for edition in ('toe', 'vanilla', 'hof'):
            for defect in ('missing', 'horizontal', 'bottom'):
                with self.subTest(edition=edition, defect=defect), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    folder, _, _ = self.fixture(edition, root)
                    path = folder / 'data' / port_ui.PAK_NAME
                    with zipfile.ZipFile(path) as archive:
                        members = {name: archive.read(name) for name in archive.namelist()}
                    panel = 'UI/DialogueScreen/DialoguePanel.(WindowSimple).xdb'
                    if defect == 'missing': del members[panel]
                    elif defect == 'horizontal': members[panel] = members[panel].replace(b'EPA_MARGIN', b'EPA_LOW_END')
                    else: members[panel] = members[panel].replace(b'EPA_HIGH_END', b'EPA_LOW_END')
                    with zipfile.ZipFile(path, 'w') as archive:
                        for name, contents in members.items(): archive.writestr(name, contents)
                    with self.assertRaisesRegex(ValueError, 'Hor\\+ panel'):
                        patches.validate_overlay(edition, folder, root)

    def test_missing_or_visible_inactive_chat_background_stops_overlay_preflight(self):
        import port_ui
        for edition in ('toe', 'vanilla', 'hof'):
            for defect in ('missing', 'background'):
                with self.subTest(edition=edition, defect=defect), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    folder, _, _ = self.fixture(edition, root)
                    path = folder / 'data' / port_ui.PAK_NAME
                    with zipfile.ZipFile(path) as archive:
                        entries = {name: archive.read(name) for name in archive.namelist()}
                    key = 'UI/MPChatInGame/ChatInputActivator.(WindowMSButtonShared).xdb'
                    if defect == 'missing': del entries[key]
                    else: entries[key] = entries[key].replace(b'href=""', b'href="old-background.xdb"')
                    with zipfile.ZipFile(path, 'w') as archive:
                        for name, data in entries.items(): archive.writestr(name, data)
                    with self.assertRaisesRegex(ValueError, 'inactive chat background'):
                        patches.validate_overlay(edition, folder, root)

    def test_missing_or_wrong_hero_dial_stops_overlay_preflight(self):
        import port_ui
        for edition in ('vanilla', 'hof'):
            for defect in ('missing', 'anchor'):
                with self.subTest(edition=edition, defect=defect), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    folder, _, _ = self.fixture(edition, root)
                    path = folder / 'data' / port_ui.PAK_NAME
                    with zipfile.ZipFile(path) as archive:
                        entries = {name: archive.read(name) for name in archive.namelist()}
                    key = 'UI/Common/JogDial/JogDial.xdb'
                    if defect == 'missing': del entries[key]
                    else: entries[key] = entries[key].replace(b'EPA_HIGH_END', b'EPA_LOW_END')
                    with zipfile.ZipFile(path, 'w') as archive:
                        for name, data in entries.items(): archive.writestr(name, data)
                    with self.assertRaisesRegex(ValueError, 'hero dial'):
                        patches.validate_overlay(edition, folder, root)

    def test_missing_or_fixed_aspect_legacy_screen_stops_overlay_preflight(self):
        import port_ui
        for edition in ('vanilla', 'hof'):
            for defect in ('missing', 'fixed_aspect'):
                with self.subTest(edition=edition, defect=defect), tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    folder, _, _ = self.fixture(edition, root)
                    ui = folder / 'data' / port_ui.PAK_NAME
                    with zipfile.ZipFile(ui) as archive:
                        entries = {name: archive.read(name) for name in archive.namelist()}
                    key = 'UI/AdventureScreen-Heavy.(WindowScreen).xdb'
                    if defect == 'missing': del entries[key]
                    else: entries[key] = entries[key].replace(b'EPA_MARGIN', b'EPA_LOW_END')
                    with zipfile.ZipFile(ui, 'w') as archive:
                        for name, data in entries.items(): archive.writestr(name, data)
                    with self.assertRaisesRegex(ValueError, 'widescreen'):
                        patches.validate_overlay(edition, folder, root)


if __name__ == "__main__":
    unittest.main()
