import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ItemScreen } from "@/screens/ItemScreen";
import { strings } from "@/strings";

const fetchMock = vi.fn<typeof fetch>();
const ID = "0192f0c1-7a2b-7c3d-8e4f-000000000001";
const BOX_A = [100, 200, 400, 200, 400, 260, 100, 260];
const BOX_B = [500, 700, 900, 700, 900, 780, 500, 780];

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
function item(extra: Record<string, unknown> = {}) {
  return {
    invoice_id: ID,
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
    fields: [
      field("invoice_date", { value: "2026-09-29", confidence: 1 }),
      field("invoice_total", {
        value: "109.00",
        currency: "SGD",
        confidence: 0.91,
        page: 1,
        polygon: BOX_A,
        flagged: true,
      }),
      field("vendor_name", {
        value: "Synthetic Kowloon Soles",
        page: 1,
        polygon: BOX_B,
        flagged: true,
      }),
    ],
    lines: [],
    pages: [{ page: 1, width: 1000, height: 1400, unit: "pixel" }],
    bank_changes: [],
    ...extra,
  };
}

function stage(): HTMLElement {
  return screen.getByTestId("viewer-stage");
}

function scale(): number {
  const match = /scale\(([\d.]+)\)/.exec(stage().style.transform);
  return Number(match?.[1]);
}

function fieldButton(name: RegExp): HTMLElement {
  return screen.getByRole("button", { name });
}

async function announced(text: string) {
  await waitFor(() =>
    expect(screen.getByTestId("item-announcer")).toHaveTextContent(text),
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("2.9 admin item", () => {
  it("opens zoomed to the first flag, steps, zooms out and links fields and boxes", async () => {
    fetchMock.mockImplementation(async () => answer(item()));
    const view = render(<ItemScreen invoiceId={ID} />);
    const total = await screen.findByRole("button", {
      name: /Box 1: Invoice total/,
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(`/api/admin/items/${ID}`);
    expect(document.title).toBe("Admin item – Babaloo");
    const image = screen.getByRole("img", {
      name: strings.item.viewer.imageAlt,
    });
    expect(image).toHaveAttribute("src", `/api/admin/items/${ID}/image`);

    // Zoomed to the first flagged box, which is selected (4px) and numbered.
    expect(total).toHaveAttribute("aria-pressed", "true");
    expect(scale()).toBeGreaterThan(1);
    expect(stage().className).toContain("transition-transform");
    const boxes = screen.getAllByTestId("flag-box");
    expect(
      boxes.map((b) =>
        b.querySelector("[data-number]")?.getAttribute("data-number"),
      ),
    ).toEqual(["1", "2"]);
    expect(boxes[0]).toHaveAttribute("data-selected", "true");
    expect(boxes[0]?.style.borderWidth).toBe(`${4 / scale()}px`);
    // The confidence badge (below 98 %) and the flag state; admin rows count 1.0.
    const totalRow = total.closest("li") as HTMLElement;
    expect(totalRow).toHaveTextContent("Confidence 91%");
    expect(totalRow).toHaveTextContent(strings.item.fields.flagged);
    expect(totalRow).toHaveTextContent("SGD 109.00");
    const dateRow = fieldButton(/Invoice date/).closest("li") as HTMLElement;
    expect(dateRow).not.toHaveTextContent("Confidence");

    // Next and Previous step between the flags, announced.
    fireEvent.click(screen.getByRole("button", { name: "Next flag" }));
    expect(fieldButton(/Supplier name/)).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Flag 2 of 2")).toBeInTheDocument();
    await announced("Flag 2 of 2: Supplier name");
    fireEvent.click(screen.getByRole("button", { name: "Next flag" }));
    expect(total).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Previous flag" }));
    expect(fieldButton(/Supplier name/)).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Show whole invoice; zoom and pan buttons.
    fireEvent.click(screen.getByRole("button", { name: "Show whole invoice" }));
    expect(stage().style.transform).toBe("translate(0%, 0%) scale(1)");
    fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
    expect(scale()).toBe(1.5);
    fireEvent.click(screen.getByRole("button", { name: "Pan right" }));
    expect(stage().style.transform).toBe("translate(-50%, -25%) scale(1.5)");
    fireEvent.click(screen.getByRole("button", { name: "Pan up" }));
    fireEvent.click(screen.getByRole("button", { name: "Pan left" }));
    fireEvent.click(screen.getByRole("button", { name: "Pan down" }));
    fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
    expect(stage().style.transform).toBe("translate(0%, 0%) scale(1)");

    // A box focuses its field; a field highlights its box (and zooms to it).
    fireEvent.click(screen.getAllByTestId("flag-box")[0] as HTMLElement);
    expect(total).toHaveFocus();
    expect(total).toHaveAttribute("aria-pressed", "true");
    await announced("Selected: Invoice total");
    fireEvent.click(fieldButton(/Supplier name/));
    expect(screen.getAllByTestId("flag-box")[1]).toHaveAttribute(
      "data-selected",
      "true",
    );
    expect(scale()).toBeGreaterThan(1);
    // A field without a region has no box.
    fireEvent.click(fieldButton(/Invoice date/));
    expect(
      screen
        .getAllByTestId("flag-box")
        .map((b) => b.getAttribute("data-selected")),
    ).toEqual(["false", "false"]);
    // No box selected: the position says so, never "Flag 1 of 2".
    expect(screen.getByText("No flag selected (2 flags)")).toBeInTheDocument();
    expect(screen.queryByText("Flag 1 of 2")).not.toBeInTheDocument();
    view.unmount();

    // Reduced motion: no zoom animation.
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("reduce"),
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    const reduced = render(<ItemScreen invoiceId={ID} />);
    await screen.findByRole("button", { name: /Box 1: Invoice total/ });
    expect(stage().className).not.toContain("transition");
    reduced.unmount();

    // No page sizes (a run before this story): fields, no boxes, whole image.
    fetchMock.mockImplementation(async () => answer(item({ pages: [] })));
    const noSizes = render(<ItemScreen invoiceId={ID} />);
    await screen.findByText(strings.item.viewer.noBoxes);
    expect(screen.queryAllByTestId("flag-box")).toEqual([]);
    expect(scale()).toBe(1);
    noSizes.unmount();

    // Image deleted after 30 days: the placeholder, and the fields still show.
    fetchMock.mockImplementation(async () =>
      answer(item({ image_available: false })),
    );
    const deleted = render(<ItemScreen invoiceId={ID} />);
    await screen.findByText(strings.item.viewer.deleted);
    expect(fieldButton(/Invoice total/)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    deleted.unmount();

    // A PDF: a link to the stream, the field list, no boxes.
    fetchMock.mockImplementation(async () =>
      answer(item({ content_type: "application/pdf" })),
    );
    const pdf = render(<ItemScreen invoiceId={ID} />);
    const link = await screen.findByRole("link", { name: "Open the PDF" });
    expect(link).toHaveAttribute("href", `/api/admin/items/${ID}/image`);
    expect(screen.queryAllByTestId("flag-box")).toEqual([]);
    expect(fieldButton(/Invoice total/)).toBeInTheDocument();
    pdf.unmount();

    // Not in the queue any more: 404.
    fetchMock.mockImplementation(async () =>
      answer({ code: "NOT_FOUND", message: "Not found." }, 404),
    );
    const gone = render(<ItemScreen invoiceId={ID} />);
    expect(await screen.findByText(strings.item.notFound)).toBeInTheDocument();
    gone.unmount();

    // Signed out (401): the shell's dialog says why; the screen offers Try again,
    // with no alert of its own, and trying again loads the item.
    fetchMock.mockImplementation(async () =>
      answer({ code: "UNAUTHENTICATED", message: "Signed out." }, 401),
    );
    render(<ItemScreen invoiceId={ID} />);
    const again = await screen.findByRole("button", {
      name: strings.errors.tryAgain,
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("item-loading")).not.toBeInTheDocument();
    fetchMock.mockImplementation(async () => answer(item()));
    fireEvent.click(again);
    expect(
      await screen.findByRole("button", { name: /Box 1: Invoice total/ }),
    ).toBeInTheDocument();
  });

  it("shows the bank change masked, reveals for 30 s with a warning and hides", async () => {
    const reveals: RequestInit[] = [];
    // The next reveal's answer: at once (null), held until released, or a 503.
    let next: null | "fail" | Promise<void> = null;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/bank/reveal")) {
        reveals.push(init ?? {});
        if (next === "fail") {
          return answer(
            { code: "SERVICE_UNAVAILABLE", message: "Try again later." },
            503,
          );
        }
        if (next !== null) await next;
        return answer({
          field_id: "payment[0].iban",
          which: "new",
          value: "SG12ABCD00009930",
        });
      }
      return answer(
        item({
          supplier_phone: "+65 6123 4567",
          reasons: [{ code: "BANK_CHANGED", field_ids: ["payment[0].iban"] }],
          fields: [
            field("payment[0].iban", {
              page: 1,
              polygon: BOX_A,
              flagged: true,
              bank: true,
            }),
          ],
          bank_changes: [
            { field_id: "payment[0].iban", on_file: null, new: "9930" },
          ],
        }),
      );
    });
    render(<ItemScreen invoiceId={ID} />);
    const panel = (
      await screen.findByRole("heading", { name: "Bank details changed" })
    ).closest("section") as HTMLElement;
    expect(panel).toHaveTextContent("Call +65 6123 4567 (number on file)");
    expect(panel).toHaveTextContent(strings.item.bank.noAccount);
    expect(within(panel).getByText("account ending 9930")).toBeInTheDocument();
    expect(screen.queryByText("SG12ABCD00009930")).not.toBeInTheDocument();

    // Show: POST reveal (with the CSRF header), and the value shows.
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const show = within(panel).getByRole("button", {
      name: "Show account ending 9930",
    });
    await act(async () => {
      fireEvent.click(show);
    });
    expect(within(panel).getByText("SG12ABCD00009930")).toBeVisible();
    expect(reveals).toHaveLength(1);
    expect(reveals[0]?.method).toBe("POST");
    expect(JSON.parse(String(reveals[0]?.body))).toEqual({
      field_id: "payment[0].iban",
      which: "new",
    });
    expect(
      (reveals[0]?.headers as Record<string, string>)["X-Requested-With"],
    ).toBe("XMLHttpRequest");

    // At 20 s: the announced warning with Keep showing.
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByTestId("item-announcer")).toHaveTextContent(
      strings.item.bank.warning,
    );
    // Keep showing reveals again (audited again) and restarts the 30 s.
    await act(async () => {
      fireEvent.click(
        within(panel).getByRole("button", { name: "Keep showing" }),
      );
    });
    expect(reveals).toHaveLength(2);
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    expect(within(panel).getByText("SG12ABCD00009930")).toBeInTheDocument();
    // 30 s after the last reveal: hidden, and announced.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("SG12ABCD00009930")).not.toBeInTheDocument();
    expect(screen.getByTestId("item-announcer")).toHaveTextContent(
      strings.item.bank.hidden,
    );

    // Hide: at once, and announced.
    await act(async () => {
      fireEvent.click(
        within(panel).getByRole("button", { name: "Show account ending 9930" }),
      );
    });
    expect(within(panel).getByText("SG12ABCD00009930")).toBeInTheDocument();
    act(() => {
      fireEvent.click(within(panel).getByRole("button", { name: "Hide" }));
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("SG12ABCD00009930")).not.toBeInTheDocument();
    expect(screen.getByTestId("item-announcer")).toHaveTextContent(
      strings.item.bank.hidden,
    );
    expect(reveals).toHaveLength(3);

    // A Keep showing still in flight when the 30 s hide fires: its late answer is
    // dropped, so the value never comes back after "hidden" was announced.
    await act(async () => {
      fireEvent.click(
        within(panel).getByRole("button", { name: "Show account ending 9930" }),
      );
    });
    act(() => {
      vi.advanceTimersByTime(20_000);
    });
    let release: () => void = () => undefined;
    next = new Promise<void>((resolve) => {
      release = resolve;
    });
    act(() => {
      fireEvent.click(
        within(panel).getByRole("button", { name: "Keep showing" }),
      );
    });
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText("SG12ABCD00009930")).not.toBeInTheDocument();
    expect(screen.getByTestId("item-announcer")).toHaveTextContent(
      strings.item.bank.hidden,
    );
    await act(async () => {
      release();
      await next;
    });
    expect(screen.queryByText("SG12ABCD00009930")).not.toBeInTheDocument();
    expect(reveals).toHaveLength(5);

    // A reveal that fails (503): announced, nothing shown, and Show still works.
    next = "fail";
    await act(async () => {
      fireEvent.click(
        within(panel).getByRole("button", { name: "Show account ending 9930" }),
      );
    });
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByTestId("item-announcer")).toHaveTextContent(
      strings.item.bank.failed,
    );
    expect(screen.queryByText("SG12ABCD00009930")).not.toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Show account ending 9930" }),
    ).toBeEnabled();
    expect(reveals).toHaveLength(6);
  });
});
