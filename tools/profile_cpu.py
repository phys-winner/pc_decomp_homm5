"""Sample an existing Heroes V PID with the matching NDK Simpleperf; never restart the app."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "org.homm5.port"
SDK = Path(os.environ.get("ANDROID_SDK_ROOT", Path.home() / "AppData/Local/Android/Sdk"))
NDK = Path(os.environ.get("ANDROID_NDK_HOME", SDK / "ndk/27.2.12479018"))


def validate_target(cmdline, status, uid):
    if cmdline.split(b"\0", 1)[0] != PACKAGE.encode():
        raise ValueError("PID is not the Heroes V application process")
    ids = next((line.split()[1:] for line in status.splitlines() if line.startswith("Uid:")), [])
    if len(ids) != 4 or any(int(value) != uid for value in ids):
        raise ValueError("PID does not belong to the debuggable application's UID")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="Already running Heroes V PID supplied by the caller")
    parser.add_argument("--serial", required=True, help="Explicit ADB device serial")
    parser.add_argument("--duration", type=float, default=15)
    parser.add_argument("--event", default="cpu-cycles:u", help="Simpleperf event; cpu-cycles also samples kernel time")
    parser.add_argument("--receipt", type=Path, default=ROOT / "build/cpu-profile/receipt.json", help="Exact installed APK receipt, including archived comparison builds")
    args = parser.parse_args()
    if args.pid <= 0 or not 1 <= args.duration <= 60:
        parser.error("Use a positive existing PID and a duration between 1 and 60 seconds")
    adb_path = shutil.which("adb") or str(SDK / "platform-tools/adb.exe")
    host_perf = NDK / "simpleperf/bin/windows/x86_64/simpleperf.exe"
    device_perf = NDK / "simpleperf/bin/android/arm64/simpleperf"
    cache_builder = NDK / "simpleperf/binary_cache_builder.py"
    for path in (Path(adb_path), host_perf, device_perf, cache_builder):
        if not path.is_file():
            parser.error(f"Required profiling input is missing: {path}")
    adb = [adb_path, "-s", args.serial]

    def device(*words, binary=False):
        options = {} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}
        return subprocess.check_output(adb + ["exec-out", *words], **options)

    uid = int(device("run-as", PACKAGE, "id", "-u").strip())
    validate_target(device("run-as", PACKAGE, "cat", f"/proc/{args.pid}/cmdline", binary=True),
                    device("run-as", PACKAGE, "cat", f"/proc/{args.pid}/status"), uid)
    # Local symbol tables must belong to the APK actually installed, including builds without ELF build IDs.
    receipt = json.loads(args.receipt.read_text())
    library = Path(receipt["library"])
    if not library.is_file():
        raise RuntimeError("The exact library named by the APK receipt is unavailable")
    apk_path = device("pm", "path", PACKAGE).strip().splitlines()
    if len(apk_path) != 1 or not apk_path[0].startswith("package:"):
        raise RuntimeError("Expected one installed base APK for Heroes V")
    installed_sha = device("run-as", PACKAGE, "sha256sum", apk_path[0][8:]).split()[0]
    if installed_sha != receipt["sha256"] or digest(library) != receipt["library_sha256"]:
        raise RuntimeError("Installed APK or local libhomm5.so differs from the current receipt; refusing wrong symbols")

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "build/cpu-profile" / f"{args.pid}-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    remote = f"cache/cpu-{args.pid}-{stamp}.data"
    recorder_hash = digest(device_perf)
    recorder = "cache/simpleperf-" + recorder_hash[:16]
    staging = "/data/local/tmp/homm5-simpleperf-" + recorder_hash[:16]
    subprocess.run(adb + ["push", str(device_perf), staging], check=True, capture_output=True)
    device("run-as", PACKAGE, "cp", staging, recorder)
    device("run-as", PACKAGE, "chmod", "700", recorder)
    if device("run-as", PACKAGE, "sha256sum", recorder).split()[0] != recorder_hash:
        raise RuntimeError("Staged NDK Simpleperf differs from the local recorder")
    record = adb + ["shell", "run-as", PACKAGE, recorder, "record", "--in-app",
                    "-p", str(args.pid), "-e", args.event, "-f", "1000",
                    "--call-graph", "fp", "--duration", str(args.duration), "-o", remote]
    metadata = {"status": "RECORDING", "pid": args.pid, "uid": uid, "serial": args.serial,
                "event": args.event, "frequency": 1000, "callgraph": "fp",
                "duration_seconds": args.duration, "record_command": record,
                "installed_apk_sha256": installed_sha,
                "local_library_sha256": receipt["library_sha256"], "remote_data": remote,
                "recorder_sha256": recorder_hash, "remote_recorder": recorder, "recorder_staging": staging,
                "scope": "Existing PID only; stages verified NDK recorder in app cache. No app launch/stop, install, clear, adb root, setprop or performance policy changes."}
    meta_path = out / "profile.json"
    try:
        # Isolate installed libraries before recording: compiler temp files in live
        # build trees can be locked, and a later relink must not change symbols.
        apk = Path(receipt["apk"])
        if digest(apk) != installed_sha:
            raise RuntimeError("Local APK differs from the installed APK receipt")
        symbols = out / "local_symbols"
        symbols.mkdir()
        with zipfile.ZipFile(apk) as archive:
            for member in archive.namelist():
                if member.startswith("lib/arm64-v8a/") and member.endswith(".so"):
                    with archive.open(member) as source, (symbols / Path(member).name).open("wb") as target:
                        shutil.copyfileobj(source, target)
        shutil.copy2(library, symbols / "libhomm5.so")
        if digest(symbols / "libhomm5.so") != receipt["library_sha256"]:
            raise RuntimeError("Local libhomm5.so changed while taking the symbol snapshot")
        metadata["symbol_snapshots"] = {path.name: digest(path) for path in sorted(symbols.glob("*.so"))}
        result = subprocess.run(record, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (out / "record.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        metadata["record_returncode"] = result.returncode
        if result.returncode:
            raise RuntimeError(f"Simpleperf record failed; inspect {out / 'record.log'}")
        data = device("run-as", PACKAGE, "cat", remote, binary=True)
        if len(data) < 104 or data[:8] != b"PERFILE2":
            raise RuntimeError("Simpleperf returned an empty or invalid perf.data")
        perf_data = out / "perf.data"
        perf_data.write_bytes(data)
        metadata["perf_data_sha256"] = hashlib.sha256(data).hexdigest()
        env = os.environ.copy()
        env["ANDROID_SERIAL"] = args.serial
        cache = [sys.executable, str(cache_builder), "-i", str(perf_data), "--disable_adb_root",
                 "--ndk_path", str(NDK), "-lib", str(symbols)]
        metadata["cache_command"] = cache
        result = subprocess.run(cache, cwd=out, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (out / "binary-cache.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("NDK binary cache builder failed; perf.data was retained")
        base = [str(host_perf), "report", "-i", str(perf_data), "--symfs", str(out / "binary_cache"),
                "--sort", "tid,dso,symbol", "--percent-limit", "0.1", "-n"]
        for name, extra in [("report-self.txt", []), ("report-callgraph.txt", ["--children", "-g", "caller", "--max-stack", "24"])]:
            result = subprocess.run(base + extra, capture_output=True, text=True, encoding="utf-8", errors="replace")
            (out / name).write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode:
                raise RuntimeError(f"NDK report failed; inspect {out / name}")
        report = (out / "report-self.txt").read_text(encoding="utf-8")
        counts = re.findall(r"Samples:\s*(\d+)", report)
        if args.event.split(":")[0] not in report or not counts or sum(map(int, counts)) == 0:
            raise RuntimeError("No CPU-cycle samples were reported; raw perf.data was retained")
        metadata["samples"] = sum(map(int, counts))
        metadata["status"] = "CAPTURED_AND_REPORTED"
    except Exception as error:
        metadata.update(status="FAILED", error=str(error))
        raise
    finally:
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
