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
from plotter.mppt_retention import BoundedMPPTRetention

DEFAULT_MAX_POINTS = 5000
DEFAULT_POINT_LIMIT_STRATEGY = "downsample"

def format_figure_3(data, fig, title="-"):
    """Format figure type 3.

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
    if len(data) == 0:
        # if request to clear has been issued, return cleared figure
        fig["data"][0]["x"] = []
        fig["data"][0]["y"] = []
        fig["data"][1]["x"] = []
        fig["data"][1]["y"] = []
        fig["data"][2]["x"] = []
        fig["data"][2]["y"] = []
        return fig
    else:
        # add data to fig
        fig["data"][0]["x"] = data[:, 0]
        fig["data"][0]["y"] = data[:, 1]
        fig["data"][1]["x"] = data[:, 0]
        fig["data"][1]["y"] = data[:, 2]
        fig["data"][2]["x"] = data[:, 0]
        fig["data"][2]["y"] = data[:, 3]

        # # update ranges
        xrange = [min(data[:, 0]), max(data[:, 0])]
        yrange = [min(data[:, 1]), max(data[:, 1])]
        yrange2 = [min(data[:, 2]), max(data[:, 2])]
        yrange3 = [min(data[:, 3]), max(data[:, 3])]
        fig["layout"]["xaxis"]["range"] = xrange
        fig["layout"]["xaxis2"]["range"] = xrange
        fig["layout"]["xaxis3"]["range"] = xrange
        fig["layout"]["yaxis"]["range"] = yrange
        fig["layout"]["yaxis2"]["range"] = yrange2
        fig["layout"]["yaxis3"]["range"] = yrange3

        # update title
        fig["layout"]["annotations"][0]["text"] = title

        return fig


# create thread-safe containers for storing latest data and plot info
graph3_latest = collections.deque(maxlen=1)
graph_epoch = collections.deque(maxlen=1)
graph_epoch.append(0)
graph_revision = collections.deque(maxlen=1)
graph_revision.append(0)
retention = BoundedMPPTRetention(DEFAULT_MAX_POINTS, DEFAULT_POINT_LIMIT_STRATEGY)
_browser_epoch = -1
_browser_length = 0
_browser_revision = -1
_browser_strategy = DEFAULT_POINT_LIMIT_STRATEGY
paused = collections.deque(maxlen=1)
invert_voltage = collections.deque(maxlen=1)
invert_voltage.append(False)
paused.append(False)

# initialise plot info/data queues
graph3_latest.append(
    {"msg": {"pixel": {"device_label": "-"}}, "data": np.empty((0, 5))}
)

# initial figure properties
fig3 = plotly.subplots.make_subplots(
    rows=3, cols=1, shared_xaxes=True, subplot_titles=["-"], vertical_spacing=0.02
)
fig3.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="j"), row=1, col=1)
fig3.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="p"), row=2, col=1)
fig3.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="v"), row=3, col=1)

fig3.update_xaxes(
    title="time (s)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
    row=3,
    col=1,
)
fig3.update_xaxes(
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
    row=2,
    col=1,
)
fig3.update_xaxes(
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
    row=1,
    col=1,
)
fig3.update_yaxes(
    title="|J| (mA/cm^2)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
    row=1,
    col=1,
)
fig3.update_yaxes(
    title="|P| (mW/cm^2)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
    row=2,
    col=1,
)
fig3.update_yaxes(
    title="voltage (V)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
    row=3,
    col=1,
)
fig3.update_layout(
    font={"size": 16}, margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)"
)
server = Flask(__name__)
app = dash.Dash(__name__, server=server)

log = logging.getLogger("werkzeug")
log.disabled = True

def create_layout(update_interval_ms=500):
    """Create the MPPT layout with the requested browser refresh interval."""
    return html.Div(
        html.Div(
            [
                dcc.Graph(
                    id="g3",
                    figure=fig3,
                    style={"width": "95vw", "height": "95vh"},
                ),
                dcc.Interval(
                    id="interval-component",
                    interval=update_interval_ms,
                    n_intervals=0,
                ),
            ],
        ),
    )


app.layout = create_layout()


@app.callback(
    [dash.dependencies.Output("g3", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
)
def update_graph_live(n):
    """Update graph."""
    global _browser_epoch, _browser_length, _browser_revision
    if paused[0] is False:
        g3_latest = graph3_latest[0]
        epoch = graph_epoch[0]
        revision = graph_revision[0]
        if revision == _browser_revision:
            return [dash.no_update]
        data = g3_latest["data"]
        title = g3_latest["msg"]["pixel"].get("device_label", "-")
        patch = dash.Patch()
        full_replace = epoch != _browser_epoch or len(data) == 0
        if (
            not full_replace
            and retention.is_raw
            and len(data) == _browser_length + 1
            and _browser_length < retention.max_points
        ):
            row = data[-1]
            for trace_index, value in enumerate(row[1:4]):
                patch["data"][trace_index]["x"].append(row[0])
                patch["data"][trace_index]["y"].append(value)
        else:
            for trace_index, column in enumerate((1, 2, 3)):
                patch["data"][trace_index]["x"] = data[:, 0].tolist()
                patch["data"][trace_index]["y"] = data[:, column].tolist()
        if len(data):
            xrange = [float(data[:, 0].min()), float(data[:, 0].max())]
            patch["layout"]["xaxis"]["range"] = xrange
            patch["layout"]["xaxis2"]["range"] = xrange
            patch["layout"]["xaxis3"]["range"] = xrange
            for axis, column in zip(("yaxis", "yaxis2", "yaxis3"), (1, 2, 3)):
                patch["layout"][axis]["range"] = [
                    float(data[:, column].min()), float(data[:, column].max())
                ]
        patch["layout"]["annotations"][0]["text"] = title
        # Data may arrive or clear while this callback formats its snapshot.
        # Do not send stale state; the next interval renders the new revision.
        if graph_revision[0] != revision:
            return [dash.no_update]
        _browser_epoch = epoch
        _browser_length = len(data)
        _browser_revision = revision
        return [patch]
    return [dash.no_update]


def process_ivt(payload, kind):
    """Calculate derived I-V-t parameters.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    kind : str
        Kind of measurement data.
    """
    data = payload["data"]
    area = payload["pixel"]["area"]

    new_data = []
    for element in data:
        # calculate current density in mA/cm2
        j = element[1] * 1000 / area
        p = element[0] * j
        new_element = element + [j, p]
        new_data.append(tuple(new_element))

    return new_data


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

            if msg.topic == "plotter/mppt_measurement/clear":
                old_msg = graph3_latest[0]["msg"]
                retention.clear()
                graph_epoch.append(graph_epoch[0] + 1)
                graph3_latest.append({"msg": old_msg, "data": retention.array()})
                graph_revision.append(graph_revision[0] + 1)
            elif msg.topic == "plotter/live_device":
                live_device = payload
                old_msg = graph3_latest[0]["msg"]
                retention.clear()
                graph_epoch.append(graph_epoch[0] + 1)
                graph3_latest.append({"msg": old_msg, "data": retention.array()})
                graph_revision.append(graph_revision[0] + 1)
            elif msg.topic == "data/raw/mppt_measurement":
                pdata = process_ivt(payload, "mppt_measurement")
                if (live_device is None) or (payload["pixel"]["device_label"] == live_device):
                    old_data = graph3_latest[0]["data"]
                    t = pdata[0][2]
                    v = pdata[0][0]
                    j = abs(pdata[0][4])
                    p = abs(pdata[0][5])

                    if invert_voltage[0] is True:
                        v = -1 * v

                    # time returned by smu is time in s since instrument turned on so
                    # measurement start offset needs to be substracted.
                    if len(retention) == 0:
                        t_offset = t
                    else:
                        t_offset = graph3_latest[0]["data"][0, -1]
                    data = retention.append([t - t_offset, j, p, v, t])
                    graph3_latest.append({"msg": payload, "data": data})
                    graph_revision.append(graph_revision[0] + 1)
            elif msg.topic == "plotter/pause":
                paused.append(payload)
            elif msg.topic == "plotter/invert_voltage":
                invert_voltage.append(payload)
        except:
            pass

        msg_queue.task_done()


def positive_integer(value):
    """Parse a strictly positive integer for an argparse option."""
    integer = int(value)
    if integer <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return integer


def valid_port(value):
    """Parse a valid TCP port for an argparse option."""
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return port


def parse_args(argv=None):
    """Parse MPPT plotter command-line arguments."""
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
    parser.add_argument(
        "--update-interval-ms",
        type=positive_integer,
        default=500,
        help="Dash graph refresh interval in milliseconds.",
    )
    parser.add_argument(
        "--dashport",
        type=valid_port,
        default=8053,
        help="TCP port for the Dash server.",
    )
    parser.add_argument(
        "--max-points",
        type=positive_integer,
        default=DEFAULT_MAX_POINTS,
        help="Maximum number of points retained for visualization.",
    )
    parser.add_argument(
        "--point-limit-strategy",
        choices=("sliding", "downsample"),
        default=DEFAULT_POINT_LIMIT_STRATEGY,
        help="Visualization point limiting strategy.",
    )

    return parser.parse_args(argv)


def run_dash(args):
    """Configure and start Dash using parsed command-line settings."""
    configure_runtime(args)
    app.layout = create_layout(args.update_interval_ms)
    app.run(host=args.dashhost, port=args.dashport, debug=False)


def configure_runtime(args):
    """Install bounded retention settings before MQTT processing begins."""
    global retention, _browser_strategy
    retention = BoundedMPPTRetention(args.max_points, args.point_limit_strategy)
    _browser_strategy = args.point_limit_strategy


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
    mqtt_analyser.subscribe("data/raw/mppt_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/#", qos=2)

    # start the mqtt client loop in its own thread to handle connection retries
    threading.Thread(target=mqtt_analyser.loop_forever, daemon=True).start()

    # Configure the interval and start the Dash server.
    run_dash(args)

if __name__ == "__main__":
    main()
