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
