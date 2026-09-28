import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { UploadHome } from "@/screens/UploadHome";

describe("1.7 Upload home", () => {
  it("says who the upload is for, with the name in bold", () => {
    render(<UploadHome supplierName="Lim Leather Trading" />);
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Uploading for Lim Leather Trading");
    expect(heading.querySelector("strong")).toHaveTextContent(
      "Lim Leather Trading",
    );
    expect(heading).toHaveFocus();
    expect(document.title).toBe("Upload – Babaloo");
  });

  it("offers Take photo and Choose file as full-width capture buttons", () => {
    render(<UploadHome supplierName="Lim Leather Trading" />);
    for (const name of ["Take photo", "Choose file"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveClass("min-h-capture", "w-full");
    }
  });

  it("shows a name as text, never as markup", () => {
    render(<UploadHome supplierName="<b>Evil</b> Co" />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Uploading for <b>Evil</b> Co",
    );
  });
});
