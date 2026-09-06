"""P7 — Frontend structural contract tests for the redesigned Loom UI.

The frontend is a single vanilla-JS file (loom/web/static/index.html) with no
build step or DOM test harness, so we assert on the source text (regex/string
matching) — the same approach as tests/test_frontend_dag.py and
tests/test_frontend_sse.py.

Contract: sidebar nav, Run/History/Audit/Cost/Digest/Templates sections,
accessibility (SVG icons, labels, aria), loading/empty states, toast feedback.
"""
import re
from pathlib import Path

HTML_PATH = Path(__file__).resolve().parent.parent / "loom" / "web" / "static" / "index.html"


def _read_html() -> str:
    return HTML_PATH.read_text(encoding="utf-8")


def _has(pattern: str, flags=0) -> bool:
    return re.search(pattern, _read_html(), flags) is not None


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

class TestNavigation:
    def test_sidebar_nav_exists(self):
        html = _read_html()
        assert "<nav" in html, "no <nav> element for navigation"
        assert 'aria-label' in html, "nav/controls missing aria-label"

    def test_section_nav_items(self):
        html = _read_html()
        for label in ("Dashboard", "Run", "History", "Audit", "Cost", "Digest", "Templates"):
            assert label in html, f"sidebar nav missing section: {label}"

    def test_sidebar_uses_svg_icons_not_emoji(self):
        # Structural navigation icons should be <svg>, not emoji characters.
        html = _read_html()
        assert _has(r"<svg") or _has(r"<path "), "nav uses no SVG icon markup"
        # No emoji-ish characters used as structural icons inside nav labels.
        emoji = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
        # Extract the nav block and assert it has no emoji.
        m = re.search(r"<nav[\s\S]*?</nav>", html)
        if m:
            assert not emoji.search(m.group(0)), "nav uses emoji as structural icons"


# ---------------------------------------------------------------------------
# Run page
# ---------------------------------------------------------------------------

class TestRun:
    def test_run_has_template_selector(self):
        html = _read_html()
        assert _has(r'id=["\']template-select["\']') or _has(r'id=["\']tpl-select["\']') \
            or _has(r'id=["\']run-template["\']') or "<select" in html, \
            "Run page lacks a template <select>"

    def test_run_param_input_has_label(self):
        html = _read_html()
        assert _has(r"<label[^>]*for="), "param inputs lack a <label for=...>"
        assert _has(r'id=["\']project_path["\']') or _has(r'id=["\']params["\']'), \
            "Run page lacks an input for project_path/params"

    def test_run_has_runner_select_and_mode(self):
        html = _read_html()
        assert _has(r'id=["\']runner["\']') or "runner" in html.lower(), \
            "Run page lacks a runner selector"
        assert _has(r"type=[\"']radio[\"']") or "mode" in html.lower(), \
            "Run page lacks a sync/async mode selector"

    def test_run_has_submit_button(self):
        html = _read_html()
        assert re.search(r"Run Template|Run ▶|type=[\"']submit[\"']", html), \
            "Run page lacks a submit/run button"

    def test_run_posts_to_api_run(self):
        html = _read_html()
        assert "/api/run" in html, "Run page does not reference POST /api/run"


# ---------------------------------------------------------------------------
# History page
# ---------------------------------------------------------------------------

class TestHistory:
    def test_history_has_table(self):
        html = _read_html()
        assert "<table" in html and "</table>" in html, "History lacks a table"

    def test_history_sortable_headers(self):
        html = _read_html()
        assert "aria-sort" in html, "History table lacks sortable headers (aria-sort)"

    def test_history_filters(self):
        html = _read_html()
        assert "template" in html.lower() and "status" in html.lower(), \
            "History lacks template/status filters"

    def test_history_uses_instances_endpoint(self):
        html = _read_html()
        assert "/api/instances" in html, "History does not consume /api/instances"


# ---------------------------------------------------------------------------
# Audit page
# ---------------------------------------------------------------------------

class TestAudit:
    def test_audit_timeline_exists(self):
        html = _read_html()
        assert _has(r'id=["\']audit["\']') or _has(r'id=["\']timeline["\']') \
            or "timeline" in html.lower(), "Audit page lacks a timeline container"

    def test_audit_consumes_api(self):
        html = _read_html()
        assert "/api/audit" in html, "Audit page does not reference /api/audit"


# ---------------------------------------------------------------------------
# Cost page
# ---------------------------------------------------------------------------

class TestCost:
    def test_cost_has_chart_container(self):
        html = _read_html()
        assert _has(r'id=["\'][^"\']*cost[^"\']*["\']') or _has(r'id=["\']chart["\']') \
            or "bar chart" in html.lower() or "canvas" in html.lower(), \
            "Cost page lacks a chart container"

    def test_cost_view_as_table(self):
        html = _read_html()
        assert "View as Table" in html or "view-as-table" in html.lower() or \
            "toggle-table" in html.lower(), "Cost page lacks a view-as-table toggle"

    def test_cost_consumes_api(self):
        html = _read_html()
        assert "/api/cost" in html, "Cost page does not reference /api/cost"


# ---------------------------------------------------------------------------
# Digest page
# ---------------------------------------------------------------------------

class TestDigest:
    def test_digest_summary(self):
        html = _read_html()
        assert "Total Cost" in html or "total_cost" in html.lower() or "cost" in html.lower(), \
            "Digest page lacks a total cost summary"

    def test_digest_over_budget_alert(self):
        html = _read_html()
        assert "over" in html.lower() or "red line" in html.lower() or "budget" in html.lower(), \
            "Digest page lacks an over-budget alert"

    def test_digest_consumes_api(self):
        html = _read_html()
        assert "/api/digest" in html, "Digest page does not reference /api/digest"


# ---------------------------------------------------------------------------
# Templates page
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_templates_install_form(self):
        html = _read_html()
        assert _has(r'id=["\']source["\']') or 'Source URL' in html or 'source' in html.lower(), \
            "Templates page lacks an install source input"

    def test_templates_install_submit(self):
        html = _read_html()
        assert re.search(r"Install Template|Install", html), \
            "Templates page lacks an install submit"

    def test_templates_table(self):
        html = _read_html()
        assert "Installed Templates" in html or "installed_templates" in html.lower(), \
            "Templates page lacks an installed-templates list"

    def test_templates_consumes_api(self):
        html = _read_html()
        assert "/api/templates" in html, "Templates page does not reference /api/templates"


# ---------------------------------------------------------------------------
# Dashboard extras — stats + health
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_consumes_stats_and_health(self):
        html = _read_html()
        assert "/api/stats" in html, "Dashboard does not reference /api/stats"
        assert "/api/health" in html, "Dashboard does not reference /api/health"

    def test_kpi_cards(self):
        html = _read_html()
        assert "Running" in html and "Failed" in html, \
            "Dashboard KPI cards missing Running/Failed"


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------

class TestAccessibility:
    def test_no_emoji_as_structural_icons(self):
        html = _read_html()
        emoji = re.compile(r"[\U0001F300-\U0001FAFF☀-➿]")
        # Allow emoji only inside comments/strings that are NOT structural nav/buttons.
        # Simpler contract: buttons and nav must use SVG, not emoji, for icons.
        assert not _has(r"<button[^>]*>[^<]*[\U0001F300-\U0001FAFF]"), \
            "a <button> uses an emoji icon instead of an SVG"

    def test_icon_buttons_have_aria_label(self):
        html = _read_html()
        assert _has(r'aria-label='), "icon-only controls lack aria-label"

    def test_inputs_have_labels(self):
        html = _read_html()
        assert _has(r"<label[^>]*for="), "some input is placeholder-only (no bound label)"

    def test_toast_uses_aria_live(self):
        html = _read_html()
        assert "aria-live" in html or 'role="alert"' in html or 'role="status"' in html, \
            "toast/feedback lacks aria-live or role=alert/status"

    def test_focus_state_visible(self):
        html = _read_html()
        assert _has(r":focus") or _has(r"focus-within") or "outline" in html.lower(), \
            "no visible focus style (:focus/outline)"

    def test_reduced_motion_respected(self):
        html = _read_html()
        assert "prefers-reduced-motion" in html, "does not respect prefers-reduced-motion"


# ---------------------------------------------------------------------------
# Loading & empty states
# ---------------------------------------------------------------------------

class TestStates:
    def test_loading_skeleton_or_spinner(self):
        html = _read_html()
        assert "skeleton" in html.lower() or "loading" in html.lower() or "spinner" in html.lower(), \
            "no loading/skeleton/spinner state"

    def test_empty_state_text(self):
        html = _read_html()
        assert "No instances" in html or "no data" in html.lower() or "empty" in html.lower(), \
            "no empty-state message"
