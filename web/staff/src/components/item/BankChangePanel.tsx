import type { BankChange } from "@/api/item";
import { strings } from "@/strings";

import { fieldLabel } from "./boxes";
import { MaskedValue } from "./MaskedValue";

interface BankChangePanelProps {
  invoiceId: string;
  phone: string | null;
  changes: BankChange[];
  announce: (message: string) => void;
}

/**
 * EXPERIENCE.md Bank-change panel (UX-DR13, AD-19): the supplier's phone number on file
 * to call back, and for each changed bank field the value on file (or "No account on
 * file") and the new one, both masked with Show. The call-back checklist and Approve
 * are Story 3.3's.
 */
export function BankChangePanel({
  invoiceId,
  phone,
  changes,
  announce,
}: BankChangePanelProps) {
  const b = strings.item.bank;
  return (
    <section
      aria-labelledby="bank-change-heading"
      className="flex flex-col gap-3 rounded-md border border-destructive p-4"
    >
      <h2 id="bank-change-heading" className="text-lg font-semibold">
        {b.heading}
      </h2>
      <p className="font-medium">{phone ? b.call(phone) : b.noPhone}</p>
      {changes.map((change) => (
        <div key={change.fieldId} className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">
            {fieldLabel(change.fieldId)}
          </h3>
          <dl className="grid gap-2 sm:grid-cols-[auto_1fr] sm:items-center">
            <dt className="text-sm">{b.onFile}</dt>
            <dd>
              {change.onFile === null ? (
                b.noAccount
              ) : (
                <MaskedValue
                  invoiceId={invoiceId}
                  fieldId={change.fieldId}
                  which="on_file"
                  digits={change.onFile}
                  announce={announce}
                />
              )}
            </dd>
            <dt className="text-sm">{b.onInvoice}</dt>
            <dd>
              {change.newValue === null ? (
                b.notRead
              ) : (
                <MaskedValue
                  invoiceId={invoiceId}
                  fieldId={change.fieldId}
                  which="new"
                  digits={change.newValue}
                  announce={announce}
                />
              )}
            </dd>
          </dl>
        </div>
      ))}
    </section>
  );
}
