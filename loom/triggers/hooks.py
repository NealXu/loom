"""CC hooks HTTP receiver — aiohttp app that records inbound hook events."""

import json
from aiohttp import web
from loom.core.models import Event


def process_hook(store, payload: dict) -> Event:
    """Validate *payload* and record it as an events row with source='hook'.

    Returns the created Event. Raises ValueError on empty / non-dict input.
    """
    if not isinstance(payload, dict) or not payload:
        raise ValueError("payload must be a non-empty dict")

    event = Event(
        source="hook",
        payload=payload,
        consumed_by_instance=payload.get("session_id", ""),
    )
    store.create_event(event)
    return event


def create_app(store) -> web.Application:
    """Return an aiohttp Application with a POST /hook route."""

    async def hook_handler(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "invalid JSON"}, status=400)

        try:
            process_hook(store, body)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

        return web.json_response({"ok": True}, status=200)

    app = web.Application()
    app.router.add_post("/hook", hook_handler)
    return app
