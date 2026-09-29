import {
  useEffect,
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent,
} from "react";

import { ApiError } from "@/api";
import { getQueue, type QueuePage } from "@/api/queue";
import { ReasonChip } from "@/components/ReasonChip";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { navigate } from "@/router";
import { useShortcuts } from "@/shell/shortcuts";
import { pageTitle, reasonLabels, strings, type ReasonCode } from "@/strings";

import { usePageHeading } from "./usePageHeading";

const REASONS = Object.keys(reasonLabels) as ReasonCode[];
const MINUTE_MS = 60_000;

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: QueuePage }
  | { kind: "error"; message: string };

/** "SGD 1,248.50": the server's 2-decimal string, grouped for reading, never computed. */
function amountText(amount: string | null, currency: string | null): string {
  if (amount === null) return strings.queue.noAmount;
  const [whole = "", cents] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const text = cents === undefined ? grouped : `${grouped}.${cents}`;
  return currency === null ? text : `${currency} ${text}`;
}

function two(n: number): string {
  return String(n).padStart(2, "0");
}

/** The received time in the browser's time zone, as YYYY-MM-DD HH:mm. */
function receivedText(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}

function ageText(iso: string, now: number): string {
  const at = new Date(iso).getTime();
  if (Number.isNaN(at)) return "";
  return strings.queue.age(Math.max(0, Math.floor((now - at) / MINUTE_MS)));
}

function itemPath(invoiceId: string): string {
  return `/queue/${encodeURIComponent(invoiceId)}`;
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
 * The admin queue (Story 2.8, EXPERIENCE.md Queue table): every invoice waiting for an
 * admin, oldest first, 50 a page, filterable by reason and supplier. The supplier name
 * is a real link to the item; a click anywhere else on the row opens it too.
 */
export function QueueScreen() {
  const title = strings.surfaces.admin_queue;
  const heading = usePageHeading(pageTitle(title));
  const reasonId = useId();
  const supplierId = useId();
  const [page, setPage] = useState(1);
  const [reason, setReason] = useState<ReasonCode | null>(null);
  const [supplier, setSupplier] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  // The answer and the query it is for: another query shows loading until its own.
  const [result, setResult] = useState<{ key: string; state: State } | null>(
    null,
  );
  const [now, setNow] = useState(() => Date.now());
  // Story 2.11: the row `j`/`k` chose, for the query it was chosen on.
  const [active, setActive] = useState<{ key: string; index: number } | null>(
    null,
  );
  const body = useRef<HTMLTableSectionElement>(null);

  const key = JSON.stringify([page, reason, supplier, attempt]);
  const state: State =
    result !== null && result.key === key ? result.state : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    getQueue({ page, reason, supplierId: supplier }, controller.signal).then(
      (data) => {
        // Past the end (the queue shrank while the admin paged): to the last page.
        if (data.items.length === 0 && data.total > 0 && page > 1) {
          setPage(Math.max(1, Math.ceil(data.total / data.pageSize)));
          return;
        }
        setNow(Date.now());
        setResult({ key, state: { kind: "ready", data } });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        // 401 and DB_OFFLINE are the shell's: the client raised their events, and the
        // sign-in dialog or offline notice shows instead.
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.code === "DB_OFFLINE")
        ) {
          return;
        }
        const network = error instanceof ApiError && error.status === 0;
        setResult({
          key,
          state: {
            kind: "error",
            message: network ? strings.errors.network : strings.errors.generic,
          },
        });
      },
    );
    return () => controller.abort();
  }, [key, page, reason, supplier]);

  function onReason(event: ChangeEvent<HTMLSelectElement>) {
    const value = event.target.value;
    setReason(value === "" ? null : (value as ReasonCode));
    setPage(1);
  }

  function onSupplier(event: ChangeEvent<HTMLSelectElement>) {
    const value = event.target.value;
    setSupplier(value === "" ? null : value);
    setPage(1);
  }

  function open(invoiceId: string) {
    navigate(itemPath(invoiceId));
  }

  function openItem(event: MouseEvent, invoiceId: string) {
    if (!plainClick(event)) return;
    event.preventDefault();
    open(invoiceId);
  }

  const filtered = reason !== null || supplier !== null;
  const loading = state.kind === "loading";
  // While the next page or filter loads, the last answer stays on screen, so the
  // pagination buttons keep focus.
  const previous = result?.state.kind === "ready" ? result.state.data : null;
  const data =
    state.kind === "ready"
      ? state.data
      : state.kind === "loading"
        ? previous
        : null;
  const pages =
    data === null ? 1 : Math.max(1, Math.ceil(data.total / data.pageSize));
  const items = state.kind === "ready" ? state.data.items : [];
  const activeIndex =
    active !== null && active.key === key && active.index < items.length
      ? active.index
      : null;

  /** Story 2.11: `j`/`k` move the chosen row and focus it; at the ends it stays. */
  function move(delta: number) {
    if (items.length === 0) return;
    const index =
      activeIndex === null
        ? 0
        : Math.min(Math.max(activeIndex + delta, 0), items.length - 1);
    setActive({ key, index });
    const row = body.current?.children[index];
    if (row instanceof HTMLElement) row.focus();
  }

  const chosen = activeIndex === null ? undefined : items[activeIndex];
  useShortcuts({
    j: () => move(1),
    k: () => move(-1),
    Enter: chosen === undefined ? undefined : () => open(chosen.invoiceId),
  });

  const selectClass =
    "min-h-tap-min w-full rounded-md border bg-background px-3 text-sm";

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      {data?.pageUsage ? (
        <Alert>
          <AlertDescription className="text-foreground">
            {strings.queue.pageUsage(
              data.pageUsage.pagesUsed,
              data.pageUsage.pageCap,
            )}
          </AlertDescription>
        </Alert>
      ) : null}
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex max-w-full min-w-0 flex-col gap-1">
          <label htmlFor={reasonId} className="text-sm font-medium">
            {strings.queue.filters.reason}
          </label>
          <select
            id={reasonId}
            className={selectClass}
            value={reason ?? ""}
            onChange={onReason}
          >
            <option value="">{strings.queue.filters.allReasons}</option>
            {REASONS.map((code) => (
              <option key={code} value={code}>
                {reasonLabels[code]}
              </option>
            ))}
          </select>
        </div>
        <div className="flex max-w-full min-w-0 flex-col gap-1">
          <label htmlFor={supplierId} className="text-sm font-medium">
            {strings.queue.filters.supplier}
          </label>
          <select
            id={supplierId}
            className={selectClass}
            value={supplier ?? ""}
            onChange={onSupplier}
          >
            <option value="">{strings.queue.filters.allSuppliers}</option>
            {(data?.suppliers ?? []).map((option) => (
              <option key={option.supplierId} value={option.supplierId}>
                {option.supplierName ?? strings.queue.unknownSupplier}
              </option>
            ))}
          </select>
        </div>
      </div>

      {state.kind === "loading" && data === null ? (
        <div
          aria-hidden="true"
          data-testid="queue-loading"
          className="flex flex-col gap-3"
        >
          {[0, 1, 2, 3, 4].map((row) => (
            <Skeleton key={row} className="h-10 w-full" />
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
        <p>{filtered ? strings.queue.noMatch : strings.queue.empty}</p>
      ) : null}

      {data !== null && data.items.length > 0 ? (
        <>
          <p>{strings.queue.waiting(data.total)}</p>
          <Table
            aria-label={strings.queue.tableLabel}
            aria-busy={state.kind === "loading"}
          >
            <TableHeader>
              <TableRow>
                <TableHead scope="col">
                  {strings.queue.columns.received}
                </TableHead>
                <TableHead scope="col">
                  {strings.queue.columns.supplier}
                </TableHead>
                <TableHead scope="col" className="text-right">
                  {strings.queue.columns.amount}
                </TableHead>
                <TableHead scope="col">
                  {strings.queue.columns.reasons}
                </TableHead>
                <TableHead scope="col">{strings.queue.columns.age}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody ref={body}>
              {data.items.map((item, index) => (
                <TableRow
                  key={item.invoiceId}
                  data-testid="queue-row"
                  // Focusable by script only (`j`/`k`), never a tab stop; the ring
                  // sits inside the row so the table's scroller doesn't clip it.
                  tabIndex={-1}
                  aria-current={index === activeIndex ? "true" : undefined}
                  className="cursor-pointer focus-visible:[outline-offset:calc(var(--focus-ring-width)*-1)]"
                  onClick={(event) => openItem(event, item.invoiceId)}
                >
                  <TableCell className="numeric">
                    {receivedText(item.receivedAt)}
                  </TableCell>
                  <TableCell>
                    <a
                      href={itemPath(item.invoiceId)}
                      className="inline-flex min-h-tap-min items-center font-medium underline-offset-4 hover:underline"
                      onClick={(event) => {
                        // The row's own click would open it a second time.
                        event.stopPropagation();
                        openItem(event, item.invoiceId);
                      }}
                    >
                      {item.supplierName ?? strings.queue.unknownSupplier}
                    </a>
                  </TableCell>
                  <TableCell className="numeric text-right">
                    {amountText(item.amount, item.currency)}
                  </TableCell>
                  <TableCell>
                    {item.returnedAfterCorrection ? (
                      // Story 2.10: the re-check flagged it again; the chips are
                      // its new reasons only.
                      <Badge variant="outline" className="mb-1">
                        {strings.queue.returned}
                      </Badge>
                    ) : null}
                    <ul className="flex flex-wrap gap-1">
                      {item.reasons.map((code) => (
                        <li key={code}>
                          <ReasonChip code={code} />
                        </li>
                      ))}
                    </ul>
                  </TableCell>
                  <TableCell>{ageText(item.receivedAt, now)}</TableCell>
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
                onClick={() => setPage((n) => Math.max(1, n - 1))}
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
                onClick={() => setPage((n) => n + 1)}
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
