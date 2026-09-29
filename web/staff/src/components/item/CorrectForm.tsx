import { useEffect, useId, useRef, useState, type FormEvent } from "react";

import { correctItem, type AdminItem } from "@/api/item";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { strings } from "@/strings";

import { actionFailed, openNext } from "./actionOutcome";
import { fieldLabel } from "./boxes";
import {
  LINE_COLUMN_IDS,
  LINE_COLUMNS,
  corrections,
  editableFieldIds,
  flaggedIds,
  initialDraft,
  type Draft,
  type LineDraft,
} from "./draft";

const DATE_FIELDS = new Set(["invoice_date", "due_date"]);
const AMOUNT_FIELDS = new Set([
  "sub_total",
  "invoice_total",
  "total_tax",
  "amount_due",
]);

const LINE_LABELS: Readonly<Record<keyof LineDraft, string>> = {
  productCode: strings.item.lines.columns.productCode,
  description: strings.item.lines.columns.description,
  quantity: strings.item.lines.columns.quantity,
  unitPrice: strings.item.lines.columns.unitPrice,
  amount: strings.item.lines.columns.amount,
};

interface CorrectFormProps {
  item: AdminItem;
  draft: Draft;
  onChange: (draft: Draft) => void;
  /** Leaves Correct mode without saving. */
  onCancel: () => void;
  /** Called once the server saved it, before the next item opens. */
  onSaved: () => void;
}

/**
 * Correct mode (Story 2.10, EXPERIENCE.md Field list): every field read, except the
 * bank fields (never editable, AD-11), and the missing checked fields become inputs; a
 * changed one is marked "Corrected". Lines are edited whole. Save and re-check sends
 * them and opens the next item with the Toast "Sent for re-check". The server checks
 * every value; nothing here is a business rule.
 */
export function CorrectForm({
  item,
  draft,
  onChange,
  onCancel,
  onSaved,
}: CorrectFormProps) {
  const c = strings.item.correct;
  const base = useId();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const start = initialDraft(item);
  const flagged = flaggedIds(item);
  const bankFields = item.fields.filter((f) => f.bank);
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    // The Correct button that opened it is gone: focus moves to the form.
    heading.current?.focus();
  }, []);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const body = corrections(item, draft);
    if (Object.keys(body.fields).length === 0 && body.lines.length === 0) {
      setProblem(c.nothing);
      return;
    }
    setBusy(true);
    setProblem(null);
    try {
      await correctItem(item.invoiceId, item.routingId, body);
    } catch (error) {
      setBusy(false);
      setProblem(actionFailed(error));
      return;
    }
    onSaved();
    await openNext(item.invoiceId, strings.item.actions.sentForRecheck);
  }

  function setField(id: string, value: string) {
    onChange({ ...draft, fields: { ...draft.fields, [id]: value } });
  }

  function setLine(lineNo: string, column: keyof LineDraft, value: string) {
    const line = draft.lines[lineNo];
    if (line === undefined) return;
    onChange({
      ...draft,
      lines: { ...draft.lines, [lineNo]: { ...line, [column]: value } },
    });
  }

  const corrected = (
    <Badge variant="outline" className="ml-2">
      {c.corrected}
    </Badge>
  );
  const flag = (
    <Badge variant="outline" className="ml-2">
      {strings.item.fields.flagged}
    </Badge>
  );
  const inputClass =
    "min-h-tap-min w-full rounded-md border bg-background px-3 text-sm";

  return (
    <form
      aria-labelledby={`${base}-heading`}
      className="flex flex-col gap-4"
      onSubmit={onSubmit}
      noValidate
    >
      <h2
        id={`${base}-heading`}
        ref={heading}
        tabIndex={-1}
        className="text-lg font-semibold"
      >
        {c.heading}
      </h2>
      <p>{c.intro}</p>
      <div className="flex flex-col gap-3">
        {editableFieldIds(item).map((id) => {
          const inputId = `${base}-f-${id}`;
          const hintId = `${inputId}-hint`;
          const hint = DATE_FIELDS.has(id)
            ? c.dateHint
            : AMOUNT_FIELDS.has(id)
              ? c.amountHint
              : null;
          const value = draft.fields[id] ?? "";
          const currency = item.fields.find((f) => f.fieldId === id)?.currency;
          return (
            <div key={id} className="flex flex-col gap-1">
              <label htmlFor={inputId} className="text-sm font-medium">
                {fieldLabel(id)}
                {currency ? ` (${currency})` : ""}
                {flagged.has(id) ? flag : null}
                {value.trim() !== (start.fields[id] ?? "").trim()
                  ? corrected
                  : null}
              </label>
              <input
                id={inputId}
                className={inputClass}
                value={value}
                inputMode={hint === c.amountHint ? "decimal" : undefined}
                aria-describedby={hint ? hintId : undefined}
                onChange={(event) => setField(id, event.target.value)}
              />
              {hint ? (
                <p id={hintId} className="text-sm">
                  {hint}
                </p>
              ) : null}
            </div>
          );
        })}
      </div>
      {bankFields.length > 0 ? (
        <p className="text-sm">
          {`${c.bankLocked} (${bankFields.map((f) => fieldLabel(f.fieldId)).join(", ")})`}
        </p>
      ) : null}
      {item.lines.map((line) => {
        const lineNo = String(line.lineNo);
        const edited = draft.lines[lineNo];
        const was = start.lines[lineNo];
        if (edited === undefined || was === undefined) return null;
        return (
          <fieldset
            key={lineNo}
            className="flex flex-col gap-3 rounded-md border p-3"
          >
            <legend className="px-1 text-sm font-semibold">
              {c.line(line.lineNo)}
            </legend>
            {LINE_COLUMNS.map((column) => {
              const inputId = `${base}-l-${lineNo}-${column}`;
              const flaggedHere = flagged.has(
                `line[${lineNo}].${LINE_COLUMN_IDS[column]}`,
              );
              return (
                <div key={column} className="flex flex-col gap-1">
                  <label htmlFor={inputId} className="text-sm font-medium">
                    {LINE_LABELS[column]}
                    {flaggedHere ? flag : null}
                    {edited[column].trim() !== was[column].trim()
                      ? corrected
                      : null}
                  </label>
                  <input
                    id={inputId}
                    className={inputClass}
                    value={edited[column]}
                    onChange={(event) =>
                      setLine(lineNo, column, event.target.value)
                    }
                  />
                </div>
              );
            })}
          </fieldset>
        );
      })}
      {problem !== null ? (
        <p role="alert" className="text-destructive">
          {problem}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? strings.item.actions.working : c.save}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={onCancel}
        >
          {strings.item.actions.cancel}
        </Button>
      </div>
    </form>
  );
}
