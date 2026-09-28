import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import thresholds from "@shared/quality-thresholds.json";

const css = readFileSync(resolve(import.meta.dirname, "index.css"), "utf8");

function token(name: string): string | undefined {
  return new RegExp(`^\\s*--${name}:\\s*([^;]+);`, "m").exec(css)?.[1]?.trim();
}

// DESIGN.md front matter (UX-DR1).
const DESIGN_TOKENS: Record<string, string> = {
  success: "#15803d",
  "success-foreground": "#ffffff",
  warning: "#b45309",
  "warning-foreground": "#ffffff",
  flag: "#dc2626",
  "flag-fill": "#dc262614",
  "flag-halo": "#ffffff",
  "confidence-low": "#b45309",
  destructive: "#b91c1c",
  "destructive-foreground": "#ffffff",
  "tap-min": "48px",
  "supplier-gutter": "16px",
  "body-supplier-font-size": "16px",
  "body-supplier-line-height": "1.5",
  "numeric-font-feature-settings": '"tnum"',
  "focus-ring-width": "2px",
  "focus-ring-offset": "2px",
};

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  const [r = 0, g = 0, b = 0] = channels;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
}

describe("1.4 design tokens", () => {
  it.each(Object.entries(DESIGN_TOKENS))(
    "defines --%s as DESIGN.md sets it",
    (name, value) => {
      expect(token(name)?.toLowerCase()).toBe(value);
    },
  );

  it("draws the 2px focus ring with a 2px offset on every focusable element", () => {
    expect(css).toMatch(
      /:focus-visible \{\s*outline: var\(--focus-ring-width\) solid var\(--ring\);\s*outline-offset: var\(--focus-ring-offset\);/,
    );
  });

  it("gives the focus ring at least 3:1 against the background (WCAG 1.4.11)", () => {
    // --background is shadcn's white.
    expect(token("background")).toBe("oklch(1 0 0)");
    const ring = token("ring") ?? "";
    expect(ring).toMatch(/^#[0-9a-f]{6}$/i);
    expect(contrast(ring, "#ffffff")).toBeGreaterThanOrEqual(3);
  });

  it("removes Tailwind's default palette so only token colours exist", () => {
    expect(css).toMatch(/@theme \{\s*--color-\*: initial;/);
  });

  it("sets scroll padding to the sticky header height", () => {
    expect(css).toMatch(/scroll-padding-top: var\(--header-height\)/);
  });

  it("resolves the @shared alias", () => {
    expect(thresholds.blur.measure).toBe("variance_of_laplacian");
  });
});
