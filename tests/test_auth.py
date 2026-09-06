"""P6-B: Web API token authentication."""
import os
import pytest
from fastapi.testclient import TestClient
from loom.core.store import Store


def _create_client_with_auth(token: str | None = None):
    """Create a TestClient with optional auth token configured."""
    import tempfile
    from loom.web.app import create_app
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, "test.db")
    store = Store(db_path)
    # Monkey-patch the auth token onto the app state
    app = create_app(store)
    if token is not None:
        app.state.auth_token = token
    client = TestClient(app)
    return client, tmpdir


# --- No auth configured (backwards compat) ---

def test_no_auth_token_allows_all_requests():
    """Without auth_token configured, all endpoints remain accessible."""
    client, tmpdir = _create_client_with_auth(token=None)
    try:
        resp = client.get("/api/instances")
        assert resp.status_code == 200
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


# --- Auth configured ---

def test_auth_required_returns_401_without_token():
    """With auth_token set, /api/ requests without token return 401."""
    client, tmpdir = _create_client_with_auth(token="secret123")
    try:
        resp = client.get("/api/instances")
        assert resp.status_code == 401
        assert "unauthorized" in resp.json().get("detail", "").lower()
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_auth_correct_token_allows_request():
    """With auth_token set, correct Authorization header passes."""
    client, tmpdir = _create_client_with_auth(token="secret123")
    try:
        resp = client.get("/api/instances", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_auth_wrong_token_returns_401():
    """With auth_token set, wrong token returns 401."""
    client, tmpdir = _create_client_with_auth(token="secret123")
    try:
        resp = client.get("/api/instances", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_auth_root_page_not_protected():
    """The root page (/) serves index.html even with auth configured."""
    client, tmpdir = _create_client_with_auth(token="secret123")
    try:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Loom" in resp.text
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_auth_endpoint_validates_token():
    """POST /api/auth with correct token returns OK."""
    client, tmpdir = _create_client_with_auth(token="secret123")
    try:
        resp = client.post("/api/auth", json={"token": "secret123"})
        assert resp.status_code == 200
        assert resp.json().get("ok") is True
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_auth_post_endpoints_also_protected():
    """POST /api/run also requires auth when token is set."""
    client, tmpdir = _create_client_with_auth(token="secret123")
    try:
        resp = client.post("/api/run", json={"template": "test"})
        assert resp.status_code == 401
    finally:
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


def test_auth_reads_from_env_var():
    """Auth token can be set via LOOM_AUTH_TOKEN env var."""
    os.environ["LOOM_AUTH_TOKEN"] = "env-secret"
    try:
        import tempfile
        from loom.web.app import create_app
        tmpdir = tempfile.mkdtemp()
        db_path = os.path.join(tmpdir, "test.db")
        store = Store(db_path)
        app = create_app(store)
        # If env var is read, app.state.auth_token should be set
        token = getattr(app.state, "auth_token", None)
        assert token == "env-secret", f"expected env-secret, got {token}"
        import shutil; shutil.rmtree(tmpdir, ignore_errors=True)
    finally:
        os.environ.pop("LOOM_AUTH_TOKEN", None)
