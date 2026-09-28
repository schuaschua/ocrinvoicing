import { useEffect, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/** After this long, the page says the app is waking up (UX-DR20). */
export const WAKING_UP_AFTER_MS = 3000;

/** Skeleton rows while the link is checked; after 3 s, "Waking up, one moment…". */
export function Loading() {
  const heading = usePageHeading(strings.loading.pageTitle);
  const [wakingUp, setWakingUp] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(
      () => setWakingUp(true),
      WAKING_UP_AFTER_MS,
    );
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="flex flex-1 flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="sr-only">
        {strings.loading.label}
      </h1>
      <div
        aria-hidden="true"
        aria-busy="true"
        data-testid="skeleton"
        className="flex flex-1 flex-col gap-4"
      >
        <Skeleton className="h-8 w-3/4" />
        <div className="mt-auto flex flex-col gap-3">
          <Skeleton className="h-capture w-full" />
          <Skeleton className="h-capture w-full" />
        </div>
      </div>
      {/* Outside the busy skeleton, and present from the start, so it is announced. */}
      <p role="status" className="min-h-6">
        {wakingUp ? strings.loading.wakingUp : ""}
      </p>
    </div>
  );
}
