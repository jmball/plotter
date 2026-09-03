"""Tests for deterministic MPPT workload and acceleration calibration."""

from benchmarks.run_mppt_memory import calibration_sustainable, payload_for


def test_payload_is_deterministic_and_within_required_ranges():
    first = payload_for(1234)

    assert first == payload_for(1234)
    voltage, current, timestamp, auxiliary = first["data"][0]
    assert 0.70 <= voltage <= 0.75
    assert -0.020 <= current <= -0.018
    assert timestamp == 1234.0
    assert auxiliary == 0.0
    assert first["pixel"] == {"area": 1.0, "device_label": "benchmark-device"}


def test_calibration_requires_render_progress_without_overlap():
    evidence = {
        "rendered_points": 200,
        "published_points": 200,
        "completed_callbacks": 20,
        "progress_observed": True,
        "catchup_seconds": 0.5,
        "process_failed": False,
        "active_requests": 0,
        "max_active_requests": 1,
        "observed_requests": 20,
        "overlap_events": 0,
    }

    assert calibration_sustainable(evidence)
    assert not calibration_sustainable(dict(evidence, overlap_events=3))
    assert not calibration_sustainable(dict(evidence, rendered_points=199))
    assert not calibration_sustainable(dict(evidence, progress_observed=False))
