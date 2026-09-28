import { Button } from "@/components/ui/button";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/**
 * EXPERIENCE.md State Patterns "Database stopped" (UX-DR20): the full-page notice when
 * the API answers 503 `DB_OFFLINE` (AD-12), with the working hours.
 */
export function Offline({ onRetry }: { onRetry: () => void }) {
  const heading = usePageHeading(pageTitle(strings.offlineHeading));
  return (
    <div className="flex max-w-prose flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {strings.offlineHeading}
      </h1>
      <div>
        <Button type="button" variant="outline" onClick={onRetry}>
          {strings.errors.tryAgain}
        </Button>
      </div>
    </div>
  );
}
