import { type KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { ApiError } from "@/api";
import {
  getSupplier,
  getSupplierDeliveries,
  getSupplierScorecard,
  type MaterialTrend,
  type SupplierRow,
} from "@/api/suppliers";
import { Chart } from "@/components/Chart";
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
import { daysText, onTimeRateText, percentText, priceText } from "@/lib/format";
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
 * back to the list, and two tabs. Scorecard (Story 5.5) shows the on-time rate and a
 * price trend per material; Deliveries (Story 4.5) lists the promised, delivered and
 * received dates.
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
          >
            {tab === "scorecard" ? (
              <ScorecardPanel supplierId={supplier.supplierId} />
            ) : (
              <DeliveriesPanel supplierId={supplier.supplierId} />
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}

/** A tab's data, loaded per attempt so Try again shows the skeleton again. */
type PanelState<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

/** Loads a tab's data for the supplier; the second value is Try again, which shows
 * the skeleton again. A 404 means the supplier was removed after the page loaded,
 * so no retry can find it. */
function usePanelData<T>(
  supplierId: string,
  load: (supplierId: string, signal: AbortSignal) => Promise<T>,
): [PanelState<T>, () => void] {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    attempt: number;
    state: PanelState<T>;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    load(supplierId, controller.signal).then(
      (data) => setResult({ attempt, state: { kind: "ready", data } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
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
  }, [supplierId, attempt, load]);

  const state: PanelState<T> =
    result !== null && result.attempt === attempt
      ? result.state
      : { kind: "loading" };
  return [state, () => setAttempt((n) => n + 1)];
}

/** The panel's skeleton, not-found and error states; null once it has data. */
function PanelStatus<T>({
  state,
  retry,
}: {
  state: PanelState<T>;
  retry: () => void;
}) {
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
          <Button type="button" onClick={retry}>
            {strings.errors.tryAgain}
          </Button>
        </div>
      </div>
    );
  }
  return null;
}

/** A trend's one-sentence summary, from the server's change (never computed here). */
function trendSummary(material: MaterialTrend): string {
  const t = strings.suppliers.scorecard;
  const first = material.points[0];
  if (material.changePct === null || first === undefined) {
    return t.onePrice(priceText(material.latestUnitPrice));
  }
  const since = t.monthYear(first.invoiceDate);
  const pct = percentText(material.changePct.replace(/^-/, ""));
  if (Number(material.changePct) > 0) return t.up(material.name, pct, since);
  if (Number(material.changePct) < 0) return t.down(material.name, pct, since);
  return t.unchanged(material.name, since);
}

/** The Scorecard tab: on-time rate and each material's price trend, as the server
 * worked them out (coding-style.md rule 16). */
function ScorecardPanel({ supplierId }: { supplierId: string }) {
  const t = strings.suppliers.scorecard;
  const [state, retry] = usePanelData(supplierId, getSupplierScorecard);
  if (state.kind !== "ready")
    return <PanelStatus state={state} retry={retry} />;
  const { onTime, materials } = state.data;
  if (onTime === null && materials.length === 0) {
    return <p className="pt-2">{t.empty}</p>;
  }
  return (
    <div className="flex flex-col gap-6 pt-2">
      <section className="flex max-w-prose flex-col gap-1 rounded-md border p-4">
        <h2 className="text-lg font-semibold">{t.onTimeHeading}</h2>
        {onTime === null ? (
          <p>{t.noReceipts}</p>
        ) : (
          <>
            <p>
              {t.onTime(
                onTimeRateText(onTime.rate, onTime.onTime, onTime.receipts),
                onTime.receipts,
              )}
            </p>
            <p>{t.average(daysText(onTime.avgDaysLate))}</p>
          </>
        )}
      </section>
      {materials.length === 0 ? <p>{t.empty}</p> : null}
      {materials.map((material) => (
        <Chart
          key={material.materialId}
          title={material.name}
          summary={trendSummary(material)}
          series={[
            {
              label: material.name,
              points: material.points.map((point) => ({
                x: point.invoiceDate,
                y: Number(point.unitPrice),
              })),
            },
          ]}
          // Only redisplays the server's 2-decimal prices (coding-style.md rule 16).
          format={(value) => priceText(value.toFixed(2))}
          yLabel={t.price}
        />
      ))}
    </div>
  );
}

/** The Deliveries tab: dates and gaps exactly as the server worked them out. */
function DeliveriesPanel({ supplierId }: { supplierId: string }) {
  const d = strings.suppliers.deliveries;
  const [state, retry] = usePanelData(supplierId, getSupplierDeliveries);
  if (state.kind !== "ready")
    return <PanelStatus state={state} retry={retry} />;
  const { items, truncated } = state.data;
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
