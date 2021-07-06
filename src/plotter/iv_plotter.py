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


def format_figure_2(data, fig, title="-"):
    """Format figure type 2.

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
        return fig
    else:
        # add data to fig
        fig["data"][0]["x"] = data[:, 0]
        fig["data"][0]["y"] = data[:, 1]

        if np.all(data[:, 2] != np.zeros(len(data[:, 2]))):
            fig["data"][1]["x"] = data[:, 2]
            fig["data"][1]["y"] = data[:, 3]

        # update ranges
        xrange = [
            min(np.append(data[:, 0], data[:, 2])),
            max(np.append(data[:, 0], data[:, 2])),
        ]
        yrange = [
            min(np.append(data[:, 1], data[:, 3])),
            max(np.append(data[:, 1], data[:, 3])),
        ]
        fig["layout"]["xaxis"]["range"] = xrange
        fig["layout"]["yaxis"]["range"] = yrange

        # update title
        fig["layout"]["annotations"][0]["text"] = title

        return fig


# create thread-safe containers for storing latest data and plot info
graph2_latest = collections.deque(maxlen=1)
paused = collections.deque(maxlen=1)
invert_voltage = collections.deque(maxlen=1)
invert_current = collections.deque(maxlen=1)
invert_voltage.append(False)
invert_current.append(False)
paused.append(False)

# queue from which processed data is published with mqtt
processed_q = queue.Queue()

# initialise plot info/data queues
graph2_latest.append(
    {"msg": {"pixel": {"label": "-", "pixel": "-"}}, "data": np.empty((0, 4))}
)

# initial figure properties
fig2 = plotly.subplots.make_subplots(subplot_titles=["-"])
fig2.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="scan0"))
fig2.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="scan1"))
fig2.update_xaxes(
    title="applied bias (V)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=True,
    zerolinecolor="#444",
    zerolinewidth=1,
    showgrid=False,
    autorange=False,
)
fig2.update_yaxes(
    title="J (mA/cm^2)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=True,
    zerolinecolor="#444",
    zerolinewidth=1,
    showgrid=False,
    autorange=False,
)
fig2.update_layout(
    font={"size": 16}, margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)"
)
server = Flask(__name__)
app = dash.Dash(__name__, server=server)

log = logging.getLogger("werkzeug")
log.disabled = True

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g2", figure=fig2, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=500, n_intervals=0,),
        ],
    ),
)


@app.callback(
    [dash.dependencies.Output("g2", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
    [dash.dependencies.State("g2", "figure")],
)
def update_graph_live(n, g2):
    """Update graph."""
    if paused[0] is False:
        g2_latest = graph2_latest[0]

        label = g2_latest["msg"]["pixel"]["label"]
        pixel = g2_latest["msg"]["pixel"]["pixel"]
        idn = f"{label}_device{pixel}"

        # update figures
        g2 = format_figure_2(g2_latest["data"], g2, idn)

    return [g2]


def process_iv(payload, kind):
    """Calculate derived I-V parameters.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    kind : str
        Kind of measurement data.
    """
    data = np.array(payload["data"], dtype=float)
    area = payload["pixel"]["area"]

    print(f"device area: {area}")

    # calculate current density in mA/cm2
    j = data[:, 1] * 1000 / area
    p = data[:, 0] * j
    data = np.append(data, j.reshape(len(p), 1), axis=1)
    data = np.append(data, p.reshape(len(p), 1), axis=1)

    # add processed data back into payload to be sent on
    payload["data"] = data.tolist()
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
    while True:
        msg = msg_queue.get()

        try:
            payload = pickle.loads(msg.payload)

            if msg.topic == "plotter/iv_measurement/clear":
                print("I-V plotter cleared")
                old_msg = graph2_latest[0]["msg"]
                data = np.empty((0, 4))
                graph2_latest.append({"msg": old_msg, "data": data})
            elif msg.topic.startswith("data/raw/iv_measurement"):
                data = graph2_latest[0]["data"]
                kind_ix = msg.topic.index("iv_measurement")
                kind = msg.topic[kind_ix:]
                pdata = process_iv(payload, kind)

                if invert_current[0] is True:
                    pdata[:, 4] = -1 * pdata[:, 4]

                if invert_voltage[0] is True:
                    pdata[:, 0] = -1 * pdata[:, 0]

                if len(data) == 0:
                    data0 = np.array(pdata[:, [0, 4]])
                    data1 = np.zeros(data0.shape)
                    data = np.append(data0, data1, axis=1)
                else:
                    data[:, 2:] = np.array(pdata[:, [0, 4]])
                graph2_latest.append({"msg": payload, "data": data})
            elif msg.topic == "measurement/run":
                config = read_config(payload)
            elif msg.topic == "plotter/pause":
                print(f"pause: {payload}")
                paused.append(payload)
            elif msg.topic == "plotter/invert_voltage":
                print(f"invert voltage: {payload}")
                invert_voltage.append(payload)
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
    mqtt_analyser.subscribe("data/raw/iv_measurement/#", qos=2)
    mqtt_analyser.subscribe("plotter/#", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    # start the sender (publishes messages from worker and manager)
    threading.Thread(target=publish_worker, args=(mqtt_analyser,), daemon=True).start()

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8052, debug=False)

if __name__ == "__main__":
    main()