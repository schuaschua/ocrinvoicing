import { expect, test } from "@playwright/test";

import { applyTextSpacing, collectErrors, floorProblems } from "./checks.ts";

// Every screen of the app; screen stories add theirs here.
const SCREENS = [{ name: "shell", path: "/" }];
const VIEWPORTS = [
  { name: "320px", width: 320, height: 640 },
  { name: "desktop", width: 1280, height: 800 },
];

for (const screen of SCREENS) {
  for (const viewport of VIEWPORTS) {
    test(`1.4 ${screen.name} meets the accessibility floor at ${viewport.name}`, async ({
      page,
    }) => {
      const errors = collectErrors(page);
      await page.setViewportSize(viewport);
      await page.goto(screen.path);
      await expect(page.locator("html")).toHaveAttribute("lang", "en");
      await expect(page.getByRole("banner")).toContainText("Babaloo");

      expect(await floorProblems(page)).toEqual([]);

      await applyTextSpacing(page);
      expect(await floorProblems(page)).toEqual([]);
      expect(errors).toEqual([]);
    });
  }
}
