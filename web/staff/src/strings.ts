// All user-facing copy for the staff app (coding-style.md rule 18, UX-DR2),
// worded as EXPERIENCE.md's Voice and Tone sets it. Components never hold copy.

import type { Side } from "@shared/quality/measure";

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

/** A file's size, as the supplier page shows it: "850 KB" or "1.2 MB". */
export function fileSize(bytes: number): string {
  // Rounded first, so 1,048,000 bytes reads "1.0 MB", never "1024 KB".
  const kb = Math.max(1, Math.round(bytes / 1024));
  if (kb < 1024) return `${kb} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A PO number as people say it: "PO 45016" for "PO-45016" or "45016". */
export function poLabel(poNumber: string): string {
  return `PO ${poNumber.replace(/^PO[-\s]*/i, "")}`;
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
  /** Story 2.11: opt-in keyboard shortcuts, off by default. */
  shortcuts: {
    toggle: "Keyboard shortcuts",
    helpHeading: "Keyboard shortcuts",
    helpIntro:
      "Single keys work when you're not typing in a field and no dialog is open.",
    close: "Close",
    keyColumn: "Key",
    actionColumn: "Does",
    keys: [
      { key: "j", action: "Next invoice in the queue" },
      { key: "k", action: "Previous invoice in the queue" },
      { key: "Enter", action: "Open the chosen invoice" },
      { key: "c", action: "Correct the fields" },
      { key: "a", action: "Approve the invoice" },
      { key: "r", action: "Reject the invoice" },
      { key: "n", action: "Next flag on the image" },
      { key: "p", action: "Previous flag on the image" },
      { key: "Esc", action: "Close a dialog, or go back to the queue" },
      { key: "?", action: "Show this list" },
    ],
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
    /** Story 2.10: corrected, then flagged again by the re-check. */
    returned: "Returned after correction",
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
      /** Story 3.3: the call-back checklist Approve needs (EXPERIENCE.md). */
      checklist: "Before you approve",
      calledNumber: "Called the number on file",
      supplierConfirmed: "Supplier confirmed the new account",
    },
    /** Story 3.3: DUPLICATE's side-by-side comparison (EXPERIENCE.md). */
    duplicate: {
      heading: "Possible duplicate",
      intro: "Compare it with the earlier invoice it matches.",
      thisInvoice: "This invoice",
      matching: "Matching invoice",
      received: "Received",
      supplier: "Supplier",
      total: "Total",
      imageAlt: (which: string) => `${which}: the invoice image`,
      noImage: "No image",
      /** DUPLICATE is open but its matching invoice can't be read. */
      unavailable: "Matching invoice unavailable.",
    },
    /** Story 3.3: ACCOUNTS_API_ERROR; Story 3.2 keeps only the status and code. */
    accountsError: {
      heading: "Couldn't post to accounts",
      answered: (status: number, code: string) =>
        `The accounts system answered with status ${status} (${code}).`,
      noAnswer: (code: string) =>
        `The accounts system didn't answer (${code}).`,
      unknown: "The accounts system's answer wasn't kept.",
      retry: "Approve to try posting again.",
    },
    /** Story 2.10: UNREADABLE and UNSUPPORTED_DOCUMENT (EXPERIENCE.md). */
    resend: {
      heading: "Ask for a new copy",
      prompt: "Ask the supplier to send it again.",
    },
    /** Story 2.10: the admin actions (EXPERIENCE.md Admin actions). */
    actions: {
      label: "Actions",
      correct: "Correct",
      approve: "Approve",
      /** Approve, when the open reason is a possible duplicate. */
      notDuplicate: "Not a duplicate",
      /** Beside a disabled Approve until both call-back checks are ticked. */
      tickBoth: "Tick both checks to approve.",
      reextract: "Re-extract",
      retryIntake: "Retry intake",
      reject: "Reject",
      cancel: "Cancel",
      working: "Working…",
      /** No action is offered (the server's guard allows none). */
      none: "No action is available for this invoice.",
      alreadyHandled: "Already handled by another admin.",
      notAllowed: "That action isn't allowed for this invoice any more.",
      sentForRecheck: "Sent for re-check",
      sentForExtraction: "Sent for extraction again",
      sentForIntake: "Sent through the quality check again",
      rejected: "Invoice rejected",
      approved: "Invoice approved and sent for posting",
      reextractDialog: {
        heading: "Extract this invoice again?",
        body: "It is read again and uses pages from this month's limit. Earlier corrections are dropped.",
        confirm: "Re-extract",
      },
      retryIntakeDialog: {
        heading: "Retry intake?",
        body: "The upload goes through the quality check again, then on to extraction.",
        confirm: "Retry intake",
      },
      rejectDialog: {
        heading: "Reject this invoice?",
        body: "It won't be paid. The reason is kept in the audit log.",
        reason: "Reason",
        hint: (left: number) =>
          `${left} ${left === 1 ? "character" : "characters"} left`,
        required: "Enter a reason to reject.",
        confirm: "Reject invoice",
      },
      /** WCAG 3.3.4: a summary before the admin confirms (EXPERIENCE.md). */
      approveDialog: {
        heading: "Approve this invoice?",
        body: "It is sent to the accounts system for payment. The reason is kept in the audit log.",
        supplier: "Supplier",
        amount: "Amount",
        reason: "Reason",
        required: "Enter a reason to approve.",
        confirm: "Approve invoice",
      },
    },
    /** Story 2.10: Correct mode (EXPERIENCE.md Field list). */
    correct: {
      heading: "Correct the fields",
      intro:
        "Fix what was misread, then save. Flagged fields you leave are confirmed as they are.",
      corrected: "Corrected",
      bankLocked: "Bank fields can't be edited.",
      dateHint: "YYYY-MM-DD",
      amountHint: "Like 1250.50",
      line: (n: number) => `Line ${n}`,
      save: "Save and re-check",
      nothing: "Change at least one field or line.",
      restored: "Your unsaved corrections were restored.",
    },
  },
  /** Story 3.4: search all invoices, and one invoice's detail (EXPERIENCE.md). */
  invoices: {
    found: (n: number) => `${plural(n, "invoice", "invoices")} found`,
    empty: "No invoices yet.",
    noMatch: "No invoices match this search.",
    tableLabel: "Invoices",
    search: "Search",
    clear: "Clear",
    filters: {
      search: "Invoice number, supplier or reference",
      searchHint: "Like INV-1042, a supplier name or R-7Q4KXM2D",
      status: "Status",
      allStatuses: "All statuses",
    },
    columns: {
      received: "Received",
      supplier: "Supplier",
      invoiceNumber: "Invoice number",
      total: "Total",
      status: "Status",
      reference: "Reference",
    },
    noNumber: "Not read yet",
    /** The server refused the search (the box itself never sends a refused one). */
    badSearch: "That search couldn't be run. Change it and search again.",
    detail: {
      back: "Back to invoices",
      heading: (supplier: string) => `Invoice from ${supplier}`,
      notFound: "This invoice can't be found.",
      summary: "Summary",
      received: "Received",
      supplier: "Supplier",
      status: "Status",
      reference: "Supplier reference",
      accountsRef: "Accounts reference",
      postedAt: "Posted",
      notPosted: "Not posted",
      fields: "Fields",
      noFields: "No fields were read.",
      bankOnFile: "Bank details on file",
      history: "Status history",
      historyLabel: "Status history",
      historyColumns: {
        at: "When",
        from: "From",
        to: "To",
        by: "By",
      },
      started: "New",
    },
    /** Who moved the invoice: a pipeline stage, an admin or the system, never a name. */
    actors: {
      quality: "Quality check",
      extract: "Extraction",
      validate: "Checks",
      post: "Posting",
      admin: "Admin",
      system: "System",
    } as Readonly<Record<string, string>>,
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
  /** Why a chosen file can't be sent (AD-6: JPEG, PNG or PDF, 4 MB or less); the
   * same words as the supplier page (src/upload.ts is shared with it). */
  fileRefused: {
    tooLarge:
      "This file is over 4 MB. Choose a smaller photo, or a PDF under 4 MB.",
    wrongType: "This file can't be sent. Choose a JPEG or PNG photo, or a PDF.",
    empty: "This file is empty. Choose the invoice again.",
  },
  /** Story 4.1: Goods-in scan (EXPERIENCE.md Delivery picker, Capture button, Quality
   * check, Flow 4 and the goods-in "Database stopped" state). */
  goodsIn: {
    today: "Today's deliveries",
    results: "Search results",
    search: "Search",
    searchLabel: "PO number or supplier",
    searchHint: "For a late delivery: at least 2 characters.",
    showToday: "Show today's deliveries",
    listLabel: "Deliveries",
    noneToday: "No deliveries today. Search by PO number or supplier.",
    noMatch: "No deliveries in the last 60 days match this search.",
    badSearch: "Enter at least 2 characters of a PO number or supplier.",
    unknownSupplier: "Unknown supplier",
    delivery: (n: number) => `Delivery ${n}`,
    scanFor: (po: string) => `Scan the invoice for ${po}`,
    otherDelivery: "Choose another delivery",
    takePhoto: "Take photo",
    chooseFile: "Choose file",
    cameraUnavailable:
      "Camera not available here. Tap Choose file to pick a photo, or open this page in your device's browser.",
    checkHeading: "Check & send",
    photo: "Photo",
    pdf: "PDF",
    send: "Send",
    chooseAgain: "Choose another file",
    sending: "Sending…",
    progressLabel: "Upload progress",
    failed: "Couldn't send. Check your connection and tap Send again.",
    checking: "Checking photo…",
    checkingPdf: "Checking PDF…",
    takeAgain: "Take again",
    sendAnyway: "Send it anyway",
    tooDark: "The photo is too dark. Move to better light and take it again.",
    blurry: "The photo is blurry. Hold the device still and take it again.",
    cutOff: (side: Side) =>
      `The ${side} edge is cut off. Fit the whole invoice in the photo and take it again.`,
    tooManyPages: "This PDF has more than 2 pages. Send a PDF of 1 or 2 pages.",
    deliveryGone:
      "This delivery can't be found. Choose it again from the list.",
    received: (po: string, supplier: string) =>
      `Received for ${po}, ${supplier}.`,
    scanAnother: "Scan another invoice",
    unavailableHeading: "Scanning unavailable",
    unavailable:
      "Scanning is unavailable until the system is back (weekdays 9am). Keep the paper invoice with the delivery.",
  },
  /** Screens not built yet show their heading and this line. */
  placeholder: "This page isn't ready yet.",
  /** EXPERIENCE.md staff surface table, one name per surface. */
  surfaces: {
    admin_queue: "Admin queue",
    admin_item: "Admin item",
    goods_in_scan: "Goods-in scan",
    invoices: "Invoices",
    invoice_detail: "Invoice",
    overdue_pos: "Overdue POs",
    suppliers: "Suppliers",
    supplier_scorecard: "Supplier scorecard",
    price_comparison: "Price comparison",
    watchlist: "Watchlist",
    finance_month: "Finance month",
  },
} as const;
