import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OFFLINE, SESSION_EXPIRED, apiEvents } from "@/api";
import { ME_TIMEOUT_MS } from "@/api/me";
import { App } from "@/App";
import { signInHref } from "@/screens/SignedOut";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function signedInAs(...roles: string[]) {
  fetchMock.mockImplementation(async () =>
    answer(200, { name: "Priya Tan", roles }),
  );
}

function openAt(path: string) {
  window.history.replaceState(null, "", path);
}

function navLinks(): string[] {
  const [nav] = screen.getAllByRole("navigation", { name: strings.nav.label });
  return within(nav!)
    .getAllByRole("link")
    .map((link) => link.textContent ?? "");
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  openAt("/");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("1.4 app shell", () => {
  it("shows the Babaloo text header and a main region", () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => {}));
    render(<App />);
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

describe("2.7 staff sign in and see only their surfaces", () => {
  it("asks /api/me who is signed in, as an XHR the platform answers with 401", async () => {
    signedInAs("admin");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Admin queue" });
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/me");
    expect(init?.headers).toMatchObject({
      "X-Requested-With": "XMLHttpRequest",
    });
  });

  it("lands an admin and finance user on the admin queue with the union of surfaces", async () => {
    signedInAs("finance", "admin");
    render(<App />);
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Admin queue",
    });
    expect(window.location.pathname).toBe("/queue");
    expect(document.title).toBe("Admin queue – Babaloo");
    expect(heading).toHaveFocus();
    expect(navLinks()).toEqual([
      "Admin queue",
      "Invoices",
      "Overdue POs",
      "Suppliers",
      "Price comparison",
      "Finance month",
    ]);
    expect(screen.getByRole("link", { name: "Admin queue" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    // No alert on a normal landing.
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("shows both roles' surfaces for admin and goods_in, landing on the admin home", async () => {
    signedInAs("goods_in", "admin");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Admin queue" });
    expect(navLinks()).toEqual([
      "Admin queue",
      "Goods-in scan",
      "Invoices",
      "Overdue POs",
    ]);
  });

  it.each([
    ["finance", "/finance-month", "Finance month"],
    ["procurement", "/suppliers", "Suppliers"],
    ["management", "/watchlist", "Watchlist"],
    ["goods_in", "/goods-in", "Goods-in scan"],
  ])("lands %s on %s", async (role, path, title) => {
    signedInAs(role);
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: title });
    expect(window.location.pathname).toBe(path);
  });

  it("redirects a route outside the user's roles home, with an inline alert", async () => {
    openAt("/queue");
    signedInAs("goods_in", "auditor");
    render(<App />);
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Goods-in scan",
    });
    expect(window.location.pathname).toBe("/goods-in");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "You don't have access to that page.",
    );
    expect(heading).toHaveFocus();
    expect(navLinks()).toEqual(["Goods-in scan"]);
  });

  it("opens a deep link the user may use, and sends unknown paths home without an alert", async () => {
    openAt("/suppliers/0199a1b2-0000-7000-8000-000000000009");
    signedInAs("procurement");
    const { unmount } = render(<App />);
    await screen.findByRole("heading", {
      level: 1,
      name: "Supplier scorecard",
    });
    expect(document.title).toBe("Supplier scorecard – Babaloo");
    // Reached from Suppliers: that link is the current section.
    expect(screen.getByRole("link", { name: "Suppliers" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    unmount();

    openAt("/no-such-page");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Suppliers" });
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("moves between pages from the sidebar: new title, focus on the h1, alert gone", async () => {
    openAt("/queue");
    signedInAs("finance");
    render(<App />);
    await screen.findByRole("alert", {}, { timeout: 2000 });
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(strings.notAllowed),
    );

    fireEvent.click(screen.getByRole("link", { name: "Invoices" }));
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Invoices",
    });
    expect(window.location.pathname).toBe("/invoices");
    expect(document.title).toBe("Invoices – Babaloo");
    expect(heading).toHaveFocus();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();

    // Back returns to the previous page.
    act(() => {
      window.history.back();
    });
    await waitFor(() =>
      expect(window.location.pathname).toBe("/finance-month"),
    );
  });

  it("leaves a modified click to the browser", async () => {
    signedInAs("finance");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Finance month" });
    fireEvent.click(screen.getByRole("link", { name: "Invoices" }), {
      ctrlKey: true,
    });
    expect(window.location.pathname).toBe("/finance-month");
  });

  it("shows the no-access page, with no sidebar, to a user with no app role", async () => {
    signedInAs("auditor");
    render(<App />);
    await screen.findByRole("heading", {
      level: 1,
      name: strings.noAccess.heading,
    });
    expect(document.title).toBe("No access yet – Babaloo");
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("button", { name: strings.nav.menu })).toBeNull();
  });

  it("opens the sidebar as a Sheet from Menu below 1024px and closes it on navigation", async () => {
    signedInAs("management");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Watchlist" });
    const menu = screen.getByRole("button", { name: strings.nav.menu });
    expect(menu).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(menu);
    const sheet = screen.getByRole("dialog", { name: "Babaloo" });
    expect(menu).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(within(sheet).getByRole("link", { name: "Suppliers" }));
    await screen.findByRole("heading", { level: 1, name: "Suppliers" });
    expect(screen.queryByRole("dialog")).toBeNull();

    // Esc (the dialog's cancel event) and the Close button also close it.
    fireEvent.click(menu);
    fireEvent(
      screen.getByRole("dialog", { name: "Babaloo" }),
      new Event("cancel", { cancelable: true }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(menu);
    fireEvent.click(screen.getByRole("button", { name: strings.nav.close }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the session-ended dialog, with a sign-in link back here, when /api/me answers 401", async () => {
    openAt("/invoices");
    fetchMock.mockResolvedValue(
      answer(401, {
        code: "UNAUTHENTICATED",
        message: strings.sessionExpired,
        correlation_id: "c-1",
      }),
    );
    render(<App />);
    const dialog = await screen.findByRole("dialog", {
      name: strings.sessionExpired,
    });
    expect(
      within(dialog).getByRole("link", { name: strings.signIn }),
    ).toHaveAttribute(
      "href",
      "/.auth/login/aad?post_login_redirect_uri=%2Finvoices",
    );
    // Behind it, the same message and link, for after Esc.
    expect(
      screen.getByRole("heading", { level: 1, name: strings.sessionExpired }),
    ).toBeInTheDocument();
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the session-ended dialog when any later call answers 401, closing the Sheet", async () => {
    signedInAs("admin");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Admin queue" });
    fireEvent.click(screen.getByRole("button", { name: strings.nav.menu }));
    act(() => {
      apiEvents.dispatchEvent(new Event(SESSION_EXPIRED));
    });
    const dialogs = screen.getAllByRole("dialog");
    expect(dialogs).toHaveLength(1);
    expect(dialogs[0]).toHaveAccessibleName(strings.sessionExpired);
  });

  it("shows the full-page offline notice with the working hours on 503 DB_OFFLINE", async () => {
    fetchMock.mockResolvedValueOnce(
      answer(503, {
        code: "DB_OFFLINE",
        message: "The database is offline. Try again later.",
        correlation_id: "c-2",
      }),
    );
    render(<App />);
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: strings.offlineHeading,
    });
    expect(heading).toHaveFocus();
    expect(document.title).toBe("System offline – Babaloo");
    // In the shell's persistent live region, so it is announced.
    expect(screen.getByTestId("shell-notice")).toHaveAttribute("role", "alert");
    expect(screen.getByTestId("shell-notice")).toHaveTextContent(
      "weekdays 9am–9pm",
    );
    expect(screen.queryByRole("navigation")).toBeNull();

    signedInAs("finance");
    fireEvent.click(
      screen.getByRole("button", { name: strings.errors.tryAgain }),
    );
    await screen.findByRole("heading", { level: 1, name: "Finance month" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("switches to the offline notice when a later call answers DB_OFFLINE", async () => {
    signedInAs("finance");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Finance month" });
    act(() => {
      apiEvents.dispatchEvent(new Event(OFFLINE));
    });
    expect(
      screen.getByRole("heading", { level: 1, name: strings.offlineHeading }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("shows a retryable error when /api/me can't be reached", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<App />);
    await screen.findByRole("heading", {
      level: 1,
      name: strings.errors.network,
    });
    fetchMock.mockResolvedValueOnce(answer(500, { code: "INTERNAL_ERROR" }));
    fireEvent.click(
      screen.getByRole("button", { name: strings.errors.tryAgain }),
    );
    await screen.findByRole("heading", {
      level: 1,
      name: strings.errors.generic,
    });
  });

  it("shows skeleton rows, then Waking up after 3 s, until /api/me answers", async () => {
    vi.useFakeTimers();
    let respond: (response: Response) => void = () => {};
    fetchMock.mockReturnValue(
      new Promise<Response>((resolve) => {
        respond = resolve;
      }),
    );
    render(<App />);
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    expect(document.title).toBe("Loading – Babaloo");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();

    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waking up, one moment…",
    );

    await act(async () => {
      respond(answer(200, { name: "Siti", roles: ["finance"] }));
    });
    expect(
      screen.getByRole("heading", { level: 1, name: "Finance month" }),
    ).toBeInTheDocument();
  });

  it("stops listening when it unmounts", () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => {}));
    const { unmount } = render(<App />);
    unmount();
    expect(() =>
      apiEvents.dispatchEvent(new Event(SESSION_EXPIRED)),
    ).not.toThrow();
  });

  it("shows the not-allowed alert once: not after Back or a reload", async () => {
    openAt("/queue");
    signedInAs("goods_in");
    const { unmount } = render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Goods-in scan" });
    const notice = screen.getByTestId("shell-notice");
    expect(notice).toHaveTextContent(strings.notAllowed);
    // The live region was in the page before the text arrived.
    expect(notice).toBe(screen.getByRole("alert"));

    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(screen.getByTestId("shell-notice")).toBeEmptyDOMElement();
    unmount();

    // A reload of the landing page shows no alert.
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Goods-in scan" });
    expect(screen.getByTestId("shell-notice")).toBeEmptyDOMElement();
  });

  it("keeps a sign-in path after a later 401's dialog is closed with Esc", async () => {
    openAt("/invoices");
    signedInAs("finance");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Invoices" });
    act(() => {
      apiEvents.dispatchEvent(new Event(SESSION_EXPIRED));
    });
    fireEvent(
      screen.getByRole("dialog", { name: strings.sessionExpired }),
      new Event("cancel", { cancelable: true }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    const heading = screen.getByRole("heading", {
      level: 1,
      name: strings.sessionExpired,
    });
    expect(heading).toHaveFocus();
    expect(document.title).toBe(`${strings.sessionExpired} – Babaloo`);
    expect(screen.getByRole("link", { name: strings.signIn })).toHaveAttribute(
      "href",
      "/.auth/login/aad?post_login_redirect_uri=%2Finvoices",
    );
    expect(screen.queryByRole("navigation")).toBeNull();
  });

  it("follows a native close of the dialog that sends no cancel event", async () => {
    signedInAs("management");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Watchlist" });
    fireEvent.click(screen.getByRole("button", { name: strings.nav.menu }));
    fireEvent(screen.getByRole("dialog"), new Event("close"));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      screen.getByRole("button", { name: strings.nav.menu }),
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the Sheet when the window widens to 1024px or more", async () => {
    const listeners: ((event: MediaQueryListEvent) => void)[] = [];
    vi.stubGlobal(
      "matchMedia",
      vi.fn((query: string) => ({
        media: query,
        matches: false,
        addEventListener: (
          _type: string,
          listener: (event: MediaQueryListEvent) => void,
        ) => listeners.push(listener),
        removeEventListener: vi.fn(),
      })),
    );
    signedInAs("management");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Watchlist" });
    expect(window.matchMedia).toHaveBeenCalledWith("(min-width: 1024px)");
    fireEvent.click(screen.getByRole("button", { name: strings.nav.menu }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() => {
      listeners.forEach((listener) =>
        listener({ matches: false } as MediaQueryListEvent),
      );
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() => {
      listeners.forEach((listener) =>
        listener({ matches: true } as MediaQueryListEvent),
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the signed-in name and a Sign out link in the header", async () => {
    signedInAs("finance");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Finance month" });
    const banner = screen.getByRole("banner");
    expect(banner).toHaveTextContent("Priya Tan");
    expect(
      within(banner).getByRole("link", { name: strings.signOut }),
    ).toHaveAttribute("href", "/.auth/logout");
  });

  it("returns to this origin only after sign-in", () => {
    expect(signInHref("/invoices?x=1")).toBe(
      "/.auth/login/aad?post_login_redirect_uri=%2Finvoices%3Fx%3D1",
    );
    for (const outside of [
      "//evil.example/x",
      "/\\evil.example",
      "https://evil.example",
      "",
    ]) {
      expect(signInHref(outside)).toBe(
        "/.auth/login/aad?post_login_redirect_uri=%2F",
      );
    }
  });

  it("treats a sign-in check that times out as a network failure, and retries", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementationOnce(
      (_path, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(init.signal?.reason),
          );
        }),
    );
    render(<App />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ME_TIMEOUT_MS);
    });
    expect(
      screen.getByRole("heading", { level: 1, name: strings.errors.network }),
    ).toBeInTheDocument();

    signedInAs("finance");
    fireEvent.click(
      screen.getByRole("button", { name: strings.errors.tryAgain }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(
      screen.getByRole("heading", { level: 1, name: "Finance month" }),
    ).toBeInTheDocument();
  });
});
