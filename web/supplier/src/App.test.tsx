import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, setUploadToken } from "@/api";
import { App } from "@/App";
import { strings } from "@/strings";
import { FakeXhr } from "@/test/fakeXhr";

describe("1.4 app shell", () => {
  it("shows the Babaloo text header and a main region", () => {
    render(<App token={null} />);
    expect(screen.getByRole("banner")).toHaveTextContent("Babaloo");
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("declares English and loads no inline script", () => {
    const html = readFileSync(
      resolve(import.meta.dirname, "../index.html"),
      "utf8",
    );
    expect(html).toMatch(/<html lang="en">/);
    // CSP is 'self' only (security.md rule 25): every script has a src.
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);
  });
});

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";
const fetchMock = vi.fn<typeof fetch>();

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const NOT_VALID = {
  code: "LINK_NOT_VALID",
  message: "This link isn't working. Please contact your buyer at Babaloo.",
  correlation_id: "0199a1b2-0000-7000-8000-000000000001",
};

describe("1.7 supplier opens their link", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    setUploadToken(null);
    vi.useRealTimers();
    vi.unstubAllGlobals();
    localStorage.clear();
    sessionStorage.clear();
  });

  it("shows Upload home for a valid link, sending the token as a header", async () => {
    fetchMock.mockResolvedValue(
      answer(200, { supplier_name: "Lim Leather Trading" }),
    );
    render(<App token={TOKEN} />);
    expect(
      await screen.findByRole("heading", {
        name: "Uploading for Lim Leather Trading",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Take photo" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose file" })).toBeVisible();

    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/link");
    expect(init?.headers).toMatchObject({ "X-Upload-Token": TOKEN });
    // Never written to storage.
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("shows Link not working for a revoked or unknown link", async () => {
    fetchMock.mockResolvedValue(answer(401, NOT_VALID));
    render(<App token={TOKEN} />);
    expect(
      await screen.findByRole("heading", { name: "This link isn't working." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Please contact your buyer at Babaloo."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();

    // The refused token is not sent again.
    fetchMock.mockResolvedValue(answer(200, {}));
    await apiRequest("/api/health");
    expect(fetchMock.mock.calls[1]![1]?.headers).not.toHaveProperty(
      "X-Upload-Token",
    );
  });

  it("shows the retryable error when the link check takes over 20 s", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(
      (_path, init) =>
        new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal?.reason),
          );
        }),
    );
    render(<App token={TOKEN} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20_000);
    });
    expect(
      screen.getByRole("heading", { name: strings.errors.generic }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(screen.queryByTestId("skeleton")).toBeNull();
  });

  it.each([
    ["no", {}],
    ["a non-string", { supplier_name: 7 }],
    ["a blank", { supplier_name: " " }],
  ])("shows the retryable error for %s supplier name", async (_, body) => {
    fetchMock.mockResolvedValue(answer(200, body));
    render(<App token={TOKEN} />);
    expect(
      await screen.findByRole("heading", { name: strings.errors.generic }),
    ).toBeInTheDocument();
  });

  it("shows Link not working without calling the server when there is no token", () => {
    render(<App token={null} />);
    expect(
      screen.getByRole("heading", { name: "This link isn't working." }),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows a retryable error, not Link not working, when the service is down", async () => {
    fetchMock
      .mockResolvedValueOnce(
        answer(503, {
          code: "SERVICE_UNAVAILABLE",
          message: "The service is busy. Try again in a moment.",
          correlation_id: "c-1",
        }),
      )
      .mockResolvedValueOnce(
        answer(200, { supplier_name: "Lim Leather Trading" }),
      );
    render(<App token={TOKEN} />);
    // Our own copy, never the server's message.
    expect(
      await screen.findByRole("heading", { name: strings.errors.generic }),
    ).toBeInTheDocument();
    expect(screen.queryByText("This link isn't working.")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByRole("heading", {
        name: "Uploading for Lim Leather Trading",
      }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("says to check the connection when the network fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<App token={TOKEN} />);
    expect(
      await screen.findByRole("heading", { name: strings.errors.network }),
    ).toBeInTheDocument();
  });

  it("shows the skeleton, then Waking up after 3 s, until the answer comes", async () => {
    vi.useFakeTimers();
    let respond: (response: Response) => void = () => {};
    fetchMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        respond = resolve;
      }),
    );
    render(<App token={TOKEN} />);
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waking up, one moment…",
    );

    await act(async () => {
      respond(answer(200, { supplier_name: "Lim Leather Trading" }));
    });
    expect(
      screen.getByRole("heading", {
        name: "Uploading for Lim Leather Trading",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("skeleton")).toBeNull();
  });
});

describe("1.8 supplier sends a photo or PDF and gets a reference", () => {
  const KEY_PATTERN =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(
      answer(200, { supplier_name: "Lim Leather Trading" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    FakeXhr.reset();
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
  });

  afterEach(() => {
    setUploadToken(null);
    vi.unstubAllGlobals();
  });

  async function home() {
    render(<App token={TOKEN} />);
    await screen.findByRole("heading", {
      name: "Uploading for Lim Leather Trading",
    });
  }

  function choose(name = "inv.jpg", lastModified = 1_790_000_000_000) {
    const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], name, {
      type: "image/jpeg",
      lastModified,
    });
    fireEvent.change(screen.getByTestId("choose-file-input"), {
      target: { files: [file] },
    });
    return file;
  }

  it("goes Upload home, Check & send, Received, and back with Upload another", async () => {
    await home();
    const file = choose();
    expect(screen.getByRole("heading", { name: "Check & send" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const xhr = FakeXhr.last();
    expect(xhr.body).toBe(file);
    expect(xhr.headers["X-Upload-Token"]).toBe(TOKEN);
    expect(xhr.headers["Idempotency-Key"]).toMatch(KEY_PATTERN);
    await act(async () =>
      xhr.respond(200, {
        invoice_id: "0199a1b2-0000-7000-8000-000000000001",
        reference: "R-7Q4KXM2D",
      }),
    );

    expect(await screen.findByText("R-7Q4KXM2D")).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent(
      /Received\.\s*Reference R-7Q4KXM2D/,
    );

    fireEvent.click(screen.getByRole("button", { name: "Upload another" }));
    expect(
      screen.getByRole("heading", {
        name: "Uploading for Lim Leather Trading",
      }),
    ).toHaveFocus();
    // The link is not checked again.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("gives each chosen file its own key, and a retry the same one", async () => {
    await home();
    choose();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => FakeXhr.last().fail());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const [first, retry] = FakeXhr.requests;
    expect(retry!.headers["Idempotency-Key"]).toBe(
      first!.headers["Idempotency-Key"],
    );

    await act(async () => retry!.fail());
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    choose("other.jpg");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["Idempotency-Key"]).not.toBe(
      first!.headers["Idempotency-Key"],
    );
  });

  it("reuses the key when the same file is chosen again after Couldn't send", async () => {
    await home();
    choose();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => FakeXhr.last().fail());
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    // The same file (a new File object: same name, size and time).
    choose();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const [first, again] = FakeXhr.requests;
    expect(again!.headers["Idempotency-Key"]).toBe(
      first!.headers["Idempotency-Key"],
    );

    // The same name with another time is another file.
    await act(async () => again!.fail());
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    choose("inv.jpg", 1_790_000_000_001);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["Idempotency-Key"]).not.toBe(
      first!.headers["Idempotency-Key"],
    );
  });

  it("shows Link not working when the link stops working mid-flow", async () => {
    await home();
    choose();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () =>
      FakeXhr.last().respond(401, {
        code: "LINK_NOT_VALID",
        message: NOT_VALID.message,
      }),
    );
    expect(
      screen.getByRole("heading", { name: "This link isn't working." }),
    ).toBeInTheDocument();
    // The refused token is not sent again.
    await apiRequest("/api/health").catch(() => undefined);
    expect(fetchMock.mock.calls.at(-1)![1]?.headers).not.toHaveProperty(
      "X-Upload-Token",
    );
  });
});
