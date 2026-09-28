import { useEffect, useRef, useState } from "react";

import { ApiError, setUploadToken } from "@/api";
import { getLink } from "@/api/link";
import { CheckAndSend } from "@/screens/CheckAndSend";
import { LinkError } from "@/screens/LinkError";
import { LinkNotWorking } from "@/screens/LinkNotWorking";
import { Loading } from "@/screens/Loading";
import { Received } from "@/screens/Received";
import { UploadHome } from "@/screens/UploadHome";
import { strings } from "@/strings";
import { newUploadKey } from "@/upload";

type Screen =
  | { kind: "loading" }
  | { kind: "home"; supplierName: string }
  // One key per file, kept for every retry of that file (AD-6).
  | { kind: "check"; supplierName: string; file: File; uploadKey: string }
  | { kind: "received"; supplierName: string; reference: string }
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
  // One upload key per file for the whole visit (AD-6): choosing the same file again,
  // for example after "Couldn't send", reuses its key, so it can't become a second
  // invoice. A file is known by its name, size and last-modified time.
  const uploadKeys = useRef(new Map<string, string>());

  function keyFor(file: File): string {
    const identity = JSON.stringify([file.name, file.size, file.lastModified]);
    let key = uploadKeys.current.get(identity);
    if (key === undefined) {
      key = newUploadKey();
      uploadKeys.current.set(identity, key);
    }
    return key;
  }

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

  function linkNotWorking() {
    // The server refused this token: stop sending it.
    setUploadToken(null);
    setScreen({ kind: "link-not-working" });
  }

  return (
    <div className="flex min-h-dvh flex-col text-body-supplier">
      <header className="sticky top-0 z-10 flex h-header items-center border-b bg-background px-supplier-gutter">
        <p className="text-lg font-semibold">{strings.appName}</p>
      </header>
      <main id="main" className="flex flex-1 flex-col px-supplier-gutter py-4">
        {screen.kind === "loading" && <Loading />}
        {screen.kind === "home" && (
          <UploadHome
            supplierName={screen.supplierName}
            onFile={(file) =>
              setScreen({
                kind: "check",
                supplierName: screen.supplierName,
                file,
                uploadKey: keyFor(file),
              })
            }
          />
        )}
        {screen.kind === "check" && (
          <CheckAndSend
            file={screen.file}
            uploadKey={screen.uploadKey}
            onSent={(reference) =>
              setScreen({
                kind: "received",
                supplierName: screen.supplierName,
                reference,
              })
            }
            onLinkNotWorking={linkNotWorking}
            onChooseAgain={() =>
              setScreen({ kind: "home", supplierName: screen.supplierName })
            }
          />
        )}
        {screen.kind === "received" && (
          <Received
            reference={screen.reference}
            onUploadAnother={() =>
              setScreen({ kind: "home", supplierName: screen.supplierName })
            }
          />
        )}
        {screen.kind === "link-not-working" && <LinkNotWorking />}
        {screen.kind === "error" && (
          <LinkError message={screen.message} onRetry={retry} />
        )}
      </main>
    </div>
  );
}
