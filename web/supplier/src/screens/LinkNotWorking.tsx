import { strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/**
 * EXPERIENCE.md "Link not working" (UX-DR7): the same page for a missing, revoked or
 * unknown link. It reveals nothing else.
 */
export function LinkNotWorking() {
  const heading = usePageHeading(strings.linkNotWorking.pageTitle);
  return (
    <div className="flex flex-col gap-2">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {strings.linkNotWorking.heading}
      </h1>
      <p>{strings.linkNotWorking.body}</p>
    </div>
  );
}
