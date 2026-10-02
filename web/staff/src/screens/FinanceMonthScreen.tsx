import { useEffect, useId, useState, type MouseEvent } from "react";

import { ApiError } from "@/api";
import { getFinanceMonth, type FinanceMonth } from "@/api/financeMonth";
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
import { monthText, priceText, wholePercentText } from "@/lib/format";
import { plainClick } from "@/lib/links";
import { navigate } from "@/router";
import { pageTitle, strings } from "@/strings";

import { supplierPath } from "./SuppliersScreen";
import { usePageHeading } from "./usePageHeading";

const MONTH_PARAM = "month";

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: FinanceMonth }
  | { kind: "error"; message: string };

/** The load error to show, or null when the shell already shows it (401, offline). */
function errorMessage(error: unknown): string | null {
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

/** Sets or removes `month` in the URL, keeping any other parameter. */
function setMonthParam(month: string | null) {
  const params = new URLSearchParams(window.location.search);
  if (month === null) params.delete(MONTH_PARAM);
  else params.set(MONTH_PARAM, month);
  const query = params.toString();
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${query === "" ? "" : `?${query}`}`,
  );
}

/**
 * A 4-decimal share as a whole percentage ("67%"), except that one below the target
 * never reads as the target: it is cut, not rounded, to one decimal ("89.9%").
 */
function shareText(share: string, target: string): string {
  const whole = wholePercentText(share);
  if (meets(share, target) || whole !== wholePercentText(target)) return whole;
  // Ten-thousandths as an integer, so the cut is exact.
  const tenths = Math.floor(Math.round(Number(share) * 10000) / 10);
  return `${(tenths / 10).toFixed(1)}%`;
}

/** The server's two 4-decimal strings compared, for wording only (no figure made). */
function meets(share: string, target: string): boolean {
  return Number(share) >= Number(target);
}

/** One month's header, chart and supplier table. */
function Month({ data }: { data: FinanceMonth }) {
  const s = strings.financeMonth;
  const ids = { suppliers: useId() };
  const { share, target, postedCount, straightThroughCount } =
    data.straightThrough;
  const targetText = wholePercentText(target);
  const met = share !== null && meets(share, target);
  const nameOf = (supplierId: string, name: string | null) =>
    name ?? `${s.unknownSupplier} ${supplierId.slice(-4)}`;

  function open(event: MouseEvent, supplierId: string) {
    if (!plainClick(event)) return;
    event.preventDefault();
    navigate(supplierPath(supplierId));
  }

  const series =
    data.history.length === 0
      ? []
      : [
          {
            label: s.shareSeries,
            points: data.history.map((item) => ({
              x: item.month,
              y: Number(item.share),
            })),
          },
          {
            label: s.targetSeries,
            points: data.history.map((item) => ({
              x: item.month,
              y: Number(target),
            })),
          },
        ];

  return (
    <>
      <section className="flex flex-col gap-1" data-testid="straight-through">
        {share === null ? (
          <p className="text-lg font-semibold">{s.noShare}</p>
        ) : (
          <>
            <p className="text-lg font-semibold">
              {s.header(shareText(share, target), targetText)}{" "}
              <span>{met ? s.met : s.notMet}</span>
            </p>
            <p className="text-sm text-muted-foreground">
              {s.posted(postedCount, straightThroughCount)}
            </p>
          </>
        )}
      </section>

      {series.length > 0 ? (
        <Chart
          title={s.chartTitle}
          summary={
            share === null
              ? s.noMonthShare(monthText(data.month), targetText)
              : s.summary(
                  monthText(data.month),
                  shareText(share, target),
                  targetText,
                  met,
                )
          }
          series={series}
          format={(value) => shareText(value.toFixed(4), target)}
          xLabel={s.monthColumn}
          yLabel={s.share}
        />
      ) : null}

      <section aria-labelledby={ids.suppliers} className="flex flex-col gap-2">
        <h2 id={ids.suppliers} className="text-lg font-semibold">
          {s.suppliersHeading}
        </h2>
        {data.suppliers.length === 0 ? (
          <p>{s.empty}</p>
        ) : (
          <Table scrollLabel={s.suppliersLabel}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{s.columns.supplier}</TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.spend}
                </TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.priceRises}
                </TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.flagged}
                </TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.duplicates}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.suppliers.map((row) => (
                <TableRow key={row.supplierId} data-testid="finance-row">
                  <TableCell className="font-medium">
                    <a
                      href={supplierPath(row.supplierId)}
                      className="inline-flex min-h-tap-min items-center underline underline-offset-4"
                      onClick={(event) => open(event, row.supplierId)}
                    >
                      {nameOf(row.supplierId, row.supplierName)}
                    </a>
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {priceText(row.spend)}
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {row.priceRises}
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {row.flaggedCount}
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {row.duplicateCount}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <p className="max-w-prose text-sm text-muted-foreground">{s.note}</p>
      </section>
    </>
  );
}

/**
 * Finance month (Story 5.6, CAP-18, EXPERIENCE.md Flow 7): finance's landing page. For
 * a month, each supplier's spend, price-creep alerts, flagged and duplicate invoices,
 * and the share posted without an admin against the 90% target, with its trend. The
 * server decides every figure (AD-13); this page only shows it.
 */
export function FinanceMonthScreen() {
  const title = strings.surfaces.finance_month;
  const heading = usePageHeading(pageTitle(title));
  const s = strings.financeMonth;
  const selectId = useId();
  const [attempt, setAttempt] = useState(0);
  // The month in the URL, so a link or a reload keeps it.
  const [chosen, setChosen] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get(MONTH_PARAM),
  );
  const key = `${attempt}:${chosen ?? ""}`;
  const [loaded, setLoaded] = useState<{ key: string; state: State } | null>(
    null,
  );
  const state: State =
    loaded !== null && loaded.key === key ? loaded.state : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    getFinanceMonth(chosen, controller.signal).then(
      (data) => setLoaded({ key, state: { kind: "ready", data } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (
          chosen !== null &&
          error instanceof ApiError &&
          error.code === "VALIDATION_FAILED"
        ) {
          // A malformed month in the URL: show the latest month instead.
          setMonthParam(null);
          setChosen(null);
          return;
        }
        const message = errorMessage(error);
        if (message !== null) {
          setLoaded({ key, state: { kind: "error", message } });
        }
      },
    );
    return () => controller.abort();
  }, [chosen, key]);

  function choose(month: string) {
    setChosen(month);
    setMonthParam(month);
  }

  const data = state.kind === "ready" ? state.data : null;
  // The picker stays while another month loads, so focus stays on it.
  const shown =
    loaded !== null && loaded.state.kind === "ready" ? loaded.state.data : null;
  const value = chosen ?? shown?.month ?? "";
  const options =
    shown === null
      ? []
      : [...new Set([...shown.months, shown.month, value])]
          .filter((month) => month !== "")
          .sort()
          .reverse();

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>

      {data !== null && data.months.length === 0 ? <p>{s.empty}</p> : null}

      {shown !== null && shown.months.length > 0 ? (
        <div className="flex max-w-sm min-w-0 flex-col gap-1">
          <label htmlFor={selectId} className="text-sm font-medium">
            {s.month}
          </label>
          <select
            id={selectId}
            className="min-h-tap-min w-full rounded-md border bg-background px-3 text-sm"
            value={value}
            onChange={(event) => choose(event.target.value)}
          >
            {options.map((month) => (
              <option key={month} value={month}>
                {monthText(month)}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {data !== null && data.months.length > 0 ? <Month data={data} /> : null}

      {state.kind === "loading" ? (
        <div aria-hidden="true" className="flex flex-col gap-3">
          {[0, 1, 2].map((n) => (
            <Skeleton key={n} className="h-10 w-full" />
          ))}
        </div>
      ) : null}

      {state.kind === "error" ? (
        <div className="flex max-w-prose flex-col gap-4">
          <p role="alert">{state.message}</p>
          <div>
            <Button type="button" onClick={() => setAttempt((n) => n + 1)}>
              {strings.errors.tryAgain}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
