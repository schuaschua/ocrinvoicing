import { strings } from "@/strings";

/** "SGD 1,248.50": the server's 2-decimal string, grouped for reading, never computed. */
export function amountText(
  amount: string | null,
  currency: string | null,
): string {
  if (amount === null) return strings.queue.noAmount;
  const [whole = "", cents] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const text = cents === undefined ? grouped : `${grouped}.${cents}`;
  return currency === null ? text : `${currency} ${text}`;
}

function two(n: number): string {
  return String(n).padStart(2, "0");
}

/** A timestamp in the browser's time zone, as YYYY-MM-DD HH:mm. */
export function dateTimeText(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}

// en-CA formats a date as YYYY-MM-DD.
const SINGAPORE_DATE = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Asia/Singapore",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** A timestamp's Singapore date, as YYYY-MM-DD: the business day (spine: Dates),
 * whatever the viewer's time zone. */
export function singaporeDateText(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return SINGAPORE_DATE.format(at);
}

/** "S$4.20": a 2-decimal price string in the invoice currency (SGD, AD-20). */
export function priceText(amount: string): string {
  return `S$${amountText(amount, null)}`;
}

/** "2.5" for "2.50": a 2-decimal percentage without its trailing zeros. */
export function percentText(pct: string): string {
  return pct.includes(".") ? pct.replace(/\.?0+$/, "") : pct;
}

/** "80%" or "87.5%": a 4-decimal rate string as a percentage, for display only. */
export function rateText(rate: string): string {
  return `${percentText((Number(rate) * 100).toFixed(1))}%`;
}

/** An on-time rate as `rateText` shows it, except that it never reads 100% while
 * some receipts were late, nor 0% while some were on time (99.9% and 0.1%). */
export function onTimeRateText(
  rate: string,
  onTime: number,
  receipts: number,
): string {
  const text = rateText(rate);
  if (text === "100%" && onTime < receipts) return "99.9%";
  if (text === "0%" && onTime > 0) return "0.1%";
  return text;
}

/** "8" for "8.00", "7.5" for "7.50": a 2-decimal number of days, for display only. */
export function daysText(days: string): string {
  return days.includes(".") ? days.replace(/\.?0+$/, "") : days;
}

const MONTH_NAME = new Intl.DateTimeFormat("en-SG", {
  timeZone: "UTC",
  month: "long",
  year: "numeric",
});

/** "September 2026" for "2026-09"; anything else as given. */
export function monthText(month: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(month);
  if (match === null) return month;
  return MONTH_NAME.format(
    new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)),
  );
}

/** "67%" for "0.6667": a 4-decimal share as a whole percentage, for display only. */
export function wholePercentText(rate: string): string {
  return `${Math.round(Number(rate) * 100)}%`;
}
