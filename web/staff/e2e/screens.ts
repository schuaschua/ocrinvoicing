// The staff app's screens for the accessibility check (e2e/a11y.spec.ts, shared with
// web/supplier). Screen stories add theirs here.
import type { Page } from "@playwright/test";

import type { ApiAnswer, Screen } from "./checks.ts";

/** `GET /api/me` for a user with these app roles (synthetic). */
function me(...roles: string[]): Record<string, ApiAnswer> {
  return { "/api/me": { status: 200, body: { name: "Priya Tan", roles } } };
}

/** Below 1024px the sidebar is a Sheet behind the Menu button: open it there. */
async function openMenuWhenNarrow(page: Page): Promise<void> {
  await page.getByRole("heading", { level: 1, name: "Watchlist" }).waitFor();
  const menu = page.getByRole("button", { name: "Menu" });
  if (await menu.isVisible()) {
    await menu.click();
    await page.getByRole("dialog", { name: "Babaloo" }).waitFor();
  }
}

/** Story 2.8: a populated admin queue (synthetic), with the page-cap Alert and pages. */
const ADMIN_QUEUE: Record<string, ApiAnswer> = {
  "/api/admin/queue": {
    status: 200,
    body: {
      items: [
        {
          invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000002",
          received_at: "2026-09-01T01:02:00+00:00",
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
          supplier_name: "Synthetic Alpha Building Supplies",
          amount: "1248.50",
          currency: "SGD",
          reasons: ["LOW_CONFIDENCE", "PO_MISMATCH"],
        },
        {
          invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000003",
          received_at: "2026-09-02T03:30:00+00:00",
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0",
          supplier_name: "Synthetic Beta Traders",
          amount: null,
          currency: null,
          reasons: ["BANK_CHANGED"],
        },
      ],
      page: 1,
      page_size: 50,
      total: 51,
      page_usage: { pages_used: 322, page_cap: 400 },
      suppliers: [
        {
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
          supplier_name: "Synthetic Alpha Building Supplies",
        },
        {
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0",
          supplier_name: "Synthetic Beta Traders",
        },
      ],
    },
  },
};

/** Story 2.9: an admin item with a bank change, its image and two flag boxes; Story
 * 2.10: its action bar; Story 3.3: Approve with the call-back checklist, the duplicate
 * comparison and the accounts error. */
const ITEM_ID = "0192f0c1-7a2b-7c3d-8e4f-000000000003";
const ITEM_PATH = `/api/admin/items/${ITEM_ID}`;
// A 1x1 PNG (synthetic): the viewer and its boxes render over it.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=",
  "base64",
);
const BOX = [100, 200, 400, 200, 400, 260, 100, 260];
const ADMIN_ITEM: Record<string, ApiAnswer> = {
  [ITEM_PATH]: {
    status: 200,
    body: {
      invoice_id: ITEM_ID,
      received_at: "2026-09-02T03:30:00+00:00",
      content_type: "image/png",
      image_available: true,
      supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0",
      supplier_name: "Synthetic Beta Traders",
      supplier_phone: "+65 6123 4567",
      reasons: [
        { code: "LOW_CONFIDENCE", field_ids: ["invoice_total"], detail: {} },
        { code: "BANK_CHANGED", field_ids: ["payment[0].iban"], detail: {} },
        {
          code: "DUPLICATE",
          field_ids: [],
          detail: {
            invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000001",
            basis: "phash",
          },
        },
        {
          code: "ACCOUNTS_API_ERROR",
          field_ids: [],
          detail: { status: 503, code: "SIMULATED_FAILURE" },
        },
      ],
      fields: [
        {
          field_id: "invoice_total",
          value: "1248.50",
          currency: "SGD",
          confidence: 0.91,
          page: 1,
          polygon: BOX,
          flagged: true,
          bank: false,
        },
        {
          field_id: "payment[0].iban",
          value: null,
          currency: null,
          confidence: 0.99,
          page: 1,
          polygon: [100, 900, 700, 900, 700, 960, 100, 960],
          flagged: true,
          bank: true,
        },
      ],
      lines: [
        {
          line_no: 1,
          product_code: "EVA-01",
          description: "EVA soles",
          quantity: "10",
          unit_price: "124.85",
          amount: "1248.50",
          confidence: 0.99,
        },
      ],
      pages: [{ page: 1, width: 1000, height: 1400, unit: "pixel" }],
      bank_changes: [
        { field_id: "payment[0].iban", on_file: "4821", new: "9930" },
      ],
      // Story 2.10: the action bar the open reasons allow; Story 3.3: Approve.
      allowed_actions: ["correct", "approve", "reject"],
      duplicate_of: {
        invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000001",
        received_at: "2026-08-28T02:00:00+00:00",
        content_type: "image/png",
        supplier_name: "Synthetic Beta Traders",
        invoice_total: "1248.50",
        currency: "SGD",
        image_available: true,
      },
    },
  },
};

/** The item's and the matching invoice's images are not JSON: answer them with the
 * PNG, ahead of the JSON stubs. */
async function itemImage(page: Page): Promise<void> {
  for (const path of [`${ITEM_PATH}/image`, `${ITEM_PATH}/duplicate/image`]) {
    await page.route(`**${path}`, (route) =>
      route.fulfill({ status: 200, contentType: "image/png", body: PNG }),
    );
  }
}

/** Story 3.4: invoice search results (synthetic), with statuses as labels. */
const INVOICES: Record<string, ApiAnswer> = {
  "/api/invoices": {
    status: 200,
    body: {
      items: [
        {
          invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000002",
          reference: "R-00000002",
          received_at: "2026-09-02T03:30:00+00:00",
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0",
          supplier_name: "Synthetic Beta Traders",
          invoice_number: "INV-002",
          amount: null,
          currency: null,
          status: "validating",
          after_correction: true,
        },
        {
          invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000001",
          reference: "R-00000001",
          received_at: "2026-09-01T01:02:00+00:00",
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
          supplier_name: "Synthetic Alpha Building Supplies",
          invoice_number: "INV 001",
          amount: "1248.50",
          currency: "SGD",
          status: "posted",
          after_correction: false,
        },
      ],
      page: 1,
      page_size: 50,
      total: 51,
      suppliers: [
        {
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
          supplier_name: "Synthetic Alpha Building Supplies",
        },
        {
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0",
          supplier_name: "Synthetic Beta Traders",
        },
      ],
    },
  },
};

/** Story 3.4: one invoice's detail (synthetic): bank fields only as on file. */
const DETAIL_ID = "0192f0c1-7a2b-7c3d-8e4f-000000000001";
const INVOICE_DETAIL: Record<string, ApiAnswer> = {
  [`/api/invoices/${DETAIL_ID}`]: {
    status: 200,
    body: {
      invoice_id: DETAIL_ID,
      reference: "R-00000001",
      received_at: "2026-09-01T01:02:00+00:00",
      supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
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
          from_status: "posting",
          to_status: "posted",
          at: "2026-09-01T03:00:00+00:00",
          actor: "post",
        },
      ],
    },
  },
};

/** Story 4.1: goods-in's delivery picker (synthetic), on a phone-width dock device. */
const GOODS_IN: Record<string, ApiAnswer> = {
  "/api/goods-in/deliveries": {
    status: 200,
    body: {
      today: "2026-09-29",
      items: [
        {
          delivery_id: "01a0c450-aa80-72d5-bb5c-e21dfa7e05aa",
          po_number: "PO-45016",
          delivery_no: 1,
          delivery_date: "2026-09-29",
          supplier_name: "Synthetic Gamma Construction Materials",
        },
        {
          delivery_id: "01a0c450-c1f0-7569-b3aa-76f1c8cc87a8",
          po_number: "PO-45017",
          delivery_no: 1,
          delivery_date: "2026-09-29",
          supplier_name: null,
        },
      ],
    },
  },
};

/** Story 5.4: the Watchlist (synthetic): a supplier listed for a price gap and
 * lateness, with read-only evidence and ranked alternatives. */
const WATCHLIST: Record<string, ApiAnswer> = {
  "/api/watchlist": {
    status: 200,
    body: {
      has_price_points: true,
      entries: [
        {
          supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0",
          supplier_name: "Synthetic Beta Traders",
          rules: [
            {
              rule: "late",
              first_added_on: "2026-10-01",
              avg_days_late: "8.00",
              evidence: [
                {
                  material_id: "0192f0c1-7a2b-7c3d-8e4f-0000000053c1",
                  material_name: "EVA soles",
                  received_date: "2026-09-28",
                  days_late: 8,
                },
              ],
            },
            {
              rule: "price_gap",
              first_added_on: "2026-10-01",
              avg_days_late: null,
              evidence: [
                {
                  material_id: "0192f0c1-7a2b-7c3d-8e4f-0000000053c1",
                  material_name: "EVA soles",
                  invoice_id: null,
                  invoice_date: "2026-09-20",
                  unit_price: "4.24",
                  lowest_unit_price: "4.00",
                  cheapest_supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
                  cheapest_supplier_name: "Synthetic Alpha Building Supplies",
                  pct: "6.00",
                },
              ],
            },
          ],
          alternatives: [
            {
              material_id: "0192f0c1-7a2b-7c3d-8e4f-0000000053c1",
              material_name: "EVA soles",
              suppliers: [
                {
                  supplier_id: "01a0c450-6c00-7b7b-8aa9-4ccade9f5526",
                  supplier_name: "Synthetic Alpha Building Supplies",
                  latest_unit_price: "4.00",
                  on_time_rate: "0.8000",
                  watchlisted: false,
                },
              ],
            },
          ],
        },
      ],
    },
  },
};

/** Story 5.3: Price comparison for a material (synthetic): the chart and its summary,
 * suppliers' prices and a price-rise alert whose evidence links (finance). */
const SOLES = "0192f0c1-7a2b-7c3d-8e4f-0000000053c1";
const ALPHA = "01a0c450-6c00-7b7b-8aa9-4ccade9f5526";
const BETA = "01a0c450-6c00-7b7b-8aa9-4ccade9f55b0";
const PRICE_COMPARISON: Record<string, ApiAnswer> = {
  "/api/materials": {
    status: 200,
    body: { items: [{ material_id: SOLES, name: "EVA soles" }] },
  },
  "/api/price-comparison": {
    status: 200,
    body: {
      material_id: SOLES,
      name: "EVA soles",
      suppliers: [
        {
          supplier_id: BETA,
          supplier_name: "Synthetic Beta Traders",
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
        { supplier_id: BETA, invoice_date: "2026-09-02", unit_price: "4.30" },
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
              invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000001",
              invoice_date: "2026-09-01",
              unit_price: "4.00",
            },
            {
              invoice_id: "0192f0c1-7a2b-7c3d-8e4f-000000000002",
              invoice_date: "2026-09-10",
              unit_price: "4.50",
            },
          ],
        },
      ],
    },
  },
};

export const SCREENS: Screen[] = [
  {
    story: "5.3",
    name: "price comparison with its chart and a price-rise alert",
    path: "/price-comparison",
    api: { ...me("finance"), ...PRICE_COMPARISON },
    ready: "lowest latest price S$4.20 from Synthetic Beta Traders",
  },
  {
    story: "4.1",
    name: "goods-in scan lists today's deliveries",
    path: "/goods-in",
    api: { ...me("goods_in"), ...GOODS_IN },
    ready: "Synthetic Gamma Construction Materials",
  },
  {
    story: "2.9",
    name: "admin item with a bank change and its actions",
    path: `/queue/${ITEM_ID}`,
    api: { ...me("admin"), ...ADMIN_ITEM },
    setup: itemImage,
    ready: "Call +65 6123 4567 (number on file)",
  },
  {
    story: "3.4",
    name: "invoice detail with bank details on file",
    path: `/invoices/${DETAIL_ID}`,
    api: { ...me("finance"), ...INVOICE_DETAIL },
    ready: "Bank details on file",
  },
  {
    story: "3.4",
    name: "finance searches all invoices",
    path: "/invoices",
    api: { ...me("finance"), ...INVOICES },
    ready: "Re-checking",
  },
  {
    story: "2.7",
    name: "admin and goods_in land on the admin queue",
    path: "/",
    api: { ...me("goods_in", "admin"), ...ADMIN_QUEUE },
    ready: "Synthetic Beta Traders",
  },
  {
    story: "2.7",
    name: "sidebar Sheet below 1024px",
    path: "/watchlist",
    api: { ...me("management", "procurement"), ...WATCHLIST },
    steps: openMenuWhenNarrow,
    ready: "Synthetic Beta Traders",
  },
  {
    story: "2.7",
    name: "session ended",
    path: "/invoices",
    api: {
      "/api/me": {
        status: 401,
        body: {
          code: "UNAUTHENTICATED",
          message: "Your session ended. Sign in again to continue.",
          correlation_id: "0199a1b2-0000-7000-8000-000000000011",
        },
      },
    },
    ready: "Your session ended. Sign in again to continue.",
  },
];
