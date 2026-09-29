import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueueScreen } from "@/screens/QueueScreen";
import { reasonLabels, strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

const FIRST = "0192f0c1-7a2b-7c3d-8e4f-000000000002";
const SECOND = "0192f0c1-7a2b-7c3d-8e4f-000000000003";
const BETA = "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0";

function answer(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// Every queued invoice's supplier, by name: Gamma has no row on this page.
const SUPPLIERS = [
  {
    supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
    supplier_name: "Synthetic Alpha Building Supplies",
  },
  { supplier_id: BETA, supplier_name: "Synthetic Beta Traders" },
  {
    supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55c0",
    supplier_name: "Synthetic Gamma Hardware",
  },
];

function queue(items: unknown[], extra: Record<string, unknown> = {}) {
  return {
    items,
    page: 1,
    page_size: 50,
    total: items.length,
    page_usage: null,
    suppliers: SUPPLIERS,
    ...extra,
  };
}

// Synthetic rows, in the order the API sends them (oldest first).
const ROWS = [
  {
    invoice_id: FIRST,
    received_at: "2026-09-01T01:02:00+00:00",
    supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
    supplier_name: "Synthetic Alpha Building Supplies",
    amount: "1100.50",
    currency: "SGD",
    reasons: ["PO_MISMATCH"],
  },
  {
    invoice_id: SECOND,
    received_at: "2026-09-01T01:03:00+00:00",
    supplier_id: BETA,
    supplier_name: "Synthetic Beta Traders",
    amount: null,
    currency: null,
    reasons: ["BANK_CHANGED", "DUPLICATE"],
  },
];

function requested(): URL[] {
  return fetchMock.mock.calls.map(
    ([input]) => new URL(String(input), "http://localhost"),
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/queue");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("2.8 admin queue", () => {
  it("lists the queue with labels, filters, pages, warns at the cap and opens items", async () => {
    // --- Empty: the EXPERIENCE.md line, and no Alert.
    fetchMock.mockResolvedValueOnce(answer(queue([])));
    const empty = render(<QueueScreen />);
    expect(await screen.findByText(strings.queue.empty)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(document.title).toBe("Admin queue – Babaloo");
    empty.unmount();

    // --- Rows in API order, labels not codes, amounts as sent; the page-cap Alert.
    // Page 2 answers empty with rows left (the queue shrank): back to the last page.
    // The BANK_CHANGED filter matches nothing.
    const populated = () =>
      answer(
        queue(ROWS, {
          total: 51,
          page_usage: { pages_used: 322, page_cap: 400 },
        }),
      );
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      if (url.searchParams.get("page") === "2") {
        return answer(queue([], { page: 2, total: 40 }));
      }
      if (url.searchParams.get("reason") === "BANK_CHANGED") {
        return answer(queue([]));
      }
      return populated();
    });
    render(<QueueScreen />);
    let rows = await screen.findAllByTestId("queue-row");
    expect(requested()[1]?.pathname).toBe("/api/admin/queue");
    expect(requested()[1]?.searchParams.get("page")).toBe("1");
    expect(
      rows.map((row) => within(row).getByRole("link").textContent),
    ).toEqual(["Synthetic Alpha Building Supplies", "Synthetic Beta Traders"]);
    expect(rows[0]).toHaveTextContent("SGD 1,100.50");
    expect(rows[0]).toHaveTextContent(reasonLabels.PO_MISMATCH);
    expect(rows[1]).toHaveTextContent(strings.queue.noAmount);
    expect(rows[1]).toHaveTextContent(reasonLabels.BANK_CHANGED);
    expect(rows[1]).toHaveTextContent(reasonLabels.DUPLICATE);
    expect(rows[1]).not.toHaveTextContent("BANK_CHANGED");
    // Blocking chips are marked for screen readers; the others are not.
    expect(rows[1]).toHaveTextContent(`${strings.queue.blocking}:`);
    expect(rows[0]).not.toHaveTextContent(`${strings.queue.blocking}:`);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "322 of 400 pages used this month.",
    );
    expect(screen.getByText("51 invoices waiting")).toBeInTheDocument();
    // The supplier options are every queued supplier the API lists, in its order.
    const supplierSelect = screen.getByLabelText(
      strings.queue.filters.supplier,
      { selector: "select" },
    );
    expect(
      within(supplierSelect)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      strings.queue.filters.allSuppliers,
      "Synthetic Alpha Building Supplies",
      "Synthetic Beta Traders",
      "Synthetic Gamma Hardware",
    ]);

    // --- The supplier name is a real link to the item; the rest of the row opens it too.
    const link = within(rows[0]!).getByRole("link");
    expect(link).toHaveAttribute("href", `/queue/${FIRST}`);
    fireEvent.click(link);
    expect(window.location.pathname).toBe(`/queue/${FIRST}`);
    fireEvent.click(within(rows[1]!).getByText(strings.queue.noAmount));
    expect(window.location.pathname).toBe(`/queue/${SECOND}`);

    // --- Pagination: the next page is asked for, with Previous and Next disabled
    // while it loads; an empty page with rows left goes back to the last page.
    const next = screen.getByRole("button", {
      name: strings.queue.pagination.next,
    });
    fireEvent.click(next);
    expect(next).toBeDisabled();
    expect(
      screen.getByRole("button", { name: strings.queue.pagination.previous }),
    ).toBeDisabled();
    await waitFor(() =>
      expect(requested().at(-1)?.searchParams.get("page")).toBe("1"),
    );
    expect(
      requested()
        .slice(-2)
        .map((url) => url.searchParams.get("page")),
    ).toEqual(["2", "1"]);
    rows = await screen.findAllByTestId("queue-row");
    expect(rows).toHaveLength(2);
    expect(screen.queryByText(strings.queue.empty)).not.toBeInTheDocument();

    // --- Filters: a change asks again from page 1 with the filter; nothing matching
    // reads "no match", not the empty queue.
    fireEvent.change(
      screen.getByLabelText(strings.queue.filters.reason, {
        selector: "select",
      }),
      { target: { value: "BANK_CHANGED" } },
    );
    await waitFor(() =>
      expect(requested().at(-1)?.searchParams.get("reason")).toBe(
        "BANK_CHANGED",
      ),
    );
    expect(requested().at(-1)?.searchParams.get("page")).toBe("1");
    expect(await screen.findByText(strings.queue.noMatch)).toBeInTheDocument();
    expect(screen.queryByText(strings.queue.empty)).not.toBeInTheDocument();
    fireEvent.change(
      screen.getByLabelText(strings.queue.filters.supplier, {
        selector: "select",
      }),
      { target: { value: BETA } },
    );
    await waitFor(() =>
      expect(requested().at(-1)?.searchParams.get("supplier_id")).toBe(BETA),
    );
    cleanup();

    // --- DB_OFFLINE is the shell's notice: no local error here.
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ code: "DB_OFFLINE", message: "offline" }), {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const offline = render(<QueueScreen />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: strings.errors.tryAgain }),
    ).not.toBeInTheDocument();
    offline.unmount();

    // --- Any other failure: an alert with the error, and Try again asks again.
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<QueueScreen />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      strings.errors.network,
    );
    fireEvent.click(
      screen.getByRole("button", { name: strings.errors.tryAgain }),
    );
    rows = await screen.findAllByTestId("queue-row");
    expect(rows).toHaveLength(2);
  });
});
