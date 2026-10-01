import { useEffect, useId, useState, type MouseEvent } from "react";

import { ApiError } from "@/api";
import {
  getMaterials,
  getPriceComparison,
  type Material,
  type PriceComparison,
} from "@/api/priceComparison";
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
import { percentText, priceText, rateText } from "@/lib/format";
import { navigate } from "@/router";
import { pageTitle, strings } from "@/strings";

import { invoicePath } from "./InvoicesScreen";
import { usePageHeading } from "./usePageHeading";

const MATERIAL_PARAM = "material_id";

type State<T> =
  | { kind: "loading" }
  | { kind: "ready"; data: T }
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

/** A plain left click; a modified one keeps the browser's own behaviour (new tab). */
function plainClick(event: MouseEvent): boolean {
  return !(
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}

function money(value: number): string {
  // Only redisplays the server's 2-decimal prices (coding-style.md rule 16).
  return priceText(value.toFixed(2));
}

/** One material's suppliers, chart and alerts. */
function Comparison({ data }: { data: PriceComparison }) {
  const s = strings.priceComparison;
  const nameOf = (supplierId: string, name: string | null) =>
    name ?? `${s.unknownSupplier} ${supplierId.slice(-4)}`;
  const ids = { suppliers: useId(), alerts: useId() };
  const cheapest = data.suppliers[0];
  const series = data.suppliers
    .map((supplier) => ({
      label: nameOf(supplier.supplierId, supplier.supplierName),
      points: data.history
        .filter((point) => point.supplierId === supplier.supplierId)
        .map((point) => ({ x: point.invoiceDate, y: Number(point.unitPrice) })),
    }))
    .filter((one) => one.points.length > 0);

  function open(event: MouseEvent, invoiceId: string) {
    if (!plainClick(event)) return;
    event.preventDefault();
    navigate(invoicePath(invoiceId));
  }

  return (
    <>
      {series.length === 0 || cheapest === undefined ? (
        <p>{s.noRecent}</p>
      ) : (
        <Chart
          title={s.chartTitle}
          summary={s.summary(
            data.name,
            priceText(cheapest.latestUnitPrice),
            nameOf(cheapest.supplierId, cheapest.supplierName),
          )}
          series={series}
          format={money}
          yLabel={s.price}
        />
      )}

      {data.suppliers.length > 0 ? (
        <section
          aria-labelledby={ids.suppliers}
          className="flex flex-col gap-2"
        >
          <h2 id={ids.suppliers} className="text-lg font-semibold">
            {s.suppliersHeading}
          </h2>
          <Table scrollLabel={s.suppliersLabel}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{s.columns.supplier}</TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.latestPrice}
                </TableHead>
                <TableHead scope="col">{s.columns.latestDate}</TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.onTime}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.suppliers.map((supplier) => (
                <TableRow key={supplier.supplierId} data-testid="supplier-row">
                  <TableCell className="font-medium">
                    {nameOf(supplier.supplierId, supplier.supplierName)}
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {priceText(supplier.latestUnitPrice)}
                  </TableCell>
                  <TableCell className="numeric">
                    {supplier.latestInvoiceDate}
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {supplier.onTimeRate === null
                      ? s.noRate
                      : rateText(supplier.onTimeRate)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      ) : null}

      <section aria-labelledby={ids.alerts} className="flex flex-col gap-2">
        <h2 id={ids.alerts} className="text-lg font-semibold">
          {s.alertsHeading}
        </h2>
        {data.alerts.length === 0 ? <p>{s.noAlerts}</p> : null}
        <ul className="flex flex-col gap-4">
          {data.alerts.map((alert) => {
            const supplier = nameOf(alert.supplierId, alert.supplierName);
            const linked = alert.evidence.some((row) => row.invoiceId !== null);
            return (
              <li
                key={alert.alertId}
                className="flex flex-col gap-2 rounded-md border p-3"
              >
                <p className="font-medium">
                  {s.alert(supplier, data.name, percentText(alert.pct))}
                </p>
                {/* A table with no link in it gets a focusable scroll region. */}
                <Table
                  aria-label={s.evidenceLabel(supplier)}
                  {...(linked
                    ? {}
                    : { scrollLabel: s.evidenceLabel(supplier) })}
                >
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">
                        {s.evidenceColumns.date}
                      </TableHead>
                      <TableHead scope="col" className="text-right">
                        {s.evidenceColumns.price}
                      </TableHead>
                      <TableHead scope="col">
                        {s.evidenceColumns.invoice}
                      </TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {alert.evidence.map((row, n) => (
                      <TableRow key={n} data-testid="evidence-row">
                        <TableCell className="numeric">
                          {row.invoiceDate}
                        </TableCell>
                        <TableCell className="numeric text-right">
                          {priceText(row.unitPrice)}
                        </TableCell>
                        <TableCell>
                          {row.invoiceId === null ? (
                            s.readOnly
                          ) : (
                            <a
                              href={invoicePath(row.invoiceId)}
                              className="inline-flex min-h-tap-min items-center font-medium underline underline-offset-4"
                              onClick={(event) =>
                                open(event, row.invoiceId ?? "")
                              }
                            >
                              {s.openInvoice}
                            </a>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}

/**
 * Price comparison (Story 5.3, CAP-14, EXPERIENCE.md): for a material, each supplier's
 * latest unit price with their on-time rate, the price history as a chart, and the
 * price-rise alerts with their evidence. The server decides every figure (AD-13);
 * this page only shows it.
 */
export function PriceComparisonScreen() {
  const title = strings.surfaces.price_comparison;
  const heading = usePageHeading(pageTitle(title));
  const s = strings.priceComparison;
  const selectId = useId();
  const [attempt, setAttempt] = useState(0);
  const [materials, setMaterials] = useState<{
    attempt: number;
    state: State<Material[]>;
  } | null>(null);
  // The material in the URL, so an alert email can link to it (EXPERIENCE.md).
  const [chosen, setChosen] = useState<string | null>(() =>
    new URLSearchParams(window.location.search).get(MATERIAL_PARAM),
  );
  const [comparison, setComparison] = useState<{
    key: string;
    state: State<PriceComparison>;
  } | null>(null);

  const listState: State<Material[]> =
    materials !== null && materials.attempt === attempt
      ? materials.state
      : { kind: "loading" };
  const list = listState.kind === "ready" ? listState.data : null;
  // An absent or unknown material falls back to the first one.
  const materialId =
    list?.find((item) => item.materialId === chosen)?.materialId ??
    list?.[0]?.materialId ??
    null;
  const key = materialId === null ? null : `${attempt}:${materialId}`;
  const comparisonState: State<PriceComparison> =
    comparison !== null && comparison.key === key
      ? comparison.state
      : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    getMaterials(controller.signal).then(
      (data) => {
        setMaterials({ attempt, state: { kind: "ready", data } });
        // A reloaded list without the chosen material: back to the first one.
        setChosen((held) =>
          data.some((item) => item.materialId === held) ? held : null,
        );
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = errorMessage(error);
        if (message !== null) {
          setMaterials({ attempt, state: { kind: "error", message } });
        }
      },
    );
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (materialId === null || key === null) return;
    const controller = new AbortController();
    getPriceComparison(materialId, controller.signal).then(
      (data) => setComparison({ key, state: { kind: "ready", data } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = errorMessage(error);
        if (message !== null) {
          setComparison({ key, state: { kind: "error", message } });
        }
      },
    );
    return () => controller.abort();
  }, [materialId, key]);

  function choose(value: string) {
    setChosen(value);
    const query = new URLSearchParams({ [MATERIAL_PARAM]: value });
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}?${query.toString()}`,
    );
  }

  const error =
    listState.kind === "error"
      ? listState.message
      : list !== null && list.length > 0 && comparisonState.kind === "error"
        ? comparisonState.message
        : null;
  const loading =
    listState.kind === "loading" ||
    (list !== null && list.length > 0 && comparisonState.kind === "loading");

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>

      {list !== null && list.length === 0 ? <p>{s.empty}</p> : null}

      {list !== null && list.length > 0 ? (
        <div className="flex max-w-sm min-w-0 flex-col gap-1">
          <label htmlFor={selectId} className="text-sm font-medium">
            {s.material}
          </label>
          <select
            id={selectId}
            className="min-h-tap-min w-full rounded-md border bg-background px-3 text-sm"
            value={materialId ?? ""}
            onChange={(event) => choose(event.target.value)}
          >
            {list.map((item) => (
              <option key={item.materialId} value={item.materialId}>
                {item.name}
              </option>
            ))}
          </select>
        </div>
      ) : null}

      {loading ? (
        <div aria-hidden="true" className="flex flex-col gap-3">
          {[0, 1, 2].map((n) => (
            <Skeleton key={n} className="h-10 w-full" />
          ))}
        </div>
      ) : null}

      {error !== null ? (
        <div className="flex max-w-prose flex-col gap-4">
          <p role="alert">{error}</p>
          <div>
            <Button type="button" onClick={() => setAttempt((n) => n + 1)}>
              {strings.errors.tryAgain}
            </Button>
          </div>
        </div>
      ) : null}

      {comparisonState.kind === "ready" ? (
        <Comparison data={comparisonState.data} />
      ) : null}
    </div>
  );
}
