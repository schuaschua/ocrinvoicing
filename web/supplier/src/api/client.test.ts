import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  LINK_NOT_VALID,
  OFFLINE,
  SESSION_EXPIRED,
  apiHeaders,
  apiRequest,
  onApiEvent,
  setUploadToken,
} from "@/api";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();
// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";

function jsonResponse(
  body: unknown,
  status: number,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  setUploadToken(null);
  vi.unstubAllGlobals();
});

describe("1.4 API client", () => {
  it("sends the CSRF header, same-origin credentials and the upload token only while set", async () => {
    fetchMock.mockImplementation(async () => jsonResponse({ ok: 1 }, 200));
    setUploadToken(TOKEN);
    await expect(apiRequest("/api/health")).resolves.toEqual({ ok: 1 });
    setUploadToken(null);
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(
      apiRequest("/api/things", { method: "POST", json: { a: 1 } }),
    ).resolves.toBeUndefined();

    const [withToken, without] = fetchMock.mock.calls;
    // The token travels in a header, never in the URL.
    expect(withToken![0]).toBe("/api/health");
    expect(withToken![1]).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      redirect: "manual",
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-Upload-Token": TOKEN,
      },
    });
    expect(without![1]?.body).toBe('{"a":1}');
    expect(without![1]?.headers).toMatchObject({
      "Content-Type": "application/json",
    });
    expect(without![1]?.headers).not.toHaveProperty("X-Upload-Token");
    expect(apiHeaders()).not.toHaveProperty("X-Upload-Token");

    // Same origin only.
    await expect(apiRequest("https://evil.example/api/x")).rejects.toThrow(
      "API paths start with /api/",
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("maps failures to typed errors and raises the session and offline events", async () => {
    const expired = vi.fn();
    const offline = vi.fn();
    const stopExpired = onApiEvent(SESSION_EXPIRED, expired);
    const stopOffline = onApiEvent(OFFLINE, offline);

    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        { code: "UNAUTHENTICATED", message: "Sign in.", correlation_id: "c-1" },
        401,
      ),
    );
    await expect(apiRequest("/api/me")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      code: "UNAUTHENTICATED",
      correlationId: "c-1",
    });
    expect(expired).toHaveBeenCalledTimes(1);

    // A supplier link that isn't valid is not an expired sign-in.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: LINK_NOT_VALID, message: "Not valid." }, 401),
    );
    await expect(apiRequest("/api/link")).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledTimes(1);

    const redirect = Response.error();
    Object.defineProperty(redirect, "type", { value: "opaqueredirect" });
    fetchMock.mockResolvedValueOnce(redirect);
    await expect(apiRequest("/api/me")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(2);

    // Built-in auth's empty 403 on an expired session is a 401; any other 403 (our
    // own JSON refusal, or a platform HTML page) is not an expired sign-in.
    fetchMock.mockResolvedValueOnce(new Response("", { status: 403 }));
    await expect(apiRequest("/api/me")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(3);
    // A platform 403 page (site stopped, quota) has HTML: not a sign-in problem.
    fetchMock.mockResolvedValueOnce(
      new Response("<html>Site stopped</html>", { status: 403 }),
    );
    await expect(apiRequest("/api/me")).rejects.toMatchObject({
      status: 403,
      code: null,
    });
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "FORBIDDEN", message: "Not allowed." }, 403),
    );
    await expect(apiRequest("/api/queue")).rejects.toMatchObject({
      status: 403,
      code: "FORBIDDEN",
    });
    expect(expired).toHaveBeenCalledTimes(3);

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ code: "DB_OFFLINE", message: "Offline." }, 503),
    );
    await expect(apiRequest("/api/queue")).rejects.toMatchObject({
      status: 503,
    });
    expect(offline).toHaveBeenCalledTimes(1);

    fetchMock.mockResolvedValueOnce(
      new Response("<html>Bad gateway</html>", {
        status: 502,
        headers: { "X-Correlation-Id": "c-4" },
      }),
    );
    await expect(apiRequest("/api/x")).rejects.toMatchObject({
      status: 502,
      code: null,
      message: strings.errors.generic,
      correlationId: "c-4",
    });

    fetchMock.mockResolvedValueOnce(new Response("", { status: 200 }));
    await expect(apiRequest("/api/x")).rejects.toMatchObject({
      status: 200,
      message: strings.errors.generic,
    });

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(apiRequest("/api/x")).rejects.toMatchObject({
      status: 0,
      message: strings.errors.network,
    });

    // The caller's own abort is not a network failure.
    const controller = new AbortController();
    const reason = new Error("user left the page");
    controller.abort(reason);
    fetchMock.mockRejectedValueOnce(reason);
    await expect(
      apiRequest("/api/x", { signal: controller.signal }),
    ).rejects.toBe(reason);

    stopExpired();
    stopOffline();
    fetchMock.mockResolvedValueOnce(jsonResponse({}, 401));
    await expect(apiRequest("/api/me")).rejects.toBeInstanceOf(ApiError);
    expect(expired).toHaveBeenCalledTimes(3);
  });
});
