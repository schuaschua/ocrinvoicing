import { useEffect, useId, useState, type MouseEvent } from "react";

import { ApiError } from "@/api";
import {
  getWatchlist,
  type Alternatives,
  type Watchlist,
  type WatchlistEntry,
  type WatchlistRule,
} from "@/api/watchlist";
import { Badge } from "@/components/ui/badge";
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
import { daysText, percentText, priceText, rateText } from "@/lib/format";
import { navigate } from "@/router";
import { pageTitle, strings } from "@/strings";

import { invoicePath } from "./InvoicesScreen";
import { usePageHeading } from "./usePageHeading";

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: Watchlist }
  | { kind: "error"; message: string };

const s = strings.watchlist;

function supplierName(supplierId: string, name: string | null): string {
  return name ?? `${s.unknownSupplier} ${supplierId.slice(-4)}`;
}

function materialName(name: string | null): string {
  return name ?? s.unknownMaterial;
}

/** The rule in plain words (EXPERIENCE.md voice), from the server's figures. */
function ruleText(rule: WatchlistRule): string {
  switch (rule.rule) {
    case "price_rises":
      return s.priceRises(rule.evidence.length);
    case "late":
      return rule.avgDaysLate === null
        ? s.lateNoAverage
        : s.late(daysText(rule.avgDaysLate));
    case "price_gap":
      return rule.evidence
        .map((row) =>
          s.priceGap(materialName(row.materialName), percentText(row.pct)),
        )
        .join("; ");
  }
}

/** An evidence row's invoice: a link for the roles that can open one, else plain. */
function InvoiceCell({ invoiceId }: { invoiceId: string | null }) {
  if (invoiceId === null) return <>{s.readOnly}</>;
  function open(event: MouseEvent) {
    // A modified click keeps the browser's own behaviour (new tab).
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    navigate(invoicePath(invoiceId ?? ""));
  }
  return (
    <a
      href={invoicePath(invoiceId)}
      className="inline-flex min-h-tap-min items-center font-medium underline underline-offset-4"
      onClick={open}
    >
      {s.openInvoice}
    </a>
  );
}

function Evidence({ rule, label }: { rule: WatchlistRule; label: string }) {
  // A table with no link in it gets a focusable scroll region.
  const linked =
    rule.rule !== "late" && rule.evidence.some((row) => row.invoiceId !== null);
  const tableProps = linked
    ? { "aria-label": label }
    : { "aria-label": label, scrollLabel: label };
  if (rule.rule === "price_rises") {
    const c = s.riseColumns;
    return (
      <Table {...tableProps}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{c.material}</TableHead>
            <TableHead scope="col">{c.date}</TableHead>
            <TableHead scope="col" className="text-right">
              {c.previous}
            </TableHead>
            <TableHead scope="col" className="text-right">
              {c.price}
            </TableHead>
            <TableHead scope="col" className="text-right">
              {c.rise}
            </TableHead>
            <TableHead scope="col">{c.invoice}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rule.evidence.map((row, n) => (
            <TableRow key={n} data-testid="evidence-row">
              <TableCell>{materialName(row.materialName)}</TableCell>
              <TableCell className="numeric">{row.invoiceDate}</TableCell>
              <TableCell className="numeric text-right">
                {priceText(row.previousUnitPrice)}
              </TableCell>
              <TableCell className="numeric text-right">
                {priceText(row.unitPrice)}
              </TableCell>
              <TableCell className="numeric text-right">
                {s.plusPct(percentText(row.pct))}
              </TableCell>
              <TableCell>
                <InvoiceCell invoiceId={row.invoiceId} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }
  if (rule.rule === "late") {
    const c = s.lateColumns;
    return (
      <Table {...tableProps}>
        <TableHeader>
          <TableRow>
            <TableHead scope="col">{c.material}</TableHead>
            <TableHead scope="col">{c.received}</TableHead>
            <TableHead scope="col" className="text-right">
              {c.daysLate}
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rule.evidence.map((row, n) => (
            <TableRow key={n} data-testid="evidence-row">
              <TableCell>{materialName(row.materialName)}</TableCell>
              <TableCell className="numeric">{row.receivedDate}</TableCell>
              <TableCell className="numeric text-right">
                {row.daysLate}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );
  }
  const c = s.gapColumns;
  return (
    <Table {...tableProps}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{c.material}</TableHead>
          <TableHead scope="col">{c.date}</TableHead>
          <TableHead scope="col" className="text-right">
            {c.price}
          </TableHead>
          <TableHead scope="col" className="text-right">
            {c.lowest}
          </TableHead>
          <TableHead scope="col">{c.cheapest}</TableHead>
          <TableHead scope="col">{c.invoice}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rule.evidence.map((row, n) => (
          <TableRow key={n} data-testid="evidence-row">
            <TableCell>{materialName(row.materialName)}</TableCell>
            <TableCell className="numeric">{row.invoiceDate}</TableCell>
            <TableCell className="numeric text-right">
              {priceText(row.unitPrice)}
            </TableCell>
            <TableCell className="numeric text-right">
              {priceText(row.lowestUnitPrice)}
            </TableCell>
            <TableCell>
              {supplierName(row.cheapestSupplierId, row.cheapestSupplierName)}
            </TableCell>
            <TableCell>
              <InvoiceCell invoiceId={row.invoiceId} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function AlternativesList({ item }: { item: Alternatives }) {
  const label = s.alternativesFor(materialName(item.materialName));
  const c = s.alternativeColumns;
  return (
    <div className="flex flex-col gap-1">
      <h4 className="font-medium">{materialName(item.materialName)}</h4>
      {item.suppliers.length === 0 ? (
        <p>{s.noAlternatives}</p>
      ) : (
        <Table aria-label={label} scrollLabel={label}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{c.supplier}</TableHead>
              <TableHead scope="col" className="text-right">
                {c.price}
              </TableHead>
              <TableHead scope="col" className="text-right">
                {c.onTime}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {item.suppliers.map((row) => (
              <TableRow key={row.supplierId} data-testid="alternative-row">
                <TableCell className="font-medium">
                  {supplierName(row.supplierId, row.supplierName)}
                  {row.watchlisted ? (
                    <Badge variant="outline" className="ml-2">
                      {s.onWatchlist}
                    </Badge>
                  ) : null}
                </TableCell>
                <TableCell className="numeric text-right">
                  {priceText(row.latestUnitPrice)}
                </TableCell>
                <TableCell className="numeric text-right">
                  {row.onTimeRate === null
                    ? s.noRate
                    : rateText(row.onTimeRate)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

/** One supplier's card: its rules, their evidence, and the alternatives. */
function EntryCard({ entry }: { entry: WatchlistEntry }) {
  const headingId = useId();
  const name = supplierName(entry.supplierId, entry.supplierName);
  return (
    <section
      // A watchlist email can link straight to the supplier's card.
      id={`supplier-${entry.supplierId}`}
      aria-labelledby={headingId}
      data-testid="watchlist-card"
      className="flex flex-col gap-4 rounded-md border p-4"
    >
      <h2 id={headingId} tabIndex={-1} className="text-lg font-semibold">
        {name}
      </h2>
      {entry.rules.map((rule) => {
        const text = ruleText(rule);
        return (
          <div key={rule.rule} className="flex flex-col gap-2">
            <h3 className="font-medium">{text}</h3>
            <p className="text-sm text-muted-foreground">
              {s.since(rule.firstAddedOn)}
            </p>
            <Evidence rule={rule} label={s.evidenceLabel(name, text)} />
          </div>
        );
      })}
      {entry.alternatives.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="font-medium">{s.alternativesHeading}</h3>
          {entry.alternatives.map((item) => (
            <AlternativesList key={item.materialId} item={item} />
          ))}
        </div>
      ) : null}
    </section>
  );
}

/**
 * Watchlist (Story 5.4, CAP-15, CAP-16, EXPERIENCE.md), management's landing page: one
 * card per watchlisted supplier with its rules in plain words, their evidence and the
 * ranked alternatives for each material involved. The server decides every figure
 * and the order (AD-13, AD-20); this page only shows them.
 */
export function WatchlistScreen() {
  const title = strings.surfaces.watchlist;
  const heading = usePageHeading(pageTitle(title));
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{
    attempt: number;
    state: State;
  } | null>(null);
  const state: State =
    result !== null && result.attempt === attempt
      ? result.state
      : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    getWatchlist(controller.signal).then(
      (data) => setResult({ attempt, state: { kind: "ready", data } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        // 401 and DB_OFFLINE are the shell's.
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.code === "DB_OFFLINE")
        ) {
          return;
        }
        const message =
          error instanceof ApiError && error.status === 0
            ? strings.errors.network
            : strings.errors.generic;
        setResult({ attempt, state: { kind: "error", message } });
      },
    );
    return () => controller.abort();
  }, [attempt]);

  const data = state.kind === "ready" ? state.data : null;

  useEffect(() => {
    // A watchlist email links to `?supplier=<id>` (a query survives the sign-in
    // redirect; `#supplier-<id>` still works): once the cards are shown, bring that
    // card into view and move focus to its heading.
    if (data === null) return;
    const supplier = new URLSearchParams(window.location.search).get(
      "supplier",
    );
    const hash = decodeURIComponent(window.location.hash.slice(1));
    const id = supplier ? `supplier-${supplier}` : hash;
    if (!id.startsWith("supplier-")) return;
    const card = document.getElementById(id);
    if (card?.dataset.testid !== "watchlist-card") return;
    card.scrollIntoView?.({ block: "start" });
    card.querySelector<HTMLElement>("h2")?.focus();
  }, [data]);

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>

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

      {data !== null && !data.hasPricePoints ? <p>{s.empty}</p> : null}
      {data !== null && data.hasPricePoints && data.entries.length === 0 ? (
        <p>{s.none}</p>
      ) : null}
      {data?.entries.map((entry) => (
        <EntryCard key={entry.supplierId} entry={entry} />
      ))}
    </div>
  );
}
