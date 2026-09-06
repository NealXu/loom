"""Webhook notifications for instance state transitions (P6-D)."""
from __future__ import annotations
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def http_post(url: str, json_data: dict, timeout: float = 5.0):
    """Default HTTP POST implementation. Patchable for tests."""
    try:
        import urllib.request
        req = urllib.request.Request(
            url,
            data=json.dumps(json_data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp
    except Exception as e:
        logger.warning(f"webhook POST to {url} failed: {e}")
        return None


def send_notification(config: dict, event_type: str, instance) -> None:
    """Send webhook notifications for an instance event.

    config: {"webhooks": [{"url": "...", "secret": "..."}]}
    event_type: "instance_succeeded" | "instance_failed"
    instance: Instance dataclass (or dict-like with id, title, status, cost_usd)
    """
    webhooks = config.get("webhooks", [])
    if not webhooks:
        return

    # Support both dataclass instances and dict-like objects
    if isinstance(instance, dict):
        instance_id = instance.get("id", "")
        title = instance.get("title", "")
        status = instance.get("status", "")
        cost_usd = instance.get("cost_usd", 0)
    else:
        instance_id = getattr(instance, "id", "")
        title = getattr(instance, "title", "")
        status = getattr(instance, "status", "")
        cost_usd = getattr(instance, "cost_usd", 0)

    payload = {
        "event_type": event_type,
        "instance_id": instance_id,
        "title": title,
        "status": status,
        "cost_usd": cost_usd,
        "timestamp": datetime.now().isoformat(),
    }

    for wh in webhooks:
        url = wh.get("url", "")
        if not url:
            continue
        try:
            resp = http_post(url, payload)
            if resp and hasattr(resp, "status_code") and resp.status_code >= 400:
                logger.warning(f"webhook {url} returned {resp.status_code}")
        except Exception as e:
            logger.error(f"webhook {url} failed: {e}")
