import { expect, test } from "@playwright/test";

import { applyTextSpacing, floorProblems } from "./checks.ts";

// The check itself must fail on a broken page, or a green run proves nothing.
test("1.4 the floor check reports axe, reflow and tap-target violations", async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 640 });
  await page.setContent(`<!doctype html>
    <html><head><title>Broken</title></head><body>
      <main>
        <img src="x.png">
        <div style="width: 1000px">wide</div>
        <button style="width: 20px; height: 20px">x</button>
      </main>
    </body></html>`);

  const problems = (await floorProblems(page)).join("\n");
  expect(problems).toContain("axe html-has-lang");
  expect(problems).toContain("axe image-alt");
  expect(problems).toContain("horizontal page scroll");
  expect(problems).toMatch(/tap target under 48px: <button> "x" is 20x20/);
});

test("1.4 the floor check reports a sticky header without scroll padding", async ({
  page,
}) => {
  await page.setContent(`<!doctype html>
    <html lang="en"><head><title>No padding</title></head><body>
      <header style="position: sticky; top: 0; height: 56px">Babaloo</header>
      <main><h1>Page</h1></main>
    </body></html>`);

  const problems = (await floorProblems(page)).join("\n");
  expect(problems).toContain("no scroll padding under the sticky header");
});

test("1.4 the floor check reports text clipped by the text-spacing override", async ({
  page,
}) => {
  await page.setContent(`<!doctype html>
    <html lang="en"><head><title>Clipped</title></head><body>
      <main>
        <p style="height: 18px; overflow: hidden; font-size: 16px; line-height: 1">
          Received
        </p>
      </main>
    </body></html>`);

  expect((await floorProblems(page)).join("\n")).not.toContain("text clipped");
  await applyTextSpacing(page);
  expect((await floorProblems(page)).join("\n")).toContain(
    'text clipped: <p> "Received"',
  );
});

test("1.4 the floor check exempts inline links in a sentence and hidden skip links", async ({
  page,
}) => {
  await page.setContent(`<!doctype html>
    <html lang="en"><head><title>Exempt</title></head><body>
      <a href="#main" style="position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%)">Skip to content</a>
      <main id="main">
        <p>Read the <a href="/help">help page</a> before you start.</p>
      </main>
    </body></html>`);

  expect(await floorProblems(page)).toEqual([]);
});

test("1.8 the floor check reports a capture button under 56px", async ({
  page,
}) => {
  await page.setContent(`<!doctype html>
    <html lang="en"><head><title>Capture</title></head><body>
      <main>
        <button data-capture style="height: 48px; width: 200px">Take photo</button>
        <button data-capture style="height: 56px; width: 200px">Choose file</button>
      </main>
    </body></html>`);

  const problems = await floorProblems(page);
  expect(problems).toEqual([
    'capture button under 56px: "Take photo" is 48px tall',
  ]);
});
