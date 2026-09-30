import {
  useEffect,
  useId,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";

import { ApiError } from "@/api";
import {
  searchInvoices,
  type InvoicePage,
  type InvoiceQuery,
} from "@/api/invoices";
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
import { amountText, dateTimeText } from "@/lib/format";
import { navigate } from "@/router";
import {
  pageTitle,
  statusLabel,
  statusLabels,
  strings,
  type InvoiceStatus,
} from "@/strings";

import { usePageHeading } from "./usePageHeading";

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: InvoicePage }
  | { kind: "error"; message: string };

/** The status filter's options: one per label, each standing for all its codes. */
const STATUS_OPTIONS: { label: string; codes: InvoiceStatus[] }[] = [];
for (const [code, label] of Object.entries(statusLabels) as [
  InvoiceStatus,
  string,
][]) {
  const option = STATUS_OPTIONS.find((o) => o.label === label);
  if (option) option.codes.push(code);
  else STATUS_OPTIONS.push({ label, codes: [code] });
}

const EMPTY: InvoiceQuery = {
  page: 1,
  supplierId: null,
  statuses: [],
  invoiceNumber: null,
  reference: null,
};

export function invoicePath(invoiceId: string): string {
  return `/invoices/${encodeURIComponent(invoiceId)}`;
}

function text(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
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

/**
 * Invoices (Story 3.4, EXPERIENCE.md Invoices): every invoice, newest first, 50 a
 * page, searched by supplier, status, invoice number or supplier reference. Statuses
 * show as labels, never codes. The supplier name links to the invoice's detail.
 */
export function InvoicesScreen() {
  const title = strings.surfaces.invoices;
  const heading = usePageHeading(pageTitle(title));
  const s = strings.invoices;
  const ids = {
    supplier: useId(),
    status: useId(),
    number: useId(),
    reference: useId(),
    hint: useId(),
  };
  // The form's fields, applied as the query only on Search.
  const [supplier, setSupplier] = useState("");
  const [status, setStatus] = useState("");
  const [number, setNumber] = useState("");
  const [reference, setReference] = useState("");
  const [query, setQuery] = useState<InvoiceQuery>(EMPTY);
  const [attempt, setAttempt] = useState(0);
  // The supplier options outlive a failed search, so a chosen supplier stays shown.
  const [suppliers, setSuppliers] = useState<InvoicePage["suppliers"]>([]);
  const [result, setResult] = useState<{ key: string; state: State } | null>(
    null,
  );

  const key = JSON.stringify([query, attempt]);
  const state: State =
    result !== null && result.key === key ? result.state : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    searchInvoices(query, controller.signal).then(
      (data) => {
        // Past the end (fewer matches than when paged): to the last page.
        const last = Math.max(1, Math.ceil(data.total / data.pageSize));
        if (data.items.length === 0 && data.total > 0 && last < query.page) {
          setQuery((q) => ({ ...q, page: last }));
          return;
        }
        setSuppliers(data.suppliers);
        setResult({ key, state: { kind: "ready", data } });
      },
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
          error instanceof ApiError && error.status === 400
            ? s.badSearch
            : error instanceof ApiError && error.status === 0
              ? strings.errors.network
              : strings.errors.generic;
        setResult({ key, state: { kind: "error", message } });
      },
    );
    return () => controller.abort();
  }, [key, query, s.badSearch]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    const option = STATUS_OPTIONS.find((o) => o.label === status);
    setQuery({
      page: 1,
      supplierId: supplier === "" ? null : supplier,
      statuses: option?.codes ?? [],
      invoiceNumber: text(number),
      reference: text(reference),
    });
  }

  function onClear() {
    setSupplier("");
    setStatus("");
    setNumber("");
    setReference("");
    setQuery(EMPTY);
  }

  function open(event: MouseEvent, invoiceId: string) {
    if (!plainClick(event)) return;
    event.preventDefault();
    navigate(invoicePath(invoiceId));
  }

  const filtered =
    query.supplierId !== null ||
    query.statuses.length > 0 ||
    query.invoiceNumber !== null ||
    query.reference !== null;
  const loading = state.kind === "loading";
  // While the next page loads, the last answer stays, so the paging buttons keep focus.
  const previous = result?.state.kind === "ready" ? result.state.data : null;
  const data = state.kind === "ready" ? state.data : loading ? previous : null;
  const pages =
    data === null ? 1 : Math.max(1, Math.ceil(data.total / data.pageSize));
  const control =
    "min-h-tap-min w-full rounded-md border bg-background px-3 text-sm";

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      <form
        role="search"
        // Top-aligned: the reference hint under its input must not lift that input
        // above the others (the buttons sit level with the inputs, below the labels).
        className="flex flex-wrap items-start gap-4"
        onSubmit={onSearch}
      >
        <div className="flex max-w-full min-w-0 flex-col gap-1">
          <label htmlFor={ids.supplier} className="text-sm font-medium">
            {s.filters.supplier}
          </label>
          <select
            id={ids.supplier}
            className={control}
            value={supplier}
            onChange={(event) => setSupplier(event.target.value)}
          >
            <option value="">{s.filters.allSuppliers}</option>
            {suppliers.map((option) => (
              <option key={option.supplierId} value={option.supplierId}>
                {option.supplierName ?? strings.queue.unknownSupplier}
              </option>
            ))}
          </select>
        </div>
        <div className="flex max-w-full min-w-0 flex-col gap-1">
          <label htmlFor={ids.status} className="text-sm font-medium">
            {s.filters.status}
          </label>
          <select
            id={ids.status}
            className={control}
            value={status}
            onChange={(event) => setStatus(event.target.value)}
          >
            <option value="">{s.filters.allStatuses}</option>
            {STATUS_OPTIONS.map((option) => (
              <option key={option.label} value={option.label}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex max-w-full min-w-0 flex-col gap-1">
          <label htmlFor={ids.number} className="text-sm font-medium">
            {s.filters.invoiceNumber}
          </label>
          <input
            id={ids.number}
            className={control}
            value={number}
            maxLength={64}
            autoComplete="off"
            onChange={(event) => setNumber(event.target.value)}
          />
        </div>
        <div className="flex max-w-full min-w-0 flex-col gap-1">
          <label htmlFor={ids.reference} className="text-sm font-medium">
            {s.filters.reference}
          </label>
          <input
            id={ids.reference}
            className={control}
            value={reference}
            maxLength={16}
            autoComplete="off"
            aria-describedby={ids.hint}
            onChange={(event) => setReference(event.target.value)}
          />
          <p id={ids.hint} className="text-sm text-muted-foreground">
            {s.filters.referenceHint}
          </p>
        </div>
        <div className="flex gap-2 sm:mt-6">
          <Button type="submit">{s.search}</Button>
          <Button type="button" variant="outline" onClick={onClear}>
            {s.clear}
          </Button>
        </div>
      </form>

      {loading && data === null ? (
        <div
          aria-hidden="true"
          data-testid="invoices-loading"
          className="flex flex-col gap-3"
        >
          {[0, 1, 2, 3, 4].map((n) => (
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

      {data !== null && data.items.length === 0 ? (
        <p>{filtered ? s.noMatch : s.empty}</p>
      ) : null}

      {data !== null && data.items.length > 0 ? (
        <>
          <p>{s.found(data.total)}</p>
          <Table aria-label={s.tableLabel} aria-busy={loading}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{s.columns.received}</TableHead>
                <TableHead scope="col">{s.columns.supplier}</TableHead>
                <TableHead scope="col">{s.columns.invoiceNumber}</TableHead>
                <TableHead scope="col" className="text-right">
                  {s.columns.total}
                </TableHead>
                <TableHead scope="col">{s.columns.status}</TableHead>
                <TableHead scope="col">{s.columns.reference}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => (
                <TableRow key={item.invoiceId} data-testid="invoice-row">
                  <TableCell className="numeric">
                    {dateTimeText(item.receivedAt)}
                  </TableCell>
                  <TableCell>
                    <a
                      href={invoicePath(item.invoiceId)}
                      className="inline-flex min-h-tap-min items-center font-medium underline-offset-4 hover:underline"
                      onClick={(event) => open(event, item.invoiceId)}
                    >
                      {item.supplierName ?? strings.queue.unknownSupplier}
                    </a>
                  </TableCell>
                  <TableCell>{item.invoiceNumber ?? s.noNumber}</TableCell>
                  <TableCell className="numeric text-right">
                    {amountText(item.amount, item.currency)}
                  </TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {statusLabel(item.status, {
                        afterCorrection: item.afterCorrection,
                      })}
                    </Badge>
                  </TableCell>
                  <TableCell className="numeric">
                    {item.reference ?? ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {pages > 1 ? (
            <nav
              aria-label={strings.queue.pagination.label}
              className="flex flex-wrap items-center gap-2"
            >
              <Button
                type="button"
                variant="outline"
                disabled={loading || data.page <= 1}
                onClick={() =>
                  setQuery((q) => ({ ...q, page: Math.max(1, q.page - 1) }))
                }
              >
                {strings.queue.pagination.previous}
              </Button>
              <p className="text-sm">
                {strings.queue.pagination.status(data.page, pages)}
              </p>
              <Button
                type="button"
                variant="outline"
                disabled={loading || data.page >= pages}
                onClick={() => setQuery((q) => ({ ...q, page: q.page + 1 }))}
              >
                {strings.queue.pagination.next}
              </Button>
            </nav>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
