import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "@/App";

describe("1.4 app shell", () => {
  it("shows the Babaloo text header and a main region", () => {
    render(<App />);
    expect(screen.getByRole("banner")).toHaveTextContent("Babaloo");
    expect(screen.getByRole("main")).toBeInTheDocument();
  });

  it("declares English and loads no inline script", () => {
    const html = readFileSync(
      resolve(import.meta.dirname, "../index.html"),
      "utf8",
    );
    expect(html).toMatch(/<html lang="en">/);
    // CSP is 'self' only (security.md rule 25): every script has a src.
    expect(html).not.toMatch(/<script(?![^>]*\bsrc=)[^>]*>/);
  });
});
