// Story 2.10: what happens after an admin action (EXPERIENCE.md Admin actions and State
// Patterns "Item already resolved").

import { ApiError } from "@/api";
import { getQueue } from "@/api/queue";
import { navigate } from "@/router";
import { showNotice } from "@/shell/notices";
import { strings } from "@/strings";

export const QUEUE_PATH = "/queue";

function itemPath(invoiceId: string): string {
  return `${QUEUE_PATH}/${encodeURIComponent(invoiceId)}`;
}

/**
 * The action is done: open the next queued item (the first on the queue's first page
 * other than this one) with `toast`, or the queue when none is left. Its screen moves
 * focus to its heading.
 */
export async function openNext(
  invoiceId: string,
  toast: string,
): Promise<void> {
  let path = QUEUE_PATH;
  try {
    const page = await getQueue({ page: 1, reason: null, supplierId: null });
    const next = page.items.find((item) => item.invoiceId !== invoiceId);
    if (next !== undefined) path = itemPath(next.invoiceId);
  } catch {
    // The action itself succeeded; without the queue, go to the queue page.
  }
  showNotice(toast, "status", path);
  navigate(path);
}

/**
 * A failed action. 409 (another admin acted first, or the reasons changed): the alert,
 * and back to the queue; returns null. 401 and DB_OFFLINE are the shell's (null too).
 * Otherwise the message to show on the item: the server's plain 400 message, or a
 * generic one.
 */
export function actionFailed(error: unknown): string | null {
  if (error instanceof ApiError && error.status === 409) {
    const message =
      error.code === "ACTION_NOT_ALLOWED"
        ? strings.item.actions.notAllowed
        : strings.item.actions.alreadyHandled;
    showNotice(message, "alert", QUEUE_PATH);
    navigate(QUEUE_PATH);
    return null;
  }
  if (
    error instanceof ApiError &&
    (error.status === 401 || error.code === "DB_OFFLINE")
  ) {
    return null;
  }
  if (error instanceof ApiError && error.status === 400) return error.message;
  if (error instanceof ApiError && error.status === 0) {
    return strings.errors.network;
  }
  return strings.errors.generic;
}
