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
paused = collections.deque(maxlen=1)
invert_voltage = collections.deque(maxlen=1)
invert_voltage.append(False)
paused.append(False)

# queue from which processed data is published with mqtt
processed_q = queue.Queue()

# initialise plot info/data queues
graph3_latest.append(
    {"msg": {"pixel": {"label": "-", "pixel": "-"}}, "data": np.empty((0, 5))}
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

app = dash.Dash(__name__)

log = logging.getLogger("werkzeug")
log.disabled = True

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g3", figure=fig3, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=500, n_intervals=0,),
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

        label = g3_latest["msg"]["pixel"]["label"]
        pixel = g3_latest["msg"]["pixel"]["pixel"]
        idn = f"{label}_device{pixel}"

        # update figures
        g3 = format_figure_3(g3_latest["data"], g3, idn)

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
    global config

    print("reading config...")

    config = payload["config"]


msg_queue = queue.Queue()


def on_message(mqttc, obj, msg):
    """Act on an MQTT message."""
    msg_queue.put_nowait(msg)


def msg_handler():
    """Handle incoming MQTT messages."""
    while True:
        msg = msg_queue.get()

        try:
            payload = pickle.loads(msg.payload)

            if msg.topic == "plotter/mppt_measurement/clear":
                print("MPPT plotter cleared")
                old_msg = graph3_latest[0]["msg"]
                data = np.empty((0, 5))
                graph3_latest.append({"msg": old_msg, "data": data})
            elif msg.topic == "data/raw/mppt_measurement":
                old_data = graph3_latest[0]["data"]
                pdata = process_ivt(payload, "mppt_measurement")
                t = pdata[2]
                v = pdata[0]
                j = abs(pdata[4])
                p = abs(pdata[5])

                if invert_voltage[0] is True:
                    v = -1 * v

                data = np.append(old_data, np.array([[0, j, p, v, t]]), axis=0,)

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
            elif msg.topic == "plotter/invert_voltage":
                print(f"invert voltage: {payload}")
                invert_voltage.append(payload)
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

    # start the msg queue thread
    threading.Thread(target=msg_handler, daemon=True).start()

    mqtt_analyser = mqtt.Client(client_id)
    mqtt_analyser.on_message = on_message

    # connect MQTT client to broker
    mqtt_analyser.connect(args.mqtthost)

    # subscribe to data and request topics
    mqtt_analyser.subscribe("data/raw/mppt_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/#", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    # start the sender (publishes messages from worker and manager)
    threading.Thread(target=publish_worker, args=(mqtt_analyser,), daemon=True).start()

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8053, debug=False)

if __name__ == "__main__":
    main()