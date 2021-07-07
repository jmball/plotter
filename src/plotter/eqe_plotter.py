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
import scipy as sp
import argparse
from flask import Flask


def format_figure_5(data, fig, title="-"):
    """Format figure type 5.

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
        return fig
    else:
        # add data to fig
        fig["data"][0]["x"] = data[:, 0]
        fig["data"][0]["y"] = data[:, 1]
        # fig["data"][1]["x"] = data[:, 0]
        # fig["data"][1]["y"] = data[:, 2]

        # update ranges
        xrange = [min(data[:, 0]), max(data[:, 0])]
        yrange = [0, max(data[:, 1])]
        # yrange2 = [min(data[:, 2]), max(data[:, 2])]
        fig["layout"]["xaxis"]["range"] = xrange
        fig["layout"]["yaxis"]["range"] = yrange
        # fig["layout"]["yaxis2"]["range"] = yrange2

        # update title
        fig["layout"]["annotations"][0]["text"] = title

        return fig


# create thread-safe containers for storing latest data and plot info
graph5_latest = collections.deque(maxlen=1)
paused = collections.deque(maxlen=1)
paused.append(False)


# queue from which processed data is published with mqtt
processed_q = queue.Queue()

# initialise plot info/data queues
graph5_latest.append(
    {"msg": {"pixel": {"device_label": "-"}}, "data": np.empty((0, 2))}
)

# initial figure properties
fig5 = plotly.subplots.make_subplots(
    specs=[[{"secondary_y": True}]], subplot_titles=["-"]
)
fig5.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="eta"))
fig5.update_xaxes(
    title="wavelength (nm)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig5.update_yaxes(
    title="EQE (calibration units)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig5.update_layout(
    font={"size": 16}, margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)"
)
server = Flask(__name__)
app = dash.Dash(__name__, server=server)

log = logging.getLogger("werkzeug")
log.disabled = True

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g5", figure=fig5, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=500, n_intervals=0,),
        ],
    ),
)


@app.callback(
    [dash.dependencies.Output("g5", "figure")],
    [dash.dependencies.Input("interval-component", "n_intervals")],
    [dash.dependencies.State("g5", "figure")],
)
def update_graph_live(n, g5):
    """Update graph."""
    if paused[0] is False:
        g5_latest = graph5_latest[0]

        # update figures
        g5 = format_figure_5(g5_latest["data"], g5, g5_latest["msg"]["pixel"]["device_label"])

    return [g5]


def process_eqe(payload, kind, eqe_calibration, config):
    """Calculate EQE.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    kind : str
        Kind of measurement data.
    """
    if eqe_calibration is not {}:
        # read measurement
        meas = payload["data"]
        meas_wl = meas[1]
        # ratio signal R/Aux In 1 to correct for intensity drift
        if (ratio := config["lia"]["ratio"]) is True:
            meas_sig = meas[8] / meas[4]
        else:
            meas_sig = meas[8]

        # get interpolation object
        cal = np.array(eqe_calibration)
        cal_wls = cal[:, 1]
        # ratio signal R/Aux In 1 to correct for intensity drift
        if ratio is True:
            cal_sig = cal[:, 8] / cal[:, 4]
        else:
            cal_sig = cal[:, 8]
        f_cal = sp.interpolate.interp1d(
            cal_wls, cal_sig, kind="linear", bounds_error=False, fill_value=0
        )

        # look up ref eqe
        ref_wls = config["reference"]["calibration"]["eqe"]["wls"]
        ref_eqe = config["reference"]["calibration"]["eqe"]["eqe"]
        f_ref = sp.interpolate.interp1d(
            ref_wls, ref_eqe, kind="linear", bounds_error=False, fill_value=0
        )

        # calculate eqe and append to data
        meas_eqe = f_ref(meas_wl) * meas_sig / f_cal(meas_wl)
        meas.append(meas_eqe)

        # publish
        payload["data"] = meas
        processed_q.put([f"data/processed/{kind}", payload])

        return meas
    else:
        print("no eqe calibration available")
        return None


def read_eqe_cal(payload):
    """Read calibration from payload.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    """

    print("reading eqe cal...")

    return payload["data"]


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
    eqe_calibration = {}

    while True:
        msg = msg_queue.get()

        try:
            payload = pickle.loads(msg.payload)

            if msg.topic == "plotter/eqe_measurement/clear":
                print("EQE plotter cleared")
                old_msg = graph5_latest[0]["msg"]
                data = np.empty((0, 2))
                graph5_latest.append({"msg": old_msg, "data": data})
            elif msg.topic == "data/raw/eqe_measurement":
                old_data = graph5_latest[0]["data"]
                pdata = process_eqe(payload, "eqe_measurement", eqe_calibration, config)
                wl = pdata[1]
                eqe = pdata[-1]
                data = np.append(old_data, np.array([[wl, eqe]]), axis=0)
                graph5_latest.append({"msg": payload, "data": data})
            elif msg.topic == "calibration/eqe":
                eqe_calibration = read_eqe_cal(payload)
            elif msg.topic == "measurement/run":
                config = read_config(payload)
            elif msg.topic == "plotter/pause":
                print(f"pause: {payload}")
                paused.append(payload)
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

    msg_queue = queue.Queue()

    # start the msg queue thread
    threading.Thread(target=msg_handler, args=(msg_queue,), daemon=True).start()

    mqtt_analyser = mqtt.Client(client_id)
    mqtt_analyser.on_message =  lambda mqttc, obj, msg: on_message(mqttc, obj, msg, msg_queue)

    # connect MQTT client to broker
    mqtt_analyser.connect(args.mqtthost)

    # subscribe to data and request topics
    mqtt_analyser.subscribe("calibration/eqe", qos=2)
    mqtt_analyser.subscribe("data/raw/eqe_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/#", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    # start the publish worker
    threading.Thread(target=publish_worker, args=(mqtt_analyser,), daemon=True).start()

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8055, debug=False)

if __name__ == "__main__":
    main()