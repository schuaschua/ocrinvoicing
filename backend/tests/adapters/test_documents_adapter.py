"""Story 2.1: reading an upload original with Pillow, ImageHash and pypdf (AD-6, AD-9,
AD-19), measured the way the page measures it."""

import io
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pypdf import PdfWriter

from _documents import (
    blurred,
    darkened,
    exif,
    hamming,
    jpeg,
    page,
    pdf,
    png,
)
from invoicing.adapters import documents
from invoicing.adapters.documents import (
    ImageFacts,
    PdfFacts,
    load_quality_thresholds,
    measure_grey,
    read_document,
    read_image,
    to_rgb,
)
from invoicing.domain.quality import (
    GreyImage,
    ImageMeasures,
    QualityThresholds,
    image_reason,
    measure,
)
from invoicing.domain.reasons import ReasonCode
from invoicing.domain.upload import UploadContentType

THRESHOLDS = load_quality_thresholds()


def _image(data: bytes) -> ImageFacts:
    facts = read_document(data, UploadContentType.JPEG, THRESHOLDS)
    assert isinstance(facts, ImageFacts)
    return facts


def test_story_2_1_the_thresholds_file_is_the_one_the_page_reads() -> None:
    shared = Path(__file__).resolve().parents[3] / "shared" / "quality-thresholds.json"
    assert THRESHOLDS == QualityThresholds.from_json(json.loads(shared.read_text()))


def test_story_2_1_the_packaged_thresholds_file_is_found_at_the_package_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The deploy package: <root>/invoicing/adapters/documents.py, <root>/shared/.
    adapters = tmp_path / "invoicing" / "adapters"
    adapters.mkdir(parents=True)
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "quality-thresholds.json").write_text(
        json.dumps(
            {
                "analysis": {"max_long_side_px": 512},
                "blur": {"min_variance": 7},
                "darkness": {"min_mean_luminance": 9},
            }
        )
    )
    monkeypatch.setattr(documents, "__file__", str(adapters / "documents.py"))
    assert load_quality_thresholds() == QualityThresholds(512, 7.0, 9.0)


def test_story_2_1_a_missing_or_malformed_thresholds_file_stops_the_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(documents, "__file__", str(tmp_path / "a" / "b" / "c" / "d.py"))
    with pytest.raises(RuntimeError, match="quality-thresholds.json not found"):
        load_quality_thresholds()
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    with pytest.raises(TypeError):
        load_quality_thresholds(bad)


def test_story_2_1_a_sharp_bright_photo_is_readable_with_a_phash() -> None:
    facts = _image(jpeg(page()))
    assert facts.measures is not None
    assert image_reason(facts.measures, THRESHOLDS) is None
    assert facts.phash is not None and 0 <= facts.phash < 1 << 64
    # No EXIF: no photo time (AD-19).
    assert facts.photo_taken_at is None


@pytest.mark.parametrize("spoil", [blurred, darkened])
def test_story_2_1_blurry_or_dark_photos_are_unreadable(spoil: object) -> None:
    facts = _image(jpeg(spoil(page())))  # type: ignore[operator]  # a helper
    assert facts.measures is not None
    assert image_reason(facts.measures, THRESHOLDS) is ReasonCode.UNREADABLE
    # Still hashed: the quality stage finished reading it.
    assert facts.phash is not None


def test_story_2_1_png_is_read_like_jpeg() -> None:
    facts = read_document(png(page(800, 600)), UploadContentType.PNG, THRESHOLDS)
    assert isinstance(facts, ImageFacts) and facts.measures is not None
    assert image_reason(facts.measures, THRESHOLDS) is None


@pytest.mark.parametrize(
    "data",
    [b"", b"\xff\xd8\xff\xe0 not really a jpeg", b"\x89PNG\r\n\x1a\n" + b"\0" * 40],
)
def test_story_2_1_bytes_that_do_not_decode_have_no_measures(data: bytes) -> None:
    facts = _image(data)
    assert facts == ImageFacts(measures=None, phash=None, photo_taken_at=None)
    assert image_reason(facts.measures, THRESHOLDS) is ReasonCode.UNREADABLE


def test_story_2_1_a_truncated_jpeg_is_unreadable() -> None:
    whole = jpeg(page())
    facts = _image(whole[: len(whole) // 3])
    assert image_reason(facts.measures, THRESHOLDS) is ReasonCode.UNREADABLE


def test_story_2_1_exif_orientation_is_applied_before_measuring_and_hashing() -> None:
    upright = _image(jpeg(page()))
    # Stored on its side with orientation 6 ("turn 90 degrees clockwise to view").
    turned = page().transpose(Image.Transpose.ROTATE_90)
    oriented = _image(jpeg(turned, exif(orientation=6)))
    unoriented = _image(jpeg(turned))
    assert upright.phash is not None and oriented.phash is not None
    assert unoriented.phash is not None
    # The oriented copy hashes like the upright page; ignoring the tag would not.
    assert hamming(oriented.phash, upright.phash) <= 8
    assert hamming(unoriented.phash, upright.phash) > 8
    assert upright.measures is not None and oriented.measures is not None
    assert oriented.measures.mean_luminance == pytest.approx(
        upright.measures.mean_luminance, abs=1
    )


def test_story_2_1_the_measured_copy_has_the_pages_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sizes: list[tuple[int, int]] = []
    real = documents.measure_grey

    def spy(grey: np.ndarray) -> documents.ImageMeasures:
        sizes.append((grey.shape[1], grey.shape[0]))
        return real(grey)

    monkeypatch.setattr(documents, "measure_grey", spy)
    read_image(jpeg(page(4000, 3000)), 1024)
    read_image(jpeg(page(300, 200)), 1024)
    # Long side 1024 after orientation; never enlarged.
    turned = page(3000, 1500).transpose(Image.Transpose.ROTATE_90)
    read_image(jpeg(turned, exif(orientation=6)), 1024)
    assert sizes == [(1024, 768), (300, 200), (1024, 512)]


@pytest.mark.parametrize(
    ("taken", "offset", "expected"),
    [
        ("2026:09:20 14:30:05", None, datetime(2026, 9, 20, 6, 30, 5, tzinfo=UTC)),
        ("2026:09:20 14:30:05", "+02:00", datetime(2026, 9, 20, 12, 30, 5, tzinfo=UTC)),
        ("not a date", None, None),
        (None, "+08:00", None),
    ],
)
def test_story_2_1_photo_taken_at_comes_from_exif(
    taken: str | None, offset: str | None, expected: datetime | None
) -> None:
    facts = _image(jpeg(page(400, 300), exif(taken=taken, offset=offset)))
    assert facts.photo_taken_at == expected


@pytest.mark.parametrize(("pages", "count"), [(1, 1), (2, 2), (3, 3)])
def test_story_2_1_pdf_pages_are_counted(pages: int, count: int) -> None:
    assert read_document(pdf(pages), UploadContentType.PDF, THRESHOLDS) == PdfFacts(
        count
    )


@pytest.mark.parametrize(
    "data", [b"%PDF-1.4\nnot a pdf at all", b"", jpeg(page(50, 50))]
)
def test_story_2_1_an_unreadable_pdf_has_no_page_count(data: bytes) -> None:
    assert read_document(data, UploadContentType.PDF, THRESHOLDS) == PdfFacts(None)


# --- Review fixes: vectorised measures, bounded and faithful decoding ------------------


def _reference(grey: np.ndarray) -> ImageMeasures:
    """The domain's pure-Python definitions (domain/quality.py)."""
    height, width = grey.shape
    return measure(GreyImage(width, height, grey.astype(np.uint8).tobytes()))


@pytest.mark.parametrize(
    "image",
    [
        page(640, 480),
        blurred(page(640, 480)),
        darkened(page(640, 480)),
        page(3, 3),
        page(2, 7),
        page(1, 1),
    ],
    ids=["sharp", "blurry", "dark", "3x3", "2x7", "1x1"],
)
def test_story_2_1_the_vectorised_measures_equal_the_reference(
    image: Image.Image,
) -> None:
    grey = np.asarray(image.convert("L"))
    assert measure_grey(grey) == _reference(grey)


def test_story_2_1_the_vectorised_measures_equal_the_reference_on_noise() -> None:
    grey = np.random.default_rng(21).integers(0, 256, (768, 1024), dtype=np.uint8)
    assert measure_grey(grey) == _reference(grey)


def test_story_2_1_measuring_a_1024x768_copy_stays_within_200_ms() -> None:
    grey = np.random.default_rng(7).integers(0, 256, (768, 1024), dtype=np.uint8)
    # Best of 3, so a busy machine does not fail the budget by one slow run.
    best = min(_timed(lambda: measure_grey(grey)) for _ in range(3))
    assert best <= 0.2


def _timed(work: Callable[[], object]) -> float:
    started = time.perf_counter()
    work()
    return time.perf_counter() - started


@pytest.mark.parametrize("factor", [1.5, 3])
def test_story_2_1_an_image_over_the_pixel_limit_is_refused_before_decoding(
    monkeypatch: pytest.MonkeyPatch, factor: float
) -> None:
    data = jpeg(page(400, 300))
    # Between 1x and 2x Pillow only warns; over 2x it raises. Both are refused.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", int(400 * 300 / factor))
    decoded: list[bool] = []
    monkeypatch.setattr(documents, "to_rgb", lambda image: decoded.append(True))
    facts = read_image(data, 1024)
    assert facts == ImageFacts(measures=None, phash=None, photo_taken_at=None)
    assert decoded == []


def test_story_2_1_running_out_of_memory_is_raised_not_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_memory(image: Image.Image) -> Image.Image:
        raise MemoryError

    monkeypatch.setattr(documents, "to_rgb", no_memory)
    with pytest.raises(MemoryError):
        read_image(jpeg(page(400, 300)), 1024)


def test_story_2_1_running_out_of_memory_on_a_pdf_is_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_memory(*args: object, **kwargs: object) -> None:
        raise MemoryError

    monkeypatch.setattr(documents, "PdfReader", no_memory)
    with pytest.raises(MemoryError):
        documents.pdf_page_count(pdf(1))


def _transparent_page() -> Image.Image:
    # Ink where the page has ink; fully transparent (black underneath) elsewhere.
    ink = page(800, 600).convert("L").point(lambda v: 255 if v < 128 else 0)
    image = Image.new("RGBA", ink.size, (0, 0, 0, 0))
    image.putalpha(ink)
    return image


def _palette_page() -> Image.Image:
    # Index 0 is black but transparent (the paper), index 1 is the ink.
    ink = np.asarray(page(800, 600).convert("L")) < 128
    image = Image.fromarray(ink.astype(np.uint8), "L").convert("P")
    image.putpalette([0, 0, 0, 25, 25, 25])
    image.info["transparency"] = 0
    return image


@pytest.mark.parametrize(
    "image",
    [_transparent_page(), _transparent_page().convert("LA"), _palette_page()],
    ids=["rgba", "la", "p-transparency"],
)
def test_story_2_1_transparent_pixels_read_as_white_paper(image: Image.Image) -> None:
    # Transparent pixels are black underneath: read as they are, the page is "dark".
    assert np.asarray(image.convert("RGB").convert("L")).mean() < 60
    facts = read_document(png(image), UploadContentType.PNG, THRESHOLDS)
    assert isinstance(facts, ImageFacts) and facts.measures is not None
    assert facts.measures.mean_luminance > THRESHOLDS.min_mean_luminance
    assert image_reason(facts.measures, THRESHOLDS) is None


def test_story_2_1_a_16_bit_png_is_scaled_to_8_bits() -> None:
    eight = np.asarray(page(800, 600).convert("L"), dtype=np.uint16)
    sixteen = Image.fromarray(eight * 257)
    assert sixteen.mode == "I;16"
    facts = read_document(png(sixteen), UploadContentType.PNG, THRESHOLDS)
    reference = read_document(
        png(page(800, 600).convert("L")), UploadContentType.PNG, THRESHOLDS
    )
    assert isinstance(facts, ImageFacts) and isinstance(reference, ImageFacts)
    assert facts.measures is not None and reference.measures is not None
    assert facts.measures.mean_luminance == pytest.approx(
        reference.measures.mean_luminance, abs=0.5
    )
    assert image_reason(facts.measures, THRESHOLDS) is None


def _wide(mode: str, values: list[int]) -> Image.Image:
    array = np.array([values], dtype=np.uint16)
    if mode == "I;16":
        return Image.fromarray(array)
    if mode == "I;16B":
        return Image.frombytes("I;16B", (len(values), 1), array.astype(">u2").tobytes())
    return Image.fromarray(array.astype(np.int32))


@pytest.mark.parametrize("mode", ["I;16", "I;16B", "I"])
def test_story_2_1_wide_grey_modes_become_8_bit(mode: str) -> None:
    image = _wide(mode, [0, 257 * 100, 65535])
    assert image.mode == mode
    assert np.asarray(to_rgb(image).convert("L")).tolist() == [[0, 100, 255]]


def test_story_2_1_32_bit_grey_already_in_8_bit_range_is_kept() -> None:
    image = Image.fromarray(np.array([[0, 100, 255]], dtype=np.int32))
    assert np.asarray(to_rgb(image).convert("L")).tolist() == [[0, 100, 255]]


def test_story_2_1_an_encrypted_pdf_is_unreadable() -> None:
    writer = PdfWriter()
    writer.add_blank_page(595, 842)
    writer.encrypt(user_password="u", owner_password="o")  # noqa: S106  # test fixture
    out = io.BytesIO()
    writer.write(out)
    assert read_document(out.getvalue(), UploadContentType.PDF, THRESHOLDS) == PdfFacts(
        None
    )


def test_story_2_1_a_pdf_whose_page_tree_loops_is_unreadable() -> None:
    looping = (
        b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n"
        b"2 0 obj << /Type /Pages /Kids [2 0 R] /Count 1 >> endobj\n"
        b"trailer << /Root 1 0 R >>\n%%EOF\n"
    )
    assert read_document(looping, UploadContentType.PDF, THRESHOLDS) == PdfFacts(None)
