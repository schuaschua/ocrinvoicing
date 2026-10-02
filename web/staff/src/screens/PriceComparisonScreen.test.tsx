import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PriceComparisonScreen } from "@/screens/PriceComparisonScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

function answer(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// Synthetic suppliers and prices, in the server's order (latest price, then rate).
const ALPHA = "01a0c450-6c00-7b7b-8aa9-4ccade9f5526";
const BETA = "01a0c450-6fe8-7cb7-9e60-74d841e2024a";
const SOLES = "0192f0c1-7a2b-7c3d-8e4f-0000000053c1";
const INVOICE_1 = "0192f0c1-7a2b-7c3d-8e4f-000000000001";
const INVOICE_2 = "0192f0c1-7a2b-7c3d-8e4f-000000000002";
const LACES = "0192f0c1-7a2b-7c3d-8e4f-0000000053c2";
const MATERIALS = {
  items: [
    { material_id: SOLES, name: "EVA soles" },
    { material_id: LACES, name: "Laces" },
  ],
};
const COMPARISON = {
  material_id: SOLES,
  name: "EVA soles",
  suppliers: [
    {
      supplier_id: BETA,
      supplier_name: "Kowloon Soles",
      latest_unit_price: "4.20",
      latest_invoice_date: "2026-09-15",
      on_time_rate: null,
    },
    {
      supplier_id: ALPHA,
      supplier_name: "Synthetic Alpha Building Supplies",
      latest_unit_price: "4.50",
      latest_invoice_date: "2026-09-10",
      on_time_rate: "0.8000",
    },
  ],
  history: [
    { supplier_id: ALPHA, invoice_date: "2026-09-01", unit_price: "4.00" },
    { supplier_id: ALPHA, invoice_date: "2026-09-10", unit_price: "4.50" },
    { supplier_id: BETA, invoice_date: "2026-09-15", unit_price: "4.20" },
  ],
  alerts: [
    {
      alert_id: "0192f0c1-7a2b-7c3d-8e4f-0000000053d1",
      created_at: "2026-10-01T01:30:00+00:00",
      supplier_id: ALPHA,
      supplier_name: "Synthetic Alpha Building Supplies",
      pct: "12.50",
      evidence: [
        {
          invoice_id: INVOICE_1,
          invoice_date: "2026-09-01",
          unit_price: "4.00",
        },
        {
          invoice_id: INVOICE_2,
          invoice_date: "2026-09-10",
          unit_price: "4.50",
        },
      ],
    },
  ],
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/price-comparison");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("5.3 Price comparison", () => {
  it("summarises the chart, lists every point as a table, tells series apart, shows alerts with evidence, and says when there are no prices", async () => {
    const s = strings.priceComparison;

    // --- The first material's comparison, with a one-sentence summary above the chart.
    fetchMock
      .mockResolvedValueOnce(answer(MATERIALS))
      .mockResolvedValueOnce(answer(COMPARISON));
    render(<PriceComparisonScreen />);
    const summary = await screen.findByText(
      "EVA soles: lowest latest price S$4.20 from Kowloon Soles.",
    );
    expect(document.title).toBe("Price comparison – Babaloo");
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      `/api/price-comparison?material_id=${SOLES}`,
    );
    expect(screen.getByLabelText(s.material)).toHaveValue(SOLES);
    const chart = screen.getByRole("img", { name: /EVA soles: lowest/ });
    expect(
      summary.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // --- Series: a text label each and a distinct marker shape, not colour alone.
    const legend = screen.getByRole("list", { name: strings.chart.legend });
    const items = within(legend).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "Kowloon Soles",
      "Synthetic Alpha Building Supplies",
    ]);
    const shapes = items.map((item) =>
      item.querySelector("[data-marker]")?.getAttribute("data-marker"),
    );
    expect(new Set(shapes).size).toBe(2);
    expect(chart.querySelectorAll("[data-marker]")).toHaveLength(3);

    // --- Labelled ranges; dates sit in proportion to time (10 Sep is 9 of the 14
    // days from 1 Sep to 15 Sep).
    expect(
      screen.getByText(strings.chart.range("Price", "S$4.00", "S$4.50")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        strings.chart.range("Dates", "2026-09-01", "2026-09-15"),
      ),
    ).toBeInTheDocument();
    const centres = Array.from(chart.querySelectorAll("rect[data-marker]")).map(
      (mark) =>
        Number(mark.getAttribute("x")) + Number(mark.getAttribute("width")) / 2,
    );
    const beta = Number(
      chart.querySelector("circle[data-marker]")?.getAttribute("cx"),
    );
    const [start = 0, middle = 0] = centres;
    expect((middle - start) / (beta - start)).toBeCloseTo(9 / 14);

    // --- View as table lists every plotted value; and back.
    fireEvent.click(
      screen.getByRole("button", { name: strings.chart.viewTable }),
    );
    expect(
      screen.getAllByTestId("chart-row").map((row) => row.textContent),
    ).toEqual([
      "Kowloon Soles2026-09-15S$4.20",
      "Synthetic Alpha Building Supplies2026-09-01S$4.00",
      "Synthetic Alpha Building Supplies2026-09-10S$4.50",
    ]);
    expect(screen.queryByRole("img")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: strings.chart.viewChart }),
    );
    expect(screen.getByRole("img")).toBeInTheDocument();

    // --- Suppliers' latest prices and on-time rates.
    expect(
      screen.getAllByTestId("supplier-row").map((row) => row.textContent),
    ).toEqual([
      `Kowloon SolesS$4.202026-09-15${s.noRate}`,
      "Synthetic Alpha Building SuppliesS$4.502026-09-1080%",
    ]);

    // --- The alert with its evidence, each row linking to its invoice (finance).
    expect(
      screen.getByText(
        "Price rise: Synthetic Alpha Building Supplies, EVA soles +12.5%",
      ),
    ).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: s.openInvoice });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      `/invoices/${INVOICE_1}`,
      `/invoices/${INVOICE_2}`,
    ]);

    // --- Choosing another material fetches it and puts it in the URL; this one
    // has no price in the last 12 months.
    fetchMock.mockResolvedValueOnce(
      answer({
        material_id: LACES,
        name: "Laces",
        suppliers: [],
        history: [],
        alerts: [],
      }),
    );
    fireEvent.change(screen.getByLabelText(s.material), {
      target: { value: LACES },
    });
    expect(await screen.findByText(s.noRecent)).toBeInTheDocument();
    expect(String(fetchMock.mock.calls[2]?.[0])).toBe(
      `/api/price-comparison?material_id=${LACES}`,
    );
    expect(window.location.search).toBe(`?material_id=${LACES}`);
    expect(screen.queryByRole("img")).toBeNull();
    cleanup();

    // --- Opened with ?material_id= (an alert email's link): that material.
    fetchMock
      .mockResolvedValueOnce(answer(MATERIALS))
      .mockResolvedValueOnce(answer({ ...COMPARISON, material_id: LACES }));
    render(<PriceComparisonScreen />);
    await screen.findAllByTestId("supplier-row");
    expect(String(fetchMock.mock.calls[4]?.[0])).toBe(
      `/api/price-comparison?material_id=${LACES}`,
    );
    expect(screen.getByLabelText(s.material)).toHaveValue(LACES);
    cleanup();
    window.history.replaceState(null, "", "/price-comparison");

    // --- Procurement: the same evidence as read-only rows.
    const readOnly = {
      ...COMPARISON,
      alerts: COMPARISON.alerts.map((alert) => ({
        ...alert,
        evidence: alert.evidence.map((row) => ({ ...row, invoice_id: null })),
      })),
    };
    fetchMock
      .mockResolvedValueOnce(answer(MATERIALS))
      .mockResolvedValueOnce(answer(readOnly));
    render(<PriceComparisonScreen />);
    const rows = await screen.findAllByTestId("evidence-row");
    expect(rows.map((row) => row.textContent)).toEqual([
      `2026-09-01S$4.00${s.readOnly}`,
      `2026-09-10S$4.50${s.readOnly}`,
    ]);
    expect(screen.queryByRole("link")).toBeNull();
    cleanup();

    // --- Empty: no material has a posted price.
    fetchMock.mockResolvedValueOnce(answer({ items: [] }));
    render(<PriceComparisonScreen />);
    expect(await screen.findByText(s.empty)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(8);
    expect(screen.queryByRole("img")).toBeNull();
  });
});
