// All user-facing copy for the staff app (coding-style.md rule 18, UX-DR2),
// worded as EXPERIENCE.md's Voice and Tone sets it. Components never hold copy.

/** AD-4 admin-queue reason codes. */
export type ReasonCode =
  | "UNREADABLE"
  | "UNSUPPORTED_DOCUMENT"
  | "EXTRACTION_QUOTA"
  | "LOW_CONFIDENCE"
  | "PO_MISMATCH"
  | "DUPLICATE"
  | "DATE_MISMATCH"
  | "NO_PHOTO_DATE"
  | "BANK_CHANGED"
  | "SUPPLIER_ID_MISMATCH"
  | "ACCOUNTS_API_ERROR"
  | "PROCESSING_FAILED";

/** AD-3 invoice statuses (`intake.invoice.status`). */
export type InvoiceStatus =
  | "received"
  | "awaiting_extraction"
  | "extracting"
  | "awaiting_validation"
  | "validating"
  | "ready_to_post"
  | "posting"
  | "posted"
  | "in_admin_queue"
  | "rejected";

/** EXPERIENCE.md "Reason labels": the only labels used for AD-4 codes. */
export const reasonLabels: Readonly<Record<ReasonCode, string>> = {
  UNREADABLE: "Photo unreadable",
  UNSUPPORTED_DOCUMENT: "More than 2 pages",
  EXTRACTION_QUOTA: "Monthly page limit reached",
  LOW_CONFIDENCE: "Unsure reading",
  PO_MISMATCH: "Amount doesn't match PO",
  DUPLICATE: "Possible duplicate",
  DATE_MISMATCH: "Photo date doesn't match delivery",
  NO_PHOTO_DATE: "No photo date",
  BANK_CHANGED: "Bank details changed",
  SUPPLIER_ID_MISMATCH: "Supplier on invoice doesn't match",
  ACCOUNTS_API_ERROR: "Couldn't post to accounts",
  PROCESSING_FAILED: "Processing failed",
};

/** EXPERIENCE.md "Status labels": statuses are shown as labels, never as codes. */
export const statusLabels: Readonly<Record<InvoiceStatus, string>> = {
  received: "Processing",
  awaiting_extraction: "Processing",
  extracting: "Processing",
  awaiting_validation: "Checking",
  validating: "Checking",
  ready_to_post: "Posting",
  posting: "Posting",
  posted: "Posted",
  in_admin_queue: "In admin queue",
  rejected: "Rejected",
};

const RECHECKING = "Re-checking";
const FALLBACK_STATUS = "Processing";

/** The label for a status; "Checking" reads "Re-checking" after an admin correction. */
export function statusLabel(
  status: InvoiceStatus,
  options: { afterCorrection?: boolean } = {},
): string {
  if (
    options.afterCorrection &&
    (status === "awaiting_validation" || status === "validating")
  ) {
    return RECHECKING;
  }
  // A status this build doesn't know yet (a newer API) still reads as work in progress.
  return statusLabels[status] ?? FALLBACK_STATUS;
}

/** A page title: the page's own words, then the company name (UX-DR21). */
export function pageTitle(text: string): string {
  return `${text} – Babaloo`;
}

export const strings = {
  appName: "Babaloo",
  errors: {
    generic: "Something went wrong. Try again later.",
    network: "Couldn't reach Babaloo. Check your connection and try again.",
    tryAgain: "Try again",
  },
  // EXPERIENCE.md State Patterns, shown on the API client's events (UX-DR3).
  sessionExpired: "Your session ended. Sign in again to continue.",
  signIn: "Sign in",
  signOut: "Sign out",
  offline:
    "The system is offline outside working hours (weekdays 9am–9pm). Supplier uploads still arrive and will be processed when it's back.",
  offlineHeading: "System offline",
  /** Skeleton rows, then this line after 3 s (UX-DR20: the app scales to zero when idle). */
  loading: {
    label: "Loading",
    wakingUp: "Waking up, one moment…",
  },
  /** EXPERIENCE.md State Patterns "Not allowed": an inline Alert on the landing page. */
  notAllowed: "You don't have access to that page.",
  /** Signed in, but with no app role (Story 2.7). */
  noAccess: {
    heading: "No access yet",
    body: "You're signed in, but you haven't been given a role in Babaloo. Ask your administrator to add one, then sign in again.",
  },
  nav: {
    label: "Pages",
    menu: "Menu",
    close: "Close menu",
  },
  /** Screens not built yet show their heading and this line. */
  placeholder: "This page isn't ready yet.",
  /** EXPERIENCE.md staff surface table, one name per surface. */
  surfaces: {
    admin_queue: "Admin queue",
    admin_item: "Admin item",
    goods_in_scan: "Goods-in scan",
    invoices: "Invoices",
    overdue_pos: "Overdue POs",
    suppliers: "Suppliers",
    supplier_scorecard: "Supplier scorecard",
    price_comparison: "Price comparison",
    watchlist: "Watchlist",
    finance_month: "Finance month",
  },
} as const;
