#!/usr/bin/env python
"""Plot data obtained from MQTT broker using Dash."""

import collections
import logging
import pickle
import queue
import threading
import uuid

import dash
import dash_core_components as dcc
import dash_html_components as html
import numpy as np
import paho.mqtt.client as mqtt
import plotly
import plotly.subplots
import plotly.graph_objs as go
import argparse
from flask import Flask


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
paused = collections.deque(maxlen=1)
invert_current = collections.deque(maxlen=1)
invert_current.append(False)
paused.append(False)

# queue from which processed data is published with mqtt
processed_q = queue.Queue()

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

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g4", figure=fig4, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=500, n_intervals=0,),
        ],
    ),
)


@app.callback(
    [dash.dependencies.Output("g4", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
    [dash.dependencies.State("g4", "figure")],
)
def update_graph_live(n, g4):
    """Update graph."""
    if paused[0] is False:
        g4_latest = graph4_latest[0]

        # update figures
        g4 = format_figure_4(g4_latest["data"], g4, g4_latest["msg"]["pixel"]["device_label"])

    return [g4]


def process_ivt(payload, kind):
    """Calculate derived I-V-t parameters.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    kind : str
        Kind of measurement data.
    """
    data = list(payload["data"])
    area = payload["pixel"]["area"]

    # calculate current density in mA/cm2
    j = data[1] * 1000 / area
    p = data[0] * j
    data.append(j)
    data.append(p)

    # add processed data back into payload to be sent on
    payload["data"] = data
    processed_q.put([f"data/processed/{kind}", payload])

    return data


def read_config(payload):
    """Get config data from payload.

    Parameters
    ----------
    payload : dict
        Request dictionary for measurement server.
    """

    print("reading config...")

    return payload["config"]


def on_message(mqttc, obj, msg, msg_queue):
    """Act on an MQTT message."""
    msg_queue.put_nowait(msg)


def msg_handler(msg_queue):
    """Handle incoming MQTT messages."""
    # init empty dicts for caching latest data
    config = {}
    live_device = None  # keep track of which device to plot

    while True:
        msg = msg_queue.get()

        try:
            payload = pickle.loads(msg.payload)

            if msg.topic == "plotter/it_measurement/clear":
                print("I-t plotter cleared")
                old_msg = graph4_latest[0]["msg"]
                data = np.empty((0, 3))
                graph4_latest.append({"msg": old_msg, "data": data})
            elif msg.topic == "plotter/live_device":
                live_device = payload
                print("I-t plotter cleared")
                old_msg = graph4_latest[0]["msg"]
                data = np.empty((0, 3))
                graph4_latest.append({"msg": old_msg, "data": data})
            elif msg.topic == "data/raw/it_measurement":
                pdata = process_ivt(payload, "it_measurement")
                if (live_device is None) or (payload["pixel"]["device_label"] == live_device):
                    old_data = graph4_latest[0]["data"]
                    
                    t = pdata[2]
                    j = pdata[4]

                    if invert_current[0] is True:
                        j = -1 * j

                    data = np.append(old_data, np.array([[0, j, t]]), axis=0)

                    # time returned by smu is time in s since instrument turned on so
                    # measurement start offset needs to be substracted.
                    t_scaled = data[:, -1] - data[0, -1]
                    data[:, 0] = t_scaled
                    graph4_latest.append({"msg": payload, "data": data})
            elif msg.topic == "measurement/run":
                config = read_config(payload)
            elif msg.topic == "plotter/pause":
                print(f"pause: {payload}")
                paused.append(payload)
            elif msg.topic == "plotter/invert_current":
                print(f"invert current: {payload}")
                invert_current.append(payload)
        except:
            pass

        msg_queue.task_done()


def publish_worker(mqttc):
    """Publish payloads added to queue.

    Parameters
    ----------
    mqttc : mqtt.Client
        MQTT client.
    """
    while True:
        topic, payload = processed_q.get()
        mqttc.publish(topic, pickle.dumps(payload), 2).wait_for_publish()
        processed_q.task_done()


def main():
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

    args = parser.parse_args()

    # create mqtt client id
    client_id = f"plotter-{uuid.uuid4().hex}"

    # queue for storing incoming messages
    msg_queue = queue.Queue()

    # start the msg queue thread
    threading.Thread(target=msg_handler, args=(msg_queue,), daemon=True).start()

    mqtt_analyser = mqtt.Client(client_id)
    mqtt_analyser.on_message = lambda mqttc, obj, msg: on_message(mqttc, obj, msg, msg_queue)

    # connect MQTT client to broker
    mqtt_analyser.connect(args.mqtthost)

    # subscribe to data and request topics
    mqtt_analyser.subscribe("data/raw/it_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/#", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    # start the sender (publishes messages from worker and manager)
    threading.Thread(target=publish_worker, args=(mqtt_analyser,), daemon=True).start()

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8054, debug=False)

if __name__ == "__main__":
    main()