// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import viteConfig from "./vite.config.ts";

describe("1.4 preview security headers", () => {
  it("equal the ones the Function app sends (shared/security-headers.json)", () => {
    const shared: unknown = JSON.parse(
      readFileSync(
        resolve(import.meta.dirname, "../../shared/security-headers.json"),
        "utf8",
      ),
    );
    expect(viteConfig.preview?.headers).toEqual(shared);
    expect(shared).toHaveProperty(
      "Content-Security-Policy",
      "default-src 'self'; frame-ancestors 'none'",
    );
  });
});
