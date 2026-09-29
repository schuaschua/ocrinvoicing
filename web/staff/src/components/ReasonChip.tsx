import { Badge } from "@/components/ui/badge";
import { reasonLabels, strings, type ReasonCode } from "@/strings";

/** DESIGN.md: these chips block payment, so they are destructive and carry an icon. */
const BLOCKING: ReadonlySet<string> = new Set<ReasonCode>([
  "BANK_CHANGED",
  "SUPPLIER_ID_MISMATCH",
]);

/** The plain-language label of a reason code; a code this build doesn't know reads "Needs a look". */
export function reasonLabel(code: string): string {
  return code in reasonLabels
    ? reasonLabels[code as ReasonCode]
    : strings.queue.otherReason;
}

function WarningIcon() {
  return (
    <svg
      viewBox="0 0 16 16"
      aria-hidden="true"
      focusable="false"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 1.75 15 14.25H1L8 1.75Z" />
      <path d="M8 6.5v3.25M8 12h.01" />
    </svg>
  );
}

/** One admin-queue reason (DESIGN.md Reason chip), labelled, never the code. */
export function ReasonChip({ code }: { code: string }) {
  const blocking = BLOCKING.has(code);
  return (
    <Badge
      variant={blocking ? "destructive" : "secondary"}
      className="rounded-full"
    >
      {blocking ? <WarningIcon /> : null}
      {blocking ? (
        <span className="sr-only">{`${strings.queue.blocking}: `}</span>
      ) : null}
      {reasonLabel(code)}
    </Badge>
  );
}
