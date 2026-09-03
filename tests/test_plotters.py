"""Tests for measurement processing and module dispatch."""

import sys
from types import SimpleNamespace

import numpy as np

from plotter import __main__
from plotter import it_plotter
from plotter import iv_plotter


def test_process_iv_calculates_light_current_density():
    payload = {
        "data": [[0.5, 0.002]],
        "pixel": {"area": 2.0, "dark_area": 4.0},
        "sweep": "light",
    }

    data = iv_plotter.process_iv(payload)

    np.testing.assert_allclose(data, [[0.5, 0.002, 1.0, 0.5]])


def test_process_iv_uses_dark_area_for_dark_sweep():
    payload = {
        "data": [[0.5, 0.002]],
        "pixel": {"area": 2.0, "dark_area": 4.0},
        "sweep": "dark",
    }

    data = iv_plotter.process_iv(payload)

    np.testing.assert_allclose(data, [[0.5, 0.002, 0.5, 0.25]])


def test_process_ivt_appends_current_density_and_power():
    payload = {
        "data": [[0.5, 0.002, 10.0]],
        "pixel": {"area": 2.0},
    }

    data = it_plotter.process_ivt(payload, "it_measurement")

    assert data == [(0.5, 0.002, 10.0, 1.0, 0.5)]


def test_dispatches_remaining_arguments_to_selected_plotter(monkeypatch):
    dispatched = {}
    selected_module = SimpleNamespace(
        main=lambda: dispatched.update(argv=sys.argv.copy())
    )
    imported = []

    def import_module(name):
        imported.append(name)
        return selected_module

    monkeypatch.setattr(
        sys, "argv", ["plotter", "iv", "--mqtthost", "broker.example"]
    )
    monkeypatch.setattr(__main__.importlib, "import_module", import_module)

    __main__.main()

    assert imported == ["plotter.iv_plotter"]
    assert dispatched["argv"] == ["iv-plotter", "--mqtthost", "broker.example"]
