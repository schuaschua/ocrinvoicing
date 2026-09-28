import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  OFFLINE,
  SESSION_EXPIRED,
  apiRequest,
  onApiEvent,
} from "@/api";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

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

function listen(type: typeof SESSION_EXPIRED | typeof OFFLINE) {
  const listener = vi.fn();
  const stop = onApiEvent(type, listener);
  return { listener, stop };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("1.4 API client", () => {
  it("sends X-Requested-With and same-origin credentials on every call", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: "ok" }, 200));
    await expect(apiRequest("/api/health")).resolves.toEqual({ status: "ok" });

    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/health");
    expect(init?.method).toBe("GET");
    expect(init?.credentials).toBe("same-origin");
    expect(init?.headers).toMatchObject({
      "X-Requested-With": "XMLHttpRequest",
      Accept: "application/json",
    });
  });

  it("sends a JSON body with its content type", async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
    await expect(
      apiRequest("/api/things", { method: "POST", json: { a: 1 } }),
    ).resolves.toBeUndefined();

    const init = fetchMock.mock.calls[0]![1]!;
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"a":1}');
    expect(init.headers).toMatchObject({
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    });
  });

  it("refuses a path outside the same-origin API", async () => {
    await expect(apiRequest("https://evil.example/api/x")).rejects.toThrow(
      "API paths start with /api/",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fires session-expired on 401 and rejects", async () => {
    const { listener, stop } = listen(SESSION_EXPIRED);
    fetchMock.mockResolvedValue(
      jsonResponse(
        { code: "UNAUTHORIZED", message: "Sign in.", correlation_id: "c-1" },
        401,
      ),
    );
    await expect(apiRequest("/api/me")).rejects.toMatchObject({
      status: 401,
      code: "UNAUTHORIZED",
    });
    expect(listener).toHaveBeenCalledTimes(1);
    stop();
  });

  it("fires offline on 503 DB_OFFLINE and rejects", async () => {
    const offline = listen(OFFLINE);
    const expired = listen(SESSION_EXPIRED);
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          code: "DB_OFFLINE",
          message: "The database is offline. Try again later.",
          correlation_id: "c-2",
        },
        503,
      ),
    );
    await expect(apiRequest("/api/queue")).rejects.toMatchObject({
      status: 503,
      code: "DB_OFFLINE",
      correlationId: "c-2",
    });
    expect(offline.listener).toHaveBeenCalledTimes(1);
    expect(expired.listener).not.toHaveBeenCalled();
    offline.stop();
    expired.stop();
  });

  it("treats any other 503 as an ordinary error", async () => {
    const { listener, stop } = listen(OFFLINE);
    fetchMock.mockResolvedValue(
      jsonResponse(
        { code: "INTERNAL_ERROR", message: "Busy.", correlation_id: "c-3" },
        503,
      ),
    );
    await expect(apiRequest("/api/queue")).rejects.toBeInstanceOf(ApiError);
    expect(listener).not.toHaveBeenCalled();
    stop();
  });

  it("maps the error shape to a typed error with code and correlation id", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          code: "VALIDATION_FAILED",
          message: "Amount is missing.",
          correlation_id: "0199a1b2-0000-7000-8000-000000000001",
        },
        400,
      ),
    );
    const error = await apiRequest("/api/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 400,
      code: "VALIDATION_FAILED",
      message: "Amount is missing.",
      correlationId: "0199a1b2-0000-7000-8000-000000000001",
    });
  });

  it("turns a non-JSON error body into a generic error", async () => {
    fetchMock.mockResolvedValue(
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
  });

  it("turns a JSON body that is not an object into a generic error", async () => {
    fetchMock.mockResolvedValue(jsonResponse("nope", 500));
    await expect(apiRequest("/api/x")).rejects.toMatchObject({
      code: null,
      correlationId: null,
      message: strings.errors.generic,
    });
  });

  it("turns a network failure into a network error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(apiRequest("/api/x")).rejects.toMatchObject({
      status: 0,
      message: strings.errors.network,
    });
  });

  it("rethrows the signal's own abort reason", async () => {
    const controller = new AbortController();
    const reason = new Error("user left the page");
    controller.abort(reason);
    fetchMock.mockImplementation(async (_path, init) => {
      throw init?.signal?.reason;
    });
    await expect(
      apiRequest("/api/x", { signal: controller.signal }),
    ).rejects.toBe(reason);
  });

  it("reports a timeout as the timeout, not a network failure", async () => {
    const controller = new AbortController();
    const timeout = new DOMException("signal timed out", "TimeoutError");
    controller.abort(timeout);
    fetchMock.mockRejectedValue(timeout);
    await expect(
      apiRequest("/api/x", { signal: controller.signal }),
    ).rejects.toBe(timeout);
  });

  it.each([
    ["an empty", ""],
    ["a non-JSON", "<html>ok</html>"],
  ])("turns %s success body into a generic error", async (_, body) => {
    fetchMock.mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "X-Correlation-Id": "c-5" },
      }),
    );
    await expect(apiRequest("/api/x")).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      code: null,
      message: strings.errors.generic,
      correlationId: "c-5",
    });
  });

  it("stops notifying after unsubscribe", async () => {
    const { listener, stop } = listen(SESSION_EXPIRED);
    stop();
    fetchMock.mockResolvedValue(jsonResponse({}, 401));
    await expect(apiRequest("/api/me")).rejects.toBeInstanceOf(ApiError);
    expect(listener).not.toHaveBeenCalled();
  });
});
