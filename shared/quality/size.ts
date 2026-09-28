// A photo's stored size from its header (Story 1.9), so the page can ask the browser
// to decode it already downscaled instead of at full size. JPEG and PNG only; the
// size is as stored, before any EXIF orientation.

/** Enough of the file for any JPEG's frame header after its EXIF and other segments. */
export const HEADER_BYTES = 256 * 1024;

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
// JPEG start-of-frame markers: C0–CF except DHT (C4), JPG (C8) and DAC (CC).
const NOT_FRAMES = new Set([0xc4, 0xc8, 0xcc]);

function u16(b: Uint8Array, at: number): number {
  return (b[at]! << 8) | b[at + 1]!;
}

function u32(b: Uint8Array, at: number): number {
  return (
    ((b[at]! << 24) >>> 0) + (b[at + 1]! << 16) + (b[at + 2]! << 8) + b[at + 3]!
  );
}

/** The stored width and height of a JPEG or PNG, or null when the header can't be read. */
export function imageSize(
  bytes: Uint8Array,
): { width: number; height: number } | null {
  const size = (width: number, height: number) =>
    width > 0 && height > 0 ? { width, height } : null;
  if (PNG_SIGNATURE.every((b, i) => bytes[i] === b)) {
    // IHDR is always the first chunk: width and height at bytes 16 and 20.
    return bytes.length >= 24 ? size(u32(bytes, 16), u32(bytes, 20)) : null;
  }
  if (bytes[0] !== 0xff || bytes[1] !== 0xd8) return null;
  let at = 2;
  while (at + 9 < bytes.length) {
    if (bytes[at] !== 0xff) return null;
    const marker = bytes[at + 1]!;
    // Fill bytes, and markers with no length (TEM, RSTn).
    if (marker === 0xff) {
      at += 1;
      continue;
    }
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      at += 2;
      continue;
    }
    if (marker >= 0xc0 && marker <= 0xcf && !NOT_FRAMES.has(marker)) {
      return size(u16(bytes, at + 7), u16(bytes, at + 5));
    }
    const length = u16(bytes, at + 2);
    if (length < 2) return null;
    at += 2 + length;
  }
  return null;
}
