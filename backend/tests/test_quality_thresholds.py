"""Story 1.9: the contract of `shared/quality-thresholds.json` that the server
`quality` stage (Story 2.1) reads with the same meaning as the page (AD-6)."""

import json
from pathlib import Path

import pytest

THRESHOLDS = Path(__file__).resolve().parents[2] / "shared" / "quality-thresholds.json"


@pytest.mark.parametrize(
    "path",
    [
        ("analysis", "max_long_side_px"),
        ("blur", "min_variance"),
        ("darkness", "min_mean_luminance"),
    ],
)
def test_story_1_9_the_server_keys_exist_and_are_numbers(
    path: tuple[str, str],
) -> None:
    value: object = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    for key in path:
        assert isinstance(value, dict) and key in value, ".".join(path)
        value = value[key]
    assert isinstance(value, int | float) and not isinstance(value, bool)
    assert value > 0
