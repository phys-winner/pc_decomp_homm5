"""Offline controls for the real SurfaceFlinger pacing parser and continuity guards."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("measure_pacing", ROOT / "tools/measure_pacing.py")
pacing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pacing)

PERIOD_120 = 8_333_333
PERIOD_60 = 16_666_667
SENTINEL = (1 << 63) - 1


def latency(timestamps, period=PERIOD_120):
    # Deliberately distinct columns: only the actual presentation (column 2) counts.
    return str(period) + "\n" + "\n".join(f"{stamp - 17} {stamp} {stamp + 29}" for stamp in timestamps) + "\n"


def display_info(mode=2, rate="120.0", render="120.0", width=2560, height=1600):
    return (f'  mDisplayInfo=DisplayInfo{{"Built-in", displayId 0, real {width} x {height}, '
            f'mode {mode}, renderFrameRate {render}, modes [{{id=1, width={width}, height={height}, fps=60.0}}, '
            f'{{id=2, width={width}, height={height}, fps={rate}}}]}}\n')


def identity():
    return {
        "pid": "1234", "starttime": "567890", "library_sha256": "a" * 64,
        "layer": "SurfaceView[org.homm5.port/org.homm5.port.GameActivity](BLAST)#123",
        "display": {"mode_id": 2, "width": 2560, "height": 1600,
                    "refresh_rate": 120.0, "render_frame_rate": 120.0},
    }


class LatencyParsing(unittest.TestCase):
    def test_actual_column_sorted_unique_and_sentinel_filter(self):
        raw = latency([1300, 1100, 1300, 1200])
        raw += f"0 0 0\n1 {SENTINEL} {SENTINEL}\n"
        period, timestamps = pacing.parse_latency(raw)
        self.assertEqual(period, PERIOD_120)
        self.assertEqual(timestamps, [1100, 1200, 1300])

    def test_oplus_terminal_marker_preserves_frame_rows(self):
        # Rows and footer from an Android SurfaceFlinger capture.
        raw = ("8333333\n"
               "314388074094965\t314388091836631\t314388081033455\n"
               "314388090006371\t314388108477621\t314388097154601\n"
               "314390173878246\t9223372036854775807\t314390180592569\n")
        expected = (PERIOD_120, [314388091836631, 314388108477621])
        for ending in ("OPlusFrameTracker\n", "OPlusFrameTracker\n\n"):
            self.assertEqual(pacing.parse_latency(raw + ending), expected)
            self.assertEqual(pacing.parse_latency((raw + ending).replace("\n", "\r\n")), expected)

    def test_bad_headers_rows_and_empty_measurements_fail_closed(self):
        cases = (
            "", "not a period\n1 2 3\n", "0\n1 2 3\n", "-1\n1 2 3\n",
            str(PERIOD_120) + "\n", str(PERIOD_120) + "\n0 0 0\n",
            str(PERIOD_120) + f"\n0 {SENTINEL} 0\n",
            latency([1000]) + "bad row\n", latency([1000]) + "1 2\n",
            latency([1000]) + "1 2 3 4\n", latency([1000]) + "1 NaN 3\n",
            latency([1000]) + "OPlusFrameTracker junk\n",
            latency([1000]) + "OPlusFrameTracker\n1 2 3\n",
            latency([1000]) + "OPlusFrameTracker\nOPlusFrameTracker\n",
            latency([1000]) + "bad row\nOPlusFrameTracker\n",
            latency([1000]) + "1 -2 3\nOPlusFrameTracker\n",
            str(PERIOD_120) + "\nOPlusFrameTracker\n",
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                pacing.parse_latency(raw)

    def test_sixty_hz_is_measured_as_sixty(self):
        period, timestamps = pacing.parse_latency(latency([1_000_000_000 + i * PERIOD_60 for i in range(61)], PERIOD_60))
        self.assertEqual(period, PERIOD_60)
        self.assertEqual(len(timestamps), 61)
        self.assertAlmostEqual(pacing.summarize(timestamps, period)["fps"], 60, places=4)


class HistoryContinuity(unittest.TestCase):
    def test_initial_sample_is_only_an_anchor_then_overlaps_merge_once(self):
        initial = [100, 200, 300]
        history = pacing.merge_history([], initial)
        self.assertEqual(history, [300], "pre-measurement ring frames must not count")
        self.assertEqual(initial, [100, 200, 300])
        sample = [200, 300, 400, 500]
        saved = history.copy()
        merged = pacing.merge_history(history, sample)
        self.assertEqual(merged, [300, 400, 500])
        self.assertEqual(history, saved)
        self.assertEqual(sample, [200, 300, 400, 500])
        self.assertEqual(pacing.merge_history(merged, [300, 400, 500]), merged)
        self.assertEqual(pacing.merge_history(merged, [500, 600]), [300, 400, 500, 600])

    def test_120_hz_polling_keeps_the_whole_measured_window(self):
        frame = [10_000_000_000 + i * PERIOD_120 for i in range(841)]
        history = pacing.merge_history([], frame[:120])
        for last in range(180, 841, 60):
            history = pacing.merge_history(history, frame[last - 120:last])
        self.assertEqual(history, frame[119:840])
        stats = pacing.summarize(history, PERIOD_120)
        self.assertAlmostEqual(stats["fps"], 120, places=4)
        self.assertAlmostEqual(stats["duration_s"], 720 * PERIOD_120 / 1e9, places=9)
        self.assertEqual(stats["frames"], 721)

    def test_lost_overlap_and_backward_history_are_not_silently_joined(self):
        cases = (
            ([100, 200, 300], [400, 500, 600]),
            ([100, 200, 300], [100, 200]),
            ([100, 200, 300], [200, 400, 500]),
            ([100, 200, 300], []),
            ([], []),
        )
        for history, sample in cases:
            with self.subTest(history=history, sample=sample), self.assertRaises(ValueError):
                pacing.merge_history(history, sample)


class DisplayAndIdentity(unittest.TestCase):
    def test_current_display_and_current_mode_are_selected(self):
        primary = display_info()
        unrelated = display_info(mode=1, render="60.0").replace("displayId 0", "displayId 8")
        parsed = pacing.parse_display(unrelated + primary)
        self.assertEqual(parsed, identity()["display"])
        # The supported-mode list contains 120 Hz; the actual current mode is 60 Hz.
        legacy = pacing.parse_display(display_info(mode=1, render="60.0"))
        self.assertEqual(legacy["mode_id"], 1)
        self.assertEqual(legacy["refresh_rate"], 60.0)
        self.assertEqual(legacy["render_frame_rate"], 60.0)

    def test_missing_or_invalid_current_display_is_rejected(self):
        cases = (
            "", display_info().replace("displayId 0", "displayId 1"),
            display_info(mode=9), display_info(width=0), display_info(height=-1),
            display_info(rate="NaN"), display_info(rate="Infinity"), display_info(rate="0.0"),
            display_info(render="NaN"), display_info(render="Infinity"), display_info(render="0.0"),
            display_info().replace("mode 2, ", ""),
            display_info().replace("renderFrameRate 120.0, ", ""),
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                pacing.parse_display(raw)

    def test_only_game_focus_is_visible(self):
        component = "org.homm5.port/org.homm5.port.GameActivity"
        raw = f"  mCurrentFocus=Window{{abc u0 {component}}}\n"
        self.assertEqual(pacing.require_visible(raw), component)
        for wrong in ("", "mCurrentFocus=null\n", "mCurrentFocus=Window{abc u0 com.android.launcher/.Launcher}\n",
                      "mCurrentFocus=Window{abc u0 org.homm5.port.fake/.Activity}\n",
                      f"mFocusedApp=AppWindowToken{{{component}}}\nmCurrentFocus=null\n"):
            with self.subTest(raw=wrong), self.assertRaises(ValueError):
                pacing.require_visible(wrong)

    def test_invalid_authoritative_display_does_not_fall_back_to_stale_base(self):
        raw = display_info(mode=9) + display_info().replace("mDisplayInfo=", "mBaseDisplayInfo=")
        with self.assertRaises(ValueError):
            pacing.parse_display(raw)

    def test_identity_is_stable_including_library_layer_and_display(self):
        before = identity()
        after = copy.deepcopy(before)
        pacing.validate_identity(before, after)
        changes = (
            ("pid", "1235"), ("starttime", "567891"), ("library_sha256", "b" * 64),
            ("layer", before["layer"] + "-recreated"),
        )
        for key, value in changes:
            changed = copy.deepcopy(before)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                pacing.validate_identity(before, changed)
        for key, value in (("mode_id", 1), ("width", 1280), ("height", 800),
                           ("refresh_rate", 60.0), ("render_frame_rate", 60.0)):
            changed = copy.deepcopy(before)
            changed["display"][key] = value
            with self.subTest(display_key=key), self.assertRaises(ValueError):
                pacing.validate_identity(before, changed)
        for key in before:
            changed = copy.deepcopy(before)
            del changed[key]
            with self.subTest(missing_key=key), self.assertRaises((ValueError, KeyError)):
                pacing.validate_identity(before, changed)


class Summary(unittest.TestCase):
    def test_exact_120_and_jank_are_computed_from_intervals(self):
        clean = [10_000_000_000 + i * PERIOD_120 for i in range(121)]
        stats = pacing.summarize(clean, PERIOD_120)
        self.assertEqual(stats["frames"], 121)
        self.assertAlmostEqual(stats["duration_s"], 120 * PERIOD_120 / 1e9, places=9)
        self.assertAlmostEqual(stats["fps"], 120, places=4)
        for key in ("p50", "p95", "p99", "max"):
            self.assertAlmostEqual(stats["interval_ms"][key], PERIOD_120 / 1e6, places=7)
        for key in ("over25ms", "over50ms", "over_1_5_refresh"):
            self.assertEqual(stats[key], 0)

        # Include an exact 25 ms interval: the threshold is strictly greater.
        intervals = [8_333_333, 16_666_666, 25_000_000, 30_000_000, 60_000_000]
        timestamps = [10_000_000_000]
        for interval in intervals:
            timestamps.append(timestamps[-1] + interval)
        stats = pacing.summarize(timestamps, PERIOD_120)
        self.assertEqual(stats["over25ms"], 2)
        self.assertEqual(stats["over50ms"], 1)
        self.assertEqual(stats["over_1_5_refresh"], 4)
        self.assertEqual(stats["interval_ms"]["max"], 60.0)
        self.assertAlmostEqual(stats["fps"], 5e9 / sum(intervals))

    def test_insufficient_or_nonmonotonic_timestamps_are_rejected(self):
        for timestamps, period in (([], PERIOD_120), ([100], PERIOD_120), ([100, 100], PERIOD_120),
                                   ([200, 100], PERIOD_120), ([100, 200], 0)):
            with self.subTest(timestamps=timestamps, period=period), self.assertRaises(ValueError):
                pacing.summarize(timestamps, period)


class Collector(unittest.TestCase):
    class Clock:
        now = 0.0

        def monotonic(self):
            return self.now

        def sleep(self, seconds):
            self.now += seconds

    class Device:
        prefix = ["adb", "-s", "fixture-only", "shell"]

        def __init__(self, clock, failure=None):
            self.clock, self.failure = clock, failure
            self.calls = 0
            self.snapshots = []

        def snapshot(self, output, suffix):
            self.snapshots.append(suffix)
            value = identity()
            if suffix == "after" and self.failure in ("pid", "library_sha256"):
                value[self.failure] = "changed"
            if self.failure == "mapped_library":
                value["library_sha256"] = "b" * 64
            return value

        def shell(self, *args):
            if args == ("dumpsys", "thermalservice"):
                return "fixture thermal status"
            assert args == ("dumpsys", "SurfaceFlinger", "--latency", identity()["layer"])
            self.calls += 1
            self.clock.now += .01
            latest = 128 + int(self.clock.now * 120)
            if self.failure == "stale":
                latest = 128
            if self.failure == "lost_overlap" and self.calls >= 3:
                latest += 1000
            period = PERIOD_60 if self.failure == "period" and self.calls >= 3 else PERIOD_120
            stamps = [10_000_000_000 + frame * period for frame in range(latest - 127, latest + 1)]
            return latency(stamps, period)

    def run_collector(self, failure=None):
        clock = self.Clock()
        device = self.Device(clock, failure)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(pacing.time, "monotonic", clock.monotonic), \
                patch.object(pacing.time, "sleep", clock.sleep), \
                patch.object(pacing, "digest", return_value="a" * 64):
            result = pacing.measure(device, Path(directory), 2.1)
            self.assertGreaterEqual(len(list(Path(directory).glob("[0-9]*.txt"))), 8)
        return device, result

    def test_actual_collector_with_120_hz_overlapping_ring(self):
        device, result = self.run_collector()
        self.assertEqual(device.snapshots, ["before", "after"])
        self.assertEqual(result["serial"], "fixture-only")
        self.assertAlmostEqual(result["fps"], 120, places=4)
        self.assertGreater(result["frames"], 200)
        self.assertGreaterEqual(result["duration_s"], 2.0)
        self.assertEqual(result["over_1_5_refresh"], 0)

    def test_actual_collector_rejects_stale_lost_changed_identity_and_period(self):
        for failure, message in (("stale", "stopped presenting"), ("lost_overlap", "overlap lost"),
                                 ("pid", "identity changed"), ("library_sha256", "identity changed"),
                                 ("period", "refresh period changed"), ("mapped_library", "does not match local")):
            with self.subTest(failure=failure), self.assertRaisesRegex(ValueError, message):
                self.run_collector(failure)


if __name__ == "__main__":
    unittest.main()
