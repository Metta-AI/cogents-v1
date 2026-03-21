"""Post to Discord via per-cogent webhooks using the bot token.

Usage (CLI):
    python -m cogos.io.discord.announce --channel-id 1454583125786230906 \
        --username cogents.0 --message "Pushed to main: ..."

Usage (Python):
    from cogos.io.discord.announce import post
    post(channel_id="...", username="cogents.0", message="...")

Webhook lifecycle:
    - Looks for an existing webhook named "cogent-{username}" in the channel
    - Creates one if it doesn't exist (using the bot token)
    - Posts via the webhook URL with the given username

Token source: agora/discord secret via SecretsProvider.
"""

from __future__ import annotations

import json
import logging
import sys
import urllib.request

logger = logging.getLogger(__name__)

DISCORD_API = "https://discord.com/api/v10"


def _get_bot_token(secrets_provider=None) -> str:
    """Get the Discord bot token from agora/discord via secrets provider."""
    if secrets_provider is None:
        from cogtainer.runtime.factory import create_executor_runtime
        secrets_provider = create_executor_runtime().get_secrets_provider()

    try:
        token = secrets_provider.get_secret("agora/discord", field="bot_token")
    except (KeyError, Exception):
        try:
            token = secrets_provider.get_secret("agora/discord", field="access_token")
        except (KeyError, Exception):
            token = ""
    if token:
        return token
    raise RuntimeError("No bot token found in agora/discord secret.")


def _api(method: str, path: str, token: str, body: dict | None = None) -> dict | list:
    """Make a Discord REST API call."""
    url = f"{DISCORD_API}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _get_or_create_webhook(channel_id: str, username: str, token: str) -> str:
    """Get or create a webhook named 'cogent-{username}' in the channel. Returns webhook URL."""
    wh_name = f"cogent-{username}"
    webhooks = _api("GET", f"/channels/{channel_id}/webhooks", token)
    for wh in webhooks:
        if wh.get("name") == wh_name:
            return f"{DISCORD_API}/webhooks/{wh['id']}/{wh['token']}"

    wh = _api("POST", f"/channels/{channel_id}/webhooks", token, {"name": wh_name})
    logger.info("Created webhook %s in channel %s", wh_name, channel_id)
    return f"{DISCORD_API}/webhooks/{wh['id']}/{wh['token']}"


def post(*, channel_id: str, username: str, message: str) -> None:
    """Post a message to Discord via a per-cogent webhook."""
    token = _get_bot_token()
    webhook_url = _get_or_create_webhook(channel_id, username, token)

    data = json.dumps({"username": username, "content": message}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Post to Discord via cogent webhook")
    parser.add_argument("--channel-id", required=True, help="Discord channel ID")
    parser.add_argument("--username", required=True, help="Display name for the post")
    parser.add_argument("--message", required=True, help="Message content (max 2000 chars)")
    args = parser.parse_args()

    if len(args.message) > 2000:
        print("Error: message exceeds 2000 character Discord limit", file=sys.stderr)
        sys.exit(1)

    post(channel_id=args.channel_id, username=args.username, message=args.message)
    print(f"Posted to #{args.channel_id} as {args.username}")


if __name__ == "__main__":
    main()
