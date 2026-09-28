// The photo measures of the device quality check (Story 1.9, CAP-3, AD-6). Pure
// functions over RGBA pixel arrays, with no browser or framework code, so they run in
// tests without a canvas. The server `quality` stage (Story 2.1) computes the blur and
// darkness measures the same way with Pillow, on the same downscaled copy.

/** RGBA pixels, 4 bytes each, row by row (the shape of a canvas `ImageData`). */
export interface Pixels {
  width: number;
  height: number;
  data: ArrayLike<number>;
}

/** One luminance value (0–255) per pixel, row by row. */
export interface Grey {
  width: number;
  height: number;
  values: Float32Array;
}

/** A side of the photo, as the user sees it (EXIF orientation already applied). */
export type Side = "top" | "right" | "bottom" | "left";

export const SIDES: readonly Side[] = ["top", "right", "bottom", "left"];

/** Luminance per pixel: 0.299 R + 0.587 G + 0.114 B, as Pillow's "L" mode. Alpha is ignored. */
export function toGrey(pixels: Pixels): Grey {
  const { width, height, data } = pixels;
  const count = width * height;
  if (data.length < count * 4) {
    throw new RangeError("pixel data is shorter than width × height × 4");
  }
  const values = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    const o = i * 4;
    values[i] = 0.299 * data[o]! + 0.587 * data[o + 1]! + 0.114 * data[o + 2]!;
  }
  return { width, height, values };
}

/** Mean luminance, 0–255 (the darkness measure). 0 for an empty image. */
export function meanLuminance(grey: Grey): number {
  const { values } = grey;
  if (values.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < values.length; i++) sum += values[i]!;
  return sum / values.length;
}

/**
 * Variance of the Laplacian (the blur measure): the 4-neighbour kernel
 * [0 1 0; 1 -4 1; 0 1 0] over every pixel that has all four neighbours. Low means
 * few sharp edges, so a blurry photo. 0 for an image under 3 × 3.
 */
export function laplacianVariance(grey: Grey): number {
  const { width: w, height: h, values: g } = grey;
  if (w < 3 || h < 3) return 0;
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  for (let y = 1; y < h - 1; y++) {
    const row = y * w;
    for (let x = 1; x < w - 1; x++) {
      const i = row + x;
      const lap = g[i - w]! + g[i + w]! + g[i - 1]! + g[i + 1]! - 4 * g[i]!;
      sum += lap;
      sumSq += lap * lap;
      n++;
    }
  }
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

/** Edge density (0–1) in each outer strip and in the interior between them. */
export interface EdgeDensity {
  top: number;
  right: number;
  bottom: number;
  left: number;
  interior: number;
}

/**
 * The share of "edge" pixels in each of the 4 outer strips and in the interior (the
 * cut-off measure). A pixel is an edge when |∂x| + |∂y| (forward differences) exceeds
 * `gradientThreshold`. Each strip is `stripFraction` of its side deep, at least 1 px.
 */
export function edgeDensity(
  grey: Grey,
  stripFraction: number,
  gradientThreshold: number,
): EdgeDensity {
  const { width: w, height: h, values: g } = grey;
  const empty = { top: 0, right: 0, bottom: 0, left: 0, interior: 0 };
  if (w < 2 || h < 2) return empty;
  const sy = Math.max(1, Math.round(h * stripFraction));
  const sx = Math.max(1, Math.round(w * stripFraction));
  const edges = { top: 0, right: 0, bottom: 0, left: 0, interior: 0 };
  const totals = { top: 0, right: 0, bottom: 0, left: 0, interior: 0 };
  // The last row and column have no forward neighbour: measured against the one before.
  for (let y = 0; y < h; y++) {
    const ny = y < h - 1 ? y + 1 : y - 1;
    for (let x = 0; x < w; x++) {
      const nx = x < w - 1 ? x + 1 : x - 1;
      const v = g[y * w + x]!;
      const edge =
        Math.abs(g[y * w + nx]! - v) + Math.abs(g[ny * w + x]! - v) >
        gradientThreshold;
      // A corner pixel counts for both of its strips.
      let inStrip = false;
      if (y < sy) {
        totals.top++;
        if (edge) edges.top++;
        inStrip = true;
      }
      if (y >= h - sy) {
        totals.bottom++;
        if (edge) edges.bottom++;
        inStrip = true;
      }
      if (x < sx) {
        totals.left++;
        if (edge) edges.left++;
        inStrip = true;
      }
      if (x >= w - sx) {
        totals.right++;
        if (edge) edges.right++;
        inStrip = true;
      }
      if (!inStrip) {
        totals.interior++;
        if (edge) edges.interior++;
      }
    }
  }
  const share = (key: keyof EdgeDensity) =>
    totals[key] === 0 ? 0 : edges[key] / totals[key];
  return {
    top: share("top"),
    right: share("right"),
    bottom: share("bottom"),
    left: share("left"),
    interior: share("interior"),
  };
}
