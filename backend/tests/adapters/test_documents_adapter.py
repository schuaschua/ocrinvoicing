"""Story 2.1: reading an upload original with Pillow, ImageHash and pypdf (AD-6, AD-9,
AD-19), measured the way the page measures it."""

from _documents import (
    jpeg,
    page,
)
from invoicing.adapters.documents import (
    ImageFacts,
    load_quality_thresholds,
    read_document,
)
from invoicing.domain.quality import (
    image_reason,
)
from invoicing.domain.upload import UploadContentType

THRESHOLDS = load_quality_thresholds()


def _image(data: bytes) -> ImageFacts:
    facts = read_document(data, UploadContentType.JPEG, THRESHOLDS)
    assert isinstance(facts, ImageFacts)
    return facts


def test_story_2_1_a_sharp_bright_photo_is_readable_with_a_phash() -> None:
    facts = _image(jpeg(page()))
    assert facts.measures is not None
    assert image_reason(facts.measures, THRESHOLDS) is None
    assert facts.phash is not None and 0 <= facts.phash < 1 << 64
    # No EXIF: no photo time (AD-19).
    assert facts.photo_taken_at is None
