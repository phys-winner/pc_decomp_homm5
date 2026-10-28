# pc_decomp_homm5

Heroes of Might and Magic V, Hammers of Fate and Tribes of the East on Android ARM64 through static
x86 recompilation, with native touch controls and a Direct3D 9 to OpenGL ES bridge.

**Development version: 0.3-dev.** The release build uses ThinLTO and PGO.
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

Vanilla 1.6 and HoF 2.1 have device smoke coverage for profile creation, scenario
loading, adventure maps and troop splitting. Original-binary ABI checks and host
regression tests cover their adapted native entry points. Device gameplay coverage
is recorded separately from successful generation and compilation.

The older games use ToE's widescreen anchor policy with their own window geometry.
Their font scaling follows ToE's equal horizontal and vertical glyph scale.
Legacy UI and town-music overrides are also installed as loose resources: expansion
archives take precedence over a new base PAK. Packaging and CLI deployment verify
that every loose resource exactly matches its reviewed override archive.
Ubisoft tracking is disabled before the startup commands in all three editions.

Original EXE/DLL files, resource archives, music, videos, maps and saves are not
distributed in this repository. The town music XML resources are read
from the selected edition's original resource banks during packaging, checked
against its manifest in `config/music/`, and patched in a separate Android overlay.

## Current capabilities and limits

- Original menus, profile creation, scenario loading, adventure maps, towns,
  battles, saving and loading have been exercised during development.
- Touch input supports selection, movement, camera gestures, tooltips,
  spell targeting, troop and artifact transfers, and the Android keyboard.
- Additional game settings control render scale, interface scale, frame limit,
  camera sensitivity, touch cursor offset and optional touch cursor display.
  The default frame limit is 60 FPS.
- LAN play has been tested between Android devices and between Android and the
  original PC game with ToE 3.1. Peers use the same original game version and data;
  those checks do not establish LAN coverage for the other editions. Network
  discovery depends on the local Wi-Fi network.
- The launcher accepts an installed game folder or a ZIP containing its files.
  It can convert DXT textures to ASTC/ETC2 and skip the intro videos.
- An optional launcher switch, off by default, applies the MMH5.5 New Creature
  Framework patches to ToE 3.1 (1000 creature records, IDs up to 999; random maps skip creatures
  without map objects): the `Original` group of
  [NewCreatureFramework.yml](https://github.com/Might-Magic-Heroes-5-5/MMH55/blob/master/Frameworks/NewCreatureFramework/NewCreatureFramework.yml).
  Enable it only for a mod that provides those creatures: without their files the
  game does not start. Vanilla and HoF are unaffected.
- Every edition renders with OpenGL ES. The experimental DXVK (Vulkan/Turnip)
  renderer for ToE 3.1 is disabled in this build; see [Renderers](#renderers-tribes-of-the-east).
- ARM64 Android 8.0 or later and OpenGL ES 3.2 are required. The manifest targets
  API 28; this development package uses legacy external storage access.
- Native libraries and APK packaging support 16 KiB alignment. This does not
  establish testing on a device with 16 KiB memory pages.
- Campaign completion, every map, every GPU and every Android version have not
  been verified. Development test results are not a complete compatibility claim.

## Renderers (Tribes of the East)

Every edition, ToE 3.1 included, renders with the port's own Direct3D 9 to
OpenGL ES 3.2 renderer.

An experimental DXVK renderer for ToE (DXVK 2.4.1 on the system Vulkan driver, or
on a bundled Mesa Turnip driver on Adreno 6xx/7xx GPUs) is disabled for now: on
the tested Adreno 650 with Turnip the game started, but the screen stayed black
after the startup device reset. Its sources remain in the repository
(`android/dxvk`, `android/host/d3d9_dxvk.c`, `RendererPolicy`/`Renderers` in the
app), but the launcher shows no renderer choice, runs no graphics driver check
and the APK carries no DXVK libraries. Re-enabling it for development takes
`RendererPolicy.ENABLED = true`, `HOMM5_DXVK` in `android/host/d3d9_dxvk.c` and
`tools/build_game_apk.py --dxvk`.

## Build requirements

The current scripts build on **Windows x64**, without Gradle. Install:

| Tool | Version |
| --- | --- |
| Python | 3.13 used during development |
| Android SDK platform | `platforms;android-36` |
| Android SDK Build Tools | `build-tools;36.1.0` |
| Android NDK | `27.2.12479018` |
| JDK | 17 or later; 24.0.1 used during development |
| UPX | 5.2.1, for unpacking the private copy of `fmod.dll` |

Python requirements are pinned in [`requirements.txt`](requirements.txt).
The needed source snapshots of pcrecomp, MojoShader, dlmalloc, astcenc and etcpak
are vendored in `reference/`; zlib sources support desktop regression tests.
Versions, origins and local adaptations are recorded in
[`dependencies.json`](dependencies.json) and
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
Keep the supplied MojoShader snapshot: a plain upstream checkout omits the
legacy shader fixes used by this port.

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
`editions.vanilla.game_directory` and `editions.hof.game_directory` to the base
game and Hammers of Fate installations. A combined base-game/HoF installation
can supply both paths, for example `C:/Games/Heroes of Might and Magic V`.
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
foreach ($homm5Edition in @("toe", "vanilla", "hof")) {
    python -X utf8 tools/lift_homm5.py --edition $homm5Edition --upx $homm5Upx
    if ($LASTEXITCODE -ne 0) { throw "Generation failed: $homm5Edition" }
}
python -X utf8 tools/call_protocol.py
python -X utf8 tools/x87_locals.py
python -X utf8 tools/build_game_apk.py --thinlto --no-pgo
```

Output: **`build/android-game/heroes-v.apk`**.

`tools/build_dxvk.py` stages the ToE DXVK renderer in `build/dxvk`. It downloads
nothing and rebuilds no DXVK source. It reuses the DXVK, adrenotools and Turnip
binaries built by the sibling `ut3` port, checks each one against its hash in
[`dependencies.json`](dependencies.json), imports the needed DXVK Native headers
into `reference/dxvk`, and compiles `android/dxvk` into `libh5dxvk.so`. `--ut3`,
`--dxvk-library`, `--turnip-runtime` and `--dxvk-headers` select other locations.
Run it again after changing `android/dxvk` or `android/host/dxvk_methods.h`;
`tools/generate_dxvk_bridge.py` regenerates those tables from the pinned header.
The APK builder packages the stage only with `--dxvk` (the renderer is disabled
by default, see [Renderers](#renderers-tribes-of-the-east)) and then refuses a
stale stage. The DXVK libraries add about 6 MB to the APK and 24 MB when installed.

Packaging requires XZ Utils 5.4+ for its ARM64 branch filter (`XZ`, `PATH`, or
Git for Windows' `mingw64/bin/xz.exe`). All three engines are stored as XZ
assets with 128 MiB independent chunks. The small bundled XZ Embedded decoder
unpacks only the selected engine in the background on its first start after
an update. Its size and SHA-256 are checked before an atomic rename from
`.part`; later starts reuse the completed copy in private app storage.
Allow about 131 MB for ToE or 220 MB for each legacy engine, plus the previous
copy while replacing it after an update. Compression changes APK size, not
the game engines, resources or their installed sizes.

Generation creates checked PE images and C sources under `generated/` for ToE,
`generated/vanilla/` for the base game and `generated/hof/` for HoF. Function
catalogs use the matching edition directory, while the original ToE catalog
paths remain under `config/`. These are all local
build outputs. Compilation fingerprints sources, headers, compiler and flags
before reusing objects. The APK builder compiles the texture converter and Java
launcher, includes the prepared PE images and port overlays, aligns the APK and
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
2. Grant the requested file access. Choose the original game folder or a ZIP
   above the game cards. The launcher detects the editions from their files;
   a combined Vanilla + HoF installation registers both games automatically.
   An offline GOG installer EXE is not a game ZIP.
3. Vanilla 1.6 requires `bin/`, `data/` and `DataLS/`, including
   `DataLS/p6-data.pak`. HoF 2.1 requires `bina1/`, base `data/` and `dataa1/`;
   it does not use the Vanilla `DataLS/` bank. ToE requires `bin/` and `data/`.
4. Let the launcher copy or unpack the resources. Texture conversion is optional
   and can take time and additional storage space.
5. Start the game from the launcher. Intro skipping and cleanup are available
   there; keep a separate copy of your original game files.

The main menu's **Переключить игру** opens an Android dialog with the installed
games and **Открыть лаунчер**. Switching saves the current engine's profile and
closes it before starting the selected game. The ordinary exit dialog keeps its
original confirmation buttons.

The application ID is `org.homm5.port`.

| Edition | Developer resource copy | Prepared PE images | Settings, profiles and saves |
| --- | --- | --- | --- |
| ToE | `/sdcard/HeroesV/game/` | `/sdcard/HeroesV/lifted/` | `/sdcard/HeroesV/userdata/` |
| Vanilla | `/sdcard/HeroesV/game-vanilla/` | `/sdcard/HeroesV/lifted-vanilla/` | `/sdcard/HeroesV/userdata-vanilla/` |
| HoF | `/sdcard/HeroesV/game-hof/` | `/sdcard/HeroesV/lifted-hof/` | `/sdcard/HeroesV/userdata-hof/` |

The launcher can also use another selected resource directory. Its writable
folders remain under `/sdcard/HeroesV/`, as listed above.

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
banks and shared assets, then applies private profile, intro, music and UI
overrides. It never modifies the installed PC game. Omitting `--data` updates
the prepared PE images and executable only. The executable is uploaded through
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
| Brief simultaneous tap with three fingers on the field | Restore camera tilt and rotation; in battle, also restore its position |
| Hold an interface element | Show its tooltip |
| While aiming in battle, rest a second finger | Show the details card of the creature under the first finger at once; lift the second finger to hide it and keep aiming. Lifting the first finger while the second rests gives no order |
| While aiming in battle, tap with a second finger | Show the details card until the first finger lifts (no order is given); each further second-finger tap switches once between the card and the creature's effects (ToE) |
| Tap a portrait on the battle initiative bar, then tap it again | The first tap selects the portrait (it stays highlighted); the second shows the creature's details card, which stays open without holding; each further tap on the portrait switches between the card and the effects; a touch elsewhere closes it (ToE) |
| Hold a map or town object, or the battle initiative bar | Show its tooltip and details card; in ToE each second-finger tap on a held initiative bar portrait switches its card once |
| Drag your active shooter onto an enemy in battle | Melee attack instead of a shot, like Ctrl+click on the PC (ToE) |
| Brief simultaneous tap with two fingers on the adventure map | Stop the moving hero or cancel an aim (ToE) |
| Double tap the minimap, or tap it with two fingers | Toggle the highlighting of objects, like holding Alt on the PC; the camera stays. A single tap on the minimap moves the camera after a short pause (0.4 s) (ToE) |
| Swipe left or right across the spellbook | Next or previous page (ToE) |
| Swipe up or down across the spellbook | Previous or next bookmark (school); the orcish book switches its page. A tap that misses a bookmark by a little takes the nearest one (ToE) |
| Drag a stack during troop deployment | Move it between the field and the reserve slots; the dragged portrait stays centred under the finger (ToE) |
| Swipe from a dropdown, move to an item and release | Select that item; a second finger cancels (Vanilla/HoF: hold the dropdown first) |
| Swipe on a slider | Move its value from where it is; a tap or hold does not move it (ToE) |
| Swipe a list | Scroll |
| Drag troops or artifacts | Transfer between slots |
| Aim a selected ability, then release | Confirm the target |
| Second finger while aiming | Cancel targeting (in battles: a quick two-finger touch or moving the second finger) |

While a creature card is shown, the battle camera stays still: a moving second
finger does not turn it.

The main menu's **Управление** guide explains troop splitting, redistribution,
collection and transfers, along with touch and gamepad controls. Cursor offset
and visibility are under **Настройки → Дополнительные → Управление**. Offsets
apply to selection, holding and dragging; actions use the visible cursor's
position. The offset tapers smoothly near screen edges so every point remains
reachable. Camera gestures and physical pointer input retain their own coordinates.
Field taps are dispatched immediately on release, with no multi-tap wait.
For the camera reset, place all three fingers within 120 ms and release within
300 ms, moving each finger no more than 16 dp. Three sequential taps do not reset
the camera.

## In-game Android settings

**Настройки → Дополнительные** holds the port's options. In ToE, render scale,
interface scale and the frame rate limit are dropdowns; the frame rate list is
built from the display's own refresh rates (30 FPS and every supported rate from
45 to 240 Hz). The touch cursor and **LAN через Tailscale/VPN** are checkboxes.
Vanilla and HoF keep sliders for these options.

## LAN over Tailscale or another VPN (ToE, experimental)

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

## Versions and local release files

Development versions advance as `0.1-dev`, `0.2-dev`, `0.3-dev`, and so on.
The version is stored in `android/app/AndroidManifest.xml`; increase
`android:versionCode` for every subsequent published build. Version `0.3-dev`
uses code `5` (the replacement build supersedes the earlier code `4` APK).

Local release copies use `heroes-v-0.3-dev-<sha256-prefix>.apk`, where the suffix
is the first eight characters of the APK's SHA-256, with a companion `.sha256`
file. The `pub/` directory is ignored. Building and naming an APK does not
automatically publish it or create a Git tag.

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
- ToE's additional settings use dropdowns for render/UI scale and refresh-rate
  limits from the display's supported rates, plus touch-cursor and VPN LAN checkboxes.
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
Broader campaign, save/load and legacy LAN checks remain outstanding, as do legacy
PGO profiles and the ToE-only generated-code optimizations.

## Checks

The packaging, toolchain resolution and resource transformation checks can run
without the original game or a device:

```powershell
python -m unittest discover -s tests -p test_android_tools.py
python -m unittest discover -s tests -p test_town_music.py
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
