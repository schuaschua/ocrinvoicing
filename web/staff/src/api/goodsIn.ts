import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** One delivery goods-in can scan against (`GET /api/goods-in/deliveries`, Story 4.1). */
export interface DeliveryRow {
  deliveryId: string;
  poNumber: string;
  deliveryNo: number;
  /** YYYY-MM-DD. */
  deliveryDate: string;
  /** The supplier master's name; null when the master has none. */
  supplierName: string | null;
}

export interface DeliveryList {
  /** The server's today (Singapore), YYYY-MM-DD. */
  today: string;
  items: DeliveryRow[];
}

type Wire = Record<string, unknown>;

function isWire(value: unknown): value is Wire {
  return value !== null && typeof value === "object";
}

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function row(value: unknown): DeliveryRow {
  if (
    !isWire(value) ||
    typeof value.delivery_id !== "string" ||
    typeof value.po_number !== "string" ||
    typeof value.delivery_no !== "number" ||
    typeof value.delivery_date !== "string"
  ) {
    throw broken();
  }
  return {
    deliveryId: value.delivery_id,
    poNumber: value.po_number,
    deliveryNo: value.delivery_no,
    deliveryDate: value.delivery_date,
    supplierName:
      typeof value.supplier_name === "string" ? value.supplier_name : null,
  };
}

/**
 * Today's deliveries, or with `search` those of the last 60 days whose PO number or
 * supplier matches it, newest first. Rejects with the client's `ApiError` (401 and 503
 * `DB_OFFLINE` have already raised their events) or when `signal` aborts.
 */
export async function listDeliveries(
  search: string | null,
  signal?: AbortSignal,
): Promise<DeliveryList> {
  const path =
    search === null
      ? "/api/goods-in/deliveries"
      : `/api/goods-in/deliveries?${new URLSearchParams({ q: search })}`;
  const body = await apiRequest<unknown>(path, { signal });
  if (
    !isWire(body) ||
    typeof body.today !== "string" ||
    !Array.isArray(body.items)
  ) {
    throw broken();
  }
  return { today: body.today, items: body.items.map(row) };
}
