"""Story 2.1: the server readability rules (AD-6) and `photo_taken_at` (AD-19)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from invoicing.domain.exif_time import photo_taken_at
from invoicing.domain.quality import (
    MAX_PDF_PAGES,
    GreyImage,
    ImageMeasures,
    PhotoProblem,
    QualityThresholds,
    analysis_size,
    image_reason,
    laplacian_variance,
    mean_luminance,
    measure,
    pdf_reason,
    photo_problem,
)
from invoicing.domain.reasons import ReasonCode

THRESHOLDS_FILE = (
    Path(__file__).resolve().parents[3] / "shared" / "quality-thresholds.json"
)
THRESHOLDS = QualityThresholds(
    max_long_side_px=1024, min_variance=100.0, min_mean_luminance=60.0
)


def test_story_2_1_thresholds_are_read_from_the_shared_file() -> None:
    data = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    thresholds = QualityThresholds.from_json(data)
    assert thresholds == QualityThresholds(
        max_long_side_px=data["analysis"]["max_long_side_px"],
        min_variance=data["blur"]["min_variance"],
        min_mean_luminance=data["darkness"]["min_mean_luminance"],
    )


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (
            {"blur": {"min_variance": 1}, "darkness": {"min_mean_luminance": 1}},
            "analysis.max_long_side_px",
        ),
        (
            {
                "analysis": {"max_long_side_px": 1024},
                "blur": {"min_variance": 0},
                "darkness": {"min_mean_luminance": 1},
            },
            "blur.min_variance",
        ),
        (
            {
                "analysis": {"max_long_side_px": 1024},
                "blur": {"min_variance": 1},
                "darkness": {"min_mean_luminance": True},
            },
            "darkness.min_mean_luminance",
        ),
        (
            {
                "analysis": {"max_long_side_px": "1024"},
                "blur": {"min_variance": 1},
                "darkness": {"min_mean_luminance": 1},
            },
            "analysis.max_long_side_px",
        ),
        (
            {
                "analysis": 3,
                "blur": {"min_variance": 1},
                "darkness": {"min_mean_luminance": 1},
            },
            "analysis.max_long_side_px",
        ),
    ],
)
def test_story_2_1_a_missing_or_bad_threshold_is_named(
    data: dict[str, object], key: str
) -> None:
    with pytest.raises(ValueError, match=key.replace(".", r"\.")):
        QualityThresholds.from_json(data)


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((4000, 3000), (1024, 768)),
        ((3000, 4000), (768, 1024)),
        ((800, 600), (800, 600)),  # never enlarged
        ((2049, 1), (1024, 1)),
        ((0, 0), (1, 1)),
        ((1025, 1025), (1024, 1024)),
        ((3000, 1500), (1024, 512)),
        ((2048, 1023), (1024, 512)),  # 511.5 rounds half up, as JS Math.round
    ],
)
def test_story_2_1_analysis_size_matches_the_page(
    size: tuple[int, int], expected: tuple[int, int]
) -> None:
    assert analysis_size(*size, 1024) == expected


def _grey(rows: list[list[int]]) -> GreyImage:
    return GreyImage(len(rows[0]), len(rows), bytes(v for row in rows for v in row))


def test_story_2_1_mean_luminance() -> None:
    assert mean_luminance(_grey([[0, 255], [255, 0]])) == 127.5
    assert mean_luminance(GreyImage(0, 0, b"")) == 0.0


def test_story_2_1_laplacian_variance_uses_the_4_neighbour_kernel() -> None:
    flat = _grey([[50] * 5 for _ in range(5)])
    assert laplacian_variance(flat) == 0.0
    # One bright pixel in the middle of a 3 x 3: one Laplacian value, so no variance.
    assert laplacian_variance(_grey([[0, 0, 0], [0, 100, 0], [0, 0, 0]])) == 0.0
    # A 3 x 4 image has two inner pixels: -400 and 100, mean -150, variance 62500.
    assert (
        laplacian_variance(_grey([[0, 0, 0, 0], [0, 100, 0, 0], [0, 0, 0, 0]]))
        == 62500.0
    )
    # Too small to have an inner pixel.
    assert laplacian_variance(_grey([[1, 2], [3, 4]])) == 0.0


def test_story_2_1_grey_values_must_fill_the_image() -> None:
    with pytest.raises(ValueError):
        GreyImage(2, 2, b"\x00\x00\x00")


def test_story_2_1_sharp_text_measures_as_readable() -> None:
    rows = [
        [25 if (y % 5 < 2 and x % 9 < 7) else 235 for x in range(60)] for y in range(40)
    ]
    measures = measure(_grey(rows))
    assert measures.mean_luminance > THRESHOLDS.min_mean_luminance
    assert measures.laplacian_variance > THRESHOLDS.min_variance
    assert photo_problem(measures, THRESHOLDS) is None


@pytest.mark.parametrize(
    ("measures", "problem"),
    [
        (
            ImageMeasures(mean_luminance=59.9, laplacian_variance=5000),
            PhotoProblem.DARK,
        ),
        # Darkness is named first: a dark photo also looks blurry.
        (ImageMeasures(mean_luminance=10, laplacian_variance=1), PhotoProblem.DARK),
        (
            ImageMeasures(mean_luminance=200, laplacian_variance=99.9),
            PhotoProblem.BLURRY,
        ),
        (ImageMeasures(mean_luminance=60, laplacian_variance=100), None),
    ],
)
def test_story_2_1_photo_problem_uses_the_shared_thresholds(
    measures: ImageMeasures, problem: PhotoProblem | None
) -> None:
    assert photo_problem(measures, THRESHOLDS) is problem
    expected = None if problem is None else ReasonCode.UNREADABLE
    assert image_reason(measures, THRESHOLDS) is expected


def test_story_2_1_an_image_that_cannot_be_decoded_is_unreadable() -> None:
    assert image_reason(None, THRESHOLDS) is ReasonCode.UNREADABLE


@pytest.mark.parametrize(
    ("pages", "reason"),
    [
        (1, None),
        (2, None),
        (3, ReasonCode.UNSUPPORTED_DOCUMENT),
        (40, ReasonCode.UNSUPPORTED_DOCUMENT),
        (0, ReasonCode.UNREADABLE),
        (None, ReasonCode.UNREADABLE),
    ],
)
def test_story_2_1_pdf_rules(pages: int | None, reason: ReasonCode | None) -> None:
    assert MAX_PDF_PAGES == 2
    assert pdf_reason(pages) is reason


@pytest.mark.parametrize(
    ("original", "offset", "expected"),
    [
        # Singapore time when there is no offset (AD-19).
        ("2026:09:20 14:30:05", None, datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("2026:09:20 14:30:05\x00", "", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("2026:09:20 14:30:05", "+02:00", datetime(2026, 9, 20, 12, 30, 5, tzinfo=UTC)),
        ("2026:09:20 01:00:00", "-05:30", datetime(2026, 9, 20, 6, 30, 0, tzinfo=UTC)),
        ("2026:09:20 14:30:05", "+00:00", datetime(2026, 9, 20, 14, 30, 5, tzinfo=UTC)),
        # A malformed offset is ignored, not guessed.
        ("2026:09:20 14:30:05", "+8", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("2026:09:20 14:30:05", "+15:00", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("2026:09:20 14:30:05", "+08:75", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        # Malformed or unset dates give no photo time.
        (None, "+08:00", None),
        ("", None, None),
        ("2026-09-20 14:30:05", None, None),
        ("0000:00:00 00:00:00", None, None),
        ("2026:02:30 10:00:00", None, None),
        ("2026:09:20 25:00:00", None, None),
        ("    :  :     :  :  ", None, None),
    ],
)
def test_story_2_1_photo_taken_at_is_utc_from_singapore_or_the_given_offset(
    original: str | None, offset: str | None, expected: datetime | None
) -> None:
    assert photo_taken_at(original, offset) == expected


@pytest.mark.parametrize("value", [1023.5, 2, 0.5, 2.9])
def test_story_2_1_max_long_side_must_be_an_integer_of_at_least_3(value: float) -> None:
    data = {
        "analysis": {"max_long_side_px": value},
        "blur": {"min_variance": 1},
        "darkness": {"min_mean_luminance": 1},
    }
    with pytest.raises(
        ValueError, match=r"analysis\.max_long_side_px must be an integer"
    ):
        QualityThresholds.from_json(data)


@pytest.mark.parametrize("value", [3, 1024, 1024.0])
def test_story_2_1_whole_max_long_sides_are_accepted(value: float) -> None:
    data = {
        "analysis": {"max_long_side_px": value},
        "blur": {"min_variance": 1},
        "darkness": {"min_mean_luminance": 1},
    }
    assert QualityThresholds.from_json(data).max_long_side_px == int(value)


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        # Real offsets run from -12:00 to +14:00; outside it the offset is ignored and
        # the time is read as Singapore time.
        ("-13:00", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("-12:00", datetime(2026, 9, 21, 2, 30, 5, tzinfo=UTC)),
        ("+14:00", datetime(2026, 9, 20, 0, 30, 5, tzinfo=UTC)),
        ("+14:30", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("-12:30", datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
    ],
)
def test_story_2_1_offsets_outside_minus_12_to_plus_14_are_ignored(
    offset: str, expected: datetime
) -> None:
    assert photo_taken_at("2026:09:20 14:30:05", offset) == expected
