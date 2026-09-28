import { describe, expect, it } from "vitest";

import thresholdsFile from "../quality-thresholds.json";
import {
  THRESHOLDS,
  analysisSize,
  evaluate,
  measurePhoto,
  photoProblem,
} from "./check";
import { blurred, darkened, page, turnedClockwise } from "./fixtures";

describe("1.9 device quality check", () => {
  it("reads every threshold from shared/quality-thresholds.json", () => {
    expect(THRESHOLDS).toEqual({
      maxLongSidePx: thresholdsFile.analysis.max_long_side_px,
      targetCheckMs: 2000,
      maxCheckMs: 5000,
      minVariance: thresholdsFile.blur.min_variance,
      minMeanLuminance: thresholdsFile.darkness.min_mean_luminance,
      edge: {
        stripFraction: thresholdsFile.edge.strip_fraction,
        gradientThreshold: thresholdsFile.edge.gradient_threshold,
        maxBorderEdgeDensity: thresholdsFile.edge.max_border_edge_density,
        minInteriorEdgeDensity: thresholdsFile.edge.min_interior_edge_density,
      },
      maxFailuresBeforeSendAnyway: 2,
    });
    // The server quality stage reads the same keys (AD-6); new ones are marked.
    expect(thresholdsFile.blur.measure).toBe("variance_of_laplacian");
    expect(thresholdsFile.darkness.measure).toBe("mean_luminance_0_255");
    expect(thresholdsFile.edge.note).toContain("[ASSUMPTION]");
    expect(thresholdsFile.edge.note).toContain("busy background");
    expect(thresholdsFile.analysis.note).toContain("[ASSUMPTION]");
  });

  it("passes a sharp, bright, framed page", () => {
    expect(photoProblem(page())).toBeNull();
  });

  it("names a dark photo", () => {
    expect(photoProblem(darkened(page()))).toEqual({ kind: "dark" });
  });

  it("names darkness first: a dark, blurry photo is dark", () => {
    const both = darkened(blurred(page()));
    const measures = measurePhoto(both);
    expect(measures.laplacianVariance).toBeLessThan(THRESHOLDS.minVariance);
    expect(photoProblem(both)).toEqual({ kind: "dark" });
  });

  it("names a blurry photo", () => {
    expect(photoProblem(blurred(page()))).toEqual({ kind: "blurry" });
  });

  it("names blur before a cut-off edge", () => {
    expect(photoProblem(blurred(page({ bleed: "bottom" }), 4))).toEqual({
      kind: "blurry",
    });
  });

  it.each(["top", "right", "bottom", "left"] as const)(
    "names the %s edge when the page runs past it",
    (side) => {
      expect(photoProblem(page({ bleed: side }))).toEqual({
        kind: "cut-off",
        side,
      });
    },
  );

  it("names the side as the photo is shown: a turned photo's bottom is its left", () => {
    // The browser applies EXIF orientation before the check sees the pixels.
    expect(photoProblem(turnedClockwise(page({ bleed: "bottom" })))).toEqual({
      kind: "cut-off",
      side: "left",
    });
  });

  it("names the busiest side when several are cut off", () => {
    const measures = {
      meanLuminance: 200,
      laplacianVariance: 5000,
      edges: { top: 0.1, right: 0.3, bottom: 0.2, left: 0, interior: 0.2 },
    };
    expect(evaluate(measures)).toEqual({ kind: "cut-off", side: "right" });
  });

  it("calls no side cut off when the interior is empty (a blank sheet on a busy table)", () => {
    const measures = {
      meanLuminance: 200,
      laplacianVariance: 5000,
      edges: { top: 0.5, right: 0.5, bottom: 0.5, left: 0.5, interior: 0 },
    };
    expect(evaluate(measures)).toBeNull();
  });

  it("measures a 12 MP photo at 1024 px on the long side, never enlarging", () => {
    expect(analysisSize(4032, 3024)).toEqual({ width: 1024, height: 768 });
    expect(analysisSize(3024, 4032)).toEqual({ width: 768, height: 1024 });
    expect(analysisSize(800, 600)).toEqual({ width: 800, height: 600 });
    expect(analysisSize(0, 0)).toEqual({ width: 1, height: 1 });
  });

  it("checks a full-size analysis copy within the 2 s target", () => {
    const big = page({ width: 1024, height: 768 });
    const started = performance.now();
    expect(photoProblem(big)).toBeNull();
    expect(performance.now() - started).toBeLessThan(THRESHOLDS.targetCheckMs);
  });
});
