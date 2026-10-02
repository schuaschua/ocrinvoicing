import { useEffect, useId, useState } from "react";

import { ApiError } from "@/api";
import { getSupplier, type SupplierRow } from "@/api/suppliers";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { plainClick } from "@/lib/links";
import { navigate } from "@/router";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

const SUPPLIERS_PATH = "/suppliers";

type State =
  | { kind: "loading" }
  | { kind: "ready"; supplier: SupplierRow }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

/**
 * One supplier's page (Story 4.4, EXPERIENCE.md Supplier scorecard): its name, a way
 * back to the list, and a tab list. Only Scorecard for now, with a "coming" note until
 * Story 5.5 fills it; Story 4.5 adds a Deliveries tab beside it.
 */
export function SupplierScreen({ supplierId }: { supplierId: string }) {
  const p = strings.suppliers.page;
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const supplier = state.kind === "ready" ? state.supplier : null;
  const title = supplier ? supplier.name : strings.surfaces.supplier_scorecard;
  const heading = usePageHeading(pageTitle(title));
  const tabId = useId();
  const panelId = useId();

  useEffect(() => {
    const controller = new AbortController();
    getSupplier(supplierId, controller.signal).then(
      (found) => {
        if (!controller.signal.aborted) {
          setState({ kind: "ready", supplier: found });
        }
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ kind: "not-found" });
          return;
        }
        // 401 and DB_OFFLINE are the shell's.
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.code === "DB_OFFLINE")
        ) {
          return;
        }
        const network = error instanceof ApiError && error.status === 0;
        setState({
          kind: "error",
          message: network ? strings.errors.network : strings.errors.generic,
        });
      },
    );
    return () => controller.abort();
  }, [supplierId, attempt]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button asChild variant="ghost" className="px-2">
          <a
            href={SUPPLIERS_PATH}
            onClick={(event) => {
              if (!plainClick(event)) return;
              event.preventDefault();
              navigate(SUPPLIERS_PATH);
            }}
          >
            {p.back}
          </a>
        </Button>
      </div>
      <h1
        ref={heading}
        tabIndex={-1}
        className="min-w-0 break-words text-xl font-semibold"
      >
        {title}
      </h1>

      {state.kind === "loading" ? (
        <div aria-hidden="true" className="flex flex-col gap-3">
          {[0, 1].map((n) => (
            <Skeleton key={n} className="h-10 w-full" />
          ))}
        </div>
      ) : null}

      {state.kind === "not-found" ? <p>{p.notFound}</p> : null}

      {state.kind === "error" ? (
        <div className="flex max-w-prose flex-col gap-4">
          <p role="alert">{state.message}</p>
          <div>
            <Button
              type="button"
              onClick={() => {
                setState({ kind: "loading" });
                setAttempt((n) => n + 1);
              }}
            >
              {strings.errors.tryAgain}
            </Button>
          </div>
        </div>
      ) : null}

      {supplier !== null ? (
        <>
          {/* One tab today; Deliveries (Story 4.5) joins it, with arrow-key moves. */}
          <div
            role="tablist"
            aria-label={p.tabsLabel}
            className="flex gap-2 border-b"
          >
            <button
              type="button"
              role="tab"
              id={tabId}
              aria-selected="true"
              aria-controls={panelId}
              className="min-h-tap-min border-b-2 border-primary px-3 text-sm font-medium"
            >
              {p.tabs.scorecard}
            </button>
          </div>
          <div
            role="tabpanel"
            id={panelId}
            aria-labelledby={tabId}
            className="max-w-prose"
          >
            <p className="text-muted-foreground">{p.scorecardComing}</p>
          </div>
        </>
      ) : null}
    </div>
  );
}
