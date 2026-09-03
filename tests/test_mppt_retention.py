"""Tests for bounded MPPT visualization retention."""

import numpy as np
import pytest

from plotter.core.retention import (
    BoundedMPPTRetention,
    BoundedTimeSeriesRetention,
    select_downsampled_rows,
)


def rows(count):
    return np.asarray([[i, i, i * 2, -i, i] for i in range(count)], dtype=float)


@pytest.mark.parametrize("strategy", ["sliding", "downsample"])
def test_points_below_cap_are_unchanged(strategy):
    retention = BoundedMPPTRetention(10, strategy)
    for row in rows(4):
        retention.append(row)
    np.testing.assert_array_equal(retention.array(), rows(4))


def test_sliding_retains_newest_aligned_rows():
    retention = BoundedMPPTRetention(3, "sliding")
    for row in rows(6):
        retention.append(row)
    np.testing.assert_array_equal(retention.array(), rows(6)[-3:])


def test_downsampling_preserves_first_latest_and_extrema():
    source = rows(20)
    source[7, 1] = -100
    source[13, 2] = 100
    source[3, 3] = -200
    result = select_downsampled_rows(source, 8)

    assert len(result) <= 8
    assert result[0, 0] == source[0, 0]
    assert result[-1, 0] == source[-1, 0]
    for column in (1, 2, 3):
        assert source[np.argmin(source[:, column]), 0] in result[:, 0]
        assert source[np.argmax(source[:, column]), 0] in result[:, 0]
    assert np.all(np.diff(result[:, 0]) >= 0)


def test_repeated_compaction_has_no_hidden_history_and_clear_resets():
    retention = BoundedMPPTRetention(5, "downsample")
    for row in rows(1000):
        retention.append(row)
        assert len(retention) <= 5
    retention.clear()
    assert len(retention) == 0
    assert retention.array().shape == (0, 5)


def test_streaming_downsampling_covers_the_full_elapsed_run():
    """Repeated compaction must not leave raw early data and sparse late data."""
    retention = BoundedMPPTRetention(100, "downsample")
    for row in rows(2000):
        retention.append(row)

    result = retention.array()
    assert len(result) <= 100
    assert result[0, 0] == 0
    assert result[-1, 0] == 1999
    # Each quarter of the run is represented, rather than just a dense prefix.
    for start in range(0, 2000, 500):
        assert np.any((result[:, 0] >= start) & (result[:, 0] < start + 500))


def test_downsampling_reports_initial_compaction_size(capsys):
    retention = BoundedMPPTRetention(10, "downsample")
    for row in rows(11):
        retention.append(row)

    assert "compacting 11 plotted samples" in capsys.readouterr().out


def test_downsampling_reports_each_bucket_merge(capsys):
    retention = BoundedMPPTRetention(10, "downsample")
    for row in rows(12):
        retention.append(row)

    assert "merging time buckets" in capsys.readouterr().out


def test_streaming_downsampling_retains_extrema_after_bucket_merges():
    retention = BoundedMPPTRetention(20, "downsample")
    source = rows(500)
    source[80, 1] = -1000
    source[230, 2] = 1000
    source[420, 3] = -1000
    for row in source:
        retention.append(row)

    result = retention.array()
    for timestamp in (80, 230, 420):
        assert timestamp in result[:, 0]


def test_invalid_retention_configuration_is_rejected():
    with pytest.raises(ValueError):
        BoundedMPPTRetention(0)
    with pytest.raises(ValueError):
        BoundedMPPTRetention(2, "unknown")


def test_generic_single_signal_retention_bounds_it_and_vt_row_shape():
    retention = BoundedTimeSeriesRetention(4, "sliding", 3, (1,), "test")
    for row in [[index, index * 10, 100 + index] for index in range(6)]:
        retention.append(row)

    np.testing.assert_array_equal(
        retention.array(),
        [[2, 20, 102], [3, 30, 103], [4, 40, 104], [5, 50, 105]],
    )
