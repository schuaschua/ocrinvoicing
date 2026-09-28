import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Received } from "@/screens/Received";

afterEach(() => {
  vi.useRealTimers();
});

describe("1.8 Received", () => {
  it("announces Received with the reference, and focuses the reference", () => {
    vi.useFakeTimers();
    render(<Received reference="R-7Q4KXM2D" onUploadAnother={vi.fn()} />);
    const status = screen.getByRole("status");
    // The live region is in the page empty first, then filled, so it is announced.
    expect(status).toBeEmptyDOMElement();
    act(() => vi.runAllTimers());
    expect(status).toHaveTextContent(/^Received\.\s*Reference R-7Q4KXM2D$/);
    expect(screen.getByRole("heading", { level: 1 })).toHaveClass(
      "text-success",
    );
    expect(screen.getByText("R-7Q4KXM2D")).toHaveFocus();
    expect(document.title).toBe("Received – Babaloo");
  });

  it("Upload another goes back", async () => {
    const onUploadAnother = vi.fn();
    render(
      <Received reference="R-7Q4KXM2D" onUploadAnother={onUploadAnother} />,
    );
    const button = await screen.findByRole("button", {
      name: "Upload another",
    });
    expect(button).toHaveAttribute("data-capture");
    fireEvent.click(button);
    expect(onUploadAnother).toHaveBeenCalledTimes(1);
  });
});
