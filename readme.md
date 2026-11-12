# pc_decomp_homm5

Heroes of Might and Magic V, Hammers of Fate and Tribes of the East on Android ARM64 through static
x86 recompilation, with native touch controls and a Direct3D 9 to OpenGL ES bridge.

**Current version: 0.6-dev.** All three engines use ThinLTO and their own device-trained PGO profiles.
This is an experimental port for sideloading.
The original game's menus, adventure maps, towns, battles, sound and saves run
through a local Win32 compatibility host. The game and eight DLLs are translated
from x86 to C ahead of time, then compiled into a separate native library for
each edition with the Android NDK.

## Supported original games

The build inputs are the Russian releases of the three games from
[Heroes of Might and Magic 5: Bundle on GOG](https://www.gog.com/en/game/heroes_of_might_and_magic_5_bundle).
Use your own installed copies. Other languages, executable revisions and mods
are not verified build inputs.
The APK uses two original-data folders: one complete GOG Gold installation for
Heroes V 1.6 + Hammers of Fate 2.1, and a separate GOG Tribes of the East 3.1
installation. It keeps three **Play** choices and separate edition settings and saves.

| Edition ID | Original version | Input manifest | Native library |
| --- | --- | --- | --- |
| `toe` | Tribes of the East 3.1 | [`config/modules.json`](config/modules.json) | `libhomm5.so` |
| `vanilla` | Heroes V 1.6 | [`config/vanilla.modules.json`](config/vanilla.modules.json) | `libhomm5_vanilla.so` |
| `hof` | Hammers of Fate 2.1 | [`config/hof.modules.json`](config/hof.modules.json) | `libhomm5_hof.so` |

The SHA-256 values of each required executable and DLL are pinned in these
manifests. The lifter verifies every input
before copying, unpacking or relocating it. The original installation is read
only; unpacked images and generated C go into ignored local directories.
The launcher provides separate game cards, processes, settings and saves. Existing
ToE paths remain compatible with earlier builds. Native patch contracts also pin
the edition-specific host mappings and required port features; APK packaging
requires all three patched libraries and resource overlays, including when
`--skip-native` is used.

Vanilla 1.6 and HoF 2.1 have device coverage for profile creation, scenario
selection, original saves, adventure maps, battles, deployment and troop splitting.
The legacy engines use their own call-protocol and x87 analyses, mapped hot paths,
and PGO profiles; the build verifies that these inputs belong to the selected edition.
Original-binary ABI checks and host regression tests cover their adapted native entry
points. These checks and representative gameplay do not establish campaign completion
or compatibility with every map.

The older games use ToE's widescreen anchor policy with their own window geometry.
Their font scaling follows ToE's equal horizontal and vertical glyph scale.
Legacy UI overrides are also installed as loose resources: expansion
archives take precedence over a new base PAK. Packaging and CLI deployment verify
that every loose resource exactly matches its reviewed override archive.
Ubisoft tracking is disabled before the startup commands in all three editions.

Original EXE/DLL files, resource archives, music, videos, maps and saves are not
distributed in this repository. The APK reads `H5_Game.exe` and `granny2.dll`
directly from the selected original installation (`bin`, or `bina1` for HoF),
after checking their size and SHA-256 on a startup worker. It carries the remaining
prepared DLLs. Town music uses the original resources and pause settings.

## Current capabilities and limits

- Original menus, profile creation, scenario loading, adventure maps, towns,
  battles, saving and loading have been exercised during development.
- Heroes sheltered in a Sanctuary are excluded from quick combat in all three
  editions, preventing a stalled AI turn in the reproduced Inferno campaign case.
  The player's Quick Combat setting and eligibility elsewhere are preserved.
- Touch input supports selection, movement, camera gestures, tooltips,
  spell targeting, troop and artifact transfers, and the Android keyboard.
- Additional game settings control render scale, interface scale, frame limit,
  camera sensitivity, touch cursor offset and optional touch cursor display.
  The default frame limit is 60 FPS.
- LAN play has been tested between Android devices and between Android and the
  original PC game with ToE 3.1. Peers use the same original game version and data;
  those checks do not establish LAN coverage for the other editions. Network
  discovery depends on the local Wi-Fi network.
- The launcher accepts an installed GOG game folder, a ZIP containing its files,
  or an offline GOG setup EXE with its adjacent BIN files. Vanilla and HoF share
  one Gold folder; ToE has its own folder. The launcher can convert DXT textures
  to ASTC/ETC2 and skip the intro videos.
- The launcher's **4 GB address space** option lets each 32-bit engine use
  addresses above 2 GB. Its initial default is on when Android reports at least
  5 GiB of physical RAM; a saved player choice takes priority. Changes apply at
  the next game start. The port preserves the original EXE and implements this
  in its runtime; the Windows `4gb_patch.exe` utility is not bundled or executed.
- An optional launcher switch, off by default, applies the MMH5.5 New Creature
  Framework patches to ToE 3.1 (1000 creature records, IDs up to 999; random maps skip creatures
  without map objects): the `Original` group of
  [NewCreatureFramework.yml](https://github.com/Might-Magic-Heroes-5-5/MMH55/blob/master/Frameworks/NewCreatureFramework/NewCreatureFramework.yml).
  Enable it only for a mod that provides those creatures: without their files the
  game does not start. Vanilla and HoF are unaffected.
- Every edition uses OpenGL ES;
  see [Renderers](#renderers).
- ARM64 Android 8.0 or later and OpenGL ES 3.2 are required. The manifest targets
  API 37; Android 11+ uses the launcher's All files access permission, and Android
  8–10 uses the storage permission.
- Native libraries and APK packaging support 16 KiB alignment. This does not
  establish testing on a device with 16 KiB memory pages.
- Campaign completion, every map, every GPU and every Android version have not
  been verified. Development test results are not a complete compatibility claim.

## Renderers

OpenGL ES 3.2 is the only enabled renderer for all editions. Renderer choices
saved by older launchers are ignored. The APK excludes DXVK and Turnip libraries
and does not run a Vulkan driver probe.

OpenGL ES spatial filters independently reconstruct the
scene (bilinear, bicubic, or FSR 1 EASU plus adjustable RCAS) and UI textures
(nearest, bilinear, bicubic, or FSR 1 EASU). UI filtering preserves alpha at
transparent edges. These spatial filters do not provide temporal accumulation
or frame generation and apply to the OpenGL ES renderer.

The GLES bridge records commands for a dedicated render thread, which owns the EGL
context and publishes completed GPU query results without blocking the game thread.
Dynamic buffers retain D3D9 DISCARD/NOOVERWRITE semantics, and UI/filter targets stay
at display resolution. For a same-build comparison, put `0` or `1` in the edition's
`userdata/render-thread` file before launch (`VOID_RENDER_THREAD` takes precedence
in shell builds). Both modes execute the same commands. `--rt-check` on the native
or APK builder enables GL thread ownership diagnostics. `VOID_RT_CORES` selects
`auto` (default), `big`, `next`, or `any` (no additional affinity). Auto uses the
second capacity tier on SoCs with at least three tiers, the top tier on two-tier
SoCs with multiple top-tier cores, and the lower tier when the top has one core.
Homogeneous or unknown capacities keep the inherited scheduling mask. The `[rt]`
startup log records the selected policy and any affinity failure.

On Snapdragon 865 / Adreno 650, two alternating pairs on the same diagnostic APK
gave 50.3 -> 59.4 FPS for the near adventure view (about 264 draws) and 34.9 -> 45.9
for the far view (about 468 draws). Far-view game-thread CPU time fell from 27.0
to 21.0 ms per frame. These are warmed, stationary views at 2400x1080 output,
70% scene scale and a 60 FPS cap; they include thermal and scheduling noise and
do not establish the same gain on other phones or in battles.

## Build requirements

Use the current shared launcher base with grouped game folders, the GOG importer,
the `PortHooks.installationProblem` and `PortHooks.verifyInstallation` hooks, and
the static `Launch.folder(context, distribution, part)` accessor. The older
`patches/launcher/installation-conflicts.patch` and
`patches/launcher/dxt-status.patch` document the conflict/DXT changes; they do not
add grouped folders or the GOG importer to an older base.
For a newer base that already displays DXT support in folding section headings,
use `patches/launcher/dxt-status-folded.patch` instead of `dxt-status.patch` to keep
the support message bold, red when unsupported and green when supported.

The current scripts build on **Windows x64**, without Gradle. Install:

| Tool | Version / requirement |
| --- | --- |
| Python | 3.13 used during development |
| Android SDK platform | `platforms;android-37.0` (the APK targets SDK 37) |
| Android SDK Build Tools | `build-tools;36.1.0` |
| Android NDK | `27.2.12479018` |
| Android SDK CMake | `cmake;3.22.1`, including Ninja |
| JDK | 17 or later; 24.0.1 used during development |
| Git | In `PATH`, for fetching and verifying the pinned GOG reader sources |
| UPX | 5.2.1, for unpacking the private copy of `fmod.dll` |

The launcher is the shared port launcher base, a sibling project
(`../launcher`, or an `android/launcher` submodule, or the folder named by
`PORT_LAUNCHER`); `tools/build_game_apk.py` renders it into the package
`org.homm5.port.launcher` from the game's description in
[`android/port.json`](android/port.json).

Python requirements are pinned in [`requirements.txt`](requirements.txt).
The needed source snapshots of pcrecomp, MojoShader, dlmalloc, astcenc and etcpak
are vendored in `reference/`; zlib sources support desktop regression tests.
Versions, origins and local adaptations are recorded in
[`dependencies.json`](dependencies.json) and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
Keep the supplied MojoShader snapshot: a plain upstream checkout omits the
legacy shader fixes used by this port.

The GOG reader uses pinned innoextract 1.9, liblzma 5.4.7, bzip2 1.0.8 and
Boost 1.84.0. `tools/build_innoextract.py --fetch --jobs 2` fetches those sources
into ignored `reference/` directories and builds the standalone ARM64/API 26
reader at `build/gog-android/libinnoextract.so`, with its build receipt beside it.
The first fetch needs network access; later builds reuse the pinned local sources.
The APK builder also invokes this reader build when GOG import is enabled in
`android/port.json`. A Stronghold checkout is not needed to build it.
The reader's licenses are included in the APK and available in
[`licenses/innoextract.txt`](licenses/innoextract.txt),
[`licenses/boost.txt`](licenses/boost.txt),
[`licenses/bzip2.txt`](licenses/bzip2.txt) and
[`licenses/liblzma.txt`](licenses/liblzma.txt).

## Build the APK

Run these commands from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

$env:ANDROID_HOME = Join-Path $env:LOCALAPPDATA "Android\Sdk"
$env:ANDROID_NDK = Join-Path $env:ANDROID_HOME "ndk\27.2.12479018"
$env:JAVA_HOME = Read-Host "JDK installation directory"
$homm5Upx = Read-Host "Path to upx.exe"

Copy-Item port.example.json port.json
notepad port.json
```

Set `game_directory` to the ToE installation, and set
`editions.vanilla.game_directory` and `editions.hof.game_directory` to the same
complete GOG Gold installation, for example `C:/Games/Heroes of Might and Magic V`.
The build retains a field per engine because Vanilla reads `bin` and HoF reads
`bina1` inside that one installation.
Absolute paths and
paths relative to the repository root are supported. Use forward slashes or
escaped backslashes in JSON. The example uses `originals/tribes-of-the-east`.
`device` is optional and is needed only for developer deployment tools.
The personal `port.json` and the entire `originals/` directory stay outside Git.

The scripts resolve the SDK using `ANDROID_SDK`, `ANDROID_HOME`, then
`ANDROID_SDK_ROOT`, or the current account's usual Windows SDK location.
`ANDROID_NDK` overrides the pinned NDK under that SDK. Set `JAVA_HOME` explicitly.

Generate the modules for all three editions, then compile and package:

```powershell
python tools/build_innoextract.py --fetch --jobs 2
foreach ($homm5Edition in @("toe", "vanilla", "hof")) {
    python -X utf8 tools/lift_homm5.py --edition $homm5Edition --upx $homm5Upx
    if ($LASTEXITCODE -ne 0) { throw "Generation failed: $homm5Edition" }
}
python -X utf8 tools/call_protocol.py
python -X utf8 tools/x87_locals.py
python -X utf8 tools/build_game_apk.py --thinlto --no-pgo
```

Output: **`build/android-game/heroes-v.apk`**.

The archived DXVK/Turnip source and pinned dependencies remain in the repository
for development. Shipping engines compile the GLES stubs, the launcher exposes
only GLES, and the default APK omits the Vulkan runtime. `tools/build_dxvk.py`
and the APK builder's internal `--dxvk` staging option do not enable that backend
in a shipping engine.

Packaging requires XZ Utils 5.4+ for its ARM64 branch filter (`XZ`, `PATH`, or
Git for Windows' `mingw64/bin/xz.exe`). All three engines are stored as XZ
assets with 128 MiB independent chunks. The small bundled XZ Embedded decoder
unpacks only the selected engine in the background on its first start after
an update. Its size and SHA-256 are checked before an atomic rename from
`.part`; later starts reuse the completed copy in private app storage.
Allow about 132 MB per engine with the current optimized builds, plus the previous
copy while replacing it after an update. Compression changes APK size, not
the game engines, resources or their installed sizes.

Generation creates checked PE images and C sources under `generated/` for ToE,
`generated/vanilla/` for the base game and `generated/hof/` for HoF. Function
catalogs use the matching edition directory, while the original ToE catalog
paths remain under `config/`. These are all local
build outputs. Compilation fingerprints sources, headers, compiler and flags
before reusing objects. The APK builder compiles the texture converter and Java
launcher, includes the prepared DLLs and port overlays, aligns the APK and
signs it with a locally generated development key.
Native builds remap embedded source paths to repository-relative names.

The two analysis steps produce `build/call-protocol/summary.json` and `x87.json`
for ToE. Run them again after regenerating or repairing its lifted functions.
The legacy editions use their own generated code and ABI mappings; they do not
reuse ToE register or x87 analysis reports.

For lower memory use and fewer compilation workers:

```powershell
foreach ($homm5Edition in @("toe", "vanilla", "hof")) {
    python -X utf8 tools/build_android.py --edition $homm5Edition --shared --thinlto --no-pgo --jobs 4 --thinlto-jobs 2
    if ($LASTEXITCODE -ne 0) { throw "Native build failed: $homm5Edition" }
}
python -X utf8 tools/build_game_apk.py --skip-native --thinlto --no-pgo
```

`--no-pgo` makes the documented build independent of local training profiles.
Profiles stay outside Git and belong to their original engine: ToE uses
`build/pgo/homm5.profdata`, Vanilla uses `build/pgo-vanilla/homm5.profdata` and HoF
uses `build/pgo-hof/homm5.profdata`. To use available edition-specific defaults:

```powershell
python -X utf8 tools/build_game_apk.py --thinlto
```

For an individual native build, `--pgo-use PATH` selects another compatible LLVM
profile for that edition. Do not apply a ToE profile to the other engines.
Performance can differ between builds using profiles and the profile-independent
build above.

The signing key is created in `build/android/debug.keystore`. Keep your local key
if you want subsequent APKs to update the same installation. Another key requires
uninstalling the old package or signing with the original key. Keys and keystores
are excluded from Git.

## Install and provide game resources

1. Install your APK on an ARM64 Android device and open **Heroes V**.
2. Grant file access when the launcher asks: Android 11 and later need
   *All files access*; Android 8–10 ask for storage, and a permanently refused
   permission opens the app's settings.
3. Select the original game files under **Game files**. There are exactly two
   data-folder choices: **Heroes V + Hammers of Fate (GOG)**, shared by Vanilla
   and HoF, and **Tribes of the East**. Their defaults are
   `/sdcard/HeroesV/game-hof/` and `/sdcard/HeroesV/game/`. Choose an installed
   GOG folder (a folder inside or above it also works) or a ZIP of that installed
   game. The Gold folder must contain both `bin/` and `bina1/`, base `data/`,
   `DataLS/` including `p6-data.pak`, and `dataa1/` including `a1p1-data.pak`.
   ToE uses its separate `bin/` and `data/`, including `a2p1-data.pak`.
   An empty required EXE or data bank is reported as `0 B`.
4. To import an offline installer, choose **Install from GOG…** and select its
   setup EXE in device storage. Keep every matching BIN beside it; a single EXE
   URI from another app does not supply access to its sibling BIN files. This
   action uses the built-in file browser and All files access. The confirmation
   names the detected package and its destination. Use its other-folder button
   to choose an empty destination directly, or a nonempty parent in which a new
   game folder will be created. The original EXE/BIN pair is kept. GOG files are
   read as data by the bundled reader; the Windows installer is never executed.
   Gold is unpacked once and supplies both Vanilla and HoF.
5. GOG extraction checks payload checksums and the required original EXE/Granny
   sizes and SHA-256 values before replacing a destination. It uses a temporary
   full copy, so enough free space is needed while the old installation remains
   present. Cancellation or failed validation removes that temporary copy and
   keeps the previous destination. Unsupported original-image diagnostics give
   the expected edition/version, size and SHA-256 and the found size and SHA-256.
   Folder selection and game startup also verify the required original images.
6. Texture conversion is optional and can take time and additional storage space.
7. Start the game from the launcher; keep a separate copy of your original game
   files.

Folder buttons remain available when the game is **Ready to play**. Changing
the Gold folder through either legacy edition changes that one shared choice;
the ToE folder is kept. Choosing a folder does not move or delete its files,
and the choice survives restarting the app. If a device's system folder picker
is unavailable or unsuitable, enable **Always use the built-in file browser**
under **About**.

An update preserves an earlier common Vanilla/HoF location. If the two old
choices point to different locations, the launcher asks for one complete Gold
installation and displays both old paths. Choose it explicitly; the old
directories, their files and the historical choices are kept. Mixed Gold/ToE
files or overlapping Gold/ToE roots are refused.

The GOG importer and folder checks were physically exercised with
`setup_heroes_of_might_and_magic_v_2.1_v2_(russian)_(28567).exe` and its matching
`-1.bin` on the test tablet, Android 11/API 30. This imported 378 game files and checked
both Gold editions' original EXE/Granny hashes. The same-size corrupt-payload,
missing/truncated BIN, cancellation, folder migration and restart cases were
also checked. Verified installer coverage is limited to this Russian Gold pair;
Android 16, other localizations and a ToE installer import remain untested.

The launcher shows a card per edition with **Play**, or *Return to the game*
while it runs. Options: skip the opening videos (per edition, on by default),
the players for LAN over Tailscale/VPN, and New Creature Framework (ToE). On
GPUs without DXT textures it converts them to ASTC or ETC2, can undo that, or
delete the originals afterwards to save space (irreversible). Cleanup previews
and removes the map editor, installers, manuals and store files. *About* shows
the version, the GitHub page, the update check and the language (English or
Russian). Updating from 0.3.x keeps the chosen game folders, edition and
options; saves stay in `/sdcard/HeroesV/userdata*`. On Android 17 the launcher
asks for local-network access before the first start.

The main menu's **Переключить игру** opens an Android dialog with the installed
games and **Открыть лаунчер**. Switching saves the current engine's profile and
closes it before starting the selected game. The ordinary exit dialog keeps its
original confirmation buttons.

The application ID is `org.homm5.port`.

| GOG package | Default launcher data folder | Play choices |
| --- | --- | --- |
| Heroes V + Hammers of Fate (Gold) | `/sdcard/HeroesV/game-hof/` | Vanilla 1.6 and HoF 2.1 |
| Tribes of the East | `/sdcard/HeroesV/game/` | ToE 3.1 |

| Edition | Settings, profiles and saves |
| --- | --- |
| ToE | `/sdcard/HeroesV/userdata/` |
| Vanilla | `/sdcard/HeroesV/userdata-vanilla/` |
| HoF | `/sdcard/HeroesV/userdata-hof/` |

Either of the two data folders can be changed. Writable edition folders stay
under `/sdcard/HeroesV/`, as listed above. The APK keeps its prepared DLLs in
private app storage; the standalone developer tools below print their own
edition-specific data/image paths and do not set the APK launcher's choices.

Optional installation through ADB:

```powershell
python tools/build_game_apk.py --skip-native --thinlto --install
```

If several devices are connected, pass `--serial SERIAL` or set `ANDROID_SERIAL`
or `HOMM5_SERIAL` locally. No device identifier is included in the repository.

For the standalone developer executable, build and deploy the selected edition:

```powershell
python tools/build_android.py --edition vanilla --no-pgo
python tools/deploy.py --edition vanilla --data --serial SERIAL
```

`deploy.py` defaults to `toe`; `--edition hof` selects HoF. It validates the
selected executable's mandatory patch receipt before any device operation and
again before uploading native code. `--data` copies only that edition's resource
banks and shared assets, then applies private profile, intro and UI
overrides. It never modifies the installed PC game. Omitting `--data` updates
the prepared DLLs and executable only. Original EXE/Granny images are read from
the selected game's `bin` or `bina1`. The executable is uploaded through
a temporary file and renamed; no game is started automatically.

The script prints a launch command with explicit `--game`, `--data` and
`--images` arguments; use those arguments for legacy executables because the
bare executable's default paths are the historical ToE paths. Developer
executables use `/data/local/tmp/homm5[-vanilla|-hof]/homm5-arm64`; deployment
receipts are `build/deploy-receipt[-vanilla|-hof].json`.

## Touch controls

| Gesture | Action |
| --- | --- |
| Tap | Original selection or contextual action |
| Double tap your hero or town | Open its screen |
| Drag the map | Move the camera |
| Two fingers | Move, zoom and rotate the camera |
| Two nearby fingers moving vertically together | Tilt the camera, including in battle |
| Brief simultaneous tap with three fingers anywhere in the game view | Restore the original camera in adventure, battle, troop deployment and town, including over the interface |
| Hold an interface element | Show its tooltip |
| Swipe left or right on a scenario's hero, faction, bonus, team or player-state icon | Cycle through the scenario's allowed choices. The active icon stays highlighted with its name and tooltip; heroes also show their specialization description |
| While aiming in battle, rest a second finger | Show the details card of the creature under the first finger at once; lift the second finger to hide it and keep aiming. Lifting the first finger while the second rests gives no order |
| While aiming in battle, tap with a second finger | Show the details card until the first finger lifts (no order is given); each further second-finger tap switches once between the card and the creature's effects |
| Tap a portrait on the battle initiative bar, then tap it again after a pause | The first tap selects the portrait (it stays highlighted); the second shows the creature's details card, which stays open without holding; each further tap on the portrait switches between the card and the effects; a touch elsewhere closes it |
| Hold a map or town object, or the battle initiative bar | Show its tooltip and details card; each second-finger tap on a held initiative bar portrait switches its card once |
| Double tap a creature portrait on the initiative bar | Issue the original attack action through the portrait |
| Drag your active shooter onto an enemy in battle | Melee attack instead of a shot, like Ctrl+click on the PC |
| Brief simultaneous tap with two fingers anywhere in the game view | Cancel a selected spell or creature ability; on the adventure map, stop the moving hero |
| Double tap the minimap, or tap it with two fingers | Toggle the highlighting of objects, like holding Alt on the PC; the camera stays. A single tap on the minimap moves the camera after a short pause (0.4 s) |
| Swipe left or right across the spellbook | Next or previous page |
| Swipe up or down across the spellbook | Previous or next bookmark (school); the orcish book of ToE switches its page. A tap that misses a bookmark by a little takes the nearest one |
| Drag a stack during troop deployment | Move it between the field and the reserve slots; the dragged portrait stays centred under the finger |
| Hold a deployment reserve portrait and tap the reserve bar with a second finger | Split one creature into the next free reserve slot per tap. Hold the second finger on a destination slot to open the original army split dialog |
| Swipe from a dropdown, move to an item and release | Select that item; a second finger cancels |
| Swipe horizontally across a scenario hero, faction or bonus selector | Step through several choices without lifting the finger; reverse the swipe to step back |
| Tap the town render during its camera flyby | Skip the flyby without selecting a building |
| Swipe on a slider | Move its value from where it is; a tap or hold does not move it |
| Swipe a list | Scroll |
| Drag a troop stack into the visible split zones | Release over Quick split to split it in half; hold over Split one to detach the first unit after 1 second and another every 0.5 seconds, with progress shown. A free army slot is required |
| Drag troops or artifacts | Transfer between slots, empty slots included; a tap on a stack and then a tap on a slot does the same |
| Hold a stack and tap any army slot with a second finger; or drag a stack onto an army portrait | Split one creature off per tap, open the split dialog by holding the second finger, collect or distribute a creature type on its own portrait, move stacks to the other army — in towns, hero screens and the caravan, raise-the-dead, joining-creatures, garrison and creature-exchange windows |
| Aim a selected ability, then release | Confirm the target |
| Second finger while aiming | Cancel targeting (in battles: a quick two-finger touch or moving the second finger) |

While a creature card is shown, the battle camera stays still: a moving second
finger does not turn it.

The first use of targeting, hero movement, the camera or the enabled console shows a brief
touch-control tip. Each type appears once per device across all three editions. The
**Пропустить все подсказки** button in **Настройки → Дополнительные** skips them together.
These markers are shared in the app's private files and survive APK updates; clearing
application data resets them.

In all three editions, dragging a stack also shows how to open the quantity dialog: keep the
stack held and hold a free slot with another finger. **Подсказки деления отрядов**
and **Зоны деления отрядов** under **Настройки → Дополнительные** control the
instructions and the quick-split regions separately. Disabling regions also
disables their actions; splitting with a second finger remains available.
The centred instruction banner follows the text width with small side padding
and fits inside the viewport on narrow screens.

The main menu's **Управление** guide explains troop splitting, redistribution,
collection and transfers, along with touch and gamepad controls. Cursor offset
and visibility are under **Настройки → Дополнительные → Управление**. Offsets
apply to selection, holding and dragging. During a battle damage preview, the
attack or shot icon appears above the damage and retaliation text; the forecast
identifies the selected target. This icon is shown even when other touch cursors
are disabled. The offset tapers smoothly near screen edges so every point remains
reachable. Camera gestures and physical pointer input retain their own coordinates.
Field taps are dispatched immediately on release, with no multi-tap wait.
For the camera reset, place all three fingers within 120 ms and release within
300 ms, moving each finger no more than 16 dp. Three sequential taps do not reset
the camera. When **Консоль игры** is enabled, hold the in-game gear button to
toggle the console, or use the physical `~` key. A short gear tap opens the
ordinary menu. Three-finger holds have no console action. Opening the console
selects its text field and brings up the Android keyboard.

With the console switch enabled, hold the adventure screen's scenario-information
button to open the original cheats menu. It asks before enabling cheats for the
current map and retains the original turn, ownership and multiplayer restrictions.
Army choices include six factions in Vanilla, seven in HoF and eight in ToE;
alternative upgrades are offered only in ToE.

## In-game Android settings

**Настройки → Дополнительные** holds the port's options. Render and interface
scales use native sliders with fixed percentage steps. The frame rate dropdown is
built from the display's own refresh rates (30 FPS and every supported rate from
45 to 240 Hz). The touch cursor and **LAN через Tailscale/VPN** are checkboxes.
All three editions include the console switch, separate
OpenGL ES scene/UI filters and the FSR sharpness slider. Each edition keeps its
own profile settings. All three editions keep the original battle camera distance and aim,
with the vertical coverage of its 16:9 PC view on wider displays, including attack
close-ups. Above 100% UI scale, deployment keeps the entire available placement
grid above the reserve bar without zooming out; the battle overview compensates
only for the extra area occupied by the enlarged HUD. Native attack close-ups
retain their own framing.
The **Вмещать поле боя** switch is removed in all three editions; its old saved
variable remains registered for profile compatibility and no longer changes the camera.
Vanilla and HoF use one shared GOG Gold installation; ToE stays separate:
the launcher warns about conflicting paths and mixed Vanilla/ToE archives and
refuses incompatible import destinations before replacing files.

The interface scale is an upper limit: a large panel temporarily uses
the largest scale at which it fits on screen. Closing it restores the requested
scale. This also applies to adventure dialogs such as level-up; wrapped list
rows grow to keep their text from overlapping the next row.
Cutscenes, dialogue scenes, video screens and loading illustrations temporarily
use the original 100% interface scale, then restore the chosen game scale. This
keeps loading artwork from starting cropped before the screen's adaptive layout
fits it. Original illustrations keep their own proportions, including side margins
on wider screens. Vanilla and HoF dialogue
cameras also preserve the original vertical field of view on wide displays by
showing more at the sides; ToE keeps its existing wide-screen camera conversion.

## LAN over Tailscale or another VPN (experimental)

The game finds LAN games by broadcast, which a VPN such as
[Tailscale](https://tailscale.com) does not carry, and the game has no direct-IP
connection. To play across a tailnet:

1. Install Tailscale on every device and join the same tailnet.
2. In the launcher, under **LAN через Tailscale/VPN: игроки**, enter the other
   players' Tailscale addresses (100.x.y.z) or MagicDNS names, separated by spaces,
   commas or lines.
3. In the game, enable **Настройки → Дополнительные → LAN через Tailscale/VPN** on
   every device, then use **Сетевая игра → Локальная сеть** as usual.

With the option on, the LAN search also goes to the listed addresses, names are
resolved once a minute in the background, and the game advertises its Tailscale
address. Keep the option off for ordinary Wi-Fi play: a player who is not on the
tailnet cannot reach that address. This mode has not been tested with live
Tailscale devices.

## Sound

The DirectSound mixer converts FMOD's 44.1 kHz output to 48 kHz with a 32-tap
windowed-sinc filter instead of repeating samples, which removes the harsh
aliasing heard on music and effects. The Android output uses the normal
(server-mixed) path, and the mixer refills the device queue after a late wake, so
slow frames no longer cause crackling. Every edition shares these changes.

## Logs and crash reports (all editions)

Every start writes `homm5.log` in the edition's settings folder
(`/sdcard/HeroesV/userdata/`, `userdata-vanilla/` or `userdata-hof/`). The two previous
sessions stay beside it as `homm5.1.log` and `homm5.2.log`, so restarting the
game after a crash no longer overwrites the log that recorded it. The new log
begins with the device and Android version and, on Android 11 and later, with
how the previous game process ended: a native crash and its signal, a kill for
low memory, "not responding" (with the thread trace), or an engine error (exit
code 70). The previous log ends with the same line; a native crash also leaves
an Android tombstone (`adb bugreport`). A crash or engine error records the
faulting thread, the host backtrace as `libhomm5.so+offset` (resolve it with
`llvm-symbolizer` against the unstripped library whose build ID the log names)
and the guest return addresses found on the game's stack. To report a crash,
send `homm5.1.log` (the session that crashed) together with `homm5.log`.

## Versions and local release files

The current version is `0.6-dev` / code `11`. Earlier development builds used
`0.1-dev`, `0.2-dev`, `0.3-dev`, `0.3.1-dev`, `0.3.2-dev`, `0.4-dev`, `0.5-dev` and `0.5.1-dev`. The version is stored in
`android/app/AndroidManifest.xml`; increase `android:versionCode` for every
subsequent published build. Version `0.3-dev` uses code `5` (the replacement
build supersedes the earlier code `4` APK); `0.3.1-dev` uses code `6`, and
`0.3.2-dev` uses code `7`, `0.4-dev` uses code `8`, `0.5-dev` uses code `9`, and
`0.5.1-dev` uses code `10`.

Local release copies use `heroes-v-0.6-dev-<sha256-prefix>.apk`, where the suffix
is the first eight characters of the APK's SHA-256, with a companion `.sha256`
file. The `pub/` directory is ignored. Building and naming an APK does not
automatically publish it or create a Git tag.

## Changes in 0.6-dev

Changes since 0.5.1-dev, for Heroes V 1.6, Hammers of Fate 2.1 and Tribes of the East 3.1:

- Exclude live heroes sheltered in a Sanctuary from quick combat to prevent the
  reproduced stalled AI turn, preserving the player's global Quick Combat setting.
- Cancel spell or ability targeting with a two-finger tap even over the interface;
  on the adventure map, the same gesture stops the moving hero.
- Restore the original camera with a three-finger tap in adventure, battle,
  deployment and town, including over the interface. A town-render tap skips the flyby.
- Show the native attack or shot icon above the damage forecast even when other
  touch cursors are disabled.
- Refresh the font scale of new multiplayer-list rows after filter changes and
  support continuous, reversible swipes across scenario player choices.
- Add four brief first-use control tips shared across editions and a
  **Skip all tips** button in Additional settings.
- Reduce the default FMOD mixer request from 100 to 50 ms and shorten the AAudio
  output queue, retaining adaptive buffer growth when underruns occur.
- Include the shared launcher's queued early Play action and touch-safe deferred
  rebuilds. Add native, Java and UI regression coverage.
- Set Android version to `0.6-dev` / code `11`.

## Changes in 0.5.1-dev

Changes since 0.5-dev:

- Wait for actual GPU completion during graphics autodetection in all three editions,
  preventing permanent freezes when creating a profile. Preserve the original calibration.
- Keep the launcher and all three editions in one Android task. Remove stale edition
  tasks from earlier builds so Recents shows one card and resumes the latest open game.
- Set Android version to `0.5.1-dev` / code `10`.

## Changes in 0.5-dev

Changes since 0.4-dev:

- Import offline GOG EXE/BIN installers without executing Windows programs, with
  checksum verification, cancellation and preservation of the previous installation.
  Create `.nomedia` before extraction to keep game media out of Android galleries.
- Use one shared Gold data folder for Heroes V 1.6 and Hammers of Fate 2.1,
  plus a separate Tribes of the East 3.1 folder. Preserve edition saves/settings,
  migrate existing choices and expose UserMODs paths and content directories.
- Ask on each launch before using unsupported original-image sizes or hashes;
  missing, unreadable, empty or malformed inputs remain hard errors.
- Add the optional 4 GB guest address space, with a RAM-based initial default,
  and fix runtime allocation, thread/TLS, sound-interface and sampler lifetimes.
- Decode original DXT and converted CPU textures for spellbook/UI images in all
  three editions; correct legacy widescreen dialogue cameras and scaled loading,
  video and cutscene screens. Keep the deployment grid above the enlarged HUD.
- Seed the original random generator with OS entropy at initial construction,
  fixing repeated random duel heroes in all three editions while preserving
  explicit seeds and restored/network state.
- Smooth the launcher-to-game window transition and give the three Play buttons
  distinct magic, snow and ember particles with independent initial layouts.
- Keep optional native replacement groups disabled by default; no new universal
  FPS improvement or full campaign/device compatibility is claimed.
- Set Android version to `0.5-dev` / code `9`.

## Changes in 0.3.2-dev

Changes since 0.3.1-dev:

- The Additional settings include **Вмещать поле боя**, enabled by default.
  Disable it to keep the original battle camera framing.
- DXVK/Turnip render into the game's own Android window, including presents that
  name its guest window handle. PC backbuffer sizes remain available to the older
  editions; their frame boundary now applies render scale and the full display size.
- Ghost armour uses the correct cube reflection texture in OpenGL ES. Shader
  Model 1 programs follow the dimensions of their bound textures, while the
  ghost's translucent cloth keeps its original alpha blending.
- Render and interface scale use native sliders that save their actual fractional
  values. Numeric dropdowns are reserved for settings whose values are item indices.
- Optional anisotropic filtering respects the driver's extension and reported limit.
- Lifted CALL-next sequences retain the real guest return address and flags; the
  generator also preserves the correct sine/cosine order for FSINCOS.
- Fix Android 17 startup: unpacked native engines are made read-only before
  loading, including engines already cached by an earlier APK. All three editions.
- The game no longer closes on snow. The five random sounds of the snow terrain
  ambience are the only MS ADPCM files of Hammers of Fate and Tribes of the East;
  FMOD decodes them through the Windows Audio Compression Manager, which the port
  lacked, so the first of them (a few seconds after starting on snow, or in a
  battle on a snow arena) stopped the game. The port now provides those ACM calls
  with an MS ADPCM decoder that matches Windows' own codec sample for sample.
  All three editions.
- Dropping a creature onto an empty army cell works in the caravan, raise-the-dead,
  joining-creatures, garrison and creature-exchange windows (and wherever an empty
  cell hides its icon): the touch adapter looked for the target among visible
  slots only, while the game's own drop takes the hidden empty cell. Tap a stack,
  then tap an empty cell, or drag it there. All three editions.
- The quick army management of the town and the hero screen (splitting with a
  second finger, the split dialog, collecting and distributing on the army's
  portrait, moving a stack or the whole army to the other portrait) also works in
  those windows. Raising the dead uses the game's own controller with its dark
  energy cost, so a stack can be raised partly. All three editions (no caravans
  in 1.6).
- The launcher is the shared port launcher base (see "Install and provide game
  resources"); the APK targets Android SDK 37.
- Sound fixes for very short loops, several cursor laps per mixer step, invalid
  formats and silent 8-bit buffers, and the crash logs of the previous two
  sessions, now apply to Heroes V 1.6 and Hammers of Fate as well.
- Scenario options can be cycled with swipes and keep their highlight and
  tooltip, heroes show their specialization; deployment reserve stacks can be
  split with a second finger; large panels such as level-up shrink to fit at high
  interface scales; scenario list rows reflow after text wrapping and stay
  scrollable; the object highlight refreshes in small batches.
- The touch controls, settings and network options that were Tribes of the East's
  only now work in Heroes V 1.6 and Hammers of Fate too: the initiative bar
  portrait and its card, second-finger card taps, the minimap highlight
  (double tap or two fingers), stopping a hero with a quick two-finger tap,
  spellbook page and bookmark swipes, slider and dropdown swipes, the shooter's
  melee drag, the centred deployment portrait, the dropdowns and checkboxes of
  **Настройки → Дополнительные**, and LAN over Tailscale/VPN. The 1.6 and 2.1
  engine addresses were matched against their own code. Checked on a device: the
  settings page, slider and dropdown swipes, the initiative bar card, the
  two-finger tap, spellbook swipes and bookmarks, scenario swipes. Later device
  checks confirmed visible Alt object highlighting in both legacy editions too.
- The spellbook of Heroes V 1.6 and Hammers of Fate is no longer cut off at the
  top and bottom on wide screens: its camera now widens the view the way Tribes
  of the East does. Tapping a spell selects it again on wide screens; those two
  engines pick spells by fixed 4:3 screen areas, which the port now maps onto the
  widened screen (the spell tooltips follow).
- Android version is now `0.3.2-dev` / code `7`.

## Changes in 0.3.1-dev

Fixes since 0.3-dev:
- The game no longer closes when the town's creature hire window opens. The
  lifted spell-name lookup missed every spell id above 255 (Fortress runes,
  Stronghold war cries and abilities, Tribes of the East specialities), so
  Fortress and Stronghold towns crashed in single player and LAN games alike, at
  any interface scale. Fixed in Tribes of the East and Hammers of Fate (the same
  crash for the Fortress); Heroes V 1.6 has fewer spells and was not affected.
  The lifter now reads declared jump tables in full; every table longer than 256
  entries is declared for each engine, including the DirectX error-name tables
  that were cut in all three.
- Tribes of the East keeps the logs of its two previous sessions
  (`homm5.1.log`, `homm5.2.log`) and records how the previous game process ended,
  the device, the engine build ID and more crash details (see "Logs and crash
  reports"). Hammers of Fate and 1.6 keep the old single log.
- Android version is now `0.3.1-dev` / code `6`.

## Changes in 0.3-dev

Changes since 0.2-dev:

- Troop deployment supports dragging stacks from the battlefield to reserve slots
  and back in ToE 3.1, Heroes V 1.6 and Hammers of Fate 2.1.
- While aiming in battle, a resting second finger shows the creature's details
  card without losing the attack preview. Lifting the second finger closes the
  card and resumes aiming; lifting the aiming finger first issues no order and
  keeps the card until the second finger lifts. ToE keeps the camera still while
  a card is open and supports a second-finger tap to keep it until the first lifts.
- Holding a map or town object, or a combat control such as the initiative bar,
  requests its details card after its tooltip appears. The original right-click
  tooltip setting is respected. These controls work in all three editions.
- The in-game control guide and the controls table document the new gestures.
- All editions use a 32-tap windowed-sinc resampler for non-48 kHz sound buffers,
  replacing sample repetition. Normal AAudio output and queue refill after late
  mixer wakes improve audio continuity; mixer threads use the revised priorities
  and can run on all CPU cores.
- Additional settings use native sliders for render/UI scale, a dropdown for
  frame limits from the display's supported rates, and touch-cursor and VPN LAN checkboxes.
- ToE sliders move relative to their current value on a swipe; dropdowns open on
  swipe start and select on release. Deployment portraits stay under the finger.
- ToE initiative-bar portraits can be selected with one tap and opened with the
  next, without holding. Each subsequent tap switches once between the card and
  effects; tapping elsewhere closes the card without issuing a battlefield order.
  Second-finger taps over a held portrait also switch once between these views.
- ToE supports forcing an active shooter's melee attack by dragging to the enemy,
  and a two-finger map tap to stop the hero or cancel targeting.
- Double-tapping the ToE minimap, or tapping it with two fingers, toggles object
  highlighting without moving the camera. A single minimap tap waits 0.4 seconds.
  Reused highlight handles avoid rebuilding unchanged selections every frame;
  lists are rebuilt when changed and periodically refreshed every 30 frames.
- ToE spellbooks accept horizontal page swipes and vertical bookmark swipes;
  near-miss school-tab taps select the closest bookmark within the snap distance.
- Experimental ToE VPN LAN support adds launcher peer addresses and an in-game
  switch, off by default, for Tailscale-style discovery and tunnel addresses.
  Peer names resolve in a background thread. Live VPN play remains untested.
- DXVK/Turnip renderer sources, capability probes, bridge generation/build tools,
  dependency hashes and license notes are included for development. The renderer
  UI and probe service are disabled, and the default APK ships no DXVK/Turnip
  runtime libraries; the experimental GPU stall remains unresolved.
- A successful-start marker identifies the installed build and is cleared before
  each engine start. After an update or an unsuccessful start, the app icon opens
  the launcher; a successful start restores automatic game launch.
- The launcher brings back a running game only while its game activity still has
  an Android task, so a process surviving a removed task cannot hijack the launcher.
- ZIP import recognizes Cyrillic CP866 names from Windows archivers, including
  names whose bytes also form valid UTF-8. Explicit UTF-8 and valid Unicode extra
  fields retain precedence; other names use the existing decoding fallbacks.
- ZIP import restores file modification times from DOS, extended Unix or NTFS
  timestamps, including the metadata written by 7-Zip.
- Archive inspection and extraction report decoder/runtime failures and Java
  errors through the launcher instead of leaving an unfinished import. Existing
  CRC checks and extraction cleanup are retained.
- Missing or blocked system file pickers show an error. Refused foreground-service
  starts are logged and extraction continues while the launcher is on screen.
- Sparse graphics buffer remapping uses local pointers, chooses index width once,
  prefetches scattered reads and checks the gathered vertex range once per draw.
  The same implementation now serves all three engines; no FPS gain is claimed.
- Heroes V 1.6 and HoF 2.1 use widescreen anchors for new-day/week and tactics
  messages, announcement boxes, turn timers, edit dials, Fort on the Hill,
  mission objectives and the right combat hero panel.
- HoF loading screens regain the gradient background supplied by the original
  game around the resized loading artwork.
- The launcher adds an optional New Creature Framework switch for ToE 3.1,
  disabled by default. It raises the creature count from 180 to 1000 and guards
  random-map copies of missing creature map visuals. Mods must supply the creature
  records; enabling it with an unmodified game prevents startup.
- New Creature Framework uses host values in the translated code, preserving its
  control flow and compatibility with the existing ToE PGO profile.
- Native address mappings, layout patch anchors and source hashes are updated in
  all three edition contracts for the shared touch and rendering changes.
- Regression coverage is extended for two-finger contact order, creature cards,
  reserve deployment, successful-start markers, sparse buffers, CP866 ZIP names,
  archive timestamps and New Creature Framework transforms and host values.
- The release uses the retrained ToE PGO profile covering menus, adventure views,
  hero interaction and battles. Vanilla and HoF still build without PGO; the local
  profile is a build input outside Git. No measurable FPS gain was established.
- Android version is now `0.3-dev` / code `5`; local APK filenames and version
  documentation follow that version.

Outstanding player reports: the oversized spellbook on Pixel 10 and a HoF
hot-seat hero-battle crash were not reproduced. No fix is claimed for either.
As of 2026-11-07, Vanilla and HoF also have their own device-trained PGO profiles
and generated-code optimizations. Their original saves load across the update,
and representative map, army and battle flows have been exercised on an ARM64 phone.
Native crashes, Java exceptions and ANRs retain their previous session logs in both
editions. Full campaign completion and multiplayer LAN/Tailscale sessions for the
legacy editions remain outside the verified coverage.

## Checks

The packaging, toolchain resolution and resource transformation checks can run
without the original game or a device:

```powershell
python -m unittest discover -s tests -p test_android_tools.py
python -m unittest discover -s tests -p test_installed_images.py
python -m unittest discover -s tests -p test_deploy.py
python -m unittest discover -s tests -p test_apk_pgo.py
python -m unittest discover -s tests -p test_apk_thinlto.py
python -m unittest discover -s tests -p test_builder_thinlto.py
```

Additional tests use the original installation, generated C, a local Microsoft
C++ toolchain, optional ANGLE binaries or an explicitly selected Android device.
They are not all prerequisites for packaging an APK. The Windows host and tools
are retained for differential checks of the same runtime and generated code.

## License

Project-authored port code and documentation are licensed under the
**GNU General Public License, version 3 or (at your option) any later version**
(`GPL-3.0-or-later`). See [`LICENSE`](LICENSE). This is a strong copyleft license;
redistribution of covered modifications carries the corresponding source and
license obligations.

Vendored dependencies and derived upstream portions retain their licenses and
copyright notices; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
The GPL grant does not relicense Heroes V, its middleware, resources or code
translated from the original binaries. A locally built APK contains translated
game code and prepared PE images, even though the large game resource archives
are supplied separately. Rights to those components remain with their respective
holders. This is an unofficial project, unaffiliated with Ubisoft, Nival or GOG.

## GitHub description

Android ARM64 port of Heroes V: Tribes of the East via static x86 recompilation,
with touch controls. Requires original game files.
