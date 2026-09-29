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

function plural(n: number, one: string, many: string): string {
  return `${n} ${n === 1 ? one : many}`;
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
  /** Story 2.8: the admin queue (EXPERIENCE.md Queue table and State Patterns). */
  queue: {
    waiting: (n: number) => `${plural(n, "invoice", "invoices")} waiting`,
    empty: "Nothing waiting. New exceptions appear here automatically.",
    noMatch: "No invoices match these filters.",
    pageUsage: (used: number, cap: number) =>
      `${used} of ${cap} pages used this month.`,
    tableLabel: "Invoices waiting for an admin",
    columns: {
      received: "Received",
      supplier: "Supplier",
      amount: "Amount",
      reasons: "Reasons",
      age: "Age",
    },
    /** A supplier the master has no name for (should not happen). */
    unknownSupplier: "Unknown supplier",
    noAmount: "Not read yet",
    /** A reason code this build doesn't know yet (a newer API). */
    otherReason: "Needs a look",
    blocking: "Blocking",
    filters: {
      reason: "Reason",
      supplier: "Supplier",
      allReasons: "All reasons",
      allSuppliers: "All suppliers",
    },
    pagination: {
      label: "Pages",
      previous: "Previous page",
      next: "Next page",
      status: (page: number, pages: number) => `Page ${page} of ${pages}`,
    },
    /** How long an invoice has waited, from when it was received. */
    age: (minutes: number) => {
      if (minutes < 60) return "Under an hour";
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return plural(hours, "hour", "hours");
      return plural(Math.floor(hours / 24), "day", "days");
    },
  },
  /** Story 2.9: the admin item (EXPERIENCE.md Image viewer, Field list, Bank-change
   * panel and Masked value). */
  item: {
    back: "Back to the queue",
    from: (supplier: string) => `From ${supplier}`,
    received: (when: string) => `Received ${when}`,
    reasons: "Reasons",
    notFound: "This invoice isn't waiting in the queue any more.",
    viewer: {
      label: "Invoice image",
      imageAlt: "The invoice",
      deleted: "Image deleted after 30 days",
      failed: "The image couldn't be loaded.",
      openPdf: "Open the PDF",
      pdfNote: "PDFs open in a new tab; the flagged fields are listed here.",
      noBoxes: "This reading has no field positions, so no boxes are drawn.",
      controls: "Image controls",
      previous: "Previous flag",
      next: "Next flag",
      whole: "Show whole invoice",
      zoomIn: "Zoom in",
      zoomOut: "Zoom out",
      panLeft: "Pan left",
      panRight: "Pan right",
      panUp: "Pan up",
      panDown: "Pan down",
      position: (n: number, total: number) => `Flag ${n} of ${total}`,
      noFlags: "No flagged areas",
      noSelection: (total: number) =>
        `No flag selected (${total} ${total === 1 ? "flag" : "flags"})`,
    },
    fields: {
      heading: "Fields",
      flagged: "Flagged",
      notRead: "Not read",
      /** Screen-reader prefix of the badge: announced as "Confidence 91%". */
      confidence: "Confidence",
      box: (n: number) => `Box ${n}`,
      selected: (label: string) => `Selected: ${label}`,
      bankOnFile: "Bank details on file",
      none: "No fields were read.",
    },
    lines: {
      heading: "Lines",
      label: "Invoice lines",
      columns: {
        line: "Line",
        productCode: "Product code",
        description: "Description",
        quantity: "Quantity",
        unitPrice: "Unit price",
        amount: "Amount",
      },
    },
    bank: {
      heading: "Bank details changed",
      call: (phone: string) => `Call ${phone} (number on file)`,
      noPhone: "No phone number on file",
      onFile: "On file",
      onInvoice: "On this invoice",
      noAccount: "No account on file",
      notRead: "Not read",
      ending: (digits: string) => `account ending ${digits}`,
      /** A value too short to mask shows no digits at all (AD-11). */
      noDigits: "account on file, digits hidden",
      show: "Show",
      showLabel: (digits: string) =>
        digits ? `Show account ending ${digits}` : "Show account",
      hide: "Hide",
      keepShowing: "Keep showing",
      warning: "The account number hides in 10 seconds.",
      hidden: "The account number is hidden again.",
      failed: "Couldn't show the account number. Try again.",
    },
  },
  /** AD-18 field ids as the admin reads them; any other id is shown as it is. */
  fieldLabels: {
    vendor_name: "Supplier name",
    vendor_tax_id: "Supplier tax ID",
    vendor_address: "Supplier address",
    customer_name: "Customer name",
    invoice_number: "Invoice number",
    invoice_date: "Invoice date",
    due_date: "Due date",
    purchase_order: "PO number",
    sub_total: "Subtotal",
    total_tax: "Tax",
    invoice_total: "Invoice total",
    amount_due: "Amount due",
  } as Readonly<Record<string, string>>,
  /** `payment[<n>].<id>` bank fields, with their payment number from 1. */
  bankFieldLabel: (kind: string, payment: number) => {
    const names: Readonly<Record<string, string>> = {
      bank_account_number: "Account number",
      iban: "IBAN",
      swift: "SWIFT code",
    };
    return `${names[kind] ?? kind} (payment ${payment})`;
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
