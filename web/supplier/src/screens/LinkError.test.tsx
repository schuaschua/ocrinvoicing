import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LinkError } from "@/screens/LinkError";
import { strings } from "@/strings";

describe("1.7 link check failed", () => {
  it.each([strings.errors.generic, strings.errors.network])(
    "focuses the message once, titles the page with it and offers Try again (%s)",
    (message) => {
      const retry = vi.fn();
      render(<LinkError message={message} onRetry={retry} />);
      const heading = screen.getByRole("heading", { level: 1 });
      expect(heading).toHaveTextContent(message);
      expect(heading).toHaveFocus();
      // Announced by the focus move; no alert region reads it a second time.
      expect(screen.queryByRole("alert")).toBeNull();
      expect(document.title).toBe(`${message} – Babaloo`);
      fireEvent.click(screen.getByRole("button", { name: "Try again" }));
      expect(retry).toHaveBeenCalledTimes(1);
    },
  );
});
