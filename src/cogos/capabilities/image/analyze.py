"""AI image analysis using Gemini Vision."""
from __future__ import annotations

import io
import logging

from cogos.capabilities.image import AnalysisResult, ExtractedText, ImageDescription, ImageError
from cogos.capabilities.image._gemini_helper import get_gemini_client

logger = logging.getLogger(__name__)

MODEL = "gemini-2.0-flash"


def _image_to_part(img) -> dict:
    """Convert a PIL Image to a Gemini inline_data part (PNG bytes)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"inline_data": {"mime_type": "image/png", "data": buf.getvalue()}}


def describe(cap, key: str, prompt: str | None = None) -> ImageDescription | ImageError:
    """Describe an image using Gemini Vision."""
    err = cap._check_op("describe")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    try:
        client = get_gemini_client(secrets_provider=cap._secrets_provider)
        text_prompt = prompt or "Describe this image in detail."
        image_part = _image_to_part(img)
        response = client.models.generate_content(
            model=MODEL, contents=[text_prompt, image_part]
        )
        return ImageDescription(key=key, description=response.text)
    except Exception as exc:
        logger.exception("describe failed for key=%s", key)
        return ImageError(error=str(exc))


def analyze(cap, key: str, prompt: str) -> AnalysisResult | ImageError:
    """Answer a question about an image using Gemini Vision."""
    err = cap._check_op("analyze")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    try:
        client = get_gemini_client(secrets_provider=cap._secrets_provider)
        image_part = _image_to_part(img)
        response = client.models.generate_content(
            model=MODEL, contents=[prompt, image_part]
        )
        return AnalysisResult(key=key, answer=response.text)
    except Exception as exc:
        logger.exception("analyze failed for key=%s", key)
        return ImageError(error=str(exc))


def extract_text(cap, key: str) -> ExtractedText | ImageError:
    """Extract text from an image (OCR) using Gemini Vision."""
    err = cap._check_op("extract_text")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    try:
        client = get_gemini_client(secrets_provider=cap._secrets_provider)
        text_prompt = "Extract all text visible in this image. Return only the extracted text, nothing else."
        image_part = _image_to_part(img)
        response = client.models.generate_content(
            model=MODEL, contents=[text_prompt, image_part]
        )
        return ExtractedText(key=key, text=response.text)
    except Exception as exc:
        logger.exception("extract_text failed for key=%s", key)
        return ImageError(error=str(exc))
