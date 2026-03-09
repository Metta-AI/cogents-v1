"""Tests for cogos email capability — sender, capability handlers, ingest."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.io.email.sender import SesSender
from cogos.io.email.capability import send, check, search, _email_from_event
from cogos.sandbox.executor import CapabilityResult


# ── SesSender ─────────────────────────────────────────────────


class TestSesSender:
    @patch("cogos.io.email.sender.boto3")
    def test_send_basic(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "abc123"}
        mock_boto3.client.return_value = mock_client

        sender = SesSender(from_address="ovo@softmax-cogents.com")
        result = sender.send(to="user@example.com", subject="Hello", body="Hi there")

        assert result["MessageId"] == "abc123"
        mock_client.send_email.assert_called_once()
        call_kwargs = mock_client.send_email.call_args[1]
        assert call_kwargs["Source"] == "ovo@softmax-cogents.com"
        assert call_kwargs["Destination"] == {"ToAddresses": ["user@example.com"]}
        assert call_kwargs["Message"]["Subject"]["Data"] == "Hello"
        assert call_kwargs["Message"]["Body"]["Text"]["Data"] == "Hi there"
        assert "ReplyToAddresses" not in call_kwargs

    @patch("cogos.io.email.sender.boto3")
    def test_send_with_reply_to(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.send_email.return_value = {"MessageId": "def456"}
        mock_boto3.client.return_value = mock_client

        sender = SesSender(from_address="ovo@softmax-cogents.com")
        sender.send(to="a@b.com", subject="Re: test", body="reply", reply_to="c@d.com")

        call_kwargs = mock_client.send_email.call_args[1]
        assert call_kwargs["ReplyToAddresses"] == ["c@d.com"]


# ── Capability Handlers ──────────────────────────────────────


class FakeEvent:
    def __init__(self, payload):
        self.id = uuid4()
        self.event_type = "email:received"
        self.source = "cloudflare-email-worker"
        self.payload = payload
        self.parent_event = None
        self.created_at = None


class TestEmailFromEvent:
    def test_extracts_fields(self):
        e = FakeEvent({"from": "a@b.com", "to": "ovo@x.com", "subject": "Hi", "body": "Hello", "date": "Mon", "message_id": "123"})
        result = _email_from_event(e)
        assert result == {"from": "a@b.com", "to": "ovo@x.com", "subject": "Hi", "body": "Hello", "date": "Mon", "message_id": "123"}

    def test_missing_fields(self):
        e = FakeEvent({})
        result = _email_from_event(e)
        assert result["from"] is None
        assert result["subject"] is None


class TestSendCapability:
    @patch("cogos.io.email.capability._get_sender")
    def test_send_success(self, mock_get_sender):
        mock_sender = MagicMock()
        mock_sender.send.return_value = {"MessageId": "msg-1"}
        mock_get_sender.return_value = mock_sender

        repo = MagicMock()
        result = send(repo, uuid4(), {"to": "a@b.com", "subject": "Test", "body": "Hi"})

        assert isinstance(result, CapabilityResult)
        assert result.content["message_id"] == "msg-1"
        assert result.content["to"] == "a@b.com"

    def test_send_missing_fields(self):
        repo = MagicMock()
        result = send(repo, uuid4(), {"to": "", "subject": "", "body": ""})
        assert "error" in result.content


class TestCheckCapability:
    def test_check_returns_emails(self):
        repo = MagicMock()
        repo.get_events.return_value = [
            FakeEvent({"from": "a@b.com", "subject": "Hi", "body": "Hello", "to": "ovo@x.com", "date": "Mon", "message_id": "1"}),
            FakeEvent({"from": "c@d.com", "subject": "Hey", "body": "World", "to": "ovo@x.com", "date": "Tue", "message_id": "2"}),
        ]

        result = check(repo, uuid4(), {"limit": 10})
        assert len(result.content) == 2
        assert result.content[0]["from"] == "a@b.com"
        repo.get_events.assert_called_once_with(event_type="email:received", limit=10)


class TestSearchCapability:
    def test_search_filters_by_query(self):
        repo = MagicMock()
        repo.get_events.return_value = [
            FakeEvent({"from": "alice@b.com", "subject": "Review PR", "body": "Please review", "to": "ovo@x.com", "date": "Mon", "message_id": "1"}),
            FakeEvent({"from": "bob@b.com", "subject": "Lunch?", "body": "Let's eat", "to": "ovo@x.com", "date": "Tue", "message_id": "2"}),
        ]

        result = search(repo, uuid4(), {"query": "review"})
        assert len(result.content) == 1
        assert result.content[0]["from"] == "alice@b.com"

    def test_search_empty_results(self):
        repo = MagicMock()
        repo.get_events.return_value = []

        result = search(repo, uuid4(), {"query": "nonexistent"})
        assert result.content == []


# ── Ingest Endpoint ──────────────────────────────────────────


class TestIngestEndpoint:
    @pytest.fixture
    def client(self):
        import os
        os.environ["EMAIL_INGEST_SECRET"] = "test-secret-123"
        os.environ.setdefault("USE_LOCAL_DB", "1")

        from fastapi.testclient import TestClient
        from cogos.io.email.ingest import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router, prefix="/api")
        return TestClient(app)

    def test_ingest_valid(self, client):
        with patch("dashboard.db.get_cogos_repo") as mock_repo_fn:
            mock_repo = MagicMock()
            mock_repo.append_event.return_value = uuid4()
            mock_repo_fn.return_value = mock_repo

            resp = client.post(
                "/api/ingest/email",
                json={
                    "event_type": "email:received",
                    "source": "cloudflare-email-worker",
                    "payload": {"from": "a@b.com", "subject": "Hi"},
                },
                headers={"Authorization": "Bearer test-secret-123"},
            )
            assert resp.status_code == 200
            assert "event_id" in resp.json()
            mock_repo.append_event.assert_called_once()

    def test_ingest_unauthorized(self, client):
        resp = client.post(
            "/api/ingest/email",
            json={"event_type": "email:received", "source": "x", "payload": {}},
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401

    def test_ingest_no_token(self, client):
        resp = client.post(
            "/api/ingest/email",
            json={"event_type": "email:received", "source": "x", "payload": {}},
        )
        assert resp.status_code == 401
