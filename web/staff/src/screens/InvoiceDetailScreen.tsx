import { useEffect, useState } from "react";

import { ApiError } from "@/api";
import { getInvoice, type InvoiceDetail } from "@/api/invoices";
import { fieldLabel } from "@/components/item/boxes";
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
import { dateTimeText } from "@/lib/format";
import { navigate } from "@/router";
import { pageTitle, statusLabel, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

const INVOICES_PATH = "/invoices";

type State =
  | { kind: "loading" }
  | { kind: "ready"; invoice: InvoiceDetail }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

/**
 * One invoice for admin and finance (Story 3.4): its current fields, lines, status
 * history and accounts reference. Read-only: no image, and bank fields only as "Bank
 * details on file" (AD-11); admin actions live on the admin item screen.
 */
export function InvoiceDetailScreen({ invoiceId }: { invoiceId: string }) {
  const s = strings.invoices;
  const d = s.detail;
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const invoice = state.kind === "ready" ? state.invoice : null;
  const title = invoice
    ? d.heading(invoice.supplierName ?? strings.queue.unknownSupplier)
    : strings.surfaces.invoice_detail;
  const heading = usePageHeading(pageTitle(title));

  useEffect(() => {
    const controller = new AbortController();
    getInvoice(invoiceId, controller.signal).then(
      (found) => setState({ kind: "ready", invoice: found }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ kind: "not-found" });
          return;
        }
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
  }, [invoiceId, attempt]);

  const status = (code: InvoiceDetail["status"], afterCorrection = false) =>
    statusLabel(code, { afterCorrection });

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button asChild variant="ghost" className="px-2">
          <a
            href={INVOICES_PATH}
            onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey) return;
              event.preventDefault();
              navigate(INVOICES_PATH);
            }}
          >
            {d.back}
          </a>
        </Button>
      </div>
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

      {state.kind === "not-found" ? <p>{d.notFound}</p> : null}

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

      {invoice !== null ? (
        <>
          <section aria-labelledby="invoice-summary" className="max-w-prose">
            <h2 id="invoice-summary" className="mb-2 text-lg font-semibold">
              {d.summary}
            </h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
              <dt className="text-sm">{d.status}</dt>
              <dd>
                <Badge variant="outline">
                  {status(invoice.status, invoice.afterCorrection)}
                </Badge>
              </dd>
              <dt className="text-sm">{d.supplier}</dt>
              <dd className="min-w-0 break-words">
                {invoice.supplierName ?? strings.queue.unknownSupplier}
              </dd>
              <dt className="text-sm">{d.received}</dt>
              <dd className="numeric">{dateTimeText(invoice.receivedAt)}</dd>
              <dt className="text-sm">{d.reference}</dt>
              <dd className="numeric">{invoice.reference ?? ""}</dd>
              <dt className="text-sm">{d.accountsRef}</dt>
              <dd className="numeric min-w-0 break-words">
                {invoice.accountsRef ?? d.notPosted}
              </dd>
              <dt className="text-sm">{d.postedAt}</dt>
              <dd className="numeric">
                {invoice.postedAt === null
                  ? d.notPosted
                  : dateTimeText(invoice.postedAt)}
              </dd>
            </dl>
          </section>

          <section aria-labelledby="invoice-fields" className="max-w-prose">
            <h2 id="invoice-fields" className="mb-2 text-lg font-semibold">
              {d.fields}
            </h2>
            {invoice.fields.length === 0 && !invoice.bankOnFile ? (
              <p>{d.noFields}</p>
            ) : (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                {invoice.fields.map((field) => (
                  <div key={field.fieldId} className="contents">
                    <dt className="text-sm">{fieldLabel(field.fieldId)}</dt>
                    <dd className="numeric min-w-0 break-words">
                      {field.value === null
                        ? strings.item.fields.notRead
                        : field.currency === null
                          ? field.value
                          : `${field.currency} ${field.value}`}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
            {invoice.bankOnFile ? <p className="mt-2">{d.bankOnFile}</p> : null}
          </section>

          {invoice.lines.length > 0 ? (
            <section aria-labelledby="invoice-lines">
              <h2 id="invoice-lines" className="mb-2 text-lg font-semibold">
                {strings.item.lines.heading}
              </h2>
              <Table
                aria-label={strings.item.lines.label}
                scrollLabel={strings.item.lines.label}
              >
                <TableHeader>
                  <TableRow>
                    {(
                      [
                        ["line", false],
                        ["productCode", false],
                        ["description", false],
                        ["quantity", true],
                        ["unitPrice", true],
                        ["amount", true],
                      ] as const
                    ).map(([column, right]) => (
                      <TableHead
                        key={column}
                        scope="col"
                        className={right ? "text-right" : undefined}
                      >
                        {strings.item.lines.columns[column]}
                      </TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {invoice.lines.map((line) => (
                    <TableRow key={line.lineNo}>
                      <TableCell className="numeric">{line.lineNo}</TableCell>
                      <TableCell>{line.productCode ?? ""}</TableCell>
                      <TableCell>{line.description ?? ""}</TableCell>
                      <TableCell className="numeric text-right">
                        {line.quantity ?? ""}
                      </TableCell>
                      <TableCell className="numeric text-right">
                        {line.unitPrice ?? ""}
                      </TableCell>
                      <TableCell className="numeric text-right">
                        {line.amount ?? ""}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </section>
          ) : null}

          <section aria-labelledby="invoice-history">
            <h2 id="invoice-history" className="mb-2 text-lg font-semibold">
              {d.history}
            </h2>
            <Table aria-label={d.historyLabel} scrollLabel={d.historyLabel}>
              <TableHeader>
                <TableRow>
                  <TableHead scope="col">{d.historyColumns.at}</TableHead>
                  <TableHead scope="col">{d.historyColumns.from}</TableHead>
                  <TableHead scope="col">{d.historyColumns.to}</TableHead>
                  <TableHead scope="col">{d.historyColumns.by}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {invoice.history.map((entry, index) => (
                  <TableRow key={index}>
                    <TableCell className="numeric">
                      {dateTimeText(entry.at)}
                    </TableCell>
                    <TableCell>
                      {entry.fromStatus === null
                        ? d.started
                        : status(entry.fromStatus)}
                    </TableCell>
                    <TableCell>{status(entry.toStatus)}</TableCell>
                    <TableCell>
                      {s.actors[entry.actor] ?? s.actors.system}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        </>
      ) : null}
    </div>
  );
}
