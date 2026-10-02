import {
  useEffect,
  useId,
  useState,
  type FormEvent,
  type MouseEvent,
} from "react";

import { ApiError } from "@/api";
import {
  listSuppliers,
  type SupplierPage,
  type SupplierQuery,
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
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: SupplierPage }
  | { kind: "error"; message: string };

const EMPTY: SupplierQuery = { page: 1, text: null };

export function supplierPath(supplierId: string): string {
  return `/suppliers/${encodeURIComponent(supplierId)}`;
}

/**
 * Suppliers (Story 4.4, EXPERIENCE.md Suppliers, Flow 5): every supplier by name, 50
 * a page, with a search by name. Each name links to the supplier's page. There is no
 * supplier admin here (EXPERIENCE.md: no supplier master surface).
 */
export function SuppliersScreen() {
  const title = strings.surfaces.suppliers;
  const heading = usePageHeading(pageTitle(title));
  const s = strings.suppliers;
  const searchId = useId();
  // The box, applied as the query only on Search (Enter or the button).
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState<SupplierQuery>(EMPTY);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: string; state: State } | null>(
    null,
  );

  const key = JSON.stringify([query, attempt]);
  const state: State =
    result !== null && result.key === key ? result.state : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    listSuppliers(query, controller.signal).then(
      (data) => {
        // A late answer must not overwrite a newer query or an unmounted screen.
        if (controller.signal.aborted) return;
        // Past the end (fewer matches than when paged): to the last page.
        const last = Math.max(1, Math.ceil(data.total / data.pageSize));
        if (data.items.length === 0 && data.total > 0 && last < query.page) {
          setQuery((q) => ({ ...q, page: last }));
          return;
        }
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
    const text = search.trim();
    setQuery({ page: 1, text: text === "" ? null : text });
  }

  function onClear() {
    setSearch("");
    setQuery(EMPTY);
  }

  function open(event: MouseEvent, supplierId: string) {
    if (!plainClick(event)) return;
    event.preventDefault();
    navigate(supplierPath(supplierId));
  }

  const loading = state.kind === "loading";
  // While the next page loads, the last answer stays, so the paging buttons keep focus.
  const previous = result?.state.kind === "ready" ? result.state.data : null;
  const data = state.kind === "ready" ? state.data : loading ? previous : null;
  const pages =
    data === null ? 1 : Math.max(1, Math.ceil(data.total / data.pageSize));

  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      <form
        role="search"
        className="flex flex-wrap items-end gap-4"
        onSubmit={onSearch}
      >
        <div className="flex w-full max-w-sm min-w-0 flex-col gap-1">
          <label htmlFor={searchId} className="text-sm font-medium">
            {s.searchLabel}
          </label>
          <input
            id={searchId}
            type="search"
            className="min-h-tap-min w-full rounded-md border bg-background px-3 text-sm"
            value={search}
            maxLength={64}
            autoComplete="off"
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <div className="flex gap-2">
          <Button type="submit">{s.search}</Button>
          <Button type="button" variant="outline" onClick={onClear}>
            {s.clear}
          </Button>
        </div>
      </form>

      {loading && data === null ? (
        <div
          aria-hidden="true"
          data-testid="suppliers-loading"
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
        <p>{query.text !== null ? s.noMatch : s.empty}</p>
      ) : null}

      {data !== null && data.items.length > 0 ? (
        <>
          <p>{s.found(data.total)}</p>
          <Table aria-label={s.tableLabel} aria-busy={loading}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{s.columns.name}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => (
                <TableRow key={item.supplierId} data-testid="supplier-row">
                  <TableCell>
                    <a
                      href={supplierPath(item.supplierId)}
                      className="inline-flex min-h-tap-min items-center font-medium underline-offset-4 hover:underline"
                      onClick={(event) => open(event, item.supplierId)}
                    >
                      {item.name}
                    </a>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {pages > 1 ? (
            <nav
              aria-label={s.pagination.label}
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
                {s.pagination.previous}
              </Button>
              <p className="text-sm">{s.pagination.status(data.page, pages)}</p>
              <Button
                type="button"
                variant="outline"
                disabled={loading || data.page >= pages}
                onClick={() => setQuery((q) => ({ ...q, page: q.page + 1 }))}
              >
                {s.pagination.next}
              </Button>
            </nav>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
