import { describe, expect, it } from "vitest";

import { imageSize } from "./size";

function png(width: number, height: number): Uint8Array {
  const b = new Uint8Array(33);
  b.set([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13]);
  b.set([0x49, 0x48, 0x44, 0x52], 12);
  new DataView(b.buffer).setUint32(16, width);
  new DataView(b.buffer).setUint32(20, height);
  return b;
}

function jpeg(width: number, height: number, frame = 0xc0): Uint8Array {
  const app1 = [0xff, 0xe1, 0x00, 0x08, 0x45, 0x78, 0x69, 0x66, 0x00, 0x00];
  const dht = [0xff, 0xc4, 0x00, 0x04, 0x00, 0x00];
  const sof = [
    0xff,
    frame,
    0x00,
    0x11,
    0x08,
    height >> 8,
    height & 0xff,
    width >> 8,
    width & 0xff,
    0x03,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
  ];
  return Uint8Array.from([0xff, 0xd8, 0xff, ...app1, ...dht, ...sof]);
}

describe("1.9 photo size from its header", () => {
  it("reads a PNG's IHDR", () => {
    expect(imageSize(png(4032, 3024))).toEqual({ width: 4032, height: 3024 });
  });

  it.each([0xc0, 0xc2])(
    "reads a JPEG's frame header (SOF %i), past other segments",
    (frame) => {
      expect(imageSize(jpeg(4032, 3024, frame))).toEqual({
        width: 4032,
        height: 3024,
      });
    },
  );

  it("skips fill bytes between segments", () => {
    const b = jpeg(640, 480);
    const filled = Uint8Array.from([...b.slice(0, 2), 0xff, ...b.slice(2)]);
    expect(imageSize(filled)).toEqual({ width: 640, height: 480 });
  });

  it("gives null for anything it can't read", () => {
    expect(imageSize(new Uint8Array())).toBeNull();
    expect(imageSize(Uint8Array.from([0x47, 0x49, 0x46, 0x38]))).toBeNull();
    expect(imageSize(png(0, 10))).toBeNull();
    expect(imageSize(png(10, 10).slice(0, 20))).toBeNull();
    // A JPEG cut off before its frame header, or with a broken segment.
    expect(imageSize(jpeg(10, 10).slice(0, 12))).toBeNull();
    expect(
      imageSize(
        Uint8Array.from([0xff, 0xd8, 0x00, 0xe1, 0, 8, 0, 0, 0, 0, 0, 0]),
      ),
    ).toBeNull();
    expect(
      imageSize(
        Uint8Array.from([0xff, 0xd8, 0xff, 0xe1, 0, 1, 0, 0, 0, 0, 0, 0]),
      ),
    ).toBeNull();
  });
});
