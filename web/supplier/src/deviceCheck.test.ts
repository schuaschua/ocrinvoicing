import { afterEach, describe, expect, it, vi } from "vitest";

import { blurred, darkened, page, pdfBytes } from "@shared/quality/fixtures";
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
  it("decodes with EXIF orientation applied, at 1024 px on the long side", async () => {
    const { decode, drawn, bitmap, context } = stubDecoder(page());
    const file = jpeg();
    await decodePhoto(file);
    // No size in this header: decoded at full size, downscaled on the canvas.
    expect(decode).toHaveBeenCalledWith(file, {
      imageOrientation: "from-image",
    });
    expect(drawn).toEqual([[0, 0, 1024, 768]]);
    expect(context.imageSmoothingQuality).toBe("high");
    expect(bitmap.close).toHaveBeenCalled();
  });

  it("asks the browser to decode already downscaled when the header gives the size", async () => {
    const { decode, drawn } = stubDecoder(page(), { width: 1024, height: 768 });
    const file = jpegWithSize();
    await decodePhoto(file);
    expect(decode).toHaveBeenCalledWith(file, {
      imageOrientation: "from-image",
      resizeWidth: 1024,
      resizeQuality: "high",
    });
    expect(drawn).toEqual([[0, 0, 1024, 768]]);
  });

  it("decodes plainly when the browser rejects the options", async () => {
    const { decode } = stubDecoder(page());
    decode.mockRejectedValueOnce(new TypeError("imageOrientation"));
    const file = jpegWithSize();
    await expect(decodePhoto(file)).resolves.not.toBeNull();
    expect(decode).toHaveBeenCalledTimes(2);
    expect(decode).toHaveBeenLastCalledWith(file);
  });

  it("draws over white, so a transparent PNG reads as paper", async () => {
    const { calls } = stubDecoder(page());
    await decodePhoto(jpeg());
    expect(calls).toEqual(["fill white", "draw"]);
  });

  it("passes a good photo", async () => {
    stubDecoder(page());
    await expect(checkFile(jpeg())).resolves.toEqual({ kind: "passed" });
  });

  it.each([
    ["dark", darkened(page()), { kind: "dark" }],
    ["blurry", blurred(page()), { kind: "blurry" }],
    ["cut off", page({ bleed: "bottom" }), { kind: "cut-off", side: "bottom" }],
  ])("names a %s photo", async (_, pixels, problem) => {
    stubDecoder(pixels);
    await expect(checkFile(jpeg())).resolves.toEqual({
      kind: "photo-problem",
      problem,
    });
  });

  it("passes a photo it can't decode, without failing", async () => {
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn(async () => {
        throw new DOMException("bad", "InvalidStateError");
      }),
    );
    await expect(decodePhoto(jpeg())).resolves.toBeNull();
    await expect(checkFile(jpeg())).resolves.toEqual({ kind: "passed" });
  });

  it("passes when the canvas gives no context or fails to draw", async () => {
    const { getContext, bitmap } = stubDecoder(page());
    getContext.mockReturnValue(null);
    await expect(decodePhoto(jpeg())).resolves.toBeNull();
    getContext.mockImplementation(() => {
      throw new Error("tainted");
    });
    await expect(decodePhoto(jpeg())).resolves.toBeNull();
    expect(bitmap.close).toHaveBeenCalledTimes(2);
  });

  it("passes a photo whose check is still running at the hard cap", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn(() => new Promise(() => {})),
    );
    let settled = false;
    const result = checkFile(jpeg()).then((value) => {
      settled = true;
      return value;
    });
    await vi.advanceTimersByTimeAsync(THRESHOLDS.maxCheckMs - 1);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await expect(result).resolves.toEqual({ kind: "passed" });
    expect(THRESHOLDS.maxCheckMs).toBeGreaterThan(THRESHOLDS.targetCheckMs);
  });

  it.each([
    [1, { kind: "passed" }],
    [2, { kind: "passed" }],
    [3, { kind: "too-many-pages" }],
  ])("a %i-page PDF: %o, with no photo check", async (pages, result) => {
    const decode = vi.fn();
    vi.stubGlobal("createImageBitmap", decode);
    await expect(checkFile(pdf(pages))).resolves.toEqual(result);
    expect(decode).not.toHaveBeenCalled();
  });

  it("sends a PDF whose pages can't be counted (the server decides)", async () => {
    const file = new File(
      ["%PDF-1.7\n5 0 obj\n<< /Type /ObjStm >>\nendobj"],
      "x.pdf",
      {
        type: "application/pdf",
      },
    );
    await expect(checkFile(file)).resolves.toEqual({ kind: "passed" });
  });

  it("passes a PDF it can't read", async () => {
    const file = pdf(3);
    vi.spyOn(file, "arrayBuffer").mockRejectedValue(new Error("gone"));
    await expect(checkFile(file)).resolves.toEqual({ kind: "passed" });
  });

  it("knows when this browser can check a file", () => {
    expect(canCheck(pdf(1))).toBe(true);
    // jsdom has no image decoder.
    expect(canCheck(jpeg())).toBe(false);
    stubDecoder(page());
    expect(canCheck(jpeg())).toBe(true);
  });
});
