"""P6-D: Webhook notifications on instance state transitions."""
import json
import pytest
from unittest.mock import patch, MagicMock
from loom.core.store import Store
from loom.core.models import Instance


def test_send_notification_posts_to_webhook(tmp_path):
    """send_notification POSTs JSON to configured webhook URLs."""
    from loom.notifications import send_notification
    store = Store(str(tmp_path / "t.db"))
    store.create_instance(Instance(id="i1", title="Test", template_id="t", status="succeeded"))

    received = []
    def mock_post(url, json_data, timeout=5):
        received.append((url, json_data))
        return MagicMock(status_code=200)

    with patch("loom.notifications.http_post", side_effect=mock_post):
        config = {"webhooks": [{"url": "https://example.com/hook", "secret": None}]}
        send_notification(config, "instance_succeeded", store.get_instance("i1"))

    assert len(received) == 1
    url, data = received[0]
    assert url == "https://example.com/hook"
    assert data["event_type"] == "instance_succeeded"
    assert data["instance_id"] == "i1"


def test_no_notification_when_no_webhooks(tmp_path):
    """No webhooks configured -> no HTTP calls."""
    from loom.notifications import send_notification
    store = Store(str(tmp_path / "t.db"))
    store.create_instance(Instance(id="i2", title="Test", template_id="t", status="succeeded"))

    with patch("loom.notifications.http_post") as mock_post:
        send_notification({}, "instance_succeeded", store.get_instance("i2"))
        mock_post.assert_not_called()


def test_multiple_webhooks_all_notified(tmp_path):
    """Multiple webhook URLs all receive the notification."""
    from loom.notifications import send_notification
    store = Store(str(tmp_path / "t.db"))
    store.create_instance(Instance(id="i3", title="Test", template_id="t", status="failed"))

    received_urls = []
    def mock_post(url, json_data, timeout=5):
        received_urls.append(url)
        return MagicMock(status_code=200)

    with patch("loom.notifications.http_post", side_effect=mock_post):
        config = {"webhooks": [
            {"url": "https://a.example.com/hook"},
            {"url": "https://b.example.com/hook"},
        ]}
        send_notification(config, "instance_failed", store.get_instance("i3"))

    assert received_urls == ["https://a.example.com/hook", "https://b.example.com/hook"]


def test_notification_payload_structure(tmp_path):
    """Notification payload has required fields."""
    from loom.notifications import send_notification
    store = Store(str(tmp_path / "t.db"))
    store.create_instance(Instance(id="i4", title="Payload Test", template_id="t",
                                    status="succeeded", cost_usd=1.23))

    received = []
    def mock_post(url, json_data, timeout=5):
        received.append(json_data)
        return MagicMock(status_code=200)

    with patch("loom.notifications.http_post", side_effect=mock_post):
        config = {"webhooks": [{"url": "https://example.com/hook"}]}
        send_notification(config, "instance_succeeded", store.get_instance("i4"))

    payload = received[0]
    assert "event_type" in payload
    assert "instance_id" in payload
    assert "title" in payload
    assert "status" in payload
    assert "cost_usd" in payload
    assert "timestamp" in payload


def test_webhook_failure_does_not_break_flow(tmp_path):
    """If a webhook returns 500, notification still completes (no exception)."""
    from loom.notifications import send_notification
    store = Store(str(tmp_path / "t.db"))
    store.create_instance(Instance(id="i5", title="Test", template_id="t", status="succeeded"))

    def mock_post(url, json_data, timeout=5):
        return MagicMock(status_code=500, text="Internal Server Error")

    with patch("loom.notifications.http_post", side_effect=mock_post):
        config = {"webhooks": [{"url": "https://example.com/hook"}]}
        # Should not raise
        send_notification(config, "instance_succeeded", store.get_instance("i5"))
