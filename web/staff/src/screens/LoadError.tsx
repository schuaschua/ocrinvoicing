import { Button } from "@/components/ui/button";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/** The sign-in check failed for another reason (network, timeout, a server error). */
export function LoadError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  const heading = usePageHeading(pageTitle(message));
  return (
    <div className="flex max-w-prose flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl">
        {message}
      </h1>
      <div>
        <Button type="button" onClick={onRetry}>
          {strings.errors.tryAgain}
        </Button>
      </div>
    </div>
  );
}
