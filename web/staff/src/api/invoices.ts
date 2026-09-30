import { strings, type InvoiceStatus } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** One invoice in the search results (`GET /api/invoices`, Story 3.4). */
export interface InvoiceRow {
  invoiceId: string;
  /** The supplier reference, `R-` and 8 characters. */
  reference: string | null;
  /** ISO 8601 UTC: when the invoice was received. */
  receivedAt: string;
  supplierId: string;
  supplierName: string | null;
  /** The current invoice number (AD-18), or null before extraction. */
  invoiceNumber: string | null;
  /** The current total as the server sent it (2 decimals), or null. */
  amount: string | null;
  currency: string | null;
  /** The AD-3 code; shown only through `statusLabel`. */
  status: InvoiceStatus;
  /** An admin corrected the current reading ("Re-checking"). */
  afterCorrection: boolean;
}

export interface InvoicePage {
  items: InvoiceRow[];
  page: number;
  pageSize: number;
  total: number;
  /** Every supplier with an invoice, whatever the filters, by name. */
  suppliers: { supplierId: string; supplierName: string | null }[];
}

export interface InvoiceQuery {
  page: number;
  supplierId: string | null;
  /** AD-3 codes; empty for any status. */
  statuses: readonly InvoiceStatus[];
  invoiceNumber: string | null;
  reference: string | null;
}

export interface InvoiceDetail {
  invoiceId: string;
  reference: string | null;
  receivedAt: string;
  supplierId: string;
  supplierName: string | null;
  status: InvoiceStatus;
  afterCorrection: boolean;
  accountsRef: string | null;
  postedAt: string | null;
  /** Current header fields; bank fields never come, only `bankOnFile`. */
  fields: { fieldId: string; value: string | null; currency: string | null }[];
  bankOnFile: boolean;
  lines: {
    lineNo: number;
    productCode: string | null;
    description: string | null;
    quantity: string | null;
    unitPrice: string | null;
    amount: string | null;
  }[];
  /** `actor` is a category: a pipeline stage, `admin` or `system`. */
  history: {
    fromStatus: InvoiceStatus | null;
    toStatus: InvoiceStatus;
    at: string;
    actor: string;
  }[];
}

type Wire = Record<string, unknown>;

function isWire(value: unknown): value is Wire {
  return value !== null && typeof value === "object";
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

/** A status as sent; one this build doesn't know still reads "Processing". */
function status(value: unknown): InvoiceStatus {
  return (str(value) ?? "received") as InvoiceStatus;
}

function row(value: unknown): InvoiceRow {
  if (!isWire(value)) throw broken();
  const invoiceId = str(value.invoice_id);
  const receivedAt = str(value.received_at);
  const supplierId = str(value.supplier_id);
  if (invoiceId === null || receivedAt === null || supplierId === null) {
    throw broken();
  }
  return {
    invoiceId,
    reference: str(value.reference),
    receivedAt,
    supplierId,
    supplierName: str(value.supplier_name),
    invoiceNumber: str(value.invoice_number),
    amount: str(value.amount),
    currency: str(value.currency),
    status: status(value.status),
    afterCorrection: value.after_correction === true,
  };
}

function suppliers(value: unknown): InvoicePage["suppliers"] {
  return list(value).flatMap((entry: unknown) => {
    if (!isWire(entry)) return [];
    const supplierId = str(entry.supplier_id);
    return supplierId === null
      ? []
      : [{ supplierId, supplierName: str(entry.supplier_name) }];
  });
}

/**
 * A page of invoices, newest first. Rejects with the client's `ApiError` (401 and 503
 * `DB_OFFLINE` have already raised their events) or when `signal` aborts.
 */
export async function searchInvoices(
  query: InvoiceQuery,
  signal?: AbortSignal,
): Promise<InvoicePage> {
  const params = new URLSearchParams({ page: String(query.page) });
  if (query.supplierId !== null) params.set("supplier_id", query.supplierId);
  if (query.statuses.length > 0) params.set("status", query.statuses.join(","));
  if (query.invoiceNumber !== null) {
    params.set("invoice_number", query.invoiceNumber);
  }
  if (query.reference !== null) params.set("reference", query.reference);
  const body = await apiRequest<unknown>(`/api/invoices?${params}`, { signal });
  if (!isWire(body) || !Array.isArray(body.items)) throw broken();
  return {
    items: body.items.map(row),
    page: num(body.page) ?? query.page,
    pageSize: num(body.page_size) ?? body.items.length,
    total: num(body.total) ?? body.items.length,
    suppliers: suppliers(body.suppliers),
  };
}

/** One invoice's detail; rejects with `ApiError` 404 for an unknown id. */
export async function getInvoice(
  invoiceId: string,
  signal?: AbortSignal,
): Promise<InvoiceDetail> {
  const body = await apiRequest<unknown>(
    `/api/invoices/${encodeURIComponent(invoiceId)}`,
    { signal },
  );
  if (!isWire(body)) throw broken();
  const head = row({ ...body, invoice_number: null, amount: null });
  return {
    invoiceId: head.invoiceId,
    reference: head.reference,
    receivedAt: head.receivedAt,
    supplierId: head.supplierId,
    supplierName: head.supplierName,
    status: head.status,
    afterCorrection: head.afterCorrection,
    accountsRef: str(body.accounts_ref),
    postedAt: str(body.posted_at),
    fields: list(body.fields).flatMap((field: unknown) => {
      if (!isWire(field)) return [];
      const fieldId = str(field.field_id);
      return fieldId === null
        ? []
        : [
            {
              fieldId,
              value: str(field.value),
              currency: str(field.currency),
            },
          ];
    }),
    bankOnFile: body.bank_on_file === true,
    lines: list(body.lines).flatMap((line: unknown) => {
      if (!isWire(line)) return [];
      const lineNo = num(line.line_no);
      return lineNo === null
        ? []
        : [
            {
              lineNo,
              productCode: str(line.product_code),
              description: str(line.description),
              quantity: str(line.quantity),
              unitPrice: str(line.unit_price),
              amount: str(line.amount),
            },
          ];
    }),
    history: list(body.history).flatMap((entry: unknown) => {
      if (!isWire(entry)) return [];
      const at = str(entry.at);
      const toStatus = str(entry.to_status);
      if (at === null || toStatus === null) return [];
      const from = str(entry.from_status);
      return [
        {
          fromStatus: from === null ? null : (from as InvoiceStatus),
          toStatus: toStatus as InvoiceStatus,
          at,
          actor: str(entry.actor) ?? "system",
        },
      ];
    }),
  };
}
