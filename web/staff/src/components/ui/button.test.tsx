import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "@/components/ui/button";

describe("1.4 Button", () => {
  it("meets the 48px tap target and keeps the focus ring", () => {
    render(<Button>Send</Button>);
    const button = screen.getByRole("button", { name: "Send" });
    expect(button).toHaveClass("min-h-tap-min", "min-w-tap-min");
    expect(button.className).not.toMatch(/outline-none/);
  });

  it("uses the destructive tokens", () => {
    render(<Button variant="destructive">Reject</Button>);
    expect(screen.getByRole("button", { name: "Reject" })).toHaveClass(
      "bg-destructive",
      "text-destructive-foreground",
    );
  });

  it("renders its child element when asChild is set", () => {
    render(
      <Button asChild>
        <a href="/help">Help</a>
      </Button>,
    );
    expect(screen.getByRole("link", { name: "Help" })).toHaveAttribute(
      "data-slot",
      "button",
    );
  });

  it("lets a caller's token size replace the 48px minimum (1.8)", () => {
    render(<Button className="min-h-capture">Take photo</Button>);
    const button = screen.getByRole("button", { name: "Take photo" });
    // Only one min-height class, so the stylesheet's order can't overrule the caller.
    expect(button).toHaveClass("min-h-capture", "min-w-tap-min");
    expect(button).not.toHaveClass("min-h-tap-min");
  });
});
