import { useState } from "react";

import {
  duplicateImageUrl,
  itemImageUrl,
  type AdminItem,
  type DuplicateOf,
} from "@/api/item";
import { Button } from "@/components/ui/button";
import { amountText, dateTimeText } from "@/lib/format";
import { strings } from "@/strings";

interface Side {
  heading: string;
  receivedAt: string;
  supplierName: string | null;
  invoiceTotal: string | null;
  currency: string | null;
  contentType: string;
  imageAvailable: boolean;
  imageUrl: string;
}

function Picture({ side }: { side: Side }) {
  const v = strings.item.viewer;
  const [failed, setFailed] = useState(false);
  if (!side.imageAvailable) return <p>{v.deleted}</p>;
  if (side.contentType === "application/pdf") {
    return (
      <Button asChild variant="outline" className="self-start">
        <a href={side.imageUrl} target="_blank" rel="noopener noreferrer">
          {v.openPdf}
        </a>
      </Button>
    );
  }
  if (failed) return <p>{v.failed}</p>;
  return (
    <img
      src={side.imageUrl}
      alt={strings.item.duplicate.imageAlt(side.heading)}
      className="max-h-80 w-full rounded-md border object-contain"
      onError={() => setFailed(true)}
    />
  );
}

function Column({ side }: { side: Side }) {
  const d = strings.item.duplicate;
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h3 className="text-sm font-semibold">{side.heading}</h3>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt className="text-sm">{d.received}</dt>
        <dd className="numeric">{dateTimeText(side.receivedAt)}</dd>
        <dt className="text-sm">{d.supplier}</dt>
        <dd className="break-words">
          {side.supplierName ?? strings.queue.unknownSupplier}
        </dd>
        <dt className="text-sm">{d.total}</dt>
        <dd className="numeric">
          {amountText(side.invoiceTotal, side.currency)}
        </dd>
      </dl>
      <Picture side={side} />
    </div>
  );
}

/**
 * Story 3.3, EXPERIENCE.md "Allowed actions by reason": a possible duplicate shows the
 * earlier invoice it matches side by side with this one (received, supplier, total and
 * image), so the admin can Approve it as not a duplicate or Reject it. The matching
 * image is served only while the `DUPLICATE` is open; once deleted, a placeholder.
 * Without the matching invoice (a bad detail, or its row is gone) the panel still
 * flags the duplicate and says so.
 */
export function DuplicatePanel({
  item,
  duplicate,
}: {
  item: AdminItem;
  duplicate: DuplicateOf | null;
}) {
  const d = strings.item.duplicate;
  if (duplicate === null) {
    return (
      <section
        aria-labelledby="duplicate-heading"
        className="flex flex-col gap-3 rounded-md border p-4"
      >
        <h2 id="duplicate-heading" className="text-lg font-semibold">
          {d.heading}
        </h2>
        <p>{d.unavailable}</p>
      </section>
    );
  }
  const total = item.fields.find((f) => f.fieldId === "invoice_total");
  const sides: Side[] = [
    {
      heading: d.thisInvoice,
      receivedAt: item.receivedAt,
      supplierName: item.supplierName,
      invoiceTotal: total?.value ?? null,
      currency: total?.currency ?? null,
      contentType: item.contentType,
      imageAvailable: item.imageAvailable,
      imageUrl: itemImageUrl(item.invoiceId),
    },
    {
      heading: d.matching,
      receivedAt: duplicate.receivedAt,
      supplierName: duplicate.supplierName,
      invoiceTotal: duplicate.invoiceTotal,
      currency: duplicate.currency,
      contentType: duplicate.contentType,
      imageAvailable: duplicate.imageAvailable,
      imageUrl: duplicateImageUrl(item.invoiceId),
    },
  ];
  return (
    <section
      aria-labelledby="duplicate-heading"
      className="flex flex-col gap-3 rounded-md border p-4"
    >
      <h2 id="duplicate-heading" className="text-lg font-semibold">
        {d.heading}
      </h2>
      <p>{d.intro}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {sides.map((side) => (
          <Column key={side.heading} side={side} />
        ))}
      </div>
    </section>
  );
}
