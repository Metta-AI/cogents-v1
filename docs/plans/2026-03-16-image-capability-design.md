# Image Capability Design

## Overview

Add a unified `image` capability to CogOS that provides pixel manipulation, compositing, AI-powered analysis (Gemini Vision), and AI-powered generation (Gemini image generation). All operations are blob-key oriented: input blob keys, output new blob keys.

## Architecture

Single capability (`image`) with methods grouped into submodules:

```
src/cogos/capabilities/image/
  __init__.py          # ImageCapability class, aggregates all methods
  _gemini_helper.py    # shared Gemini client init
  manipulate.py        # resize, crop, rotate, convert, thumbnail
  compose.py           # overlay_text, watermark, combine
  analyze.py           # describe, analyze, extract_text (Gemini vision)
  generate.py          # generate, edit, variations (Gemini generation)
```

## API Surface

All methods live on `ImageCapability`:

### Manipulation (Pillow)
- `resize(key, width, height?) -> BlobRef` — auto-aspect if one dimension omitted
- `crop(key, left, top, right, bottom) -> BlobRef`
- `rotate(key, degrees) -> BlobRef`
- `convert(key, format) -> BlobRef` — e.g. PNG to JPEG
- `thumbnail(key, max_size) -> BlobRef` — fit within box

### Compositing (Pillow)
- `overlay_text(key, text, position, font_size?, color?) -> BlobRef`
- `watermark(key, watermark_key, position?, opacity?) -> BlobRef`
- `combine(keys, layout) -> BlobRef` — horizontal/vertical/grid

### Analysis (Gemini Vision)
- `describe(key, prompt?) -> ImageDescription`
- `analyze(key, prompt) -> AnalysisResult`
- `extract_text(key) -> ExtractedText`

### Generation (Gemini Image Generation)
- `generate(prompt, size?, style?) -> BlobRef`
- `edit(key, prompt) -> BlobRef`
- `variations(key, count?) -> list[BlobRef]`

## Pipeline Example

```python
ref = image.generate("a sunset over mountains")
ref2 = image.resize(ref.key, width=800)
ref3 = image.overlay_text(ref2.key, "Good morning!", position="bottom")
discord.send(channel, "Here you go", files=[ref3.key])
```

## Dependencies

- `Pillow` — manipulation and compositing
- `google-genai` — Gemini SDK for vision and generation

No new infrastructure. Uses existing S3 bucket (`SESSIONS_BUCKET`) via blob capability.

## Secrets

- Master key: `polis/shared/gemini-api-key`
- Per-cogent copy: `cogent/{name}/gemini`
- `_gemini_helper.py` fetches the key via SecretsCapability internally

## Scope

Single `ops` set covering all methods. Processes can be scoped to any subset:

```python
capabilities=["image.scope(ops=['resize', 'describe'])"]
```

## Registration

One entry in `BUILTIN_CAPABILITIES`:
- name: `image`
- handler: `cogos.capabilities.image.ImageCapability`

Add `"image"` and `"blob"` to init process capabilities in `images/cogent-v1/init/processes.py`.

## Intermediate Format

All intermediate images stored as PNG (lossless). Format conversion only on explicit `convert()`. Content-type metadata set on S3 upload.

## Size Limits

Inherit from blob capability's `max_size_bytes` scope. Output size checked before upload.

## Testing

- `tests/cogos/capabilities/test_image_manipulate.py` — fixture PNGs, verify dimensions/format
- `tests/cogos/capabilities/test_image_compose.py` — verify text overlay, combine output
- `tests/cogos/capabilities/test_image_analyze.py` — mock Gemini client
- `tests/cogos/capabilities/test_image_generate.py` — mock Gemini client
