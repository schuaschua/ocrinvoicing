import { describe, expect, it } from "vitest";

import {
  reasonLabels,
  statusLabel,
  statusLabels,
  type InvoiceStatus,
} from "@/strings";

// EXPERIENCE.md "Reason labels" and "Status labels", word for word (UX-DR2).
const REASONS = {
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

const STATUSES = {
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

describe("1.4 strings module", () => {
  it("holds exactly the 12 AD-4 reason labels", () => {
    expect(reasonLabels).toEqual(REASONS);
    expect(Object.keys(reasonLabels)).toHaveLength(12);
  });

  it("labels every invoice status, never showing the code", () => {
    expect(statusLabels).toEqual(STATUSES);
  });

  it("reads Re-checking only for a checking status after a correction", () => {
    expect(statusLabel("validating", { afterCorrection: true })).toBe(
      "Re-checking",
    );
    expect(statusLabel("awaiting_validation", { afterCorrection: true })).toBe(
      "Re-checking",
    );
    expect(statusLabel("validating")).toBe("Checking");
    expect(statusLabel("posted", { afterCorrection: true })).toBe("Posted");
  });

  it("falls back to a neutral label for an unknown status", () => {
    expect(statusLabel("archived" as InvoiceStatus)).toBe("Processing");
  });
});
