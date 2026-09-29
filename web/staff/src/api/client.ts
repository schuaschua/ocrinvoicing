// The one API client (coding-style.md rule 15, UX-DR3). Components call these
// functions and never `fetch` directly; ESLint blocks fetch outside src/api/.

import { strings } from "@/strings";

/** Fired on `apiEvents` when the API answers 401: the sign-in has expired. */
export const SESSION_EXPIRED = "session-expired";
/** Fired on `apiEvents` on the first successful call after a 401: signed in again. */
export const SESSION_RESTORED = "session-restored";
/** Fired on `apiEvents` when the API answers 503 `DB_OFFLINE` (AD-12). */
export const OFFLINE = "offline";
export type ApiEventType =
  typeof SESSION_EXPIRED | typeof SESSION_RESTORED | typeof OFFLINE;

// Whether the last answer was a 401, so the next success is a new sign-in.
let expired = false;

function sessionExpired(): void {
  expired = true;
  apiEvents.dispatchEvent(new Event(SESSION_EXPIRED));
}

/** Session-expired and offline notices listen here. */
export const apiEvents = new EventTarget();

/** Subscribe to an API event; returns the unsubscribe function. */
export function onApiEvent(
  type: ApiEventType,
  listener: () => void,
): () => void {
  apiEvents.addEventListener(type, listener);
  return () => apiEvents.removeEventListener(type, listener);
}

const CORRELATION_HEADER = "X-Correlation-Id";
const UPLOAD_TOKEN_HEADER = "X-Upload-Token";
/** The API's 401 code for a supplier link that can't be used (UX-DR7). */
export const LINK_NOT_VALID = "LINK_NOT_VALID";

// The supplier page's link token (AD-6), read from the URL fragment (which stays there
// so a reload works). It reaches the server only in this header, never in a request
// URL, and is never stored or logged. The staff app never sets it.
let uploadToken: string | null = null;

/** Send `token` as `X-Upload-Token` on every later call; null stops sending it. */
export function setUploadToken(token: string | null): void {
  uploadToken = token;
}

/**
 * The headers every API call sends: JSON accepted, the CSRF header and, on the supplier
 * page, the upload token. For callers in src/api/ that can't use `apiRequest`, such as
 * the supplier upload, which needs XHR progress events.
 */
export function apiHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    // CSRF defence (security.md rule 24); built-in auth answers 401, not a redirect.
    "X-Requested-With": "XMLHttpRequest",
  };
  if (uploadToken !== null) {
    headers[UPLOAD_TOKEN_HEADER] = uploadToken;
  }
  return headers;
}

/** A failed call, carrying the API's `{code, message, correlation_id}` when it sent one. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly correlationId: string | null;

  constructor(
    message: string,
    status: number,
    code: string | null,
    correlationId: string | null,
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.correlationId = correlationId;
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** Sent as JSON. */
  json?: unknown;
  signal?: AbortSignal;
}

interface ErrorBody {
  code?: unknown;
  message?: unknown;
  correlation_id?: unknown;
}

async function readErrorBody(response: Response): Promise<ErrorBody | null> {
  try {
    const body: unknown = await response.json();
    return body !== null && typeof body === "object"
      ? (body as ErrorBody)
      : null;
  } catch {
    return null;
  }
}

function text(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * Call the same-origin API at `path` (it must start with `/api/`) and return the
 * parsed JSON body, or `undefined` for 204. Rejects with an `ApiError` otherwise.
 */
export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  // Same origin only (AD-14, security.md rule 23): never an absolute URL.
  if (!path.startsWith("/api/")) {
    throw new Error(`API paths start with /api/, got ${path}`);
  }
  const headers = apiHeaders();
  const init: RequestInit = {
    method: options.method ?? "GET",
    headers,
    credentials: "same-origin",
    // An expired staff session may be answered with a redirect to the Entra login.
    // Followed, it fails as a cross-origin request and would read as "network"; kept
    // manual, it arrives as an opaque redirect, handled below as 401.
    redirect: "manual",
    signal: options.signal,
  };
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.json);
  }

  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    // The caller's own abort or timeout, with its reason, is not a network failure.
    if (options.signal?.aborted) {
      throw options.signal.reason;
    }
    throw new ApiError(strings.errors.network, 0, null, null);
  }

  if (response.type === "opaqueredirect") {
    sessionExpired();
    throw new ApiError(strings.errors.generic, 401, null, null);
  }

  if (response.ok) {
    if (expired) {
      expired = false;
      apiEvents.dispatchEvent(new Event(SESSION_RESTORED));
    }
    if (response.status === 204) {
      return undefined as T;
    }
    try {
      return (await response.json()) as T;
    } catch {
      // An empty or non-JSON success body is a broken answer, not a crash.
      throw new ApiError(
        strings.errors.generic,
        response.status,
        null,
        response.headers.get(CORRELATION_HEADER),
      );
    }
  }

  const body = await readErrorBody(response);
  const code = text(body?.code);
  const error = new ApiError(
    text(body?.message) ?? strings.errors.generic,
    response.status,
    code,
    text(body?.correlation_id) ?? response.headers.get(CORRELATION_HEADER),
  );
  // A supplier link that isn't valid is not an expired staff sign-in.
  if (response.status === 401 && code !== LINK_NOT_VALID) {
    sessionExpired();
  } else if (response.status === 503 && code === "DB_OFFLINE") {
    apiEvents.dispatchEvent(new Event(OFFLINE));
  }
  throw error;
}
