import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { WatchlistScreen } from "@/screens/WatchlistScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

function answer(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// Synthetic suppliers and materials, in the server's order.
const ALPHA = "01a0c450-6c00-7b7b-8aa9-4ccade9f5526";
const KOWLOON = "01a0c450-6fe8-7cb7-9e60-74d841e2024a";
const NEW = "0192f0c1-7a2b-7c3d-8e4f-0000000054e1";
const SOLES = "0192f0c1-7a2b-7c3d-8e4f-0000000053c1";
const LACES = "0192f0c1-7a2b-7c3d-8e4f-0000000053c2";
const INVOICE = "0192f0c1-7a2b-7c3d-8e4f-000000000009";

function rise(date: string, previous: string, price: string, pct: string) {
  return {
    material_id: SOLES,
    material_name: "EVA soles",
    invoice_id: null,
    invoice_date: date,
    unit_price: price,
    previous_invoice_id: null,
    previous_invoice_date: "2026-08-01",
    previous_unit_price: previous,
    pct,
  };
}

const WATCHLIST = {
  has_price_points: true,
  entries: [
    {
      supplier_id: KOWLOON,
      supplier_name: "Kowloon Soles",
      rules: [
        {
          rule: "price_rises",
          first_added_on: "2026-10-06",
          avg_days_late: null,
          evidence: [
            rise("2026-09-20", "4.20", "4.30", "2.38"),
            rise("2026-09-15", "4.10", "4.20", "2.44"),
            rise("2026-09-10", "4.00", "4.10", "2.50"),
          ],
        },
        {
          rule: "price_gap",
          first_added_on: "2026-10-01",
          avg_days_late: null,
          evidence: [
            {
              material_id: SOLES,
              material_name: "EVA soles",
              // As a user who can open invoices (also finance) gets it.
              invoice_id: INVOICE,
              invoice_date: "2026-09-20",
              unit_price: "4.24",
              lowest_unit_price: "4.00",
              cheapest_supplier_id: ALPHA,
              cheapest_supplier_name: "Synthetic Alpha Building Supplies",
              pct: "6.00",
            },
          ],
        },
      ],
      alternatives: [
        {
          material_id: SOLES,
          material_name: "EVA soles",
          suppliers: [
            {
              supplier_id: ALPHA,
              supplier_name: "Synthetic Alpha Building Supplies",
              latest_unit_price: "4.00",
              on_time_rate: "0.8000",
              watchlisted: true,
            },
            {
              supplier_id: NEW,
              supplier_name: null,
              latest_unit_price: "4.10",
              on_time_rate: null,
              watchlisted: false,
            },
          ],
        },
      ],
    },
    {
      supplier_id: ALPHA,
      supplier_name: "Synthetic Alpha Building Supplies",
      rules: [
        {
          rule: "late",
          first_added_on: "2026-10-01",
          avg_days_late: "8.00",
          evidence: [
            {
              material_id: LACES,
              material_name: "Laces",
              received_date: "2026-09-28",
              days_late: 9,
            },
          ],
        },
        // A rule this page doesn't know yet: skipped, the rest still shown.
        {
          rule: "future_rule",
          first_added_on: "2026-10-01",
          avg_days_late: null,
          evidence: [],
        },
      ],
      alternatives: [
        { material_id: LACES, material_name: "Laces", suppliers: [] },
      ],
    },
  ],
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("5.4 Watchlist", () => {
  it("shows a card per supplier with its rules in plain words, read-only evidence and ranked alternatives, and both empty states", async () => {
    const s = strings.watchlist;

    // --- A card per supplier, in the server's order, rules in plain words.
    fetchMock.mockResolvedValueOnce(answer(WATCHLIST));
    render(<WatchlistScreen />);
    const cards = await screen.findAllByTestId("watchlist-card");
    expect(document.title).toBe("Watchlist – Babaloo");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/watchlist");
    expect(
      cards.map(
        (card) => within(card).getByRole("heading", { level: 2 }).textContent,
      ),
    ).toEqual(["Kowloon Soles", "Synthetic Alpha Building Supplies"]);
    const [kowloon, alpha] = cards as [HTMLElement, HTMLElement];
    expect(
      within(kowloon)
        .getAllByRole("heading", { level: 3 })
        .map((h) => h.textContent),
    ).toEqual([
      "3 price rises in the last 12 months",
      "EVA soles 6% above the cheapest supplier",
      s.alternativesHeading,
    ]);
    expect(
      within(kowloon).getByText(s.since("2026-10-06")),
    ).toBeInTheDocument();
    expect(
      within(alpha).getByRole("heading", { name: "On average 8 days late" }),
    ).toBeInTheDocument();

    // --- Evidence as read-only rows (no invoice for these roles).
    const rises = within(
      within(kowloon).getByRole("table", {
        name: s.evidenceLabel(
          "Kowloon Soles",
          "3 price rises in the last 12 months",
        ),
      }),
    ).getAllByTestId("evidence-row");
    expect(rises.map((row) => row.textContent)).toEqual([
      `EVA soles2026-09-20S$4.20S$4.30+2.38%${s.readOnly}`,
      `EVA soles2026-09-15S$4.10S$4.20+2.44%${s.readOnly}`,
      `EVA soles2026-09-10S$4.00S$4.10+2.5%${s.readOnly}`,
    ]);
    expect(
      within(alpha)
        .getAllByTestId("evidence-row")
        .map((row) => row.textContent),
    ).toEqual(["Laces2026-09-289"]);
    expect(within(alpha).getAllByRole("heading", { level: 3 })).toHaveLength(2);
    expect(kowloon).toHaveTextContent(
      "EVA soles2026-09-20S$4.24S$4.00Synthetic Alpha Building Supplies",
    );
    // Only the evidence row with an invoice id links to it.
    expect(
      screen
        .getAllByRole("link", { name: s.openInvoice })
        .map((link) => link.getAttribute("href")),
    ).toEqual([`/invoices/${INVOICE}`]);

    // --- Alternatives per material, in the server's ranking; none for Laces.
    expect(
      within(kowloon)
        .getAllByTestId("alternative-row")
        .map((row) => row.textContent),
    ).toEqual([
      `Synthetic Alpha Building Supplies${s.onWatchlist}S$4.0080%`,
      `${s.unknownSupplier} 54e1S$4.10${s.noRate}`,
    ]);
    expect(within(alpha).getByText(s.noAlternatives)).toBeInTheDocument();
    cleanup();

    // --- Opened from an email's `#supplier-<id>` link: that card scrolled to and
    // its heading focused once the data is shown.
    const scrolled = vi.fn();
    Element.prototype.scrollIntoView = scrolled;
    window.history.replaceState(null, "", `/watchlist#supplier-${ALPHA}`);
    fetchMock.mockResolvedValueOnce(answer(WATCHLIST));
    render(<WatchlistScreen />);
    const target = await screen.findByRole("heading", {
      level: 2,
      name: "Synthetic Alpha Building Supplies",
    });
    expect(target).toHaveFocus();
    expect(scrolled.mock.contexts[0]).toBe(
      document.getElementById(`supplier-${ALPHA}`),
    );
    window.history.replaceState(null, "", "/watchlist");
    cleanup();

    // --- No price points at all.
    fetchMock.mockResolvedValueOnce(
      answer({ has_price_points: false, entries: [] }),
    );
    render(<WatchlistScreen />);
    expect(await screen.findByText(s.empty)).toBeInTheDocument();
    expect(screen.queryByText(s.none)).toBeNull();
    cleanup();

    // --- Price points, but nobody listed.
    fetchMock.mockResolvedValueOnce(
      answer({ has_price_points: true, entries: [] }),
    );
    render(<WatchlistScreen />);
    expect(await screen.findByText(s.none)).toBeInTheDocument();
    expect(screen.queryByText(s.empty)).toBeNull();
    expect(screen.queryByTestId("watchlist-card")).toBeNull();
  });
});
