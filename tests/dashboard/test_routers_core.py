"""Tests for status, programs, and sessions routers."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from dashboard.app import create_app

_HAS_DB = bool(os.environ.get("TEST_DATABASE_URL"))


# ---------------------------------------------------------------------------
# Route registration tests (no DB required)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


def test_status_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/status")
    # Without a running DB the handler will fail, but a 404 would mean
    # the route is not registered at all.
    assert resp.status_code != 404


def test_programs_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/programs")
    assert resp.status_code != 404


def test_program_executions_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/programs/my-skill/executions")
    assert resp.status_code != 404


def test_sessions_route_registered(client: TestClient):
    resp = client.get("/api/cogents/test-cogent/sessions")
    assert resp.status_code != 404


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

def test_status_interval_mapping():
    from dashboard.routers.status import _interval
    assert _interval("1m") == "1 minute"
    assert _interval("10m") == "10 minutes"
    assert _interval("1h") == "1 hour"
    assert _interval("24h") == "24 hours"
    assert _interval("1w") == "7 days"
    assert _interval("unknown") == "1 hour"


def test_try_parse_json_programs():
    from dashboard.routers.programs import _try_parse_json
    assert _try_parse_json(None) is None
    assert _try_parse_json({"a": 1}) == {"a": 1}
    assert _try_parse_json([1, 2]) == [1, 2]
    assert _try_parse_json('{"b": 2}') == {"b": 2}
    assert _try_parse_json("not-json") == "not-json"
    assert _try_parse_json(42) == 42


def test_try_parse_json_sessions():
    from dashboard.routers.sessions import _try_parse_json
    assert _try_parse_json(None) is None
    assert _try_parse_json({"a": 1}) == {"a": 1}
    assert _try_parse_json('{"b": 2}') == {"b": 2}
    assert _try_parse_json("bad") == "bad"


# ---------------------------------------------------------------------------
# Integration tests (require a real database)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_DB, reason="TEST_DATABASE_URL not set")
class TestWithDatabase:
    """These tests only run when a test database is available."""

    def test_status_returns_zeros(self, client: TestClient):
        resp = client.get("/api/cogents/nonexistent-cogent/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["cogent_id"] == "nonexistent-cogent"
        assert data["active_sessions"] == 0

    def test_programs_empty(self, client: TestClient):
        resp = client.get("/api/cogents/nonexistent-cogent/programs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["programs"] == []

    def test_sessions_empty(self, client: TestClient):
        resp = client.get("/api/cogents/nonexistent-cogent/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["sessions"] == []
