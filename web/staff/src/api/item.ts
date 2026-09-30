import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** One current field of an item (AD-18). A bank field has no value: only masks. */
export interface ItemField {
  fieldId: string;
  value: string | null;
  currency: string | null;
  /** 0 to 1; an admin correction counts 1. Null when DI gave none. */
  confidence: number | null;
  page: number | null;
  /** The first bounding region, as x, y pairs in the page's unit. */
  polygon: number[] | null;
  flagged: boolean;
  bank: boolean;
}

export interface ItemReason {
  code: string;
  fieldIds: string[];
  /** The reason's facts, e.g. `ACCOUNTS_API_ERROR`'s `{status, code}` (Story 3.2). */
  detail: Record<string, unknown>;
}

/** Story 3.3: the earlier invoice an open `DUPLICATE` names, for the comparison. */
export interface DuplicateOf {
  invoiceId: string;
  receivedAt: string;
  contentType: string;
  supplierName: string | null;
  /** The exact total as the server sent it; the app never computes with it. */
  invoiceTotal: string | null;
  currency: string | null;
  imageAvailable: boolean;
}

export interface ItemLine {
  lineNo: number;
  productCode: string | null;
  description: string | null;
  /** Exact numbers as the server sent them; the app never computes with them. */
  quantity: string | null;
  unitPrice: string | null;
  amount: string | null;
  confidence: number;
}

export interface PageSize {
  page: number;
  width: number;
  height: number;
  unit: string;
}

/** One changed bank field: the last 4 characters on file and on the invoice. */
export interface BankChange {
  fieldId: string;
  onFile: string | null;
  newValue: string | null;
}

/** `GET /api/admin/items/{id}` (Story 2.9). */
export interface AdminItem {
  invoiceId: string;
  receivedAt: string;
  contentType: string;
  imageAvailable: boolean;
  supplierName: string | null;
  /** Only when the bank details changed (UX-DR13). */
  supplierPhone: string | null;
  reasons: ItemReason[];
  fields: ItemField[];
  lines: ItemLine[];
  pages: PageSize[];
  bankChanges: BankChange[];
  /** What the open reasons allow; the server applies the same guard (UX-DR12). */
  allowedActions: AdminAction[];
  /** The routing this page shows; every action sends it back (stale-page guard). */
  routingId: string | null;
  /** The missing checked fields Correct may add, as the server decides them. */
  addableFields: string[];
  /** Story 3.3: the matching invoice of an open `DUPLICATE`; null without one. */
  duplicateOf: DuplicateOf | null;
}

export type RevealWhich = "new" | "on_file";

/** Stories 2.10 and 3.3: an admin action, as the server names it. */
export type AdminAction =
  "correct" | "approve" | "reextract" | "retry_intake" | "reject";

const ACTIONS: readonly AdminAction[] = [
  "correct",
  "approve",
  "reextract",
  "retry_intake",
  "reject",
];

type Wire = Record<string, unknown>;

function isWire(value: unknown): value is Wire {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function textList(value: unknown): string[] {
  return list(value).filter((v): v is string => typeof v === "string");
}

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function itemPath(invoiceId: string): string {
  return `/api/admin/items/${encodeURIComponent(invoiceId)}`;
}

/** The same-origin image or PDF stream, for an `<img>` or a link (never a SAS URL). */
export function itemImageUrl(invoiceId: string): string {
  return `${itemPath(invoiceId)}/image`;
}

/** Story 3.3: the matching invoice's image, served while the item's `DUPLICATE` is
 * open. */
export function duplicateImageUrl(invoiceId: string): string {
  return `${itemPath(invoiceId)}/duplicate/image`;
}

function duplicateOf(value: unknown): DuplicateOf | null {
  if (!isWire(value)) return null;
  const invoiceId = str(value.invoice_id);
  const contentType = str(value.content_type);
  if (invoiceId === null || contentType === null) return null;
  return {
    invoiceId,
    receivedAt: str(value.received_at) ?? "",
    contentType,
    supplierName: str(value.supplier_name),
    invoiceTotal: str(value.invoice_total),
    currency: str(value.currency),
    imageAvailable: value.image_available === true,
  };
}

function field(value: unknown): ItemField[] {
  if (!isWire(value)) return [];
  const fieldId = str(value.field_id);
  if (fieldId === null) return [];
  const polygon = list(value.polygon);
  return [
    {
      fieldId,
      value: str(value.value),
      currency: str(value.currency),
      confidence: num(value.confidence),
      page: num(value.page),
      polygon:
        polygon.length >= 6 && polygon.every((p) => num(p) !== null)
          ? (polygon as number[])
          : null,
      flagged: value.flagged === true,
      bank: value.bank === true,
    },
  ];
}

function line(value: unknown): ItemLine[] {
  if (!isWire(value)) return [];
  const lineNo = num(value.line_no);
  if (lineNo === null) return [];
  return [
    {
      lineNo,
      productCode: str(value.product_code),
      description: str(value.description),
      quantity: str(value.quantity),
      unitPrice: str(value.unit_price),
      amount: str(value.amount),
      confidence: num(value.confidence) ?? 0,
    },
  ];
}

function page(value: unknown): PageSize[] {
  if (!isWire(value)) return [];
  const number = num(value.page);
  const width = num(value.width);
  const height = num(value.height);
  const unit = str(value.unit);
  if (number === null || width === null || height === null || unit === null) {
    return [];
  }
  if (width <= 0 || height <= 0) return [];
  return [{ page: number, width, height, unit }];
}

/**
 * The admin item. Rejects with the client's `ApiError` (404 when the invoice is not in
 * the queue; 401 and 503 `DB_OFFLINE` have already raised their events).
 */
export async function getItem(
  invoiceId: string,
  signal?: AbortSignal,
): Promise<AdminItem> {
  const body = await apiRequest<unknown>(itemPath(invoiceId), { signal });
  if (!isWire(body)) throw broken();
  const id = str(body.invoice_id);
  const contentType = str(body.content_type);
  if (id === null || contentType === null) throw broken();
  return {
    invoiceId: id,
    receivedAt: str(body.received_at) ?? "",
    contentType,
    imageAvailable: body.image_available === true,
    supplierName: str(body.supplier_name),
    supplierPhone: str(body.supplier_phone),
    reasons: list(body.reasons).flatMap((r) =>
      isWire(r) && str(r.code) !== null
        ? [
            {
              code: str(r.code) as string,
              fieldIds: textList(r.field_ids),
              detail: isWire(r.detail) ? r.detail : {},
            },
          ]
        : [],
    ),
    fields: list(body.fields).flatMap(field),
    lines: list(body.lines).flatMap(line),
    pages: list(body.pages).flatMap(page),
    bankChanges: list(body.bank_changes).flatMap((c) => {
      if (!isWire(c)) return [];
      const fieldId = str(c.field_id);
      return fieldId === null
        ? []
        : [{ fieldId, onFile: str(c.on_file), newValue: str(c.new) }];
    }),
    allowedActions: textList(body.allowed_actions).filter(
      (a): a is AdminAction => (ACTIONS as readonly string[]).includes(a),
    ),
    routingId: str(body.routing_id),
    addableFields: textList(body.addable_fields),
    duplicateOf: duplicateOf(body.duplicate_of),
  };
}

/**
 * One changed bank value in full (UX-DR14). The server writes an audit entry before it
 * answers. The value is kept in memory only, never in browser storage.
 */
export async function revealBankValue(
  invoiceId: string,
  fieldId: string,
  which: RevealWhich,
): Promise<string> {
  const body = await apiRequest<unknown>(`${itemPath(invoiceId)}/bank/reveal`, {
    method: "POST",
    json: { field_id: fieldId, which },
  });
  const value = isWire(body) ? str(body.value) : null;
  if (value === null) throw broken();
  return value;
}

/** A Correct request: header values by field id, and each line's changed columns
 * by their AD-18 id (`product_code`, `unit_price`, …); the server writes the whole
 * line, copying the rest. A line with no changes confirms it as read. */
export interface Corrections {
  fields: Record<string, string>;
  lines: { lineNo: number; changes: Record<string, string | null> }[];
}

/**
 * Save and re-check (Story 2.10). `routingId` is the item's: the server refuses a
 * stale page. Rejects with the client's `ApiError`: 400 for a value the server
 * refuses, 409 `CONFLICT` when another admin acted first (or it was routed again),
 * 409 `ACTION_NOT_ALLOWED` when the reasons no longer allow it.
 */
export async function correctItem(
  invoiceId: string,
  routingId: string | null,
  corrections: Corrections,
): Promise<void> {
  await apiRequest<unknown>(`${itemPath(invoiceId)}/correct`, {
    method: "POST",
    json: {
      routing_id: routingId,
      fields: corrections.fields,
      lines: corrections.lines.map((l) => ({
        line_no: l.lineNo,
        ...l.changes,
      })),
    },
  });
}

/** Re-extract or Retry intake (Story 2.10); rejects like `correctItem`. */
export async function rerunItem(
  invoiceId: string,
  routingId: string | null,
  action: "reextract" | "retry_intake",
): Promise<void> {
  const path = action === "reextract" ? "reextract" : "retry-intake";
  await apiRequest<unknown>(`${itemPath(invoiceId)}/${path}`, {
    method: "POST",
    json: { routing_id: routingId },
  });
}

/** Reject with a reason (500 characters at most); rejects like `correctItem`. */
export async function rejectItem(
  invoiceId: string,
  routingId: string | null,
  reason: string,
): Promise<void> {
  await apiRequest<unknown>(`${itemPath(invoiceId)}/reject`, {
    method: "POST",
    json: { routing_id: routingId, reason },
  });
}

/** Story 3.3: Approve's call-back checklist, for changed bank details (AD-11). */
export interface ApproveChecks {
  calledNumberOnFile: boolean;
  supplierConfirmed: boolean;
}

/**
 * Approve with a reason (500 characters at most) and the call-back checks; rejects
 * like `correctItem`, and with 400 `CHECKS_REQUIRED` when the bank details changed and
 * a check is missing (the server decides, AD-11).
 */
export async function approveItem(
  invoiceId: string,
  routingId: string | null,
  reason: string,
  checks: ApproveChecks,
): Promise<void> {
  await apiRequest<unknown>(`${itemPath(invoiceId)}/approve`, {
    method: "POST",
    json: {
      routing_id: routingId,
      reason,
      checks: {
        called_number_on_file: checks.calledNumberOnFile,
        supplier_confirmed: checks.supplierConfirmed,
      },
    },
  });
}
