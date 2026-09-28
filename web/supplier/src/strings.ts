// All user-facing copy for the supplier page (coding-style.md rule 18, UX-DR2),
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

/** A file's size for the Check & send summary: "850 KB" or "1.2 MB". */
export function fileSize(bytes: number): string {
  // Rounded first, so 1,048,000 bytes reads "1.0 MB", never "1024 KB".
  const kb = Math.max(1, Math.round(bytes / 1024));
  if (kb < 1024) return `${kb} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
    /** EXPERIENCE.md "Capture button": camera permission denied or blocked in-app. */
    cameraUnavailable:
      "Camera not available here. Tap Choose file to pick a photo, or open this link in your phone's browser.",
  },
  /** Why a chosen file can't be sent (AD-6: JPEG, PNG or PDF, 4 MB or less). */
  fileRefused: {
    tooLarge:
      "This file is over 4 MB. Choose a smaller photo, or a PDF under 4 MB.",
    wrongType: "This file can't be sent. Choose a JPEG or PNG photo, or a PDF.",
    empty: "This file is empty. Choose the invoice again.",
  },
  /** EXPERIENCE.md "Check & send" and its Upload states (UX-DR5). */
  checkAndSend: {
    heading: "Check & send",
    pageTitle: "Check & send – Babaloo",
    photo: "Photo",
    pdf: "PDF",
    send: "Send",
    chooseAgain: "Choose another file",
    sending: "Sending…",
    progressLabel: "Upload progress",
    failed: "Couldn't send. Check your connection and tap Send again.",
    /** Story 1.9: the on-device check (EXPERIENCE.md "Quality check"). */
    checking: "Checking photo…",
    checkingPdf: "Checking PDF…",
    takeAgain: "Take again",
    sendAnyway: "Send it anyway",
    tooDark: "The photo is too dark. Move to better light and take it again.",
    blurry: "The photo is blurry. Hold the phone still and take it again.",
    cutOff: (side: Side) =>
      `The ${side} edge is cut off. Fit the whole invoice in the photo and take it again.`,
    tooManyPages: "This PDF has more than 2 pages. Send a PDF of 1 or 2 pages.",
  },
  /** EXPERIENCE.md "Received": "Received. Reference R-7Q4KXM2D." */
  received: {
    heading: "Received.",
    reference: "Reference",
    uploadAnother: "Upload another",
    pageTitle: "Received – Babaloo",
  },
  /** EXPERIENCE.md "Link not working" (UX-DR7): identical for revoked and unknown links. */
  linkNotWorking: {
    heading: "This link isn't working.",
    body: "Please contact your buyer at Babaloo.",
    pageTitle: "Link not working – Babaloo",
  },
} as const;
