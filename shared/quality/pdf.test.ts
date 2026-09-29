import { describe, expect, it } from "vitest";

import { pdfBytes } from "./fixtures";
import { MAX_PDF_PAGES, countPdfPages, tooManyPages } from "./pdf";

const ascii = (text: string) => Uint8Array.from(text, (c) => c.charCodeAt(0));

describe("1.9 PDF page count", () => {
  it("reads the page count, refuses over 2, and gives up quickly on what it can't read", () => {
    expect([1, 2, 3].map((n) => countPdfPages(pdfBytes(n)))).toEqual([1, 2, 3]);
    expect(MAX_PDF_PAGES).toBe(2);
    expect(tooManyPages(countPdfPages(pdfBytes(2)))).toBe(false);
    expect(tooManyPages(countPdfPages(pdfBytes(3)))).toBe(true);
    expect(tooManyPages(null)).toBe(false);
    // The page tree packed in a compressed object stream (PDF 1.5+): the server decides.
    expect(
      countPdfPages(
        ascii(
          "%PDF-1.7\n5 0 obj\n<< /Type /ObjStm /N 3 >>\nstream\nx\x9c\nendstream\nendobj\n%%EOF",
        ),
      ),
    ).toBeNull();
    expect(countPdfPages(new Uint8Array())).toBeNull();
    // Hostile bytes (long digit and object runs) stay fast.
    const started = performance.now();
    expect(
      countPdfPages(ascii(`%PDF-1.4\n${"1".repeat(1_000_000)}`)),
    ).toBeNull();
    expect(
      countPdfPages(ascii(`%PDF-1.4\n${"1 0 obj ".repeat(100_000)}`)),
    ).toBeNull();
    expect(performance.now() - started).toBeLessThan(2000);
  });
});
