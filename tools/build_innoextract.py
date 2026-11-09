"""Build the pinned ARM64 GOG installer reader, packaged as a native executable in the APK."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = json.loads((ROOT / 'dependencies.json').read_text())
SDK = Path(os.environ.get('ANDROID_SDK') or os.environ.get('ANDROID_HOME') or
           os.environ.get('ANDROID_SDK_ROOT') or Path.home() / 'AppData/Local/Android/Sdk')


def prepare(fetch):
    for name in ('innoextract', 'xz', 'bzip2'):
        dependency = DEPENDENCIES[name]
        directory = ROOT / dependency['directory']
        if fetch and not directory.exists():
            subprocess.run(['git', 'clone', '--no-checkout', dependency['url'], str(directory)], check=True)
            subprocess.run(['git', '-C', str(directory), 'checkout', '--detach', dependency['revision']], check=True)
        revision = subprocess.run(['git', '-C', str(directory), 'rev-parse', 'HEAD'],
                                  capture_output=True, text=True, check=True).stdout.strip()
        if revision != dependency['revision']:
            raise ValueError(f'{name}: revision mismatch')
        dirty = subprocess.run(['git', '-C', str(directory), 'status', '--porcelain', '--untracked-files=no'],
                               capture_output=True, text=True, check=True).stdout.strip()
        if dirty:
            raise ValueError(f'{name}: tracked upstream files were modified; keep Android adaptations in android/gog')
    dependency = DEPENDENCIES['boost']
    directory = ROOT / dependency['directory']
    if fetch and not directory.exists():
        archive = ROOT / 'build/boost_1_84_0.tar.gz'
        archive.parent.mkdir(parents=True, exist_ok=True)
        if not archive.exists():
            urllib.request.urlretrieve(dependency['url'], archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != dependency['sha256']:
            raise ValueError('Boost archive SHA256 mismatch')
        with tarfile.open(archive) as source:
            source.extractall(ROOT / 'reference', filter='data')
    if not (directory / 'boost/version.hpp').is_file():
        raise ValueError('Missing Boost sources; run tools/build_innoextract.py --fetch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    prepare(args.fetch)
    ndk = Path(os.environ.get('ANDROID_NDK') or SDK / 'ndk/27.2.12479018')
    cmake = SDK / 'cmake/3.22.1/bin/cmake.exe'
    ninja = cmake.with_name('ninja.exe')
    output = ROOT / 'build/gog-android'
    subprocess.run([str(cmake), '-S', str(ROOT / 'android/gog'), '-B', str(output), '-G', 'Ninja',
                    f'-DCMAKE_MAKE_PROGRAM={ninja}', f'-DCMAKE_TOOLCHAIN_FILE={ndk}/build/cmake/android.toolchain.cmake',
                    '-DANDROID_ABI=arm64-v8a', '-DANDROID_PLATFORM=android-26', '-DANDROID_STL=c++_static',
                    '-DCMAKE_BUILD_TYPE=Release'], check=True)
    subprocess.run([str(cmake), '--build', str(output), '--target', 'innoextract', '-j', str(args.jobs)], check=True)
    strip = ndk / 'toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe'
    subprocess.run([str(strip), '--strip-debug', str(output / 'libinnoextract.so')], check=True)
    sha = lambda path: hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
    sources = ['android/gog/CMakeLists.txt', 'android/gog/inspect.cpp', 'tools/build_innoextract.py', 'dependencies.json']
    receipt = dict(schema=1, sources={name: sha(ROOT / name) for name in sources},
                   dependencies={name: DEPENDENCIES[name] for name in ('innoextract', 'xz', 'bzip2', 'boost')},
                   binary=dict(file='libinnoextract.so', sha256=sha(output / 'libinnoextract.so'), bytes=(output / 'libinnoextract.so').stat().st_size),
                   abi='arm64-v8a', min_sdk=26, max_page_size=16384)
    (output / 'build-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(output / 'libinnoextract.so')


if __name__ == '__main__':
    main()
