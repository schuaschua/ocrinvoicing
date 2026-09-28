import { useEffect, useRef, useState } from "react";

import { ApiError } from "@/api";
import { uploadInvoice } from "@/api/upload";
import { Button } from "@/components/ui/button";
import { fileSize, strings } from "@/strings";
import { isPdf } from "@/upload";

import { CAPTURE } from "./capture";
import { usePageHeading } from "./usePageHeading";

type Phase =
  | { kind: "ready" }
  | { kind: "sending"; progress: number }
  | { kind: "failed" }
  | { kind: "refused"; message: string };

/** What the page says about an upload the server refused (never the server's own words). */
function refusedMessage(error: ApiError): string | null {
  if (error.status === 413) return strings.fileRefused.tooLarge;
  if (error.status === 415) return strings.fileRefused.wrongType;
  // The page always sends a well-formed key, so a 400 is the empty-body refusal.
  if (error.status === 400) return strings.fileRefused.empty;
  // The key is held by another upload: a new choice makes a new key.
  if (error.status === 409) return strings.errors.generic;
  return null;
}

/**
 * EXPERIENCE.md "Check & send": what was chosen, and Send. While sending, a progress
 * bar and "Sending…" (`role="status"`), Send disabled, and leaving the page asks for
 * confirmation. A failed send keeps the file and says so (`role="alert"`); Send again
 * reuses `uploadKey`, so it can never make a second invoice (AD-6).
 *
 * Story 1.9 adds the on-device photo check here.
 */
export function CheckAndSend({
  file,
  uploadKey,
  onSent,
  onLinkNotWorking,
  onChooseAgain,
}: {
  file: File;
  uploadKey: string;
  onSent: (reference: string) => void;
  onLinkNotWorking: () => void;
  onChooseAgain: () => void;
}) {
  const heading = usePageHeading(strings.checkAndSend.pageTitle);
  const [phase, setPhase] = useState<Phase>({ kind: "ready" });
  const sending = phase.kind === "sending";
  const controller = useRef<AbortController | null>(null);
  // Set synchronously, so a second tap before the re-render sends nothing.
  const inFlight = useRef(false);

  // Leaving mid-upload asks first; the browser shows its own wording.
  useEffect(() => {
    if (!sending) return;
    const confirmLeave = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", confirmLeave);
    return () => window.removeEventListener("beforeunload", confirmLeave);
  }, [sending]);

  // Unmounting (never during a send, but safe) stops the request.
  useEffect(() => () => controller.current?.abort(), []);

  async function send() {
    if (inFlight.current) return;
    inFlight.current = true;
    const current = new AbortController();
    controller.current = current;
    setPhase({ kind: "sending", progress: 0 });
    try {
      const result = await uploadInvoice(file, uploadKey, {
        signal: current.signal,
        onProgress: (progress) => {
          if (!current.signal.aborted) setPhase({ kind: "sending", progress });
        },
      });
      if (current.signal.aborted) return;
      onSent(result.reference);
    } catch (error: unknown) {
      if (current.signal.aborted) return;
      if (error instanceof ApiError && error.status === 401) {
        onLinkNotWorking();
        return;
      }
      const message = error instanceof ApiError ? refusedMessage(error) : null;
      setPhase(
        message === null ? { kind: "failed" } : { kind: "refused", message },
      );
    } finally {
      inFlight.current = false;
    }
  }

  const kind = isPdf(file)
    ? strings.checkAndSend.pdf
    : strings.checkAndSend.photo;

  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {strings.checkAndSend.heading}
      </h1>
      <p className="break-words">
        {kind}: <span className="font-medium">{file.name}</span>{" "}
        <span className="numeric text-muted-foreground">
          ({fileSize(file.size)})
        </span>
      </p>
      <div className="flex flex-col gap-2">
        {/* Present from the start and holding only this text, so "Sending…" is
            announced once when a send starts; the end is announced by the alert
            below or by Received. Progress updates stay out of the live region. */}
        <p role="status">{sending ? strings.checkAndSend.sending : ""}</p>
        {sending && (
          <progress
            className="h-2 w-full accent-primary"
            aria-label={strings.checkAndSend.progressLabel}
            max={1}
            value={phase.progress}
          />
        )}
      </div>
      <p role="alert">
        {phase.kind === "failed" && strings.checkAndSend.failed}
        {phase.kind === "refused" && phase.message}
      </p>
      <div className="mt-auto flex flex-col gap-3">
        {phase.kind !== "refused" && (
          <Button
            type="button"
            className={CAPTURE}
            data-capture
            disabled={sending}
            onClick={() => void send()}
          >
            {strings.checkAndSend.send}
          </Button>
        )}
        {!sending && (
          <Button
            type="button"
            variant={phase.kind === "refused" ? "default" : "outline"}
            className={CAPTURE}
            data-capture
            onClick={onChooseAgain}
          >
            {strings.checkAndSend.chooseAgain}
          </Button>
        )}
      </div>
    </div>
  );
}
