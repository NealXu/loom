"""Tests for i18n (internationalization) support in the web UI."""
import json
import re
from pathlib import Path


def test_html_has_data_i18n_attributes():
    """Verify HTML contains data-i18n attributes for translatable text."""
    html_path = Path(__file__).parent.parent / "loom" / "web" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    # Check for data-i18n attributes on key elements
    assert 'data-i18n="nav.dashboard"' in html
    assert 'data-i18n="nav.run"' in html
    assert 'data-i18n="nav.history"' in html
    assert 'data-i18n="nav.audit"' in html
    assert 'data-i18n="nav.cost"' in html
    assert 'data-i18n="nav.digest"' in html
    assert 'data-i18n="nav.templates"' in html

    # Panel headers
    assert 'data-i18n="panel.instances"' in html
    assert 'data-i18n="panel.gates"' in html
    assert 'data-i18n="panel.graph"' in html

    # Buttons
    assert 'data-i18n="btn.run_template"' in html
    assert 'data-i18n="btn.close"' in html


def test_html_has_language_switcher():
    """Verify HTML contains a language switcher element."""
    html_path = Path(__file__).parent.parent / "loom" / "web" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    # Language switcher should exist
    assert 'id="language-switcher"' in html or 'class="language-switcher"' in html

    # Should have buttons/links for zh and en
    assert 'data-lang="zh"' in html or 'lang="zh"' in html
    assert 'data-lang="en"' in html or 'lang="en"' in html


def test_html_has_i18n_script():
    """Verify HTML contains i18n initialization script."""
    html_path = Path(__file__).parent.parent / "loom" / "web" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    # Should have i18n module/function
    assert "function applyI18n" in html or "function switchLanguage" in html or "const i18n" in html

    # Should reference localStorage for language preference
    assert "localStorage" in html


def test_translation_keys_complete():
    """Verify all translatable text has corresponding translation keys."""
    html_path = Path(__file__).parent.parent / "loom" / "web" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    # Extract all data-i18n keys
    i18n_pattern = r'data-i18n="([^"]+)"'
    keys = re.findall(i18n_pattern, html)

    assert len(keys) > 20, f"Expected at least 20 i18n keys, found {len(keys)}"

    # Verify key structure (should be like "nav.dashboard", "btn.run_template")
    for key in keys:
        assert "." in key, f"Key '{key}' should have format 'section.key'"


def test_html_default_lang_is_zh():
    """Verify default language preference is Chinese."""
    html_path = Path(__file__).parent.parent / "loom" / "web" / "static" / "index.html"
    html = html_path.read_text(encoding="utf-8")

    # Should default to 'zh' if no localStorage preference
    assert "'zh'" in html or '"zh"' in html

    # Should check localStorage for language preference
    assert "getItem" in html
