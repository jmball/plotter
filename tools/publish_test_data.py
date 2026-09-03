#!/usr/bin/env python3
"""Publish generated MPPT measurements to an MQTT broker."""

import argparse
import json
import time

import numpy as np
import paho.mqtt.publish as publish


def main():
    """Publish a configurable number of synthetic measurements."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mqtthost", default="127.0.0.1", help="MQTT broker host.")
    parser.add_argument("--mqttport", type=int, default=1883, help="MQTT broker port.")
    parser.add_argument(
        "--kind",
        choices=("mppt", "it", "vt"),
        default="mppt",
        help="Measurement kind and corresponding raw MQTT topic.",
    )
    parser.add_argument("--count", type=int, default=100, help="Number of messages.")
    parser.add_argument(
        "--interval", type=float, default=2.0, help="Seconds between messages."
    )
    args = parser.parse_args()
    topic = "data/raw/{}_measurement".format(args.kind)

    for _ in range(args.count):
        data = [(np.random.rand(), 10 * np.random.rand(), time.time(), 0)]
        payload = {
            "idn": "test",
            "pixel": {"area": 1, "device_label": "test-device"},
            "data": data,
            "clear": False,
        }
        publish.single(
            topic,
            json.dumps(payload),
            qos=2,
            hostname=args.mqtthost,
            port=args.mqttport,
        )
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
