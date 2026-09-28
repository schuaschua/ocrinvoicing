import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setUploadToken } from "@/api";
import { LINK_TIMEOUT_MS, getLink } from "@/api/link";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();
// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";

function ok(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200 });
}

/** A fetch that never answers, and rejects like the browser's when aborted. */
function hanging(_path: unknown, init?: RequestInit): Promise<Response> {
  return new Promise((_, reject) => {
    init?.signal?.addEventListener("abort", () => reject(init.signal?.reason));
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  setUploadToken(null);
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("1.7 link API", () => {
  it("sends the token as X-Upload-Token on every call, never in the URL", async () => {
    fetchMock.mockImplementation(async () =>
      ok({ supplier_name: "Lim Leather Trading" }),
    );
    setUploadToken(TOKEN);
    await expect(getLink()).resolves.toEqual({
      supplier_name: "Lim Leather Trading",
    });
    await getLink();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [path, init] of fetchMock.mock.calls) {
      expect(path).toBe("/api/link");
      expect(String(path)).not.toContain(TOKEN);
      expect(init?.headers).toMatchObject({ "X-Upload-Token": TOKEN });
    }
  });

  it("trims the supplier name", async () => {
    fetchMock.mockResolvedValue(
      ok({ supplier_name: "  Lim Leather Trading " }),
    );
    await expect(getLink()).resolves.toEqual({
      supplier_name: "Lim Leather Trading",
    });
  });

  it.each([
    ["a missing", {}],
    ["a non-string", { supplier_name: 42 }],
    ["a blank", { supplier_name: "   " }],
    ["a null body's", null],
  ])("treats %s supplier name as a generic error", async (_, body) => {
    fetchMock.mockResolvedValue(ok(body));
    await expect(getLink()).rejects.toMatchObject({
      name: "ApiError",
      status: 200,
      code: null,
      message: strings.errors.generic,
    });
  });

  it("gives up after 20 s with a timeout", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(hanging);
    const result = getLink().catch((error: unknown) => error);
    await vi.advanceTimersByTimeAsync(LINK_TIMEOUT_MS);
    expect(LINK_TIMEOUT_MS).toBe(20_000);
    expect(await result).toMatchObject({ name: "TimeoutError" });
  });

  it("passes the caller's abort through", async () => {
    fetchMock.mockImplementation(hanging);
    const controller = new AbortController();
    const reason = new Error("left the page");
    const result = getLink(controller.signal).catch((error: unknown) => error);
    controller.abort(reason);
    expect(await result).toBe(reason);
  });

  it("sends no token header before one is set", async () => {
    fetchMock.mockResolvedValue(ok({ supplier_name: "Lim" }));
    await getLink();
    expect(fetchMock.mock.calls[0]![1]?.headers).not.toHaveProperty(
      "X-Upload-Token",
    );
  });
});
