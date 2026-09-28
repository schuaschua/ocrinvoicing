"""Reading an upload original for the quality stage (AD-6, AD-9, AD-19): Pillow for
images, ImageHash for the perceptual hash and pypdf for a PDF's page count. The
readability rules themselves are in `domain/quality.py`.

Images are measured the way the page measures them (`shared/quality/`): EXIF
orientation applied, scaled so the long side is at most `max_long_side_px`, then
grey as Pillow "L". The phash is taken from the same oriented copy. Transparent
pixels are composited over white paper and 16-bit images scaled to 8 bits first, so
neither reads as dark.

The measures are the domain's (`domain/quality.py`), vectorised with numpy here: the
pure-Python reference is kept for the tests, which assert both give the same numbers.

Bounded work: an image over Pillow's pixel limit is refused before it is decoded
(`DecompressionBombWarning` is an error here), and a PDF is only opened, checked for
encryption and counted. `MemoryError` is never read as "unreadable": it is raised,
so the host retries the message.
"""

import io
import json
import warnings
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import imagehash
import numpy as np
from PIL import ExifTags, Image, ImageOps
from pypdf import PdfReader

from invoicing.domain.exif_time import photo_taken_at
from invoicing.domain.quality import (
    ImageMeasures,
    QualityThresholds,
    analysis_size,
)
from invoicing.domain.upload import UploadContentType

QUALITY_THRESHOLDS_FILE = "quality-thresholds.json"

# EXIF tags in the Exif sub-IFD (0x8769).
_DATE_TIME_ORIGINAL = ExifTags.Base.DateTimeOriginal
_OFFSET_TIME_ORIGINAL = ExifTags.Base.OffsetTimeOriginal


def _thresholds_file() -> Path:
    """shared/quality-thresholds.json: at the deploy package's root (ci/code-deploy.sh
    copies it there) or, in the repository, at the repository root."""
    parents = Path(__file__).resolve().parents
    # <package>/invoicing/adapters, then <repo>/backend/src/invoicing/adapters.
    for depth in (2, 4):
        if depth < len(parents):
            candidate = parents[depth] / "shared" / QUALITY_THRESHOLDS_FILE
            if candidate.is_file():
                return candidate
    raise RuntimeError(f"shared/{QUALITY_THRESHOLDS_FILE} not found")


def load_quality_thresholds(path: Path | None = None) -> QualityThresholds:
    """The thresholds the page uses too (AD-6), from their one file."""
    data = json.loads((path or _thresholds_file()).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{QUALITY_THRESHOLDS_FILE} must hold a JSON object")
    return QualityThresholds.from_json(data)


@dataclass(frozen=True)
class ImageFacts:
    """An image's measures (None when it can't be decoded), phash and photo time."""

    measures: ImageMeasures | None
    phash: int | None
    photo_taken_at: datetime | None


@dataclass(frozen=True)
class PdfFacts:
    """A PDF's page count, or None when it can't be read."""

    page_count: int | None


def read_document(
    data: bytes, content_type: UploadContentType, thresholds: QualityThresholds
) -> ImageFacts | PdfFacts:
    """What the quality stage needs from an original of `content_type` (the type
    sniffed from its bytes at upload, AD-6). CPU-bound: run it off the event loop."""
    if content_type is UploadContentType.PDF:
        return PdfFacts(pdf_page_count(data))
    return read_image(data, thresholds.max_long_side_px)


def pdf_page_count(data: bytes) -> int | None:
    """The number of pages, or None for bytes pypdf can't read, including an
    encrypted PDF (its pages can't be read without the password)."""
    try:
        with warnings.catch_warnings():
            # pypdf warns about repaired files; the log must not carry their text.
            warnings.simplefilter("ignore")
            # Non-strict, and nothing beyond the page tree is read.
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                return None
            return len(reader.pages)
    except MemoryError:
        raise
    # Any failure to parse (including a looping page tree) means unreadable (AD-6);
    # the text may quote file bytes.
    except Exception:  # noqa: BLE001
        return None


def measure_grey(grey: np.ndarray) -> ImageMeasures:
    """The domain's two measures (`mean_luminance`, `laplacian_variance`) over an
    8-bit grey array, vectorised. Integer sums, so the result equals the reference."""
    g = grey.astype(np.int64)
    height, width = g.shape
    mean = float(g.sum()) / g.size if g.size else 0.0
    if width < 3 or height < 3:
        return ImageMeasures(mean_luminance=mean, laplacian_variance=0.0)
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4 * g[1:-1, 1:-1]
    n = lap.size
    lap_mean = int(lap.sum()) / n
    variance = int((lap * lap).sum()) / n - lap_mean * lap_mean
    return ImageMeasures(mean_luminance=mean, laplacian_variance=variance)


_WHITE = (255, 255, 255, 255)


def to_rgb(image: Image.Image) -> Image.Image:
    """An 8-bit RGB copy as a viewer shows it: transparency composited over white
    paper, and 16- or 32-bit grey scaled to 8 bits (not clipped)."""
    mode = image.mode
    if mode.startswith("I;16") or mode in ("I", "F"):
        values = np.asarray(image, dtype=np.float64)
        # 16-bit samples (Pillow opens 16-bit grey PNGs as I;16 or I) span 0-65535.
        if mode.startswith("I;16") or values.max(initial=0) > 255:
            values = values / 257.0
        grey = np.clip(np.rint(values), 0, 255).astype(np.uint8)
        return Image.fromarray(grey, "L").convert("RGB")
    has_alpha = mode in ("RGBA", "LA", "PA", "La", "RGBa") or (
        mode == "P" and "transparency" in image.info
    )
    if has_alpha:
        rgba = image.convert("RGBA")
        paper = Image.new("RGBA", rgba.size, _WHITE)
        return Image.alpha_composite(paper, rgba).convert("RGB")
    return image.convert("RGB")


def read_image(data: bytes, max_long_side: int) -> ImageFacts:
    """Measures, phash and photo time of an image. Bytes that don't decode, or would
    decode to more pixels than Pillow's limit, give no measures and no phash."""
    try:
        with warnings.catch_warnings():
            # Pillow only warns between 1x and 2x its pixel limit; refuse those too,
            # before any pixel is decoded.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as opened:
                # The same cap without relying on the (process-wide) warning filter.
                limit = Image.MAX_IMAGE_PIXELS
                if limit is not None and opened.width * opened.height > limit:
                    raise ValueError("over the pixel limit")
                taken_at = _photo_taken_at(opened)
                # Decode JPEGs already reduced, like the page does; `draft` only picks
                # a scale at least as large as asked, so the resize below sets the size.
                opened.draft("RGB", (max_long_side, max_long_side))
                oriented = ImageOps.exif_transpose(opened)
                size = analysis_size(oriented.width, oriented.height, max_long_side)
                # [ASSUMPTION] Bilinear, like a browser canvas downscale; calibrated
                # with the thresholds (AD-6 Open Questions).
                scaled = to_rgb(oriented).resize(size, Image.Resampling.BILINEAR)
                measures = measure_grey(np.asarray(scaled.convert("L")))
                phash = int(str(imagehash.phash(scaled)), 16)
    except MemoryError:
        # Out of memory says nothing about the invoice: retry, never UNREADABLE.
        raise
    # Corrupt, truncated or unsupported bytes, or a decompression bomb: unreadable.
    except Exception:  # noqa: BLE001
        return ImageFacts(measures=None, phash=None, photo_taken_at=None)
    return ImageFacts(measures=measures, phash=phash, photo_taken_at=taken_at)


def _photo_taken_at(image: Image.Image) -> datetime | None:
    """EXIF `DateTimeOriginal` (with `OffsetTimeOriginal`), as UTC (AD-19)."""
    try:
        exif = image.getexif().get_ifd(ExifTags.IFD.Exif)
    # A broken EXIF block only loses the photo time, never the image.
    except Exception:  # noqa: BLE001
        return None
    original = exif.get(_DATE_TIME_ORIGINAL)
    offset = exif.get(_OFFSET_TIME_ORIGINAL)
    return photo_taken_at(
        original if isinstance(original, str) else None,
        offset if isinstance(offset, str) else None,
    )
