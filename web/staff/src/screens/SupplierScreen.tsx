import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { ApiError } from "@/api";
import {
  getSupplier,
  getSupplierDeliveries,
  type SupplierDeliveries,
  type SupplierRow,
} from "@/api/suppliers";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { plainClick } from "@/lib/links";
import { navigate } from "@/router";
import { pageTitle, poLabel, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

const SUPPLIERS_PATH = "/suppliers";

type State =
  | { kind: "loading" }
  | { kind: "ready"; supplier: SupplierRow }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

const TABS = ["scorecard", "deliveries"] as const;
type Tab = (typeof TABS)[number];
const TAB_PARAM = "tab";

/** The tab the URL names (`?tab=deliveries`); Scorecard otherwise. */
function tabFromUrl(): Tab {
  const named = new URLSearchParams(window.location.search).get(TAB_PARAM);
  return named === "deliveries" ? "deliveries" : "scorecard";
}

/** Who failed: 401 and DB_OFFLINE are the shell's, so they show nothing here. */
function failureMessage(error: unknown): string | null {
  if (
    error instanceof ApiError &&
    (error.status === 401 || error.code === "DB_OFFLINE")
  ) {
    return null;
  }
  return error instanceof ApiError && error.status === 0
    ? strings.errors.network
    : strings.errors.generic;
}

/**
 * One supplier's page (Story 4.4, EXPERIENCE.md Supplier scorecard): its name, a way
 * back to the list, and two tabs. Scorecard shows a "coming" note until Story 5.5
 * fills it; Deliveries (Story 4.5) lists the promised, delivered and received dates.
 * The selected tab is in the URL, so a link or reload opens it.
 */
export function SupplierScreen({ supplierId }: { supplierId: string }) {
  const p = strings.suppliers.page;
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const supplier = state.kind === "ready" ? state.supplier : null;
  const title = supplier ? supplier.name : strings.surfaces.supplier_scorecard;
  const heading = usePageHeading(pageTitle(title));
  const [tab, setTab] = useState<Tab>(tabFromUrl);
  const baseId = useId();
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({
    scorecard: null,
    deliveries: null,
  });

  function select(next: Tab, focus = false) {
    setTab(next);
    // Replace, not push: switching tabs doesn't fill Back with tab changes.
    const path = window.location.pathname;
    navigate(next === "deliveries" ? `${path}?${TAB_PARAM}=${next}` : path, {
      replace: true,
    });
    if (focus) tabRefs.current[next]?.focus();
  }

  // The APG tabs pattern: arrows move and select, Home and End jump.
  function onTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const at = TABS.indexOf(tab);
    const target =
      event.key === "ArrowRight"
        ? TABS[(at + 1) % TABS.length]
        : event.key === "ArrowLeft"
          ? TABS[(at - 1 + TABS.length) % TABS.length]
          : event.key === "Home"
            ? TABS[0]
            : event.key === "End"
              ? TABS[TABS.length - 1]
              : undefined;
    if (target === undefined) return;
    event.preventDefault();
    select(target, true);
  }

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
        const message = failureMessage(error);
        if (message !== null) setState({ kind: "error", message });
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
          <div
            role="tablist"
            aria-label={p.tabsLabel}
            className="flex gap-2 border-b"
          >
            {TABS.map((name) => {
              const selected = name === tab;
              return (
                <button
                  key={name}
                  ref={(element) => {
                    tabRefs.current[name] = element;
                  }}
                  type="button"
                  role="tab"
                  id={`${baseId}-tab-${name}`}
                  aria-selected={selected}
                  // Only the selected tab's panel is rendered.
                  aria-controls={
                    selected ? `${baseId}-panel-${name}` : undefined
                  }
                  tabIndex={selected ? 0 : -1}
                  onClick={() => select(name)}
                  onKeyDown={onTabKey}
                  className={`min-h-tap-min border-b-2 px-3 text-sm font-medium ${
                    selected
                      ? "border-primary"
                      : "border-transparent text-muted-foreground"
                  }`}
                >
                  {p.tabs[name]}
                </button>
              );
            })}
          </div>
          <div
            role="tabpanel"
            id={`${baseId}-panel-${tab}`}
            aria-labelledby={`${baseId}-tab-${tab}`}
            tabIndex={0}
            className={tab === "scorecard" ? "max-w-prose" : undefined}
          >
            {tab === "scorecard" ? (
              <p className="text-muted-foreground">{p.scorecardComing}</p>
            ) : (
              <DeliveriesPanel supplierId={supplier.supplierId} />
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

type DeliveriesState =
  | { kind: "loading" }
  | { kind: "ready"; deliveries: SupplierDeliveries }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

/** The Deliveries tab: dates and gaps exactly as the server worked them out. */
function DeliveriesPanel({ supplierId }: { supplierId: string }) {
  const d = strings.suppliers.deliveries;
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    attempt: number;
    state: DeliveriesState;
  } | null>(null);
  const state: DeliveriesState =
    result !== null && result.attempt === attempt
      ? result.state
      : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    getSupplierDeliveries(supplierId, controller.signal).then(
      (deliveries) =>
        setResult({ attempt, state: { kind: "ready", deliveries } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        // The supplier was removed after the page loaded: no retry can find it.
        if (error instanceof ApiError && error.status === 404) {
          setResult({ attempt, state: { kind: "not-found" } });
          return;
        }
        const message = failureMessage(error);
        if (message !== null) {
          setResult({ attempt, state: { kind: "error", message } });
        }
      },
    );
    return () => controller.abort();
  }, [supplierId, attempt]);

  if (state.kind === "loading") {
    return (
      <div aria-hidden="true" className="flex flex-col gap-3 pt-2">
        {[0, 1, 2].map((n) => (
          <Skeleton key={n} className="h-10 w-full" />
        ))}
      </div>
    );
  }
  if (state.kind === "not-found") {
    return <p className="pt-2">{strings.suppliers.page.notFound}</p>;
  }
  if (state.kind === "error") {
    return (
      <div className="flex max-w-prose flex-col gap-4 pt-2">
        <p role="alert">{state.message}</p>
        <div>
          <Button type="button" onClick={() => setAttempt((n) => n + 1)}>
            {strings.errors.tryAgain}
          </Button>
        </div>
      </div>
    );
  }
  const { items, truncated } = state.deliveries;
  if (items.length === 0) return <p className="pt-2">{d.none}</p>;

  const date = (value: string | null) => value ?? d.missing;
  const late = (days: number | null) =>
    days === null ? d.missing : d.lateness(days);
  const c = d.columns;
  return (
    <div className="flex flex-col gap-2 pt-2">
      {truncated ? (
        <p className="text-muted-foreground">{d.truncated(items.length)}</p>
      ) : null}
      <Table aria-label={d.tableLabel}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{c.po}</TableHead>
            <TableHead scope="col">{c.delivery}</TableHead>
            <TableHead scope="col">{c.promised}</TableHead>
            <TableHead scope="col">{c.delivered}</TableHead>
            <TableHead scope="col">{c.received}</TableHead>
            <TableHead scope="col">{c.late}</TableHead>
            <TableHead scope="col">{c.toReceive}</TableHead>
            <TableHead scope="col">{c.overall}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow
              key={`${item.poNumber}-${item.deliveryNo}`}
              data-testid="delivery-row"
            >
              <TableCell className="font-medium">
                {poLabel(item.poNumber)}
              </TableCell>
              <TableCell className="numeric">
                {d.deliveryNo(item.deliveryNo)}
              </TableCell>
              <TableCell className="numeric">
                {date(item.promisedDate)}
              </TableCell>
              <TableCell className="numeric">
                {date(item.deliveredDate)}
              </TableCell>
              <TableCell className="numeric">
                {date(item.receivedDate)}
              </TableCell>
              <TableCell>{late(item.daysLate)}</TableCell>
              <TableCell>
                {item.daysToReceive === null
                  ? d.missing
                  : d.days(item.daysToReceive)}
              </TableCell>
              <TableCell>{late(item.daysOverall)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
