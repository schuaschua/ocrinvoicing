import { strings } from "@/strings";
import { knownRoles, type Role } from "@/surfaces";

import { ApiError, apiRequest } from "./client";

/** `GET /api/me`: the signed-in staff user's display name and app roles (AD-14). */
export interface Me {
  name: string;
  roles: Role[];
}

/** A sign-in check that takes longer than this ends in the retryable error. */
export const ME_TIMEOUT_MS = 30_000;

/**
 * Who is signed in. Rejects with the client's `ApiError` (401 has already raised the
 * session-ended event, 503 `DB_OFFLINE` the offline one), when `signal` aborts, or after
 * `ME_TIMEOUT_MS`. Roles this build doesn't know are dropped: the server checks every
 * route anyway.
 */
export async function getMe(signal?: AbortSignal): Promise<Me> {
  const controller = new AbortController();
  const stop = () => controller.abort(signal?.reason);
  if (signal?.aborted) stop();
  signal?.addEventListener("abort", stop, { once: true });
  const timer = window.setTimeout(
    () =>
      controller.abort(
        new DOMException("The sign-in check timed out.", "TimeoutError"),
      ),
    ME_TIMEOUT_MS,
  );
  try {
    const body = await apiRequest<{ name?: unknown; roles?: unknown } | null>(
      "/api/me",
      { signal: controller.signal },
    );
    if (!body || !Array.isArray(body.roles)) {
      throw new ApiError(strings.errors.generic, 200, null, null);
    }
    return {
      name: typeof body.name === "string" ? body.name : "",
      roles: knownRoles(body.roles),
    };
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", stop);
  }
}
