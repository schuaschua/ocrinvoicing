import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Loading, WAKING_UP_AFTER_MS } from "@/screens/Loading";
import { strings } from "@/strings";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("1.7 waking-up state", () => {
  it("shows a skeleton, then after 3 s says it is waking up in a live region", () => {
    render(<Loading />);
    const skeleton = screen.getByTestId("skeleton");
    expect(skeleton).toHaveAttribute("aria-hidden", "true");
    expect(skeleton).toHaveAttribute("aria-busy", "true");
    const status = screen.getByRole("status");
    // The live region is not inside the busy region, so it is announced.
    expect(status.closest("[aria-busy]")).toBeNull();
    expect(status).toBeEmptyDOMElement();

    act(() => vi.advanceTimersByTime(WAKING_UP_AFTER_MS - 1));
    expect(status).toBeEmptyDOMElement();

    act(() => vi.advanceTimersByTime(1));
    expect(WAKING_UP_AFTER_MS).toBe(3000);
    expect(status).toHaveTextContent(strings.loading.wakingUp);
    expect(strings.loading.wakingUp).toBe("Waking up, one moment…");
  });

  it("has its own page title and a heading", () => {
    render(<Loading />);
    expect(document.title).toBe("Loading – Babaloo");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      strings.loading.label,
    );
  });
});
