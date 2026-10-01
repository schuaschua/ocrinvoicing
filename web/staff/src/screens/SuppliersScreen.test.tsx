import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SupplierScreen } from "@/screens/SupplierScreen";
import { SuppliersScreen } from "@/screens/SuppliersScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

const ALPHA = "01a0c450-6c00-7b7b-8aa9-4ccade9f5526";
const BETA = "01a0c450-6fe8-7cb7-9e60-74d841e2024a";

function answer(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requested(): URL[] {
  return fetchMock.mock.calls.map(
    ([input]) => new URL(String(input), "http://localhost"),
  );
}

// Synthetic suppliers, by name as the API sends them.
const ALPHA_ROW = {
  supplier_id: ALPHA,
  name: "Synthetic Alpha Building Supplies",
};
const BETA_ROW = { supplier_id: BETA, name: "Synthetic Beta Hardware Trading" };

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/suppliers");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("4.4 suppliers list and supplier page", () => {
  it("lists suppliers by name with paging, searches from page 1, and links each row", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const q = url.searchParams.get("q");
      const page = Number(url.searchParams.get("page"));
      if (q === "zzz") {
        return answer({ items: [], page: 1, page_size: 50, total: 0 });
      }
      if (q !== null) {
        return answer({ items: [BETA_ROW], page: 1, page_size: 50, total: 1 });
      }
      return answer({
        items: page === 2 ? [BETA_ROW] : [ALPHA_ROW],
        page,
        page_size: 50,
        total: 51,
      });
    });
    render(<SuppliersScreen />);
    const rows = await screen.findAllByTestId("supplier-row");
    expect(document.title).toBe("Suppliers – Babaloo");
    expect(requested()[0]?.pathname).toBe("/api/suppliers");
    expect(requested()[0]?.searchParams.get("page")).toBe("1");
    expect(within(rows[0]!).getByRole("link")).toHaveAttribute(
      "href",
      `/suppliers/${ALPHA}`,
    );
    expect(screen.getByText("51 suppliers found")).toBeInTheDocument();

    // --- Paging: Next asks for page 2.
    fireEvent.click(
      screen.getByRole("button", { name: strings.suppliers.pagination.next }),
    );
    await screen.findByText(BETA_ROW.name);
    expect(requested().at(-1)?.searchParams.get("page")).toBe("2");

    // --- Search on Enter: trimmed, back to page 1, its own no-match copy.
    const box = screen.getByLabelText(strings.suppliers.searchLabel);
    fireEvent.change(box, { target: { value: "  beta " } });
    fireEvent.submit(box.closest("form")!);
    await waitFor(() =>
      expect(screen.getByText("1 supplier found")).toBeInTheDocument(),
    );
    expect(requested().at(-1)?.searchParams.get("q")).toBe("beta");
    expect(requested().at(-1)?.searchParams.get("page")).toBe("1");
    fireEvent.change(box, { target: { value: "zzz" } });
    fireEvent.click(
      screen.getByRole("button", { name: strings.suppliers.search }),
    );
    expect(
      await screen.findByText(strings.suppliers.noMatch),
    ).toBeInTheDocument();
  });

  it("shows the supplier's page with a Scorecard tab, or a not-found state", async () => {
    fetchMock.mockImplementation(async (input) =>
      String(input) === `/api/suppliers/${ALPHA}`
        ? answer(ALPHA_ROW)
        : answer({ code: "NOT_FOUND", message: "Not found." }, 404),
    );
    const found = render(<SupplierScreen supplierId={ALPHA} />);
    await screen.findByRole("heading", { level: 1, name: ALPHA_ROW.name });
    expect(
      screen.getByRole("link", { name: strings.suppliers.page.back }),
    ).toHaveAttribute("href", "/suppliers");
    const tab = screen.getByRole("tab", {
      name: strings.suppliers.page.tabs.scorecard,
    });
    expect(tab).toHaveAttribute("aria-selected", "true");
    expect(
      screen.getByRole("tabpanel", { name: "Scorecard" }),
    ).toHaveTextContent(strings.suppliers.page.scorecardComing);
    found.unmount();

    render(<SupplierScreen supplierId="no-such-supplier" />);
    expect(
      await screen.findByText(strings.suppliers.page.notFound),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });
});

describe("4.5 delivery dates on the supplier page", () => {
  it("switches to Deliveries by arrow key and URL, words the gaps, and shows an empty state", async () => {
    const late = {
      po_number: "PO-45012",
      delivery_no: 2,
      promised_date: "2026-09-12",
      delivered_date: "2026-09-14",
      received_date: "2026-09-15",
      days_late: 2,
      days_to_receive: 1,
      days_overall: 3,
    };
    const early = {
      ...late,
      delivery_no: 3,
      delivered_date: "2026-09-10",
      received_date: "2026-09-12",
      days_late: -2,
      days_to_receive: 2,
      days_overall: 0,
    };
    const pending = {
      ...late,
      po_number: "PO-45017",
      delivery_no: 1,
      received_date: null,
      days_late: 1,
      days_to_receive: null,
      days_overall: null,
    };
    const GAMMA = "01a0c450-73d0-7ee3-94ca-ef9fef9d793d";
    let alphaCalls = 0;
    fetchMock.mockImplementation(async (input) => {
      const path = String(input);
      if (path === `/api/suppliers/${ALPHA}`) return answer(ALPHA_ROW);
      if (path === `/api/suppliers/${BETA}`) return answer(BETA_ROW);
      if (path === `/api/suppliers/${GAMMA}`) {
        return answer({ supplier_id: GAMMA, name: "Synthetic Gamma" });
      }
      if (path === `/api/suppliers/${ALPHA}/deliveries`) {
        alphaCalls += 1;
        // The first call fails; the retry has more than the server sends.
        return alphaCalls === 1
          ? answer({ code: "INTERNAL", message: "Failed." }, 500)
          : answer({ items: [pending, late, early], truncated: true });
      }
      if (path === `/api/suppliers/${GAMMA}/deliveries`) {
        return answer({ code: "NOT_FOUND", message: "Not found." }, 404);
      }
      return answer({ items: [], truncated: false });
    });
    window.history.replaceState(null, "", `/suppliers/${ALPHA}`);
    const page = render(<SupplierScreen supplierId={ALPHA} />);
    const scorecard = await screen.findByRole("tab", {
      name: strings.suppliers.page.tabs.scorecard,
    });

    // --- Arrow right selects Deliveries, in the URL, and loads the table.
    scorecard.focus();
    fireEvent.keyDown(scorecard, { key: "ArrowRight" });
    const deliveriesTab = screen.getByRole("tab", {
      name: strings.suppliers.page.tabs.deliveries,
    });
    expect(deliveriesTab).toHaveAttribute("aria-selected", "true");
    expect(deliveriesTab).toHaveFocus();
    expect(window.location.search).toBe("?tab=deliveries");
    // --- A failed load: the alert, then Try again asks again and shows the rows.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      strings.errors.generic,
    );
    fireEvent.click(
      screen.getByRole("button", { name: strings.errors.tryAgain }),
    );
    const rows = await screen.findAllByTestId("delivery-row");
    expect(alphaCalls).toBe(2);
    expect(
      screen.getByText(strings.suppliers.deliveries.truncated(3)),
    ).toBeInTheDocument();
    expect(requested().at(-1)?.pathname).toBe(
      `/api/suppliers/${ALPHA}/deliveries`,
    );
    expect(rows.map((row) => row.textContent)).toEqual([
      "PO 45017#12026-09-122026-09-14—1 day late——",
      "PO 45012#22026-09-122026-09-142026-09-152 days late1 day3 days late",
      "PO 45012#32026-09-122026-09-102026-09-122 days early2 daysOn time",
    ]);

    // --- Back to Scorecard: the shell stays, the URL drops the tab.
    fireEvent.click(scorecard);
    expect(window.location.search).toBe("");
    expect(
      screen.getByRole("heading", { level: 1, name: ALPHA_ROW.name }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("delivery-row")).not.toBeInTheDocument();
    page.unmount();

    // --- Opened at ?tab=deliveries with none: the empty state, no "could-have".
    window.history.replaceState(null, "", `/suppliers/${BETA}?tab=deliveries`);
    render(<SupplierScreen supplierId={BETA} />);
    expect(
      await screen.findByText(strings.suppliers.deliveries.none),
    ).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/could/i);
    cleanup();

    // --- The supplier is gone by the time Deliveries loads: not found, no retry.
    window.history.replaceState(null, "", `/suppliers/${GAMMA}?tab=deliveries`);
    render(<SupplierScreen supplierId={GAMMA} />);
    expect(
      await screen.findByText(strings.suppliers.page.notFound),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: strings.errors.tryAgain }),
    ).not.toBeInTheDocument();
  });
});
