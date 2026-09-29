import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(import.meta.dirname, "index.css"), "utf8");

function token(name: string): string | undefined {
  return new RegExp(`^\\s*--${name}:\\s*([^;]+);`, "m").exec(css)?.[1]?.trim();
}

describe("1.4 design tokens", () => {
  it("sets the tap and capture sizes, the focus ring and only token colours", () => {
    expect(token("tap-min")).toBe("48px");
    expect(token("capture-min-height")).toBe("56px");
    expect(token("destructive")).toBe("#b91c1c");
    expect(css).toMatch(
      /:focus-visible \{\s*outline: var\(--focus-ring-width\) solid var\(--ring\);\s*outline-offset: var\(--focus-ring-offset\);/,
    );
    expect(token("focus-ring-width")).toBe("2px");
    expect(css).toMatch(/@theme \{\s*--color-\*: initial;/);
    expect(css).toMatch(/scroll-padding-top: var\(--header-height\)/);
  });
});
