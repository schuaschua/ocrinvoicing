import { describe, expect, it, vi } from "vitest";

import { fileSize, strings } from "@/strings";
import {
  CHOOSE_FILE_ACCEPT,
  MAX_UPLOAD_BYTES,
  TAKE_PHOTO_ACCEPT,
  cameraAvailable,
  isPdf,
  newUploadKey,
  normalisedType,
  refusal,
} from "@/upload";

function file(size: number, type: string): File {
  const made = new File([], "invoice", { type });
  Object.defineProperty(made, "size", { value: size });
  return made;
}

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("1.8 file rules on the page", () => {
  it.each(["image/jpeg", "image/png", "application/pdf", ""])(
    "lets a %s file of 4 MB through",
    (type) => {
      expect(refusal(file(MAX_UPLOAD_BYTES, type))).toBeNull();
    },
  );

  it("refuses a file over 4 MB", () => {
    expect(MAX_UPLOAD_BYTES).toBe(4 * 1024 * 1024);
    expect(refusal(file(MAX_UPLOAD_BYTES + 1, "image/jpeg"))).toBe(
      strings.fileRefused.tooLarge,
    );
  });

  it.each(["image/gif", "image/heic", "text/plain"])(
    "refuses a %s file",
    (type) => {
      expect(refusal(file(10, type))).toBe(strings.fileRefused.wrongType);
    },
  );

  it.each([
    ["image/jpg", "image/jpeg"],
    ["image/pjpeg", "image/jpeg"],
    ["image/x-png", "image/png"],
    ["IMAGE/JPEG", "image/jpeg"],
  ])(
    "reads the older type name %s as %s and lets it through",
    (type, standard) => {
      expect(normalisedType(type)).toBe(standard);
      expect(refusal(file(10, type))).toBeNull();
    },
  );

  it("says too large without suggesting a photo is smaller", () => {
    expect(strings.fileRefused.tooLarge).toBe(
      "This file is over 4 MB. Choose a smaller photo, or a PDF under 4 MB.",
    );
  });

  it("tells a PDF by its type or, with no type, by its name", () => {
    const named = (name: string, type: string) => new File([], name, { type });
    expect(isPdf(named("a.bin", "application/pdf"))).toBe(true);
    expect(isPdf(named("Invoice.PDF", ""))).toBe(true);
    expect(isPdf(named("invoice.jpg", ""))).toBe(false);
    expect(isPdf(named("invoice.pdf", "image/jpeg"))).toBe(false);
  });

  it("lets the camera save only JPEG or PNG", () => {
    expect(TAKE_PHOTO_ACCEPT).toBe("image/jpeg,image/png");
  });

  it("refuses an empty file", () => {
    expect(refusal(file(0, "image/jpeg"))).toBe(strings.fileRefused.empty);
  });

  it("accepts only JPEG, PNG and PDF in the picker", () => {
    expect(CHOOSE_FILE_ACCEPT.split(",")).toEqual([
      "image/jpeg",
      "image/png",
      "application/pdf",
      ".jpg",
      ".jpeg",
      ".png",
      ".pdf",
    ]);
  });

  it("shows sizes in KB under 1 MB and in MB above, never 1024 KB", () => {
    expect(fileSize(10)).toBe("1 KB");
    expect(fileSize(850 * 1024)).toBe("850 KB");
    expect(fileSize(1023 * 1024)).toBe("1023 KB");
    expect(fileSize(1024 * 1024 - 100)).toBe("1.0 MB");
    expect(fileSize(1.25 * 1024 * 1024)).toBe("1.3 MB");
  });
});

describe("1.8 upload key", () => {
  it("is a new random UUID each time", () => {
    const keys = new Set(Array.from({ length: 50 }, () => newUploadKey()));
    expect(keys.size).toBe(50);
    for (const key of keys) expect(key).toMatch(UUID_V4);
  });

  it("is built from getRandomValues where randomUUID is missing", () => {
    const source = {
      getRandomValues: <T extends ArrayBufferView | null>(array: T): T => {
        (array as unknown as Uint8Array).fill(0xff);
        return array;
      },
    } as unknown as Crypto;
    expect(newUploadKey(source)).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
  });
});

describe("1.8 camera availability", () => {
  function devices(kinds: MediaDeviceKind[]) {
    return {
      enumerateDevices: vi.fn(async () =>
        kinds.map((kind) => ({ kind }) as MediaDeviceInfo),
      ),
    };
  }

  it("is true with a video input", async () => {
    await expect(
      cameraAvailable(devices(["audioinput", "videoinput"])),
    ).resolves.toBe(true);
  });

  it("is false when the browser lists no video input", async () => {
    await expect(cameraAvailable(devices(["audioinput"]))).resolves.toBe(false);
  });

  it("is left to the native input when the browser can't tell", async () => {
    await expect(cameraAvailable(undefined)).resolves.toBe(true);
    await expect(
      cameraAvailable({
        enumerateDevices: () => Promise.reject(new Error("blocked")),
      }),
    ).resolves.toBe(true);
  });
});
