"""Generated upload originals for the quality stage (Story 2.1). Synthetic only
(coding-style.md rule 24): an invoice-like page of dark "words" on light paper, drawn
with Pillow, and blank PDFs from pypdf."""

import io

from PIL import ExifTags, Image, ImageFilter

PAPER = 235
INK = 25


def page(width: int = 1600, height: int = 1200) -> Image.Image:
    """A sharp, bright page: rows of 14 px words, 4 px tall, inside a 15% margin."""
    image = Image.new("RGB", (width, height), (PAPER, PAPER, PAPER))
    pixels = image.load()
    assert pixels is not None
    for y in range(int(height * 0.15), int(height * 0.85)):
        if y % 10 >= 4:
            continue
        for x in range(int(width * 0.15), int(width * 0.85)):
            if x % 18 < 14:
                pixels[x, y] = (INK, INK, INK)
    return image


def blurred(image: Image.Image, radius: float = 6) -> Image.Image:
    """An out-of-focus photo of `image`."""
    return image.filter(ImageFilter.GaussianBlur(radius))


def darkened(image: Image.Image, factor: float = 0.15) -> Image.Image:
    """`image` in poor light."""
    return image.point(lambda value: int(value * factor))


def exif(
    *,
    orientation: int | None = None,
    taken: str | None = None,
    offset: str | None = None,
) -> Image.Exif:
    """EXIF with an orientation tag and `DateTimeOriginal` / `OffsetTimeOriginal`."""
    data = Image.Exif()
    if orientation is not None:
        data[ExifTags.Base.Orientation] = orientation
    sub = data.get_ifd(ExifTags.IFD.Exif)
    if taken is not None:
        sub[ExifTags.Base.DateTimeOriginal] = taken
    if offset is not None:
        sub[ExifTags.Base.OffsetTimeOriginal] = offset
    return data


def jpeg(image: Image.Image, exif_data: Image.Exif | None = None) -> bytes:
    """`image` as JPEG bytes, with `exif_data` when given."""
    out = io.BytesIO()
    extra = {"exif": exif_data} if exif_data is not None else {}
    image.save(out, "JPEG", quality=92, **extra)
    return out.getvalue()


def png(image: Image.Image) -> bytes:
    """`image` as PNG bytes."""
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
