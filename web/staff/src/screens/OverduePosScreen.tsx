import { useEffect, useState } from "react";

import { ApiError } from "@/api";
import { getOverduePos, type OverdueList } from "@/api/overdue";
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
import { singaporeDateText } from "@/lib/format";
import { pageTitle, poLabel, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

type State =
  | { kind: "loading" }
  | { kind: "ready"; list: OverdueList }
  | { kind: "error"; message: string };

/**
 * Overdue POs (Story 4.2, CAP-12, EXPERIENCE.md): POs past their expected date with no
 * invoice, one section per supplier, with the date the weekday job made the list. The
 * server decides what is overdue (AD-13); this page only shows it.
 */
export function OverduePosScreen() {
  const title = strings.surfaces.overdue_pos;
  const heading = usePageHeading(pageTitle(title));
  const s = strings.overdue;
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
    getOverduePos(controller.signal).then(
      (list) => setResult({ attempt, state: { kind: "ready", list } }),
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

  const list = state.kind === "ready" ? state.list : null;

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

      {list !== null && list.madeAt === null ? (
        <p className="max-w-prose">{s.neverMade}</p>
      ) : null}

      {list !== null && list.madeAt !== null ? (
        <>
          <p className="numeric text-muted-foreground">
            {s.asOf(singaporeDateText(list.madeAt))}
          </p>
          {list.suppliers.length === 0 ? <p>{s.none}</p> : null}
          {list.suppliers.map((supplier) => {
            const name = supplier.supplierName ?? s.unknownSupplier;
            return (
              <section
                key={supplier.supplierId}
                aria-label={name}
                className="flex flex-col gap-2"
              >
                <h2 className="text-lg font-semibold">{name}</h2>
                <Table aria-label={name}>
                  <TableHeader>
                    <TableRow>
                      <TableHead scope="col">{s.columns.po}</TableHead>
                      <TableHead scope="col">{s.columns.expected}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {supplier.pos.map((po) => (
                      <TableRow key={po.poNumber}>
                        <TableCell className="font-medium">
                          {poLabel(po.poNumber)}
                        </TableCell>
                        <TableCell className="numeric">
                          {po.expectedDate}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </section>
            );
          })}
        </>
      ) : null}
    </div>
  );
}
