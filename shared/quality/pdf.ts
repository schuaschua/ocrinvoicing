// A light PDF page count for the device check (Story 1.9): PDFs over 2 pages are
// refused on the device, the rest go to the server, which decides (AD-6,
// UNSUPPORTED_DOCUMENT). No PDF library: the page tree's `/Count` is read from the raw
// bytes.

/** More pages than this are refused on the device (AD-6). */
export const MAX_PDF_PAGES = 2;

// The start of an indirect object, "12 0 obj". Bounded digit runs and the lookbehind
// keep the scan linear on any bytes.
const OBJECT_START =
  /(?<![0-9])([0-9]{1,10})[ \t\r\n\f\0]+([0-9]{1,5})[ \t\r\n\f\0]+obj\b/g;
const OBJECT_END = "endobj";
// A stream's data starts after "stream" and its end of line, and runs to "endstream".
const STREAM_START = /\bstream(?:\r\n|\r|\n)/g;
const STREAM_END = "endstream";
// "/Type /Pages" (a page tree node), never "/Type /Page".
const PAGES_TYPE = /\/Type\s*\/Pages(?![A-Za-z0-9])/;
const COUNT = /\/Count\s+([0-9]{1,9})(?![0-9])/;

/** `text` with every stream's data cut out, so bytes inside a stream can't look like objects. */
function withoutStreams(text: string): string {
  const kept: string[] = [];
  let at = 0;
  for (;;) {
    STREAM_START.lastIndex = at;
    const start = STREAM_START.exec(text);
    if (start === null) break;
    kept.push(text.slice(at, STREAM_START.lastIndex));
    const end = text.indexOf(STREAM_END, STREAM_START.lastIndex);
    if (end === -1) return kept.join("");
    at = end;
  }
  kept.push(text.slice(at));
  return kept.join("");
}

/**
 * The number of pages in a PDF's bytes: the largest `/Count` among its page tree
 * nodes (`/Type /Pages`; the root holds the total). An object redefined by a later
 * revision counts in its latest form only. Null when no count can be read: not a PDF,
 * or the page tree packed in a compressed object stream (PDF 1.5+). A null count must
 * never block a send; the server decides.
 */
export function countPdfPages(bytes: Uint8Array): number | null {
  // "latin1" decodes as windows-1252: one character per byte, and ASCII unchanged, so
  // binary data can't break the scan for ASCII tokens.
  const text = new TextDecoder("latin1").decode(bytes);
  if (!text.includes("%PDF-")) return null;
  const scanned = withoutStreams(text);
  // Object number and generation, normalised ("003 0" is "3 0"), to its latest count.
  const counts = new Map<string, number | null>();
  OBJECT_START.lastIndex = 0;
  for (;;) {
    const start = OBJECT_START.exec(scanned);
    if (start === null) break;
    const bodyStart = OBJECT_START.lastIndex;
    const end = scanned.indexOf(OBJECT_END, bodyStart);
    if (end === -1) break;
    const body = scanned.slice(bodyStart, end);
    const id = `${Number(start[1])} ${Number(start[2])}`;
    const count = PAGES_TYPE.test(body) ? COUNT.exec(body) : null;
    counts.set(id, count === null ? null : Number(count[1]));
    // Each byte is read once: the next object starts after this one ends.
    OBJECT_START.lastIndex = end + OBJECT_END.length;
  }
  let pages: number | null = null;
  for (const count of counts.values()) {
    if (count !== null && (pages === null || count > pages)) pages = count;
  }
  return pages;
}

/** Whether a PDF must be refused on the device: only when its count is known and over the limit. */
export function tooManyPages(pages: number | null): boolean {
  return pages !== null && pages > MAX_PDF_PAGES;
}
