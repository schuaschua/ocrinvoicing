import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/api";
import { getItem, type AdminItem } from "@/api/item";
import { BankChangePanel } from "@/components/item/BankChangePanel";
import { fieldLabel, flagBoxes } from "@/components/item/boxes";
import { FieldList, LineTable } from "@/components/item/FieldList";
import { ImageViewer } from "@/components/item/ImageViewer";
import { ReasonChip } from "@/components/ReasonChip";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { navigate } from "@/router";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

type State =
  | { kind: "loading" }
  | { kind: "ready"; item: AdminItem }
  | { kind: "not-found" }
  /** `message` is null after a 401 or DB_OFFLINE: the shell already says why. */
  | { kind: "error"; message: string | null };

const QUEUE_PATH = "/queue";

function two(n: number): string {
  return String(n).padStart(2, "0");
}

/** The received time in the browser's time zone, as YYYY-MM-DD HH:mm. */
function receivedText(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}

/**
 * The admin item (Story 2.9, EXPERIENCE.md Admin item): the image zoomed to the first
 * flagged region on the left (about 55 %), and on the right the bank-change panel when
 * the bank details changed, the fields linked to their boxes, and the lines. Below
 * 1024px the image stacks above the fields. One live region announces selections and
 * the masked values' changes (4.1.3). The admin actions are Story 2.10's.
 */
export function ItemScreen({ invoiceId }: { invoiceId: string }) {
  const title = strings.surfaces.admin_item;
  const heading = usePageHeading(pageTitle(title));
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<{ key: number; state: State } | null>(
    null,
  );
  const [selection, setSelection] = useState<{
    fieldId: string | null;
    key: number;
    focusKey: number;
  } | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const state: State =
    result !== null && result.key === attempt
      ? result.state
      : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    getItem(invoiceId, controller.signal).then(
      (item) => setResult({ key: attempt, state: { kind: "ready", item } }),
      (error: unknown) => {
        if (controller.signal.aborted) return;
        // 401 and DB_OFFLINE are the shell's: the client raised their events, and
        // the sign-in dialog or offline notice says why. Only Try again shows here.
        if (
          error instanceof ApiError &&
          (error.status === 401 || error.code === "DB_OFFLINE")
        ) {
          setResult({ key: attempt, state: { kind: "error", message: null } });
          return;
        }
        const next: State =
          error instanceof ApiError && error.status === 404
            ? { kind: "not-found" }
            : {
                kind: "error",
                message:
                  error instanceof ApiError && error.status === 0
                    ? strings.errors.network
                    : strings.errors.generic,
              };
        setResult({ key: attempt, state: next });
      },
    );
    return () => controller.abort();
  }, [invoiceId, attempt]);

  const announce = useCallback((message: string) => {
    // A repeated message is still announced: clear, then set.
    setAnnouncement("");
    window.setTimeout(() => setAnnouncement(message), 0);
  }, []);

  const item = state.kind === "ready" ? state.item : null;
  const boxes = useMemo(
    () =>
      item !== null && item.contentType !== "application/pdf"
        ? flagBoxes(item.fields, item.pages)
        : [],
    [item],
  );
  const flaggedLines = useMemo(
    () =>
      new Set(
        (item?.reasons ?? []).flatMap((reason) =>
          reason.fieldIds.filter((id) => id.startsWith("line[")),
        ),
      ),
    [item],
  );

  // At first, the first flag box is selected, so the viewer opens zoomed to it.
  const selected =
    selection !== null ? selection.fieldId : (boxes[0]?.fieldId ?? null);
  const selectionKey = selection?.key ?? 0;

  function select(fieldId: string, message: string, focus = false) {
    setSelection((current) => ({
      fieldId,
      key: (current?.key ?? 0) + 1,
      focusKey: (current?.focusKey ?? 0) + (focus ? 1 : 0),
    }));
    announce(message);
  }

  const f = strings.item.fields;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <Button asChild variant="ghost" className="px-2">
          <a
            href={QUEUE_PATH}
            onClick={(event) => {
              if (event.button !== 0 || event.metaKey || event.ctrlKey) return;
              event.preventDefault();
              navigate(QUEUE_PATH);
            }}
          >
            {strings.item.back}
          </a>
        </Button>
      </div>
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      <p role="status" className="sr-only" data-testid="item-announcer">
        {announcement}
      </p>

      {state.kind === "loading" ? (
        <div
          aria-hidden="true"
          data-testid="item-loading"
          className="flex flex-col gap-3"
        >
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      ) : null}

      {state.kind === "not-found" ? <p>{strings.item.notFound}</p> : null}

      {state.kind === "error" ? (
        <div className="flex max-w-prose flex-col gap-4">
          {state.message !== null ? <p role="alert">{state.message}</p> : null}
          <div>
            <Button type="button" onClick={() => setAttempt((n) => n + 1)}>
              {strings.errors.tryAgain}
            </Button>
          </div>
        </div>
      ) : null}

      {item !== null ? (
        <>
          <div className="flex flex-col gap-1">
            <p className="font-medium">
              {strings.item.from(
                item.supplierName ?? strings.queue.unknownSupplier,
              )}
            </p>
            <p className="numeric text-sm">
              {strings.item.received(receivedText(item.receivedAt))}
            </p>
          </div>
          <section aria-label={strings.item.reasons}>
            <ul className="flex flex-wrap gap-1">
              {item.reasons.map((reason) => (
                <li key={reason.code}>
                  <ReasonChip code={reason.code} />
                </li>
              ))}
            </ul>
          </section>
          <div className="grid gap-6 lg:grid-cols-[11fr_9fr]">
            <ImageViewer
              invoiceId={item.invoiceId}
              contentType={item.contentType}
              imageAvailable={item.imageAvailable}
              boxes={boxes}
              selected={selected}
              selectionKey={selectionKey}
              onStep={(fieldId, position) =>
                select(
                  fieldId,
                  `${strings.item.viewer.position(position, boxes.length)}: ${fieldLabel(fieldId)}`,
                )
              }
              onSelectBox={(fieldId) =>
                select(fieldId, f.selected(fieldLabel(fieldId)), true)
              }
            />
            <div className="flex min-w-0 flex-col gap-4">
              {item.bankChanges.length > 0 ? (
                <BankChangePanel
                  invoiceId={item.invoiceId}
                  phone={item.supplierPhone}
                  changes={item.bankChanges}
                  announce={announce}
                />
              ) : null}
              <section aria-labelledby="fields-heading">
                <h2 id="fields-heading" className="mb-2 text-lg font-semibold">
                  {f.heading}
                </h2>
                <FieldList
                  fields={item.fields}
                  boxes={boxes}
                  bankChanges={item.bankChanges}
                  selected={selected}
                  focusKey={selection?.focusKey ?? 0}
                  onSelect={(fieldId) =>
                    select(fieldId, f.selected(fieldLabel(fieldId)))
                  }
                />
              </section>
              {item.lines.length > 0 ? (
                <section aria-labelledby="lines-heading">
                  <h2 id="lines-heading" className="mb-2 text-lg font-semibold">
                    {strings.item.lines.heading}
                  </h2>
                  <LineTable lines={item.lines} flagged={flaggedLines} />
                </section>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
