"""The one reason catalogue of the admin queue (AD-4). Stages never invent their own
reason strings: every `intake.admin_item.reason` is one of these."""

from enum import StrEnum


class ReasonCode(StrEnum):
    """Why an invoice is in the admin queue (AD-4)."""

    # Intake (quality stage, AD-6) and extraction (AD-8).
    UNREADABLE = "UNREADABLE"
    UNSUPPORTED_DOCUMENT = "UNSUPPORTED_DOCUMENT"
    EXTRACTION_QUOTA = "EXTRACTION_QUOTA"
    # Validation (AD-19).
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PO_MISMATCH = "PO_MISMATCH"
    DUPLICATE = "DUPLICATE"
    DATE_MISMATCH = "DATE_MISMATCH"
    NO_PHOTO_DATE = "NO_PHOTO_DATE"
    BANK_CHANGED = "BANK_CHANGED"
    SUPPLIER_ID_MISMATCH = "SUPPLIER_ID_MISMATCH"
    # Posting (AD-10) and poison messages (AD-2).
    ACCOUNTS_API_ERROR = "ACCOUNTS_API_ERROR"
    PROCESSING_FAILED = "PROCESSING_FAILED"
