"""P6-A: Vendored Cytoscape + dagre layout."""
import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "loom" / "web" / "static" / "index.html"
VENDOR_DIR = Path(__file__).resolve().parent.parent / "loom" / "web" / "static" / "vendor"


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def test_no_cdn_scripts():
    """HTML does NOT load Cytoscape from external CDN."""
    html = _read_html()
    assert "cdn.jsdelivr.net" not in html
    assert "cdnjs.cloudflare.com" not in html
    assert "unpkg.com" not in html


def test_vendor_cytoscape_exists():
    """Cytoscape minified JS exists in static/vendor/."""
    assert (VENDOR_DIR / "cytoscape.min.js").exists()


def test_vendor_dagre_exists():
    """cytoscape-dagre minified JS exists in static/vendor/."""
    assert (VENDOR_DIR / "cytoscape-dagre.min.js").exists()


def test_vendor_graphlib_exists():
    """graphlib (dagre dependency) minified JS exists in static/vendor/."""
    assert (VENDOR_DIR / "graphlib.min.js").exists()


def test_dagre_layout_configured():
    """HTML JS uses 'dagre' layout instead of 'cose'."""
    html = _read_html()
    assert '"dagre"' in html or "'dagre'" in html


def test_dagre_layout_options():
    """Dagre layout includes rankDir: TB (top-to-bottom)."""
    html = _read_html()
    assert "rankDir" in html
    assert "TB" in html
