import type { ItemField, PageSize } from "@/api/item";
import { strings } from "@/strings";

/** A flagged field's box on the image, as fractions of the page (0 to 1). */
export interface FlagBox {
  fieldId: string;
  /** The tag on the box and beside its field in the list, from 1. */
  number: number;
  left: number;
  top: number;
  width: number;
  height: number;
}

const PAYMENT = /^payment\[(\d+)\]\.(.+)$/;

/** The label an admin reads for an AD-18 field id. */
export function fieldLabel(fieldId: string): string {
  const [, index, kind] = PAYMENT.exec(fieldId) ?? [];
  if (index !== undefined && kind !== undefined) {
    return strings.bankFieldLabel(kind, Number(index) + 1);
  }
  return strings.fieldLabels[fieldId] ?? fieldId;
}

/**
 * The boxes of the flagged fields that have a region on a page with a known size, in
 * field-list order (UX-DR10). An image has one page; a run saved before page sizes
 * were kept has none, and so no boxes.
 */
export function flagBoxes(fields: ItemField[], pages: PageSize[]): FlagBox[] {
  const boxes: FlagBox[] = [];
  for (const field of fields) {
    if (!field.flagged || field.polygon === null || field.page === null) {
      continue;
    }
    const size = pages.find((p) => p.page === field.page);
    if (size === undefined) continue;
    const xs = field.polygon.filter((_, i) => i % 2 === 0);
    const ys = field.polygon.filter((_, i) => i % 2 === 1);
    const left = Math.max(0, Math.min(...xs) / size.width);
    const top = Math.max(0, Math.min(...ys) / size.height);
    const right = Math.min(1, Math.max(...xs) / size.width);
    const bottom = Math.min(1, Math.max(...ys) / size.height);
    if (right <= left || bottom <= top) continue;
    boxes.push({
      fieldId: field.fieldId,
      number: boxes.length + 1,
      left,
      top,
      width: right - left,
      height: bottom - top,
    });
  }
  return boxes;
}
