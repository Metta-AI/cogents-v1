from fastapi.testclient import TestClient
from dashboard.app import create_app


def test_all_rest_endpoints_registered():
    """Verify every REST endpoint is routed (not 404)."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)

    endpoints = [
        ("GET", "/api/cogents/test/status?range=1h"),
        ("GET", "/api/cogents/test/programs"),
        ("GET", "/api/cogents/test/sessions"),
        ("GET", "/api/cogents/test/events?range=1h"),
        ("GET", "/api/cogents/test/triggers"),
        ("GET", "/api/cogents/test/memory"),
        ("GET", "/api/cogents/test/tasks"),
        ("GET", "/api/cogents/test/channels"),
        ("GET", "/api/cogents/test/alerts"),
        ("GET", "/api/cogents/test/resources"),
    ]

    for method, path in endpoints:
        resp = client.request(method, path)
        # Should NOT be 404 (route exists) or 405 (wrong method)
        assert resp.status_code != 404, f"{method} {path} returned 404"
        assert resp.status_code != 405, f"{method} {path} returned 405"


def test_healthz():
    app = create_app()
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_websocket_endpoint():
    app = create_app()
    client = TestClient(app)
    with client.websocket_connect("/ws/cogents/test") as ws:
        ws.send_text("ping")


def test_trigger_toggle_endpoint():
    """POST endpoint exists and accepts JSON body."""
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/cogents/test/triggers/toggle",
        json={"ids": [], "enabled": True},
    )
    # Should not be 404 or 405 (route exists)
    assert resp.status_code != 404
    assert resp.status_code != 405
