"""Tests for MPPT benchmark memory parsing and classification."""

from benchmarks.analyze_memory import analyze_telemetry, classify, linear_fit, parse_smaps_rollup
from benchmarks.analyze_memory import should_stop_early


def test_parse_smaps_rollup_sums_private_memory():
    result = parse_smaps_rollup(
        "Rss: 120 kB\nPss: 80 kB\nPrivate_Clean: 7 kB\nPrivate_Dirty: 11 kB\n"
    )

    assert result == {"rss_kib": 120, "pss_kib": 80, "private_kib": 18}


def test_linear_fit_reports_slope_and_r_squared():
    slope, r_squared = linear_fit([100, 110, 120, 130, 140])

    assert slope == 10
    assert r_squared == 1


def test_classification_results():
    assert classify([100_000, 103_000, 106_000, 109_000, 112_000]) == "REPRODUCED"
    assert classify([100_000, 101_000, 101_100, 101_050, 101_100]) == "NOT_DETECTED"
    assert classify([100_000] * 5, rendering_valid=False) == "INCONCLUSIVE"


def test_early_stop_requires_three_consistently_growing_cycles():
    assert not should_stop_early([100_000, 120_000], 100_000)
    assert should_stop_early([100_000, 130_000, 160_000], 100_000)
    assert not should_stop_early([100_000, 140_000, 130_000], 100_000)


def test_telemetry_aggregates_multiple_webkit_processes_per_cycle(tmp_path):
    telemetry = tmp_path / "telemetry.csv"
    telemetry.write_text(
        "process_group,phase,cycle,pss_kib\n"
        "webkit,post-clear,1,100\n"
        "webkit,post-clear,1,120\n"
        "webkit,post-clear,2,130\n"
        "webkit,post-clear,3,140\n"
        "webkit,post-clear,4,150\n"
        "webkit,post-clear,5,160\n"
    )
    report = analyze_telemetry(
        telemetry,
        {"rendering_valid": True, "processes_stable": True},
    )

    assert report["post_clear_webkit_pss_kib"] == [120.0, 130.0, 140.0, 150.0, 160.0]
