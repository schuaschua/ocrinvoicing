import { useEffect, useState } from "react";

import { ApiError, setUploadToken } from "@/api";
import { getLink } from "@/api/link";
import { LinkError } from "@/screens/LinkError";
import { LinkNotWorking } from "@/screens/LinkNotWorking";
import { Loading } from "@/screens/Loading";
import { UploadHome } from "@/screens/UploadHome";
import { strings } from "@/strings";

type Screen =
  | { kind: "loading" }
  | { kind: "home"; supplierName: string }
  | { kind: "link-not-working" }
  | { kind: "error"; message: string };

function afterFailure(error: unknown): Screen {
  // 401 is the server's one answer for a missing, malformed, unknown or revoked link.
  if (error instanceof ApiError && error.status === 401) {
    return { kind: "link-not-working" };
  }
  const offline = error instanceof ApiError && error.status === 0;
  return {
    kind: "error",
    message: offline ? strings.errors.network : strings.errors.generic,
  };
}

/**
 * The supplier page: the "Babaloo" text header (DESIGN.md: no logo) and one screen in a
 * single column. `token` is the link's token from the URL fragment, or null.
 */
export function App({ token }: { token: string | null }) {
  const [screen, setScreen] = useState<Screen>(
    token === null ? { kind: "link-not-working" } : { kind: "loading" },
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // No token: Link not working, and no call to the server.
    if (token === null) return;
    setUploadToken(token);
    const controller = new AbortController();
    let cancelled = false;
    getLink(controller.signal).then(
      (link) => {
        if (!cancelled) {
          setScreen({ kind: "home", supplierName: link.supplier_name });
        }
      },
      (error: unknown) => {
        // Only the effect's own cleanup is ignored; a timeout is a failure to show.
        if (cancelled) return;
        const next = afterFailure(error);
        // The server refused this token: stop sending it.
        if (next.kind === "link-not-working") setUploadToken(null);
        setScreen(next);
      },
    );
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [token, attempt]);

  function retry() {
    setScreen({ kind: "loading" });
    setAttempt((n) => n + 1);
  }

  return (
    <div className="flex min-h-dvh flex-col text-body-supplier">
      <header className="sticky top-0 z-10 flex h-header items-center border-b bg-background px-supplier-gutter">
        <p className="text-lg font-semibold">{strings.appName}</p>
      </header>
      <main id="main" className="flex flex-1 flex-col px-supplier-gutter py-4">
        {screen.kind === "loading" && <Loading />}
        {screen.kind === "home" && (
          <UploadHome supplierName={screen.supplierName} />
        )}
        {screen.kind === "link-not-working" && <LinkNotWorking />}
        {screen.kind === "error" && (
          <LinkError message={screen.message} onRetry={retry} />
        )}
      </main>
    </div>
  );
}
