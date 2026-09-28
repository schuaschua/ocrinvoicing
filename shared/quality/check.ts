// The device quality check (Story 1.9, CAP-3): the measures of measure.ts against the
// thresholds of shared/quality-thresholds.json, the one file the server `quality`
// stage reads too (AD-6). Checked in this order: dark, blurry, cut off; a dark photo
// also looks blurry, so darkness is named first.

import thresholdsFile from "../quality-thresholds.json";
import {
  type Pixels,
  type Side,
  SIDES,
  edgeDensity,
  laplacianVariance,
  meanLuminance,
  toGrey,
} from "./measure";

export interface QualityThresholds {
  maxLongSidePx: number;
  /** The check aims to finish within this, on a mid-range phone. */
  targetCheckMs: number;
  /** A check still running after this is given up, and the file passes. */
  maxCheckMs: number;
  minVariance: number;
  minMeanLuminance: number;
  edge: {
    stripFraction: number;
    gradientThreshold: number;
    maxBorderEdgeDensity: number;
    minInteriorEdgeDensity: number;
  };
  maxFailuresBeforeSendAnyway: number;
}

/** The thresholds in shared/quality-thresholds.json. */
export const THRESHOLDS: QualityThresholds = {
  maxLongSidePx: thresholdsFile.analysis.max_long_side_px,
  targetCheckMs: thresholdsFile.analysis.target_check_ms,
  maxCheckMs: thresholdsFile.analysis.max_check_ms,
  minVariance: thresholdsFile.blur.min_variance,
  minMeanLuminance: thresholdsFile.darkness.min_mean_luminance,
  edge: {
    stripFraction: thresholdsFile.edge.strip_fraction,
    gradientThreshold: thresholdsFile.edge.gradient_threshold,
    maxBorderEdgeDensity: thresholdsFile.edge.max_border_edge_density,
    minInteriorEdgeDensity: thresholdsFile.edge.min_interior_edge_density,
  },
  maxFailuresBeforeSendAnyway:
    thresholdsFile.max_device_check_failures_before_send_anyway,
};

/** What is wrong with a photo, or nothing. */
export type PhotoProblem =
  { kind: "dark" } | { kind: "blurry" } | { kind: "cut-off"; side: Side };

/** The measures behind a result, for tests and calibration (never shown to suppliers). */
export interface PhotoMeasures {
  meanLuminance: number;
  laplacianVariance: number;
  edges: ReturnType<typeof edgeDensity>;
}

/** The first problem with `pixels` (dark, then blurry, then cut off), or null when it passes. */
export function photoProblem(
  pixels: Pixels,
  thresholds: QualityThresholds = THRESHOLDS,
): PhotoProblem | null {
  return evaluate(measurePhoto(pixels, thresholds), thresholds);
}

export function measurePhoto(
  pixels: Pixels,
  thresholds: QualityThresholds = THRESHOLDS,
): PhotoMeasures {
  const grey = toGrey(pixels);
  return {
    meanLuminance: meanLuminance(grey),
    laplacianVariance: laplacianVariance(grey),
    edges: edgeDensity(
      grey,
      thresholds.edge.stripFraction,
      thresholds.edge.gradientThreshold,
    ),
  };
}

export function evaluate(
  measures: PhotoMeasures,
  thresholds: QualityThresholds = THRESHOLDS,
): PhotoProblem | null {
  if (measures.meanLuminance < thresholds.minMeanLuminance) {
    return { kind: "dark" };
  }
  if (measures.laplacianVariance < thresholds.minVariance) {
    return { kind: "blurry" };
  }
  const { edges } = measures;
  // The document runs past the frame: a busy strip while the page itself has content.
  if (edges.interior >= thresholds.edge.minInteriorEdgeDensity) {
    let worst: Side | null = null;
    for (const side of SIDES) {
      if (
        edges[side] > thresholds.edge.maxBorderEdgeDensity &&
        (worst === null || edges[side] > edges[worst])
      ) {
        worst = side;
      }
    }
    if (worst !== null) return { kind: "cut-off", side: worst };
  }
  return null;
}

/** The size to measure a `width` × `height` photo at: long side at most `maxLongSide`, never enlarged. */
export function analysisSize(
  width: number,
  height: number,
  maxLongSide: number = THRESHOLDS.maxLongSidePx,
): { width: number; height: number } {
  const scale = Math.min(1, maxLongSide / Math.max(width, height, 1));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}
