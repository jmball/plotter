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
import scipy as sp
import scipy.interpolate


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
        return fig
    else:
        # add data to fig
        fig["data"][0]["x"] = data[:, 0]
        fig["data"][0]["y"] = data[:, 1]
        # fig["data"][1]["x"] = data[:, 0]
        # fig["data"][1]["y"] = data[:, 2]

        # update ranges
        xrange = [min(data[:, 0]), max(data[:, 0])]
        yrange = [min(data[:, 1]), max(data[:, 1])]
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

# initialise plot info/data queues
graph5_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 2))})

# initial figure properties
fig5 = plotly.subplots.make_subplots(
    specs=[[{"secondary_y": True}]], subplot_titles=["-"]
)
fig5.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="eta"))
# fig5.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="j"), secondary_y=True)
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
    title="EQE (%)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
# fig5.update_yaxes(
#     title="integrated j (A/m^2)",
#     ticks="inside",
#     mirror=True,
#     linecolor="#444",
#     showline=True,
#     zeroline=False,
#     showgrid=False,
#     overlaying="y",
#     secondary_y=True,
#     autorange=False,
# )
fig5.update_layout(
    font={"size": 18}, margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)"
)

app = dash.Dash(__name__)

app.layout = html.Div(
    html.Div(
        [
            dcc.Graph(id="g5", figure=fig5, style={"width": "95vw", "height": "95vh"}),
            dcc.Interval(id="interval-component", interval=1 * 250, n_intervals=0,),
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
        g5 = format_figure_5(g5_latest["data"], g5, g5_latest["msg"]["idn"])

    return [g5]


def process_eqe(payload):
    """Calculate EQE.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    mqttc : MQTTQueuePublisher
        MQTT queue publisher client.
    """
    if eqe_calibration is not {}:
        # read measurement
        meas = payload["data"]
        meas_wl = meas[1]
        # ratio signal R/Aux In 1 to correct for intensity drift
        meas_sig = meas[8] / meas[4]

        # get interpolation object
        cal = np.array(eqe_calibration)
        cal_wls = cal[:, 1]
        # ratio signal R/Aux In 1 to correct for intensity drift
        cal_sig = cal[:, 8] / cal[:, 4]
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
        _publish("data/processed/eqe_measurement", pickle.dumps(payload))

        return meas
    else:
        print("no eqe calibration available")
        return None


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


def read_eqe_cal(payload):
    """Read calibration from payload.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    """
    global eqe_calibration

    print("reading eqe cal...")

    eqe_calibration = payload["data"]


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

    if msg.topic == "data/raw/eqe_measurement":
        data = graph5_latest[0]["data"]
        if payload["clear"] is True:
            print("eqe clear")
            data = np.empty((0, 2))
        else:
            pdata = process_eqe(payload)
            if pdata is not None:
                wl = pdata[1]
                eqe = pdata[-1]
                data = np.append(data, np.array([[wl, eqe]]), axis=0)
        graph5_latest.append({"msg": payload, "data": data})
    elif msg.topic == "calibration/eqe":
        read_eqe_cal(payload)
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
    mqtt_analyser.subscribe("calibration/eqe", qos=2)
    mqtt_analyser.subscribe("data/raw/eqe_measurement", qos=2)
    mqtt_analyser.subscribe("plotter/pause", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, port=8055, debug=False)
