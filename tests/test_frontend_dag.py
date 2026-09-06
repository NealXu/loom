"""Tests for Cytoscape DAG visualization in the web frontend."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "loom" / "web" / "static" / "index.html"


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_cytoscape_cdn_loaded():
    """HTML includes Cytoscape.js from CDN."""
    html = _read_html()
    assert "cytoscape" in html.lower()
    assert re.search(r'<script[^>]*src=["\'][^"\']*cytoscape[^"\']*["\']', html, re.IGNORECASE)


def test_cytoscape_container_exists():
    """HTML has a #cytoscape-container div for the graph to render into."""
    html = _read_html()
    assert re.search(r'id=["\']cytoscape-container["\']', html)


def test_node_detail_panel_exists():
    """HTML has a #node-detail div for showing node info on click."""
    html = _read_html()
    assert re.search(r'id=["\']node-detail["\']', html)


def test_status_color_mapping():
    """JS includes a statusToColor function mapping status to colors."""
    html = _read_html()
    assert "statusToColor" in html or "status_color" in html.lower()


def test_cytoscape_init_function():
    """JS includes an initCytoscape function or cytoscape() initialization call."""
    html = _read_html()
    assert "initCytoscape" in html or "cytoscape(" in html
