// All user-facing copy for the supplier page (coding-style.md rule 18, UX-DR2),
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

/** A page title: the screen's own words, then the company name. */
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
  /** Skeleton, then this line after 3 s (UX-DR20: the app scales to zero when idle). */
  loading: {
    label: "Loading",
    pageTitle: "Loading – Babaloo",
    wakingUp: "Waking up, one moment…",
  },
  /** EXPERIENCE.md "Upload home" (UX-DR4); the supplier name is shown in bold after the prefix. */
  uploadHome: {
    uploadingFor: "Uploading for",
    takePhoto: "Take photo",
    chooseFile: "Choose file",
    pageTitle: "Upload – Babaloo",
  },
  /** EXPERIENCE.md "Link not working" (UX-DR7): identical for revoked and unknown links. */
  linkNotWorking: {
    heading: "This link isn't working.",
    body: "Please contact your buyer at Babaloo.",
    pageTitle: "Link not working – Babaloo",
  },
} as const;
