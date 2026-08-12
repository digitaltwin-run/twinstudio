from __future__ import annotations

import json
import os
from pathlib import Path

import paho.mqtt.client as mqtt

from housing_studio.artifacts import generate_artifacts
from housing_studio.models import ProjectConfig, default_project_config
from scoped_brep_adapter import apply_scoped_operation


HOST = os.getenv("MQTT_HOST", "mqtt")
PORT = int(os.getenv("MQTT_PORT", "1883"))
PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "twinstudio/v1").strip("/")
DATA = Path(os.getenv("TWINSTUDIO_DATA_DIR", os.getenv("LPS_DATA_DIR", "/data"))).resolve()


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(f"{PREFIX}/+/commands/generate-artifacts", qos=1)
    client.subscribe(f"{PREFIX}/+/commands/apply-scoped-cad-change", qos=1)


def _safe_data_path(raw: str) -> Path:
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = DATA / candidate
    resolved = candidate.resolve()
    if resolved != DATA and DATA not in resolved.parents:
        raise ValueError("CAD worker input must be inside TWINSTUDIO_DATA_DIR")
    return resolved


def on_message(client, userdata, message):
    parts = message.topic.split("/")
    project_id = parts[-3] if len(parts) >= 3 else "unknown"
    command = parts[-1]
    try:
        payload = json.loads(message.payload.decode("utf-8"))
        project_id = payload.get("project_id") or project_id
        job_id = payload.get("job_id") or f"{project_id}-{payload.get('revision', 'main')}"
        output = DATA / "cad-jobs" / job_id
        if command == "generate-artifacts":
            config_data = payload.get("housing_config")
            config = ProjectConfig.model_validate(config_data) if config_data else default_project_config()
            manifest = generate_artifacts(
                config,
                DATA / "cad-jobs",
                job_id=job_id,
                source_prompt=payload.get("prompt"),
            )
            result = {"mode": "parametric-regeneration", "manifest": manifest}
        elif command == "apply-scoped-cad-change":
            result = apply_scoped_operation(
                input_step=_safe_data_path(payload["input_step"]),
                output_dir=output,
                selection=payload["selection"],
                operation=payload["operation"],
            )
            result = {"mode": "derived-scoped-brep", "journal": result}
        else:
            raise ValueError(f"Unsupported CAD worker command: {command}")
        client.publish(
            f"{PREFIX}/{project_id}/events/generation-completed",
            json.dumps({"project_id": project_id, "job_id": job_id, **result}),
            qos=1,
        )
    except Exception as exc:
        client.publish(
            f"{PREFIX}/{project_id}/events/generation-failed",
            json.dumps({"project_id": project_id, "command": command, "error": str(exc)}),
            qos=1,
        )


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
if os.getenv("MQTT_USERNAME"):
    client.username_pw_set(os.getenv("MQTT_USERNAME"), os.getenv("MQTT_PASSWORD", ""))
client.connect(HOST, PORT, keepalive=30)
client.loop_forever()
