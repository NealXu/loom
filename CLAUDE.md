# Loom — Claude Code Project Instructions

## Git Push

HTTPS push to `https://github.com/NealXu/loom.git` consistently fails with `Connection was reset`.
Use **SSH** instead:

```bash
git remote set-url origin git@github.com:NealXu/loom.git
# or temporarily: git push git@github.com:NealXu/loom.git <branch>
```

Alternatively, `gh repo sync` works.

## Deploy

Production deployment lives at `D:\Deploys\loom` with an isolated venv (`.venv`).
Deploy steps:
1. `robocopy D:\Codes\innovation\loom D:\Deploys\loom /MIR /XD .git __pycache__ .pytest_cache loom.egg-info .claude vault_out .venv .worktrees /XF loom.db loom.db-wal loom.db-shm loom_dev.db-shm loom_dev.db-wal loom_check.db-shm loom_check.db-wal *.pyc`
2. `pip install -e D:\Deploys\loom` (editable — package-data is not declared in pyproject.toml, so wheel install misses `web/static/`)
3. `loom serve --runner auto --config loom.toml --templates loom/templates --db loom.db`

## Known: package-data

`pyproject.toml` is missing `[tool.setuptools.package-data]` for `loom.web.static`. Non-editable installs break the web UI. Either fix pyproject.toml or stick with `-e` install.
