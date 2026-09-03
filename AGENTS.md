# AGENTS.md

## Project overview

This repository provides five small, independent live-data dashboards. Each
process subscribes to measurement messages from an MQTT broker, keeps the
latest data in memory, and serves a Plotly graph through Dash.

The package uses a `src/` layout and is configured through `pyproject.toml`.

## Repository map

- `src/plotter/iv_plotter.py`: current-voltage scans; Dash port 8052.
- `src/plotter/mppt_plotter.py`: MPPT current, power, and voltage over time;
  Dash port 8053.
- `src/plotter/it_plotter.py`: current density over time; Dash port 8054.
- `src/plotter/vt_plotter.py`: voltage over time; Dash port 8051.
- `src/plotter/eqe_plotter.py`: EQE by wavelength; Dash port 8055.
- `src/plotter/assets/stylesheet.css`: stylesheet automatically discovered by
  Dash.
- `data/systemd/*.service`: user-service templates installed by the package.
- `pyproject.toml`: dependencies, package data, console scripts, and systemd data
  files.
- `tests/`: automated pytest tests.
- `tools/publish_test_data.py`: a configurable manual MQTT data generator.

## Setup and common commands

Use Python 3.9-compatible syntax unless the supported versions in `pyproject.toml`
are deliberately changed.

```bash
uv sync --group test
```

Run an installed dashboard with an MQTT broker hostname or IP:

```bash
iv-plotter --mqtthost 127.0.0.1 --dashhost 0.0.0.0
mppt-plotter --mqtthost 127.0.0.1 --dashhost 0.0.0.0
it-plotter --mqtthost 127.0.0.1 --dashhost 0.0.0.0
vt-plotter --mqtthost 127.0.0.1 --dashhost 0.0.0.0
eqe-plotter --mqtthost 127.0.0.1 --dashhost 0.0.0.0
```

There is currently no configured formatter or linter. Run the automated tests
and validate Python syntax with:

```bash
uv run pytest
uv run python -m compileall -q src tests tools
```

For behavior changes, add focused tests for pure processing or figure-formatting
functions where practical. Broker integration checks require a reachable MQTT
broker and should be described in the handoff. `tools/publish_test_data.py`
publishes messages to the configured/default broker and is never run as part of
the automated test suite.

## Architecture and data flow

Each dashboard follows the same pattern:

1. `main()` parses `--mqtthost` and `--dashhost`.
2. A Paho MQTT client subscribes to its `data/raw/...` topic and selected
   control topics under `plotter/#`.
3. The MQTT callback places messages on a `queue.Queue`; a daemon handler
   thread parses JSON and updates module-level state.
4. Single-item `collections.deque` objects hold the latest plot data and flags
   shared with the Dash callback.
5. A 500 ms Dash interval reads that state and updates the Plotly figure.

Preserve this separation: keep MQTT callbacks short, perform message work in
the handler thread, and avoid blocking the Dash callback. Keep NumPy array
column shapes consistent with the corresponding initialized `np.empty` array
and figure traces.

The dashboards consume payload fields such as `data`, `pixel.area`,
`pixel.dark_area`, and `pixel.device_label`. EQE additionally depends on
calibration and measurement configuration messages. Treat MQTT topic names and
payload shapes as external interfaces; coordinate changes across every affected
plotter and producer.

## Change guidelines

- Keep changes localized to the relevant dashboard, but apply shared bug fixes
  consistently when the duplicated implementations are affected.
- Preserve each console-script name, MQTT subscription, Dash port, and matching
  systemd unit unless the change explicitly requires an interface change.
- When adding a dashboard, update `pyproject.toml` entry points, package/data settings
  as needed, and add the corresponding systemd service.
- Follow the existing NumPy/SciPy and Plotly conventions. Use descriptive
  docstrings for processing and formatting functions.
- Do not silently swallow newly introduced errors. Existing handlers use broad
  `except` blocks, but new code should catch expected exceptions narrowly and
  log enough context to diagnose malformed messages without killing the worker.
- Keep network connections and server startup inside `main()` so modules remain
  importable for tests.
- Launch through `python3 -m plotter <eqe|it|iv|mppt|vt>` or the console scripts
  declared in `pyproject.toml`.

## Packaging and service checks

If dependencies, entry points, assets, or services change, verify both the
source checkout and a built package:

```bash
uv build
```

Inspect the wheel contents when changing `src/plotter/assets` or `data/systemd`.
Systemd templates use the instance value (`%i`) as the MQTT host and expect the
console scripts under `/usr/bin`; keep service and CLI changes synchronized.
