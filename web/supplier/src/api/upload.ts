// `POST /api/upload` (Story 1.8, AD-6): the chosen file as the raw body, with its
// Idempotency-Key. XHR, not fetch, because only XHR reports upload progress.

import { strings } from "@/strings";

import { ApiError, apiHeaders } from "./client";

const PATH = "/api/upload";
const IDEMPOTENCY_KEY_HEADER = "Idempotency-Key";
const CORRELATION_HEADER = "X-Correlation-Id";
/** Story 1.9: how the page's photo check went (AD-5 `device_check`). */
export const DEVICE_CHECK_HEADER = "X-Device-Check";

/**
 * "passed" when the check ran and passed, "overridden" after Send it anyway, "skipped"
 * when the page couldn't check the file (the server checks it either way).
 */
export type DeviceCheck = "passed" | "overridden" | "skipped";
// R- and 8 Crockford base32 characters (EXPERIENCE.md "Supplier reference").
const REFERENCE = /^R-[0-9A-HJKMNP-TV-Z]{8}$/;

/** A 4 MB file on a weak mobile signal still fits; the Functions host allows 230 s. */
export const UPLOAD_TIMEOUT_MS = 180_000;

export interface UploadResult {
  invoice_id: string;
  reference: string;
}

export interface UploadOptions {
  /** Called with the fraction sent so far, from 0 to 1. */
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
  /** The device check's outcome (see `DeviceCheck`). Default "passed". */
  deviceCheck?: DeviceCheck;
}

function parse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function field(body: unknown, name: string): string | null {
  if (body === null || typeof body !== "object") return null;
  const value = (body as Record<string, unknown>)[name];
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * Send `file` once under `key`. A retry with the same key never creates a second
 * invoice (AD-6), so after any failure the caller may send it again with that key.
 * Rejects with an `ApiError` (status 0 for a network failure or timeout), or with the
 * signal's reason when `signal` aborts.
 */
export function uploadInvoice(
  file: Blob,
  key: string,
  options: UploadOptions = {},
): Promise<UploadResult> {
  const { onProgress, signal, deviceCheck = "passed" } = options;
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }
    const xhr = new XMLHttpRequest();
    const onAbort = () => xhr.abort();
    const done = () => signal?.removeEventListener("abort", onAbort);

    xhr.open("POST", PATH);
    for (const [name, value] of Object.entries(apiHeaders())) {
      xhr.setRequestHeader(name, value);
    }
    // The raw file: the server stores these bytes exactly as sent.
    xhr.setRequestHeader(
      "Content-Type",
      file.type || "application/octet-stream",
    );
    xhr.setRequestHeader(IDEMPOTENCY_KEY_HEADER, key);
    xhr.setRequestHeader(DEVICE_CHECK_HEADER, deviceCheck);
    xhr.timeout = UPLOAD_TIMEOUT_MS;

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.(Math.min(1, event.loaded / event.total));
      }
    });
    xhr.addEventListener("load", () => {
      done();
      const body = parse(xhr.responseText);
      const correlationId =
        field(body, "correlation_id") ??
        xhr.getResponseHeader(CORRELATION_HEADER);
      if (xhr.status >= 200 && xhr.status < 300) {
        const invoiceId = field(body, "invoice_id");
        const reference = field(body, "reference");
        if (
          invoiceId !== null &&
          reference !== null &&
          REFERENCE.test(reference)
        ) {
          onProgress?.(1);
          resolve({ invoice_id: invoiceId, reference });
          return;
        }
        // A broken answer, not a success to show.
        reject(
          new ApiError(strings.errors.generic, xhr.status, null, correlationId),
        );
        return;
      }
      reject(
        new ApiError(
          field(body, "message") ?? strings.errors.generic,
          xhr.status,
          field(body, "code"),
          correlationId,
        ),
      );
    });
    const networkFailure = () => {
      done();
      reject(new ApiError(strings.errors.network, 0, null, null));
    };
    xhr.addEventListener("error", networkFailure);
    xhr.addEventListener("timeout", networkFailure);
    xhr.addEventListener("abort", () => {
      done();
      reject(
        signal?.reason ?? new ApiError(strings.errors.network, 0, null, null),
      );
    });
    signal?.addEventListener("abort", onAbort, { once: true });

    xhr.send(file);
  });
}
