"""Tests for favicon + static asset serving (regression: /static was never mounted)."""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient
from loom.core.store import Store
from loom.web.app import create_app


def _client():
    tmpdir = tempfile.mkdtemp()
    store = Store(Path(tmpdir) / "test.db")
    app = create_app(store)
    return TestClient(app)


def test_static_favicon_svg_served():
    client = _client()
    resp = client.get("/static/favicon.svg")
    assert resp.status_code == 200
    assert "image/svg" in resp.headers.get("content-type", "").lower()
    assert b"<svg" in resp.content


def test_static_favicon_png_served():
    client = _client()
    resp = client.get("/static/favicon-32.png")
    assert resp.status_code == 200
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic bytes


def test_static_favicon_ico_served():
    client = _client()
    resp = client.get("/static/favicon.ico")
    assert resp.status_code == 200
    # ICO header: reserved 0, type 1
    assert resp.content[:4] == b"\x00\x00\x01\x00"


def test_vendor_scripts_served():
    """The graph vendor libs must be reachable or the DAG view silently breaks."""
    client = _client()
    for lib in ("cytoscape.min.js", "graphlib.min.js", "cytoscape-dagre.min.js"):
        resp = client.get(f"/static/vendor/{lib}")
        assert resp.status_code == 200, f"vendor/{lib} not served"
        assert len(resp.content) > 100, f"vendor/{lib} empty"


def test_index_html_references_static_assets():
    client = _client()
    html = client.get("/").text
    assert "/static/favicon.svg" in html
    assert "/static/vendor/cytoscape.min.js" in html
