"""CogOS — operating system for cogents."""

import os


def get_sessions_bucket() -> str:
    """Return the S3 sessions bucket name from env, deriving from COGTAINER_NAME if needed."""
    bucket = os.environ.get("SESSIONS_BUCKET", "")
    if not bucket:
        cogtainer = os.environ.get("COGTAINER_NAME", "")
        if cogtainer:
            bucket = f"cogtainer-{cogtainer}-sessions"
    return bucket


def get_sessions_prefix() -> str:
    """Return the S3 key prefix for this cogent's data within the shared bucket."""
    prefix = os.environ.get("SESSIONS_PREFIX", "")
    if not prefix:
        cogent = os.environ.get("COGENT", "") or os.environ.get("COGENT_NAME", "")
        if cogent:
            prefix = cogent.replace(".", "-")
    return prefix
