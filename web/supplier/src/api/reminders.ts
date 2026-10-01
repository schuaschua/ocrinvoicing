import { strings } from "@/strings";

import { ApiError, apiRequest } from "./client";

/**
 * `GET /api/reminders` (Story 4.3): the PO numbers the weekly job reminds this link's
 * supplier of, sorted. The server decides the supplier from the upload token alone.
 * Rejects on any failure or a broken answer; the caller shows nothing then.
 */
export async function getReminders(signal?: AbortSignal): Promise<string[]> {
  const body = await apiRequest<{ po_numbers?: unknown } | null>(
    "/api/reminders",
    { signal },
  );
  const poNumbers = body?.po_numbers;
  if (
    !Array.isArray(poNumbers) ||
    !poNumbers.every((po) => typeof po === "string" && po !== "")
  ) {
    throw new ApiError(strings.errors.generic, 200, null, null);
  }
  return poNumbers as string[];
}
