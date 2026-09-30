import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** One overdue PO (Story 4.2). */
export interface OverduePo {
  poNumber: string;
  /** The earliest line's expected date, YYYY-MM-DD. */
  expectedDate: string;
}

/** A supplier's overdue POs, by expected date then PO number. */
export interface OverdueSupplier {
  supplierId: string;
  /** The supplier master's name; null when the master has none. */
  supplierName: string | null;
  pos: OverduePo[];
}

export interface OverdueList {
  /** When the list was made (ISO 8601 UTC); null when it hasn't been made yet. */
  madeAt: string | null;
  /** By supplier name. */
  suppliers: OverdueSupplier[];
}

type Wire = Record<string, unknown>;

function isWire(value: unknown): value is Wire {
  return value !== null && typeof value === "object";
}

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function po(value: unknown): OverduePo {
  if (
    !isWire(value) ||
    typeof value.po_number !== "string" ||
    typeof value.expected_date !== "string"
  ) {
    throw broken();
  }
  return { poNumber: value.po_number, expectedDate: value.expected_date };
}

function supplier(value: unknown): OverdueSupplier {
  if (
    !isWire(value) ||
    typeof value.supplier_id !== "string" ||
    (value.supplier_name !== null && typeof value.supplier_name !== "string") ||
    !Array.isArray(value.pos)
  ) {
    throw broken();
  }
  return {
    supplierId: value.supplier_id,
    supplierName: value.supplier_name,
    pos: value.pos.map(po),
  };
}

/**
 * The overdue list the weekday job last made (`GET /api/overdue-pos`, Story 4.2).
 * Rejects with the client's `ApiError` (401 and 503 `DB_OFFLINE` have already raised
 * their events) or when `signal` aborts.
 */
export async function getOverduePos(
  signal?: AbortSignal,
): Promise<OverdueList> {
  const body = await apiRequest<unknown>("/api/overdue-pos", { signal });
  if (
    !isWire(body) ||
    (body.made_at !== null && typeof body.made_at !== "string") ||
    !Array.isArray(body.suppliers)
  ) {
    throw broken();
  }
  return { madeAt: body.made_at, suppliers: body.suppliers.map(supplier) };
}
