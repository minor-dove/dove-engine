"""Process roles: API publish-only vs worker (subscribe + planner)."""

from app.core.config import settings
from app.mqtt.client import MQTTService


class FakeClient:
    def __init__(self):
        self.subscribed = []

    def subscribe(self, topic, qos=0):
        self.subscribed.append(topic)


def test_worker_subscribes_to_all_device_topics(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_SUBSCRIBE", True)
    c = FakeClient()
    MQTTService()._on_connect(c, None, None, 0)
    assert len(c.subscribed) == 5
    assert any(t.endswith("/privacy") for t in c.subscribed)


def test_api_process_is_publish_only(monkeypatch):
    monkeypatch.setattr(settings, "MQTT_SUBSCRIBE", False)
    c = FakeClient()
    svc = MQTTService()
    svc._on_connect(c, None, None, 0)
    assert c.subscribed == [] and svc.is_connected
