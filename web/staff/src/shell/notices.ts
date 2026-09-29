// The shell's one-shot notices (Story 2.10): a Toast ("Sent for re-check") or an alert
// ("Already handled by another admin.") raised by a screen just before it navigates,
// shown by the shell on the page it lands on. In memory only, never in browser storage.

import { useSyncExternalStore } from "react";

export interface Notice {
  message: string;
  /** "status" for a Toast, "alert" for a problem (4.1.3). */
  kind: "status" | "alert";
  /** The path it belongs to: it shows only there, so the next navigation drops it. */
  path: string;
  id: number;
}

/** A Toast disappears after this long; an alert stays until the admin moves on. */
export const TOAST_MS = 6000;

let current: Notice | null = null;
let nextId = 1;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Show `message` on `path` (the page the caller is about to open). */
export function showNotice(
  message: string,
  kind: Notice["kind"],
  path: string,
): void {
  const notice = { message, kind, path, id: nextId++ };
  current = notice;
  emit();
  if (kind === "status") {
    window.setTimeout(() => {
      if (current?.id === notice.id) {
        current = null;
        emit();
      }
    }, TOAST_MS);
  }
}

/** The app moved to `path`: a notice for another page is dropped, so it never shows
 * again on a later visit to its page. */
export function leftFor(path: string): void {
  if (current !== null && current.path !== path) {
    current = null;
    emit();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The notice for `path`, if any. */
export function useNotice(path: string): Notice | null {
  const notice = useSyncExternalStore(subscribe, () => current);
  return notice !== null && notice.path === path ? notice : null;
}
