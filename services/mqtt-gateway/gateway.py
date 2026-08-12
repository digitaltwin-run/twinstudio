from __future__ import annotations

import base64
import json
import os
import traceback
from uuid import uuid4

import httpx
import paho.mqtt.client as mqtt

MQTT_HOST = os.getenv("MQTT_HOST", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "twinstudio/v1").strip("/")
API_BASE = os.getenv("TWINSTUDIO_API_BASE", os.getenv("LPS_API_BASE", "http://app:8000")).rstrip("/")
SERVICE_EMAIL = os.getenv("TWINSTUDIO_SERVICE_EMAIL", os.getenv("LPS_SERVICE_EMAIL", "mqtt-gateway@example.test"))
SERVICE_TOKEN = os.getenv("TWINSTUDIO_SERVICE_TOKEN", os.getenv("LPS_SERVICE_TOKEN", ""))


def auth_headers() -> dict[str, str]:
    if not SERVICE_TOKEN:
        return {}
    raw = base64.b64encode(f"{SERVICE_EMAIL}:{SERVICE_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def response_topic(project_id: str, correlation_id: str) -> str:
    return f"{PREFIX}/{project_id}/responses/{correlation_id}"


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(f"{PREFIX}/+/commands/+", qos=1)


def on_message(client, userdata, message):
    parts = message.topic.split("/")
    project_id = parts[-3] if len(parts) >= 3 else "unknown"
    command_name = parts[-1]
    correlation_id = str(uuid4())
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        correlation_id = str(payload.get("correlation_id") or correlation_id)
        with httpx.Client(timeout=120.0, headers=auth_headers()) as http:
            if command_name == "execute":
                response = http.post(
                    f"{API_BASE}/api/v1/projects/{project_id}/commands",
                    json={
                        "command_type": payload["command_type"],
                        "expected_version": payload.get("expected_version"),
                        "payload": payload.get("payload", {}),
                    },
                )
            elif command_name == "resolve-selection":
                response = http.post(
                    f"{API_BASE}/api/v1/projects/{project_id}/selections/resolve",
                    json=payload["selection"],
                )
            elif command_name == "plan-change":
                response = http.post(
                    f"{API_BASE}/api/v1/projects/{project_id}/change-plans",
                    json={"prompt": payload["prompt"], "selection": payload["selection"]},
                )
            elif command_name == "apply-change":
                response = http.post(
                    f"{API_BASE}/api/v1/projects/{project_id}/change-plans/{payload['plan_id']}/apply"
                )
            elif command_name == "simulate-power":
                response = http.post(f"{API_BASE}/api/v1/projects/{project_id}/simulations/power")
            elif command_name == "review-design-fixation":
                response = http.post(
                    f"{API_BASE}/api/v1/projects/{project_id}/design-fixation/scan",
                    json={
                        "target_uri": payload["target_uri"],
                        "challenge": payload.get("challenge", ""),
                        "lens_ids": payload.get("lens_ids", []),
                        "max_alternatives": payload.get("max_alternatives", 8),
                        "use_llm": payload.get("use_llm", True),
                        "record": payload.get("record", True),
                    },
                )
            else:
                raise ValueError(f"Unsupported MQTT command: {command_name}")
            content_type = response.headers.get("content-type", "")
            body = response.json() if "json" in content_type else {"text": response.text}
            result = {
                "correlation_id": correlation_id,
                "project_id": project_id,
                "command": command_name,
                "ok": response.is_success,
                "status_code": response.status_code,
                "result": body,
            }
    except Exception as exc:
        result = {
            "correlation_id": correlation_id,
            "project_id": project_id,
            "command": command_name,
            "ok": False,
            "error": str(exc),
            "trace": traceback.format_exc(limit=3),
        }
    client.publish(response_topic(project_id, correlation_id), json.dumps(result), qos=1)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
if os.getenv("MQTT_USERNAME"):
    client.username_pw_set(os.getenv("MQTT_USERNAME"), os.getenv("MQTT_PASSWORD", ""))
client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
client.loop_forever()
