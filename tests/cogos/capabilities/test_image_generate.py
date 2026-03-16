"""Tests for image AI generation operations (Gemini)."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch
from uuid import uuid4

from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef
from cogos.capabilities.image import ImageCapability, ImageError


def _make_png(width: int = 100, height: int = 80, color=(255, 0, 0, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_cap(png_bytes: bytes | None = None) -> ImageCapability:
    repo = MagicMock()
    with patch("cogos.capabilities.image.BlobCapability"):
        cap = ImageCapability(repo, uuid4())
    cap._blob = MagicMock()
    if png_bytes is not None:
        cap._blob.download = MagicMock(return_value=BlobContent(
            data=png_bytes, filename="test.png", content_type="image/png",
        ))
    return cap


def _mock_gemini_response(png_bytes: bytes) -> MagicMock:
    """Build a mock Gemini response containing image inline_data."""
    part = MagicMock()
    part.inline_data = MagicMock()
    part.inline_data.data = png_bytes
    part.inline_data.mime_type = "image/png"
    part.text = None

    candidate = MagicMock()
    candidate.content.parts = [part]

    response = MagicMock()
    response.candidates = [candidate]
    return response


def _blob_ref(filename: str = "generated.png") -> BlobRef:
    return BlobRef(key=f"blobs/{uuid4()}/{filename}", url="https://example.com/img", filename=filename, size=1234)


@patch("cogos.capabilities.image.generate.get_gemini_client")
def test_generate(mock_get_client):
    png = _make_png()
    cap = _make_cap()
    ref = _blob_ref("generated.png")
    cap._blob.upload = MagicMock(return_value=ref)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_gemini_response(png)
    mock_get_client.return_value = mock_client

    result = cap.generate("a sunset over mountains")
    assert isinstance(result, BlobRef)
    assert "generated" in result.filename
    mock_client.models.generate_content.assert_called_once()
    cap._blob.upload.assert_called_once()


@patch("cogos.capabilities.image.generate.get_gemini_client")
def test_generate_scope_denied(mock_get_client):
    cap = _make_cap()
    cap._scope = {"ops": ["resize"]}

    result = cap.generate("a sunset")
    assert isinstance(result, ImageError)
    assert "not allowed" in result.error.lower()
    mock_get_client.assert_not_called()


@patch("cogos.capabilities.image.generate.get_gemini_client")
def test_edit(mock_get_client):
    png = _make_png()
    cap = _make_cap(png)
    ref = _blob_ref("edited.png")
    cap._blob.upload = MagicMock(return_value=ref)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_gemini_response(png)
    mock_get_client.return_value = mock_client

    result = cap.edit("blobs/abc/test.png", "make it blue")
    assert isinstance(result, BlobRef)
    mock_client.models.generate_content.assert_called_once()
    cap._blob.upload.assert_called_once()


@patch("cogos.capabilities.image.generate.get_gemini_client")
def test_variations(mock_get_client):
    png = _make_png()
    cap = _make_cap(png)

    count = 3
    refs = [_blob_ref(f"variation_{i+1}.png") for i in range(count)]
    cap._blob.upload = MagicMock(side_effect=refs)

    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = _mock_gemini_response(png)
    mock_get_client.return_value = mock_client

    result = cap.variations("blobs/abc/test.png", count=count)
    assert isinstance(result, list)
    assert len(result) == count
    assert all(isinstance(r, BlobRef) for r in result)
    assert mock_client.models.generate_content.call_count == count
