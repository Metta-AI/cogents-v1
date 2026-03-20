from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_extract_asana_accept_link():
    from polis.io.email.handler import _extract_asana_accept_link

    html_body = '''
    <html><body>
    <a href="https://app.asana.com/0/accept/invitation/12345?token=abc123">Accept Invite</a>
    </body></html>
    '''
    link = _extract_asana_accept_link(html_body)
    assert link is not None
    assert "accept" in link
    assert "asana.com" in link


def test_extract_asana_accept_link_no_match():
    from polis.io.email.handler import _extract_asana_accept_link

    html_body = '<html><body><a href="https://example.com">Click</a></body></html>'
    assert _extract_asana_accept_link(html_body) is None


def test_try_asana_auto_accept_hits_link_and_updates_dynamo():
    from polis.io.email.handler import _try_asana_auto_accept

    payload = {
        "from": "no-reply@asana.com",
        "subject": "You've been invited to join Softmax",
        "html_body": '<a href="https://app.asana.com/0/accept/invitation/123?token=abc">Accept</a>',
    }

    with patch("polis.io.email.handler.requests") as mock_requests, \
         patch("polis.io.email.handler._get_dynamo_table") as mock_dynamo:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_requests.get.return_value = mock_resp

        mock_table = MagicMock()
        mock_dynamo.return_value = mock_table

        _try_asana_auto_accept("scout", payload)

        mock_requests.get.assert_called_once()
        mock_table.update_item.assert_called_once()


def test_try_asana_auto_accept_skips_non_asana():
    from polis.io.email.handler import _try_asana_auto_accept

    payload = {"from": "noreply@github.com", "subject": "New PR", "html_body": "<html></html>"}

    with patch("polis.io.email.handler.requests") as mock_requests, \
         patch("polis.io.email.handler._get_dynamo_table") as mock_dynamo:
        mock_table = MagicMock()
        mock_dynamo.return_value = mock_table

        _try_asana_auto_accept("scout", payload)

        mock_requests.get.assert_not_called()
        mock_table.update_item.assert_not_called()
