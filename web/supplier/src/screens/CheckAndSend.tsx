import { type ChangeEvent, useEffect, useRef, useState } from "react";

import { type PhotoProblem, THRESHOLDS } from "@shared/quality/check";

import { ApiError } from "@/api";
import { uploadInvoice } from "@/api/upload";
import { Button } from "@/components/ui/button";
import { type DeviceCheck, canCheck, checkFile } from "@/deviceCheck";
import { fileSize, strings } from "@/strings";
import {
  CHOOSE_FILE_ACCEPT,
  TAKE_PHOTO_ACCEPT,
  isPdf,
  refusal,
} from "@/upload";

import { CAPTURE, type CaptureSource } from "./capture";
import { usePageHeading } from "./usePageHeading";

type Phase =
  | { kind: "checking" }
  | { kind: "ready" }
  | { kind: "photo-problem"; message: string }
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

/** The failure copy: the exact problem, and the side as the supplier sees the photo. */
function problemMessage(problem: PhotoProblem): string {
  if (problem.kind === "dark") return strings.checkAndSend.tooDark;
  if (problem.kind === "blurry") return strings.checkAndSend.blurry;
  return strings.checkAndSend.cutOff(problem.side);
}

/**
 * EXPERIENCE.md "Check & send": what was chosen, the device check (Story 1.9), and
 * Send. A photo is checked first ("Checking photo…", `role="status"`); a failure names
 * the problem (`role="alert"`) and offers Take again, which reopens the camera or
 * picker the photo came from. From the 2nd failed check of the same upload
 * (`previousFailures` counts the earlier ones), Send it anyway sends the photo marked
 * `overridden`. A PDF of more than 2 pages is refused here; any other PDF is sent. A
 * file the page can't check (no decoder, a failed decode, the time cap, a PDF whose
 * pages can't be counted) is sent marked `skipped` (AD-5); one that passed, `passed`.
 *
 * While sending, a progress bar and "Sending…" (`role="status"`), Send disabled, and
 * leaving the page asks for confirmation. A failed send keeps the file and says so
 * (`role="alert"`); Send again reuses `uploadKey` and the same device check, so it can
 * never make a second invoice (AD-6).
 */
export function CheckAndSend({
  file,
  uploadKey,
  source,
  previousFailures,
  onSent,
  onLinkNotWorking,
  onChooseAgain,
  onRetake,
}: {
  file: File;
  uploadKey: string;
  source: CaptureSource;
  previousFailures: number;
  onSent: (reference: string) => void;
  onLinkNotWorking: () => void;
  onChooseAgain: () => void;
  onRetake: (file: File) => void;
}) {
  const heading = usePageHeading(strings.checkAndSend.pageTitle);
  const [checkable] = useState(() => canCheck(file));
  const [phase, setPhase] = useState<Phase>(() =>
    checkable ? { kind: "checking" } : { kind: "ready" },
  );
  // Whether the check couldn't run on this device: then the file is sent "skipped".
  const [skipped, setSkipped] = useState(!checkable);
  const sending = phase.kind === "sending";
  const controller = useRef<AbortController | null>(null);
  // Set synchronously, so a second tap before the re-render sends nothing.
  const inFlight = useRef(false);
  // Set by Send it anyway: a retry after a failed send stays "overridden", and Take
  // again stays on offer.
  const [overridden, setOverridden] = useState(false);
  const retakeInput = useRef<HTMLInputElement>(null);
  const pdf = isPdf(file);

  // The device check, once per file (the screen is remounted for a retaken photo).
  const checking = phase.kind === "checking";
  useEffect(() => {
    if (!checking) return;
    let current = true;
    void checkFile(file).then((result) => {
      if (!current) return;
      if (result.kind === "passed") setPhase({ kind: "ready" });
      else if (result.kind === "skipped") {
        setSkipped(true);
        setPhase({ kind: "ready" });
      } else if (result.kind === "too-many-pages") {
        setPhase({
          kind: "refused",
          message: strings.checkAndSend.tooManyPages,
        });
      } else {
        setPhase({
          kind: "photo-problem",
          message: problemMessage(result.problem),
        });
      }
    });
    return () => {
      current = false;
    };
  }, [checking, file]);

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

  async function send(deviceCheck: DeviceCheck) {
    if (inFlight.current) return;
    inFlight.current = true;
    const current = new AbortController();
    controller.current = current;
    setPhase({ kind: "sending", progress: 0 });
    try {
      const result = await uploadInvoice(file, uploadKey, {
        signal: current.signal,
        deviceCheck,
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

  function sendAnyway() {
    setOverridden(true);
    void send("overridden");
  }

  function retaken(event: ChangeEvent<HTMLInputElement>) {
    const retake = event.target.files?.[0];
    // Cleared, so choosing the same file again still counts as a choice.
    event.target.value = "";
    if (!retake) return;
    const reason = refusal(retake);
    if (reason !== null) {
      setPhase({ kind: "refused", message: reason });
      return;
    }
    onRetake(retake);
  }

  const failures = previousFailures + (phase.kind === "photo-problem" ? 1 : 0);
  const offerSendAnyway =
    phase.kind === "photo-problem" &&
    failures >= THRESHOLDS.maxFailuresBeforeSendAnyway;
  const canSend = phase.kind === "ready" || phase.kind === "failed" || sending;
  // The photo stays retakeable after a failed check, and after a failed send of a
  // photo sent anyway (then beside Send, as the secondary action).
  const offerRetake =
    phase.kind === "photo-problem" || (phase.kind === "failed" && overridden);
  const status = sending
    ? strings.checkAndSend.sending
    : checking
      ? pdf
        ? strings.checkAndSend.checkingPdf
        : strings.checkAndSend.checking
      : "";

  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {strings.checkAndSend.heading}
      </h1>
      <p className="break-words">
        {pdf ? strings.checkAndSend.pdf : strings.checkAndSend.photo}:{" "}
        <span className="font-medium">{file.name}</span>{" "}
        <span className="numeric text-muted-foreground">
          ({fileSize(file.size)})
        </span>
      </p>
      <div className="flex flex-col gap-2">
        {/* Present from the start and holding only this text, so "Checking…" and
            "Sending…" are each announced once; the end is announced by the alert
            below or by Received. Progress updates stay out of the live region. */}
        <p role="status">{status}</p>
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
        {(phase.kind === "refused" || phase.kind === "photo-problem") &&
          phase.message}
      </p>
      <div className="mt-auto flex flex-col gap-3">
        {canSend && (
          <Button
            type="button"
            className={CAPTURE}
            data-capture
            disabled={sending}
            onClick={() =>
              void send(
                overridden ? "overridden" : skipped ? "skipped" : "passed",
              )
            }
          >
            {strings.checkAndSend.send}
          </Button>
        )}
        {offerRetake && (
          <>
            <Button
              // A new element when its style changes, so its colours don't animate.
              key={canSend ? "secondary" : "primary"}
              type="button"
              variant={canSend ? "outline" : "default"}
              className={CAPTURE}
              data-capture
              onClick={() => retakeInput.current?.click()}
            >
              {strings.checkAndSend.takeAgain}
            </Button>
            {offerSendAnyway && (
              <Button
                type="button"
                variant="outline"
                className={CAPTURE}
                data-capture
                onClick={sendAnyway}
              >
                {strings.checkAndSend.sendAnyway}
              </Button>
            )}
            <input
              ref={retakeInput}
              type="file"
              accept={
                source === "camera" ? TAKE_PHOTO_ACCEPT : CHOOSE_FILE_ACCEPT
              }
              capture={source === "camera" ? "environment" : undefined}
              hidden
              tabIndex={-1}
              data-testid="take-again-input"
              onChange={retaken}
            />
          </>
        )}
        {!sending && (
          <Button
            // A new element when it becomes the primary action, so its colours
            // don't animate from the outline style (transition-all).
            key={phase.kind === "refused" ? "primary" : "secondary"}
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
