from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


def test_extract_accept_link():
    from polis.io.asana.handler import _extract_accept_link

    html_body = '''
    <html><body>
    <a href="https://app.asana.com/0/accept/invitation/12345?token=abc123">Accept Invite</a>
    </body></html>
    '''
    link = _extract_accept_link(html_body)
    assert link is not None
    assert "accept" in link
    assert "asana.com" in link


def test_extract_accept_link_no_match():
    from polis.io.asana.handler import _extract_accept_link

    html_body = '<html><body><a href="https://example.com">Click</a></body></html>'
    assert _extract_accept_link(html_body) is None


def test_handler_accepts_and_updates_dynamo():
    from polis.io.asana.handler import handler

    event = {
        "Records": [
            {
                "body": json.dumps({
                    "cogent_name": "scout",
                    "from": "no-reply@asana.com",
                    "subject": "You've been invited to join Softmax",
                    "html_body": '<a href="https://app.asana.com/0/accept/invitation/123?token=abc">Accept</a>',
                }),
            }
        ]
    }

    with patch("polis.io.asana.handler.requests") as mock_requests, \
         patch("polis.io.asana.handler._get_dynamo_table") as mock_dynamo:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_requests.get.return_value = mock_resp

        mock_table = MagicMock()
        mock_dynamo.return_value = mock_table

        handler(event, None)

        mock_requests.get.assert_called_once()
        mock_table.update_item.assert_called_once()


def test_handler_skips_non_asana_email():
    from polis.io.asana.handler import handler

    event = {
        "Records": [
            {
                "body": json.dumps({
                    "cogent_name": "scout",
                    "from": "noreply@github.com",
                    "subject": "New PR",
                    "html_body": "<html></html>",
                }),
            }
        ]
    }

    with patch("polis.io.asana.handler.requests") as mock_requests, \
         patch("polis.io.asana.handler._get_dynamo_table") as mock_dynamo:
        mock_table = MagicMock()
        mock_dynamo.return_value = mock_table

        handler(event, None)

        mock_requests.get.assert_not_called()
        mock_table.update_item.assert_not_called()
