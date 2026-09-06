"""Tests for P5-B: SSE frontend EventSource integration in the web UI.

These are structural/regex tests over the raw index.html, matching the
approach in tests/test_frontend_dag.py — the frontend is a single vanilla-JS
file with no build step or DOM test harness available under pytest, so we
assert on the source text rather than executing it.
"""
import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "loom" / "web" / "static" / "index.html"


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_eventsource_used():
    """JS opens an EventSource against the /api/events/stream SSE endpoint."""
    html = _read_html()
    assert "new EventSource" in html, (
        "frontend does not construct an EventSource to consume the SSE stream"
    )
    assert "/api/events/stream" in html, (
        "frontend does not reference the SSE endpoint /api/events/stream"
    )


def test_sse_reconnect_logic():
    """JS attaches an error/reconnect handler to the event source."""
    html = _read_html()
    has_onerror = re.search(r"\.onerror\s*=", html) is not None
    has_error_listener = re.search(r"""addEventListener\(\s*["']error["']""", html) is not None
    assert has_onerror or has_error_listener, (
        "frontend does not handle SSE errors/reconnection "
        "(no .onerror and no 'error' addEventListener)"
    )


def test_sse_triggers_refresh():
    """The SSE message handler triggers a (debounced) data refresh."""
    html = _read_html()

    # A message handler is attached to the event source.
    has_onmessage = re.search(r"\.onmessage\s*=", html) is not None
    has_message_listener = re.search(r"""addEventListener\(\s*["']message["']""", html) is not None
    assert has_onmessage or has_message_listener, (
        "frontend does not attach an SSE message handler "
        "(no .onmessage and no 'message' addEventListener)"
    )

    # The handler schedules or performs a refresh.
    triggers = (
        re.search(r"onmessage[\s\S]{0,200}?(scheduleRefresh|refreshData)", html)
        or re.search(
            r"""addEventListener\(\s*["']message["'][\s\S]{0,200}?(scheduleRefresh|refreshData)""",
            html,
        )
    )
    assert triggers, "SSE message handler does not trigger a data refresh"

    # A reusable refresh function exists that re-fetches the endpoints.
    assert re.search(r"function\s+refreshData\s*\(", html), (
        "no reusable refreshData() function to re-fetch data"
    )


def test_sse_debounce():
    """SSE-triggered refreshes are debounced/throttled to avoid hammering."""
    html = _read_html()

    # A scheduler coalesces bursts of events into a throttled refresh.
    has_scheduler = (
        re.search(r"function\s+scheduleRefresh\s*\(", html) is not None
        or "debounce" in html.lower()
        or "throttle" in html.lower()
    )
    assert has_scheduler, "no debounce/throttle scheduler for SSE-triggered refreshes"

    # The scheduler guards with a timer or a timestamp.
    has_timer = "setTimeout" in html
    has_ts_guard = re.search(r"Date\.now\(\)", html) is not None
    assert has_timer or has_ts_guard, (
        "SSE refresh scheduler uses neither a setTimeout nor a timestamp guard"
    )

    # The scheduler ultimately calls the refresh.
    assert re.search(r"scheduleRefresh[\s\S]{0,400}?refreshData", html), (
        "scheduler does not ultimately call refreshData()"
    )
