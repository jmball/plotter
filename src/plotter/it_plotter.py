#!/usr/bin/env python
"""Plot data obtained from MQTT broker using Dash."""

import collections
import logging
import json
import queue
import threading
import uuid

import dash
from dash import dcc
from dash import html
import numpy as np
import paho.mqtt.client as mqtt
import plotly
import plotly.subplots
import plotly.graph_objs as go
import argparse
from flask import Flask
from plotter.core.cli import positive_integer, valid_port
from plotter.core.live_plot import time_series_patch
from plotter.core.retention import BoundedTimeSeriesRetention
from plotter.core.processing import process_ivt

DEFAULT_MAX_POINTS = 5000
DEFAULT_POINT_LIMIT_STRATEGY = "downsample"


def format_figure_1(data, fig, title="-"):
    """Format figure type 1.

    Parameters
    ----------
    data : array
        Array of data.
    fig : dict
        Dictionary representation of Plotly figure.
    title : str
        Title of plot.

    Returns
    -------
    fig : dict
        Dictionary representation of Plotly figure.
    """
    if len(data) == 0:
        # if request to clear has been issued, return cleared figure
        fig["data"][0]["x"] = []
        fig["data"][0]["y"] = []
        return fig
    else:
        # add data to fig
        fig["data"][0]["x"] = data[:, 0]
        fig["data"][0]["y"] = data[:, 1]

        # update ranges
        fig["layout"]["xaxis"]["range"] = [min(data[:, 0]), max(data[:, 0])]
        fig["layout"]["yaxis"]["range"] = [min(data[:, 1]), max(data[:, 1])]

        # update title
        fig["layout"]["annotations"][0]["text"] = title

        return fig


def format_figure_4(data, fig, title="-"):
    """Format figure type 4.

    Parameters
    ----------
    data : array
        Array of data.
    fig : plotly.graph_objs.Figure
        Plotly figure.
    title : str
        Title of plot.

    Returns
    -------
    fig : plotly.graph_objs.Figure
        Updated plotly figure.
    """
    return format_figure_1(data, fig, title)


# create thread-safe containers for storing latest data and plot info
graph4_latest = collections.deque(maxlen=1)
graph_epoch = collections.deque([0], maxlen=1)
graph_revision = collections.deque([0], maxlen=1)
retention = BoundedTimeSeriesRetention(
    DEFAULT_MAX_POINTS, DEFAULT_POINT_LIMIT_STRATEGY, 3, (1,), "IT"
)
_browser_epoch = -1
_browser_length = 0
_browser_revision = -1
paused = collections.deque(maxlen=1)
invert_current = collections.deque(maxlen=1)
invert_current.append(False)
paused.append(False)

# initialise plot info/data queues
graph4_latest.append(
    {"msg": {"pixel": {"device_label": "-"}}, "data": np.empty((0, 3))}
)

# initial figure properties
fig4 = plotly.subplots.make_subplots(subplot_titles=["-"])
fig4.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="j"))
fig4.update_xaxes(
    title="time (s)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig4.update_yaxes(
    title="J (mA/cm^2)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig4.update_layout(
    font={"size": 16}, margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)"
)
server = Flask(__name__)
app = dash.Dash(__name__, server=server)

log = logging.getLogger("werkzeug")
log.disabled = True

def create_layout(update_interval_ms=500):
    """Create the IT layout with the requested browser refresh interval."""
    return html.Div(
    html.Div(
        [
            dcc.Graph(id="g4", figure=fig4, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=update_interval_ms, n_intervals=0),
        ],
    ),
    )


app.layout = create_layout()


@app.callback(
    [dash.dependencies.Output("g4", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
)
def update_graph_live(n):
    """Update graph."""
    global _browser_epoch, _browser_length, _browser_revision
    if paused[0] is False:
        g4_latest = graph4_latest[0]
        epoch = graph_epoch[0]
        revision = graph_revision[0]
        if revision == _browser_revision:
            return [dash.no_update]
        data = g4_latest["data"]
        append = (
            epoch == _browser_epoch
            and retention.is_raw
            and len(data) == _browser_length + 1
            and _browser_length < retention.max_points
        )
        patch = time_series_patch(
            data, g4_latest["msg"]["pixel"].get("device_label", "-"),
            (1,), append, ("xaxis",), ("yaxis",),
        )
        if graph_revision[0] != revision:
            return [dash.no_update]
        _browser_epoch = epoch
        _browser_length = len(data)
        _browser_revision = revision
        return [patch]
    return [dash.no_update]


def on_message(mqttc, obj, msg, msg_queue):
    """Act on an MQTT message."""
    msg_queue.put_nowait(msg)


def msg_handler(msg_queue):
    """Handle incoming MQTT messages."""
    # init empty dicts for caching latest data
    live_device = None  # keep track of which device to plot

    while True:
        msg = msg_queue.get()

        try:
            payload = json.loads(msg.payload.decode())

            if msg.topic == "plotter/it_measurement/clear":
                old_msg = graph4_latest[0]["msg"]
                retention.clear()
                graph_epoch.append(graph_epoch[0] + 1)
                graph_revision.append(graph_revision[0] + 1)
                graph4_latest.append({"msg": old_msg, "data": retention.array()})
            elif msg.topic == "plotter/live_device":
                live_device = payload
                old_msg = graph4_latest[0]["msg"]
                retention.clear()
                graph_epoch.append(graph_epoch[0] + 1)
                graph_revision.append(graph_revision[0] + 1)
                graph4_latest.append({"msg": old_msg, "data": retention.array()})
            elif msg.topic == "data/raw/it_measurement":
                pdata = process_ivt(payload, "it_measurement")
                if (live_device is None) or (payload["pixel"]["device_label"] == live_device):
                    t = pdata[0][2]
                    j = pdata[0][4]

                    if invert_current[0] is True:
                        j = -1 * j

                    if len(retention) == 0:
                        t_offset = t
                    else:
                        t_offset = graph4_latest[0]["data"][0, -1]
                    data = retention.append([t - t_offset, j, t])
                    graph4_latest.append({"msg": payload, "data": data})
                    graph_revision.append(graph_revision[0] + 1)
            elif msg.topic == "plotter/pause":
                paused.append(payload)
            elif msg.topic == "plotter/invert_current":
                invert_current.append(payload)
        except:
            pass

        msg_queue.task_done()


def parse_args(argv=None):
    """Parse IT plotter command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mqtthost",
        type=str,
        default="127.0.0.1",
        const="127.0.0.1",
        nargs='?',
        help="IP address or hostname for MQTT broker.",
    )
    parser.add_argument(
        "--dashhost",
        type=str,
        default="0.0.0.0",
        help="Where dash server should listen.",
    )

    parser.add_argument("--update-interval-ms", type=positive_integer, default=500)
    parser.add_argument("--dashport", type=valid_port, default=8054)
    parser.add_argument("--max-points", type=positive_integer, default=DEFAULT_MAX_POINTS)
    parser.add_argument(
        "--point-limit-strategy", choices=("sliding", "downsample"),
        default=DEFAULT_POINT_LIMIT_STRATEGY,
    )
    return parser.parse_args(argv)


def configure_runtime(args):
    """Install bounded IT retention before MQTT processing begins."""
    global retention
    retention = BoundedTimeSeriesRetention(
        args.max_points, args.point_limit_strategy, 3, (1,), "IT"
    )


def run_dash(args):
    """Configure and start Dash using parsed IT settings."""
    configure_runtime(args)
    app.layout = create_layout(args.update_interval_ms)
    app.run(host=args.dashhost, port=args.dashport, debug=False)


def main():
    args = parse_args()
    configure_runtime(args)

    # create mqtt client id
    client_id = f"plotter-{uuid.uuid4().hex}"

    # queue for storing incoming messages
    msg_queue = queue.Queue()

    # start the msg queue thread
    threading.Thread(target=msg_handler, args=(msg_queue,), daemon=True).start()

    mqtt_analyser = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )
    mqtt_analyser.on_message = lambda mqttc, obj, msg: on_message(mqttc, obj, msg, msg_queue)

    # connect MQTT client to broker
    mqtt_analyser.connect(args.mqtthost)

    # subscribe to data and request topics
    mqtt_analyser.subscribe("data/raw/it_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/#", qos=2)

    # start the mqtt client loop in its own thread to handle connection retries
    threading.Thread(target=mqtt_analyser.loop_forever, daemon=True).start()

    # start dash server
    run_dash(args)

if __name__ == "__main__":
    main()
