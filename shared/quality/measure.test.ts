import { describe, expect, it } from "vitest";

import { blurred, darkened, page } from "./fixtures";
import {
  edgeDensity,
  laplacianVariance,
  meanLuminance,
  toGrey,
} from "./measure";

function solid(width: number, height: number, rgb: [number, number, number]) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) {
    data.set([...rgb, 255], i);
  }
  return { width, height, data };
}

describe("1.9 photo measures", () => {
  it("weights luminance as Pillow's L mode and ignores alpha", () => {
    const grey = toGrey({ width: 1, height: 1, data: [100, 200, 50, 0] });
    expect(grey.values[0]).toBeCloseTo(
      0.299 * 100 + 0.587 * 200 + 0.114 * 50,
      3,
    );
  });

  it("refuses pixel data shorter than the image", () => {
    expect(() => toGrey({ width: 2, height: 2, data: [0, 0, 0, 255] })).toThrow(
      RangeError,
    );
  });

  it("measures mean luminance, 0-255", () => {
    expect(meanLuminance(toGrey(solid(4, 4, [255, 255, 255])))).toBeCloseTo(
      255,
      3,
    );
    expect(meanLuminance(toGrey(solid(4, 4, [0, 0, 0])))).toBe(0);
    expect(meanLuminance(toGrey({ width: 0, height: 0, data: [] }))).toBe(0);
    expect(meanLuminance(toGrey(darkened(page())))).toBeLessThan(40);
  });

  it("gives a flat image no Laplacian variance, and a sharp page far more than a blurred one", () => {
    expect(laplacianVariance(toGrey(solid(8, 8, [120, 120, 120])))).toBe(0);
    expect(laplacianVariance(toGrey(solid(2, 8, [0, 0, 0])))).toBe(0);
    const sharp = laplacianVariance(toGrey(page()));
    const soft = laplacianVariance(toGrey(blurred(page())));
    expect(sharp).toBeGreaterThan(1000);
    expect(soft).toBeLessThan(sharp / 20);
  });

  it("finds no edges in the strips of a framed page, and text in its interior", () => {
    const density = edgeDensity(toGrey(page()), 0.03, 40);
    expect(density.top).toBe(0);
    expect(density.right).toBe(0);
    expect(density.bottom).toBe(0);
    expect(density.left).toBe(0);
    expect(density.interior).toBeGreaterThan(0.1);
  });

  it.each(["top", "right", "bottom", "left"] as const)(
    "finds edges in the %s strip when the text runs past it",
    (side) => {
      const density = edgeDensity(toGrey(page({ bleed: side })), 0.03, 40);
      expect(density[side]).toBeGreaterThan(0.1);
      for (const other of ["top", "right", "bottom", "left"] as const) {
        if (other !== side) expect(density[other]).toBe(0);
      }
    },
  );

  it("measures a tiny image without failing", () => {
    expect(edgeDensity(toGrey(solid(1, 1, [0, 0, 0])), 0.03, 40)).toEqual({
      top: 0,
      right: 0,
      bottom: 0,
      left: 0,
      interior: 0,
    });
    const two = edgeDensity(toGrey(solid(2, 2, [9, 9, 9])), 0.03, 40);
    expect(two.interior).toBe(0);
  });
});
