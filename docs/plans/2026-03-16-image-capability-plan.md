# Image Capability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a unified `image` capability to CogOS with manipulation, compositing, AI analysis, and AI generation — all blob-key oriented.

**Architecture:** Single `ImageCapability` class with methods delegating to submodules (manipulate, compose, analyze, generate). Uses existing `BlobCapability` for S3 storage, `_secrets_helper.fetch_secret` for Gemini API key, Pillow for pixel ops, and `google-genai` SDK for AI ops.

**Tech Stack:** Pillow, google-genai, boto3 (existing), pydantic (existing)

**Design doc:** `docs/plans/2026-03-16-image-capability-design.md`

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml:6-28` (dependencies list)

**Step 1: Add Pillow and google-genai to dependencies**

In `pyproject.toml`, add to the `dependencies` list:
```
    "Pillow>=10.0",
    "google-genai>=1.0",
```

**Step 2: Sync dependencies**

Run: `uv sync --all-extras`
Expected: installs Pillow and google-genai successfully

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(image): add Pillow and google-genai dependencies"
```

---

### Task 2: Create image capability package with Gemini helper and IO models

**Files:**
- Create: `src/cogos/capabilities/image/__init__.py`
- Create: `src/cogos/capabilities/image/_gemini_helper.py`

**Step 1: Create `_gemini_helper.py`**

```python
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
```

**Step 2: Create `__init__.py`** with the ImageCapability class skeleton and IO models.

```python
"""Image capability — manipulation, compositing, AI analysis, and generation."""
from __future__ import annotations

import io
import logging
from typing import Any

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.blob import BlobCapability, BlobRef, BlobError

logger = logging.getLogger(__name__)

ALL_OPS = {
    "resize", "crop", "rotate", "convert", "thumbnail",
    "overlay_text", "watermark", "combine",
    "describe", "analyze", "extract_text",
    "generate", "edit", "variations",
}


# ── IO Models ────────────────────────────────────────────────

class ImageDescription(BaseModel):
    key: str
    description: str

class AnalysisResult(BaseModel):
    key: str
    answer: str

class ExtractedText(BaseModel):
    key: str
    text: str

class ImageError(BaseModel):
    error: str


# ── Capability ───────────────────────────────────────────────

class ImageCapability(Capability):
    """Manipulate, compose, analyze, and generate images.

    All operations are blob-key oriented: input blob keys, output new blob keys.

    Usage:
        ref = image.generate("a sunset over mountains")
        ref2 = image.resize(ref.key, width=800)
        ref3 = image.overlay_text(ref2.key, "Hello!", position="bottom")
    """

    def __init__(self, repo, process_id, run_id=None, trace_id=None):
        super().__init__(repo, process_id, run_id, trace_id)
        self._blob = BlobCapability(repo, process_id, run_id, trace_id)

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result: dict = {}
        e_ops = existing.get("ops")
        r_ops = requested.get("ops")
        if e_ops is not None and r_ops is not None:
            result["ops"] = sorted(set(e_ops) & set(r_ops))
        elif e_ops is not None:
            result["ops"] = e_ops
        elif r_ops is not None:
            result["ops"] = r_ops
        return result

    def _check_op(self, op: str) -> str | None:
        allowed = self._scope.get("ops")
        if allowed is not None and op not in allowed:
            return f"Operation '{op}' not allowed by scope"
        return None

    def _download_image(self, key: str):
        """Download a blob and return a PIL Image."""
        from PIL import Image
        content = self._blob.download(key)
        if isinstance(content, BlobError):
            return None, content.error
        return Image.open(io.BytesIO(content.data)), None

    def _upload_image(self, img, filename: str, fmt: str = "PNG") -> BlobRef | ImageError:
        """Save a PIL Image to blob store."""
        buf = io.BytesIO()
        save_kwargs: dict[str, Any] = {}
        if fmt.upper() == "JPEG":
            img = img.convert("RGB")
            save_kwargs["quality"] = 95
        img.save(buf, format=fmt, **save_kwargs)
        data = buf.getvalue()
        content_type = f"image/{fmt.lower()}"
        result = self._blob.upload(data, filename, content_type=content_type)
        if isinstance(result, BlobError):
            return ImageError(error=result.error)
        return result

    # -- Manipulation (Task 3) --
    # -- Compositing (Task 4) --
    # -- Analysis (Task 5) --
    # -- Generation (Task 6) --

    def __repr__(self) -> str:
        return "<ImageCapability resize() crop() rotate() convert() thumbnail() overlay_text() watermark() combine() describe() analyze() extract_text() generate() edit() variations()>"
```

**Step 3: Verify import works**

Run: `cd /Users/daveey/code/cogents/cogents.8 && uv run python -c "from cogos.capabilities.image import ImageCapability; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/cogos/capabilities/image/
git commit -m "feat(image): add ImageCapability skeleton with IO models and Gemini helper"
```

---

### Task 3: Implement manipulation methods + tests

**Files:**
- Create: `src/cogos/capabilities/image/manipulate.py`
- Modify: `src/cogos/capabilities/image/__init__.py` (add method imports)
- Create: `tests/cogos/capabilities/test_image_manipulate.py`

**Step 1: Write tests**

```python
"""Tests for image manipulation methods."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef, BlobError
from cogos.capabilities.image import ImageCapability, ImageError


def _make_png(width: int = 100, height: int = 80) -> bytes:
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_capability() -> ImageCapability:
    repo = MagicMock()
    cap = ImageCapability(repo, process_id=MagicMock())
    return cap


def _mock_blob_download(cap, png_bytes: bytes):
    cap._blob.download = MagicMock(return_value=BlobContent(
        data=png_bytes, filename="test.png", content_type="image/png",
    ))


def _mock_blob_upload(cap):
    def fake_upload(data, filename, content_type=None):
        return BlobRef(key=f"blobs/fake/{filename}", url="https://fake", filename=filename, size=len(data))
    cap._blob.upload = MagicMock(side_effect=fake_upload)


class TestResize:
    def test_resize_both_dimensions(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.resize("blobs/old/test.png", width=50, height=40)
        assert isinstance(result, BlobRef)
        # Verify the uploaded image dimensions
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (50, 40)

    def test_resize_width_only_preserves_aspect(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.resize("blobs/old/test.png", width=50)
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (50, 40)

    def test_resize_height_only_preserves_aspect(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.resize("blobs/old/test.png", height=40)
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (50, 40)

    def test_resize_scope_denied(self):
        cap = _make_capability()
        cap._scope = {"ops": ["crop"]}
        result = cap.resize("blobs/old/test.png", width=50)
        assert isinstance(result, ImageError)


class TestCrop:
    def test_crop_region(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.crop("blobs/old/test.png", left=10, top=10, right=60, bottom=50)
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (50, 40)


class TestRotate:
    def test_rotate_90(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.rotate("blobs/old/test.png", degrees=90)
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (80, 100)


class TestConvert:
    def test_convert_to_jpeg(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.convert("blobs/old/test.png", format="JPEG")
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        assert upload_call[1].get("content_type") == "image/jpeg" or "jpeg" in upload_call[0][1]


class TestThumbnail:
    def test_thumbnail_fits_box(self):
        cap = _make_capability()
        _mock_blob_download(cap, _make_png(100, 80))
        _mock_blob_upload(cap)

        result = cap.thumbnail("blobs/old/test.png", max_size=50)
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size[0] <= 50 and img.size[1] <= 50
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cogos/capabilities/test_image_manipulate.py -v`
Expected: FAIL — methods not implemented yet

**Step 3: Implement `manipulate.py`**

```python
"""Image manipulation — resize, crop, rotate, convert, thumbnail."""
from __future__ import annotations

from PIL import Image

from cogos.capabilities.blob import BlobRef
from cogos.capabilities.image import ImageError


def resize(cap, key: str, width: int | None = None, height: int | None = None) -> BlobRef | ImageError:
    """Resize an image. If only one dimension given, preserves aspect ratio."""
    err = cap._check_op("resize")
    if err:
        return ImageError(error=err)
    if width is None and height is None:
        return ImageError(error="At least one of width or height is required")
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    orig_w, orig_h = img.size
    if width and not height:
        height = int(orig_h * (width / orig_w))
    elif height and not width:
        width = int(orig_w * (height / orig_h))
    img = img.resize((width, height), Image.LANCZOS)
    return cap._upload_image(img, f"resized_{width}x{height}.png")


def crop(cap, key: str, left: int, top: int, right: int, bottom: int) -> BlobRef | ImageError:
    """Crop an image to the given bounding box."""
    err = cap._check_op("crop")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    img = img.crop((left, top, right, bottom))
    return cap._upload_image(img, f"cropped_{right-left}x{bottom-top}.png")


def rotate(cap, key: str, degrees: float) -> BlobRef | ImageError:
    """Rotate an image by the given degrees (counterclockwise). Expands canvas to fit."""
    err = cap._check_op("rotate")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    img = img.rotate(degrees, expand=True)
    return cap._upload_image(img, f"rotated_{int(degrees)}deg.png")


def convert(cap, key: str, format: str) -> BlobRef | ImageError:
    """Convert an image to a different format (e.g. PNG, JPEG, WEBP)."""
    err = cap._check_op("convert")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    fmt = format.upper()
    ext = fmt.lower()
    if ext == "jpeg":
        ext = "jpg"
    return cap._upload_image(img, f"converted.{ext}", fmt=fmt)


def thumbnail(cap, key: str, max_size: int) -> BlobRef | ImageError:
    """Create a thumbnail that fits within a max_size x max_size box."""
    err = cap._check_op("thumbnail")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    img.thumbnail((max_size, max_size), Image.LANCZOS)
    return cap._upload_image(img, f"thumb_{max_size}.png")
```

**Step 4: Wire methods into `__init__.py`**

Add the delegation methods to `ImageCapability`, replacing the `# -- Manipulation (Task 3) --` comment:

```python
    # -- Manipulation --

    def resize(self, key: str, width: int | None = None, height: int | None = None) -> BlobRef | ImageError:
        """Resize an image. If only one dimension given, preserves aspect ratio."""
        from cogos.capabilities.image.manipulate import resize
        return resize(self, key, width, height)

    def crop(self, key: str, left: int, top: int, right: int, bottom: int) -> BlobRef | ImageError:
        """Crop an image to the given bounding box."""
        from cogos.capabilities.image.manipulate import crop
        return crop(self, key, left, top, right, bottom)

    def rotate(self, key: str, degrees: float) -> BlobRef | ImageError:
        """Rotate an image by the given degrees."""
        from cogos.capabilities.image.manipulate import rotate
        return rotate(self, key, degrees)

    def convert(self, key: str, format: str) -> BlobRef | ImageError:
        """Convert an image to a different format (PNG, JPEG, WEBP)."""
        from cogos.capabilities.image.manipulate import convert
        return convert(self, key, format)

    def thumbnail(self, key: str, max_size: int) -> BlobRef | ImageError:
        """Create a thumbnail that fits within a max_size x max_size box."""
        from cogos.capabilities.image.manipulate import thumbnail
        return thumbnail(self, key, max_size)
```

**Step 5: Run tests**

Run: `uv run pytest tests/cogos/capabilities/test_image_manipulate.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/image/manipulate.py src/cogos/capabilities/image/__init__.py tests/cogos/capabilities/test_image_manipulate.py
git commit -m "feat(image): add manipulation methods — resize, crop, rotate, convert, thumbnail"
```

---

### Task 4: Implement compositing methods + tests

**Files:**
- Create: `src/cogos/capabilities/image/compose.py`
- Modify: `src/cogos/capabilities/image/__init__.py` (add method delegates)
- Create: `tests/cogos/capabilities/test_image_compose.py`

**Step 1: Write tests**

```python
"""Tests for image compositing methods."""
from __future__ import annotations

import io
from unittest.mock import MagicMock

from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef
from cogos.capabilities.image import ImageCapability, ImageError


def _make_png(width=100, height=80, color=(255, 0, 0, 255)) -> bytes:
    img = Image.new("RGBA", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_capability() -> ImageCapability:
    repo = MagicMock()
    return ImageCapability(repo, process_id=MagicMock())


def _mock_blob(cap, png_map: dict[str, bytes] | None = None):
    default_png = _make_png()
    if png_map is None:
        png_map = {}

    def fake_download(key):
        data = png_map.get(key, default_png)
        return BlobContent(data=data, filename="test.png", content_type="image/png")

    def fake_upload(data, filename, content_type=None):
        return BlobRef(key=f"blobs/fake/{filename}", url="https://fake", filename=filename, size=len(data))

    cap._blob.download = MagicMock(side_effect=fake_download)
    cap._blob.upload = MagicMock(side_effect=fake_upload)


class TestOverlayText:
    def test_overlay_text_returns_blob_ref(self):
        cap = _make_capability()
        _mock_blob(cap)
        result = cap.overlay_text("blobs/old/test.png", "Hello!", position="center")
        assert isinstance(result, BlobRef)

    def test_overlay_text_scope_denied(self):
        cap = _make_capability()
        cap._scope = {"ops": ["resize"]}
        result = cap.overlay_text("blobs/old/test.png", "Hello!", position="center")
        assert isinstance(result, ImageError)


class TestWatermark:
    def test_watermark_returns_blob_ref(self):
        cap = _make_capability()
        _mock_blob(cap)
        result = cap.watermark("blobs/base.png", "blobs/mark.png")
        assert isinstance(result, BlobRef)


class TestCombine:
    def test_combine_horizontal(self):
        cap = _make_capability()
        png1 = _make_png(50, 80, (255, 0, 0, 255))
        png2 = _make_png(60, 80, (0, 255, 0, 255))
        _mock_blob(cap, {"k1": png1, "k2": png2})

        result = cap.combine(["k1", "k2"], layout="horizontal")
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (110, 80)

    def test_combine_vertical(self):
        cap = _make_capability()
        png1 = _make_png(80, 50)
        png2 = _make_png(80, 60)
        _mock_blob(cap, {"k1": png1, "k2": png2})

        result = cap.combine(["k1", "k2"], layout="vertical")
        assert isinstance(result, BlobRef)
        upload_call = cap._blob.upload.call_args
        img = Image.open(io.BytesIO(upload_call[0][0]))
        assert img.size == (80, 110)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cogos/capabilities/test_image_compose.py -v`

**Step 3: Implement `compose.py`**

```python
"""Image compositing — overlay text, watermark, combine."""
from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from cogos.capabilities.blob import BlobRef, BlobError
from cogos.capabilities.image import ImageError

POSITIONS = {
    "center": lambda w, h, tw, th: ((w - tw) // 2, (h - th) // 2),
    "top": lambda w, h, tw, th: ((w - tw) // 2, 10),
    "bottom": lambda w, h, tw, th: ((w - tw) // 2, h - th - 10),
    "top-left": lambda w, h, tw, th: (10, 10),
    "top-right": lambda w, h, tw, th: (w - tw - 10, 10),
    "bottom-left": lambda w, h, tw, th: (10, h - th - 10),
    "bottom-right": lambda w, h, tw, th: (w - tw - 10, h - th - 10),
}


def overlay_text(
    cap,
    key: str,
    text: str,
    position: str = "center",
    font_size: int = 24,
    color: str = "white",
) -> BlobRef | ImageError:
    """Overlay text on an image at the given position."""
    err = cap._check_op("overlay_text")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    img = img.convert("RGBA")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
    except (OSError, IOError):
        font = ImageFont.load_default(size=font_size)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    w, h = img.size
    pos_fn = POSITIONS.get(position, POSITIONS["center"])
    x, y = pos_fn(w, h, tw, th)
    draw.text((x, y), text, fill=color, font=font)
    return cap._upload_image(img, "text_overlay.png")


def watermark(
    cap,
    key: str,
    watermark_key: str,
    position: str = "bottom-right",
    opacity: float = 0.5,
) -> BlobRef | ImageError:
    """Overlay a watermark image on a base image."""
    err = cap._check_op("watermark")
    if err:
        return ImageError(error=err)
    base, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    mark, dl_err2 = cap._download_image(watermark_key)
    if dl_err2:
        return ImageError(error=dl_err2)
    base = base.convert("RGBA")
    mark = mark.convert("RGBA")
    # Apply opacity
    alpha = mark.getchannel("A")
    alpha = alpha.point(lambda p: int(p * opacity))
    mark.putalpha(alpha)
    # Position
    bw, bh = base.size
    mw, mh = mark.size
    pos_fn = POSITIONS.get(position, POSITIONS["bottom-right"])
    x, y = pos_fn(bw, bh, mw, mh)
    base.paste(mark, (x, y), mark)
    return cap._upload_image(base, "watermarked.png")


def combine(
    cap,
    keys: list[str],
    layout: str = "horizontal",
) -> BlobRef | ImageError:
    """Combine multiple images into one. Layout: horizontal, vertical, or grid."""
    err = cap._check_op("combine")
    if err:
        return ImageError(error=err)
    if not keys:
        return ImageError(error="At least one image key is required")
    images = []
    for k in keys:
        img, dl_err = cap._download_image(k)
        if dl_err:
            return ImageError(error=dl_err)
        images.append(img.convert("RGBA"))

    if layout == "horizontal":
        total_w = sum(im.size[0] for im in images)
        max_h = max(im.size[1] for im in images)
        combined = Image.new("RGBA", (total_w, max_h))
        x = 0
        for im in images:
            combined.paste(im, (x, 0))
            x += im.size[0]
    elif layout == "vertical":
        max_w = max(im.size[0] for im in images)
        total_h = sum(im.size[1] for im in images)
        combined = Image.new("RGBA", (max_w, total_h))
        y = 0
        for im in images:
            combined.paste(im, (0, y))
            y += im.size[1]
    elif layout == "grid":
        import math
        cols = math.ceil(math.sqrt(len(images)))
        rows = math.ceil(len(images) / cols)
        cell_w = max(im.size[0] for im in images)
        cell_h = max(im.size[1] for im in images)
        combined = Image.new("RGBA", (cols * cell_w, rows * cell_h))
        for i, im in enumerate(images):
            r, c = divmod(i, cols)
            combined.paste(im, (c * cell_w, r * cell_h))
    else:
        return ImageError(error=f"Unknown layout '{layout}'; use horizontal, vertical, or grid")

    return cap._upload_image(combined, f"combined_{layout}.png")
```

**Step 4: Wire into `__init__.py`** — replace `# -- Compositing (Task 4) --`:

```python
    # -- Compositing --

    def overlay_text(self, key: str, text: str, position: str = "center", font_size: int = 24, color: str = "white") -> BlobRef | ImageError:
        """Overlay text on an image."""
        from cogos.capabilities.image.compose import overlay_text
        return overlay_text(self, key, text, position, font_size, color)

    def watermark(self, key: str, watermark_key: str, position: str = "bottom-right", opacity: float = 0.5) -> BlobRef | ImageError:
        """Overlay a watermark image."""
        from cogos.capabilities.image.compose import watermark
        return watermark(self, key, watermark_key, position, opacity)

    def combine(self, keys: list[str], layout: str = "horizontal") -> BlobRef | ImageError:
        """Combine multiple images. Layout: horizontal, vertical, grid."""
        from cogos.capabilities.image.compose import combine
        return combine(self, keys, layout)
```

**Step 5: Run tests**

Run: `uv run pytest tests/cogos/capabilities/test_image_compose.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/image/compose.py src/cogos/capabilities/image/__init__.py tests/cogos/capabilities/test_image_compose.py
git commit -m "feat(image): add compositing methods — overlay_text, watermark, combine"
```

---

### Task 5: Implement AI analysis methods + tests

**Files:**
- Create: `src/cogos/capabilities/image/analyze.py`
- Modify: `src/cogos/capabilities/image/__init__.py` (add method delegates)
- Create: `tests/cogos/capabilities/test_image_analyze.py`

**Step 1: Write tests**

```python
"""Tests for image AI analysis methods (Gemini Vision)."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef
from cogos.capabilities.image import ImageCapability, ImageDescription, AnalysisResult, ExtractedText, ImageError


def _make_png() -> bytes:
    img = Image.new("RGBA", (100, 80), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_capability() -> ImageCapability:
    repo = MagicMock()
    return ImageCapability(repo, process_id=MagicMock())


def _mock_blob(cap):
    cap._blob.download = MagicMock(return_value=BlobContent(
        data=_make_png(), filename="test.png", content_type="image/png",
    ))


class TestDescribe:
    @patch("cogos.capabilities.image.analyze.get_gemini_client")
    def test_describe_returns_description(self, mock_get_client):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "A red rectangle on a transparent background"
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        cap = _make_capability()
        _mock_blob(cap)
        result = cap.describe("blobs/test.png")
        assert isinstance(result, ImageDescription)
        assert "red" in result.description.lower()

    def test_describe_scope_denied(self):
        cap = _make_capability()
        cap._scope = {"ops": ["resize"]}
        result = cap.describe("blobs/test.png")
        assert isinstance(result, ImageError)


class TestAnalyze:
    @patch("cogos.capabilities.image.analyze.get_gemini_client")
    def test_analyze_returns_answer(self, mock_get_client):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "The dominant color is red"
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        cap = _make_capability()
        _mock_blob(cap)
        result = cap.analyze("blobs/test.png", prompt="What is the dominant color?")
        assert isinstance(result, AnalysisResult)
        assert "red" in result.answer.lower()


class TestExtractText:
    @patch("cogos.capabilities.image.analyze.get_gemini_client")
    def test_extract_text_returns_text(self, mock_get_client):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello World"
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        cap = _make_capability()
        _mock_blob(cap)
        result = cap.extract_text("blobs/test.png")
        assert isinstance(result, ExtractedText)
        assert result.text == "Hello World"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cogos/capabilities/test_image_analyze.py -v`

**Step 3: Implement `analyze.py`**

```python
"""Image AI analysis — describe, analyze, extract_text via Gemini Vision."""
from __future__ import annotations

import io
import logging

from PIL import Image

from cogos.capabilities.blob import BlobRef
from cogos.capabilities.image import ImageDescription, AnalysisResult, ExtractedText, ImageError
from cogos.capabilities.image._gemini_helper import get_gemini_client

logger = logging.getLogger(__name__)

MODEL = "gemini-2.0-flash"


def _image_to_part(img: Image.Image) -> dict:
    """Convert a PIL Image to a Gemini inline_data part."""
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
        client = get_gemini_client()
        text_prompt = prompt or "Describe this image in detail."
        response = client.models.generate_content(
            model=MODEL,
            contents=[text_prompt, _image_to_part(img)],
        )
        return ImageDescription(key=key, description=response.text)
    except Exception as e:
        return ImageError(error=f"Gemini vision error: {e}")


def analyze(cap, key: str, prompt: str) -> AnalysisResult | ImageError:
    """Answer a question about an image using Gemini Vision."""
    err = cap._check_op("analyze")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[prompt, _image_to_part(img)],
        )
        return AnalysisResult(key=key, answer=response.text)
    except Exception as e:
        return ImageError(error=f"Gemini vision error: {e}")


def extract_text(cap, key: str) -> ExtractedText | ImageError:
    """Extract text from an image using Gemini Vision (OCR)."""
    err = cap._check_op("extract_text")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                "Extract all text visible in this image. Return only the extracted text, nothing else.",
                _image_to_part(img),
            ],
        )
        return ExtractedText(key=key, text=response.text)
    except Exception as e:
        return ImageError(error=f"Gemini vision error: {e}")
```

**Step 4: Wire into `__init__.py`** — replace `# -- Analysis (Task 5) --`:

```python
    # -- Analysis (Gemini Vision) --

    def describe(self, key: str, prompt: str | None = None) -> ImageDescription | ImageError:
        """Describe an image using Gemini Vision."""
        from cogos.capabilities.image.analyze import describe
        return describe(self, key, prompt)

    def analyze(self, key: str, prompt: str) -> AnalysisResult | ImageError:
        """Answer a question about an image."""
        from cogos.capabilities.image.analyze import analyze
        return analyze(self, key, prompt)

    def extract_text(self, key: str) -> ExtractedText | ImageError:
        """Extract text from an image (OCR via Gemini Vision)."""
        from cogos.capabilities.image.analyze import extract_text
        return extract_text(self, key)
```

**Step 5: Run tests**

Run: `uv run pytest tests/cogos/capabilities/test_image_analyze.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/image/analyze.py src/cogos/capabilities/image/__init__.py tests/cogos/capabilities/test_image_analyze.py
git commit -m "feat(image): add AI analysis methods — describe, analyze, extract_text"
```

---

### Task 6: Implement generation methods + tests

**Files:**
- Create: `src/cogos/capabilities/image/generate.py`
- Modify: `src/cogos/capabilities/image/__init__.py` (add method delegates)
- Create: `tests/cogos/capabilities/test_image_generate.py`

**Step 1: Write tests**

```python
"""Tests for image AI generation methods (Gemini)."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

from PIL import Image

from cogos.capabilities.blob import BlobContent, BlobRef
from cogos.capabilities.image import ImageCapability, ImageError


def _make_png() -> bytes:
    img = Image.new("RGBA", (100, 80), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_capability() -> ImageCapability:
    repo = MagicMock()
    cap = ImageCapability(repo, process_id=MagicMock())
    cap._blob.upload = MagicMock(side_effect=lambda data, filename, content_type=None:
        BlobRef(key=f"blobs/fake/{filename}", url="https://fake", filename=filename, size=len(data)))
    return cap


def _mock_gemini_image_response():
    """Create a mock Gemini response with an image part."""
    mock_part = MagicMock()
    mock_part.inline_data.data = _make_png()
    mock_part.inline_data.mime_type = "image/png"
    mock_part.text = None
    mock_candidate = MagicMock()
    mock_candidate.content.parts = [mock_part]
    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    return mock_response


class TestGenerate:
    @patch("cogos.capabilities.image.generate.get_gemini_client")
    def test_generate_returns_blob_ref(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_gemini_image_response()
        mock_get_client.return_value = mock_client

        cap = _make_capability()
        result = cap.generate("a red square on white background")
        assert isinstance(result, BlobRef)
        assert "generated" in result.filename

    def test_generate_scope_denied(self):
        cap = _make_capability()
        cap._scope = {"ops": ["resize"]}
        result = cap.generate("anything")
        assert isinstance(result, ImageError)


class TestEdit:
    @patch("cogos.capabilities.image.generate.get_gemini_client")
    def test_edit_returns_blob_ref(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_gemini_image_response()
        mock_get_client.return_value = mock_client

        cap = _make_capability()
        cap._blob.download = MagicMock(return_value=BlobContent(
            data=_make_png(), filename="test.png", content_type="image/png",
        ))
        result = cap.edit("blobs/test.png", "make the background blue")
        assert isinstance(result, BlobRef)


class TestVariations:
    @patch("cogos.capabilities.image.generate.get_gemini_client")
    def test_variations_returns_list(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = _mock_gemini_image_response()
        mock_get_client.return_value = mock_client

        cap = _make_capability()
        cap._blob.download = MagicMock(return_value=BlobContent(
            data=_make_png(), filename="test.png", content_type="image/png",
        ))
        result = cap.variations("blobs/test.png", count=2)
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(r, BlobRef) for r in result)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/cogos/capabilities/test_image_generate.py -v`

**Step 3: Implement `generate.py`**

```python
"""Image generation — generate, edit, variations via Gemini."""
from __future__ import annotations

import io
import logging

from PIL import Image

from cogos.capabilities.blob import BlobRef
from cogos.capabilities.image import ImageError
from cogos.capabilities.image._gemini_helper import get_gemini_client

logger = logging.getLogger(__name__)

MODEL = "gemini-2.0-flash-exp"  # Image generation model


def _image_to_part(img: Image.Image) -> dict:
    """Convert a PIL Image to a Gemini inline_data part."""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"inline_data": {"mime_type": "image/png", "data": buf.getvalue()}}


def _extract_image_from_response(response) -> bytes | None:
    """Extract image bytes from a Gemini response."""
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data and part.inline_data.data:
                return part.inline_data.data
    return None


def generate(cap, prompt: str, size: str | None = None, style: str | None = None) -> BlobRef | ImageError:
    """Generate an image from a text prompt using Gemini."""
    err = cap._check_op("generate")
    if err:
        return ImageError(error=err)
    try:
        client = get_gemini_client()
        full_prompt = prompt
        if style:
            full_prompt = f"{prompt}, in {style} style"
        if size:
            full_prompt = f"{full_prompt}. Image size: {size}"

        response = client.models.generate_content(
            model=MODEL,
            contents=full_prompt,
            config={"response_modalities": ["IMAGE", "TEXT"]},
        )
        img_bytes = _extract_image_from_response(response)
        if not img_bytes:
            return ImageError(error="Gemini did not return an image")
        result = cap._blob.upload(img_bytes, "generated.png", content_type="image/png")
        from cogos.capabilities.blob import BlobError
        if isinstance(result, BlobError):
            return ImageError(error=result.error)
        return result
    except Exception as e:
        return ImageError(error=f"Gemini generation error: {e}")


def edit(cap, key: str, prompt: str) -> BlobRef | ImageError:
    """Edit an existing image using a text prompt via Gemini."""
    err = cap._check_op("edit")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[prompt, _image_to_part(img)],
            config={"response_modalities": ["IMAGE", "TEXT"]},
        )
        img_bytes = _extract_image_from_response(response)
        if not img_bytes:
            return ImageError(error="Gemini did not return an edited image")
        result = cap._blob.upload(img_bytes, "edited.png", content_type="image/png")
        from cogos.capabilities.blob import BlobError
        if isinstance(result, BlobError):
            return ImageError(error=result.error)
        return result
    except Exception as e:
        return ImageError(error=f"Gemini edit error: {e}")


def variations(cap, key: str, count: int = 2) -> list[BlobRef] | ImageError:
    """Generate variations of an existing image via Gemini."""
    err = cap._check_op("variations")
    if err:
        return ImageError(error=err)
    img, dl_err = cap._download_image(key)
    if dl_err:
        return ImageError(error=dl_err)
    results: list[BlobRef] = []
    try:
        client = get_gemini_client()
        for i in range(count):
            response = client.models.generate_content(
                model=MODEL,
                contents=[
                    f"Generate a creative variation (#{i+1}) of this image. Keep the same subject but vary style/composition.",
                    _image_to_part(img),
                ],
                config={"response_modalities": ["IMAGE", "TEXT"]},
            )
            img_bytes = _extract_image_from_response(response)
            if not img_bytes:
                return ImageError(error=f"Gemini did not return variation #{i+1}")
            result = cap._blob.upload(img_bytes, f"variation_{i+1}.png", content_type="image/png")
            from cogos.capabilities.blob import BlobError
            if isinstance(result, BlobError):
                return ImageError(error=result.error)
            results.append(result)
        return results
    except Exception as e:
        return ImageError(error=f"Gemini variation error: {e}")
```

**Step 4: Wire into `__init__.py`** — replace `# -- Generation (Task 6) --`:

```python
    # -- Generation (Gemini) --

    def generate(self, prompt: str, size: str | None = None, style: str | None = None) -> BlobRef | ImageError:
        """Generate an image from a text prompt."""
        from cogos.capabilities.image.generate import generate
        return generate(self, prompt, size, style)

    def edit(self, key: str, prompt: str) -> BlobRef | ImageError:
        """Edit an existing image using a text prompt."""
        from cogos.capabilities.image.generate import edit
        return edit(self, key, prompt)

    def variations(self, key: str, count: int = 2) -> list[BlobRef] | ImageError:
        """Generate variations of an existing image."""
        from cogos.capabilities.image.generate import variations
        return variations(self, key, count)
```

**Step 5: Run tests**

Run: `uv run pytest tests/cogos/capabilities/test_image_generate.py -v`
Expected: all PASS

**Step 6: Commit**

```bash
git add src/cogos/capabilities/image/generate.py src/cogos/capabilities/image/__init__.py tests/cogos/capabilities/test_image_generate.py
git commit -m "feat(image): add AI generation methods — generate, edit, variations"
```

---

### Task 7: Register capability and update image

**Files:**
- Modify: `src/cogos/capabilities/__init__.py:973` (add image entry before closing `]`)
- Modify: `images/cogent-v1/init/processes.py` (add "image" and "blob" to capabilities list)
- Modify: `src/tool.hatch.build.targets.wheel` in `pyproject.toml:52` (add image package)

**Step 1: Add to BUILTIN_CAPABILITIES**

Insert before the closing `]` in `src/cogos/capabilities/__init__.py`:

```python
    {
        "name": "image",
        "description": "Manipulate, compose, analyze, and generate images. All operations are blob-key oriented.",
        "handler": "cogos.capabilities.image.ImageCapability",
        "instructions": (
            "Use image to work with images. All ops take/return blob keys.\n"
            "Manipulation:\n"
            "- image.resize(key, width?, height?) — resize (auto-aspect if one dim omitted)\n"
            "- image.crop(key, left, top, right, bottom) — crop region\n"
            "- image.rotate(key, degrees) — rotate\n"
            "- image.convert(key, format) — convert format (PNG, JPEG, WEBP)\n"
            "- image.thumbnail(key, max_size) — fit within box\n"
            "Compositing:\n"
            "- image.overlay_text(key, text, position?, font_size?, color?) — add text\n"
            "- image.watermark(key, watermark_key, position?, opacity?) — add watermark\n"
            "- image.combine(keys, layout?) — stitch images (horizontal/vertical/grid)\n"
            "Analysis (Gemini Vision):\n"
            "- image.describe(key, prompt?) — describe/caption image\n"
            "- image.analyze(key, prompt) — answer questions about image\n"
            "- image.extract_text(key) — OCR\n"
            "Generation (Gemini):\n"
            "- image.generate(prompt, size?, style?) — text-to-image\n"
            "- image.edit(key, prompt) — edit image with prompt\n"
            "- image.variations(key, count?) — generate variations\n"
            "Pipeline: generate → resize → overlay_text → send via discord"
        ),
        "schema": {
            "scope": {
                "properties": {
                    "ops": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "resize", "crop", "rotate", "convert", "thumbnail",
                                "overlay_text", "watermark", "combine",
                                "describe", "analyze", "extract_text",
                                "generate", "edit", "variations",
                            ],
                        },
                    },
                },
            },
        },
    },
```

**Step 2: Add "image" and "blob" to init process capabilities**

In `images/cogent-v1/init/processes.py`, update the capabilities list:

```python
    capabilities=[
        "me", "procs", "dir", "file", "discord", "channels",
        "secrets", "stdlib", "coglet_factory", "coglet", "alerts",
        "blob", "image",
    ],
```

**Step 3: Add image package to hatch build**

In `pyproject.toml`, append to `packages` list in `[tool.hatch.build.targets.wheel]`:

```
packages = ["src/cli", "src/body", "src/cogtainer", "src/memory", "src/run", "src/polis", "src/dashboard", "src/cogos", "src/cogos/io", "src/cogos/io/email", "src/cogos/io/discord", "src/cogos/io/github", "src/cogos/io/asana", "src/cogos/capabilities/image"]
```

**Step 4: Run full test suite**

Run: `uv run pytest tests/cogos/capabilities/test_image_*.py -v`
Expected: all PASS

**Step 5: Run existing tests to check for regressions**

Run: `uv run pytest tests/ -v --timeout 60`
Expected: no regressions

**Step 6: Commit**

```bash
git add src/cogos/capabilities/__init__.py images/cogent-v1/init/processes.py pyproject.toml
git commit -m "feat(image): register image capability in BUILTIN_CAPABILITIES and init process"
```

---

### Task 8: Provision Gemini API key secrets

**This is a manual/operational step** — document commands but don't run in CI.

**Step 1: Create master secret**

```bash
aws secretsmanager create-secret \
  --name polis/shared/gemini-api-key \
  --secret-string "<GEMINI_API_KEY>" \
  --profile softmax-org \
  --region us-east-1
```

**Step 2: Copy to each cogent**

```bash
# For each cogent (e.g. dr.alpha, dr.beta):
aws secretsmanager create-secret \
  --name cogent/dr.alpha/gemini \
  --secret-string "<GEMINI_API_KEY>" \
  --profile softmax-org \
  --region us-east-1
```

**Step 3: Verify from cogent context**

```bash
cogent dr.alpha cogos process run test-image --local
```
