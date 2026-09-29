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

export const SCREENS: Screen[] = [
  {
    story: "2.7",
    name: "admin and goods_in land on the admin queue",
    path: "/",
    api: me("goods_in", "admin"),
    ready: "Admin queue",
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
