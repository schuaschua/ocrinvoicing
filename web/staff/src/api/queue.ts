import { strings, type ReasonCode } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** One invoice in the admin queue (`GET /api/admin/queue`, Story 2.8). */
export interface QueueItem {
  invoiceId: string;
  /** ISO 8601 UTC: when the invoice was received. */
  receivedAt: string;
  supplierId: string;
  supplierName: string | null;
  /** The current total as the server sent it (2 decimals), or null before extraction. */
  amount: string | null;
  currency: string | null;
  /** The open reasons (AD-4). A code this build doesn't know is kept as sent. */
  reasons: string[];
}

/** One page of the queue, and the page-cap warning (only from 80 %, server-decided). */
export interface QueuePage {
  items: QueueItem[];
  page: number;
  pageSize: number;
  total: number;
  pageUsage: { pagesUsed: number; pageCap: number } | null;
  /** Every supplier with a queued invoice, whatever the filters, by name. */
  suppliers: { supplierId: string; supplierName: string | null }[];
}

export interface QueueQuery {
  page: number;
  reason: ReasonCode | null;
  supplierId: string | null;
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

function item(value: unknown): QueueItem {
  if (!isWire(value)) throw broken();
  const invoiceId = str(value.invoice_id);
  const receivedAt = str(value.received_at);
  const supplierId = str(value.supplier_id);
  if (invoiceId === null || receivedAt === null || supplierId === null) {
    throw broken();
  }
  return {
    invoiceId,
    receivedAt,
    supplierId,
    supplierName: str(value.supplier_name),
    amount: str(value.amount),
    currency: str(value.currency),
    reasons: Array.isArray(value.reasons)
      ? value.reasons.filter((r): r is string => typeof r === "string")
      : [],
  };
}

function usage(value: unknown): QueuePage["pageUsage"] {
  if (!isWire(value)) return null;
  const pagesUsed = num(value.pages_used);
  const pageCap = num(value.page_cap);
  return pagesUsed === null || pageCap === null ? null : { pagesUsed, pageCap };
}

function suppliers(value: unknown): QueuePage["suppliers"] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry: unknown) => {
    if (!isWire(entry)) return [];
    const supplierId = str(entry.supplier_id);
    return supplierId === null
      ? []
      : [{ supplierId, supplierName: str(entry.supplier_name) }];
  });
}

/**
 * A page of the admin queue, oldest first. Rejects with the client's `ApiError` (401
 * and 503 `DB_OFFLINE` have already raised their events) or when `signal` aborts.
 */
export async function getQueue(
  query: QueueQuery,
  signal?: AbortSignal,
): Promise<QueuePage> {
  const params = new URLSearchParams({ page: String(query.page) });
  if (query.reason !== null) params.set("reason", query.reason);
  if (query.supplierId !== null) params.set("supplier_id", query.supplierId);
  const body = await apiRequest<unknown>(`/api/admin/queue?${params}`, {
    signal,
  });
  if (!isWire(body) || !Array.isArray(body.items)) throw broken();
  return {
    items: body.items.map(item),
    page: num(body.page) ?? query.page,
    pageSize: num(body.page_size) ?? body.items.length,
    total: num(body.total) ?? body.items.length,
    pageUsage: usage(body.page_usage),
    suppliers: suppliers(body.suppliers),
  };
}
