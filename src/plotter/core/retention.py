"""Bounded retention strategies shared by live time-series visualizations."""

from collections import deque

import numpy as np


def select_downsampled_rows(rows, max_points, signal_columns=(1, 2, 3)):
    """Select a chronological min/max envelope from a finite set of rows.

    This is a batch helper used for small-cap fallback cases. Long-running
    streams use :class:`BoundedMPPTRetention`'s bucketed envelope instead.
    """
    array = np.asarray(rows, dtype=float)
    if len(array) <= max_points:
        return array.copy()
    if max_points == 1:
        return array[-1:].copy()

    required = {0, len(array) - 1}
    for column in signal_columns:
        required.add(int(np.argmin(array[:, column])))
        required.add(int(np.argmax(array[:, column])))
    required = sorted(required)
    if len(required) > max_points:
        return array[required[: max_points - 1] + [len(array) - 1]].copy()

    selected = set(required)
    available = [index for index in range(len(array)) if index not in selected]
    needed = max_points - len(selected)
    if needed:
        positions = np.linspace(0, len(available) - 1, needed, dtype=int)
        selected.update(available[position] for position in positions)
    return array[sorted(selected)].copy()


class _EnvelopeBucket:
    """Keep extrema candidates for one or more plotted signals."""

    def __init__(self, signal_columns):
        self._candidates = {}
        self._signal_columns = signal_columns

    def add(self, row):
        """Add one row, retaining only per-signal minimums and maximums."""
        for column in self._signal_columns:
            for operation, better in (("min", np.less), ("max", np.greater)):
                key = (column, operation)
                existing = self._candidates.get(key)
                if existing is None or better(row[column], existing[column]):
                    self._candidates[key] = row.copy()

    def rows(self):
        """Return the bounded extrema candidates in this bucket."""
        return self._candidates.values()


class BoundedTimeSeriesRetention:
    """Store aligned rows using sliding or streaming-envelope retention.

    The downsampling strategy starts by retaining raw rows. Once the cap is
    reached it replaces them with time buckets covering the *whole* run. As
    the run grows, bucket widths double and adjacent buckets are merged. Thus
    no discarded raw history is kept, while old and new portions of the plot
    receive the same min/max-envelope treatment.
    """

    def __init__(
        self, max_points=5000, strategy="downsample", row_width=5,
        signal_columns=(1, 2, 3), diagnostic_label="time series",
    ):
        if not isinstance(max_points, int) or max_points <= 0:
            raise ValueError("max_points must be a positive integer")
        if strategy not in ("sliding", "downsample"):
            raise ValueError("strategy must be 'sliding' or 'downsample'")
        self.max_points = max_points
        self.strategy = strategy
        self.row_width = row_width
        self.signal_columns = tuple(signal_columns)
        self.diagnostic_label = diagnostic_label
        if not self.signal_columns or any(
            column <= 0 or column >= row_width for column in self.signal_columns
        ):
            raise ValueError("signal columns must be non-time row columns")
        self._rows = deque(maxlen=max_points if strategy == "sliding" else None)
        self.clear()

    def clear(self):
        """Release all retained rows and reset aggregation state."""
        self._rows.clear()
        self._first = None
        self._latest = None
        self._buckets = None
        self._origin = None
        self._bucket_width = None
        self._bucket_count = max(
            1, (self.max_points - 2) // (2 * len(self.signal_columns))
        )

    def _start_envelope(self):
        raw = list(self._rows)
        print(
            "{} downsampling: compacting {} plotted samples into {} time buckets "
            "(at most {} envelope samples).".format(
                self.diagnostic_label,
                len(raw), self._bucket_count,
                2 + (2 * len(self.signal_columns) * self._bucket_count),
            )
        )
        self._first = raw[0]
        self._latest = raw[-1]
        self._origin = self._first[0]
        span = self._latest[0] - self._origin
        self._bucket_width = max(span / self._bucket_count, np.finfo(float).eps)
        self._buckets = [_EnvelopeBucket(self.signal_columns) for _ in range(self._bucket_count)]
        for row in raw[1:-1]:
            self._add_history(row)
        self._rows.clear()

    def _coarsen(self):
        """Double bucket width and merge adjacent extrema envelopes."""
        before_count = len(self.array())
        merged = [_EnvelopeBucket(self.signal_columns) for _ in range(self._bucket_count)]
        for index, bucket in enumerate(self._buckets):
            target = merged[index // 2]
            for row in bucket.rows():
                target.add(row)
        self._buckets = merged
        self._bucket_width *= 2
        print(
            "{} downsampling: compacting {} plotted samples by merging time "
            "buckets; {} envelope samples remain.".format(
                self.diagnostic_label, before_count, len(self.array())
            )
        )

    def _ensure_span(self, timestamp):
        while int((timestamp - self._origin) / self._bucket_width) >= self._bucket_count:
            self._coarsen()

    def _add_history(self, row):
        index = int((row[0] - self._origin) / self._bucket_width)
        index = min(max(index, 0), self._bucket_count - 1)
        self._buckets[index].add(row)

    def append(self, row):
        """Append one aligned row and return the bounded array snapshot."""
        values = np.asarray(row, dtype=float)
        if values.shape != (self.row_width,):
            raise ValueError("time-series rows must contain {} values".format(self.row_width))
        if self.strategy == "sliding":
            self._rows.append(values.copy())
        elif self._buckets is None:
            self._rows.append(values.copy())
            if len(self._rows) > self.max_points:
                self._start_envelope()
        else:
            self._ensure_span(values[0])
            self._add_history(self._latest)
            self._latest = values.copy()
        return self.array()

    def array(self):
        """Return a copy of retained rows; no hidden raw history is exposed."""
        if self.strategy == "sliding" or self._buckets is None:
            if not self._rows:
                return np.empty((0, self.row_width), dtype=float)
            return np.asarray(list(self._rows), dtype=float).copy()

        candidates = [self._first, self._latest]
        for bucket in self._buckets:
            candidates.extend(bucket.rows())
        unique = {row.tobytes(): row for row in candidates}
        array = np.asarray(sorted(unique.values(), key=lambda row: row[0]), dtype=float)
        if len(array) > self.max_points:
            return select_downsampled_rows(array, self.max_points, self.signal_columns)
        return array.copy()

    def __len__(self):
        return len(self.array())

    @property
    def is_raw(self):
        """Whether every retained row is still an unaggregated input row."""
        return self.strategy == "sliding" or self._buckets is None


class BoundedMPPTRetention(BoundedTimeSeriesRetention):
    """Compatibility wrapper for MPPT's three-signal retention settings."""

    def __init__(self, max_points=5000, strategy="downsample"):
        super().__init__(
            max_points=max_points,
            strategy=strategy,
            row_width=5,
            signal_columns=(1, 2, 3),
            diagnostic_label="MPPT",
        )
