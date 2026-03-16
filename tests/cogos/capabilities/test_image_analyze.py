"""Tests for image AI analysis operations (Gemini Vision)."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image

from cogos.capabilities.blob import BlobContent
from cogos.capabilities.image import (
    AnalysisResult,
    ExtractedText,
    ImageCapability,
    ImageDescription,
    ImageError,
)


def _make_png(width: int = 100, height: int = 80, color=(255, 0, 0, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_cap(png_bytes: bytes | None = None) -> ImageCapability:
    repo = MagicMock()
    with patch("cogos.capabilities.image.BlobCapability"):
        cap = ImageCapability(repo, uuid4())
    if png_bytes is not None:
        cap._blob.download = MagicMock(return_value=BlobContent(
            data=png_bytes, filename="test.png", content_type="image/png",
        ))
    return cap


@patch("cogos.capabilities.image.analyze.get_gemini_client")
def test_describe(mock_get_client):
    png = _make_png()
    cap = _make_cap(png)

    mock_response = MagicMock()
    mock_response.text = "A red rectangle on a transparent background."
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    result = cap.describe("blobs/abc/test.png")
    assert isinstance(result, ImageDescription)
    assert result.key == "blobs/abc/test.png"
    assert result.description == "A red rectangle on a transparent background."
    mock_client.models.generate_content.assert_called_once()


@patch("cogos.capabilities.image.analyze.get_gemini_client")
def test_describe_scope_denied(mock_get_client):
    png = _make_png()
    cap = _make_cap(png)
    cap._scope = {"ops": ["resize"]}

    result = cap.describe("blobs/abc/test.png")
    assert isinstance(result, ImageError)
    assert "not allowed" in result.error.lower()
    mock_get_client.assert_not_called()


@patch("cogos.capabilities.image.analyze.get_gemini_client")
def test_analyze(mock_get_client):
    png = _make_png()
    cap = _make_cap(png)

    mock_response = MagicMock()
    mock_response.text = "The dominant color is red"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    result = cap.analyze("blobs/abc/test.png", "What is the dominant color?")
    assert isinstance(result, AnalysisResult)
    assert result.key == "blobs/abc/test.png"
    assert result.answer == "The dominant color is red"


@patch("cogos.capabilities.image.analyze.get_gemini_client")
def test_extract_text(mock_get_client):
    png = _make_png()
    cap = _make_cap(png)

    mock_response = MagicMock()
    mock_response.text = "Hello World"
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    result = cap.extract_text("blobs/abc/test.png")
    assert isinstance(result, ExtractedText)
    assert result.key == "blobs/abc/test.png"
    assert result.text == "Hello World"
