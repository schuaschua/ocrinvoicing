import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** A supplier as staff screens list it: id and name only (Story 4.4, AD-11). */
export interface SupplierRow {
  supplierId: string;
  name: string;
}

export interface SupplierPage {
  /** By name in any case, then id. */
  items: SupplierRow[];
  page: number;
  pageSize: number;
  total: number;
}

export interface SupplierQuery {
  page: number;
  /** The name search, sent as `q`; null for every supplier. */
  text: string | null;
}

type Wire = Record<string, unknown>;

function isWire(value: unknown): value is Wire {
  return value !== null && typeof value === "object";
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function row(value: unknown): SupplierRow {
  if (
    !isWire(value) ||
    typeof value.supplier_id !== "string" ||
    typeof value.name !== "string"
  ) {
    throw broken();
  }
  return { supplierId: value.supplier_id, name: value.name };
}

/**
 * A page of suppliers (`GET /api/suppliers`). Rejects with the client's `ApiError`
 * (401 and 503 `DB_OFFLINE` have already raised their events) or when `signal` aborts.
 */
export async function listSuppliers(
  query: SupplierQuery,
  signal?: AbortSignal,
): Promise<SupplierPage> {
  const params = new URLSearchParams({ page: String(query.page) });
  if (query.text !== null) params.set("q", query.text);
  const body = await apiRequest<unknown>(`/api/suppliers?${params}`, {
    signal,
  });
  if (!isWire(body) || !Array.isArray(body.items)) throw broken();
  // Paging divides by it: a missing, zero or negative page size is a broken answer.
  const pageSize = num(body.page_size);
  if (pageSize === null || pageSize < 1) throw broken();
  return {
    items: body.items.map(row),
    page: num(body.page) ?? query.page,
    pageSize,
    total: num(body.total) ?? body.items.length,
  };
}

/** One supplier; rejects with `ApiError` 404 for an unknown id. */
export async function getSupplier(
  supplierId: string,
  signal?: AbortSignal,
): Promise<SupplierRow> {
  const body = await apiRequest<unknown>(
    `/api/suppliers/${encodeURIComponent(supplierId)}`,
    { signal },
  );
  return row(body);
}
