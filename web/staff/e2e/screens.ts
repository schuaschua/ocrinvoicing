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

export const SCREENS: Screen[] = [
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
