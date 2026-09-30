// The on-device check of a chosen file (Story 1.9, CAP-3): a photo is decoded with its
// EXIF orientation, measured on a downscaled copy (shared/quality), and a PDF's pages
// are counted. Only the check reads these pixels: the upload still sends the original
// bytes (AD-6). Anything the page can't check (no decoder, an undecodable file, an
// error, a check that takes too long, a PDF whose pages can't be counted) is sent
// marked skipped (AD-5); the server checks again either way.

import {
  type PhotoProblem,
  THRESHOLDS,
  analysisSize,
  photoProblem,
} from "@shared/quality/check";
import type { Pixels } from "@shared/quality/measure";
import { countPdfPages, tooManyPages } from "@shared/quality/pdf";
import { HEADER_BYTES, imageSize } from "@shared/quality/size";

import { isPdf } from "@/upload";

// One definition of the header value, shared with the upload call.
export type { DeviceCheck } from "@/api/upload";

export type CheckResult =
  | { kind: "passed" }
  | { kind: "skipped" }
  | { kind: "photo-problem"; problem: PhotoProblem }
  | { kind: "too-many-pages" };

const PASSED: CheckResult = { kind: "passed" };
const SKIPPED: CheckResult = { kind: "skipped" };

/** Whether this browser can check `file` at all; when it can't, the page skips the check. */
export function canCheck(file: File): boolean {
  if (isPdf(file)) return typeof file.arrayBuffer === "function";
  return (
    typeof createImageBitmap === "function" &&
    typeof document.createElement("canvas").getContext === "function"
  );
}

/**
 * Decode `file` as the user sees it (EXIF orientation applied). When its header gives
 * its size, the browser decodes it already downscaled: only the width is set, so the
 * aspect ratio holds whether the browser turns the photo before or after resizing (a
 * turned photo may come out up to 4/3 over the analysis size; the canvas finishes the
 * job). A browser that rejects these options (a TypeError) decodes it plainly.
 */
async function decodeBitmap(file: Blob): Promise<ImageBitmap> {
  const stored = imageSize(
    new Uint8Array(await file.slice(0, HEADER_BYTES).arrayBuffer()),
  );
  const options: ImageBitmapOptions = { imageOrientation: "from-image" };
  if (stored !== null) {
    options.resizeWidth = analysisSize(stored.width, stored.height).width;
    options.resizeQuality = "high";
  }
  try {
    return await createImageBitmap(file, options);
  } catch (error) {
    if (!(error instanceof TypeError)) throw error;
    return createImageBitmap(file);
  }
}

/**
 * `file`'s pixels as the user sees the photo, downscaled so the long side is at most
 * the analysis size, over white (a transparent PNG reads as paper, not as black);
 * null when it can't be decoded.
 */
export async function decodePhoto(file: Blob): Promise<Pixels | null> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await decodeBitmap(file);
  } catch {
    return null;
  }
  try {
    const { width, height } = analysisSize(bitmap.width, bitmap.height);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (context === null) return null;
    context.fillStyle = "white";
    context.fillRect(0, 0, width, height);
    context.imageSmoothingEnabled = true;
    context.imageSmoothingQuality = "high";
    context.drawImage(bitmap, 0, 0, width, height);
    return context.getImageData(0, 0, width, height);
  } catch {
    return null;
  } finally {
    bitmap.close();
  }
}

async function run(file: File): Promise<CheckResult> {
  if (isPdf(file)) {
    const pages = countPdfPages(new Uint8Array(await file.arrayBuffer()));
    if (pages === null) return SKIPPED;
    return tooManyPages(pages) ? { kind: "too-many-pages" } : PASSED;
  }
  const pixels = await decodePhoto(file);
  if (pixels === null) return SKIPPED;
  const problem = photoProblem(pixels);
  return problem === null ? PASSED : { kind: "photo-problem", problem };
}

/**
 * Check `file` on the device. Never rejects: whatever can't be checked is skipped, and
 * so is a check still running at the hard cap (`analysis.max_check_ms`; the target is
 * `target_check_ms`).
 */
export async function checkFile(
  file: File,
  timeoutMs: number = THRESHOLDS.maxCheckMs,
): Promise<CheckResult> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<CheckResult>((resolve) => {
    timer = setTimeout(() => resolve(SKIPPED), timeoutMs);
  });
  try {
    return await Promise.race([run(file).catch(() => SKIPPED), timeout]);
  } finally {
    clearTimeout(timer);
  }
}
