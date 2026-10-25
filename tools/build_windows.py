"""Build all nine statically lifted modules with the native Win32 API bridge.

Separate x86 object cache; never edits Android objects, original PE files or the
vendor checkout. The default executable is build/windows-x86/homm5-static.exe.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import pefile
from prepare_windows_runtime import prepare
from prepare_windows_game import prepare_game
import build_android as source_transforms

ROOT = Path(__file__).resolve().parents[1]
HOST_BASE = 0x60000000
WINDOWS_MANIFEST_SHA256 = 'e1896f59d551bcb2d8f04b5923bedfbf5d8a16565f1f9e717447f8000080e8e6'
PROFILE_RUNTIME = 'build/pc-full/pgo/llvm18/lib/clang/18/lib/windows/clang_rt.profile-i386.lib'
# Private PC profile seed (input_a2.cfg, user_a2-max2048.cfg, Saves/save_6.sav), relative to ROOT.
PROFILE_SEED = 'tools/harness/fixtures/pc-profile'
PROFILE_RUNTIME_SHA256 = '7da3975786d61a37c6dc4715c783ec21b330866ea71a9d03f3f9928aec6ed31f'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compiler_environment():
    vswhere = Path(r'C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe')
    installation = Path(subprocess.check_output([str(vswhere), '-latest', '-products', '*', '-property', 'installationPath'], text=True).strip())
    msvc = sorted((installation / 'VC/Tools/MSVC').iterdir())[-1]
    sdk = Path(r'C:\Program Files (x86)\Windows Kits\10')
    version = sorted((sdk / 'Lib').iterdir())[-1].name
    env = os.environ.copy()
    if env.get('CL') or env.get('_CL_'):
        raise ValueError('CL/_CL_ overrides would change the pinned compiler options')
    env['PATH'] = str(msvc / 'bin/Hostx64/x86') + os.pathsep + env['PATH']
    env['INCLUDE'] = ';'.join(map(str, [msvc / 'include', sdk / f'Include/{version}/ucrt', sdk / f'Include/{version}/shared', sdk / f'Include/{version}/um']))
    env['LIB'] = ';'.join(map(str, [msvc / 'lib/x86', sdk / f'Lib/{version}/ucrt/x86', sdk / f'Lib/{version}/um/x86']))
    clang = Path(os.environ.get('LOCALAPPDATA', '')) / 'Android/Sdk/ndk/27.2.12479018/toolchains/llvm/prebuilt/windows-x86_64/bin/clang-cl.exe'
    return clang, msvc / 'bin/Hostx64/x86/link.exe', env


def collect_inputs():
    modules, sources, entries = [], [], {}
    definitions = set()
    manifest = json.loads((ROOT / 'config/modules.json').read_text())
    for module in manifest:
        folder = ROOT / f"generated/{module['name']}-x86"
        report = json.loads((folder / 'report.json').read_text())
        image = ROOT / 'generated/input' / module['file']
        expected = report['rebased_sha256']
        if report.get('status') != 'GENERATED' or sha(image) != expected:
            raise ValueError('Generated image/report mismatch: ' + module['name'])
        pe = pefile.PE(str(image), fast_load=True)
        base = int(module['base'], 16)
        if pe.OPTIONAL_HEADER.ImageBase != base or base + pe.OPTIONAL_HEADER.SizeOfImage > HOST_BASE:
            raise ValueError('Unsupported Windows guest image range: ' + module['name'])
        if pe.OPTIONAL_HEADER.DATA_DIRECTORY[13].Size:
            raise ValueError('Delay imports require a dedicated loader path')
        tls = pe.OPTIONAL_HEADER.DATA_DIRECTORY[9]
        if tls.Size and module['name'] != 'game':
            raise ValueError('Only the verified H5 EXE static TLS template is currently supported')
        modules.append(dict(name=module['file'], base=base,
                            span=pe.OPTIONAL_HEADER.SizeOfImage,
                            entry=base + pe.OPTIONAL_HEADER.AddressOfEntryPoint,
                            path=str(image.resolve()), sha256=expected, exe=module.get('exe', False)))
        chunks = sorted(folder.glob(module['name'] + '_[0-9][0-9][0-9][0-9].c'))
        if not chunks:
            raise ValueError('No generated chunks: ' + module['name'])
        sources.extend(chunks)
        for chunk in chunks:
            definitions.update(name.decode() for name in re.findall(rb'^void (sub_[0-9A-Fa-f]+)\(void\) \{', chunk.read_bytes(), re.M))
        dispatch = (folder / 'recomp_dispatch.c').read_text()
        found = re.findall(r'\{(0x[0-9A-Fa-f]+)u, (sub_[0-9A-Fa-f]+)\}', dispatch)
        if not found:
            raise ValueError('Empty static dispatch: ' + module['name'])
        for address, symbol in found:
            address = int(address, 16)
            # Later module dispatches intentionally include the preceding
            # modules too (the Android builder links only the last table).
            if address in entries and entries[address] != symbol:
                raise ValueError('Conflicting static dispatch address')
            entries[address] = symbol
    # Match Android: the last module owns the canonical cumulative table.
    # Earlier tables retain stale addresses from DLLs before rebasing.
    entries = {int(address, 16): symbol for address, symbol in found}
    if any(not any(item['base'] <= address < item['base'] + item['span'] for item in modules)
           for address in entries):
        raise ValueError('Canonical dispatch entry outside current guest images')
    if set(entries.values()) != definitions:
        raise ValueError('Canonical dispatch does not exactly match compiled function bodies')
    return modules, sources, entries


def write_generated(output, modules, entries):
    def save(name, text):
        path = output / name
        data = text.encode()
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
        return path
    dispatch = ['#include "recomp_types.h"']
    for name in sorted(set(entries.values())):
        dispatch.append(f'void {name}(void);')
    dispatch += ['const recomp_dispatch_entry_t recomp_dispatch_table[] = {']
    dispatch += [f'    {{0x{address:08X}u, {name}}},' for address, name in sorted(entries.items())]
    dispatch += ['};', f'const uint32_t recomp_dispatch_count = {len(entries)}u;']
    save('pc_dispatch.c', '\n'.join(dispatch) + '\n')
    lines = ['/* Validated current generated image metadata; all addresses remain NX. */', 'static pc_module pc_modules[] = {']
    for item in modules:
        lines.append('    {%s, %s, 0x%08Xu, 0x%Xu, 0x%08Xu, %d, 0, 0},' %
                     (json.dumps(item['name']), json.dumps(item['path']), item['base'], item['span'], item['entry'], item['exe']))
    lines += ['};', '#define PC_MODULE_COUNT (sizeof(pc_modules)/sizeof(pc_modules[0]))']
    save('pc_modules.h', '\n'.join(lines) + '\n')


def prepare_generated(source, output):
    """Reuse only the architecture-neutral Android passes, without overrides.

    Calling these pure transforms avoids changing Android OUT or its caches.
    The original source is returned when all passes leave it byte-identical.
    """
    raw = source.read_bytes()
    body = source_transforms.guard_fpu_memory(raw)
    if b'goto _ljump; }' in body:
        body = source_transforms.direct_jump_tables(body, source_transforms.module_image(source.parent.name[:-4]))
    body = source_transforms.packed_sse(body)
    body = source_transforms.fast_rep_movs(body)
    body = source_transforms.index_region(body)
    body = source_transforms.localize_sse(body)
    body = source_transforms.localize_backedges(body, source_transforms.BACKEDGE_HOT_FUNCTIONS)
    body = source_transforms.apply_protocol(body, source_transforms.call_protocol(), source.parent.name[:-4])
    body = source_transforms.apply_x87(body, source_transforms.x87_plan())
    if body == raw:
        return source
    target = output / 'patched' / source.parent.name / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_bytes() != body:
        target.write_bytes(body)
    return target


def windows_manifest_bytes():
    body = (ROOT / 'config/windows.manifest').read_bytes()
    if hashlib.sha256(body).hexdigest() != WINDOWS_MANIFEST_SHA256:
        raise ValueError('Windows UTF-8 manifest differs from the verified configuration')
    return body


def stage_manifest(target, fresh_executable=False):
    """Publish the verified UTF-8 activation context without changing PE bytes."""
    target = Path(target).resolve()
    if not target.is_relative_to((ROOT / 'build').resolve()) or not target.is_file():
        raise ValueError('Windows manifest target must be an existing private build executable')
    body = windows_manifest_bytes()
    before = sha(target)
    sidecar = target.with_suffix(target.suffix + '.manifest')
    changed = not sidecar.exists() or sidecar.read_bytes() != body
    if changed:
        sidecar.write_bytes(body)
        # Windows can cache a previous no-manifest activation context by the
        # executable timestamp. A newly linked target already has a new one.
        if not fresh_executable:
            os.utime(target, None)
    if sha(target) != before:
        raise ValueError('Staging the Windows manifest changed executable bytes')
    return dict(path=str(sidecar), sha256=WINDOWS_MANIFEST_SHA256,
                changed=changed, executable_timestamp_updated=changed and not fresh_executable,
                executable_sha256=before)


def stage_profile(destination, game=None):
    """Seed only a fresh isolated profile. Never replace files from a prior PC run."""
    # Verified in the original game's real Load UI with the UTF-8 manifest.
    # Older replacement-character product folders are deliberately preserved.
    profile = destination / 'Documents/My Games/Heroes of Might and Magic V \u2014 Tribes of the East/Profiles/hero'
    if profile.exists():
        return
    source = ROOT / PROFILE_SEED
    profile.mkdir(parents=True)
    shutil.copy2(source / 'input_a2.cfg', profile / 'input_a2.cfg')
    text = (source / 'user_a2-max2048.cfg').read_text()
    for name, value in [('gfx_fullscreen', '0'), ('gfx_resolution', '1472x920'), ('gfx_window_size', '1472x920')]:
        text, count = re.subn(r'(?m)^(setvar ' + name + r' = )[^\r\n]+', r'\g<1>' + value, text)
        if count != 1:
            raise ValueError('Expected one private profile setting: ' + name)
    (profile / 'user_a2.cfg').write_text(text, encoding='utf8')
    (profile / 'Saves').mkdir()
    shutil.copy2(source / 'Saves/save_6.sav', profile / 'Saves/save_6.sav')
    product = profile.parents[1]
    for path in (product / 'global_a2.cfg', product / 'Profiles/global_a2.cfg'):
        path.write_text('setvar profile_name = hero\n', encoding='ascii')
    (profile / 'name.txt').write_text('hero', encoding='utf16')
    (destination / 'AppData').mkdir(exist_ok=True)
    if game is not None:
        (game / 'profiles/default_profile/user_a2.cfg').write_text(text, encoding='utf8')
    (destination / 'profile-seed.json').write_text(json.dumps(dict(source=str(source), save6_sha256=sha(source / 'Saves/save_6.sav'),
            private_profile=str(profile), changed=['gfx_fullscreen=0', 'gfx_resolution=1472x920', 'gfx_window_size=1472x920']), indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--thinlto', action='store_true', help='Use a separate ThinLTO release cache and NDK COFF linker')
    pgo = parser.add_mutually_exclusive_group()
    pgo.add_argument('--pgo-generate', action='store_true', help='Instrument static guest functions; set LLVM_PROFILE_FILE for training')
    pgo.add_argument('--pgo-use', type=Path, help='Use an explicitly merged Windows training profile')
    parser.add_argument('--profile', type=Path, default=ROOT / 'build/windows-profile')
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--generated-only', action='store_true')
    parser.add_argument('--protocol-check', action='store_true',
                        help='Validation build: full state at every transfer plus callee-saved checks')
    args = parser.parse_args()
    if not 1 <= args.jobs <= 32:
        parser.error('--jobs must be between 1 and 32')
    profile_flags, profile_info = [], None
    if args.pgo_generate:
        profile_runtime = ROOT / PROFILE_RUNTIME
        if not profile_runtime.is_file() or sha(profile_runtime) != PROFILE_RUNTIME_SHA256:
            raise ValueError('Verified LLVM18 i386 profile runtime required: ' + str(profile_runtime))
        profile_flags = ['/clang:-fprofile-generate']
        profile_info = dict(mode='generate', runtime_sha256=PROFILE_RUNTIME_SHA256, clean_fps_eligible=False)
    elif args.pgo_use:
        profile_data = args.pgo_use.resolve()
        if not profile_data.is_file():
            raise ValueError('Windows PGO profile not found: ' + str(profile_data))
        profile_flags = ['/clang:-fprofile-use=' + str(profile_data),
                         '/clang:-Wno-everything', '/clang:-Werror=backend-plugin']
        profile_info = dict(mode='use', path=str(profile_data), sha256=sha(profile_data), clean_fps_eligible=True)
    output = (args.output or ROOT / ('build/windows-x86-thinlto' if args.thinlto else 'build/windows-x86')).resolve()
    if not output.is_relative_to((ROOT / 'build').resolve()) or not args.profile.resolve().is_relative_to((ROOT / 'build').resolve()):
        parser.error('Windows output and profile must be isolated under build/')
    if not args.generated_only:
        windows_manifest_bytes()
    output.mkdir(parents=True, exist_ok=True)
    previous_runtime_path = output / 'runtime/receipt.json'
    previous_runtime = json.loads(previous_runtime_path.read_text()) if previous_runtime_path.exists() else None
    runtime = prepare(output / 'runtime')
    modules, sources, entries = collect_inputs()
    write_generated(output, modules, entries)
    compiler, linker, env = compiler_environment()
    link_program = [str(linker)]
    if args.thinlto:
        linker = compiler.with_name('ld.lld.exe')
        if not linker.is_file():
            raise ValueError('ThinLTO requires the NDK ld.lld.exe beside clang-cl.exe')
        link_program = [str(linker), '-flavor', 'link']
    common = ['/nologo', '/O2', '/W0', '/std:c11', '/D_CRT_SECURE_NO_WARNINGS', '/DVOID_GUEST_BASE=0',
              '/DRECOMP_TRACE', '/DRECOMP_X87_WINDOW', '/clang:--target=i686-pc-windows-msvc', '/clang:-fno-strict-aliasing',
              '/clang:-fwrapv', '/clang:-ffp-contract=off', '/clang:-fno-math-errno', '/clang:-msse4.1',
              '/I' + str(output / 'runtime'), '/FI' + str(output / 'runtime/recomp_types.h'),
              '/I' + str(ROOT / 'reference/pcrecomp/runtime/recomp32'), '/I' + str(output)]
    if args.thinlto:
        common.append('/clang:-flto=thin')
    generated = set(sources)
    sources.append(output / 'pc_dispatch.c')
    if not args.generated_only:
        sources += [output / 'runtime/native32.c', ROOT / 'reference/pcrecomp/runtime/recomp32/image_loader.c',
                    ROOT / 'reference/pcrecomp/runtime/recomp32/recomp_trace.c', ROOT / 'native/windows_host.c']
    headers = {str(path): sha(path) for path in [*sorted((output / 'runtime').glob('*.h')), output / 'pc_modules.h',
               *sorted((ROOT / 'generated').glob('*-x86/*_funcs.h'))]}
    identity = dict(compiler=str(compiler), compiler_sha256=sha(compiler), common=common, headers=headers)
    if profile_info:
        identity['pgo'] = profile_info
    base_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    # Migrate the initial cache's overbroad runtime-source dependency when all
    # included headers match. Each C source still has its own exact byte hash.
    legacy_base = None
    if previous_runtime and all(previous_runtime.get('outputs', {}).get(name) == digest
            for name, digest in runtime['outputs'].items() if name.endswith('.h')):
        legacy_identity = dict(identity, runtime=previous_runtime)
        legacy_base = hashlib.sha256(json.dumps(legacy_identity, sort_keys=True).encode()).hexdigest()
    cache_path = output / 'objects.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    jobs, reused, objects = [], [], []
    source_hashes = {str(path): sha(path) for path in sources}
    compiled_sources = {str(path): prepare_generated(path, output) if path in generated else path for path in sources}
    compiled_hashes = {name: sha(path) for name, path in compiled_sources.items()}
    for path in sources:
        key = str(path)
        flags = list(common)
        if path in generated:
            flags += ['/I' + str(path.parent), '/DRECOMP_GENERATED_CODE', '/DRECOMP_LOCAL_REGS', '/DRECOMP_PLAIN_MEMORY', '/URECOMP_TRACE',
                      '/DRECOMP_GUEST_PROVENANCE']
            if args.protocol_check:
                flags.append('/DRECOMP_PROTOCOL_CHECK')
            if args.pgo_use:
                # /W0 hides LLVM's stale-profile diagnostic even with -Werror.
                flags.remove('/W0')
            flags += profile_flags
            if path.parent.name == 'fmod-x86':
                flags.append('/DRECOMP_YIELD_EVERY=2048u')
        if path == ROOT / 'native/windows_host.c':
            if args.pgo_generate:
                flags.append('/DPC_PGO_GENERATE')
            flags += ['/DPC_DEFAULT_GAME_BIN=' + json.dumps((ROOT / 'build/windows-game/bin').as_posix()),
                      '/DPC_DEFAULT_PROFILE=' + json.dumps(args.profile.resolve().as_posix())]
        fingerprint = hashlib.sha256(json.dumps([base_key, compiled_hashes[key], flags]).encode()).hexdigest()
        legacy_fingerprint = hashlib.sha256(json.dumps([legacy_base, compiled_hashes[key], flags]).encode()).hexdigest() if legacy_base else None
        obj = output / 'objects' / (path.stem + '.obj')
        objects.append(obj)
        old = cache.get(key, {})
        if old.get('fingerprint') in (fingerprint, legacy_fingerprint) and obj.is_file() and old.get('sha256') == sha(obj):
            reused.append(key)
            cache[key] = dict(old, fingerprint=fingerprint)
        else:
            jobs.append((path, compiled_sources[key], obj, fingerprint, flags))
    plan = dict(sources=len(sources), static_functions=len(entries), compile=len(jobs), reused=len(reused),
                output=str(output), generated_only=args.generated_only, thinlto=args.thinlto, modules=modules)
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    print(json.dumps({key: plan[key] for key in ('sources', 'static_functions', 'compile', 'reused', 'generated_only')}), flush=True)
    if args.plan:
        if cache_path.exists():
            cache_path.write_text(json.dumps(cache, indent=2) + '\n')
        return
    (output / 'objects').mkdir(exist_ok=True)
    logs = output / 'logs'
    logs.mkdir(exist_ok=True)
    start = time.monotonic()

    def compile_one(job):
        path, compiled, obj, fingerprint, flags = job
        proc = subprocess.run([str(compiler), *flags, '/c', str(compiled), '/Fo' + str(obj)],
                              cwd=ROOT, env=env, capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        (logs / (path.stem + '.log')).write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError('Compile failed: ' + str(path) + '; ' + str(logs / (path.stem + '.log')))
        return str(path), dict(fingerprint=fingerprint, sha256=sha(obj))

    try:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for index, future in enumerate(as_completed([pool.submit(compile_one, job) for job in jobs]), 1):
                name, item = future.result()
                cache[name] = item
                if index % 20 == 0 or index == len(jobs):
                    cache_path.write_text(json.dumps(cache, indent=2) + '\n')
                    print(f'Compiled {index}/{len(jobs)}', flush=True)
    finally:
        cache_path.write_text(json.dumps(cache, indent=2) + '\n')
    if source_hashes != {str(path): sha(path) for path in sources}:
        raise ValueError('Source changed during Windows build')
    if compiled_hashes != {name: sha(path) for name, path in compiled_sources.items()}:
        raise ValueError('Prepared source changed during Windows build')
    if args.pgo_use and sha(profile_data) != profile_info['sha256']:
        raise ValueError('PGO training profile changed during Windows build')
    if args.pgo_generate and sha(profile_runtime) != PROFILE_RUNTIME_SHA256:
        raise ValueError('PGO runtime changed during Windows build')
    receipt = dict(status='COMPILED', plan=plan, seconds=time.monotonic() - start, identity=identity, runtime=runtime,
                   source_hashes=source_hashes, compiled_hashes=compiled_hashes,
                   source_preparation='guard_fpu_memory + direct_jump_tables + packed_sse + index_region + localize_sse + localize_backedges(008800B0,00C362E0) + call protocol + x87 locals; no native overrides',
                   execution='UNVERIFIED')
    if not args.generated_only:
        pending = output / 'homm5-static.pending.exe'
        command = ['/nologo', *map(str, objects), '/OUT:' + str(pending), '/BASE:0x60000000', '/DYNAMICBASE:NO', '/FIXED',
                   '/MACHINE:X86', '/STACK:262144', '/NXCOMPAT', '/MAP:' + str(output / 'homm5-static.map'),
                   'user32.lib', 'shell32.lib', 'advapi32.lib', 'ole32.lib']
        if args.pgo_generate:
            command += [str(profile_runtime), '/LIBPATH:' + str(profile_runtime.parent)]
        if args.thinlto:
            command += ['/OPT:REF', '/OPT:ICF', '/OPT:lldlto=2', '/threads:' + str(args.jobs),
                        '/OPT:lldltojobs=' + str(args.jobs), '/lldltocache:' + str(output / 'thinlto-cache'),
                        '/lldltocachepolicy:cache_size=0%:cache_size_bytes=4g:prune_interval=0s']
        response = output / 'link.rsp'
        response.write_text('\n'.join(subprocess.list2cmdline([argument]) for argument in command))
        proc = subprocess.run([*link_program, '@' + str(response)], cwd=ROOT, env=env, capture_output=True, text=True,
                              creationflags=subprocess.CREATE_NO_WINDOW)
        (output / 'link.log').write_text(proc.stdout + proc.stderr)
        if proc.returncode:
            raise RuntimeError('Link failed: ' + str(output / 'link.log'))
        pe = pefile.PE(str(pending), fast_load=True)
        valid_image = pe.FILE_HEADER.Machine == 0x14C and pe.OPTIONAL_HEADER.ImageBase == HOST_BASE and HOST_BASE + pe.OPTIONAL_HEADER.SizeOfImage <= 0x80000000
        pe.close()
        if not valid_image:
            raise ValueError('Linked x86 host image range invalid')
        target = output / 'homm5-static.exe'
        os.replace(pending, target)
        manifest = stage_manifest(target, fresh_executable=True)
        prepare_game(ROOT / 'build/windows-game')
        stage_profile(args.profile.resolve(), ROOT / 'build/windows-game')
        receipt.update(status='LINKED', executable_sha256=sha(target), executable_bytes=target.stat().st_size,
                       linker=dict(command=link_program, sha256=sha(linker)),
                       manifest=manifest,
                       profile=str(args.profile.resolve()))
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(receipt['status'], f"{time.monotonic() - start:.1f}s", flush=True)


if __name__ == '__main__':
    main()
