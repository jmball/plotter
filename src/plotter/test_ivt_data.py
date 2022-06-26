import paho.mqtt.publish as publish
import time
import json
import numpy as np

for i in range(100):
    data = [(np.random.rand(), 10 * np.random.rand(), time.time(), 0)]
    print(data)
    payload = {"idn": "test", "pixel": {"area": 1}, "data": data, "clear": False}
    publish.single("data/raw/mppt_measurement", json.dumps(payload), 2)
    time.sleep(2)
