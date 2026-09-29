// Story 2.10: Correct mode's unsaved edits. They survive the full-page sign-in after a
// 401 in `sessionStorage` (this tab only), keyed by invoice, and are restored only when
// the item is still queued. Bank fields are never editable, so no bank value is ever
// kept; revealed values never go here either (AD-11).

import type { AdminItem, Corrections } from "@/api/item";

export interface LineDraft {
  productCode: string;
  description: string;
  quantity: string;
  unitPrice: string;
  amount: string;
}

export const LINE_COLUMNS: readonly (keyof LineDraft)[] = [
  "productCode",
  "description",
  "quantity",
  "unitPrice",
  "amount",
];

/** The AD-18 column id of each line input, for its flag. */
export const LINE_COLUMN_IDS: Readonly<Record<keyof LineDraft, string>> = {
  productCode: "product_code",
  description: "description",
  quantity: "quantity",
  unitPrice: "unit_price",
  amount: "amount",
};

export interface Draft {
  fields: Record<string, string>;
  /** By line number. */
  lines: Record<string, LineDraft>;
}

const KEY_PREFIX = "babaloo.correct.";

function key(invoiceId: string): string {
  return `${KEY_PREFIX}${invoiceId}`;
}

/** The flagged field ids of the open reasons, lines included. */
export function flaggedIds(item: AdminItem): Set<string> {
  return new Set([
    ...item.reasons.flatMap((r) => r.fieldIds),
    ...item.fields.filter((f) => f.flagged).map((f) => f.fieldId),
  ]);
}

/** The editable fields: every non-bank field read, then the missing ones the server
 * lets Correct add. */
export function editableFieldIds(item: AdminItem): string[] {
  const read = item.fields.filter((f) => !f.bank).map((f) => f.fieldId);
  const all = [...read, ...item.addableFields];
  return all.filter((id, i) => all.indexOf(id) === i);
}

/** The draft Correct mode starts from: the current values. */
export function initialDraft(item: AdminItem): Draft {
  const fields: Record<string, string> = {};
  for (const id of editableFieldIds(item)) {
    fields[id] = item.fields.find((f) => f.fieldId === id)?.value ?? "";
  }
  const lines: Record<string, LineDraft> = {};
  for (const line of item.lines) {
    lines[String(line.lineNo)] = {
      productCode: line.productCode ?? "",
      description: line.description ?? "",
      quantity: line.quantity ?? "",
      unitPrice: line.unitPrice ?? "",
      amount: line.amount ?? "",
    };
  }
  return { fields, lines };
}

/** What Save and re-check sends: every changed editable field and every flagged one
 * left filled (confirmed as it is); for each changed or flagged line, only its changed
 * columns (the server copies the rest). */
export function corrections(item: AdminItem, draft: Draft): Corrections {
  const start = initialDraft(item);
  const flagged = flaggedIds(item);
  const fields: Record<string, string> = {};
  // Only ids editable now: a restored draft may hold others.
  for (const id of editableFieldIds(item)) {
    const value = (draft.fields[id] ?? "").trim();
    const was = (start.fields[id] ?? "").trim();
    if (value !== was || (flagged.has(id) && value !== "")) {
      fields[id] = value;
    }
  }
  const lines: Corrections["lines"] = [];
  for (const line of item.lines) {
    const edited = draft.lines[String(line.lineNo)];
    const was = start.lines[String(line.lineNo)];
    if (edited === undefined || was === undefined) continue;
    const changes: Record<string, string | null> = {};
    for (const c of LINE_COLUMNS) {
      if (edited[c].trim() !== was[c].trim()) {
        changes[LINE_COLUMN_IDS[c]] = edited[c].trim() || null;
      }
    }
    const isFlagged = LINE_COLUMNS.some((c) =>
      flagged.has(`line[${line.lineNo}].${LINE_COLUMN_IDS[c]}`),
    );
    if (Object.keys(changes).length > 0 || isFlagged) {
      lines.push({ lineNo: line.lineNo, changes });
    }
  }
  return { fields, lines };
}

function isDraft(value: unknown): value is Draft {
  if (value === null || typeof value !== "object") return false;
  const { fields, lines } = value as Record<string, unknown>;
  const isRecord = (v: unknown) =>
    v !== null && typeof v === "object" && !Array.isArray(v);
  return (
    isRecord(fields) &&
    Object.values(fields as object).every((v) => typeof v === "string") &&
    isRecord(lines) &&
    Object.values(lines as object).every(
      (line) =>
        isRecord(line) &&
        LINE_COLUMNS.every(
          (c) => typeof (line as Record<string, unknown>)[c] === "string",
        ),
    )
  );
}

/** The saved draft of `invoiceId`, or null (none, unreadable, or storage blocked). */
export function loadDraft(invoiceId: string): Draft | null {
  try {
    const raw = window.sessionStorage.getItem(key(invoiceId));
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    return isDraft(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

export function saveDraft(invoiceId: string, draft: Draft): void {
  try {
    window.sessionStorage.setItem(key(invoiceId), JSON.stringify(draft));
  } catch {
    // Storage full or blocked: the edits stay in memory only.
  }
}

export function clearDraft(invoiceId: string): void {
  try {
    window.sessionStorage.removeItem(key(invoiceId));
  } catch {
    // Nothing was kept.
  }
}
