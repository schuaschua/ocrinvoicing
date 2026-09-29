import { expect, test } from "@playwright/test";

import { floorProblems } from "./checks.ts";

// The check itself must fail on a broken page, or a green run proves nothing.
test("1.4 the floor check reports axe, reflow, tap-target and capture-size violations", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.setContent(`<!doctype html>
    <html><head><title>Broken</title></head><body>
      <main>
        <img src="x.png">
        <div style="width: 1000px">wide</div>
        <button style="width: 20px; height: 20px">x</button>
        <button data-capture style="height: 48px; width: 200px">Take photo</button>
      </main>
    </body></html>`);

  const problems = (await floorProblems(page)).join("\n");
  expect(problems).toContain("axe html-has-lang");
  expect(problems).toContain("axe image-alt");
  expect(problems).toContain("horizontal page scroll");
  expect(problems).toMatch(/tap target under 48px: <button> "x" is 20x20/);
  // 1.8: a capture button needs 56px.
  expect(problems).toContain(
    'capture button under 56px: "Take photo" is 48px tall',
  );
});
