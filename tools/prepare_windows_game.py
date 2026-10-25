"""Stage writable PC bin/config copies and read-only-use game asset junctions.

Original files are only read. Existing stages are preserved rather than reset.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIRECTORIES = ('data', 'Maps', 'music', 'video', 'hwcursors', 'DuelPresets',
                     'UserCampaigns', 'UserMODs', 'CustomContentDM')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def junction(destination, source):
    # Exact, already resolved staging paths. No shell deletion or wildcards.
    quoted = [str(path).replace("'", "''") for path in (destination, source)]
    command = f"New-Item -ItemType Junction -Path '{quoted[0]}' -Target '{quoted[1]}' | Out-Null"
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                   check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)


def prepare_game(destination):
    destination = Path(destination).resolve()
    if not destination.is_relative_to((ROOT / 'build').resolve()):
        raise ValueError('Private PC game stage must remain under build/')
    receipt_path = destination / 'stage.json'
    if receipt_path.exists():
        result = json.loads(receipt_path.read_text())
        if result['destination'] != str(destination) or not (destination / 'bin/H5_Game.exe').is_file():
            raise ValueError('Existing private PC game stage is inconsistent')
        return result
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Refusing to overwrite an unrecognized PC game stage')
    source = Path(json.loads((ROOT / 'port.json').read_text())['game_directory']).resolve()
    modules = json.loads((ROOT / 'config/modules.json').read_text())
    verified = {item['source']: sha(source / item['source']) for item in modules}
    if any(verified[item['source']] != item['sha256'] for item in modules):
        raise ValueError('Original PC input does not match the module manifest')
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'bin').mkdir()
    for path in (source / 'bin').iterdir():
        if path.is_file():
            shutil.copy2(path, destination / 'bin' / path.name)
    shutil.copytree(source / 'profiles', destination / 'profiles')
    links = []
    for name in ASSET_DIRECTORIES:
        if (source / name).is_dir():
            junction(destination / name, source / name)
            links.append(dict(path=str(destination / name), source=str(source / name), usage='read-only game assets'))
    # Same private optional-tracking setting as the isolated original baseline.
    autoexec = destination / 'profiles/autoexec_a2.cfg'
    body = autoexec.read_text(encoding='utf8')
    autoexec.write_text(body.replace('setvar ubi_tracking_tool_enabled = 1',
                                    'setvar ubi_tracking_tool_enabled = 0'), encoding='utf8')
    if verified != {item['source']: sha(source / item['source']) for item in modules}:
        raise ValueError('Original input changed while staging')
    result = dict(destination=str(destination), source=str(source), original_module_hashes=verified,
                  asset_junctions=links, changed_private_setting='ubi_tracking_tool_enabled=0',
                  original_files_modified=False, game_launched=False)
    receipt_path.write_text(json.dumps(result, indent=2) + '\n')
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/windows-game')
    print(json.dumps(prepare_game(parser.parse_args().output), indent=2))
