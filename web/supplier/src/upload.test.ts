import { describe, expect, it } from "vitest";

import { fileSize, strings } from "@/strings";
import {
  CHOOSE_FILE_ACCEPT,
  MAX_UPLOAD_BYTES,
  TAKE_PHOTO_ACCEPT,
  isPdf,
  newUploadKey,
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
  it("lets JPEG, PNG and PDF of up to 4 MB through, and refuses the rest with the reason", () => {
    for (const type of [
      "image/jpeg",
      "image/png",
      "application/pdf",
      "",
      "image/pjpeg",
    ]) {
      expect(refusal(file(MAX_UPLOAD_BYTES, type))).toBeNull();
    }
    expect(refusal(file(MAX_UPLOAD_BYTES + 1, "image/jpeg"))).toBe(
      strings.fileRefused.tooLarge,
    );
    expect(refusal(file(10, "image/heic"))).toBe(strings.fileRefused.wrongType);
    expect(refusal(file(0, "image/jpeg"))).toBe(strings.fileRefused.empty);
    expect(TAKE_PHOTO_ACCEPT).toBe("image/jpeg,image/png");
    expect(CHOOSE_FILE_ACCEPT).toBe(
      "image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf",
    );
    expect(isPdf(new File([], "Invoice.PDF"))).toBe(true);
    expect(isPdf(new File([], "invoice.pdf", { type: "image/jpeg" }))).toBe(
      false,
    );
    expect(fileSize(1024 * 1024 - 100)).toBe("1.0 MB");
  });
});

describe("1.8 upload key", () => {
  it("is a new random UUID each time, also where randomUUID is missing", () => {
    const keys = new Set(Array.from({ length: 50 }, () => newUploadKey()));
    expect(keys.size).toBe(50);
    for (const key of keys) expect(key).toMatch(UUID_V4);
    const source = {
      getRandomValues: <T extends ArrayBufferView | null>(array: T): T => {
        (array as unknown as Uint8Array).fill(0xff);
        return array;
      },
    } as unknown as Crypto;
    expect(newUploadKey(source)).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
  });
});
