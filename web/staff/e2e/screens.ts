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
 * 2.10: its action bar. */
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
      // Story 2.10: the action bar the open reasons allow.
      allowed_actions: ["correct", "reject"],
    },
  },
};

/** The item's image is not JSON: answer it with the PNG, ahead of the JSON stubs. */
async function itemImage(page: Page): Promise<void> {
  await page.route(`**${ITEM_PATH}/image`, (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: PNG }),
  );
}

export const SCREENS: Screen[] = [
  {
    story: "2.9",
    name: "admin item with a bank change and its actions",
    path: `/queue/${ITEM_ID}`,
    api: { ...me("admin"), ...ADMIN_ITEM },
    setup: itemImage,
    ready: "Call +65 6123 4567 (number on file)",
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
    api: me("management", "procurement"),
    steps: openMenuWhenNarrow,
    ready: "Watchlist",
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
