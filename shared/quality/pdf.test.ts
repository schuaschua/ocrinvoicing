import { describe, expect, it } from "vitest";

import { pdfBytes, pdfFrom } from "./fixtures";
import { MAX_PDF_PAGES, countPdfPages, tooManyPages } from "./pdf";

const ascii = (text: string) => Uint8Array.from(text, (c) => c.charCodeAt(0));
const CATALOG = "<< /Type /Catalog /Pages 2 0 R >>";
const PAGE = "<< /Type /Page /Parent 2 0 R >>";

describe("1.9 PDF page count", () => {
  it.each([1, 2, 3, 7])("reads %i pages from the page tree", (pages) => {
    expect(countPdfPages(pdfBytes(pages))).toBe(pages);
  });

  it("refuses a 3-page PDF on the device", () => {
    expect(tooManyPages(countPdfPages(pdfBytes(3)))).toBe(true);
  });

  it("counts a page rewritten by an incremental update once", () => {
    const bytes = pdfFrom(
      [CATALOG, "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>", PAGE, PAGE],
      "3 0 obj\n<< /Type /Page /Parent 2 0 R /Rotate 90 >>\nendobj\n",
    );
    expect(countPdfPages(bytes)).toBe(2);
  });

  it("reads the page tree's latest revision, however its number is written", () => {
    const bytes = pdfFrom(
      [
        CATALOG,
        "<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>",
        PAGE,
        PAGE,
        PAGE,
      ],
      // A later revision drops a page; "002 00" is object 2 0 again.
      "002 00 obj\n<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>\nendobj\n",
    );
    expect(countPdfPages(bytes)).toBe(2);
  });

  it("ignores an orphaned page object outside the page tree", () => {
    const bytes = pdfFrom([
      CATALOG,
      "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
      PAGE,
      "<< /Type /Page >>",
      "<< /Type /Page >>",
    ]);
    expect(countPdfPages(bytes)).toBe(1);
  });

  it("reads the root of a nested page tree", () => {
    const bytes = pdfFrom([
      CATALOG,
      "<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 3 >>",
      "<< /Type /Pages /Parent 2 0 R /Kids [5 0 R 6 0 R] /Count 2 >>",
      "<< /Type /Pages /Parent 2 0 R /Kids [7 0 R] /Count 1 >>",
      PAGE,
      PAGE,
      PAGE,
    ]);
    expect(countPdfPages(bytes)).toBe(3);
  });

  it("never reads inside stream data", () => {
    const bytes = pdfFrom([
      CATALOG,
      "<< /Type /Pages /Kids [4 0 R] /Count 1 >>",
      // A content stream holding text that looks like objects and a page tree.
      "<< /Length 80 >>\nstream\nendobj 9 0 obj << /Type /Pages /Count 40 >> endobj /Type /Page\nendstream",
      PAGE,
    ]);
    expect(countPdfPages(bytes)).toBe(1);
  });

  it("gives null when no page count can be read", () => {
    // The page tree packed in a compressed object stream (PDF 1.5+).
    expect(
      countPdfPages(
        ascii(
          "%PDF-1.7\n5 0 obj\n<< /Type /ObjStm /N 3 >>\nstream\nx\x9c\nendstream\nendobj\n%%EOF",
        ),
      ),
    ).toBeNull();
    // Page objects but no readable /Count.
    expect(
      countPdfPages(pdfFrom([CATALOG, "<< /Type /Pages >>", PAGE, PAGE, PAGE])),
    ).toBeNull();
    expect(
      countPdfPages(ascii("not a pdf 2 0 obj /Type /Pages /Count 5 endobj")),
    ).toBeNull();
    expect(countPdfPages(new Uint8Array())).toBeNull();
    // An object that never ends, and a stream that never ends.
    expect(
      countPdfPages(ascii("%PDF-1.4\n2 0 obj\n<< /Type /Pages /Count 3 >>")),
    ).toBeNull();
    expect(
      countPdfPages(
        ascii(
          "%PDF-1.4\n4 0 obj\nstream\n2 0 obj /Type /Pages /Count 3 endobj",
        ),
      ),
    ).toBeNull();
  });

  it("stays fast on hostile bytes (long digit and object runs)", () => {
    const digits = `%PDF-1.4\n${"1".repeat(1_000_000)}`;
    const objects = `%PDF-1.4\n${"1 0 obj ".repeat(100_000)}`;
    const streams = `%PDF-1.4\n${"stream\n".repeat(100_000)}`;
    const started = performance.now();
    expect(countPdfPages(ascii(digits))).toBeNull();
    expect(countPdfPages(ascii(objects))).toBeNull();
    expect(countPdfPages(ascii(streams))).toBeNull();
    expect(performance.now() - started).toBeLessThan(2000);
  });

  it("refuses only a known count over 2 pages", () => {
    expect(MAX_PDF_PAGES).toBe(2);
    expect(tooManyPages(null)).toBe(false);
    expect(tooManyPages(1)).toBe(false);
    expect(tooManyPages(2)).toBe(false);
    expect(tooManyPages(3)).toBe(true);
  });
});
