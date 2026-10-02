import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** A material with posted prices (Story 5.3). */
export interface Material {
  materialId: string;
  name: string;
}

/** A supplier's latest price for the material, with its on-time rate. */
export interface SupplierPrice {
  supplierId: string;
  /** The supplier master's name; null when the master has none. */
  supplierName: string | null;
  /** 2-decimal string, SGD. */
  latestUnitPrice: string;
  /** YYYY-MM-DD. */
  latestInvoiceDate: string;
  /** 4-decimal string; null when the supplier has no receipts. */
  onTimeRate: string | null;
}

/** One posted price, for the chart. */
export interface PricePoint {
  supplierId: string;
  invoiceDate: string;
  unitPrice: string;
}

/** An invoice behind an alert; `invoiceId` is null for roles that can't open one. */
export interface Evidence {
  invoiceId: string | null;
  invoiceDate: string;
  unitPrice: string;
}

export interface PriceAlert {
  alertId: string;
  createdAt: string;
  supplierId: string;
  supplierName: string | null;
  /** 2-decimal percentage string. */
  pct: string;
  /** The previous price, then the rising one. */
  evidence: Evidence[];
}

export interface PriceComparison {
  materialId: string;
  name: string;
  /** By latest price, then on-time rate (the server's order). */
  suppliers: SupplierPrice[];
  /** The last 365 days. */
  history: PricePoint[];
  /** Newest first. */
  alerts: PriceAlert[];
}

type Wire = Record<string, unknown>;

function isWire(value: unknown): value is Wire {
  return value !== null && typeof value === "object";
}

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function text(value: Wire, key: string): string {
  const held = value[key];
  if (typeof held !== "string") throw broken();
  return held;
}

function textOrNull(value: Wire, key: string): string | null {
  const held = value[key];
  if (held !== null && typeof held !== "string") throw broken();
  return held;
}

function wire(value: unknown): Wire {
  if (!isWire(value)) throw broken();
  return value;
}

function list(value: Wire, key: string): unknown[] {
  const held = value[key];
  if (!Array.isArray(held)) throw broken();
  return held;
}

/**
 * The materials with posted prices, by name (`GET /api/materials`, Story 5.3).
 * Rejects with the client's `ApiError` or when `signal` aborts.
 */
export async function getMaterials(signal?: AbortSignal): Promise<Material[]> {
  const body = wire(await apiRequest<unknown>("/api/materials", { signal }));
  return list(body, "items").map((item) => {
    const row = wire(item);
    return { materialId: text(row, "material_id"), name: text(row, "name") };
  });
}

/**
 * One material's suppliers, price history and price-rise alerts
 * (`GET /api/price-comparison`, Story 5.3). Rejects with the client's `ApiError`
 * (404 for a material without prices) or when `signal` aborts.
 */
export async function getPriceComparison(
  materialId: string,
  signal?: AbortSignal,
): Promise<PriceComparison> {
  const query = new URLSearchParams({ material_id: materialId });
  const body = wire(
    await apiRequest<unknown>(`/api/price-comparison?${query.toString()}`, {
      signal,
    }),
  );
  return {
    materialId: text(body, "material_id"),
    name: text(body, "name"),
    suppliers: list(body, "suppliers").map((item) => {
      const row = wire(item);
      return {
        supplierId: text(row, "supplier_id"),
        supplierName: textOrNull(row, "supplier_name"),
        latestUnitPrice: text(row, "latest_unit_price"),
        latestInvoiceDate: text(row, "latest_invoice_date"),
        onTimeRate: textOrNull(row, "on_time_rate"),
      };
    }),
    history: list(body, "history").map((item) => {
      const row = wire(item);
      return {
        supplierId: text(row, "supplier_id"),
        invoiceDate: text(row, "invoice_date"),
        unitPrice: text(row, "unit_price"),
      };
    }),
    alerts: list(body, "alerts").map((item) => {
      const row = wire(item);
      return {
        alertId: text(row, "alert_id"),
        createdAt: text(row, "created_at"),
        supplierId: text(row, "supplier_id"),
        supplierName: textOrNull(row, "supplier_name"),
        pct: text(row, "pct"),
        evidence: list(row, "evidence").map((entry) => {
          const held = wire(entry);
          return {
            invoiceId: textOrNull(held, "invoice_id"),
            invoiceDate: text(held, "invoice_date"),
            unitPrice: text(held, "unit_price"),
          };
        }),
      };
    }),
  };
}
