from __future__ import annotations

import hashlib
import json
import os
import random
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from PIL import Image, ImageStat


HOST = os.getenv("MQTT_HOST", "mqtt")
PORT = int(os.getenv("MQTT_PORT", "1883"))
PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "twinstudio/v1").strip("/")
PROJECT = os.getenv("PROJECT_ID", "demo-rpi5")
SCENARIO = Path("/scenario")


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(HOST, PORT, 30)
client.loop_start()


def analyze_image(path: Path) -> dict:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        stat = ImageStat.Stat(rgb)
        return {
            "name": path.name,
            "size": list(rgb.size),
            "mean_rgb": [round(value, 2) for value in stat.mean],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }


images = sorted(list(SCENARIO.glob("*.png")) + list(SCENARIO.glob("*.jpg")))
frame_index = 0
try:
    while True:
        workload = 0.35 + 0.55 * random.random()
        current = 0.8 + workload * 2.3
        temperature = 35 + workload * 35 + random.uniform(-1, 1)
        telemetry = {
            "project_id": PROJECT,
            "timestamp": time.time(),
            "workload": round(workload, 3),
            "estimated_current_a": round(current, 3),
            "estimated_soc_temperature_c": round(temperature, 2),
        }
        client.publish(f"{PREFIX}/{PROJECT}/telemetry/device", json.dumps(telemetry), qos=0)
        if images:
            result = analyze_image(images[frame_index % len(images)])
            result["timestamp"] = time.time()
            client.publish(f"{PREFIX}/{PROJECT}/telemetry/camera-analysis", json.dumps(result), qos=0)
            frame_index += 1
        time.sleep(2)
finally:
    client.loop_stop()
