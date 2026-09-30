import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SESSION_EXPIRED, onApiEvent } from "@/api";
import { App } from "@/App";
import type { CheckResult } from "@/deviceCheck";
import { strings } from "@/strings";
import { FakeXhr } from "@/test/fakeXhr";

// The check itself is tested in web/supplier; here it answers as told ("skipped", as
// jsdom would, unless a step says otherwise).
const check = vi.hoisted(() => ({
  canCheck: vi.fn(() => true),
  checkFile: vi.fn(),
}));
vi.mock("@/deviceCheck", () => check);

const fetchMock = vi.fn<typeof fetch>();

function answer(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Synthetic deliveries (backend/seed/sim_purchasing.json).
const TODAY = {
  delivery_id: "01a0c450-aa80-72d5-bb5c-e21dfa7e05aa",
  po_number: "PO-45016",
  delivery_no: 1,
  delivery_date: "2026-09-29",
  supplier_name: "Synthetic Gamma Construction Materials",
};
const LATE = {
  delivery_id: "01a0c450-a2b0-75b9-9eac-12e4d657f199",
  po_number: "PO-45012",
  delivery_no: 2,
  delivery_date: "2026-09-14",
  supplier_name: "Synthetic Alpha Building Supplies",
};

/** A goods_in user; `deliveries` answers `GET /api/goods-in/deliveries[?q=]`. */
function goodsIn(deliveries: (url: string) => Response) {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    return url.startsWith("/api/goods-in/deliveries")
      ? deliveries(url)
      : answer(200, { name: "Rahman", roles: ["goods_in"] });
  });
}

function requested(): string[] {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) => url.startsWith("/api/goods-in/"));
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  FakeXhr.reset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  check.checkFile.mockResolvedValue({ kind: "skipped" } satisfies CheckResult);
  window.history.replaceState(null, "", "/goods-in");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("4.1 Goods-in scan", () => {
  it("lists today's deliveries, searches late ones, sends a photo against the chosen delivery once, and says when scanning is unavailable", async () => {
    const s = strings.goodsIn;
    goodsIn((url) =>
      answer(200, {
        today: "2026-09-29",
        items: url.includes("?q=") ? [TODAY, LATE] : [TODAY],
      }),
    );
    const { unmount } = render(<App />);

    // --- Open: today's deliveries, with PO, supplier and delivery number.
    await screen.findByRole("heading", { level: 2, name: s.today });
    expect(
      await screen.findByRole("button", { name: /PO 45016/ }),
    ).toHaveTextContent(
      "PO 45016Synthetic Gamma Construction MaterialsDelivery 1 · 2026-09-29",
    );
    expect(requested()).toEqual(["/api/goods-in/deliveries"]);

    // --- Search: under 2 characters is refused here; a PO prefix is searched.
    const box = screen.getByRole("searchbox", { name: s.searchLabel });
    fireEvent.change(box, { target: { value: " x " } });
    fireEvent.click(screen.getByRole("button", { name: s.search }));
    expect(screen.getByText(s.badSearch)).toHaveAttribute("role", "alert");
    expect(requested()).toHaveLength(1);
    fireEvent.change(box, { target: { value: "po-4501" } });
    fireEvent.click(screen.getByRole("button", { name: s.search }));
    await screen.findByRole("heading", { level: 2, name: s.results });
    expect(requested()).toEqual([
      "/api/goods-in/deliveries",
      "/api/goods-in/deliveries?q=po-4501",
    ]);
    expect(
      screen.getByRole("button", { name: s.showToday }),
    ).toBeInTheDocument();

    // --- Pick the late delivery and choose its photo.
    fireEvent.click(await screen.findByRole("button", { name: /PO 45012/ }));
    const scan = screen.getByRole("heading", {
      level: 1,
      name: "Scan the invoice for PO 45012",
    });
    await waitFor(() => expect(scan).toHaveFocus());
    const photo = new File([new Uint8Array(1500)], "invoice.jpg", {
      type: "image/jpeg",
    });
    fireEvent.change(screen.getByTestId("choose-file-input"), {
      target: { files: [photo] },
    });
    await screen.findByRole("heading", { level: 1, name: s.checkHeading });
    expect(screen.getByText(/PO 45012, Synthetic Alpha/)).toBeInTheDocument();

    // --- Send: the delivery in the path, never a supplier; the file as the body.
    // The check is skipped here (the server checks again).
    fireEvent.click(await screen.findByRole("button", { name: s.send }));
    const first = FakeXhr.last();
    expect(first.method).toBe("POST");
    expect(first.url).toBe(
      `/api/goods-in/deliveries/${LATE.delivery_id}/upload`,
    );
    expect(first.body).toBe(photo);
    expect(first.headers["X-Device-Check"]).toBe("skipped");
    expect(first.headers["X-Requested-With"]).toBe("XMLHttpRequest");
    expect(first.headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
    expect(JSON.stringify(first.headers)).not.toMatch(/supplier/i);
    expect(screen.getByText(s.sending)).toHaveAttribute("role", "status");
    act(() => first.progress(50, 100));
    expect(
      screen.getByRole("progressbar", { name: s.progressLabel }),
    ).toHaveAttribute("value", "0.5");

    // --- A failed send keeps the photo; Send again reuses the key (AD-6).
    act(() => first.fail());
    expect(await screen.findByText(s.failed)).toHaveAttribute("role", "alert");
    fireEvent.click(screen.getByRole("button", { name: s.send }));
    const second = FakeXhr.last();
    expect(second).not.toBe(first);
    expect(second.headers["Idempotency-Key"]).toBe(
      first.headers["Idempotency-Key"],
    );
    act(() =>
      second.respond(200, {
        invoice_id: "0199a1b2-0000-7000-8000-000000000001",
        po_number: "PO-45012",
        supplier_name: "Synthetic Alpha Building Supplies",
      }),
    );
    const received = await screen.findByText(
      "Received for PO 45012, Synthetic Alpha Building Supplies.",
    );
    await waitFor(() => expect(received).toHaveFocus());
    expect(received.closest("[role=status]")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: s.scanAnother }));
    await screen.findByRole("heading", { level: 2, name: s.today });

    // --- A photo problem: Take again; Send it anyway from the 2nd failure.
    check.checkFile.mockResolvedValue({
      kind: "photo-problem",
      problem: { kind: "dark" },
    } satisfies CheckResult);
    fireEvent.click(await screen.findByRole("button", { name: /PO 45016/ }));
    fireEvent.change(screen.getByTestId("choose-file-input"), {
      target: { files: [photo] },
    });
    expect(await screen.findByText(s.tooDark)).toHaveAttribute("role", "alert");
    expect(screen.getByRole("button", { name: s.takeAgain })).toBeVisible();
    expect(screen.queryByRole("button", { name: s.send })).toBeNull();
    expect(screen.queryByRole("button", { name: s.sendAnyway })).toBeNull();
    const retake = new File([new Uint8Array(1600)], "retake.jpg", {
      type: "image/jpeg",
    });
    fireEvent.change(screen.getByTestId("take-again-input"), {
      target: { files: [retake] },
    });
    fireEvent.click(await screen.findByRole("button", { name: s.sendAnyway }));
    const anyway = FakeXhr.last();
    expect(anyway.url).toBe(
      `/api/goods-in/deliveries/${TODAY.delivery_id}/upload`,
    );
    expect(anyway.body).toBe(retake);
    expect(anyway.headers["X-Device-Check"]).toBe("overridden");
    check.checkFile.mockResolvedValue({
      kind: "skipped",
    } satisfies CheckResult);

    // --- The delivery has gone meanwhile: back to the list, saying so.
    act(() =>
      anyway.respond(404, {
        code: "DELIVERY_NOT_FOUND",
        message: "Delivery not found.",
        correlation_id: "0199a1b2-0000-7000-8000-000000000012",
      }),
    );
    await screen.findByRole("heading", { level: 2, name: s.today });
    expect(screen.getByText(s.deliveryGone)).toHaveAttribute("role", "alert");

    // --- Database stopped on send: the goods-in words, not the system-wide ones.
    fireEvent.click(await screen.findByRole("button", { name: /PO 45016/ }));
    fireEvent.change(screen.getByTestId("choose-file-input"), {
      target: { files: [photo] },
    });
    fireEvent.click(await screen.findByRole("button", { name: s.send }));
    act(() =>
      FakeXhr.last().respond(503, {
        code: "DB_OFFLINE",
        message: "The database is offline. Try again later.",
        correlation_id: "0199a1b2-0000-7000-8000-000000000013",
      }),
    );
    await screen.findByRole("heading", {
      level: 1,
      name: s.unavailableHeading,
    });
    expect(screen.getByTestId("shell-notice")).toHaveTextContent(s.unavailable);
    unmount();

    // --- Database stopped on open: the goods-in words, not the system-wide ones.
    cleanup();
    fetchMock.mockReset();
    goodsIn(() =>
      answer(503, {
        code: "DB_OFFLINE",
        message: "The database is offline. Try again later.",
        correlation_id: "0199a1b2-0000-7000-8000-000000000011",
      }),
    );
    render(<App />);
    await screen.findByRole("heading", {
      level: 1,
      name: s.unavailableHeading,
    });
    expect(screen.getByTestId("shell-notice")).toHaveTextContent(s.unavailable);
    expect(screen.queryByText(strings.offline)).toBeNull();

    // --- Sign-in expired on send: built-in auth's empty 403 is an expired session.
    cleanup();
    fetchMock.mockReset();
    goodsIn(() => answer(200, { today: "2026-09-29", items: [TODAY] }));
    const expired = vi.fn();
    const stop = onApiEvent(SESSION_EXPIRED, expired);
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /PO 45016/ }));
    fireEvent.change(screen.getByTestId("choose-file-input"), {
      target: {
        files: [
          new File([new Uint8Array(900)], "late.jpg", { type: "image/jpeg" }),
        ],
      },
    });
    fireEvent.click(await screen.findByRole("button", { name: s.send }));
    act(() => FakeXhr.last().respond(403, ""));
    await waitFor(() => expect(expired).toHaveBeenCalledTimes(1));
    stop();
  });
});
