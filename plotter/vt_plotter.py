#!/usr/bin/env python
"""Plot data obtained from MQTT broker using Dash."""

import collections
import pickle
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


# create thread-safe containers for storing latest data and plot info
graph1_latest = collections.deque(maxlen=1)
paused = collections.deque(maxlen=1)
paused.append(False)

# initialise plot info/data queues
graph1_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 3))})

# initial figure properties
fig1 = plotly.subplots.make_subplots(subplot_titles=["-"])
fig1.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="v"))
fig1.update_xaxes(
    title="time (s)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig1.update_yaxes(
    title="voltage (V)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig1.update_layout(margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")

app = dash.Dash(__name__)

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g1", figure=fig1, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=1 * 250, n_intervals=0,),
        ],
    ),
)


@app.callback(
    [dash.dependencies.Output("g1", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
    [dash.dependencies.State("g1", "figure")],
)
def update_graph_live(n, g1):
    """Update graph."""
    if paused[0] is False:
        g1_latest = graph1_latest[0]

        # update figures
        g1 = format_figure_1(g1_latest["data"], g1, g1_latest["msg"]["idn"])

    return [g1]


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

    # calculate current density in mA/cm2
    j = data[1] * 1000 / area
    p = data[0] * j
    data.append(j)
    data.append(p)

    # add processed data back into payload to be sent on
    payload["data"] = data
    payload = pickle.dumps(payload)
    _publish(f"data/processed/{kind}", payload)

    return data


def _publish(topic, payload):
    t = threading.Thread(target=_publish_worker, args=(topic, payload,))
    t.start()


def _publish_worker(topic, payload):
    """Publish something over MQTT with a fresh client.

    Parameters
    ----------
    topic : str
        Topic to publish to.
    payload :
        Serialised payload to publish.
    """
    mqttc = mqtt.Client()
    mqttc.connect(args.mqtthost)
    mqttc.loop_start()
    mqttc.publish(topic, payload, 2).wait_for_publish()
    mqttc.loop_stop()
    mqttc.disconnect()


def read_config(payload):
    """Get config data from payload.

    Parameters
    ----------
    payload : dict
        Request dictionary for measurement server.
    """
    global config

    print("reading config...")

    config = payload["config"]


def on_message(mqttc, obj, msg):
    """Act on an MQTT message."""
    payload = pickle.loads(msg.payload)

    if msg.topic == "data/raw/vt_measurement":
        data = graph1_latest[0]["data"]
        if payload["clear"] is True:
            print("vt clear")
            data = np.empty((0, 3))
        else:
            pdata = process_ivt(payload, "vt_measurement")
            t = pdata[2]
            v = pdata[0]

            data = np.append(data, np.array([[0, v, t]]), axis=0)

            # time returned by smu is time in s since instrument turned on so
            # measurement start offset needs to be substracted.
            t_scaled = data[:, -1] - data[0, -1]
            data[:, 0] = t_scaled
        graph1_latest.append({"msg": payload, "data": data})
    elif msg.topic == "measurement/run":
        read_config(payload)
    elif msg.topic == "plotter/pause":
        if paused[0] is True:
            paused.append(False)
        else:
            paused.append(True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-mqtthost",
        type=str,
        default="127.0.0.1",
        help="IP address or hostname for MQTT broker.",
    )
    parser.add_argument(
        "-dashhost",
        type=str,
        default="127.0.0.1",
        help="IP address or hostname for dash server.",
    )

    args = parser.parse_args()

    # init empty dicts for caching latest data
    config = {}
    eqe_calibration = {}

    # create mqtt client id
    client_id = f"plotter-{uuid.uuid4().hex}"

    mqtt_analyser = mqtt.Client(client_id)
    mqtt_analyser.on_message = on_message

    # connect MQTT client to broker
    mqtt_analyser.connect(args.mqtthost)

    # subscribe to data and request topics
    mqtt_analyser.subscribe("data/raw/vt_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/pause", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8051, debug=False)
