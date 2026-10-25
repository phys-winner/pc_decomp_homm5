"""Measure the focused Heroes V SurfaceView from overlapping presentation history."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "org.homm5.port"
POLL_SECONDS = 0.25
LIBRARY = ROOT / "build/arm64/libhomm5.so"


def parse_latency(raw):
    lines = raw.rstrip().splitlines()
    # OPlus SurfaceFlinger appends this exact terminal marker after frame rows.
    if lines and lines[-1] == "OPlusFrameTracker":
        lines.pop()
    try:
        period = int(lines[0])
        if period <= 0:
            raise ValueError("nonpositive display period")
        times = set()
        for line in lines[1:]:
            if not line.strip():
                continue
            row = [int(value) for value in line.split()]
            if len(row) != 3 or min(row) < 0:
                raise ValueError("invalid presentation row")
            if 0 < row[1] < (1 << 63) - 1:
                times.add(row[1])
        if not times:
            raise ValueError("no completed presentations")
    except (IndexError, ValueError) as error:
        raise ValueError("invalid SurfaceFlinger latency history: " + str(error)) from error
    return period, sorted(times)


def merge_history(history, sample):
    if not sample:
        raise ValueError("empty presentation history")
    if not history:
        return [sample[-1]]  # Start at the latest frame, excluding history before this measurement.
    last = history[-1]
    if sample[-1] < last:
        raise ValueError("presentation history moved backwards")
    if last not in sample:
        raise ValueError("presentation history overlap lost; polling missed frames")
    return history + [stamp for stamp in sample if stamp > last]


def parse_display(raw):
    candidates = [line for line in raw.splitlines()
                  if "DisplayInfo{" in line and re.search(r"\bdisplayId\s*[=:]?\s*0\b", line)]
    candidates.sort(key=lambda line: ("mDisplayInfo=" not in line, "mBaseDisplayInfo=" not in line))
    current = [line for line in candidates if "mDisplayInfo=" in line]
    if current:
        candidates = current
    for line in candidates:
        mode = re.search(r"\bmode(?:Id)?\s*[=:]?\s*(\d+)\b", line)
        size = re.search(r"\breal\s+(\d+)\s*x\s*(\d+)", line)
        render = re.search(r"\brenderFrameRate\s*[=:]?\s*([\d.]+)", line)
        if not mode or not size or not render:
            continue
        mode_id = int(mode[1])
        entry = re.search(r"\{id\s*[=:]?\s*" + str(mode_id) + r"\b[^{}]*\}", line)
        refresh = re.search(r"\b(?:fps|refreshRate)\s*[=:]?\s*([^,}\s]+)", entry[0]) if entry else None
        if not refresh:
            continue
        try:
            rate, render_rate = float(refresh[1]), float(render[1])
            width, height = int(size[1]), int(size[2])
            if mode_id <= 0 or width <= 0 or height <= 0 or not all(math.isfinite(n) and n > 0 for n in (rate, render_rate)):
                raise ValueError("invalid display values")
        except ValueError:
            continue
        return dict(mode_id=mode_id, width=width, height=height, refresh_rate=rate, render_frame_rate=render_rate)
    raise ValueError("current display-0 mode missing or invalid in dumpsys display")


def require_visible(raw):
    focus = re.search(r"^\s*mCurrentFocus\s*=\s*(.*)$", raw, re.MULTILINE)
    activity = re.search(r"\b" + re.escape(PACKAGE) + r"/[^\s}]+", focus[1]) if focus else None
    if not activity:
        raise ValueError("Heroes V is not the focused window")
    return activity[0]


def validate_identity(before, after):
    for key in ("pid", "starttime", "library_sha256", "layer", "display"):
        if before[key] != after[key]:
            raise ValueError("measurement identity changed: " + key)


def summarize(timestamps, period):
    if len(timestamps) < 2 or period <= 0 or any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise ValueError("insufficient or stale presentation timestamps")
    intervals = sorted((b - a) / 1e6 for a, b in zip(timestamps, timestamps[1:]))
    duration = (timestamps[-1] - timestamps[0]) / 1e9
    return dict(frames=len(timestamps), duration_s=duration, fps=len(intervals) / duration,
                refresh_period_ns=period,
                interval_ms={name: intervals[round((len(intervals) - 1) * fraction)]
                             for name, fraction in (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1))},
                over25ms=sum(value > 25 for value in intervals),
                over50ms=sum(value > 50 for value in intervals),
                over_1_5_refresh=sum(value > period * 1.5 / 1e6 for value in intervals),
                timestamps_ns=timestamps)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Device:
    def __init__(self, serial):
        self.prefix = ["adb", "-s", serial, "shell"]

    def shell(self, *args):
        return subprocess.check_output(self.prefix + [" ".join(shlex.quote(str(arg)) for arg in args)],
                                       text=True, encoding="utf-8", timeout=15).strip()

    def snapshot(self, output, suffix):
        pids = self.shell("pidof", PACKAGE).split()
        if len(pids) != 1 or not pids[0].isdigit():
            raise ValueError("expected one running Heroes V process")
        pid = int(pids[0])
        stat = self.shell("run-as", PACKAGE, "cat", f"/proc/{pid}/stat")
        if int(stat.split(" (", 1)[0]) != pid:
            raise ValueError("process stat PID mismatch")
        starttime = int(stat.rsplit(")", 1)[1].split()[19])
        maps = self.shell("run-as", PACKAGE, "cat", f"/proc/{pid}/maps")
        libraries = {line.split()[-1] for line in maps.splitlines() if line.endswith("/libhomm5.so")}
        if len(libraries) != 1:
            raise ValueError("expected one mapped libhomm5.so path")
        library = libraries.pop()
        checksum = self.shell("run-as", PACKAGE, "sha256sum", library).split()[0]
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("invalid mapped library checksum")
        windows = self.shell("dumpsys", "window")
        focused = require_visible(windows)
        display = self.shell("dumpsys", "display")
        mode = parse_display(display)
        layers = self.shell("dumpsys", "SurfaceFlinger", "--list")
        matches = [line for line in layers.splitlines() if "SurfaceView[" + PACKAGE in line and "(BLAST)" in line]
        if len(matches) != 1:
            raise ValueError("expected one Heroes V SurfaceView BLAST layer")
        layer = matches[0].split("{", 1)[-1].split(" parentId=", 1)[0].rstrip("}")
        for name, data in (("display", display), ("windows", windows), ("layers", layers)):
            (output / f"{name}-{suffix}.txt").write_text(data + "\n", encoding="utf-8")
        if self.shell("pidof", PACKAGE) != str(pid):
            raise ValueError("process changed during snapshot")
        return dict(pid=pid, starttime=starttime, library_sha256=checksum, library_path=library,
                    focused_window=focused, layer=layer, display=mode)


def measure(device, output, duration):
    before = device.snapshot(output, "before")
    local_hash = digest(LIBRARY)
    if before["library_sha256"] != local_hash:
        raise ValueError("mapped library does not match local libhomm5.so")
    thermal_before = device.shell("dumpsys", "thermalservice")
    history, polls, period = [], [], None
    start = last_new = None
    while True:
        poll_start = time.monotonic()
        raw = device.shell("dumpsys", "SurfaceFlinger", "--latency", before["layer"])
        polled = time.monotonic()
        (output / f"{len(polls):04}.txt").write_text(raw + "\n", encoding="utf-8")
        current_period, sample = parse_latency(raw)
        if period is not None and current_period != period:
            raise ValueError("display refresh period changed during measurement")
        period = current_period
        old_last = history[-1] if history else None
        history = merge_history(history, sample)
        if start is None:
            start = last_new = polled
        if history[-1] != old_last:
            last_new = polled
        if polled - last_new > 1:
            raise ValueError("surface stopped presenting for over one second")
        polls.append(dict(monotonic=polled, request_seconds=polled - poll_start,
                          history_frames=len(sample), latest_present_ns=sample[-1]))
        if polled - start >= duration:
            break
        time.sleep(min(POLL_SECONDS, duration - (polled - start)))
    after = device.snapshot(output, "after")
    validate_identity(before, after)
    if digest(LIBRARY) != local_hash:
        raise ValueError("local library changed during measurement")
    result = summarize(history, period)
    if len(history) < 100:
        raise ValueError("too few presentations for a pacing measurement")
    return dict(serial=device.prefix[2], package=PACKAGE, before=before, after=after,
                library_sha256=local_hash, requested_duration_s=duration,
                poll_seconds=POLL_SECONDS, polls=polls, thermal_before=thermal_before,
                thermal_after=device.shell("dumpsys", "thermalservice"), **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.environ.get("HOMM5_SERIAL") or os.environ.get("ANDROID_SERIAL"))
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    if not args.serial:
        parser.error("select a device with --serial or ANDROID_SERIAL")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.label) or not math.isfinite(args.duration) or args.duration < 5:
        parser.error("label must contain letters/digits/-/_ and duration must be finite and at least 5 seconds")
    output = ROOT / "build" / args.label
    output.mkdir(parents=True, exist_ok=False)
    try:
        result = measure(Device(args.serial), output, args.duration)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        (output / "rejected.json").write_text(json.dumps(dict(accepted=False, error=str(error)), indent=2) + "\n", encoding="utf-8")
        raise SystemExit("Pacing measurement rejected: " + str(error)) from error
    result.update(label=args.label, accepted=True)
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("frames", "duration_s", "fps", "refresh_period_ns", "interval_ms", "over_1_5_refresh")}, indent=2))


if __name__ == "__main__":
    main()
