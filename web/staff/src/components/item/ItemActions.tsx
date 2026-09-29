import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { SESSION_EXPIRED, onApiEvent } from "@/api";
import { rejectItem, rerunItem, type AdminAction } from "@/api/item";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { strings } from "@/strings";

import { actionFailed, openNext } from "./actionOutcome";

/** UX-DR12: Reject's reason, the only free text (the server checks it too). */
export const MAX_REASON = 500;

type Dialog = "reextract" | "retry_intake" | "reject";

interface ItemActionsProps {
  invoiceId: string;
  /** The routing the page shows; sent back so a stale page is refused. */
  routingId: string | null;
  /** The server's guard (UX-DR12): only these show. */
  allowed: AdminAction[];
  /** Opens Correct mode. */
  onCorrect: () => void;
  /** Back from Correct mode: focus returns to the Correct button. */
  focusCorrect?: boolean;
}

/**
 * The admin action bar (Story 2.10, EXPERIENCE.md Admin actions): Correct, Re-extract
 * or Retry intake, and Reject, as the open reasons allow. Re-extract and Retry intake
 * ask first; Reject needs a reason (WCAG 3.3.4). After an action the next queued item
 * opens.
 */
export function ItemActions({
  invoiceId,
  routingId,
  allowed,
  onCorrect,
  focusCorrect = false,
}: ItemActionsProps) {
  const a = strings.item.actions;
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const headingId = useId();
  const reasonId = useId();
  const hintId = useId();
  const problemId = useId();
  const correctButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (focusCorrect) correctButton.current?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- on mount only: the bar returns when Correct mode closes
  }, []);

  useEffect(
    // Dialogs stack one level deep at most: the session-ended dialog wins.
    () => onApiEvent(SESSION_EXPIRED, () => setDialog(null)),
    [],
  );

  function open(next: Dialog) {
    setProblem(null);
    setDialog(next);
  }

  async function run(action: Dialog) {
    if (action === "reject" && !reason.trim()) {
      setProblem(a.rejectDialog.required);
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      if (action === "reject") {
        await rejectItem(invoiceId, routingId, reason.trim());
      } else {
        await rerunItem(invoiceId, routingId, action);
      }
    } catch (error) {
      setBusy(false);
      const message = actionFailed(error);
      if (message === null) setDialog(null);
      setProblem(message);
      return;
    }
    await openNext(
      invoiceId,
      action === "reject"
        ? a.rejected
        : action === "reextract"
          ? a.sentForExtraction
          : a.sentForIntake,
    );
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (dialog !== null && !busy) void run(dialog);
  }

  if (allowed.length === 0) {
    return (
      <section aria-label={a.label}>
        <p>{a.none}</p>
      </section>
    );
  }

  const copy =
    dialog === "reextract"
      ? a.reextractDialog
      : dialog === "retry_intake"
        ? a.retryIntakeDialog
        : a.rejectDialog;
  return (
    <section aria-label={a.label} className="flex flex-wrap gap-2">
      {allowed.includes("correct") ? (
        <Button ref={correctButton} type="button" onClick={onCorrect}>
          {a.correct}
        </Button>
      ) : null}
      {allowed.includes("reextract") ? (
        <Button
          type="button"
          variant="outline"
          onClick={() => open("reextract")}
        >
          {a.reextract}
        </Button>
      ) : null}
      {allowed.includes("retry_intake") ? (
        <Button
          type="button"
          variant="outline"
          onClick={() => open("retry_intake")}
        >
          {a.retryIntake}
        </Button>
      ) : null}
      {allowed.includes("reject") ? (
        <Button
          type="button"
          variant="destructive"
          onClick={() => open("reject")}
        >
          {a.reject}
        </Button>
      ) : null}

      <Modal
        open={dialog !== null}
        onClose={() => {
          if (!busy) setDialog(null);
        }}
        labelledBy={headingId}
        className="m-auto w-[min(32rem,calc(100vw-2rem))] rounded-lg border p-6"
      >
        <form className="flex flex-col gap-4" onSubmit={onSubmit} noValidate>
          <h2 id={headingId} className="text-lg font-semibold">
            {copy.heading}
          </h2>
          <p>{copy.body}</p>
          {dialog === "reject" ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={reasonId} className="text-sm font-medium">
                {a.rejectDialog.reason}
              </label>
              <textarea
                id={reasonId}
                value={reason}
                maxLength={MAX_REASON}
                rows={3}
                required
                aria-describedby={problem ? `${hintId} ${problemId}` : hintId}
                aria-invalid={problem !== null}
                className="min-h-tap-min w-full rounded-md border bg-background px-3 py-2 text-sm"
                onChange={(event) => setReason(event.target.value)}
              />
              <p id={hintId} className="text-sm">
                {a.rejectDialog.hint(MAX_REASON - reason.length)}
              </p>
            </div>
          ) : null}
          {problem !== null ? (
            <p id={problemId} role="alert" className="text-destructive">
              {problem}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              type="submit"
              variant={dialog === "reject" ? "destructive" : "default"}
              disabled={busy}
            >
              {busy ? a.working : copy.confirm}
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => setDialog(null)}
            >
              {a.cancel}
            </Button>
          </div>
        </form>
      </Modal>
    </section>
  );
}
