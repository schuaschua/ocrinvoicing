import { describe, expect, it } from "vitest";

import thresholdsFile from "../quality-thresholds.json";
import { THRESHOLDS, analysisSize, photoProblem } from "./check";
import { blurred, darkened, page, turnedClockwise } from "./fixtures";

describe("1.9 device quality check", () => {
  it("reads its thresholds from the shared file and names each problem as the photo is shown", () => {
    expect(THRESHOLDS.minVariance).toBe(thresholdsFile.blur.min_variance);
    expect(THRESHOLDS.minMeanLuminance).toBe(
      thresholdsFile.darkness.min_mean_luminance,
    );
    expect(THRESHOLDS.maxFailuresBeforeSendAnyway).toBe(2);
    expect(analysisSize(4032, 3024)).toEqual({ width: 1024, height: 768 });

    expect(photoProblem(page())).toBeNull();
    // Darkness first: a dark, blurry photo is dark.
    expect(photoProblem(darkened(blurred(page())))).toEqual({ kind: "dark" });
    expect(photoProblem(blurred(page()))).toEqual({ kind: "blurry" });
    expect(photoProblem(page({ bleed: "top" }))).toEqual({
      kind: "cut-off",
      side: "top",
    });
    // The browser applies EXIF orientation first: a turned photo's bottom is its left.
    expect(photoProblem(turnedClockwise(page({ bleed: "bottom" })))).toEqual({
      kind: "cut-off",
      side: "left",
    });
  });
});
