import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "@/App";
import { AccountsErrorPanel } from "@/components/item/AccountsErrorPanel";
import { navigate } from "@/router";
import { setShortcutsEnabled } from "@/shell/shortcuts";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();
const ID = "0192f0c1-7a2b-7c3d-8e4f-000000000001";
const NEXT = "0192f0c1-7a2b-7c3d-8e4f-000000000002";
const a = strings.item.actions;
const ROUTING = "0192f0c3-0001-7000-8000-000000000000";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function field(fieldId: string, extra: Record<string, unknown> = {}) {
  return {
    field_id: fieldId,
    value: null,
    currency: null,
    confidence: 0.99,
    page: null,
    polygon: null,
    flagged: false,
    bank: false,
    ...extra,
  };
}

// Synthetic, as GET /api/admin/items/{id} sends it.
function item(id: string, extra: Record<string, unknown> = {}) {
  return {
    invoice_id: id,
    received_at: "2026-09-01T01:00:00+00:00",
    content_type: "application/pdf",
    image_available: false,
    supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5c29",
    supplier_name: "Synthetic Kowloon Soles",
    supplier_phone: null,
    reasons: [
      {
        code: "LOW_CONFIDENCE",
        field_ids: ["invoice_total", "line[1].quantity"],
        detail: {},
      },
      { code: "BANK_CHANGED", field_ids: ["payment[0].iban"], detail: {} },
    ],
    fields: [
      field("invoice_total", {
        value: "109.00",
        currency: "SGD",
        confidence: 0.91,
        flagged: true,
      }),
      field("payment[0].iban", { flagged: true, bank: true }),
      field("vendor_name", { value: "Synthetic Kowloon Soles" }),
    ],
    lines: [
      {
        line_no: 1,
        product_code: "EVA-01",
        description: "EVA soles",
        quantity: "10",
        unit_price: "10.90",
        amount: "109.00",
        confidence: 0.99,
      },
    ],
    pages: [],
    bank_changes: [
      { field_id: "payment[0].iban", on_file: "4821", new: "9930" },
    ],
    allowed_actions: ["correct", "reject"],
    routing_id: ROUTING,
    addable_fields: ["invoice_date"],
    ...extra,
  };
}

const QUEUE = {
  items: [ID, NEXT].map((invoiceId) => ({
    invoice_id: invoiceId,
    received_at: "2026-09-01T01:00:00+00:00",
    supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5c29",
    supplier_name: "Synthetic Kowloon Soles",
    amount: null,
    currency: null,
    reasons: ["LOW_CONFIDENCE"],
    returned_after_correction: invoiceId === NEXT,
  })),
  page: 1,
  page_size: 50,
  total: 2,
  page_usage: null,
  suppliers: [],
};

/** Answers GETs from `items`, and each POST in turn from `posts`. */
function serve(items: Record<string, unknown>, posts: Response[]) {
  fetchMock.mockImplementation(async (input, init) => {
    const path = String(input);
    if (init?.method === "POST") {
      return posts.shift() ?? answer({ code: "INTERNAL_ERROR" }, 500);
    }
    if (path === "/api/me") return answer({ name: "Priya", roles: ["admin"] });
    if (path.startsWith("/api/admin/queue")) return answer(QUEUE);
    const id = decodeURIComponent(path.split("/")[4] ?? "");
    return id in items ? answer(items[id]) : answer({ code: "NOT_FOUND" }, 404);
  });
}

function posted(n: number): { path: string; body: unknown } {
  const calls = fetchMock.mock.calls.filter(([, i]) => i?.method === "POST");
  const [input, init] = calls[n] ?? [];
  return { path: String(input), body: JSON.parse(String(init?.body)) };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.sessionStorage.clear();
  window.history.replaceState(null, "", `/queue/${ID}`);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("2.10 admin actions", () => {
  it("shows the allowed actions; Correct keeps edits across a sign-in, saves and opens the next item", async () => {
    serve({ [ID]: item(ID), [NEXT]: item(NEXT) }, [
      answer({ code: "UNAUTHENTICATED", message: "x" }, 401),
      answer({ invoice_id: ID, status: "awaiting_validation" }),
    ]);
    const first = render(<App />);
    const bar = await screen.findByRole("region", { name: a.label });
    // The server's guard: Correct and Reject only.
    expect(
      within(bar)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([a.correct, a.reject]);

    fireEvent.click(within(bar).getByRole("button", { name: a.correct }));
    const form = await screen.findByRole("form", {
      name: strings.item.correct.heading,
    });
    // Bank fields are never editable (AD-11).
    expect(within(form).queryByLabelText(/IBAN/)).toBeNull();
    expect(form).toHaveTextContent(strings.item.correct.bankLocked);
    const supplier = within(form).getByLabelText(/Supplier name/);
    fireEvent.change(supplier, {
      target: { value: "Synthetic Kowloon Soles Pte" },
    });
    expect(supplier.closest("div")).toHaveTextContent(
      strings.item.correct.corrected,
    );
    // The flagged total is left as read; one line cell changes.
    expect(
      within(form)
        .getByLabelText(/Invoice total/)
        .closest("div"),
    ).not.toHaveTextContent(strings.item.correct.corrected);
    fireEvent.change(within(form).getAllByLabelText(/Amount/)[0]!, {
      target: { value: "110.00" },
    });
    // A missing checked field the server lets Correct add.
    expect(within(form).queryByLabelText(/Invoice number/)).toBeNull();
    fireEvent.change(within(form).getByLabelText(/Invoice date/), {
      target: { value: "2026-09-28" },
    });

    // The session ends on save: the edits wait in this tab, never a bank value.
    fireEvent.click(
      within(form).getByRole("button", { name: strings.item.correct.save }),
    );
    expect(
      await screen.findByRole("dialog", { name: strings.sessionExpired }),
    ).toBeInTheDocument();
    const kept = window.sessionStorage.getItem(`babaloo.correct.${ID}`) ?? "";
    expect(kept).toContain("Synthetic Kowloon Soles Pte");
    expect(kept).not.toContain("payment");

    // Signed in again (a fresh page): the item is still queued, the edits return.
    first.unmount();
    render(<App />);
    const restored = await screen.findByRole("form", {
      name: strings.item.correct.heading,
    });
    expect(within(restored).getByLabelText(/Supplier name/)).toHaveValue(
      "Synthetic Kowloon Soles Pte",
    );
    fireEvent.click(
      within(restored).getByRole("button", { name: strings.item.correct.save }),
    );

    // Saved: the Toast, and the next item with focus on its heading.
    await waitFor(() =>
      expect(window.location.pathname).toBe(`/queue/${NEXT}`),
    );
    expect(screen.getByTestId("shell-toast")).toHaveTextContent(
      a.sentForRecheck,
    );
    await waitFor(() =>
      expect(document.activeElement).toHaveTextContent(
        strings.surfaces.admin_item,
      ),
    );
    const save = posted(1);
    expect(save.path).toBe(`/api/admin/items/${ID}/correct`);
    // Changed fields, the flagged one confirmed as read, and only the changed line
    // column (the server copies the rest of the line).
    expect(save.body).toEqual({
      routing_id: ROUTING,
      fields: {
        invoice_total: "109.00",
        vendor_name: "Synthetic Kowloon Soles Pte",
        invoice_date: "2026-09-28",
      },
      lines: [{ line_no: 1, amount: "110.00" }],
    });
    expect(window.sessionStorage.getItem(`babaloo.correct.${ID}`)).toBeNull();
  });

  it("asks for a new copy of an unreadable photo, needs a reject reason, and returns to the queue when another admin acted first", async () => {
    serve(
      {
        [ID]: item(ID, {
          reasons: [{ code: "UNREADABLE", field_ids: [], detail: {} }],
          supplier_phone: "+65 6000 0110",
          fields: [],
          lines: [],
          bank_changes: [],
          allowed_actions: ["reject"],
        }),
      },
      [answer({ code: "CONFLICT", message: a.alreadyHandled }, 409)],
    );
    render(<App />);
    const bar = await screen.findByRole("region", { name: a.label });
    expect(
      screen.getByRole("region", { name: strings.item.resend.heading }),
    ).toHaveTextContent(
      "Ask the supplier to send it again.Call +65 6000 0110 (number on file)",
    );
    expect(within(bar).getAllByRole("button")).toHaveLength(1);

    fireEvent.click(within(bar).getByRole("button", { name: a.reject }));
    const dialog = await screen.findByRole("dialog", {
      name: a.rejectDialog.heading,
    });
    const confirm = within(dialog).getByRole("button", {
      name: a.rejectDialog.confirm,
    });
    fireEvent.click(confirm);
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      a.rejectDialog.required,
    );
    expect(fetchMock.mock.calls.some(([, i]) => i?.method === "POST")).toBe(
      false,
    );
    fireEvent.change(within(dialog).getByLabelText(a.rejectDialog.reason), {
      target: { value: "Could not verify bank change" },
    });
    fireEvent.click(confirm);

    // Another admin acted first: the alert, back on the queue.
    await waitFor(() => expect(window.location.pathname).toBe("/queue"));
    expect(screen.getByTestId("shell-notice")).toHaveTextContent(
      a.alreadyHandled,
    );
    expect(posted(0)).toEqual({
      path: `/api/admin/items/${ID}/reject`,
      body: { routing_id: ROUTING, reason: "Could not verify bank change" },
    });
    // The queue marks a returned correction.
    const rows = await screen.findAllByTestId("queue-row");
    expect(rows[1]).toHaveTextContent(strings.queue.returned);
    expect(rows[0]).not.toHaveTextContent(strings.queue.returned);
  });

  it("sends Retry intake and Re-extract through their dialogs, and returns to the queue when an action is no longer allowed", async () => {
    const rerun = { reasons: [], fields: [], lines: [], bank_changes: [] };
    serve(
      {
        [ID]: item(ID, {
          ...rerun,
          allowed_actions: ["retry_intake", "reject"],
        }),
        [NEXT]: item(NEXT, {
          ...rerun,
          allowed_actions: ["reextract", "reject"],
        }),
      },
      [
        answer({ invoice_id: ID, status: "received" }),
        answer({ invoice_id: NEXT, status: "awaiting_extraction" }),
        answer({ code: "ACTION_NOT_ALLOWED", message: "x" }, 409),
      ],
    );
    render(<App />);

    async function confirm(
      button: string,
      dialog: { heading: string; confirm: string },
    ) {
      const bar = await screen.findByRole("region", { name: a.label });
      fireEvent.click(within(bar).getByRole("button", { name: button }));
      const open = await screen.findByRole("dialog", { name: dialog.heading });
      fireEvent.click(
        within(open).getByRole("button", { name: dialog.confirm }),
      );
    }

    // Retry intake: the next item opens with its Toast.
    await confirm(a.retryIntake, a.retryIntakeDialog);
    await waitFor(() =>
      expect(window.location.pathname).toBe(`/queue/${NEXT}`),
    );
    expect(screen.getByTestId("shell-toast")).toHaveTextContent(
      a.sentForIntake,
    );
    // Re-extract on it: back to the first with its Toast.
    await confirm(a.reextract, a.reextractDialog);
    await waitFor(() => expect(window.location.pathname).toBe(`/queue/${ID}`));
    expect(screen.getByTestId("shell-toast")).toHaveTextContent(
      a.sentForExtraction,
    );
    expect([posted(0), posted(1)]).toEqual([
      {
        path: `/api/admin/items/${ID}/retry-intake`,
        body: { routing_id: ROUTING },
      },
      {
        path: `/api/admin/items/${NEXT}/reextract`,
        body: { routing_id: ROUTING },
      },
    ]);

    // No longer allowed (its reasons changed): the alert, back on the queue.
    await confirm(a.retryIntake, a.retryIntakeDialog);
    await waitFor(() => expect(window.location.pathname).toBe("/queue"));
    expect(screen.getByTestId("shell-notice")).toHaveTextContent(a.notAllowed);
    expect(posted(2).path).toBe(`/api/admin/items/${ID}/retry-intake`);
  });
});

describe("3.3 admin approves exceptions", () => {
  it("gates Approve on both call-back checks, confirms a summary, compares a duplicate, shows the accounts error, and opens with a", async () => {
    const b = strings.item.bank;
    const d = strings.item.duplicate;
    const e = strings.item.accountsError;
    const THIRD = "0192f0c1-7a2b-7c3d-8e4f-000000000003";
    setShortcutsEnabled(true);
    serve(
      {
        // DUPLICATE alone, its matching invoice unreadable.
        [THIRD]: item(THIRD, {
          reasons: [{ code: "DUPLICATE", field_ids: [], detail: {} }],
          bank_changes: [],
          allowed_actions: ["approve", "reject"],
          duplicate_of: null,
        }),
        [ID]: item(ID, {
          supplier_phone: "+65 6000 0110",
          allowed_actions: ["correct", "approve", "reject"],
        }),
        [NEXT]: item(NEXT, {
          image_available: true,
          reasons: [
            {
              code: "DUPLICATE",
              field_ids: [],
              detail: { invoice_id: ID, basis: "fingerprint" },
            },
            {
              code: "ACCOUNTS_API_ERROR",
              field_ids: [],
              detail: { status: 503, code: "SIMULATED_FAILURE" },
            },
          ],
          bank_changes: [],
          allowed_actions: ["approve", "reject"],
          duplicate_of: {
            invoice_id: ID,
            received_at: "2026-08-28T02:00:00+00:00",
            content_type: "image/jpeg",
            supplier_name: "Synthetic Kowloon Soles",
            invoice_total: "1248.50",
            currency: "SGD",
            image_available: false,
          },
        }),
      },
      [
        answer({ invoice_id: ID, status: "ready_to_post" }),
        answer({ invoice_id: NEXT, status: "ready_to_post" }),
      ],
    );
    try {
      render(<App />);
      const bar = await screen.findByRole("region", { name: a.label });
      expect(
        within(bar)
          .getAllByRole("button")
          .map((button) => button.textContent),
      ).toEqual([a.correct, a.approve, a.reject]);

      // Bank change: Approve waits for both checks, and says why; a does nothing.
      const approve = within(bar).getByRole("button", { name: a.approve });
      expect(approve).toBeDisabled();
      expect(approve).toHaveAccessibleDescription(a.tickBoth);
      fireEvent.keyDown(document.body, { key: "a" });
      expect(screen.queryByRole("dialog")).toBeNull();
      const panel = screen.getByRole("region", { name: b.heading });
      fireEvent.click(
        within(panel).getByRole("checkbox", { name: b.calledNumber }),
      );
      expect(approve).toBeDisabled();
      fireEvent.click(
        within(panel).getByRole("checkbox", { name: b.supplierConfirmed }),
      );
      expect(approve).toBeEnabled();
      expect(bar).not.toHaveTextContent(a.tickBoth);

      // a opens the same dialog as the button: the summary, then a reason.
      fireEvent.keyDown(document.body, { key: "a" });
      const dialog = await screen.findByRole("dialog", {
        name: a.approveDialog.heading,
      });
      expect(dialog).toHaveTextContent(
        `${a.approveDialog.supplier}Synthetic Kowloon Soles`,
      );
      expect(dialog).toHaveTextContent(`${a.approveDialog.amount}SGD 109.00`);
      const confirm = within(dialog).getByRole("button", {
        name: a.approveDialog.confirm,
      });
      fireEvent.click(confirm);
      expect(within(dialog).getByRole("alert")).toHaveTextContent(
        a.approveDialog.required,
      );
      expect(fetchMock.mock.calls.some(([, i]) => i?.method === "POST")).toBe(
        false,
      );
      fireEvent.change(within(dialog).getByLabelText(a.approveDialog.reason), {
        target: { value: "Confirmed new account by phone with Ms Chan" },
      });
      fireEvent.click(confirm);
      await waitFor(() =>
        expect(window.location.pathname).toBe(`/queue/${NEXT}`),
      );
      expect(screen.getByTestId("shell-toast")).toHaveTextContent(a.approved);
      expect(posted(0)).toEqual({
        path: `/api/admin/items/${ID}/approve`,
        body: {
          routing_id: ROUTING,
          reason: "Confirmed new account by phone with Ms Chan",
          checks: { called_number_on_file: true, supplier_confirmed: true },
        },
      });

      // Duplicate: the matching invoice side by side; its image is gone.
      const compare = await screen.findByRole("region", { name: d.heading });
      const [mine, theirs] = within(compare).getAllByRole("heading", {
        level: 3,
      });
      expect([mine?.textContent, theirs?.textContent]).toEqual([
        d.thisInvoice,
        d.matching,
      ]);
      expect(compare).toHaveTextContent(`${d.total}SGD 1,248.50`);
      expect(compare).toHaveTextContent(`${d.total}SGD 109.00`);
      expect(
        within(compare).getByRole("link", {
          name: strings.item.viewer.openPdf,
        }),
      ).toHaveAttribute("href", `/api/admin/items/${NEXT}/image`);
      expect(
        within(compare).getAllByText(strings.item.viewer.deleted),
      ).toHaveLength(1);
      // The accounts error as stored: status and code.
      expect(
        screen.getByRole("region", {
          name: strings.item.accountsError.heading,
        }),
      ).toHaveTextContent(
        "The accounts system answered with status 503 (SIMULATED_FAILURE).",
      );
      expect(screen.getByText(e.retry)).toBeInTheDocument();
      // No bank change: no checklist. Another reason is open besides DUPLICATE,
      // so Approve says Approve, not "Not a duplicate".
      expect(screen.queryByRole("checkbox")).toBeNull();
      const next = screen.getByRole("region", { name: a.label });
      expect(
        within(next)
          .getAllByRole("button")
          .map((button) => button.textContent),
      ).toEqual([a.approve, a.reject]);
      fireEvent.click(within(next).getByRole("button", { name: a.approve }));
      const again = await screen.findByRole("dialog", {
        name: a.approveDialog.heading,
      });
      // Each dialog starts with its own empty reason.
      expect(within(again).getByLabelText(a.approveDialog.reason)).toHaveValue(
        "",
      );
      fireEvent.change(within(again).getByLabelText(a.approveDialog.reason), {
        target: { value: "Different delivery" },
      });
      fireEvent.click(
        within(again).getByRole("button", { name: a.approveDialog.confirm }),
      );
      await waitFor(() =>
        expect(window.location.pathname).toBe(`/queue/${ID}`),
      );
      expect(posted(1).body).toEqual({
        routing_id: ROUTING,
        reason: "Different delivery",
        checks: { called_number_on_file: false, supplier_confirmed: false },
      });

      // DUPLICATE alone: "Not a duplicate"; with no matching invoice to show, the
      // duplicate is still flagged, with a note instead of the comparison.
      act(() => navigate(`/queue/${THIRD}`));
      const alone = await screen.findByRole("region", { name: d.heading });
      expect(alone).toHaveTextContent(d.unavailable);
      expect(within(alone).queryByText(d.matching)).toBeNull();
      expect(
        within(screen.getByRole("region", { name: a.label }))
          .getAllByRole("button")
          .map((button) => button.textContent),
      ).toEqual([a.notDuplicate, a.reject]);
    } finally {
      setShortcutsEnabled(false);
    }

    // The accounts error without a status (timeout) or a code, and without Approve.
    const reason = (detail: Record<string, unknown>) => ({
      code: "ACCOUNTS_API_ERROR",
      fieldIds: [],
      detail,
    });
    const { rerender } = render(
      <AccountsErrorPanel
        reason={reason({ status: null, code: "TIMEOUT" })}
        approvable
      />,
    );
    const error = screen.getByRole("region", { name: e.heading });
    expect(error).toHaveTextContent(e.noAnswer("TIMEOUT"));
    expect(error).toHaveTextContent(e.retry);
    rerender(
      <AccountsErrorPanel
        reason={reason({ status: 503 })}
        approvable={false}
      />,
    );
    expect(error).toHaveTextContent(e.unknown);
    expect(error).not.toHaveTextContent(e.retry);
  });
});
