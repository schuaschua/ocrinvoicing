import {
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
