import { useEffect, useState } from "react";

import { OFFLINE, SESSION_EXPIRED, onApiEvent } from "@/api";
import { strings } from "@/strings";

/**
 * The staff app shell: the "Babaloo" text header (DESIGN.md: no logo), the content
 * area, and the notices the API client raises (UX-DR3, EXPERIENCE.md State Patterns).
 * The role sidebar, the sign-in dialog and screens arrive with their stories.
 */
export function App() {
  const [sessionExpired, setSessionExpired] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    const stopExpired = onApiEvent(SESSION_EXPIRED, () =>
      setSessionExpired(true),
    );
    const stopOffline = onApiEvent(OFFLINE, () => setOffline(true));
    return () => {
      stopExpired();
      stopOffline();
    };
  }, []);

  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-10 flex h-header items-center border-b bg-background px-4">
        <p className="text-lg font-semibold">{strings.appName}</p>
      </header>
      {/* Live regions stay in the page so screen readers announce their new text (4.1.3). */}
      <div role="alert" className="px-4">
        {sessionExpired ? (
          <p className="py-2">{strings.sessionExpired}</p>
        ) : null}
      </div>
      <div role="status" className="px-4">
        {offline ? <p className="py-2">{strings.offline}</p> : null}
      </div>
      <main id="main" className="p-4" />
    </div>
  );
}
