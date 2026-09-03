#!/usr/bin/env python3
"""Analyze MPPT benchmark telemetry and classify post-clear memory growth."""

import argparse
import csv
import json
from pathlib import Path

MIB = 1024


def parse_smaps_rollup(text):
    """Return RSS, PSS, and private memory in KiB from smaps_rollup text."""
    values = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, remainder = line.split(":", 1)
        fields = remainder.split()
        if fields and fields[0].isdigit():
            values[key] = int(fields[0])
    return {
        "rss_kib": values.get("Rss", 0),
        "pss_kib": values.get("Pss", 0),
        "private_kib": values.get("Private_Clean", 0)
        + values.get("Private_Dirty", 0),
    }


def linear_fit(values):
    """Return least-squares slope and R-squared for equally spaced values."""
    if len(values) < 2:
        return 0.0, 0.0
    x_mean = (len(values) - 1) / 2
    y_mean = sum(values) / len(values)
    denominator = sum((x - x_mean) ** 2 for x in range(len(values)))
    slope = sum(
        (x - x_mean) * (y - y_mean) for x, y in enumerate(values)
    ) / denominator
    fitted = [y_mean + slope * (x - x_mean) for x in range(len(values))]
    total = sum((y - y_mean) ** 2 for y in values)
    residual = sum((y - estimate) ** 2 for y, estimate in zip(values, fitted))
    r_squared = 1.0 if total == 0 else 1 - residual / total
    return slope, r_squared


def classify(post_clear_pss_kib, rendering_valid=True, processes_stable=True):
    """Classify a completed five-cycle run using the plan's thresholds."""
    if not rendering_valid or not processes_stable or len(post_clear_pss_kib) != 5:
        return "INCONCLUSIVE"
    slope, _ = linear_fit(post_clear_pss_kib)
    baseline = post_clear_pss_kib[0]
    threshold = max(2 * MIB, 0.005 * baseline)
    increases = sum(b > a for a, b in zip(post_clear_pss_kib, post_clear_pss_kib[1:]))
    total_growth = post_clear_pss_kib[-1] - baseline
    if slope >= threshold and increases >= 4 and total_growth >= 10 * MIB:
        return "REPRODUCED"
    return "NOT_DETECTED"


def should_stop_early(post_clear_pss_kib, post_warmup_pss_kib):
    """Apply the stricter unmistakable-reproduction early-stop rule."""
    if len(post_clear_pss_kib) < 3:
        return False
    slope, r_squared = linear_fit(post_clear_pss_kib)
    threshold = max(10 * MIB, 0.02 * post_warmup_pss_kib)
    return (
        all(b > a for a, b in zip(post_clear_pss_kib, post_clear_pss_kib[1:]))
        and r_squared >= 0.98
        and slope >= threshold
        and post_clear_pss_kib[-1] - post_clear_pss_kib[0] >= 50 * MIB
    )


def analyze_telemetry(telemetry_path, metadata=None):
    """Aggregate WebKit post-clear samples and classify a benchmark run."""
    with Path(telemetry_path).open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_cycle = {}
    for row in rows:
        if row["process_group"] != "webkit" or row["phase"] != "post-clear":
            continue
        cycle = int(row["cycle"])
        by_cycle[cycle] = max(by_cycle.get(cycle, 0.0), float(row["pss_kib"]))
    post_clear = [by_cycle[cycle] for cycle in sorted(by_cycle) if cycle > 0]
    report = {
        "post_clear_webkit_pss_kib": post_clear,
        "post_clear_slope_kib_per_cycle": linear_fit(post_clear)[0],
        "post_clear_r_squared": linear_fit(post_clear)[1],
    }
    rendering_valid = (metadata or {}).get("rendering_valid", False)
    processes_stable = (metadata or {}).get("processes_stable", False)
    report["classification"] = classify(post_clear, rendering_valid, processes_stable)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("telemetry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with args.telemetry.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_cycle = {}
    for row in rows:
        if row["process_group"] == "webkit" and row["phase"] == "post-clear":
            cycle = int(row["cycle"])
            by_cycle[cycle] = max(by_cycle.get(cycle, 0.0), float(row["pss_kib"]))
    post_clear = [by_cycle[cycle] for cycle in sorted(by_cycle) if cycle > 0]
    slope, r_squared = linear_fit(post_clear)
    report = {
        "classification": classify(post_clear),
        "post_clear_pss_kib": post_clear,
        "slope_kib_per_cycle": slope,
        "r_squared": r_squared,
    }
    output = args.output or args.telemetry.with_suffix(".json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
