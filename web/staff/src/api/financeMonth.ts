import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/** The month's share of invoices posted without an admin, against the target. */
export interface StraightThrough {
  /** 4-decimal string; null when nothing was posted in the month. */
  share: string | null;
  postedCount: number;
  straightThroughCount: number;
  /** 4-decimal string ("0.9000"). */
  target: string;
}

/** One month's straight-through share, for the chart. */
export interface MonthShare {
  /** YYYY-MM. */
  month: string;
  /** 4-decimal string. */
  share: string;
}

/** A supplier's figures for the month (CAP-18). */
export interface SupplierMonth {
  supplierId: string;
  /** The supplier master's name; null when the master has none. */
  supplierName: string | null;
  /** 2-decimal string, SGD. */
  spend: string;
  postedCount: number;
  priceRises: number;
  flaggedCount: number;
  duplicateCount: number;
}

export interface FinanceMonth {
  /** YYYY-MM. */
  month: string;
  /** The months with any data, newest first. */
  months: string[];
  straightThrough: StraightThrough;
  /** Every month's share, oldest first. */
  history: MonthShare[];
  /** By spend, then name (the server's order). */
  suppliers: SupplierMonth[];
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

function count(value: Wire, key: string): number {
  const held = value[key];
  if (typeof held !== "number") throw broken();
  return held;
}

function list(value: Wire, key: string): unknown[] {
  const held = value[key];
  if (!Array.isArray(held)) throw broken();
  return held;
}

/**
 * One month's figures per supplier and its straight-through share
 * (`GET /api/finance-month`, Story 5.6); `month` is YYYY-MM, or null for the latest
 * month with data. Rejects with the client's `ApiError` or when `signal` aborts.
 */
export async function getFinanceMonth(
  month: string | null,
  signal?: AbortSignal,
): Promise<FinanceMonth> {
  const query =
    month === null ? "" : `?${new URLSearchParams({ month }).toString()}`;
  const body = wire(
    await apiRequest<unknown>(`/api/finance-month${query}`, { signal }),
  );
  const held = wire(body["straight_through"]);
  return {
    month: text(body, "month"),
    months: list(body, "months").map((item) => {
      if (typeof item !== "string") throw broken();
      return item;
    }),
    straightThrough: {
      share: textOrNull(held, "share"),
      postedCount: count(held, "posted_count"),
      straightThroughCount: count(held, "straight_through_count"),
      target: text(held, "target"),
    },
    history: list(body, "history").map((item) => {
      const row = wire(item);
      return { month: text(row, "month"), share: text(row, "share") };
    }),
    suppliers: list(body, "suppliers").map((item) => {
      const row = wire(item);
      return {
        supplierId: text(row, "supplier_id"),
        supplierName: textOrNull(row, "supplier_name"),
        spend: text(row, "spend"),
        postedCount: count(row, "posted_count"),
        priceRises: count(row, "price_rises"),
        flaggedCount: count(row, "flagged_count"),
        duplicateCount: count(row, "duplicate_count"),
      };
    }),
  };
}
