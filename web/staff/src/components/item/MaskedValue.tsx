import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/api";
import { revealBankValue, type RevealWhich } from "@/api/item";
import { Button } from "@/components/ui/button";
import { strings } from "@/strings";

/** UX-DR14: a revealed value shows for at most 30 s, with a warning at 20 s. */
export const REVEAL_MS = 30_000;
export const WARN_MS = 20_000;

/** `•••• 4821`, announced as "account ending 4821" (DESIGN.md Masked value). A
 * value of 4 characters or fewer comes with no digits ("") and shows `••••` only. */
export function Masked({ digits }: { digits: string }) {
  const b = strings.item.bank;
  return (
    <span className="numeric">
      <span aria-hidden="true">{digits ? `•••• ${digits}` : "••••"}</span>
      <span className="sr-only">{digits ? b.ending(digits) : b.noDigits}</span>
    </span>
  );
}

type State =
  | { kind: "masked" }
  | { kind: "loading" }
  | { kind: "shown"; value: string; since: number }
  | { kind: "failed" };

interface MaskedValueProps {
  invoiceId: string;
  fieldId: string;
  which: RevealWhich;
  digits: string;
  announce: (message: string) => void;
}

/**
 * One masked bank value with **Show** (EXPERIENCE.md Masked value, UX-DR14). Show asks
 * the server, which audits it; the value shows until Hide, until the admin leaves the
 * item (it lives in this component's state only, never in browser storage), or for 30 s.
 * At 20 s an announced warning offers Keep showing, which reveals again (audited again)
 * and restarts the 30 s. Hiding is announced.
 */
export function MaskedValue({
  invoiceId,
  fieldId,
  which,
  digits,
  announce,
}: MaskedValueProps) {
  const [state, setState] = useState<State>({ kind: "masked" });
  const [warning, setWarning] = useState(false);
  // Each hide starts a new generation: an answer to a reveal sent before it (a Keep
  // showing still in flight at the 30 s hide) is dropped, never shown again.
  const generation = useRef(0);
  const b = strings.item.bank;

  const shownSince = state.kind === "shown" ? state.since : null;
  useEffect(() => {
    if (shownSince === null) return;
    const warn = window.setTimeout(() => {
      setWarning(true);
      announce(b.warning);
    }, WARN_MS);
    const hide = window.setTimeout(() => {
      generation.current += 1;
      setWarning(false);
      setState({ kind: "masked" });
      announce(b.hidden);
    }, REVEAL_MS);
    return () => {
      window.clearTimeout(warn);
      window.clearTimeout(hide);
    };
  }, [shownSince, announce, b]);

  async function reveal() {
    const sent = generation.current;
    setState((current) =>
      current.kind === "shown" ? current : { kind: "loading" },
    );
    try {
      const value = await revealBankValue(invoiceId, fieldId, which);
      if (sent !== generation.current) return;
      setWarning(false);
      // A new reveal (Keep showing included) restarts the 30 s.
      setState((current) => ({
        kind: "shown",
        value,
        since: current.kind === "shown" ? current.since + 1 : 1,
      }));
    } catch (error) {
      if (sent !== generation.current) return;
      setWarning(false);
      // 401 and DB_OFFLINE are the shell's (sign-in dialog, offline notice).
      if (
        error instanceof ApiError &&
        (error.status === 401 || error.code === "DB_OFFLINE")
      ) {
        setState({ kind: "masked" });
        return;
      }
      setState({ kind: "failed" });
      announce(b.failed);
    }
  }

  function hide() {
    generation.current += 1;
    setWarning(false);
    setState({ kind: "masked" });
    announce(b.hidden);
  }

  if (state.kind === "shown") {
    return (
      <span className="flex flex-wrap items-center gap-2">
        <span className="numeric break-all">{state.value}</span>
        <Button type="button" variant="outline" onClick={hide}>
          {b.hide}
        </Button>
        {warning ? (
          <>
            <span className="text-sm">{b.warning}</span>
            <Button type="button" variant="outline" onClick={reveal}>
              {b.keepShowing}
            </Button>
          </>
        ) : null}
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-2">
      <Masked digits={digits} />
      <Button
        type="button"
        variant="outline"
        aria-label={b.showLabel(digits)}
        disabled={state.kind === "loading"}
        onClick={reveal}
      >
        {b.show}
      </Button>
      {state.kind === "failed" ? (
        <span className="text-sm">{b.failed}</span>
      ) : null}
    </span>
  );
}
