import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OFFLINE, SESSION_EXPIRED, apiEvents } from "@/api";
import { App } from "@/App";
import { strings } from "@/strings";

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

  it("announces the session-expired notice when the API answers 401", () => {
    render(<App />);
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    act(() => {
      apiEvents.dispatchEvent(new Event(SESSION_EXPIRED));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(strings.sessionExpired);
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("shows the offline notice when the API answers 503 DB_OFFLINE", () => {
    render(<App />);
    act(() => {
      apiEvents.dispatchEvent(new Event(OFFLINE));
    });
    expect(screen.getByRole("status")).toHaveTextContent(strings.offline);
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("stops listening when it unmounts", () => {
    const { unmount } = render(<App />);
    unmount();
    expect(() =>
      apiEvents.dispatchEvent(new Event(SESSION_EXPIRED)),
    ).not.toThrow();
  });
});
