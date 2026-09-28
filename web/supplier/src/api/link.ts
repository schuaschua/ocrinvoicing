import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** `GET /api/link`: who the link uploads for. The supplier id never reaches the page. */
export interface LinkInfo {
  supplier_name: string;
}

/** A link check that takes longer than this ends in the retryable error. */
export const LINK_TIMEOUT_MS = 20_000;

/**
 * The supplier the current upload token belongs to. Rejects when `signal` aborts,
 * after `LINK_TIMEOUT_MS`, or when the answer has no supplier name to show.
 */
export async function getLink(signal?: AbortSignal): Promise<LinkInfo> {
  const controller = new AbortController();
  const stop = () => controller.abort(signal?.reason);
  if (signal?.aborted) stop();
  signal?.addEventListener("abort", stop, { once: true });
  const timer = window.setTimeout(
    () =>
      controller.abort(
        new DOMException("The link check timed out.", "TimeoutError"),
      ),
    LINK_TIMEOUT_MS,
  );
  try {
    const body = await apiRequest<{ supplier_name?: unknown } | null>(
      "/api/link",
      { signal: controller.signal },
    );
    const name = body?.supplier_name;
    if (typeof name !== "string" || name.trim() === "") {
      // A broken answer, not a link that doesn't work.
      throw new ApiError(strings.errors.generic, 200, null, null);
    }
    return { supplier_name: name.trim() };
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", stop);
  }
}
