import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** A rise behind `price_rises`: the previous and the rising price of one material. */
export interface RiseEvidence {
  materialId: string;
  materialName: string | null;
  /** Null for roles that can't open an invoice. */
  invoiceId: string | null;
  invoiceDate: string;
  unitPrice: string;
  previousInvoiceId: string | null;
  previousInvoiceDate: string;
  previousUnitPrice: string;
  /** 2-decimal percentage string. */
  pct: string;
}

/** A late goods-receipt line behind `late`. */
export interface LateEvidence {
  materialId: string;
  materialName: string | null;
  receivedDate: string;
  daysLate: number;
}

/** A material whose latest price is 5% or more above the cheapest supplier's. */
export interface GapEvidence {
  materialId: string;
  materialName: string | null;
  invoiceId: string | null;
  invoiceDate: string;
  unitPrice: string;
  lowestUnitPrice: string;
  cheapestSupplierId: string;
  cheapestSupplierName: string | null;
  pct: string;
}

/** The rule a supplier is listed under (AD-20), with its evidence. */
export type WatchlistRule =
  | { rule: "price_rises"; firstAddedOn: string; evidence: RiseEvidence[] }
  | {
      rule: "late";
      firstAddedOn: string;
      /** 2-decimal string; null when the server has no average. */
      avgDaysLate: string | null;
      evidence: LateEvidence[];
    }
  | { rule: "price_gap"; firstAddedOn: string; evidence: GapEvidence[] };

/** Another supplier of a material, ranked by the server (CAP-16). */
export interface AlternativeSupplier {
  supplierId: string;
  supplierName: string | null;
  latestUnitPrice: string;
  /** 4-decimal string; null when the supplier has no receipts. */
  onTimeRate: string | null;
  /** True when this supplier is itself on the watchlist. */
  watchlisted: boolean;
}

export interface Alternatives {
  materialId: string;
  materialName: string | null;
  suppliers: AlternativeSupplier[];
}

export interface WatchlistEntry {
  supplierId: string;
  supplierName: string | null;
  rules: WatchlistRule[];
  alternatives: Alternatives[];
}

export interface Watchlist {
  /** False until any invoice has been posted. */
  hasPricePoints: boolean;
  /** The most recently listed first. */
  entries: WatchlistEntry[];
}

type Wire = Record<string, unknown>;

function broken(): ApiError {
  return new ApiError(strings.errors.generic, 200, null, null);
}

function wire(value: unknown): Wire {
  if (value === null || typeof value !== "object") throw broken();
  return value as Wire;
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

function list(value: Wire, key: string): Wire[] {
  const held = value[key];
  if (!Array.isArray(held)) throw broken();
  return held.map(wire);
}

function material(row: Wire): {
  materialId: string;
  materialName: string | null;
} {
  return {
    materialId: text(row, "material_id"),
    materialName: textOrNull(row, "material_name"),
  };
}

/** A rule this page knows, or null for one it doesn't (skipped, not an error). */
function rule(row: Wire): WatchlistRule | null {
  const firstAddedOn = text(row, "first_added_on");
  const evidence = list(row, "evidence");
  switch (row.rule) {
    case "price_rises":
      return {
        rule: "price_rises",
        firstAddedOn,
        evidence: evidence.map((item) => ({
          ...material(item),
          invoiceId: textOrNull(item, "invoice_id"),
          invoiceDate: text(item, "invoice_date"),
          unitPrice: text(item, "unit_price"),
          previousInvoiceId: textOrNull(item, "previous_invoice_id"),
          previousInvoiceDate: text(item, "previous_invoice_date"),
          previousUnitPrice: text(item, "previous_unit_price"),
          pct: text(item, "pct"),
        })),
      };
    case "late":
      return {
        rule: "late",
        firstAddedOn,
        avgDaysLate: textOrNull(row, "avg_days_late"),
        evidence: evidence.map((item) => {
          if (typeof item.days_late !== "number") throw broken();
          return {
            ...material(item),
            receivedDate: text(item, "received_date"),
            daysLate: item.days_late,
          };
        }),
      };
    case "price_gap":
      return {
        rule: "price_gap",
        firstAddedOn,
        evidence: evidence.map((item) => ({
          ...material(item),
          invoiceId: textOrNull(item, "invoice_id"),
          invoiceDate: text(item, "invoice_date"),
          unitPrice: text(item, "unit_price"),
          lowestUnitPrice: text(item, "lowest_unit_price"),
          cheapestSupplierId: text(item, "cheapest_supplier_id"),
          cheapestSupplierName: textOrNull(item, "cheapest_supplier_name"),
          pct: text(item, "pct"),
        })),
      };
    default:
      return null;
  }
}

/**
 * The watchlisted suppliers with their evidence and ranked alternatives
 * (`GET /api/watchlist`, Story 5.4). Rejects with the client's `ApiError` or when
 * `signal` aborts.
 */
export async function getWatchlist(signal?: AbortSignal): Promise<Watchlist> {
  const body = wire(await apiRequest<unknown>("/api/watchlist", { signal }));
  if (typeof body.has_price_points !== "boolean") throw broken();
  return {
    hasPricePoints: body.has_price_points,
    entries: list(body, "entries").map((entry) => ({
      supplierId: text(entry, "supplier_id"),
      supplierName: textOrNull(entry, "supplier_name"),
      rules: list(entry, "rules")
        .map(rule)
        .filter((held): held is WatchlistRule => held !== null),
      alternatives: list(entry, "alternatives").map((item) => ({
        ...material(item),
        suppliers: list(item, "suppliers").map((row) => ({
          supplierId: text(row, "supplier_id"),
          supplierName: textOrNull(row, "supplier_name"),
          latestUnitPrice: text(row, "latest_unit_price"),
          onTimeRate: textOrNull(row, "on_time_rate"),
          watchlisted: row.watchlisted === true,
        })),
      })),
    })),
  };
}
