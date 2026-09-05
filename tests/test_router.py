"""Tests for tier-based runner routing (P1-C)."""
import os
import pytest
from loom.core.models import Node
from loom.core.router import load_config, RunnerRouter
from loom.adapters.base import RunnerAdapter, Result


TOML_CONTENT = """
[routing]
critical = ["cc"]
heavy = ["codex", "cc"]
tooling = ["pi", "dsh"]
bulk = ["dsh", "pi"]

[budget]
red_line_usd = 5.0
"""


@pytest.fixture
def config_path(tmp_path):
    p = tmp_path / "loom.toml"
    p.write_text(TOML_CONTENT)
    return str(p)


class _RecordingRunner(RunnerAdapter):
    """Runner that records it was called and succeeds."""
    def __init__(self, name, fail_with=None):
        self.name = name
        self.calls = 0
        self._fail_with = fail_with

    async def run(self, node) -> Result:
        self.calls += 1
        if self._fail_with:
            raise self._fail_with
        return Result(success=True, output=self.name)


def test_load_config_parses_routing(config_path):
    cfg = load_config(config_path)
    assert cfg["routing"]["critical"] == ["cc"]
    assert cfg["routing"]["heavy"] == ["codex", "cc"]
    assert cfg["budget"]["red_line_usd"] == 5.0


def test_load_config_missing_file_returns_empty():
    cfg = load_config("nonexistent.toml")
    assert cfg == {}


def test_route_returns_tier_chain(config_path):
    cfg = load_config(config_path)
    cc = _RecordingRunner("cc")
    codex = _RecordingRunner("codex")
    router = RunnerRouter(cfg, {"cc": cc, "codex": codex})

    node = Node(id="n1", instance_id="i1", template_id="t", tier="heavy")
    assert router.route(node) == ["codex", "cc"]


def test_run_picks_first_available_runner(config_path):
    cfg = load_config(config_path)
    codex = _RecordingRunner("codex")
    cc = _RecordingRunner("cc")
    router = RunnerRouter(cfg, {"cc": cc, "codex": codex})

    node = Node(id="n1", instance_id="i1", template_id="t", tier="heavy")
    import asyncio
    result = asyncio.run(router.run(node))

    assert result.success is True
    assert result.output == "codex"  # first in heavy chain
    assert codex.calls == 1
    assert cc.calls == 0


def test_run_falls_back_on_missing_binary(config_path):
    """If the primary runner's binary is absent (FileNotFoundError), try next."""
    cfg = load_config(config_path)
    codex = _RecordingRunner("codex", fail_with=FileNotFoundError("codex not found"))
    cc = _RecordingRunner("cc")
    router = RunnerRouter(cfg, {"cc": cc, "codex": codex})

    node = Node(id="n1", instance_id="i1", template_id="t", tier="heavy")
    import asyncio
    result = asyncio.run(router.run(node))

    assert result.success is True
    assert result.output == "cc"  # fell back
    assert codex.calls == 1
    assert cc.calls == 1


def test_run_does_not_fall_back_on_task_failure(config_path):
    """A runner that reports a failed Result (exit code != 0) is NOT retried
    on the next runner — task failures have side effects."""
    cfg = load_config(config_path)

    class _FailingRunner(RunnerAdapter):
        name = "codex"
        def __init__(self): self.calls = 0
        async def run(self, node):
            self.calls += 1
            return Result(success=False, exit_code=1)

    codex = _FailingRunner()
    cc = _RecordingRunner("cc")
    router = RunnerRouter(cfg, {"cc": cc, "codex": codex})

    node = Node(id="n1", instance_id="i1", template_id="t", tier="heavy")
    import asyncio
    result = asyncio.run(router.run(node))

    assert result.success is False
    assert cc.calls == 0  # no fallback for genuine failures


def test_unknown_tier_uses_tooling_default(config_path):
    cfg = load_config(config_path)
    pi = _RecordingRunner("pi")
    dsh = _RecordingRunner("dsh")
    router = RunnerRouter(cfg, {"pi": pi, "dsh": dsh})

    node = Node(id="n1", instance_id="i1", template_id="t", tier="bogus")
    assert router.route(node) == cfg["routing"]["tooling"]


def test_all_runners_missing_raises(config_path):
    cfg = load_config(config_path)
    codex = _RecordingRunner("codex", fail_with=FileNotFoundError())
    cc = _RecordingRunner("cc", fail_with=FileNotFoundError())
    router = RunnerRouter(cfg, {"cc": cc, "codex": codex})

    node = Node(id="n1", instance_id="i1", template_id="t", tier="heavy")
    import asyncio
    with pytest.raises(RuntimeError, match="no available runner"):
        asyncio.run(router.run(node))


def test_red_line_from_config(config_path):
    cfg = load_config(config_path)
    router = RunnerRouter(cfg, {})
    assert router.red_line_usd == 5.0


def test_red_line_default_when_absent():
    router = RunnerRouter({"routing": {}}, {})
    assert router.red_line_usd == 5.0


def test_cli_make_runner_auto_builds_router(tmp_path, monkeypatch):
    """_make_runner('auto') returns a RunnerRouter wired to loom.toml routing."""
    from loom.cli import _make_runner
    from loom.core.router import RunnerRouter
    cfg = tmp_path / "loom.toml"
    cfg.write_text(TOML_CONTENT)
    runner = _make_runner("auto", str(cfg))
    assert isinstance(runner, RunnerRouter)
    # heavy tier should resolve to a real cc or codex adapter
    node = Node(id="n1", instance_id="i1", template_id="t", tier="critical")
    assert runner.route(node) == ["cc"]


def test_cli_make_runner_auto_requires_routing(tmp_path):
    from loom.cli import _make_runner
    import click
    empty = tmp_path / "empty.toml"
    empty.write_text("[budget]\nred_line_usd = 3.0\n")
    with pytest.raises(click.UsageError):
        _make_runner("auto", str(empty))


def test_cron_digest_uses_configured_threshold(tmp_path):
    """build_digest honors a custom threshold passed in."""
    import asyncio
    from loom.triggers.cron import build_digest
    from loom.core.store import Store
    from loom.core.models import Instance
    db = str(tmp_path / "t.db")
    with Store(db) as store:
        store.create_instance(Instance(id="i1", template_id="t", status="succeeded", cost_usd=3.0))
        # Default threshold 5.0 -> not over budget
        d_default = build_digest(store)
        # Custom threshold 2.0 -> over budget
        d_custom = build_digest(store, threshold=2.0)
    assert d_default["over_budget"] == []
    assert len(d_custom["over_budget"]) == 1
