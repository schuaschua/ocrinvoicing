// The page's own upload rules and helpers (Story 1.8). The server enforces the same
// rules by the file's bytes whatever the page did (AD-6, coding-style.md rule 16);
// checking here only saves the supplier a wasted upload.

import { strings } from "@/strings";

/** AD-6: 4 MB or less. */
export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;

/** AD-6: JPEG, PNG or PDF. */
export const ACCEPTED_TYPES = ["image/jpeg", "image/png", "application/pdf"];

/** The `accept` of the Take photo input: what a camera saves, never HEIC or WebP. */
export const TAKE_PHOTO_ACCEPT = "image/jpeg,image/png";

/** The `accept` of the Choose file input: the types, and their extensions for pickers that match by name. */
export const CHOOSE_FILE_ACCEPT = [
  ...ACCEPTED_TYPES,
  ".jpg",
  ".jpeg",
  ".png",
  ".pdf",
].join(",");

// Older or non-standard names some browsers and pickers still report.
const TYPE_ALIASES: Readonly<Record<string, string>> = {
  "image/jpg": "image/jpeg",
  "image/pjpeg": "image/jpeg",
  "image/x-png": "image/png",
};

/** `type` in its standard spelling (lower case, aliases resolved). */
export function normalisedType(type: string): string {
  const lower = type.toLowerCase();
  return TYPE_ALIASES[lower] ?? lower;
}

/** Whether `file` is a PDF, by its type or, when the picker gave none, its name. */
export function isPdf(file: File): boolean {
  const type = normalisedType(file.type);
  return (
    type === "application/pdf" ||
    (type === "" && file.name.toLowerCase().endsWith(".pdf"))
  );
}

/** Why `file` can't be sent, or null when the page lets it through. */
export function refusal(file: File): string | null {
  if (file.size === 0) return strings.fileRefused.empty;
  const type = normalisedType(file.type);
  // An empty type (some pickers don't say) is left to the server, which reads the bytes.
  if (type !== "" && !ACCEPTED_TYPES.includes(type)) {
    return strings.fileRefused.wrongType;
  }
  if (file.size > MAX_UPLOAD_BYTES) return strings.fileRefused.tooLarge;
  return null;
}

/**
 * A new upload key (AD-6): a random UUID made once for each chosen file, so a retry of
 * that file can never create a second invoice. `crypto.randomUUID` needs a secure
 * context; the fallback builds the same version 4 UUID from `getRandomValues`.
 */
export function newUploadKey(source: Crypto = crypto): string {
  if (typeof source.randomUUID === "function") return source.randomUUID();
  const bytes = source.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6]! & 0x0f) | 0x40;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Whether this browser can reach a camera. False only when it says so (no video input
 * at all); when it can't tell, the native camera input decides. A hint only: Take
 * photo stays usable either way.
 */
export async function cameraAvailable(
  devices:
    Pick<MediaDevices, "enumerateDevices"> | undefined = navigator.mediaDevices,
): Promise<boolean> {
  if (typeof devices?.enumerateDevices !== "function") return true;
  try {
    const found = await devices.enumerateDevices();
    return found.some((device) => device.kind === "videoinput");
  } catch {
    return true;
  }
}
