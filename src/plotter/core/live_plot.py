"""Dash Patch helpers shared by bounded live time-series plots."""

import dash


def time_series_patch(data, title, signal_columns, append, xaxes, yaxes):
    """Build a bounded Patch for aligned time-series rows.

    ``append`` is only safe while retained history is unchanged.  Callers use
    full bounded assignments after compaction, eviction, or clear.
    """
    patch = dash.Patch()
    if append:
        row = data[-1]
        for trace_index, column in enumerate(signal_columns):
            patch["data"][trace_index]["x"].append(float(row[0]))
            patch["data"][trace_index]["y"].append(float(row[column]))
    else:
        for trace_index, column in enumerate(signal_columns):
            patch["data"][trace_index]["x"] = data[:, 0].tolist()
            patch["data"][trace_index]["y"] = data[:, column].tolist()
    if len(data):
        xrange = [float(data[:, 0].min()), float(data[:, 0].max())]
        for axis in xaxes:
            patch["layout"][axis]["range"] = xrange
        for axis, column in zip(yaxes, signal_columns):
            patch["layout"][axis]["range"] = [
                float(data[:, column].min()), float(data[:, column].max())
            ]
    patch["layout"]["annotations"][0]["text"] = title
    return patch
