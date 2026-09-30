import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InvoiceDetailScreen } from "@/screens/InvoiceDetailScreen";
import { InvoicesScreen } from "@/screens/InvoicesScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

const POSTED = "0192f0c1-7a2b-7c3d-8e4f-000000000001";
const RECHECKING = "0192f0c1-7a2b-7c3d-8e4f-000000000002";
const ALPHA = "01a0c450-6c00-7b7b-8aa9-4ccade9f5526";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Synthetic rows, newest first as the API sends them.
const ROWS = [
  {
    invoice_id: RECHECKING,
    reference: "R-00000002",
    received_at: "2026-09-02T03:30:00+00:00",
    supplier_id: ALPHA,
    supplier_name: "Synthetic Alpha Building Supplies",
    invoice_number: "INV-002",
    amount: null,
    currency: null,
    status: "validating",
    after_correction: true,
  },
  {
    invoice_id: POSTED,
    reference: "R-00000001",
    received_at: "2026-09-01T01:02:00+00:00",
    supplier_id: ALPHA,
    supplier_name: "Synthetic Alpha Building Supplies",
    invoice_number: "INV 001",
    amount: "1248.50",
    currency: "SGD",
    status: "posted",
    after_correction: false,
  },
];

function page(items: unknown[]) {
  return {
    items,
    page: 1,
    page_size: 50,
    total: items.length,
    suppliers: [
      {
        supplier_id: ALPHA,
        supplier_name: "Synthetic Alpha Building Supplies",
      },
    ],
  };
}

function requested(): URL[] {
  return fetchMock.mock.calls.map(
    ([input]) => new URL(String(input), "http://localhost"),
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/invoices");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("3.4 search all invoices", () => {
  it("searches with labels not codes, then shows an invoice's detail without bank digits", async () => {
    // --- Every invoice first; statuses as labels, "Re-checking" after a correction.
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const q = url.searchParams.get("q");
      if (q === "zzz") return answer(page([]));
      if (q === "INV-9999") {
        return answer({ code: "VALIDATION_FAILED", message: "x" }, 400);
      }
      if (q !== null) return answer(page([ROWS[1]]));
      return answer(page(ROWS));
    });
    const list = render(<InvoicesScreen />);
    const rows = await screen.findAllByTestId("invoice-row");
    expect(document.title).toBe("Invoices – Babaloo");
    expect(requested()[0]?.pathname).toBe("/api/invoices");
    expect(rows[0]).toHaveTextContent("Re-checking");
    expect(rows[0]).toHaveTextContent(strings.queue.noAmount);
    expect(rows[0]).not.toHaveTextContent("validating");
    expect(rows[1]).toHaveTextContent("Posted");
    expect(rows[1]).toHaveTextContent("SGD 1,248.50");
    expect(rows[1]).toHaveTextContent("INV 001");
    expect(rows[1]).toHaveTextContent("R-00000001");
    expect(within(rows[1]!).getByRole("link")).toHaveAttribute(
      "href",
      `/invoices/${POSTED}`,
    );
    expect(screen.getByText("2 invoices found")).toBeInTheDocument();

    // --- Search: one box plus Status, no other filter; a status label is its codes.
    const box = screen.getByLabelText(strings.invoices.filters.search);
    expect(box).toHaveAccessibleDescription(
      strings.invoices.filters.searchHint,
    );
    expect(screen.getAllByRole("combobox")).toHaveLength(1);
    expect(screen.getAllByRole("searchbox")).toHaveLength(1);
    fireEvent.change(screen.getByLabelText(strings.invoices.filters.status), {
      target: { value: "Posting" },
    });
    // A reference, a number or a supplier name all go in the one box, trimmed.
    for (const typed of [" r-00000001 ", "INV 001", "alpha"]) {
      fireEvent.change(box, { target: { value: typed } });
      fireEvent.click(
        screen.getByRole("button", { name: strings.invoices.search }),
      );
      await waitFor(() =>
        expect(requested().at(-1)?.searchParams.get("q")).toBe(typed.trim()),
      );
      await waitFor(() =>
        expect(screen.getAllByTestId("invoice-row")).toHaveLength(1),
      );
      const sent = requested().at(-1)!;
      expect(sent.searchParams.get("status")).toBe("ready_to_post,posting");
      expect(sent.searchParams.get("page")).toBe("1");
      for (const old of ["supplier_id", "invoice_number", "reference"]) {
        expect(sent.searchParams.has(old)).toBe(false);
      }
    }

    // --- No match says so, from the box alone (any status).
    fireEvent.change(screen.getByLabelText(strings.invoices.filters.status), {
      target: { value: "" },
    });
    fireEvent.change(box, { target: { value: "zzz" } });
    fireEvent.click(
      screen.getByRole("button", { name: strings.invoices.search }),
    );
    expect(
      await screen.findByText(strings.invoices.noMatch),
    ).toBeInTheDocument();

    // --- A refused search says so. Defensive: the box (64 characters at most, blank
    // sends no q) can't produce a refusal, so the server is mocked refusing one.
    fireEvent.change(box, { target: { value: "INV-9999" } });
    fireEvent.click(
      screen.getByRole("button", { name: strings.invoices.search }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      strings.invoices.badSearch,
    );

    // --- Clear empties the box and sends no q.
    fireEvent.click(
      screen.getByRole("button", { name: strings.invoices.clear }),
    );
    await waitFor(() =>
      expect(requested().at(-1)?.searchParams.has("q")).toBe(false),
    );
    expect(box).toHaveValue("");
    list.unmount();

    // --- Paging: Next keeps the filters; an empty page past the end goes to the last.
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      return url.searchParams.get("page") === "2"
        ? answer({ ...page([]), page: 2, total: 40 })
        : answer({ ...page(ROWS), total: 120 });
    });
    const paged = render(<InvoicesScreen />);
    await screen.findAllByTestId("invoice-row");
    fireEvent.change(screen.getByLabelText(strings.invoices.filters.status), {
      target: { value: "Posted" },
    });
    fireEvent.change(screen.getByLabelText(strings.invoices.filters.search), {
      target: { value: "alpha" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: strings.invoices.search }),
    );
    await waitFor(() =>
      expect(requested().at(-1)?.searchParams.get("status")).toBe("posted"),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: strings.queue.pagination.next,
      }),
    );
    await waitFor(() =>
      expect(requested().map((u) => u.searchParams.get("page"))).toEqual([
        "1",
        "1",
        "2",
        "1",
      ]),
    );
    expect(requested()[2]?.searchParams.get("status")).toBe("posted");
    expect(requested()[3]?.searchParams.get("status")).toBe("posted");
    expect(requested()[2]?.searchParams.get("q")).toBe("alpha");
    expect(requested()[3]?.searchParams.get("q")).toBe("alpha");
    paged.unmount();

    // --- Detail: summary, fields, bank on file only, lines, history by category.
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce(
      answer({
        invoice_id: POSTED,
        reference: "R-00000001",
        received_at: "2026-09-01T01:02:00+00:00",
        supplier_id: ALPHA,
        supplier_name: "Synthetic Alpha Building Supplies",
        status: "posted",
        after_correction: false,
        accounts_ref: "ACC-000123",
        posted_at: "2026-09-01T03:00:00+00:00",
        fields: [
          { field_id: "invoice_number", value: "INV 001", currency: null },
          { field_id: "invoice_total", value: "1248.50", currency: "SGD" },
        ],
        bank_on_file: true,
        lines: [
          {
            line_no: 1,
            product_code: "EVA-01",
            description: "EVA soles",
            quantity: "10",
            unit_price: "124.85",
            amount: "1248.50",
          },
        ],
        history: [
          {
            from_status: null,
            to_status: "received",
            at: "2026-09-01T01:02:00+00:00",
            actor: "quality",
          },
          {
            from_status: "in_admin_queue",
            to_status: "ready_to_post",
            at: "2026-09-01T02:00:00+00:00",
            actor: "admin",
          },
        ],
      }),
    );
    const detail = render(<InvoiceDetailScreen invoiceId={POSTED} />);
    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Invoice from Synthetic Alpha Building Supplies",
      }),
    ).toBeInTheDocument();
    expect(requested()[0]?.pathname).toBe(`/api/invoices/${POSTED}`);
    expect(screen.getByText("ACC-000123")).toBeInTheDocument();
    expect(screen.getByText("Invoice number")).toBeInTheDocument();
    expect(screen.getByText("SGD 1248.50")).toBeInTheDocument();
    expect(
      screen.getByText(strings.invoices.detail.bankOnFile),
    ).toBeInTheDocument();
    expect(screen.getByText("EVA soles")).toBeInTheDocument();
    const history = within(
      screen.getByRole("table", { name: strings.invoices.detail.historyLabel }),
    );
    expect(history.getByText("Quality check")).toBeInTheDocument();
    expect(history.getByText("Admin")).toBeInTheDocument();
    expect(history.getByText("In admin queue")).toBeInTheDocument();
    expect(history.queryByText("in_admin_queue")).not.toBeInTheDocument();
    detail.unmount();

    // --- An unknown invoice.
    fetchMock.mockResolvedValueOnce(
      answer({ code: "NOT_FOUND", message: "Not found." }, 404),
    );
    render(<InvoiceDetailScreen invoiceId={RECHECKING} />);
    expect(
      await screen.findByText(strings.invoices.detail.notFound),
    ).toBeInTheDocument();
  });
});
