import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

describe("1.4 Button", () => {
  it("meets the 48px tap target, keeps the focus ring and lets a token size replace it", () => {
    render(
      <>
        <Button>Send</Button>
        <Button className="min-h-capture">Take photo</Button>
      </>,
    );
    const button = screen.getByRole("button", { name: "Send" });
    expect(button).toHaveClass("min-h-tap-min", "min-w-tap-min");
    expect(button.className).not.toMatch(/outline-none/);
    // Only one min-height class, so the stylesheet's order can't overrule the caller.
    const capture = screen.getByRole("button", { name: "Take photo" });
    expect(capture).toHaveClass("min-h-capture", "min-w-tap-min");
    expect(capture).not.toHaveClass("min-h-tap-min");
  });
});
