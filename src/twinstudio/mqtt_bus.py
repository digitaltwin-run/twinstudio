from __future__ import annotations

import json
import threading
from typing import Iterable

from twinstudio.domain import EventEnvelope
from twinstudio.settings import Settings


class EventPublisher:
    def publish_events(self, project_id: str, events: Iterable[EventEnvelope]) -> None:
        raise NotImplementedError


class NullPublisher(EventPublisher):
    def publish_events(self, project_id: str, events: Iterable[EventEnvelope]) -> None:
        list(events)


class MqttPublisher(EventPublisher):
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        import paho.mqtt.client as mqtt

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if self.settings.mqtt_username:
            client.username_pw_set(self.settings.mqtt_username, self.settings.mqtt_password)
        client.connect(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=30)
        client.loop_start()
        self._client = client
        return client

    def publish_events(self, project_id: str, events: Iterable[EventEnvelope]) -> None:
        with self._lock:
            try:
                client = self._ensure_client()
                for event in events:
                    event_name = _topic_atom(event.event_type)
                    topic = f"{self.settings.mqtt_topic_prefix}/{project_id}/events/{event_name}"
                    payload = event.model_dump_json()
                    client.publish(
                        topic,
                        payload=payload,
                        qos=1,
                        retain=False,
                        properties=None,
                    )
            except Exception:
                # MQTT is an integration path, not the source of truth. The event store
                # remains authoritative when the broker is temporarily unavailable.
                return


def _topic_atom(value: str) -> str:
    output = []
    for char in value:
        if char.isupper() and output:
            output.append("-")
        output.append(char.lower())
    return "".join(output).replace("_", "-")


def publisher_from_settings(settings: Settings) -> EventPublisher:
    return MqttPublisher(settings) if settings.mqtt_enabled else NullPublisher()
