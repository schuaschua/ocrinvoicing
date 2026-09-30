import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OverduePosScreen } from "@/screens/OverduePosScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();

function answer(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

// 01:30 on 28 Sep in Singapore, still 27 Sep in UTC and westward: the list shows
// Singapore's date whatever the viewer's time zone.
const MADE_AT = "2026-09-27T17:30:00+00:00";

// Synthetic POs (backend/seed/sim_purchasing.json), as the API groups them.
const LIST = {
  made_at: MADE_AT,
  suppliers: [
    {
      supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
      supplier_name: "Synthetic Alpha Building Supplies",
      pos: [
        { po_number: "PO-45012", expected_date: "2026-09-01" },
        { po_number: "PO-45017", expected_date: "2026-09-25" },
      ],
    },
    {
      supplier_id: "0192f0c1-7a2b-7c3d-8e4f-0000000000ee",
      supplier_name: null,
      pos: [{ po_number: "PO-45015", expected_date: "2026-09-15" }],
    },
  ],
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/overdue-pos");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("4.2 Overdue POs", () => {
  it("groups overdue POs by supplier with the list's date, and says when none are overdue or the list isn't made yet", async () => {
    const s = strings.overdue;

    // --- Grouped by supplier, with the date the list was made.
    fetchMock.mockResolvedValueOnce(answer(LIST));
    render(<OverduePosScreen />);
    const alpha = await screen.findByRole("region", {
      name: "Synthetic Alpha Building Supplies",
    });
    expect(document.title).toBe("Overdue POs – Babaloo");
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe("/api/overdue-pos");
    expect(screen.getByText(s.asOf("2026-09-28"))).toBeInTheDocument();
    const rows = within(alpha).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "PO 450122026-09-01",
      "PO 450172026-09-25",
    ]);
    const unknown = screen.getByRole("region", { name: s.unknownSupplier });
    expect(unknown).toHaveTextContent("PO 45015");
    expect(unknown).not.toHaveTextContent("PO 45012");
    cleanup();

    // --- Made, none overdue: says so, with the date.
    fetchMock.mockResolvedValueOnce(
      answer({ made_at: MADE_AT, suppliers: [] }),
    );
    render(<OverduePosScreen />);
    expect(await screen.findByText(s.none)).toBeInTheDocument();
    expect(screen.getByText(s.asOf("2026-09-28"))).toBeInTheDocument();
    expect(screen.queryByRole("region")).toBeNull();
    cleanup();

    // --- Never made: when it will be.
    fetchMock.mockResolvedValueOnce(answer({ made_at: null, suppliers: [] }));
    render(<OverduePosScreen />);
    expect(await screen.findByText(s.neverMade)).toBeInTheDocument();
    expect(screen.queryByText(s.none)).toBeNull();
  });
});
