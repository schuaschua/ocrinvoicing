import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OFFLINE, apiEvents } from "@/api";
import { App } from "@/App";
import { SHORTCUTS_SETTING, setShortcutsEnabled } from "@/shell/shortcuts";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();
const FIRST = "0192f0c1-7a2b-7c3d-8e4f-000000000001";
const SECOND = "0192f0c1-7a2b-7c3d-8e4f-000000000002";
const BOX_A = [100, 200, 400, 200, 400, 260, 100, 260];
const BOX_B = [500, 700, 900, 700, 900, 780, 500, 780];
const s = strings.shortcuts;
const a = strings.item.actions;

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function field(fieldId: string, polygon: number[]) {
  return {
    field_id: fieldId,
    value: "Synthetic",
    currency: null,
    confidence: 0.9,
    page: 1,
    polygon,
    flagged: true,
    bank: false,
  };
}

// Synthetic, as the API sends them.
const QUEUE = {
  items: [FIRST, SECOND].map((invoiceId) => ({
    invoice_id: invoiceId,
    received_at: "2026-09-01T01:00:00+00:00",
    supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5c29",
    supplier_name: "Synthetic Kowloon Soles",
    amount: null,
    currency: null,
    reasons: ["LOW_CONFIDENCE"],
  })),
  page: 1,
  page_size: 50,
  total: 2,
  page_usage: null,
  suppliers: [],
};

const ITEM = {
  invoice_id: SECOND,
  received_at: "2026-09-01T01:00:00+00:00",
  content_type: "image/jpeg",
  image_available: true,
  supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5c29",
  supplier_name: "Synthetic Kowloon Soles",
  supplier_phone: null,
  reasons: [
    {
      code: "LOW_CONFIDENCE",
      field_ids: ["invoice_total", "vendor_name"],
      detail: {},
    },
  ],
  fields: [field("invoice_total", BOX_A), field("vendor_name", BOX_B)],
  lines: [],
  pages: [{ page: 1, width: 1000, height: 1400, unit: "pixel" }],
  bank_changes: [],
  allowed_actions: ["correct", "reject"],
  routing_id: "0192f0c3-0001-7000-8000-000000000000",
  addable_fields: [],
};

// The image is gone (boxes but no flag buttons), and only Re-extract is allowed.
const LIMITED = {
  ...ITEM,
  invoice_id: FIRST,
  image_available: false,
  allowed_actions: ["reextract"],
};

function press(key: string, init: KeyboardEventInit = {}) {
  fireEvent.keyDown(document.activeElement ?? document.body, { key, ...init });
}

function chosen(): number {
  return screen
    .getAllByTestId("queue-row")
    .findIndex((row) => row.getAttribute("aria-current") === "true");
}

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input) => {
    const path = String(input);
    if (path === "/api/me") return answer({ name: "Priya", roles: ["admin"] });
    if (path.startsWith("/api/admin/queue")) return answer(QUEUE);
    return answer(path.includes(FIRST) ? LIMITED : ITEM);
  });
  vi.stubGlobal("fetch", fetchMock);
  // Also clears a session-only choice an earlier test left behind.
  setShortcutsEnabled(false);
  window.localStorage.clear();
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/queue");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("2.11 test_story_2_11 keyboard shortcuts", () => {
  it("are off by default and without storage, and never fire while typing, with a modifier or under a dialog", async () => {
    render(<App />);
    await screen.findAllByTestId("queue-row");
    const toggle = screen.getByRole("switch", { name: s.toggle });

    // Off by default: keys do nothing.
    expect(toggle).not.toBeChecked();
    press("j");
    press("?");
    expect(chosen()).toBe(-1);
    expect(screen.queryByRole("dialog")).toBeNull();

    // Storage throws: still off, and the toggle works for the session, silently.
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    press("j");
    expect(chosen()).toBe(-1);
    fireEvent.click(toggle);
    expect(toggle).toBeChecked();
    expect(screen.queryByRole("alert")).toBeEmptyDOMElement();
    press("j");
    expect(chosen()).toBe(0);
    vi.restoreAllMocks();

    // Modifiers and repeats are the browser's.
    press("j", { ctrlKey: true });
    press("j", { metaKey: true });
    press("j", { altKey: true });
    press("j", { repeat: true });
    expect(chosen()).toBe(0);
    // Caps Lock: "J" is still j.
    press("J");
    expect(chosen()).toBe(1);

    // Enter on a focused link is the link's own, not the chosen row's.
    within(screen.getAllByTestId("queue-row")[0]!).getByRole("link").focus();
    press("Enter");
    expect(window.location.pathname).toBe("/queue");

    // Typing in a field: the key is the field's.
    const reason = screen.getByLabelText(strings.queue.filters.reason, {
      selector: "select",
    });
    reason.focus();
    press("j");
    expect(chosen()).toBe(1);

    // `?` opens the help; under a dialog the keys do nothing.
    screen.getByRole("heading", { level: 1 }).focus();
    press("?");
    const help = screen.getByRole("dialog", { name: s.helpHeading });
    expect(help).toHaveTextContent("Next invoice in the queue");
    press("j");
    press("Enter");
    expect(chosen()).toBe(1);
    expect(window.location.pathname).toBe("/queue");
    fireEvent.click(within(help).getByRole("button", { name: s.close }));
    expect(screen.queryByRole("dialog")).toBeNull();

    // Turned off, then on with storage working: stored as ocr.shortcuts=on.
    fireEvent.click(toggle);
    expect(toggle).not.toBeChecked();
    expect(window.localStorage.getItem(SHORTCUTS_SETTING)).toBeNull();
    fireEvent.click(toggle);
    expect(window.localStorage.getItem(SHORTCUTS_SETTING)).toBe("on");

    // A filter change drops the chosen row: Enter opens nothing.
    screen.getByRole("heading", { level: 1 }).focus();
    press("j");
    expect(chosen()).toBe(1);
    fireEvent.change(reason, { target: { value: "PO_MISMATCH" } });
    await waitFor(() =>
      expect(String(fetchMock.mock.calls.at(-1)?.[0])).toContain(
        "reason=PO_MISMATCH",
      ),
    );
    await screen.findAllByTestId("queue-row");
    await waitFor(() =>
      expect(screen.getByRole("table")).toHaveAttribute("aria-busy", "false"),
    );
    expect(chosen()).toBe(-1);
    press("Enter");
    expect(window.location.pathname).toBe("/queue");

    // Turned off in another tab while the help is open: it closes, and stays closed
    // when turned on again.
    press("?");
    expect(screen.getByRole("dialog", { name: s.helpHeading })).toBeVisible();
    act(() => {
      window.localStorage.removeItem(SHORTCUTS_SETTING);
      window.dispatchEvent(new StorageEvent("storage"));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    act(() => {
      window.localStorage.setItem(SHORTCUTS_SETTING, "on");
      window.dispatchEvent(new StorageEvent("storage"));
    });
    expect(screen.queryByRole("dialog")).toBeNull();

    // Offline while the help is open: only the offline notice shows.
    press("?");
    expect(screen.getByRole("dialog", { name: s.helpHeading })).toBeVisible();
    act(() => {
      apiEvents.dispatchEvent(new Event(OFFLINE));
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByTestId("shell-notice")).toHaveTextContent(
      strings.offline,
    );
  });

  it("move through the queue, open a row, and act on the item with the buttons' handlers", async () => {
    window.localStorage.setItem(SHORTCUTS_SETTING, "on");
    render(<App />);
    const rows = await screen.findAllByTestId("queue-row");
    expect(screen.getByRole("switch", { name: s.toggle })).toBeChecked();

    // j/k move the chosen row and its focus, staying at the ends; Esc stays here.
    press("k");
    expect(chosen()).toBe(0);
    expect(rows[0]).toHaveFocus();
    press("j");
    press("j");
    expect(chosen()).toBe(1);
    expect(rows[1]).toHaveFocus();
    press("k");
    press("j");
    press("Escape");
    expect(window.location.pathname).toBe("/queue");
    press("Enter");
    expect(window.location.pathname).toBe(`/queue/${SECOND}`);

    // n/p step the flagged regions, as Next and Previous flag do.
    await screen.findByRole("region", { name: a.label });
    expect(screen.getByText("Flag 1 of 2")).toBeInTheDocument();
    press("n");
    expect(screen.getByText("Flag 2 of 2")).toBeInTheDocument();
    press("p");
    expect(screen.getByText("Flag 1 of 2")).toBeInTheDocument();

    // r opens the Reject dialog; under it c does nothing.
    press("r");
    const reject = screen.getByRole("dialog", { name: a.rejectDialog.heading });
    press("c");
    expect(
      screen.queryByRole("form", { name: strings.item.correct.heading }),
    ).toBeNull();
    fireEvent.click(within(reject).getByRole("button", { name: a.cancel }));

    // c opens Correct mode; there Esc keeps the edits, and typing is the field's.
    press("c");
    const form = await screen.findByRole("form", {
      name: strings.item.correct.heading,
    });
    press("Escape");
    within(form)
      .getByLabelText(/Supplier name/)
      .focus();
    press("r");
    expect(window.location.pathname).toBe(`/queue/${SECOND}`);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(within(form).getByRole("button", { name: a.cancel }));

    // Out of Correct mode, Esc goes back to the queue.
    screen.getByRole("heading", { level: 1 }).focus();
    press("Escape");
    await waitFor(() => expect(window.location.pathname).toBe("/queue"));

    // An item that allows neither Correct, Approve nor Reject, with its image gone:
    // c, a, r, n and p do nothing, as there are no buttons for them.
    await screen.findAllByTestId("queue-row");
    press("j");
    press("Enter");
    expect(window.location.pathname).toBe(`/queue/${FIRST}`);
    const bar = await screen.findByRole("region", { name: a.label });
    expect(
      within(bar).getByRole("button", { name: a.reextract }),
    ).toBeVisible();
    const total = screen.getByRole("button", { name: /Box 1: Invoice total/ });
    expect(total).toHaveAttribute("aria-pressed", "true");
    press("c");
    press("a");
    press("r");
    press("n");
    press("p");
    expect(
      screen.queryByRole("form", { name: strings.item.correct.heading }),
    ).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(total).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: /Supplier name/ }),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
