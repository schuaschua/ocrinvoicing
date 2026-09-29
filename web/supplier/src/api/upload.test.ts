import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, setUploadToken } from "@/api";
import { UPLOAD_TIMEOUT_MS, uploadInvoice } from "@/api/upload";
import { strings } from "@/strings";
import { FakeXhr } from "@/test/fakeXhr";

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";
const UPLOAD_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const OK = {
  invoice_id: "0199a1b2-0000-7000-8000-000000000001",
  reference: "R-7Q4KXM2D",
};

function jpeg(): File {
  return new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])], "inv.jpg", {
    type: "image/jpeg",
  });
}

beforeEach(() => {
  FakeXhr.reset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  setUploadToken(TOKEN);
});

afterEach(() => {
  setUploadToken(null);
  vi.unstubAllGlobals();
});

describe("1.8 upload call", () => {
  it("posts the raw file with its type, the key, the token and the device check, never logging the token", async () => {
    const logged = (["log", "info", "warn", "error", "debug"] as const).map(
      (method) => vi.spyOn(console, method),
    );
    const onProgress = vi.fn();
    const file = jpeg();
    const sent = uploadInvoice(file, UPLOAD_ID, { onProgress });
    const xhr = FakeXhr.last();
    expect(xhr.method).toBe("POST");
    expect(xhr.url).toBe("/api/upload");
    // The file itself, not a form: the server stores these bytes as sent.
    expect(xhr.body).toBe(file);
    expect(xhr.headers).toEqual({
      Accept: "application/json",
      "X-Requested-With": "XMLHttpRequest",
      "X-Upload-Token": TOKEN,
      "Content-Type": "image/jpeg",
      "Idempotency-Key": UPLOAD_ID,
      "X-Device-Check": "passed",
    });
    expect(xhr.timeout).toBe(UPLOAD_TIMEOUT_MS);
    xhr.progress(25, 100);
    xhr.respond(200, OK);
    await expect(sent).resolves.toEqual(OK);
    expect(onProgress.mock.calls.map(([f]) => f)).toEqual([0.25, 1]);

    // 1.9: the other device-check outcomes, and a file with no type.
    void uploadInvoice(new File([new Uint8Array([1])], "x"), UPLOAD_ID, {
      deviceCheck: "skipped",
    });
    expect(FakeXhr.last().headers).toMatchObject({
      "X-Device-Check": "skipped",
      "Content-Type": "application/octet-stream",
    });
    void uploadInvoice(jpeg(), UPLOAD_ID, { deviceCheck: "overridden" });
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("overridden");

    for (const spy of logged) {
      expect(JSON.stringify(spy.mock.calls)).not.toContain(TOKEN);
      spy.mockRestore();
    }
  });

  it("maps a broken answer, an error answer, a network failure and an abort to errors", async () => {
    let sent = uploadInvoice(jpeg(), UPLOAD_ID);
    FakeXhr.last().respond(
      200,
      { ...OK, reference: "R-ILOU0000" },
      { "X-Correlation-Id": "c-1" },
    );
    await expect(sent).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      message: strings.errors.generic,
      correlationId: "c-1",
    });

    sent = uploadInvoice(jpeg(), UPLOAD_ID);
    FakeXhr.last().respond(415, {
      code: "UNSUPPORTED_MEDIA_TYPE",
      message: "Nope.",
      correlation_id: "c-2",
    });
    const error = await sent.catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 415,
      code: "UNSUPPORTED_MEDIA_TYPE",
      correlationId: "c-2",
    });

    sent = uploadInvoice(jpeg(), UPLOAD_ID);
    FakeXhr.last().timeOut();
    await expect(sent).rejects.toMatchObject({
      status: 0,
      message: strings.errors.network,
    });

    const controller = new AbortController();
    const reason = new Error("left the page");
    sent = uploadInvoice(jpeg(), UPLOAD_ID, { signal: controller.signal });
    controller.abort(reason);
    await expect(sent).rejects.toBe(reason);
    expect(FakeXhr.last().aborted).toBe(true);

    // Already aborted: nothing is sent.
    const requests = FakeXhr.requests.length;
    await expect(
      uploadInvoice(jpeg(), UPLOAD_ID, { signal: controller.signal }),
    ).rejects.toBe(reason);
    expect(FakeXhr.requests).toHaveLength(requests);
  });
});
