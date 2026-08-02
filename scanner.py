#!/usr/bin/env python3
"""Robot Camera Scanner core.

The module intentionally uses only the Python standard library plus DepthAI.
RealSense streaming is delegated to the small librealsense C++ helper built by
setup.sh.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import datetime as dt
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable, Optional, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
RS_FRAME_TEST_BIN = SCRIPT_DIR / ".build" / "rs-frame-test"
SCHEMA_VERSION = 1


@dataclasses.dataclass
class FrameMetrics:
    status: str = "not_tested"
    duration_seconds: float = 0.0
    target_fps: Optional[float] = None
    actual_fps: Optional[float] = None
    received_frames: int = 0
    dropped_frames: int = 0
    drop_percent: Optional[float] = None
    interval_avg_ms: Optional[float] = None
    interval_p95_ms: Optional[float] = None
    jitter_p95_ms: Optional[float] = None
    max_gap_ms: Optional[float] = None
    max_consecutive_drops: int = 0
    latency_p95_ms: Optional[float] = None
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class CameraResult:
    camera_type: str
    name: str
    serial: str
    port: str = "Not available"
    connection_speed: str = "Not reported"
    location: Optional[str] = None
    stability_successful: int = 0
    stability_samples: int = 0
    frame_test: FrameMetrics = dataclasses.field(default_factory=FrameMetrics)
    health_status: str = "UNKNOWN"
    health_reasons: list[str] = dataclasses.field(default_factory=list)
    device_info: Any = dataclasses.field(default=None, repr=False, compare=False)

    @property
    def stability_status(self) -> str:
        if self.stability_samples == 0:
            return "not_checked"
        if self.stability_successful == self.stability_samples:
            return "stable"
        return "unstable"

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.camera_type,
            "name": self.name,
            "serial": self.serial,
            "port": self.port,
            "location": self.location,
            "connection_speed": self.connection_speed,
            "stability": {
                "status": self.stability_status,
                "successful_checks": self.stability_successful,
                "total_checks": self.stability_samples,
            },
            "frame_test": self.frame_test.as_dict(),
            "health": {
                "status": self.health_status,
                "reasons": self.health_reasons,
            },
        }


def percentile(values: Sequence[float], percent: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percent / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def metrics_from_frames(
    arrival_times: Sequence[float],
    sequences: Sequence[int],
    target_fps: float,
    duration_seconds: float,
    latencies_ms: Sequence[float] = (),
) -> FrameMetrics:
    if len(arrival_times) != len(sequences):
        raise ValueError("arrival_times and sequences must have equal length")
    if not arrival_times:
        return FrameMetrics(
            status="failed",
            duration_seconds=duration_seconds,
            target_fps=target_fps,
            error="no frames received",
        )

    intervals_ms = [
        (arrival_times[index] - arrival_times[index - 1]) * 1000.0
        for index in range(1, len(arrival_times))
    ]
    elapsed = arrival_times[-1] - arrival_times[0]
    actual_fps = (
        (len(arrival_times) - 1) / elapsed
        if len(arrival_times) > 1 and elapsed > 0.0
        else 0.0
    )

    dropped = 0
    max_consecutive = 0
    for previous, current in zip(sequences, sequences[1:]):
        gap = max(0, current - previous - 1)
        dropped += gap
        max_consecutive = max(max_consecutive, gap)

    expected = len(sequences) + dropped
    drop_percent = 100.0 * dropped / expected if expected else 0.0
    interval_median = statistics.median(intervals_ms) if intervals_ms else 0.0
    jitter = [abs(interval - interval_median) for interval in intervals_ms]

    return FrameMetrics(
        status="ok",
        duration_seconds=duration_seconds,
        target_fps=target_fps,
        actual_fps=actual_fps,
        received_frames=len(sequences),
        dropped_frames=dropped,
        drop_percent=drop_percent,
        interval_avg_ms=(statistics.fmean(intervals_ms) if intervals_ms else None),
        interval_p95_ms=percentile(intervals_ms, 95.0),
        jitter_p95_ms=percentile(jitter, 95.0),
        max_gap_ms=max(intervals_ms) if intervals_ms else None,
        max_consecutive_drops=max_consecutive,
        latency_p95_ms=percentile(list(latencies_ms), 95.0),
    )


def clean_text(value: Any) -> str:
    return " ".join(str(value).replace("\t", " ").splitlines()).strip()


def first_value(obj: Any, methods: Iterable[str] = (), attributes: Iterable[str] = ()) -> str:
    for method_name in methods:
        method = getattr(obj, method_name, None)
        if callable(method):
            try:
                value = method()
            except Exception:
                continue
            if value:
                return str(value)
    for attribute_name in attributes:
        value = getattr(obj, attribute_name, None)
        if value:
            return str(value)
    return ""


def find_realsense_tool() -> Optional[str]:
    discovered = shutil.which("rs-enumerate-devices")
    if discovered:
        return discovered
    for candidate in (
        "/opt/homebrew/bin/rs-enumerate-devices",
        "/usr/local/bin/rs-enumerate-devices",
        "/usr/bin/rs-enumerate-devices",
    ):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def run_command(command: Sequence[str], timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def format_realsense_speed(descriptor: str) -> str:
    if not descriptor:
        return "Not reported"
    if descriptor.startswith("3"):
        return f"USB {descriptor} (SuperSpeed)"
    if descriptor.startswith("2"):
        return f"USB {descriptor} (High-Speed)"
    return f"USB {descriptor}"


def realsense_location(physical_port: str) -> str:
    import re

    match = re.match(r".*\.([0-9]+)-.*", physical_port)
    hub_port = match.group(1) if match else ""
    labels = {
        "1": "Hub Port 1 — Right Hand",
        "2": "Hub Port 2",
        "3": "Hub Port 3",
        "4": "Hub Port 4 — Left Hand",
    }
    return labels.get(hub_port, f"Unknown port ({physical_port})")


def parse_realsense_output(output: str) -> list[CameraResult]:
    cameras: list[CameraResult] = []
    current: dict[str, str] = {}

    def finish() -> None:
        if not current.get("Name"):
            return
        physical_port = current.get("Physical Port", "Not available")
        descriptor = current.get("Usb Type Descriptor") or current.get(
            "USB Type Descriptor", ""
        )
        cameras.append(
            CameraResult(
                camera_type="realsense",
                name=current["Name"],
                serial=current.get("Serial Number", "Not available"),
                port=physical_port,
                connection_speed=format_realsense_speed(descriptor),
                location=realsense_location(physical_port),
            )
        )

    for raw_line in output.splitlines():
        if ":" not in raw_line:
            continue
        key, value = (part.strip() for part in raw_line.split(":", 1))
        if key == "Name" and current.get("Name"):
            finish()
            current = {}
        if key in {
            "Name",
            "Serial Number",
            "Physical Port",
            "Usb Type Descriptor",
            "USB Type Descriptor",
        }:
            current[key] = value
    finish()
    return cameras


def enumerate_realsense(tool: Optional[str], warnings: list[str]) -> list[CameraResult]:
    if not tool:
        warnings.append("RealSense scan skipped: run ./setup.sh to install librealsense.")
        return []
    try:
        result = run_command([tool])
    except Exception as exc:
        warnings.append(f"RealSense scan failed: {clean_text(exc)}")
        return []
    combined = f"{result.stdout}\n{result.stderr}"
    if "No device detected" in combined or not result.stdout.strip():
        return []
    return parse_realsense_output(result.stdout)


def format_oak_speed(speed: Any) -> str:
    name = str(speed).rsplit(".", 1)[-1]
    return {
        "LOW": "USB Low-Speed (1.5 Mbit/s)",
        "FULL": "USB Full-Speed (12 Mbit/s)",
        "HIGH": "USB 2.0 High-Speed (480 Mbit/s)",
        "SUPER": "USB 3.x SuperSpeed (5 Gbit/s)",
        "SUPER_PLUS": "USB 3.x SuperSpeedPlus (10 Gbit/s)",
        "UNKNOWN": "Not reported",
    }.get(name, clean_text(speed) or "Not reported")


def oak_identity(info: Any) -> tuple[str, str]:
    serial = first_value(
        info,
        methods=("getDeviceId", "getMxId"),
        attributes=("deviceId", "mxid"),
    )
    port = first_value(info, attributes=("name",))
    return serial, port


def enumerate_oak(dai: Any, warnings: list[str]) -> list[CameraResult]:
    cameras: list[CameraResult] = []
    try:
        infos = list(dai.Device.getAllAvailableDevices())
    except Exception as exc:
        warnings.append(f"OAK scan failed: {clean_text(exc)}")
        return []

    for info in infos:
        serial, port = oak_identity(info)
        camera = CameraResult(
            camera_type="oak",
            name="Luxonis OAK camera",
            serial=serial or "Not available",
            port=port or "Not available",
            device_info=info,
        )
        try:
            with dai.Device(info) as device:
                try:
                    get_usb_speed = getattr(device, "getUsbSpeed", None)
                    if callable(get_usb_speed):
                        camera.connection_speed = format_oak_speed(get_usb_speed())
                except Exception:
                    pass
                try:
                    calibration = None
                    for method_name in ("readCalibration", "readCalibration2"):
                        method = getattr(device, method_name, None)
                        if callable(method):
                            calibration = method()
                            break
                    if calibration is not None:
                        product = getattr(calibration.getEepromData(), "productName", "")
                        if product:
                            camera.name = str(product)
                except Exception:
                    pass
        except Exception:
            pass
        cameras.append(camera)
    return cameras


def check_realsense_stability(
    cameras: Sequence[CameraResult], tool: str, samples: int, delay: float
) -> None:
    for camera in cameras:
        camera.stability_samples = samples
        camera.stability_successful = 1
    for _ in range(1, samples):
        time.sleep(delay)
        try:
            result = run_command([tool])
            output = result.stdout
        except Exception:
            output = ""
        for camera in cameras:
            if camera.serial != "Not available" and camera.serial in output:
                camera.stability_successful += 1


def check_oak_stability(cameras: Sequence[CameraResult], dai: Any, samples: int, delay: float) -> None:
    for camera in cameras:
        camera.stability_samples = samples
        camera.stability_successful = 1
    for _ in range(1, samples):
        time.sleep(delay)
        try:
            available = [oak_identity(info) for info in dai.Device.getAllAvailableDevices()]
        except Exception:
            available = []
        serials = {serial for serial, _ in available if serial}
        ports = {port for _, port in available if port}
        for camera in cameras:
            found = (
                camera.serial != "Not available" and camera.serial in serials
            ) or (camera.port != "Not available" and camera.port in ports)
            if found:
                camera.stability_successful += 1


def parse_realsense_metrics(output: str, duration: float) -> FrameMetrics:
    fields = output.strip().split("\t")
    if len(fields) < 5:
        raise ValueError(f"unexpected helper output: {clean_text(output)}")
    values = [float(field) for field in fields]
    return FrameMetrics(
        status="ok",
        duration_seconds=duration,
        actual_fps=values[0],
        received_frames=int(values[1]),
        dropped_frames=int(values[2]),
        drop_percent=values[3],
        target_fps=values[4],
        interval_avg_ms=(values[5] if len(values) > 5 else None),
        interval_p95_ms=(values[6] if len(values) > 6 else None),
        jitter_p95_ms=(values[7] if len(values) > 7 else None),
        max_gap_ms=(values[8] if len(values) > 8 else None),
        max_consecutive_drops=(int(values[9]) if len(values) > 9 else 0),
    )


def test_realsense_frames(camera: CameraResult, duration: float) -> FrameMetrics:
    if not RS_FRAME_TEST_BIN.is_file() or not os.access(RS_FRAME_TEST_BIN, os.X_OK):
        return FrameMetrics(status="not_tested", error="run ./setup.sh")
    try:
        result = run_command(
            [str(RS_FRAME_TEST_BIN), camera.serial, str(duration)],
            timeout=duration + 15.0,
        )
    except Exception as exc:
        return FrameMetrics(status="failed", duration_seconds=duration, error=clean_text(exc))
    if result.returncode != 0:
        return FrameMetrics(
            status="failed",
            duration_seconds=duration,
            error=clean_text(result.stderr or result.stdout) or "unknown error",
        )
    try:
        return parse_realsense_metrics(result.stdout, duration)
    except Exception as exc:
        return FrameMetrics(status="failed", duration_seconds=duration, error=clean_text(exc))


def test_oak_frames(camera: CameraResult, dai: Any, duration: float) -> FrameMetrics:
    pipeline_type = getattr(dai, "Pipeline", None)
    node_namespace = getattr(dai, "node", None)
    if (
        pipeline_type is None
        or not hasattr(pipeline_type, "start")
        or node_namespace is None
        or not hasattr(node_namespace, "Camera")
    ):
        return FrameMetrics(status="not_tested", error="DepthAI 3 required")

    pipeline = None
    started = False
    try:
        with dai.Device(camera.device_info) as device:
            pipeline = dai.Pipeline(device)
            node = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
            output = node.requestOutput((640, 400), fps=30)
            queue = output.createOutputQueue(maxSize=120, blocking=False)
            pipeline.start()
            started = True

            startup_deadline = time.monotonic() + 5.0
            measurement_deadline: Optional[float] = None
            arrivals: list[float] = []
            sequences: list[int] = []
            latencies_ms: list[float] = []

            while True:
                now = time.monotonic()
                if measurement_deadline is None:
                    if now >= startup_deadline:
                        raise RuntimeError("no frames received during startup")
                elif now >= measurement_deadline:
                    break

                frame = queue.tryGet()
                if frame is None:
                    time.sleep(0.001)
                    continue

                arrived_at = time.monotonic()
                if measurement_deadline is None:
                    measurement_deadline = arrived_at + duration
                arrivals.append(arrived_at)
                sequences.append(int(frame.getSequenceNum()))

                get_timestamp = getattr(frame, "getTimestamp", None)
                if callable(get_timestamp):
                    try:
                        latency = (arrived_at - get_timestamp().total_seconds()) * 1000.0
                        if 0.0 <= latency <= 10_000.0:
                            latencies_ms.append(latency)
                    except Exception:
                        pass

            return metrics_from_frames(arrivals, sequences, 30.0, duration, latencies_ms)
    except Exception as exc:
        return FrameMetrics(status="failed", duration_seconds=duration, error=clean_text(exc))
    finally:
        if pipeline is not None and started:
            try:
                pipeline.stop()
            except Exception:
                pass


def run_frame_tests(
    cameras: Sequence[CameraResult],
    dai: Any,
    duration: float,
    parallel: bool,
) -> None:
    if duration == 0:
        for camera in cameras:
            camera.frame_test = FrameMetrics(status="disabled")
        return

    def run_one(camera: CameraResult) -> FrameMetrics:
        if camera.camera_type == "realsense":
            return test_realsense_frames(camera, duration)
        return test_oak_frames(camera, dai, duration)

    if parallel and len(cameras) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(cameras)) as executor:
            future_map = {executor.submit(run_one, camera): camera for camera in cameras}
            for future in concurrent.futures.as_completed(future_map):
                camera = future_map[future]
                try:
                    camera.frame_test = future.result()
                except Exception as exc:
                    camera.frame_test = FrameMetrics(status="failed", error=clean_text(exc))
    else:
        for camera in cameras:
            camera.frame_test = run_one(camera)


def classify_camera(camera: CameraResult) -> None:
    warnings: list[str] = []
    failures: list[str] = []

    if camera.stability_samples:
        ratio = camera.stability_successful / camera.stability_samples
        if ratio < 0.8:
            failures.append("device disappeared in stability checks")
        elif ratio < 1.0:
            warnings.append("device was intermittently unavailable")

    metrics = camera.frame_test
    if metrics.status == "failed":
        failures.append(f"frame test failed: {metrics.error or 'unknown error'}")
    elif metrics.status == "not_tested":
        warnings.append(f"frame test not performed: {metrics.error or 'unknown reason'}")
    elif metrics.status == "ok":
        if metrics.drop_percent is not None:
            if metrics.drop_percent >= 5.0:
                failures.append(f"frame loss is {metrics.drop_percent:.1f}%")
            elif metrics.drop_percent >= 0.5:
                warnings.append(f"frame loss is {metrics.drop_percent:.1f}%")
        if metrics.actual_fps is not None and metrics.target_fps:
            fps_ratio = metrics.actual_fps / metrics.target_fps
            if fps_ratio < 0.8:
                failures.append("FPS is below 80% of target")
            elif fps_ratio < 0.95:
                warnings.append("FPS is below 95% of target")
        if metrics.jitter_p95_ms is not None:
            if metrics.jitter_p95_ms >= 15.0:
                failures.append(f"jitter p95 is {metrics.jitter_p95_ms:.1f} ms")
            elif metrics.jitter_p95_ms >= 5.0:
                warnings.append(f"jitter p95 is {metrics.jitter_p95_ms:.1f} ms")

    if "High-Speed" in camera.connection_speed:
        warnings.append("camera is connected through USB 2.0")

    if failures:
        camera.health_status = "FAILED"
        camera.health_reasons = failures + warnings
    elif warnings:
        camera.health_status = "WARNING"
        camera.health_reasons = warnings
    else:
        camera.health_status = "OK"
        camera.health_reasons = []


def overall_status(cameras: Sequence[CameraResult], warnings: Sequence[str]) -> str:
    if not cameras or any(camera.health_status == "FAILED" for camera in cameras):
        return "FAILED"
    if warnings or any(camera.health_status == "WARNING" for camera in cameras):
        return "WARNING"
    return "OK"


def optional_number(value: Optional[float], suffix: str = "", digits: int = 1) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def render_text(cameras: Sequence[CameraResult], warnings: Sequence[str], status: str, parallel: bool) -> str:
    lines = [
        "==========================================",
        "        Robot Camera Scanner",
        "==========================================",
        "",
        f"Overall status: {status}",
        f"Frame-test mode: {'parallel' if parallel else 'sequential'}",
        f"Cameras found: {len(cameras)}",
        "",
    ]
    if not cameras:
        lines.extend(["No RealSense or OAK cameras detected.", ""])

    for index, camera in enumerate(cameras, start=1):
        metrics = camera.frame_test
        lines.extend(
            [
                f"{index}. {camera.name}",
                f"   Type: {camera.camera_type}",
                f"   Serial number: {camera.serial}",
                f"   Health: {camera.health_status}",
                f"   Connection speed: {camera.connection_speed}",
                (
                    "   Stability: "
                    f"{camera.stability_status.title()} "
                    f"({camera.stability_successful}/{camera.stability_samples} checks)"
                ),
            ]
        )
        if metrics.status == "ok":
            lines.extend(
                [
                    (
                        "   Frame test: "
                        f"{optional_number(metrics.actual_fps, ' FPS')} "
                        f"(target {optional_number(metrics.target_fps)}); "
                        f"{metrics.received_frames} frames; "
                        f"{metrics.dropped_frames} dropped "
                        f"({optional_number(metrics.drop_percent, '%')})"
                    ),
                    (
                        "   Timing: "
                        f"interval p95 {optional_number(metrics.interval_p95_ms, ' ms')}; "
                        f"jitter p95 {optional_number(metrics.jitter_p95_ms, ' ms')}; "
                        f"max gap {optional_number(metrics.max_gap_ms, ' ms')}"
                    ),
                    f"   Max consecutive drops: {metrics.max_consecutive_drops}",
                ]
            )
            if metrics.latency_p95_ms is not None:
                lines.append(
                    f"   Host latency p95: {optional_number(metrics.latency_p95_ms, ' ms')}"
                )
        else:
            detail = metrics.error or metrics.status
            lines.append(f"   Frame test: {metrics.status.replace('_', ' ').title()} ({detail})")

        if camera.location:
            lines.append(f"   Location: {camera.location}")
        elif camera.port != "Not available":
            lines.append(f"   USB path: {camera.port}")
        for reason in camera.health_reasons:
            lines.append(f"   - {reason}")
        lines.append("")

    if warnings:
        lines.append("Warnings:")
        lines.extend(f"   - {warning}" for warning in warnings)
        lines.append("")
    lines.append("==========================================")
    return "\n".join(lines)


def build_report(
    cameras: Sequence[CameraResult],
    warnings: Sequence[str],
    status: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    counts = {name: sum(camera.health_status == name for camera in cameras) for name in ("OK", "WARNING", "FAILED")}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "configuration": {
            "duration_seconds": args.duration,
            "stability_samples": args.samples,
            "frame_test_mode": "parallel" if args.parallel else "sequential",
            "camera_filter": args.camera,
        },
        "summary": {
            "status": status,
            "cameras_found": len(cameras),
            "health_counts": counts,
        },
        "cameras": [camera.as_dict() for camera in cameras],
        "warnings": list(warnings),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sudo_uid = os.environ.get("SUDO_UID")
    sudo_gid = os.environ.get("SUDO_GID")
    if sudo_uid and sudo_gid:
        try:
            os.chown(path, int(sudo_uid), int(sudo_gid))
        except OSError:
            pass


def import_depthai() -> tuple[Any, Optional[str]]:
    try:
        import depthai as dai  # type: ignore

        return dai, None
    except Exception as exc:
        return None, clean_text(exc)


def dependency_check() -> int:
    tool = find_realsense_tool()
    dai, dai_error = import_depthai()
    checks = [
        (tool is not None, f"RealSense SDK: {tool}" if tool else "RealSense SDK"),
        (dai is not None, f"DepthAI: {getattr(dai, '__version__', 'unknown')}" if dai else f"DepthAI: {dai_error}"),
        (RS_FRAME_TEST_BIN.is_file() and os.access(RS_FRAME_TEST_BIN, os.X_OK), "RealSense FPS/frame-loss helper"),
    ]
    print("Dependency check")
    print("================")
    for success, label in checks:
        print(f"[{'OK' if success else 'MISSING'}] {label}")
    print()
    if all(success for success, _ in checks):
        print("All required dependencies are installed.")
        return 0
    print(f"Some dependencies are missing. Run: {SCRIPT_DIR / 'setup.sh'}")
    return 2


def environment_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="camera-scan",
        description="Scan and test Intel RealSense and Luxonis OAK cameras."
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=environment_int("CAMERA_SCAN_FRAME_TEST_SECONDS", 3),
        metavar="SECONDS",
        help="frame test duration, 0 disables it (default: 3, max: 30)",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=environment_int("CAMERA_SCAN_STABILITY_SAMPLES", 5),
        metavar="COUNT",
        help="stability discovery checks (default: 5, max: 20)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="stream all cameras simultaneously to stress shared USB bandwidth",
    )
    parser.add_argument(
        "--camera",
        choices=("all", "realsense", "oak"),
        default="all",
        help="only test one camera family (default: all)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--output", type=Path, help="also save a JSON report to this file")
    parser.add_argument(
        "--check-dependencies",
        "--check",
        action="store_true",
        help="check dependencies without accessing cameras",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.duration <= 30:
        parser.error("--duration must be between 0 and 30")
    if not 1 <= args.samples <= 20:
        parser.error("--samples must be between 1 and 20")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.check_dependencies:
        return dependency_check()

    warnings: list[str] = []
    rs_tool = find_realsense_tool()
    dai, dai_error = import_depthai()

    cameras: list[CameraResult] = []
    if args.camera in ("all", "realsense"):
        cameras.extend(enumerate_realsense(rs_tool, warnings))
    if args.camera in ("all", "oak"):
        if dai is None:
            warnings.append(f"OAK scan skipped: DepthAI unavailable ({dai_error}).")
        else:
            cameras.extend(enumerate_oak(dai, warnings))

    realsense = [camera for camera in cameras if camera.camera_type == "realsense"]
    oak = [camera for camera in cameras if camera.camera_type == "oak"]
    if realsense and rs_tool:
        check_realsense_stability(realsense, rs_tool, args.samples, 0.25)
    if oak and dai is not None:
        check_oak_stability(oak, dai, args.samples, 0.25)

    run_frame_tests(cameras, dai, args.duration, args.parallel)
    for camera in cameras:
        classify_camera(camera)

    status = overall_status(cameras, warnings)
    report = build_report(cameras, warnings, status, args)
    if args.output:
        write_report(args.output, report)

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_text(cameras, warnings, status, args.parallel))

    return {"OK": 0, "WARNING": 1, "FAILED": 2}[status]


if __name__ == "__main__":
    raise SystemExit(main())
