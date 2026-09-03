#!/usr/bin/env python3
"""Drive the deterministic MPPT workload and capture process telemetry."""

import csv
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import time

import paho.mqtt.client as mqtt

try:
    from .analyze_memory import parse_smaps_rollup
except ImportError:  # Direct execution inside the benchmark image.
    from analyze_memory import parse_smaps_rollup

POINTS_PER_CYCLE = 7200
MEASURED_CYCLES = 5
CALIBRATION_POINTS = 200
RATES = (
    {"acceleration": 20, "publish_interval": 0.05},
    {"acceleration": 10, "publish_interval": 0.1},
)


def payload_for(index):
    """Return one deterministic, smooth MPPT measurement row."""
    voltage = 0.725 + 0.02 * math.sin(index * 0.017) + 0.005 * math.sin(index * 0.071)
    current = -0.019 + 0.0008 * math.sin(index * 0.013) + 0.0002 * math.cos(index * 0.053)
    return {
        # The existing MPPT handler expects the established four-column
        # instrument row; the final auxiliary field is unused by plotting.
        "data": [[voltage, current, float(index), 0.0]],
        "pixel": {"area": 1.0, "device_label": "benchmark-device"},
    }


def source_fingerprint():
    digest = hashlib.sha256()
    for path in sorted(Path("src").rglob("*")):
        if path.is_file():
            digest.update(str(path).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def runtime_versions():
    """Capture benchmark library and Debian runtime versions in run metadata."""
    packages = ("dash", "plotly", "numpy", "paho-mqtt")
    versions = {name: importlib.metadata.version(name) for name in packages}
    versions["python"] = platform.python_version()
    try:
        versions["webkitgtk"] = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", "libwebkit2gtk-4.1-0"],
            text=True,
        ).strip()
        versions["gtk"] = subprocess.check_output(
            ["dpkg-query", "-W", "-f=${Version}", "libgtk-3-0t64"],
            text=True,
        ).strip()
        versions["mosquitto"] = subprocess.check_output(
            ["mosquitto_sub", "--help"], stderr=subprocess.STDOUT, text=True
        ).splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        versions["system_packages"] = "unavailable"
    return versions


def process_group(cmdline, environment=""):
    if "webkit_view.py" in cmdline:
        return "gtk"
    if "WebKit" in cmdline:
        return "webkit"
    if "mppt-plotter" in cmdline:
        if "MPPT_ROLE=webkit-backed" in environment:
            return "plotter-webkit"
        if "MPPT_ROLE=server-only" in environment:
            return "plotter-server-only"
        return "plotter-unknown"
    if "mosquitto" in cmdline:
        return "mosquitto"
    return None


def collect_processes(writer, phase, cycle, published):
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmdline = (proc / "cmdline").read_bytes().replace(b"\0", b" ").decode()
            environment = (proc / "environ").read_bytes().replace(b"\0", b" ").decode()
            group = process_group(cmdline, environment)
            if group is None:
                continue
            memory = parse_smaps_rollup((proc / "smaps_rollup").read_text())
        except (FileNotFoundError, PermissionError, ProcessLookupError, UnicodeDecodeError):
            continue
        writer.writerow({
            "timestamp": time.time(), "phase": phase, "cycle": cycle,
            "points_published": published, "process_group": group,
            "pid": proc.name, **memory,
        })


def probe(webview, request_id):
    """Request one minimally invasive rendered-state sample."""
    if webview.poll() is not None:
        raise RuntimeError("GTK/WebKit harness exited")
    webview.stdin.write(json.dumps({"command": "probe", "id": request_id}) + "\n")
    webview.stdin.flush()
    while True:
        line = webview.stdout.readline()
        if not line:
            raise RuntimeError("GTK/WebKit harness output closed")
        response = json.loads(line)
        if response.get("event") == "web-process-terminated":
            raise RuntimeError("WebKit web process terminated")
        if response.get("event") == "probe" and response.get("id") == request_id:
            if "error" in response:
                raise RuntimeError(response["error"])
            return response["result"]


def wait_for_lengths(webview, expected, timeout=90, start_request_id=0):
    """Wait until all three aligned traces have exactly the expected length."""
    deadline = time.monotonic() + timeout
    request_id = start_request_id
    while time.monotonic() < deadline:
        request_id += 1
        result = probe(webview, request_id)
        lengths = result.get("lengths")
        if lengths == [expected, expected, expected]:
            return result, request_id
        time.sleep(0.25)
    raise TimeoutError(
        "rendered traces did not reach %s points; last probe was %r"
        % (expected, result)
    )


def calibration_sustainable(evidence):
    """Decide whether a calibration attempt rendered fully without stalling."""
    return (
        evidence["rendered_points"] == evidence["published_points"]
        and evidence["completed_callbacks"] > 0
        and evidence["active_requests"] == 0
        and evidence["overlap_events"]
        <= max(2, evidence["observed_requests"] * 0.05)
        and evidence["progress_observed"]
        and evidence["catchup_seconds"] <= 5.0
        and not evidence.get("process_failed", False)
    )


def calibrate(client, webview):
    """Choose the fastest sustainable rate and return auditable evidence."""
    attempts = []
    request_id = 1000
    for rate in RATES:
        client.publish("plotter/mppt_measurement/clear", "{}", qos=2).wait_for_publish()
        _, request_id = wait_for_lengths(webview, 0, start_request_id=request_id)
        webview.stdin.write(json.dumps({"command": "reset-metrics"}) + "\n")
        webview.stdin.flush()
        observed_lengths = []
        started = time.monotonic()
        for point in range(CALIBRATION_POINTS):
            client.publish(
                "data/raw/mppt_measurement", json.dumps(payload_for(point)), qos=2
            ).wait_for_publish()
            time.sleep(rate["publish_interval"])
            if point and point % 50 == 0:
                request_id += 1
                observed_lengths.append(probe(webview, request_id).get("lengths", [0])[0])
        publishing_finished = time.monotonic()
        error = None
        failure = None
        try:
            result, request_id = wait_for_lengths(
                webview, CALIBRATION_POINTS, timeout=30, start_request_id=request_id
            )
            process_failed = False
        except (RuntimeError, TimeoutError) as error:
            result = {"lengths": [0, 0, 0], "completed_callbacks": 0}
            process_failed = True
            failure = str(error)
        evidence = {
            "acceleration": rate["acceleration"],
            "publish_interval_seconds": rate["publish_interval"],
            "published_points": CALIBRATION_POINTS,
            "rendered_points": min(result.get("lengths", [0])),
            "completed_callbacks": result.get("completed_callbacks", 0),
            "observed_requests": result.get("observed_requests", 0),
            "active_requests": result.get("active_requests", 0),
            "max_active_requests": result.get("max_active_requests", 0),
            "overlap_events": result.get("overlap_events", 0),
            "progress_observed": observed_lengths == sorted(observed_lengths)
            and len(set(observed_lengths)) > 1,
            "publish_seconds": publishing_finished - started,
            "catchup_seconds": time.monotonic() - publishing_finished,
            "process_failed": process_failed,
            "failure": failure,
        }
        evidence["sustainable"] = calibration_sustainable(evidence)
        attempts.append(evidence)
        # Drain queued server/browser work and reset both trace state and time offset.
        client.publish("plotter/mppt_measurement/clear", "{}", qos=2).wait_for_publish()
        _, request_id = wait_for_lengths(webview, 0, timeout=30, start_request_id=request_id)
        if evidence["sustainable"]:
            return rate, attempts, request_id
    return None, attempts, request_id


def main():
    if platform.machine() not in ("x86_64", "AMD64"):
        raise SystemExit("memory results are supported only on native linux/amd64")
    run_dir = Path("/results") / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir.mkdir(parents=True)
    xvfb = subprocess.Popen(["Xvfb", ":99", "-screen", "0", "1280x800x24"])
    environment = dict(os.environ, DISPLAY=":99")
    webview = subprocess.Popen(
        ["python3", "benchmarks/webkit_view.py", "http://mppt-web:8053"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=environment,
    )
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect("broker")
    client.loop_start()
    fields = ["timestamp", "phase", "cycle", "points_published", "process_group", "pid", "rss_kib", "pss_kib", "private_kib"]
    metadata = {
        "implementation": "unfixed",
        "source_fingerprint": source_fingerprint(),
        "points_per_cycle": POINTS_PER_CYCLE,
        "measured_cycles": MEASURED_CYCLES,
        "rendering_valid": False,
        "processes_stable": False,
        "classification": "INCONCLUSIVE",
        "errors": [],
        "runtime_versions": runtime_versions(),
    }
    try:
        _, request_id = wait_for_lengths(webview, 0)
        rate, attempts, request_id = calibrate(client, webview)
        metadata["calibration"] = attempts
        if rate is None:
            metadata["errors"].append("neither 20x nor 10x was sustainable")
            return
        interval = rate["publish_interval"]
        metadata["selected_acceleration"] = rate["acceleration"]
        metadata["publish_interval_seconds"] = interval
        if os.environ.get("CALIBRATION_ONLY") == "1":
            metadata["classification"] = "INCONCLUSIVE"
            metadata["errors"].append("calibration-only smoke run")
            return
        with (run_dir / "telemetry.csv").open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for cycle in range(MEASURED_CYCLES + 1):
                for point in range(POINTS_PER_CYCLE):
                    result = client.publish("data/raw/mppt_measurement", json.dumps(payload_for(point)), qos=2)
                    result.wait_for_publish()
                    if point % 100 == 0:
                        collect_processes(writer, "publishing", cycle, point + 1)
                    time.sleep(interval)
                rendered, request_id = wait_for_lengths(
                    webview, POINTS_PER_CYCLE, start_request_id=request_id
                )
                metadata.setdefault("cycle_boundaries", []).append({
                    "cycle": cycle,
                    "before_clear_lengths": rendered["lengths"],
                    "completed_callbacks": rendered.get("completed_callbacks", 0),
                })
                client.publish("plotter/mppt_measurement/clear", "{}", qos=2).wait_for_publish()
                cleared, request_id = wait_for_lengths(
                    webview, 0, start_request_id=request_id
                )
                metadata["cycle_boundaries"][-1]["after_clear_lengths"] = cleared["lengths"]
                collect_processes(writer, "post-warmup" if cycle == 0 else "post-clear", cycle, POINTS_PER_CYCLE)
                if cycle < MEASURED_CYCLES:
                    time.sleep(20 * interval)
            time.sleep(60)
            collect_processes(writer, "final-idle", MEASURED_CYCLES, POINTS_PER_CYCLE)
        metadata["rendering_valid"] = all(
            boundary["before_clear_lengths"] == [POINTS_PER_CYCLE] * 3
            and boundary["after_clear_lengths"] == [0, 0, 0]
            for boundary in metadata["cycle_boundaries"]
        )
        metadata["processes_stable"] = webview.poll() is None
        from analyze_memory import analyze_telemetry
        report = analyze_telemetry(run_dir / "telemetry.csv", metadata)
        metadata.update(report)
    except (RuntimeError, TimeoutError, OSError, ValueError) as error:
        metadata["errors"].append(str(error))
    finally:
        (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print(json.dumps(metadata, indent=2), flush=True)
        client.loop_stop()
        webview.terminate()
        xvfb.terminate()


if __name__ == "__main__":
    main()
