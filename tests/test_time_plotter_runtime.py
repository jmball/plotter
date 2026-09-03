"""Shared runtime expectations for bounded IT and VT plotters."""

import collections
import json
import queue
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from plotter import it_plotter, vt_plotter
from plotter.core.retention import BoundedTimeSeriesRetention


def mqtt_message(topic, payload):
    return SimpleNamespace(topic=topic, payload=json.dumps(payload).encode())


@pytest.mark.parametrize(
    "module,state_name,measurement_topic,clear_topic,invert_name",
    [
        (it_plotter, "graph4_latest", "data/raw/it_measurement", "plotter/it_measurement/clear", "invert_current"),
        (vt_plotter, "graph1_latest", "data/raw/vt_measurement", "plotter/vt_measurement/clear", "invert_voltage"),
    ],
)
def test_it_vt_mqtt_handlers_bound_and_clear_state(
    monkeypatch, module, state_name, measurement_topic, clear_topic, invert_name
):
    retention = BoundedTimeSeriesRetention(3, "sliding", 3, (1,), "test")
    monkeypatch.setattr(module, "retention", retention)
    monkeypatch.setattr(
        module, state_name,
        collections.deque(
            [{"msg": {"pixel": {"device_label": "-"}}, "data": np.empty((0, 3))}],
            maxlen=1,
        ),
    )
    monkeypatch.setattr(module, "graph_epoch", collections.deque([0], maxlen=1))
    monkeypatch.setattr(module, "graph_revision", collections.deque([0], maxlen=1))
    monkeypatch.setattr(module, "paused", collections.deque([False], maxlen=1))
    monkeypatch.setattr(module, invert_name, collections.deque([False], maxlen=1))

    messages = queue.Queue()
    threading.Thread(target=module.msg_handler, args=(messages,), daemon=True).start()
    for timestamp in range(4):
        messages.put(
            mqtt_message(
                measurement_topic,
                {
                    "data": [[0.72, -0.019, timestamp, 0.0]],
                    "pixel": {"area": 1.0, "device_label": "device-a"},
                },
            )
        )
        messages.join()

    data = getattr(module, state_name)[0]["data"]
    assert data.shape == (3, 3)
    np.testing.assert_array_equal(data[:, 2], [1, 2, 3])

    messages.put(mqtt_message(clear_topic, {}))
    messages.join()
    assert getattr(module, state_name)[0]["data"].shape == (0, 3)
    assert module.graph_epoch[0] == 1
