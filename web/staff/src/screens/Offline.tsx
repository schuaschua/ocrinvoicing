import { Button } from "@/components/ui/button";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/**
 * EXPERIENCE.md State Patterns "Database stopped" (UX-DR20): the full-page notice when
 * the API answers 503 `DB_OFFLINE` (AD-12), with the working hours. The shell's alert
 * holds the words; `heading` names the page (the goods-in scan has its own).
 */
export function Offline({
  onRetry,
  heading: title = strings.offlineHeading,
}: {
  onRetry: () => void;
  heading?: string;
}) {
  const heading = usePageHeading(pageTitle(title));
  return (
    <div className="flex max-w-prose flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      <div>
        <Button type="button" variant="outline" onClick={onRetry}>
          {strings.errors.tryAgain}
        </Button>
      </div>
    </div>
  );
}
