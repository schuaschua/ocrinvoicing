import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest, setUploadToken } from "@/api";
import { App } from "@/App";
import { strings } from "@/strings";
import { FakeXhr } from "@/test/fakeXhr";

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";
const fetchMock = vi.fn<typeof fetch>();

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const LINK_OK = { supplier_name: "Lim Leather Trading" };
const NOT_VALID = {
  code: "LINK_NOT_VALID",
  message: "This link isn't working. Please contact your buyer at Babaloo.",
  correlation_id: "0199a1b2-0000-7000-8000-000000000001",
};

async function home() {
  return screen.findByRole("heading", {
    name: "Uploading for Lim Leather Trading",
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
  localStorage.clear();
  sessionStorage.clear();
});

describe("1.4 app shell", () => {
  it("shows the Babaloo header, declares English and loads no inline script", () => {
    render(<App token={null} />);
    expect(screen.getByRole("banner")).toHaveTextContent("Babaloo");
    expect(screen.getByRole("main")).toBeInTheDocument();
    const html = readFileSync(
      resolve(import.meta.dirname, "../index.html"),
      "utf8",
    );
    expect(html).toMatch(/<html lang="en">/);
    // CSP is 'self' only (security.md rule 25): every script has a src.
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);
  });
});

describe("1.7 supplier opens their link", () => {
  it("shows Upload home for a valid link, sending the token only as a header", async () => {
    fetchMock.mockResolvedValue(answer(200, LINK_OK));
    render(<App token={TOKEN} />);
    const heading = await home();
    await waitFor(() => expect(heading).toHaveFocus());
    expect(heading.querySelector("strong")).toHaveTextContent(
      "Lim Leather Trading",
    );
    expect(document.title).toBe("Upload – Babaloo");
    expect(screen.getByRole("button", { name: "Take photo" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose file" })).toBeVisible();

    const [path, init] = fetchMock.mock.calls[0]!;
    // Never in the URL, never stored.
    expect(path).toBe("/api/link");
    expect(init?.headers).toMatchObject({ "X-Upload-Token": TOKEN });
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });

  it("shows Link not working with no token, or a refused one, and stops sending it", async () => {
    const { unmount } = render(<App token={null} />);
    expect(
      screen.getByRole("heading", { name: "This link isn't working." }),
    ).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
    unmount();

    fetchMock.mockResolvedValue(answer(401, NOT_VALID));
    render(<App token={TOKEN} />);
    expect(
      await screen.findByRole("heading", { name: "This link isn't working." }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Please contact your buyer at Babaloo."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.title).toBe("Link not working – Babaloo");

    fetchMock.mockResolvedValue(answer(200, {}));
    await apiRequest("/api/health");
    expect(fetchMock.mock.calls[1]![1]?.headers).not.toHaveProperty(
      "X-Upload-Token",
    );
  });

  it("shows a retryable error, in our own words, until the link check works", async () => {
    fetchMock
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        answer(503, {
          code: "SERVICE_UNAVAILABLE",
          message: "The service is busy. Try again in a moment.",
        }),
      )
      .mockResolvedValueOnce(answer(200, { supplier_name: " " }))
      .mockResolvedValueOnce(answer(200, LINK_OK));
    render(<App token={TOKEN} />);
    const error = await screen.findByRole("heading", {
      name: strings.errors.network,
    });
    await waitFor(() => expect(error).toHaveFocus());
    expect(document.title).toBe(`${strings.errors.network} – Babaloo`);

    for (let n = 0; n < 2; n++) {
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      expect(
        await screen.findByRole("heading", { name: strings.errors.generic }),
      ).toBeInTheDocument();
      expect(screen.queryByText("This link isn't working.")).toBeNull();
    }

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await home()).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("shows the skeleton, then Waking up after 3 s, then the retryable error at 20 s", async () => {
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
    expect(screen.getByTestId("skeleton")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(document.title).toBe("Loading – Babaloo");

    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waking up, one moment…",
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(17_000);
    });
    expect(
      screen.getByRole("heading", { name: strings.errors.generic }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
    expect(screen.queryByTestId("skeleton")).toBeNull();
  });
});

describe("1.8 supplier sends a photo or PDF and gets a reference", () => {
  const KEY_PATTERN =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

  beforeEach(() => {
    fetchMock.mockResolvedValue(answer(200, LINK_OK));
    FakeXhr.reset();
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
  });

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

  const send = () =>
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
  const chooseAnother = () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );

  it("goes Upload home, Check & send, Received, and back with Upload another", async () => {
    render(<App token={TOKEN} />);
    await home();
    const file = choose();
    expect(screen.getByRole("heading", { name: "Check & send" })).toHaveFocus();
    expect(screen.getByText(/Photo:/)).toHaveTextContent(
      "Photo: inv.jpg (1 KB)",
    );

    send();
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

    const reference = await screen.findByText("R-7Q4KXM2D");
    await waitFor(() => expect(reference).toHaveFocus());
    expect(screen.getByRole("status")).toHaveTextContent(
      /Received\.\s*Reference R-7Q4KXM2D/,
    );
    expect(document.title).toBe("Received – Babaloo");

    fireEvent.click(screen.getByRole("button", { name: "Upload another" }));
    const again = await home();
    await waitFor(() => expect(again).toHaveFocus());
    // The link is not checked again.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps one key per file across retries, and shows Link not working when the link stops", async () => {
    render(<App token={TOKEN} />);
    await home();
    choose();
    send();
    await act(async () => FakeXhr.last().fail());
    // Send again reuses the key.
    send();
    await act(async () => FakeXhr.last().fail());
    // The same file chosen again (a new File: same name, size and time) too.
    chooseAnother();
    choose();
    send();
    await act(async () => FakeXhr.last().fail());
    // Another file, or the same name with another time, gets a new key.
    chooseAnother();
    choose("inv.jpg", 1_790_000_000_001);
    send();
    const keys = FakeXhr.requests.map((xhr) => xhr.headers["Idempotency-Key"]);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).toBe(keys[0]);
    expect(keys[3]).not.toBe(keys[0]);

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
