"""P6-E: Template installer — fetch/copy + validate + save to discovered/."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from tempfile import NamedTemporaryFile


def fetch_template_url(url: str) -> str:
    """Fetch template content from URL. Separated for testability."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        return resp.read().decode("utf-8")


def install_template(source: str, out_dir: str, force: bool = False) -> str:
    """Install a template from a local path or URL.

    Returns the path to the installed template file.
    Raises ValueError if the template is invalid or would overwrite.
    """
    from loom.core.loader import load_template

    # Fetch content
    if source.startswith("http://") or source.startswith("https://"):
        content = fetch_template_url(source)
    else:
        content = Path(source).read_text(encoding="utf-8")

    # Validate via load_template (uses a temp file so load_template can parse)
    tmp_path = None
    try:
        with NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_path = f.name
        tpl = load_template(tmp_path)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    # Determine output path
    out_path = Path(out_dir) / f"{tpl.id}.yaml"
    if out_path.exists() and not force:
        raise ValueError(
            f"Template '{tpl.id}' already exists at {out_path}. Use --force to overwrite."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    return str(out_path)
