import { Button } from "@/components/ui/button";
import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/**
 * The link couldn't be checked (network, timeout or a server outage): a retryable
 * error, never Link not working, and never the server's own message (EXPERIENCE.md: no
 * exception messages to suppliers). Focus moves to the heading, which announces the
 * message once; there is no separate alert region to read it a second time.
 */
export function LinkError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  const heading = usePageHeading(pageTitle(message));
  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl">
        {message}
      </h1>
      <Button
        type="button"
        className="mt-auto h-auto min-h-capture w-full text-base"
        onClick={onRetry}
      >
        {strings.errors.tryAgain}
      </Button>
    </div>
  );
}
