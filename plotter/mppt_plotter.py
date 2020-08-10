#!/usr/bin/env python
"""Plot data obtained from MQTT broker using Dash."""

import collections
import logging
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
        return fig
    else:
        # add data to fig
        fig["data"][0]["x"] = data[:, 0]
        fig["data"][0]["y"] = data[:, 1]
        fig["data"][1]["x"] = data[:, 0]
        fig["data"][1]["y"] = data[:, 2]
        fig["data"][2]["x"] = data[:, 0]
        fig["data"][2]["y"] = data[:, 3]

        # update ranges
        xrange = [min(data[:, 0]), max(data[:, 0])]
        yrange = [
            min(np.append(data[:, 1], data[:, 2])),
            max(np.append(data[:, 1], data[:, 2])),
        ]
        yrange2 = [min(data[:, 3]), max(data[:, 3])]
        fig["layout"]["xaxis"]["range"] = xrange
        fig["layout"]["yaxis"]["range"] = yrange
        fig["layout"]["yaxis2"]["range"] = yrange2

        # update title
        fig["layout"]["annotations"][0]["text"] = title

        return fig


# create thread-safe containers for storing latest data and plot info
graph3_latest = collections.deque(maxlen=1)
paused = collections.deque(maxlen=1)
paused.append(False)

# initialise plot info/data queues
graph3_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 5))})

# initial figure properties
fig3 = plotly.subplots.make_subplots(
    specs=[[{"secondary_y": True}]], subplot_titles=["-"]
)
fig3.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="j"))
fig3.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="p"))
fig3.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="v"), secondary_y=True)
fig3.update_xaxes(
    title="time (s)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig3.update_yaxes(
    title="J (mA/cm^2) | P (mW/cm^2)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    overlaying="y",
    secondary_y=True,
    autorange=False,
)
fig3.update_yaxes(
    title="voltage (V)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    #overlaying="y",
    secondary_y=False,
    autorange=False,
)
fig3.update_layout(
    font={"size": 16}, margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)"
)

app = dash.Dash(__name__)

log = logging.getLogger("werkzeug")
log.disabled = True

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g3", figure=fig3, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=1 * 250, n_intervals=0,),
        ],
    ),
)


@app.callback(
    [dash.dependencies.Output("g3", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
    [dash.dependencies.State("g3", "figure")],
)
def update_graph_live(n, g3):
    """Update graph."""
    if paused[0] is False:
        g3_latest = graph3_latest[0]

        # update figures
        g3 = format_figure_3(g3_latest["data"], g3, g3_latest["msg"]["idn"])

    return [g3]


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
    p = data[0] * j * -1
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

    if msg.topic == "data/raw/mppt_measurement":
        data = graph3_latest[0]["data"]
        if payload["clear"] is True:
            print("mppt clear")
            data = np.empty((0, 5))
        else:
            pdata = process_ivt(payload, "mppt_measurement")
            t = pdata[2]
            v = pdata[0]
            j = pdata[4]
            p = pdata[5]

            data = np.append(data, np.array([[0, j, p, v, t]]), axis=0,)

            # time returned by smu is time in s since instrument turned on so
            # measurement start offset needs to be substracted.
            t_scaled = data[:, -1] - data[0, -1]
            data[:, 0] = t_scaled
        graph3_latest.append({"msg": payload, "data": data})
    elif msg.topic == "measurement/run":
        read_config(payload)
    elif msg.topic == "plotter/pause":
        print(f"pause: {payload}")
        paused.append(payload)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mqtthost",
        type=str,
        default="127.0.0.1",
        help="IP address or hostname for MQTT broker.",
    )
    parser.add_argument(
        "--dashhost",
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
    mqtt_analyser.subscribe("data/raw/mppt_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/pause", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8053, debug=False)
