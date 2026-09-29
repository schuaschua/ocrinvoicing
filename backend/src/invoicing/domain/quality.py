"""The server readability check of the `quality` stage (AD-6, CAP-3).

The same measures and thresholds as the page's device check (`shared/quality/`):
mean luminance for darkness and the variance of the 4-neighbour Laplacian for blur,
both over a grey (Pillow "L") copy whose long side is at most
`analysis.max_long_side_px`, EXIF orientation applied. Decoding and scaling happen in
an adapter; these functions only see the grey pixel values. `mean_luminance` and
`laplacian_variance` are the reference definitions: the adapter computes the same
numbers vectorised (`adapters/documents.py measure_grey`), and the tests hold the two
equal.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from invoicing.domain.reasons import ReasonCode

# AD-6: a PDF of more than 2 pages is not one invoice.
MAX_PDF_PAGES = 2
# The Laplacian needs a 3 x 3 image at least.
MIN_LONG_SIDE_PX = 3


@dataclass(frozen=True)
class QualityThresholds:
    """The server's part of `shared/quality-thresholds.json`."""

    max_long_side_px: int
    min_variance: float
    min_mean_luminance: float

    @classmethod
    def from_json(cls, data: Mapping[str, object]) -> Self:
        """Read `analysis.max_long_side_px`, `blur.min_variance` and
        `darkness.min_mean_luminance`; a missing or non-positive value is a
        ValueError naming the key."""
        max_long_side = _positive(data, "analysis", "max_long_side_px")
        # A whole number of pixels, and big enough to have an inner pixel (3 x 3).
        if not float(max_long_side).is_integer() or max_long_side < MIN_LONG_SIDE_PX:
            raise ValueError(
                "quality thresholds: analysis.max_long_side_px must be an integer"
                f" of at least {MIN_LONG_SIDE_PX}"
            )
        return cls(
            max_long_side_px=int(max_long_side),
            min_variance=_positive(data, "blur", "min_variance"),
            min_mean_luminance=_positive(data, "darkness", "min_mean_luminance"),
        )


def _positive(data: Mapping[str, object], section: str, key: str) -> float:
    group = data.get(section)
    value = group.get(key) if isinstance(group, Mapping) else None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(
            f"quality thresholds: {section}.{key} must be a positive number"
        )
    return float(value)


def analysis_size(width: int, height: int, max_long_side: int) -> tuple[int, int]:
    """The size to measure a `width` x `height` image at: long side at most
    `max_long_side`, never enlarged. Rounds half up, as the page does (JS Math.round)."""
    scale = min(1.0, max_long_side / max(width, height, 1))
    return (
        max(1, math.floor(width * scale + 0.5)),
        max(1, math.floor(height * scale + 0.5)),
    )


@dataclass(frozen=True)
class GreyImage:
    """One luminance value (0-255) per pixel, row by row."""

    width: int
    height: int
    values: Sequence[int] | bytes

    def __post_init__(self) -> None:
        if (
            self.width < 0
            or self.height < 0
            or len(self.values) != self.width * self.height
        ):
            raise ValueError("grey values must be width x height long")


def mean_luminance(grey: GreyImage) -> float:
    """Mean luminance, 0-255 (the darkness measure); 0 for an empty image."""
    if not grey.values:
        return 0.0
    return sum(grey.values) / len(grey.values)


def laplacian_variance(grey: GreyImage) -> float:
    """Variance of the Laplacian (the blur measure): the kernel [0 1 0; 1 -4 1; 0 1 0]
    over every pixel with all four neighbours; 0 for an image under 3 x 3."""
    w, h, g = grey.width, grey.height, grey.values
    if w < 3 or h < 3:
        return 0.0
    total = 0
    total_sq = 0
    for y in range(1, h - 1):
        above = g[(y - 1) * w : y * w]
        row = g[y * w : (y + 1) * w]
        below = g[(y + 1) * w : (y + 2) * w]
        for x in range(1, w - 1):
            lap = above[x] + below[x] + row[x - 1] + row[x + 1] - 4 * row[x]
            total += lap
            total_sq += lap * lap
    n = (w - 2) * (h - 2)
    mean = total / n
    return total_sq / n - mean * mean


@dataclass(frozen=True)
class ImageMeasures:
    """The two readability measures of one image."""

    mean_luminance: float
    laplacian_variance: float


def measure(grey: GreyImage) -> ImageMeasures:
    """Both measures of `grey`."""
    return ImageMeasures(mean_luminance(grey), laplacian_variance(grey))


class PhotoProblem(StrEnum):
    """Why a photo is unreadable, darkness first (a dark photo also looks blurry)."""

    DARK = "dark"
    BLURRY = "blurry"


def photo_problem(
    measures: ImageMeasures, thresholds: QualityThresholds
) -> PhotoProblem | None:
    """The first problem of a photo, or None when it is readable."""
    if measures.mean_luminance < thresholds.min_mean_luminance:
        return PhotoProblem.DARK
    if measures.laplacian_variance < thresholds.min_variance:
        return PhotoProblem.BLURRY
    return None


def image_reason(
    measures: ImageMeasures | None, thresholds: QualityThresholds
) -> ReasonCode | None:
    """The admin reason for an image, or None to go on to extraction. `measures` is
    None when the bytes could not be decoded. An upload whose device check was
    overridden or skipped is judged the same way (AD-6)."""
    if measures is None or photo_problem(measures, thresholds) is not None:
        return ReasonCode.UNREADABLE
    return None


def pdf_reason(page_count: int | None) -> ReasonCode | None:
    """The admin reason for a PDF, or None to go on to extraction. `page_count` is
    None when the PDF could not be read."""
    if page_count is None or page_count < 1:
        return ReasonCode.UNREADABLE
    if page_count > MAX_PDF_PAGES:
        return ReasonCode.UNSUPPORTED_DOCUMENT
    return None
