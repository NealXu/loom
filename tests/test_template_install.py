"""P6-E: Template marketplace — loom install command."""
import os
import json
import pytest
from unittest.mock import patch
from click.testing import CliRunner


VALID_TEMPLATE_YAML = """
id: community-deploy
version: 1
trigger: [cli]
provenance: community
params:
  target: {type: string, required: true}
nodes:
  - id: preflight
    kind: analysis
    tier: heavy
    spec: "Check {{target}} is ready"
    depends_on: []
  - id: deploy
    kind: deploy
    tier: critical
    gate: approve
    spec: "Deploy {{target}}"
    depends_on: [preflight]
"""

INVALID_TEMPLATE_YAML = """
id: broken
# missing version, trigger, nodes
foo: bar
"""


def test_install_from_local_path(tmp_path):
    """loom install copies a local YAML file to discovered/ and validates."""
    from loom.cli import main

    tpl_file = tmp_path / "my-template.yaml"
    tpl_file.write_text(VALID_TEMPLATE_YAML, encoding="utf-8")

    out_dir = tmp_path / "loom" / "templates" / "discovered"
    out_dir.mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(main, ["install", str(tpl_file), "--out", str(out_dir)])
    assert result.exit_code == 0, f"CLI failed: {result.output}"

    installed = out_dir / "community-deploy.yaml"
    assert installed.exists()
    # Validate the installed template
    from loom.core.loader import load_template
    tpl = load_template(str(installed))
    assert tpl.id == "community-deploy"
    assert len(tpl.nodes) == 2


def test_install_rejects_invalid_template(tmp_path):
    """loom install refuses to save an invalid template."""
    from loom.cli import main

    tpl_file = tmp_path / "bad.yaml"
    tpl_file.write_text(INVALID_TEMPLATE_YAML, encoding="utf-8")

    out_dir = tmp_path / "loom" / "templates" / "discovered"
    out_dir.mkdir(parents=True)

    runner = CliRunner()
    result = runner.invoke(main, ["install", str(tpl_file), "--out", str(out_dir)])
    assert result.exit_code != 0, "Should reject invalid template"


def test_install_from_url(tmp_path):
    """loom install can fetch from URL (mocked HTTP)."""
    from loom.cli import main

    out_dir = tmp_path / "loom" / "templates" / "discovered"
    out_dir.mkdir(parents=True)

    def mock_fetch(url):
        return VALID_TEMPLATE_YAML

    with patch("loom.core.installer.fetch_template_url", side_effect=mock_fetch):
        runner = CliRunner()
        result = runner.invoke(main, ["install", "https://example.com/template.yaml", "--out", str(out_dir)])
        assert result.exit_code == 0

    installed = out_dir / "community-deploy.yaml"
    assert installed.exists()


def test_install_overwrite_protection(tmp_path):
    """loom install refuses to overwrite an existing template without --force."""
    from loom.cli import main

    tpl_file = tmp_path / "my-template.yaml"
    tpl_file.write_text(VALID_TEMPLATE_YAML, encoding="utf-8")

    out_dir = tmp_path / "loom" / "templates" / "discovered"
    out_dir.mkdir(parents=True)
    (out_dir / "community-deploy.yaml").write_text("existing", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["install", str(tpl_file), "--out", str(out_dir)])
    assert result.exit_code != 0, "Should not overwrite without --force"


def test_install_force_overwrite(tmp_path):
    """loom install --force overwrites existing template."""
    from loom.cli import main

    tpl_file = tmp_path / "my-template.yaml"
    tpl_file.write_text(VALID_TEMPLATE_YAML, encoding="utf-8")

    out_dir = tmp_path / "loom" / "templates" / "discovered"
    out_dir.mkdir(parents=True)
    (out_dir / "community-deploy.yaml").write_text("existing", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["install", str(tpl_file), "--out", str(out_dir), "--force"])
    assert result.exit_code == 0

    content = (out_dir / "community-deploy.yaml").read_text(encoding="utf-8")
    assert "community-deploy" in content
