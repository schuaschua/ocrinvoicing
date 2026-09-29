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
  it("posts the raw file with its type, the key and the token", async () => {
    const file = jpeg();
    const sent = uploadInvoice(file, UPLOAD_ID);
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
    xhr.respond(200, OK);
    await expect(sent).resolves.toEqual(OK);
  });

  it("1.9 sends X-Device-Check overridden after Send it anyway", () => {
    void uploadInvoice(jpeg(), UPLOAD_ID, { deviceCheck: "overridden" });
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("overridden");
  });

  it("1.9 sends X-Device-Check skipped when the page couldn't check the file", () => {
    void uploadInvoice(jpeg(), UPLOAD_ID, { deviceCheck: "skipped" });
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("skipped");
  });

  it("labels a file with no type as octet-stream; the server reads the bytes", () => {
    void uploadInvoice(new File([new Uint8Array([1])], "x"), UPLOAD_ID);
    expect(FakeXhr.last().headers["Content-Type"]).toBe(
      "application/octet-stream",
    );
  });

  it("reports progress as a fraction, and 1 when done", async () => {
    const onProgress = vi.fn();
    const sent = uploadInvoice(jpeg(), UPLOAD_ID, { onProgress });
    const xhr = FakeXhr.last();
    xhr.progress(25, 100);
    xhr.upload.emit("progress", { lengthComputable: false });
    xhr.progress(100, 100);
    xhr.respond(200, OK);
    await sent;
    expect(onProgress.mock.calls.map(([f]) => f)).toEqual([0.25, 1, 1]);
  });

  it.each([
    ["no reference", { invoice_id: OK.invoice_id }],
    ["a malformed reference", { ...OK, reference: "R-ILOU0000" }],
    ["a non-JSON body", "<html>ok</html>"],
  ])("treats a success with %s as a broken answer", async (_, body) => {
    const sent = uploadInvoice(jpeg(), UPLOAD_ID);
    FakeXhr.last().respond(200, body, { "X-Correlation-Id": "c-1" });
    await expect(sent).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      message: strings.errors.generic,
      correlationId: "c-1",
    });
  });

  it("maps an error answer to a typed error", async () => {
    const sent = uploadInvoice(jpeg(), UPLOAD_ID);
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
  });

  it("maps an error without a JSON body to a generic error", async () => {
    const sent = uploadInvoice(jpeg(), UPLOAD_ID);
    FakeXhr.last().respond(502, "Bad gateway");
    await expect(sent).rejects.toMatchObject({
      status: 502,
      code: null,
      message: strings.errors.generic,
    });
  });

  it.each([
    ["a network failure", (xhr: FakeXhr) => xhr.fail()],
    ["a timeout", (xhr: FakeXhr) => xhr.timeOut()],
  ])("turns %s into a network error (status 0)", async (_, happen) => {
    const sent = uploadInvoice(jpeg(), UPLOAD_ID);
    happen(FakeXhr.last());
    await expect(sent).rejects.toMatchObject({
      status: 0,
      message: strings.errors.network,
    });
  });

  it("aborts the request with the signal's reason", async () => {
    const controller = new AbortController();
    const reason = new Error("left the page");
    const sent = uploadInvoice(jpeg(), UPLOAD_ID, {
      signal: controller.signal,
    });
    controller.abort(reason);
    await expect(sent).rejects.toBe(reason);
    expect(FakeXhr.last().aborted).toBe(true);
  });

  it("sends nothing when the signal has already aborted", async () => {
    const controller = new AbortController();
    controller.abort(new Error("gone"));
    await expect(
      uploadInvoice(jpeg(), UPLOAD_ID, { signal: controller.signal }),
    ).rejects.toThrow("gone");
    expect(FakeXhr.requests).toEqual([]);
  });
});
