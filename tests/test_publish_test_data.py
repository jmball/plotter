"""Tests for manual MQTT test-data publisher options."""

import sys

from tools import publish_test_data


def test_kind_selects_matching_raw_measurement_topic(monkeypatch):
    published = []
    monkeypatch.setattr(
        publish_test_data.publish,
        "single",
        lambda topic, *args, **kwargs: published.append(topic),
    )
    monkeypatch.setattr(publish_test_data.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["publish_test_data.py", "--kind", "it", "--count", "1"])

    publish_test_data.main()

    assert published == ["data/raw/it_measurement"]


def test_mppt_remains_default_kind(monkeypatch):
    published = []
    monkeypatch.setattr(
        publish_test_data.publish,
        "single",
        lambda topic, *args, **kwargs: published.append(topic),
    )
    monkeypatch.setattr(publish_test_data.time, "sleep", lambda _: None)
    monkeypatch.setattr(sys, "argv", ["publish_test_data.py", "--count", "1"])

    publish_test_data.main()

    assert published == ["data/raw/mppt_measurement"]
