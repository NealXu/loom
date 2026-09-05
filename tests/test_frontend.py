"""Tests for the web UI frontend static asset."""

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "loom" / "web" / "static"
INDEX_HTML = STATIC_DIR / "index.html"


def test_index_html_exists():
    """index.html exists and is non-empty."""
    assert INDEX_HTML.exists(), "loom/web/static/index.html does not exist"
    assert INDEX_HTML.stat().st_size > 0, "index.html is empty"


def test_index_html_has_container_ids():
    """The file contains the required element IDs."""
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="app"' in content, "missing id=\"app\""
    assert 'id="instances"' in content, "missing id=\"instances\""
    assert 'id="graph"' in content, "missing id=\"graph\""
    assert 'id="status"' in content, "missing id=\"status\""


def test_index_html_consumes_backend():
    """The file fetches from the backend API endpoints."""
    content = INDEX_HTML.read_text(encoding="utf-8")
    assert "/api/instances" in content or "/api/graph" in content, (
        "index.html does not reference a backend API endpoint"
    )
    assert "fetch(" in content, "index.html does not call fetch()"


def test_index_html_has_red_cost_threshold():
    """The file highlights instances with cost_usd >= 5 in red."""
    content = INDEX_HTML.read_text(encoding="utf-8")
    # Look for a cost threshold comparison involving 5
    assert (
        ">= 5" in content or "> 5" in content or ">=5" in content
    ), "index.html does not define a red-highlight cost threshold of 5"
