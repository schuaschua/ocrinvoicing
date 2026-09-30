import type { ItemReason } from "@/api/item";
import { strings } from "@/strings";

/**
 * Story 3.3, EXPERIENCE.md "Couldn't post to accounts": what the accounts system
 * answered on the last try. Story 3.2 keeps only its HTTP status (none for a timeout
 * or an unreachable host) and a code, never its text, so that is what shows; Approve
 * tries posting again.
 */
export function AccountsErrorPanel({
  reason,
  approvable,
}: {
  reason: ItemReason;
  /** Approve is offered, so it can try posting again. */
  approvable: boolean;
}) {
  const e = strings.item.accountsError;
  const { status, code } = reason.detail;
  const answer =
    typeof code !== "string"
      ? e.unknown
      : typeof status === "number"
        ? e.answered(status, code)
        : e.noAnswer(code);
  return (
    <section
      aria-labelledby="accounts-error-heading"
      className="flex flex-col gap-2 rounded-md border border-destructive p-4"
    >
      <h2 id="accounts-error-heading" className="text-lg font-semibold">
        {e.heading}
      </h2>
      <p>{answer}</p>
      {approvable ? <p>{e.retry}</p> : null}
    </section>
  );
}
