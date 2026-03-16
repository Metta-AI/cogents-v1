"""Image manipulation operations — resize, crop, rotate, convert, thumbnail."""
from __future__ import annotations

import os

from cogos.capabilities.blob import BlobRef
from cogos.capabilities.image import ImageError


def resize(cap, key: str, width: int | None = None, height: int | None = None) -> BlobRef | ImageError:
    """Resize an image. If only one dimension given, preserves aspect ratio."""
    from PIL import Image

    err = cap._check_op("resize")
    if err:
        return ImageError(error=err)

    if width is None and height is None:
        return ImageError(error="At least one of width or height must be specified")

    img, err = cap._download_image(key)
    if err:
        return ImageError(error=err)

    orig_w, orig_h = img.size
    if width is not None and height is not None:
        new_size = (width, height)
    elif width is not None:
        ratio = width / orig_w
        new_size = (width, round(orig_h * ratio))
    else:
        ratio = height / orig_h
        new_size = (round(orig_w * ratio), height)

    img = img.resize(new_size, Image.LANCZOS)
    filename = os.path.basename(key) if "/" in key else key
    fmt = _format_from_filename(filename)
    return cap._upload_image(img, filename, fmt)


def crop(cap, key: str, left: int, top: int, right: int, bottom: int) -> BlobRef | ImageError:
    """Crop an image to the given bounding box."""
    err = cap._check_op("crop")
    if err:
        return ImageError(error=err)

    img, err = cap._download_image(key)
    if err:
        return ImageError(error=err)

    img = img.crop((left, top, right, bottom))
    filename = os.path.basename(key) if "/" in key else key
    fmt = _format_from_filename(filename)
    return cap._upload_image(img, filename, fmt)


def rotate(cap, key: str, degrees: float) -> BlobRef | ImageError:
    """Rotate an image by the given degrees."""
    err = cap._check_op("rotate")
    if err:
        return ImageError(error=err)

    img, err = cap._download_image(key)
    if err:
        return ImageError(error=err)

    img = img.rotate(degrees, expand=True)
    filename = os.path.basename(key) if "/" in key else key
    fmt = _format_from_filename(filename)
    return cap._upload_image(img, filename, fmt)


def convert(cap, key: str, format: str) -> BlobRef | ImageError:
    """Convert an image to a different format (PNG, JPEG, WEBP)."""
    err = cap._check_op("convert")
    if err:
        return ImageError(error=err)

    fmt = format.upper()
    if fmt not in ("PNG", "JPEG", "WEBP"):
        return ImageError(error=f"Unsupported format: {format}")

    img, err = cap._download_image(key)
    if err:
        return ImageError(error=err)

    # Build new filename with correct extension
    filename = os.path.basename(key) if "/" in key else key
    base, _ = os.path.splitext(filename)
    ext_map = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
    filename = base + ext_map[fmt]

    return cap._upload_image(img, filename, fmt)


def thumbnail(cap, key: str, max_size: int) -> BlobRef | ImageError:
    """Create a thumbnail that fits within a max_size x max_size box."""
    err = cap._check_op("thumbnail")
    if err:
        return ImageError(error=err)

    img, err = cap._download_image(key)
    if err:
        return ImageError(error=err)

    img.thumbnail((max_size, max_size))
    filename = os.path.basename(key) if "/" in key else key
    fmt = _format_from_filename(filename)
    return cap._upload_image(img, filename, fmt)


def _format_from_filename(filename: str) -> str:
    """Infer image format from filename extension."""
    ext = os.path.splitext(filename)[1].lower()
    return {
        ".png": "PNG",
        ".jpg": "JPEG",
        ".jpeg": "JPEG",
        ".webp": "WEBP",
    }.get(ext, "PNG")
