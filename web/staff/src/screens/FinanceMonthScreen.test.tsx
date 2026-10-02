import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FinanceMonthScreen } from "@/screens/FinanceMonthScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

function answer(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// Synthetic suppliers, in the server's order (spend, then name).
const ALPHA = "01a0c450-6c00-7b7b-8aa9-4ccade9f5526";
const UNNAMED = "0192f0c1-7a2b-7c3d-8e4f-560000000003";
const HISTORY = [
  { month: "2026-08", share: "0.9500" },
  { month: "2026-09", share: "0.6667" },
];
const SEPTEMBER = {
  month: "2026-09",
  months: ["2026-09", "2026-08"],
  straight_through: {
    share: "0.6667",
    posted_count: 3,
    straight_through_count: 2,
    target: "0.9000",
  },
  history: HISTORY,
  suppliers: [
    {
      supplier_id: ALPHA,
      supplier_name: "Synthetic Alpha Building Supplies",
      spend: "1248.50",
      posted_count: 2,
      price_rises: 1,
      flagged_count: 1,
      duplicate_count: 0,
    },
    {
      supplier_id: UNNAMED,
      supplier_name: null,
      spend: "0.00",
      posted_count: 0,
      price_rises: 0,
      flagged_count: 1,
      duplicate_count: 2,
    },
  ],
};
const AUGUST = {
  ...SEPTEMBER,
  month: "2026-08",
  straight_through: {
    share: "0.9500",
    posted_count: 20,
    straight_through_count: 19,
    target: "0.9000",
  },
  suppliers: [],
};
const NOTHING = {
  month: "2026-10",
  months: [],
  straight_through: {
    share: null,
    posted_count: 0,
    straight_through_count: 0,
    target: "0.9000",
  },
  history: [],
  suppliers: [],
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/finance-month");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("5.6 Finance month", () => {
  it("states the share against the target in words, lists suppliers, switches month in the URL, summarises the chart with a table view, and says when there is no data", async () => {
    const s = strings.financeMonth;

    // --- The latest month: the share against the target, read as not met.
    fetchMock.mockResolvedValueOnce(answer(SEPTEMBER));
    render(<FinanceMonthScreen />);
    expect(
      await screen.findByText(/67% posted without an admin \(target 90%\)/),
    ).toHaveTextContent(s.notMet);
    expect(document.title).toBe("Finance month – Babaloo");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/finance-month");
    expect(screen.getByLabelText(s.month)).toHaveValue("2026-09");

    // --- The supplier table, in the server's order; no name reads as unknown.
    expect(
      screen.getAllByTestId("finance-row").map((row) => row.textContent),
    ).toEqual([
      "Synthetic Alpha Building SuppliesS$1,248.50110",
      `${s.unknownSupplier} 0003S$0.00012`,
    ]);

    // --- Each supplier links to its supplier page.
    expect(
      within(screen.getAllByTestId("finance-row")[0]!).getByRole("link", {
        name: "Synthetic Alpha Building Supplies",
      }),
    ).toHaveAttribute("href", `/suppliers/${ALPHA}`);
    expect(screen.getByText(s.note)).toBeInTheDocument();

    // --- The chart: a summary sentence above it, and every value as a table.
    const summary = screen.getByText(
      "September 2026: 67% posted without an admin, below the 90% target.",
    );
    const chart = screen.getByRole("img", { name: /September 2026: 67%/ });
    expect(
      summary.compareDocumentPosition(chart) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: strings.chart.viewTable }),
    );
    expect(
      screen.getAllByTestId("chart-row").map((row) => row.textContent),
    ).toEqual([
      `${s.shareSeries}2026-0895%`,
      `${s.shareSeries}2026-0967%`,
      `${s.targetSeries}2026-0890%`,
      `${s.targetSeries}2026-0990%`,
    ]);

    // --- Another month: asked for by month, kept in the URL; met reads as met.
    fetchMock.mockResolvedValueOnce(answer(AUGUST));
    fireEvent.change(screen.getByLabelText(s.month), {
      target: { value: "2026-08" },
    });
    expect(
      await screen.findByText(/95% posted without an admin \(target 90%\)/),
    ).toHaveTextContent(s.met);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "/api/finance-month?month=2026-08",
    );
    expect(window.location.search).toBe("?month=2026-08");
    expect(screen.getByText(s.empty)).toBeInTheDocument();

    // --- Started at a month in the URL: asked for and shown in the picker.
    cleanup();
    window.history.replaceState(null, "", "/finance-month?month=2026-08");
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce(answer(AUGUST));
    render(<FinanceMonthScreen />);
    await screen.findByText(/95% posted without an admin \(target/);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/finance-month?month=2026-08",
    );
    expect(screen.getByLabelText(s.month)).toHaveValue("2026-08");

    // --- A malformed month in the URL: refused, then the latest month, no alert.
    cleanup();
    window.history.replaceState(null, "", "/finance-month?month=bad");
    fetchMock.mockReset();
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            code: "VALIDATION_FAILED",
            message: "month must be a month as YYYY-MM.",
          }),
          { status: 400, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(answer(SEPTEMBER));
    render(<FinanceMonthScreen />);
    await screen.findByText(/67% posted without an admin \(target/);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe("/api/finance-month");
    expect(window.location.search).toBe("");
    expect(screen.queryByRole("alert")).toBeNull();

    // --- Just under the target never reads as the target.
    cleanup();
    window.history.replaceState(null, "", "/finance-month");
    fetchMock.mockReset();
    fetchMock.mockResolvedValueOnce(
      answer({
        ...SEPTEMBER,
        straight_through: { ...SEPTEMBER.straight_through, share: "0.8960" },
      }),
    );
    render(<FinanceMonthScreen />);
    const header = await screen.findByText(
      /89\.6% posted without an admin \(target 90%\)/,
    );
    expect(header).toHaveTextContent(s.notMet);
    expect(header).not.toHaveTextContent("90% posted");

    // --- No data at all: the empty line, no picker, no chart.
    cleanup();
    window.history.replaceState(null, "", "/finance-month");
    fetchMock.mockResolvedValueOnce(answer(NOTHING));
    render(<FinanceMonthScreen />);
    expect(await screen.findByText(s.empty)).toBeInTheDocument();
    expect(screen.queryByLabelText(s.month)).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
  });
});
