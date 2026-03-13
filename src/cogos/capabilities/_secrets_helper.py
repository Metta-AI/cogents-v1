"""Shared secret fetching — SSM Parameter Store with Secrets Manager fallback."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def fetch_secret(key: str) -> str:
    """Fetch a secret value from AWS SSM Parameter Store or Secrets Manager.

    Tries SSM first, then Secrets Manager. Returns the string value.
    Raises RuntimeError if both fail.
    """
    import boto3

    # Try SSM Parameter Store
    try:
        client = boto3.client("ssm")
        resp = client.get_parameter(Name=key, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception:
        pass

    # Try Secrets Manager
    try:
        client = boto3.client("secretsmanager")
        resp = client.get_secret_value(SecretId=key)
        value = resp.get("SecretString")
        if value is None:
            raise RuntimeError(f"Secret '{key}' is binary, not string")
        return value
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not fetch secret '{key}': {exc}") from exc
