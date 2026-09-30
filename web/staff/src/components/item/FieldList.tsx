import { useEffect, useRef, type ReactNode } from "react";

import type { BankChange, ItemField, ItemLine } from "@/api/item";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { strings } from "@/strings";

import { fieldLabel, type FlagBox } from "./boxes";
import { Masked } from "./MaskedValue";

/** P-9 / AD-18: below this a field shows its confidence badge. */
export const CONFIDENCE_THRESHOLD = 0.9;

/** DESIGN.md Confidence badge, announced as "Confidence 84%". Rounded down, so it never reads 90. */
export function ConfidenceBadge({ confidence }: { confidence: number | null }) {
  if (confidence === null || confidence >= CONFIDENCE_THRESHOLD) return null;
  const percent = Math.floor(confidence * 100);
  return (
    <Badge className="numeric border-transparent bg-confidence-low text-warning-foreground">
      <span className="sr-only">{`${strings.item.fields.confidence} `}</span>
      {`${percent}%`}
    </Badge>
  );
}

function fieldValue(field: ItemField, bank: BankChange | undefined): ReactNode {
  const f = strings.item.fields;
  if (field.bank) {
    // AD-11: only the server's mask, and only for a changed field (its Show is in
    // the bank panel); otherwise no digits at all.
    return bank?.newValue != null ? (
      <Masked digits={bank.newValue} />
    ) : (
      f.bankOnFile
    );
  }
  if (field.value === null) return f.notRead;
  return field.currency ? `${field.currency} ${field.value}` : field.value;
}

interface FieldListProps {
  fields: ItemField[];
  boxes: FlagBox[];
  bankChanges: BankChange[];
  selected: string | null;
  /** Changes when a box was chosen on the image: focus moves to its field. */
  focusKey: number;
  onSelect: (fieldId: string) => void;
}

/**
 * The item's current fields (EXPERIENCE.md Field list, UX-DR11): each with its value,
 * a confidence badge below 90 % and its flag state; a flagged field with a box carries
 * the box's number. Choosing a field highlights its box; choosing a box focuses its
 * field here.
 */
export function FieldList({
  fields,
  boxes,
  bankChanges,
  selected,
  focusKey,
  onSelect,
}: FieldListProps) {
  const buttons = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    if (focusKey === 0 || selected === null) return;
    buttons.current.get(selected)?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only a new box choice (focusKey) moves focus; a selection from the list or the Previous/Next buttons must not
  }, [focusKey]);

  const f = strings.item.fields;
  if (fields.length === 0) return <p>{f.none}</p>;
  return (
    <ul className="flex flex-col gap-2">
      {fields.map((field) => {
        const box = boxes.find((b) => b.fieldId === field.fieldId);
        const isSelected = field.fieldId === selected;
        const bank = bankChanges.find((c) => c.fieldId === field.fieldId);
        return (
          <li
            key={field.fieldId}
            className={cn(
              "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border px-3 py-1",
              isSelected ? "border-ring bg-accent" : null,
            )}
          >
            <button
              type="button"
              ref={(element) => {
                if (element) buttons.current.set(field.fieldId, element);
                else buttons.current.delete(field.fieldId);
              }}
              aria-pressed={isSelected}
              className="inline-flex min-h-tap-min items-center gap-2 text-left text-sm font-medium underline-offset-4 hover:underline"
              onClick={() => onSelect(field.fieldId)}
            >
              {box ? (
                <>
                  <span className="numeric rounded-sm border px-1">
                    <span className="sr-only">{`${f.box(box.number)}:`}</span>
                    <span aria-hidden="true">{box.number}</span>
                  </span>{" "}
                </>
              ) : null}
              {fieldLabel(field.fieldId)}
            </button>
            <span className="numeric min-w-0 break-words">
              {fieldValue(field, bank)}
            </span>
            <ConfidenceBadge confidence={field.confidence} />
            {field.flagged ? (
              <Badge variant="outline">{f.flagged}</Badge>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

/** The item's current lines; a flagged line field is marked, and low confidence badged. */
export function LineTable({
  lines,
  flagged,
}: {
  lines: ItemLine[];
  flagged: ReadonlySet<string>;
}) {
  const l = strings.item.lines;
  const cell = (lineNo: number, column: string, text: string | null) => (
    <>
      {text ?? strings.item.fields.notRead}
      {flagged.has(`line[${lineNo}].${column}`) ? (
        <Badge variant="outline" className="ml-2">
          {strings.item.fields.flagged}
        </Badge>
      ) : null}
    </>
  );
  return (
    <Table aria-label={l.label} scrollLabel={l.label}>
      <TableHeader>
        <TableRow>
          <TableHead scope="col">{l.columns.line}</TableHead>
          <TableHead scope="col">{l.columns.productCode}</TableHead>
          <TableHead scope="col">{l.columns.description}</TableHead>
          <TableHead scope="col" className="text-right">
            {l.columns.quantity}
          </TableHead>
          <TableHead scope="col" className="text-right">
            {l.columns.unitPrice}
          </TableHead>
          <TableHead scope="col" className="text-right">
            {l.columns.amount}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {lines.map((line) => (
          <TableRow key={line.lineNo}>
            <TableCell className="numeric">
              {line.lineNo} <ConfidenceBadge confidence={line.confidence} />
            </TableCell>
            <TableCell>
              {cell(line.lineNo, "product_code", line.productCode)}
            </TableCell>
            <TableCell>{line.description ?? ""}</TableCell>
            <TableCell className="numeric text-right">
              {cell(line.lineNo, "quantity", line.quantity)}
            </TableCell>
            <TableCell className="numeric text-right">
              {cell(line.lineNo, "unit_price", line.unitPrice)}
            </TableCell>
            <TableCell className="numeric text-right">
              {cell(line.lineNo, "amount", line.amount)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
