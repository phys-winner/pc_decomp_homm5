# pc_decomp_homm5

Heroes of Might and Magic V, Hammers of Fate and Tribes of the East on Android ARM64 through static
x86 recompilation, with native touch controls and a Direct3D 9 to OpenGL ES bridge.

**Development version: 0.2-dev.** The release build uses ThinLTO and PGO.
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
- ARM64 Android 8.0 or later and OpenGL ES 3.2 are required. The manifest targets
  API 28; this development package uses legacy external storage access.
- Native libraries and APK packaging support 16 KiB alignment. This does not
  establish testing on a device with 16 KiB memory pages.
- Campaign completion, every map, every GPU and every Android version have not
  been verified. Development test results are not a complete compatibility claim.

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
| Hold a dropdown, drag to an item and release | Select that item; a second finger cancels |
| Swipe a list | Scroll |
| Drag troops or artifacts | Transfer between slots |
| Aim a selected ability, then release | Confirm the target |
| Second finger while aiming | Cancel targeting |

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

## Versions and local release files

Development versions advance as `0.1-dev`, `0.2-dev`, `0.3-dev`, and so on.
The version is stored in `android/app/AndroidManifest.xml`; increase
`android:versionCode` for every subsequent published build. Version `0.2-dev`
uses code `3`.

Local release copies use `heroes-v-0.2-dev-<sha256-prefix>.apk`, where the suffix
is the first eight characters of the APK's SHA-256, with a companion `.sha256`
file. The `pub/` directory is ignored. Building and naming an APK does not
automatically publish it or create a Git tag.

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
