import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LinkNotWorking } from "@/screens/LinkNotWorking";
import { strings } from "@/strings";

describe("1.7 Link not working", () => {
  it("tells the supplier to contact their buyer, and nothing else", () => {
    render(<LinkNotWorking />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveFocus();
    // UX-DR7, word for word.
    expect(
      `${strings.linkNotWorking.heading} ${strings.linkNotWorking.body}`,
    ).toBe("This link isn't working. Please contact your buyer at Babaloo.");
    expect(heading).toHaveTextContent(strings.linkNotWorking.heading);
    expect(screen.getByText(strings.linkNotWorking.body)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(document.title).toBe("Link not working – Babaloo");
  });
});
