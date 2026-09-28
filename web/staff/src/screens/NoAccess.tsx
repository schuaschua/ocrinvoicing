import { pageTitle, strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

/** Signed in with no app role: nothing to show, and no sidebar (Story 2.7). */
export function NoAccess() {
  const heading = usePageHeading(pageTitle(strings.noAccess.heading));
  return (
    <div className="flex max-w-prose flex-col gap-2">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {strings.noAccess.heading}
      </h1>
      <p>{strings.noAccess.body}</p>
    </div>
  );
}
