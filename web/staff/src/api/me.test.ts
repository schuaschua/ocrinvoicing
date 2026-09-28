import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api";
import { ME_TIMEOUT_MS, getMe } from "@/api/me";

const fetchMock = vi.fn<typeof fetch>();

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("2.7 GET /api/me", () => {
  it("returns the name and the known roles in landing order", async () => {
    fetchMock.mockResolvedValue(
      answer(200, { name: "Priya", roles: ["goods_in", "auditor", "admin"] }),
    );
    await expect(getMe()).resolves.toEqual({
      name: "Priya",
      roles: ["admin", "goods_in"],
    });
  });

  it("treats an answer without a roles list as broken", async () => {
    fetchMock.mockResolvedValue(answer(200, { name: "Priya" }));
    await expect(getMe()).rejects.toBeInstanceOf(ApiError);
  });

  it("shows no name when the name isn't text", async () => {
    fetchMock.mockResolvedValue(answer(200, { name: 5, roles: [] }));
    await expect(getMe()).resolves.toEqual({ name: "", roles: [] });
  });

  it("gives up after the timeout", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_path, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal?.reason),
          );
        }),
    );
    const pending = getMe();
    const settled = expect(pending).rejects.toMatchObject({
      name: "TimeoutError",
    });
    await vi.advanceTimersByTimeAsync(ME_TIMEOUT_MS);
    await settled;
  });

  it("stops when the caller aborts", async () => {
    const controller = new AbortController();
    controller.abort(new DOMException("gone", "AbortError"));
    fetchMock.mockImplementation(async (_path, init) => {
      throw init?.signal?.reason;
    });
    await expect(getMe(controller.signal)).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});
