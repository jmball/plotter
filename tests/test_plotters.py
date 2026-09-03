"""Tests for measurement processing and module dispatch."""

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from plotter import __main__
from plotter import it_plotter
from plotter import iv_plotter
from plotter import mppt_plotter
from plotter import vt_plotter


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


def test_mppt_cli_benchmark_control_defaults():
    args = mppt_plotter.parse_args([])

    assert args.update_interval_ms == 500
    assert args.dashport == 8053
    assert args.max_points == 5000
    assert args.point_limit_strategy == "downsample"


def test_mppt_cli_benchmark_control_overrides():
    args = mppt_plotter.parse_args(
        [
            "--update-interval-ms", "25", "--dashport", "18053",
            "--max-points", "250", "--point-limit-strategy", "sliding",
        ]
    )

    assert args.update_interval_ms == 25
    assert args.dashport == 18053
    assert args.max_points == 250
    assert args.point_limit_strategy == "sliding"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--update-interval-ms", "0"],
        ["--update-interval-ms", "-1"],
        ["--dashport", "0"],
        ["--dashport", "65536"],
        ["--max-points", "0"],
        ["--point-limit-strategy", "invalid"],
    ],
)
def test_mppt_cli_rejects_invalid_benchmark_controls(arguments):
    with pytest.raises(SystemExit):
        mppt_plotter.parse_args(arguments)


def test_mppt_layout_applies_update_interval():
    layout = mppt_plotter.create_layout(25)
    interval = layout.children.children[1]

    assert interval.id == "interval-component"
    assert interval.interval == 25


def test_mppt_server_applies_interval_and_port(monkeypatch):
    run_options = {}
    monkeypatch.setattr(
        mppt_plotter.app,
        "run",
        lambda **options: run_options.update(options),
    )
    args = mppt_plotter.parse_args(
        [
            "--dashhost",
            "127.0.0.1",
            "--dashport",
            "18053",
            "--update-interval-ms",
            "25",
            "--max-points",
            "250",
            "--point-limit-strategy",
            "sliding",
        ]
    )

    mppt_plotter.run_dash(args)

    interval = mppt_plotter.app.layout.children.children[1]
    assert interval.interval == 25
    assert mppt_plotter.retention.max_points == 250
    assert mppt_plotter.retention.strategy == "sliding"
    assert run_options == {"host": "127.0.0.1", "port": 18053, "debug": False}


def test_mppt_callback_does_not_round_trip_browser_figure():
    callback = mppt_plotter.app.callback_map["..g3.figure.."]

    assert callback["state"] == []
    assert callback["inputs"] == [
        {"id": "interval-component", "property": "n_intervals"}
    ]


def test_mppt_callback_skips_idle_intervals(monkeypatch):
    monkeypatch.setattr(mppt_plotter, "_browser_revision", mppt_plotter.graph_revision[0])

    assert mppt_plotter.update_graph_live(1) == [mppt_plotter.dash.no_update]


@pytest.mark.parametrize(
    "module, graph_id, port",
    [(it_plotter, "g4", 8054), (vt_plotter, "g1", 8051)],
)
def test_it_vt_bounded_plotter_defaults_and_incremental_callbacks(module, graph_id, port):
    args = module.parse_args([])
    callback = module.app.callback_map["..{}.figure..".format(graph_id)]

    assert args.update_interval_ms == 500
    assert args.dashport == port
    assert args.max_points == 5000
    assert args.point_limit_strategy == "downsample"
    assert callback["state"] == []


@pytest.mark.parametrize("module", [it_plotter, vt_plotter])
def test_it_vt_bounded_plotter_rejects_invalid_controls(module):
    with pytest.raises(SystemExit):
        module.parse_args(["--max-points", "0"])
    with pytest.raises(SystemExit):
        module.parse_args(["--dashport", "0"])
