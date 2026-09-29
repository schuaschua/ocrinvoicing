// Generated test photos for the device check (Story 1.9). Test-only: nothing in the
// app imports this file. Every fixture is an invoice-like page: a light background
// with dark "text" words, drawn as RGBA pixels.

import type { Pixels, Side } from "./measure";

const WIDTH = 240;
const HEIGHT = 180;
const PAPER = 235;
const INK = 25;
// Text inside a 15% margin on every side; `bleed` runs it out to one edge.
const MARGIN = 0.15;

function blank(
  width: number,
  height: number,
  value: number,
): Uint8ClampedArray {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < data.length; i += 4) {
    data[i] = data[i + 1] = data[i + 2] = value;
    data[i + 3] = 255;
  }
  return data;
}

function set(
  p: Pixels & { data: Uint8ClampedArray },
  x: number,
  y: number,
  v: number,
) {
  const o = (y * p.width + x) * 4;
  p.data[o] = p.data[o + 1] = p.data[o + 2] = v;
}

/** A sharp, bright, framed page: rows of words (2 px tall, 3 px apart). */
export function page(
  options: { bleed?: Side; width?: number; height?: number } = {},
): Pixels & { data: Uint8ClampedArray } {
  const width = options.width ?? WIDTH;
  const height = options.height ?? HEIGHT;
  const p = { width, height, data: blank(width, height, PAPER) };
  let x0 = Math.round(width * MARGIN);
  let x1 = Math.round(width * (1 - MARGIN));
  let y0 = Math.round(height * MARGIN);
  let y1 = Math.round(height * (1 - MARGIN));
  if (options.bleed === "left") x0 = 0;
  if (options.bleed === "right") x1 = width;
  if (options.bleed === "top") y0 = 0;
  if (options.bleed === "bottom") y1 = height;
  for (let y = y0; y < y1; y++) {
    if (y % 5 >= 2) continue; // 2 rows of ink, 3 of paper
    for (let x = x0; x < x1; x++) {
      if (x % 9 < 7) set(p, x, y, INK); // 7 px words, 2 px gaps
    }
  }
  return p;
}

/** `p` box-blurred `passes` times with a 5 × 5 kernel (an out-of-focus photo). */
export function blurred(p: Pixels & { data: Uint8ClampedArray }, passes = 3) {
  let src = p.data;
  const { width: w, height: h } = p;
  for (let n = 0; n < passes; n++) {
    const out = new Uint8ClampedArray(src.length);
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        let sum = 0;
        let count = 0;
        for (let dy = -2; dy <= 2; dy++) {
          for (let dx = -2; dx <= 2; dx++) {
            const xx = x + dx;
            const yy = y + dy;
            if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
            sum += src[(yy * w + xx) * 4]!;
            count++;
          }
        }
        const o = (y * w + x) * 4;
        out[o] = out[o + 1] = out[o + 2] = Math.round(sum / count);
        out[o + 3] = 255;
      }
    }
    src = out;
  }
  return { width: w, height: h, data: src };
}

/** `p` with every channel scaled by `factor` (a photo in poor light). */
export function darkened(
  p: Pixels & { data: Uint8ClampedArray },
  factor = 0.15,
) {
  const data = new Uint8ClampedArray(p.data.length);
  for (let i = 0; i < data.length; i++) {
    data[i] = i % 4 === 3 ? 255 : Math.round(p.data[i]! * factor);
  }
  return { width: p.width, height: p.height, data };
}

/** `p` turned 90° clockwise, as a browser shows a photo with EXIF orientation 6. */
export function turnedClockwise(p: Pixels & { data: Uint8ClampedArray }) {
  const { width: w, height: h } = p;
  const data = new Uint8ClampedArray(p.data.length);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      // (x, y) goes to (h - 1 - y, x) in a h-wide image.
      const from = (y * w + x) * 4;
      const to = (x * h + (h - 1 - y)) * 4;
      for (let c = 0; c < 4; c++) data[to + c] = p.data[from + c]!;
    }
  }
  return { width: h, height: w, data };
}

/** PDF bytes from indirect object bodies, numbered from 1. */
function pdfFrom(objects: string[]): Uint8Array<ArrayBuffer> {
  const body = objects
    .map((object, i) => `${i + 1} 0 obj\n${object}\nendobj\n`)
    .join("");
  const text = `%PDF-1.4\n%\xe2\xe3\xcf\xd3\n${body}trailer\n<< /Root 1 0 R >>\n%%EOF\n`;
  return Uint8Array.from(text, (c) => c.charCodeAt(0));
}

/** A minimal PDF of `pages` pages (uncompressed, as simple generators write). */
export function pdfBytes(pages: number): Uint8Array<ArrayBuffer> {
  const kids = Array.from({ length: pages }, (_, i) => `${i + 3} 0 R`).join(
    " ",
  );
  return pdfFrom([
    "<< /Type /Catalog /Pages 2 0 R >>",
    `<< /Type /Pages /Kids [${kids}] /Count ${pages} >>`,
    ...Array.from(
      { length: pages },
      () => "<</Type/Page/Parent 2 0 R/MediaBox [0 0 595 842]>>",
    ),
  ]);
}
