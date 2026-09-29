"""Story 2.1: the server readability rules (AD-6) and `photo_taken_at` (AD-19)."""

from invoicing.domain.quality import (
    GreyImage,
    QualityThresholds,
    measure,
    photo_problem,
)

THRESHOLDS = QualityThresholds(
    max_long_side_px=1024, min_variance=100.0, min_mean_luminance=60.0
)


def _grey(rows: list[list[int]]) -> GreyImage:
    return GreyImage(len(rows[0]), len(rows), bytes(v for row in rows for v in row))


def test_story_2_1_sharp_text_measures_as_readable() -> None:
    rows = [
        [25 if (y % 5 < 2 and x % 9 < 7) else 235 for x in range(60)] for y in range(40)
    ]
    measures = measure(_grey(rows))
    assert measures.mean_luminance > THRESHOLDS.min_mean_luminance
    assert measures.laplacian_variance > THRESHOLDS.min_variance
    assert photo_problem(measures, THRESHOLDS) is None
