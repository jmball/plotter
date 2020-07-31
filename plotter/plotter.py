#!/usr/bin/env python
"""Plot data obtained from MQTT broker using Dash."""

import collections
import pickle
import threading
import uuid

import dash
import dash_core_components as dcc
import dash_daq as daq
import dash_html_components as html
import numpy as np
import paho.mqtt.client as mqtt
import plotly
import plotly.subplots
import plotly.graph_objs as go
import scipy as sp
import scipy.interpolate


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
graph1_latest = collections.deque(maxlen=1)
graph2_latest = collections.deque(maxlen=1)
graph3_latest = collections.deque(maxlen=1)
graph4_latest = collections.deque(maxlen=1)
graph5_latest = collections.deque(maxlen=1)

# initialise plot info/data queues
graph1_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 3))})
graph2_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 4))})
graph3_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 5))})
graph4_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 3))})
graph5_latest.append({"msg": {"clear": True, "idn": "-"}, "data": np.empty((0, 2))})

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

fig2 = plotly.subplots.make_subplots(subplot_titles=["-"])
fig2.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="scan0"))
fig2.add_trace(go.Scatter(x=[], y=[], mode="lines+markers", name="scan1"))
fig2.update_xaxes(
    title="voltage (V)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig2.update_yaxes(
    title="current density (mA/cm^2)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig2.update_layout(margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")

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
    title="current density (mA/cm^2) | power density (mW/cm^2)",
    ticks="inside",
    mirror=True,
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
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
    overlaying="y",
    secondary_y=True,
    autorange=False,
)
fig3.update_layout(margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")

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
    title="current density (mA/cm^2)",
    ticks="inside",
    mirror="ticks",
    linecolor="#444",
    showline=True,
    zeroline=False,
    showgrid=False,
    autorange=False,
)
fig4.update_layout(margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")

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
    title="eqe (%)",
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
fig5.update_layout(margin=dict(l=20, r=0, t=30, b=0), plot_bgcolor="rgba(0,0,0,0)")

app = dash.Dash(__name__)

# style={"width": "100vw", "height": "100vh"},

app.layout = html.Div(
    [
        html.Div(
            [
                html.Div([dcc.Graph(id="g1", figure=fig1)], className="four columns",),
                html.Div([dcc.Graph(id="g2", figure=fig2)], className="four columns",),
                html.Div([dcc.Graph(id="g3", figure=fig3)], className="four columns",),
            ],
            className="row",
        ),
        html.Div(
            [
                html.Div([dcc.Graph(id="g4", figure=fig4)], className="four columns",),
                html.Div([dcc.Graph(id="g5", figure=fig5)], className="four columns",),
                html.Div(
                    [
                        daq.ToggleSwitch(
                            id="pause-switch",
                            value=False,
                            color="#36C95D",
                            label=[
                                {
                                    "style": {
                                        "font-size": "large",
                                        "font-family": "sans-serif",
                                    },
                                    "label": "Live",
                                },
                                {
                                    "style": {
                                        "font-size": "large",
                                        "font-family": "sans-serif",
                                    },
                                    "label": "Paused",
                                },
                            ],
                            size=75,
                            style={
                                "width": "250px",
                                "margin": "auto",
                                "margin-top": "200px",
                            },
                        )
                    ],
                    className="four columns",
                ),
            ],
            className="row",
        ),
        dcc.Interval(
            id="interval-component", interval=1 * 250, n_intervals=0,  # in milliseconds
        ),
    ],
)


@app.callback(
    [
        dash.dependencies.Output("g1", "figure"),
        dash.dependencies.Output("g2", "figure"),
        dash.dependencies.Output("g3", "figure"),
        dash.dependencies.Output("g4", "figure"),
        dash.dependencies.Output("g5", "figure"),
    ],
    [dash.dependencies.Input("interval-component", "n_intervals")],
    [
        dash.dependencies.State("g1", "figure"),
        dash.dependencies.State("g2", "figure"),
        dash.dependencies.State("g3", "figure"),
        dash.dependencies.State("g4", "figure"),
        dash.dependencies.State("g5", "figure"),
        dash.dependencies.State("pause-switch", "value"),
    ],
)
def update_graph_live(n, g1, g2, g3, g4, g5, paused):
    """Update graph."""
    if paused is not True:
        g1_latest = graph1_latest[0]
        g2_latest = graph2_latest[0]
        g3_latest = graph3_latest[0]
        g4_latest = graph4_latest[0]
        g5_latest = graph5_latest[0]

        # update figures
        g1 = format_figure_1(g1_latest["data"], g1, g1_latest["msg"]["idn"])
        g2 = format_figure_2(g2_latest["data"], g2, g2_latest["msg"]["idn"])
        g3 = format_figure_3(g3_latest["data"], g3, g3_latest["msg"]["idn"])
        g4 = format_figure_4(g4_latest["data"], g4, g4_latest["msg"]["idn"])
        g5 = format_figure_5(g5_latest["data"], g5, g5_latest["msg"]["idn"])

    return g1, g2, g3, g4, g5


@app.callback(
    dash.dependencies.Output("pause-switch", "color"),
    [dash.dependencies.Input("pause-switch", "value")],
)
def pause_button(paused):
    """Update color of pause button."""
    if paused is True:
        return "#FF5E5E"
    else:
        return "#36C95D"


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


def process_iv(payload):
    """Calculate derived I-V parameters.

    Parameters
    ----------
    payload : dict
        Payload dictionary.
    """
    data = np.array(payload["data"])
    area = payload["pixel"]["area"]

    # calculate current density in mA/cm2
    j = data[:, 1] * 1000 / area
    p = data[:, 0] * j
    data = np.append(data, j.reshape(len(p), 1), axis=1)
    data = np.append(data, p.reshape(len(p), 1), axis=1)

    # add processed data back into payload to be sent on
    payload["data"] = data.tolist()
    _publish("data/processed/iv_measurement", pickle.dumps(payload))

    return data


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
        meas_sig = meas[-1]

        # get interpolation object
        cal = np.array(eqe_calibration)
        cal_wls = cal[:, 1]
        cal_sig = cal[:, -1]
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

    topic_list = msg.topic.split("/")

    if (topic_list[0] == "data") and (topic_list[1] == "raw"):
        if (measurement := topic_list[2]) == "vt_measurement":
            data = graph1_latest[0]["data"]
            if payload["clear"] is True:
                print("vt clear")
                data = np.empty((0, 3))
            else:
                pdata = process_ivt(payload, measurement)
                t = pdata[2]
                v = pdata[0]

                data = np.append(data, np.array([[0, v, t]]), axis=0)

                # time returned by smu is time in s since instrument turned on so measurement
                # start offset needs to be substracted.
                t_scaled = data[:, -1] - data[0, -1]
                data[:, 0] = t_scaled
            graph1_latest.append({"msg": payload, "data": data})
        elif measurement == "iv_measurement":
            data = graph2_latest[0]["data"]
            if payload["clear"] is True:
                print("iv clear")
                data = np.empty((0, 4))
            else:
                pdata = process_iv(payload)
                if len(data) == 0:
                    data0 = np.array(pdata[:, [0, 4]])
                    data1 = np.zeros(data0.shape)
                    data = np.append(data0, data1, axis=1)
                else:
                    data[:, 2:] = np.array(pdata[:, [0, 4]])
            graph2_latest.append({"msg": payload, "data": data})
        elif measurement == "mppt_measurement":
            data = graph3_latest[0]["data"]
            if payload["clear"] is True:
                print("mppt clear")
                data = np.empty((0, 5))
            else:
                pdata = process_ivt(payload, measurement)
                t = pdata[2]
                v = pdata[0]
                j = pdata[4]
                p = pdata[5]

                data = np.append(data, np.array([[0, v, j, p, t]]), axis=0,)

                # time returned by smu is time in s since instrument turned on so
                # measurement start offset needs to be substracted.
                t_scaled = data[:, -1] - data[0, -1]
                data[:, 0] = t_scaled
            graph3_latest.append({"msg": payload, "data": data})
        elif measurement == "it_measurement":
            data = graph4_latest[0]["data"]
            if payload["clear"] is True:
                print("it clear")
                data = np.empty((0, 3))
            else:
                pdata = process_ivt(payload, measurement)
                t = pdata[2]
                j = pdata[4]

                data = np.append(data, np.array([[0, j, t]]), axis=0)

                # time returned by smu is time in s since instrument turned on so
                # measurement start offset needs to be substracted.
                t_scaled = data[:, -1] - data[0, -1]
                data[:, 0] = t_scaled
            graph4_latest.append({"msg": payload, "data": data})
        elif measurement == "eqe_measurement":
            data = graph5_latest[0]["data"]
            if payload["clear"] is True:
                print("eqe clear")
                data = np.empty((0, 2))
            else:
                pdata = process_eqe(payload)
                print(pdata)
                if pdata is not None:
                    wl = pdata[1]
                    eqe = pdata[-1]
                    data = np.append(data, np.array([[wl, eqe]]), axis=0)
            graph5_latest.append({"msg": payload, "data": data})
    elif topic_list[0] == "calibration":
        if (measurement := topic_list[1]) == "eqe":
            read_eqe_cal(payload)
    elif msg.topic == "measurement/run":
        read_config(payload)


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
    mqtt_analyser.subscribe("data/raw/#", qos=2)
    mqtt_analyser.subscribe("calibration/eqe", qos=2)
    mqtt_analyser.subscribe("measurement/run", qos=2)

    print(f"{client_id} connected!")

    mqtt_analyser.loop_start()

    # start dash server
    app.run_server(host=args.dashhost, debug=False)
