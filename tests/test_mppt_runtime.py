"""Runtime-state tests for the bounded MPPT dashboard."""

import collections
import json
import queue
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from plotter import mppt_plotter
from plotter.core.retention import BoundedMPPTRetention


@pytest.fixture
def mppt_state(monkeypatch):
    """Install isolated module state for MQTT and Dash callback tests."""
    retention = BoundedMPPTRetention(10, "downsample")
    monkeypatch.setattr(mppt_plotter, "retention", retention)
    monkeypatch.setattr(
        mppt_plotter,
        "graph3_latest",
        collections.deque(
            [{"msg": {"pixel": {"device_label": "-"}}, "data": np.empty((0, 5))}],
            maxlen=1,
        ),
    )
    monkeypatch.setattr(mppt_plotter, "graph_epoch", collections.deque([0], maxlen=1))
    monkeypatch.setattr(mppt_plotter, "graph_revision", collections.deque([0], maxlen=1))
    monkeypatch.setattr(mppt_plotter, "paused", collections.deque([False], maxlen=1))
    monkeypatch.setattr(mppt_plotter, "invert_voltage", collections.deque([False], maxlen=1))
    monkeypatch.setattr(mppt_plotter, "_browser_epoch", -1)
    monkeypatch.setattr(mppt_plotter, "_browser_length", 0)
    monkeypatch.setattr(mppt_plotter, "_browser_revision", -1)
    return retention


def message(topic, payload):
    """Create the subset of a Paho message consumed by the handler."""
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())


def send_message(messages, topic, payload):
    messages.put(message(topic, payload))
    messages.join()


def measurement(timestamp, label="device-a"):
    return {
        "data": [[0.72, -0.019, timestamp, 0.0]],
        "pixel": {"area": 1.0, "device_label": label},
    }


def patch_operations(response):
    return response[0].to_plotly_json()["operations"]


def test_mqtt_handler_decodes_measurement_and_resets_on_clear(mppt_state):
    messages = queue.Queue()
    threading.Thread(target=mppt_plotter.msg_handler, args=(messages,), daemon=True).start()

    send_message(messages, "data/raw/mppt_measurement", measurement(100.0))
    data = mppt_plotter.graph3_latest[0]["data"]
    np.testing.assert_allclose(data, [[0.0, 19.0, 13.68, 0.72, 100.0]])
    assert mppt_plotter.graph_revision[0] == 1

    send_message(messages, "plotter/mppt_measurement/clear", {})
    assert mppt_plotter.graph3_latest[0]["data"].shape == (0, 5)
    assert mppt_plotter.graph_epoch[0] == 1
    assert mppt_plotter.graph_revision[0] == 2


def test_mqtt_handler_applies_live_device_filter_and_inversion(mppt_state):
    messages = queue.Queue()
    threading.Thread(target=mppt_plotter.msg_handler, args=(messages,), daemon=True).start()

    send_message(messages, "plotter/live_device", "device-a")
    send_message(messages, "data/raw/mppt_measurement", measurement(100.0, "device-b"))
    assert len(mppt_plotter.retention) == 0

    send_message(messages, "plotter/invert_voltage", True)
    send_message(messages, "data/raw/mppt_measurement", measurement(101.0, "device-a"))
    data = mppt_plotter.graph3_latest[0]["data"]
    assert data[0, 3] == -0.72


def test_callback_uses_append_patch_then_skips_idle_interval(mppt_state):
    data = mppt_state.append([0.0, 1.0, 2.0, 3.0, 100.0])
    mppt_plotter.graph3_latest.append(
        {"msg": {"pixel": {"device_label": "device-a"}}, "data": data}
    )
    mppt_plotter.graph_revision.append(1)
    mppt_plotter._browser_epoch = 0

    response = mppt_plotter.update_graph_live(1)
    operations = patch_operations(response)
    assert sum(operation["operation"] == "Append" for operation in operations) == 6
    assert mppt_plotter.update_graph_live(2) == [mppt_plotter.dash.no_update]


def test_callback_replaces_bounded_trace_after_downsampling(mppt_state):
    for index in range(20):
        data = mppt_state.append([index, index, index * 2, -index, index])
    mppt_plotter.graph3_latest.append(
        {"msg": {"pixel": {"device_label": "device-a"}}, "data": data}
    )
    mppt_plotter.graph_revision.append(1)

    operations = patch_operations(mppt_plotter.update_graph_live(1))
    trace_values = [
        operation["params"]["value"]
        for operation in operations
        if operation["location"][:2] == ["data", 0]
        or operation["location"][:2] == ["data", 1]
        or operation["location"][:2] == ["data", 2]
    ]
    assert trace_values
    assert all(len(values) <= mppt_state.max_points for values in trace_values)
    assert all(operation["operation"] != "Append" for operation in operations)


def test_callback_clear_replaces_all_browser_trace_arrays(mppt_state):
    mppt_plotter.graph_epoch.append(1)
    mppt_plotter.graph_revision.append(1)

    operations = patch_operations(mppt_plotter.update_graph_live(1))
    cleared = [
        operation
        for operation in operations
        if operation["location"][-1] in ("x", "y") and operation["params"]["value"] == []
    ]
    assert len(cleared) == 6


def test_callback_discards_snapshot_changed_during_formatting(mppt_state):
    class RevisionChangingPixel(dict):
        def get(self, *args, **kwargs):
            mppt_plotter.graph_revision.append(mppt_plotter.graph_revision[0] + 1)
            return super().get(*args, **kwargs)

    mppt_plotter.graph3_latest.append(
        {"msg": {"pixel": RevisionChangingPixel(device_label="device-a")}, "data": np.empty((0, 5))}
    )
    mppt_plotter.graph_revision.append(1)

    assert mppt_plotter.update_graph_live(1) == [mppt_plotter.dash.no_update]
