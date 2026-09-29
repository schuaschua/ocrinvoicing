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
  it("shows the Babaloo header, declares English and loads no inline script", () => {
    fetchMock.mockReturnValue(new Promise<Response>(() => {}));
    render(<App />);
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

describe("2.7 staff sign in and see only their surfaces", () => {
  it("asks /api/me who is signed in, then lands an admin and finance user on the admin queue with the union of surfaces", async () => {
    signedInAs("finance", "admin", "auditor");
    render(<App />);
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Admin queue",
    });
    const [path, init] = fetchMock.mock.calls[0]!;
    expect(path).toBe("/api/me");
    // An XHR, so the platform answers 401 rather than redirecting.
    expect(init?.headers).toMatchObject({
      "X-Requested-With": "XMLHttpRequest",
    });
    expect(window.location.pathname).toBe("/queue");
    expect(document.title).toBe("Admin queue – Babaloo");
    await waitFor(() => expect(heading).toHaveFocus());
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
    const banner = screen.getByRole("banner");
    expect(banner).toHaveTextContent("Priya Tan");
    expect(
      within(banner).getByRole("link", { name: strings.signOut }),
    ).toHaveAttribute("href", "/.auth/logout");
  });

  it("lands each role on its own page, and shows no-access to a user with no app role", async () => {
    for (const [roles, path, title, links] of [
      [["goods_in", "admin"], "/queue", "Admin queue", 4],
      [["finance"], "/finance-month", "Finance month", 5],
      [["procurement"], "/suppliers", "Suppliers", 4],
      [["management"], "/watchlist", "Watchlist", 3],
      [["goods_in"], "/goods-in", "Goods-in scan", 1],
    ] as const) {
      openAt("/");
      signedInAs(...roles);
      const { unmount } = render(<App />);
      await screen.findByRole("heading", { level: 1, name: title });
      expect(window.location.pathname).toBe(path);
      expect(navLinks()).toHaveLength(links);
      unmount();
    }

    openAt("/");
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

  it("redirects a route outside the user's roles home, with an alert shown once", async () => {
    openAt("/queue");
    signedInAs("goods_in");
    const { unmount } = render(<App />);
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Goods-in scan",
    });
    expect(window.location.pathname).toBe("/goods-in");
    await waitFor(() => expect(heading).toHaveFocus());
    const notice = screen.getByTestId("shell-notice");
    expect(notice).toHaveTextContent("You don't have access to that page.");
    // The live region was in the page before the text arrived.
    expect(notice).toBe(screen.getByRole("alert"));
    expect(navLinks()).toEqual(["Goods-in scan"]);

    // Not after Back, nor after a reload.
    act(() => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    expect(screen.getByTestId("shell-notice")).toBeEmptyDOMElement();
    unmount();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Goods-in scan" });
    expect(screen.getByTestId("shell-notice")).toBeEmptyDOMElement();
  });

  it("opens deep links, sends unknown paths home, and moves between pages from the sidebar", async () => {
    openAt("/suppliers/0199a1b2-0000-7000-8000-000000000009");
    signedInAs("procurement", "finance");
    const { unmount } = render(<App />);
    await screen.findByRole("heading", {
      level: 1,
      name: "Supplier scorecard",
    });
    // Reached from Suppliers: that link is the current section.
    expect(screen.getByRole("link", { name: "Suppliers" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    unmount();

    openAt("/no-such-page");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Finance month" });
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();

    // A modified click is left to the browser.
    fireEvent.click(screen.getByRole("link", { name: "Invoices" }), {
      ctrlKey: true,
    });
    expect(window.location.pathname).toBe("/finance-month");

    fireEvent.click(screen.getByRole("link", { name: "Invoices" }));
    const heading = await screen.findByRole("heading", {
      level: 1,
      name: "Invoices",
    });
    expect(window.location.pathname).toBe("/invoices");
    expect(document.title).toBe("Invoices – Babaloo");
    await waitFor(() => expect(heading).toHaveFocus());

    act(() => {
      window.history.back();
    });
    await waitFor(() =>
      expect(window.location.pathname).toBe("/finance-month"),
    );
  });

  it("opens the sidebar as a Sheet from Menu, closing it on navigation, Esc, Close and widening", async () => {
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
    const menu = screen.getByRole("button", { name: strings.nav.menu });
    expect(menu).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(menu);
    const sheet = screen.getByRole("dialog", { name: "Babaloo" });
    expect(menu).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(within(sheet).getByRole("link", { name: "Suppliers" }));
    await screen.findByRole("heading", { level: 1, name: "Suppliers" });
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(menu);
    fireEvent(
      screen.getByRole("dialog", { name: "Babaloo" }),
      new Event("cancel", { cancelable: true }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(menu);
    fireEvent.click(screen.getByRole("button", { name: strings.nav.close }));
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(menu);
    fireEvent(screen.getByRole("dialog"), new Event("close"));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(menu);
    act(() => {
      listeners.forEach((listener) =>
        listener({ matches: true } as MediaQueryListEvent),
      );
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows the session-ended dialog on a 401, with a sign-in link back here only", async () => {
    expect(signInHref("/invoices?x=1")).toBe(
      "/.auth/login/aad?post_login_redirect_uri=%2Finvoices%3Fx%3D1",
    );
    for (const outside of ["//evil.example/x", "/\\evil.example", ""]) {
      expect(signInHref(outside)).toBe(
        "/.auth/login/aad?post_login_redirect_uri=%2F",
      );
    }

    openAt("/invoices");
    fetchMock.mockResolvedValueOnce(
      answer(401, {
        code: "UNAUTHENTICATED",
        message: strings.sessionExpired,
        correlation_id: "c-1",
      }),
    );
    const { unmount } = render(<App />);
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
    fireEvent(dialog, new Event("cancel", { cancelable: true }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      screen.getByRole("heading", { level: 1, name: strings.sessionExpired }),
    ).toHaveFocus();
    expect(screen.getByRole("link", { name: strings.signIn })).toBeVisible();
    expect(screen.queryByRole("navigation")).toBeNull();
    unmount();

    // A later call's 401 closes the Sheet: one dialog at a time.
    openAt("/");
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

  it("waits, then shows the retryable errors and the offline notice until /api/me answers", async () => {
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
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    expect(document.title).toBe("Loading – Babaloo");
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Waking up, one moment…",
    );
    // A sign-in check that times out reads as a network failure.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ME_TIMEOUT_MS);
    });
    expect(
      screen.getByRole("heading", { level: 1, name: strings.errors.network }),
    ).toBeInTheDocument();

    const tryAgain = async () => {
      fireEvent.click(
        screen.getByRole("button", { name: strings.errors.tryAgain }),
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
    };

    fetchMock.mockResolvedValueOnce(answer(500, { code: "INTERNAL_ERROR" }));
    await tryAgain();
    expect(
      screen.getByRole("heading", { level: 1, name: strings.errors.generic }),
    ).toBeInTheDocument();

    fetchMock.mockResolvedValueOnce(
      answer(503, {
        code: "DB_OFFLINE",
        message: "The database is offline. Try again later.",
      }),
    );
    await tryAgain();
    expect(
      screen.getByRole("heading", { level: 1, name: strings.offlineHeading }),
    ).toHaveFocus();
    expect(document.title).toBe("System offline – Babaloo");
    // In the shell's persistent live region, so it is announced.
    expect(screen.getByRole("alert")).toHaveTextContent("weekdays 9am–9pm");
    expect(screen.queryByRole("navigation")).toBeNull();

    signedInAs("finance");
    await tryAgain();
    expect(
      screen.getByRole("heading", { level: 1, name: "Finance month" }),
    ).toBeInTheDocument();

    // A later call's DB_OFFLINE switches to the notice too.
    act(() => {
      apiEvents.dispatchEvent(new Event(OFFLINE));
    });
    expect(
      screen.getByRole("heading", { level: 1, name: strings.offlineHeading }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).toBeNull();
  });
});
