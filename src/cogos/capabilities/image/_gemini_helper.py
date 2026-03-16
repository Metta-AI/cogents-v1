"""Shared Gemini client initialization for image AI capabilities."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def get_gemini_client():
    """Return a configured google.genai.Client using the cogent's Gemini API key."""
    from google import genai

    from cogos.capabilities._secrets_helper import fetch_secret

    api_key = fetch_secret("cogent/{cogent}/gemini")
    return genai.Client(api_key=api_key)
