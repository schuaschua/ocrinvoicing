import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { SESSION_EXPIRED, onApiEvent } from "@/api";
import {
  approveItem,
  rejectItem,
  rerunItem,
  type AdminAction,
  type ApproveChecks,
} from "@/api/item";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { useShortcuts } from "@/shell/shortcuts";
import { strings } from "@/strings";

import { actionFailed, openNext } from "./actionOutcome";

/** UX-DR12: Reject's and Approve's reasons, the only free text (the server checks
 * them too). */
export const MAX_REASON = 500;

type Dialog = "approve" | "reextract" | "retry_intake" | "reject";
type ReasonDialog = "approve" | "reject";

const NO_CHECKS: ApproveChecks = {
  calledNumberOnFile: false,
  supplierConfirmed: false,
};

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
  /** Story 3.3: Approve's summary (WCAG 3.3.4): the supplier and amount as shown. */
  summary?: { supplier: string; amount: string };
  /** `DUPLICATE` is the only open reason: Approve reads "Not a duplicate". */
  duplicate?: boolean;
  /** `BANK_CHANGED` is open: the call-back checks, which Approve needs both of. */
  checks?: ApproveChecks | null;
}

/**
 * The admin action bar (Stories 2.10 and 3.3, EXPERIENCE.md Admin actions): Correct,
 * Approve, Re-extract or Retry intake, and Reject, as the open reasons allow.
 * Re-extract and Retry intake ask first; Approve and Reject need a reason, and Approve
 * shows a summary first (WCAG 3.3.4). With the bank details changed, Approve stays
 * disabled until both call-back checks are ticked. After an action the next queued
 * item opens.
 */
export function ItemActions({
  invoiceId,
  routingId,
  allowed,
  onCorrect,
  focusCorrect = false,
  summary,
  duplicate = false,
  checks = null,
}: ItemActionsProps) {
  const a = strings.item.actions;
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  // Each reason dialog keeps its own text, so one never carries into the other.
  const [reasons, setReasons] = useState<Record<ReasonDialog, string>>({
    approve: "",
    reject: "",
  });
  const tickId = useId();
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

  const canApprove = allowed.includes("approve");
  // AD-11: both call-back checks first (the server refuses without them too).
  const approveBlocked =
    checks !== null && !(checks.calledNumberOnFile && checks.supplierConfirmed);

  // Story 2.11: the buttons' own handlers, only for the buttons shown and enabled.
  useShortcuts({
    c: allowed.includes("correct") ? onCorrect : undefined,
    a: canApprove && !approveBlocked ? () => open("approve") : undefined,
    r: allowed.includes("reject") ? () => open("reject") : undefined,
  });

  async function run(action: Dialog) {
    const reason =
      action === "approve" || action === "reject" ? reasons[action].trim() : "";
    if (action === "reject" && !reason) {
      setProblem(a.rejectDialog.required);
      return;
    }
    if (action === "approve" && !reason) {
      setProblem(a.approveDialog.required);
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      if (action === "reject") {
        await rejectItem(invoiceId, routingId, reason);
      } else if (action === "approve") {
        await approveItem(invoiceId, routingId, reason, checks ?? NO_CHECKS);
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
        : action === "approve"
          ? a.approved
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
        : dialog === "approve"
          ? a.approveDialog
          : a.rejectDialog;
  const reasonDialog: ReasonDialog | null =
    dialog === "approve" || dialog === "reject" ? dialog : null;
  return (
    <section aria-label={a.label} className="flex flex-wrap gap-2">
      {allowed.includes("correct") ? (
        <Button ref={correctButton} type="button" onClick={onCorrect}>
          {a.correct}
        </Button>
      ) : null}
      {canApprove ? (
        <span className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={approveBlocked}
            aria-describedby={approveBlocked ? tickId : undefined}
            onClick={() => open("approve")}
          >
            {duplicate ? a.notDuplicate : a.approve}
          </Button>
          {approveBlocked ? (
            <span id={tickId} className="text-sm">
              {a.tickBoth}
            </span>
          ) : null}
        </span>
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
          {dialog === "approve" && summary !== undefined ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-sm">{a.approveDialog.supplier}</dt>
              <dd className="font-medium">{summary.supplier}</dd>
              <dt className="text-sm">{a.approveDialog.amount}</dt>
              <dd className="numeric font-medium">{summary.amount}</dd>
            </dl>
          ) : null}
          {reasonDialog !== null ? (
            <div className="flex flex-col gap-1">
              <label htmlFor={reasonId} className="text-sm font-medium">
                {reasonDialog === "approve"
                  ? a.approveDialog.reason
                  : a.rejectDialog.reason}
              </label>
              <textarea
                id={reasonId}
                value={reasons[reasonDialog]}
                maxLength={MAX_REASON}
                rows={3}
                required
                aria-describedby={problem ? `${hintId} ${problemId}` : hintId}
                aria-invalid={problem !== null}
                className="min-h-tap-min w-full rounded-md border bg-background px-3 py-2 text-sm"
                onChange={(event) =>
                  setReasons((current) => ({
                    ...current,
                    [reasonDialog]: event.target.value,
                  }))
                }
              />
              <p id={hintId} className="text-sm">
                {a.rejectDialog.hint(MAX_REASON - reasons[reasonDialog].length)}
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
