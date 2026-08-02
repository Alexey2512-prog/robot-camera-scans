import argparse
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import scanner  # noqa: E402


class MetricsTests(unittest.TestCase):
    def test_percentile_interpolates(self):
        self.assertEqual(scanner.percentile([], 95), None)
        self.assertEqual(scanner.percentile([10], 95), 10)
        self.assertAlmostEqual(scanner.percentile([0, 10], 50), 5)

    def test_metrics_count_sequence_gaps_and_jitter(self):
        metrics = scanner.metrics_from_frames(
            arrival_times=[0.0, 0.033, 0.066, 0.132],
            sequences=[10, 11, 12, 14],
            target_fps=30.0,
            duration_seconds=0.132,
        )
        self.assertEqual(metrics.status, "ok")
        self.assertEqual(metrics.received_frames, 4)
        self.assertEqual(metrics.dropped_frames, 1)
        self.assertEqual(metrics.max_consecutive_drops, 1)
        self.assertAlmostEqual(metrics.drop_percent, 20.0)
        self.assertGreater(metrics.jitter_p95_ms, 0.0)
        self.assertGreater(metrics.max_gap_ms, 60.0)

    def test_no_frames_is_failure(self):
        metrics = scanner.metrics_from_frames([], [], 30.0, 3.0)
        self.assertEqual(metrics.status, "failed")
        self.assertIn("no frames", metrics.error)

    def test_realsense_helper_extended_format(self):
        metrics = scanner.parse_realsense_metrics(
            "29.900\t90\t2\t2.174\t30\t33.400\t34.100\t1.200\t66.700\t2\n",
            3.0,
        )
        self.assertEqual(metrics.received_frames, 90)
        self.assertEqual(metrics.dropped_frames, 2)
        self.assertEqual(metrics.jitter_p95_ms, 1.2)
        self.assertEqual(metrics.max_consecutive_drops, 2)


class DiscoveryTests(unittest.TestCase):
    def test_parse_realsense_output(self):
        output = """
Device info:
    Name                    : Intel RealSense D435
    Serial Number           : RS123
    Physical Port           : /sys/devices/2-2.4-3
    Usb Type Descriptor     : 3.2
"""
        cameras = scanner.parse_realsense_output(output)
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0].serial, "RS123")
        self.assertEqual(cameras[0].connection_speed, "USB 3.2 (SuperSpeed)")
        self.assertIn("Left Hand", cameras[0].location)


class HealthTests(unittest.TestCase):
    def make_camera(self, metrics):
        return scanner.CameraResult(
            camera_type="oak",
            name="OAK-D-W",
            serial="ABC",
            connection_speed="USB 3.x SuperSpeed (5 Gbit/s)",
            stability_successful=5,
            stability_samples=5,
            frame_test=metrics,
        )

    def test_healthy_camera(self):
        camera = self.make_camera(
            scanner.FrameMetrics(
                status="ok",
                target_fps=30,
                actual_fps=29.9,
                drop_percent=0.0,
                jitter_p95_ms=1.0,
            )
        )
        scanner.classify_camera(camera)
        self.assertEqual(camera.health_status, "OK")

    def test_frame_loss_warning(self):
        camera = self.make_camera(
            scanner.FrameMetrics(
                status="ok",
                target_fps=30,
                actual_fps=29.9,
                drop_percent=1.0,
                jitter_p95_ms=1.0,
            )
        )
        scanner.classify_camera(camera)
        self.assertEqual(camera.health_status, "WARNING")

    def test_bad_fps_and_loss_fail(self):
        camera = self.make_camera(
            scanner.FrameMetrics(
                status="ok",
                target_fps=30,
                actual_fps=20,
                drop_percent=8.0,
                jitter_p95_ms=20.0,
            )
        )
        scanner.classify_camera(camera)
        self.assertEqual(camera.health_status, "FAILED")
        self.assertGreaterEqual(len(camera.health_reasons), 3)


class ReportTests(unittest.TestCase):
    def test_json_report_is_serializable_and_writable(self):
        camera = scanner.CameraResult(
            camera_type="realsense",
            name="D435",
            serial="RS1",
            health_status="OK",
        )
        args = argparse.Namespace(
            duration=3,
            samples=5,
            parallel=True,
            camera="all",
        )
        report = scanner.build_report([camera], [], "OK", args)
        encoded = json.dumps(report)
        self.assertIn('"schema_version": 1', encoded)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "report.json"
            scanner.write_report(path, report)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["status"], "OK")

    def test_cli_rejects_out_of_range_values(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                scanner.parse_args(["--duration", "31"])
            with self.assertRaises(SystemExit):
                scanner.parse_args(["--samples", "0"])


class ParallelTests(unittest.TestCase):
    def test_parallel_mode_runs_camera_tests_concurrently(self):
        cameras = [
            scanner.CameraResult("realsense", "D435", "RS1"),
            scanner.CameraResult("oak", "OAK-D-W", "OAK1"),
        ]

        barrier = threading.Barrier(2)

        def delayed_result(*_args):
            barrier.wait(timeout=1.0)
            return scanner.FrameMetrics(status="ok", actual_fps=30, target_fps=30)

        with mock.patch.object(scanner, "test_realsense_frames", side_effect=delayed_result), mock.patch.object(
            scanner, "test_oak_frames", side_effect=delayed_result
        ):
            scanner.run_frame_tests(cameras, object(), 1, parallel=True)

        self.assertTrue(all(camera.frame_test.status == "ok" for camera in cameras))


if __name__ == "__main__":
    unittest.main()
