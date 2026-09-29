import { expect, test, type Page } from "@playwright/test";

import {
  applyTextSpacing,
  collectErrors,
  floorProblems,
  type Screen,
} from "./checks.ts";
// Every screen of this app; screen stories add theirs in the app's own screens.ts.
import { SCREENS } from "./screens.ts";

// The narrowest supported width, where reflow and tap targets are hardest to meet.
const VIEWPORTS = [{ name: "320px", width: 320, height: 640 }];

/** Answers the screen's API calls from its stubs; any other call is an error. */
async function stubApi(
  page: Page,
  screen: Screen,
  errors: string[],
): Promise<void> {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const answer = screen.api?.[path];
    if (answer === undefined) {
      errors.push(`unexpected API call: ${path}`);
      await route.abort();
      return;
    }
    if (answer === "hang") return; // never answered
    await route.fulfill({
      status: answer.status,
      contentType: "application/json",
      body: JSON.stringify(answer.body),
    });
  });
}

/** The browser logs a console error for each stubbed 4xx/5xx answer; those are expected. */
function expectedError(screen: Screen, text: string): boolean {
  return Object.values(screen.api ?? {}).some(
    (answer) =>
      answer !== "hang" &&
      answer.status >= 400 &&
      text.startsWith("Failed to load resource") &&
      text.includes(`status of ${answer.status}`),
  );
}

for (const screen of SCREENS) {
  for (const viewport of VIEWPORTS) {
    test(`${screen.story} ${screen.name} meets the accessibility floor at ${viewport.name}`, async ({
      page,
    }) => {
      const errors = collectErrors(page);
      await stubApi(page, screen, errors);
      await page.setViewportSize(viewport);
      await screen.setup?.(page);
      await page.goto(screen.path);
      await screen.steps?.(page);
      await expect(page.locator("html")).toHaveAttribute("lang", "en");
      await expect(page.getByRole("banner")).toContainText("Babaloo");
      if (screen.ready) {
        await expect(page.getByRole("main")).toContainText(screen.ready, {
          timeout: 10_000,
        });
      }

      expect(await floorProblems(page)).toEqual([]);

      await applyTextSpacing(page);
      expect(await floorProblems(page)).toEqual([]);
      expect(errors.filter((text) => !expectedError(screen, text))).toEqual([]);
    });
  }
}
