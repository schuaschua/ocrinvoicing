import { AxeBuilder } from "@axe-core/playwright";
import type { Page } from "@playwright/test";

// EXPERIENCE.md "Accessibility Floor" (UX-DR21), as far as a machine can check it.
export const AXE_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22a",
  "wcag22aa",
];
export const TAP_MIN_PX = 48;

// WCAG 1.4.12 text-spacing overrides (the W3C bookmarklet values).
export const TEXT_SPACING_CSS = `* {
  line-height: 1.5 !important;
  letter-spacing: 0.12em !important;
  word-spacing: 0.16em !important;
}
p { margin-bottom: 2em !important; }`;

const INTERACTIVE =
  "a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem], [tabindex]:not([tabindex='-1'])";

/** Every floor violation on the page as it is now; empty when it passes. */
export async function floorProblems(page: Page): Promise<string[]> {
  const problems: string[] = [];

  const axe = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  for (const violation of axe.violations) {
    problems.push(
      `axe ${violation.id}: ${violation.help} (${violation.nodes.length} element(s))`,
    );
  }

  const layout = await page.evaluate(
    ({ selector, min }) => {
      const found: string[] = [];
      const root = document.documentElement;
      // Data tables may scroll inside their own region; the page never may.
      if (root.scrollWidth > root.clientWidth) {
        found.push(
          `horizontal page scroll: content is ${root.scrollWidth}px wide in a ${root.clientWidth}px viewport`,
        );
      }
      // WCAG 2.5.8 inline exception: a link inside a sentence is sized by its text.
      const inSentence = (element: HTMLElement): boolean =>
        element.tagName === "A" &&
        getComputedStyle(element).display === "inline" &&
        Array.from(element.parentElement?.childNodes ?? []).some(
          (node) =>
            node !== element &&
            node.nodeType === Node.TEXT_NODE &&
            (node.textContent ?? "").trim() !== "",
        );
      for (const element of document.querySelectorAll<HTMLElement>(selector)) {
        const box = element.getBoundingClientRect();
        if (box.width === 0 && box.height === 0) continue; // not rendered
        // Visually hidden until focused (an sr-only skip link): not a target yet.
        const hidden = box.width <= 1 || box.height <= 1;
        if (hidden && element !== document.activeElement) continue;
        if (inSentence(element)) continue;
        if (box.width < min || box.height < min) {
          const name =
            element.getAttribute("aria-label") ??
            element.textContent?.trim() ??
            "";
          found.push(
            `tap target under ${min}px: <${element.tagName.toLowerCase()}> "${name}" is ${Math.round(box.width)}x${Math.round(box.height)}`,
          );
        }
      }
      const header = document.querySelector("header");
      if (header && getComputedStyle(header).position === "sticky") {
        const padding = parseFloat(getComputedStyle(root).scrollPaddingTop);
        const height = header.getBoundingClientRect().height;
        if (!Number.isFinite(padding)) {
          found.push(
            `no scroll padding under the sticky header (${height}px): scroll-padding-top is "${getComputedStyle(root).scrollPaddingTop}"`,
          );
        } else if (Math.abs(padding - height) > 0.5) {
          found.push(
            `scroll padding (${padding}px) does not equal the sticky header height (${height}px)`,
          );
        }
      }
      // WCAG 1.4.12: text must not be cut off, e.g. after the text-spacing override.
      for (const element of document.body.querySelectorAll<HTMLElement>("*")) {
        const own = element.getBoundingClientRect();
        if (own.width <= 1 || own.height <= 1) continue; // visually hidden on purpose
        const style = getComputedStyle(element);
        const clips = [style.overflowX, style.overflowY].some(
          (value) => value === "hidden" || value === "clip",
        );
        if (
          clips &&
          (element.textContent ?? "").trim() !== "" &&
          (element.scrollHeight > element.clientHeight + 1 ||
            element.scrollWidth > element.clientWidth + 1)
        ) {
          found.push(
            `text clipped: <${element.tagName.toLowerCase()}> "${(element.textContent ?? "").trim().slice(0, 40)}" overflows its ${element.clientWidth}x${element.clientHeight} box`,
          );
        }
      }
      return found;
    },
    { selector: INTERACTIVE, min: TAP_MIN_PX },
  );
  return [...problems, ...layout];
}

/**
 * Applies the text-spacing overrides as a user stylesheet would. A constructed
 * stylesheet, because the page's CSP (rightly) blocks an injected <style>.
 */
export async function applyTextSpacing(page: Page): Promise<void> {
  await page.evaluate((css) => {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  }, TEXT_SPACING_CSS);
}

/** Collects console errors and uncaught exceptions (a CSP violation logs one). */
export function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  return errors;
}
