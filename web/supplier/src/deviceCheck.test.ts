import { afterEach, describe, expect, it, vi } from "vitest";

import { darkened, page, pdfBytes } from "@shared/quality/fixtures";
import { THRESHOLDS } from "@shared/quality/check";
import type { Pixels } from "@shared/quality/measure";

import { canCheck, checkFile, decodePhoto } from "@/deviceCheck";

function jpeg(name = "inv.jpg"): File {
  return new File([new Uint8Array([0xff, 0xd8, 0xff])], name, {
    type: "image/jpeg",
  });
}

/** A JPEG whose header says 4032 × 3024 (the pixels come from the stubbed decoder). */
function jpegWithSize(): File {
  const sof = [0xff, 0xc0, 0x00, 0x11, 0x08, 0x0b, 0xd0, 0x0f, 0xc0, 0x03];
  return new File(
    [Uint8Array.from([0xff, 0xd8, ...sof, ...new Array(12).fill(0)])],
    "big.jpg",
    {
      type: "image/jpeg",
    },
  );
}

function pdf(pages: number): File {
  return new File([pdfBytes(pages)], "inv.pdf", { type: "application/pdf" });
}

/**
 * A browser that decodes every photo to `pixels` at `width` × `height`: records what
 * `createImageBitmap` was asked and what the canvas drew.
 */
function stubDecoder(pixels: Pixels, size = { width: 4032, height: 3024 }) {
  const bitmap = { ...size, close: vi.fn() };
  const decode = vi.fn(async () => bitmap);
  vi.stubGlobal("createImageBitmap", decode);
  const drawn: number[][] = [];
  const calls: string[] = [];
  const context = {
    fillStyle: "",
    imageSmoothingEnabled: false,
    imageSmoothingQuality: "low",
    fillRect: vi.fn(() => calls.push(`fill ${context.fillStyle}`)),
    drawImage: vi.fn((_: unknown, ...box: number[]) => {
      calls.push("draw");
      drawn.push(box);
    }),
    getImageData: vi.fn(() => pixels),
  };
  const getContext = vi
    .spyOn(HTMLCanvasElement.prototype, "getContext")
    .mockReturnValue(context as unknown as CanvasRenderingContext2D);
  return { bitmap, decode, drawn, context, getContext, calls };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("1.9 device check of a chosen file", () => {
  it("decodes a photo as the user sees it, downscaled over white, and names its problem", async () => {
    // jsdom has no image decoder.
    expect(canCheck(jpeg())).toBe(false);
    const { decode, drawn, bitmap, calls, context } = stubDecoder(page());
    expect(canCheck(jpeg())).toBe(true);
    const file = jpeg();
    await decodePhoto(file);
    // No size in this header: decoded at full size, downscaled on the canvas.
    expect(decode).toHaveBeenCalledWith(file, {
      imageOrientation: "from-image",
    });
    expect(drawn).toEqual([[0, 0, 1024, 768]]);
    expect(calls).toEqual(["fill white", "draw"]);
    expect(context.imageSmoothingQuality).toBe("high");
    expect(bitmap.close).toHaveBeenCalled();

    // A header with the size: decoded already downscaled, or plainly when the
    // browser rejects the options.
    decode.mockRejectedValueOnce(new TypeError("imageOrientation"));
    const sized = jpegWithSize();
    await expect(decodePhoto(sized)).resolves.not.toBeNull();
    expect(decode).toHaveBeenCalledWith(sized, {
      imageOrientation: "from-image",
      resizeWidth: 1024,
      resizeQuality: "high",
    });
    expect(decode).toHaveBeenLastCalledWith(sized);

    await expect(checkFile(jpeg())).resolves.toEqual({ kind: "passed" });
    context.getImageData.mockReturnValue(darkened(page()));
    await expect(checkFile(jpeg())).resolves.toEqual({
      kind: "photo-problem",
      problem: { kind: "dark" },
    });
  });

  it("skips what it can't check, and counts a PDF's pages without a photo check", async () => {
    const { getContext, decode } = stubDecoder(page());
    getContext.mockReturnValue(null);
    await expect(checkFile(jpeg())).resolves.toEqual({ kind: "skipped" });
    decode.mockRejectedValueOnce(new DOMException("bad", "InvalidStateError"));
    await expect(checkFile(jpeg())).resolves.toEqual({ kind: "skipped" });

    expect(canCheck(pdf(1))).toBe(true);
    decode.mockClear();
    await expect(checkFile(pdf(2))).resolves.toEqual({ kind: "passed" });
    await expect(checkFile(pdf(3))).resolves.toEqual({
      kind: "too-many-pages",
    });
    expect(decode).not.toHaveBeenCalled();
    const unreadable = pdf(3);
    vi.spyOn(unreadable, "arrayBuffer").mockRejectedValue(new Error("gone"));
    await expect(checkFile(unreadable)).resolves.toEqual({ kind: "skipped" });

    // Still running at the hard cap.
    vi.useFakeTimers();
    decode.mockImplementation(() => new Promise(() => {}));
    let settled = false;
    const result = checkFile(jpeg()).then((value) => {
      settled = true;
      return value;
    });
    await vi.advanceTimersByTimeAsync(THRESHOLDS.maxCheckMs - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toEqual({ kind: "skipped" });
  });
});
