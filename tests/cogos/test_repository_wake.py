from cogos.db.repository import Repository


def _repo() -> Repository:
    return Repository(client=None, resource_arn="cluster", secret_arn="secret", database="cogent")


def test_request_ingress_wake_returns_token_when_gate_opens(monkeypatch):
    repo = _repo()
    monkeypatch.setattr(repo, "_execute", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        repo,
        "_first_row",
        lambda _response: {
            "requested_at": "2026-03-11T12:00:00+00:00",
            "enqueued_at": "2026-03-11T12:00:00+00:00",
        },
    )

    assert repo._request_ingress_wake() == "1773230400"


def test_request_ingress_wake_returns_none_when_coalesced(monkeypatch):
    repo = _repo()
    monkeypatch.setattr(repo, "_execute", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        repo,
        "_first_row",
        lambda _response: {
            "requested_at": "2026-03-11T12:00:01+00:00",
            "enqueued_at": "2026-03-11T12:00:00+00:00",
        },
    )

    assert repo._request_ingress_wake() is None
