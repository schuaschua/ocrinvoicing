import {
  type ChangeEvent,
  type FormEvent,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { type PhotoProblem, THRESHOLDS } from "@shared/quality/check";

import { ApiError } from "@/api";
import {
  type DeliveryList,
  type DeliveryRow,
  listDeliveries,
} from "@/api/goodsIn";
import { uploadGoodsIn } from "@/api/upload";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { type DeviceCheck, canCheck, checkFile } from "@/deviceCheck";
import { fileSize, pageTitle, poLabel, strings } from "@/strings";
import {
  CHOOSE_FILE_ACCEPT,
  TAKE_PHOTO_ACCEPT,
  cameraAvailable,
  isPdf,
  newUploadKey,
  refusal,
} from "@/upload";

import { CAPTURE, type CaptureSource } from "./capture";
import { usePageHeading } from "./usePageHeading";

const s = strings.goodsIn;
const MIN_SEARCH = 2;

/** Whether an API failure is the shell's to show (session ended, database stopped). */
function shells(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 401 || error.code === "DB_OFFLINE")
  );
}

function supplierOf(delivery: DeliveryRow): string {
  return delivery.supplierName ?? s.unknownSupplier;
}

type Step =
  // `notice`: why the picker is shown again (a delivery that has gone).
  | { kind: "pick"; notice?: string }
  | { kind: "capture"; delivery: DeliveryRow }
  | {
      kind: "check";
      delivery: DeliveryRow;
      file: File;
      uploadKey: string;
      source: CaptureSource;
      failures: number;
    }
  | { kind: "received"; po: string; supplier: string };

/**
 * Goods-in scan (Story 4.1, EXPERIENCE.md Flow 4): pick a delivery (today's first, or
 * a search by PO number or supplier for a late one), photograph its paper invoice,
 * let the device check it (Story 1.9), and send it against that delivery. The
 * supplier is always the delivery's, decided by the server (AD-5). Supplier-page
 * layout: one column, 48px targets, 56px capture buttons.
 */
export function GoodsInScreen() {
  const [step, setStep] = useState<Step>({ kind: "pick" });
  // One upload key per delivery and file for the whole visit (AD-6): choosing the
  // same file again after "Couldn't send" reuses its key, so it can't become a second
  // invoice. A file is known by its name, size and last-modified time.
  const uploadKeys = useRef(new Map<string, string>());

  function keyFor(delivery: DeliveryRow, file: File): string {
    const identity = JSON.stringify([
      delivery.deliveryId,
      file.name,
      file.size,
      file.lastModified,
    ]);
    let key = uploadKeys.current.get(identity);
    if (key === undefined) {
      key = newUploadKey();
      uploadKeys.current.set(identity, key);
    }
    return key;
  }

  return (
    <div className="flex w-full max-w-xl flex-1 flex-col text-body-supplier">
      {step.kind === "pick" && (
        <DeliveryPicker
          notice={step.notice ?? null}
          onPick={(delivery) => setStep({ kind: "capture", delivery })}
        />
      )}
      {step.kind === "capture" && (
        <Capture
          delivery={step.delivery}
          onFile={(file, source) =>
            setStep({
              kind: "check",
              delivery: step.delivery,
              file,
              uploadKey: keyFor(step.delivery, file),
              source,
              failures: 0,
            })
          }
          onBack={() => setStep({ kind: "pick" })}
        />
      )}
      {step.kind === "check" && (
        <CheckAndSend
          // A retaken photo is checked afresh, on a fresh screen.
          key={step.failures}
          delivery={step.delivery}
          file={step.file}
          uploadKey={step.uploadKey}
          source={step.source}
          previousFailures={step.failures}
          onSent={(po, supplier) => setStep({ kind: "received", po, supplier })}
          onChooseAgain={() =>
            setStep({ kind: "capture", delivery: step.delivery })
          }
          onDeliveryGone={() =>
            setStep({ kind: "pick", notice: s.deliveryGone })
          }
          onRetake={(file) =>
            setStep({
              ...step,
              file,
              uploadKey: keyFor(step.delivery, file),
              failures: step.failures + 1,
            })
          }
        />
      )}
      {step.kind === "received" && (
        <Received
          po={step.po}
          supplier={step.supplier}
          onScanAnother={() => setStep({ kind: "pick" })}
        />
      )}
    </div>
  );
}

type ListState =
  | { kind: "loading" }
  | { kind: "ready"; list: DeliveryList }
  | { kind: "error"; message: string };

/** EXPERIENCE.md "Delivery picker": today's deliveries first, plus a search. */
function DeliveryPicker({
  notice: initialNotice,
  onPick,
}: {
  notice: string | null;
  onPick: (delivery: DeliveryRow) => void;
}) {
  const title = strings.surfaces.goods_in_scan;
  const heading = usePageHeading(pageTitle(title));
  const ids = { search: useId(), hint: useId(), list: useId() };
  const [text, setText] = useState("");
  // null: today's deliveries; a string: the applied search.
  const [search, setSearch] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(initialNotice);
  const [result, setResult] = useState<{
    search: string | null;
    state: ListState;
  } | null>(null);
  const state: ListState =
    result !== null && result.search === search
      ? result.state
      : { kind: "loading" };

  useEffect(() => {
    const controller = new AbortController();
    listDeliveries(search, controller.signal).then(
      (list) => setResult({ search, state: { kind: "ready", list } }),
      (error: unknown) => {
        if (controller.signal.aborted || shells(error)) return;
        const message =
          error instanceof ApiError && error.status === 400
            ? s.badSearch
            : error instanceof ApiError && error.status === 0
              ? strings.errors.network
              : strings.errors.generic;
        setResult({ search, state: { kind: "error", message } });
      },
    );
    return () => controller.abort();
  }, [search]);

  function onSearch(event: FormEvent) {
    event.preventDefault();
    const wanted = text.trim();
    if (wanted.length < MIN_SEARCH) {
      setNotice(s.badSearch);
      return;
    }
    setNotice(null);
    setSearch(wanted);
  }

  function showToday() {
    setText("");
    setNotice(null);
    setSearch(null);
  }

  const items = state.kind === "ready" ? state.list.items : [];
  return (
    <div className="flex flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      <form
        role="search"
        className="flex flex-col gap-2"
        onSubmit={onSearch}
        noValidate
      >
        <label htmlFor={ids.search} className="font-medium">
          {s.searchLabel}
        </label>
        <input
          id={ids.search}
          type="search"
          value={text}
          aria-describedby={ids.hint}
          onChange={(event) => setText(event.target.value)}
          className="min-h-tap-min w-full rounded-md border bg-background px-3"
        />
        <p id={ids.hint} className="text-muted-foreground">
          {s.searchHint}
        </p>
        <Button type="submit" className={CAPTURE} data-capture>
          {s.search}
        </Button>
        {search !== null && (
          <Button
            type="button"
            variant="outline"
            className={CAPTURE}
            data-capture
            onClick={showToday}
          >
            {s.showToday}
          </Button>
        )}
      </form>
      {/* Present from the start, so a refused search is announced. */}
      {state.kind === "error" || notice !== null ? (
        <p role="alert">{state.kind === "error" ? state.message : notice}</p>
      ) : null}
      <section aria-labelledby={ids.list} className="flex flex-col gap-3">
        <h2 id={ids.list} className="text-lg font-semibold">
          {search === null ? s.today : s.results}
        </h2>
        {state.kind === "loading" && (
          <div aria-hidden="true" className="flex flex-col gap-3">
            {[0, 1, 2].map((n) => (
              <Skeleton key={n} className="h-capture w-full" />
            ))}
          </div>
        )}
        {state.kind === "ready" && items.length === 0 && (
          <p>{search === null ? s.noneToday : s.noMatch}</p>
        )}
        {items.length > 0 && (
          <ul aria-label={s.listLabel} className="flex flex-col gap-3">
            {items.map((delivery) => (
              <li key={delivery.deliveryId}>
                <Button
                  type="button"
                  variant="outline"
                  className={`${CAPTURE} flex-col items-start gap-1 py-2 text-left`}
                  data-capture
                  onClick={() => onPick(delivery)}
                >
                  <span className="font-semibold">
                    {poLabel(delivery.poNumber)}
                  </span>
                  <span>{supplierOf(delivery)}</span>
                  <span className="numeric text-muted-foreground">
                    {s.delivery(delivery.deliveryNo)} · {delivery.deliveryDate}
                  </span>
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** EXPERIENCE.md "Capture button": Take photo or Choose file for the delivery. */
function Capture({
  delivery,
  onFile,
  onBack,
}: {
  delivery: DeliveryRow;
  onFile: (file: File, source: CaptureSource) => void;
  onBack: () => void;
}) {
  const po = poLabel(delivery.poNumber);
  const heading = usePageHeading(pageTitle(s.scanFor(po)));
  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [camera, setCamera] = useState<boolean | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Asked up front, so a tap on Take photo opens the camera at once.
  useEffect(() => {
    let current = true;
    void cameraAvailable().then((available) => {
      if (current) setCamera(available);
    });
    return () => {
      current = false;
    };
  }, []);

  function chosen(source: CaptureSource, event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    // Cleared, so choosing the same file again still counts as a choice.
    event.target.value = "";
    if (!file) return;
    const reason = refusal(file);
    if (reason !== null) {
      setNotice(reason);
      return;
    }
    onFile(file, source);
  }

  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {s.scanFor(po)}
      </h1>
      <p>
        {supplierOf(delivery)} · {s.delivery(delivery.deliveryNo)}
      </p>
      {notice !== null ? <p role="alert">{notice}</p> : null}
      <div className="flex flex-col gap-3">
        <Button
          type="button"
          className={CAPTURE}
          data-capture
          aria-describedby={camera === false ? "camera-hint" : undefined}
          onClick={() => {
            setNotice(null);
            cameraInput.current?.click();
          }}
        >
          {s.takePhoto}
        </Button>
        {camera === false && (
          <p id="camera-hint" className="text-muted-foreground">
            {s.cameraUnavailable}
          </p>
        )}
        <Button
          type="button"
          variant="outline"
          className={CAPTURE}
          data-capture
          onClick={() => {
            setNotice(null);
            fileInput.current?.click();
          }}
        >
          {s.chooseFile}
        </Button>
        <Button
          type="button"
          variant="ghost"
          className={CAPTURE}
          data-capture
          onClick={onBack}
        >
          {s.otherDelivery}
        </Button>
        <input
          ref={cameraInput}
          type="file"
          accept={TAKE_PHOTO_ACCEPT}
          capture="environment"
          hidden
          tabIndex={-1}
          data-testid="take-photo-input"
          onChange={(event) => chosen("camera", event)}
        />
        <input
          ref={fileInput}
          type="file"
          accept={CHOOSE_FILE_ACCEPT}
          hidden
          tabIndex={-1}
          data-testid="choose-file-input"
          onChange={(event) => chosen("file", event)}
        />
      </div>
    </div>
  );
}

type Phase =
  | { kind: "checking" }
  | { kind: "ready" }
  | { kind: "photo-problem"; message: string }
  | { kind: "sending"; progress: number }
  | { kind: "failed" }
  | { kind: "refused"; message: string };

/** What the page says about a send the server refused (never the server's words). */
function refusedMessage(error: ApiError): string | null {
  if (error.status === 413) return strings.fileRefused.tooLarge;
  if (error.status === 415) return strings.fileRefused.wrongType;
  // The page always sends a well-formed key, so a 400 is the empty-body refusal.
  if (error.status === 400) return strings.fileRefused.empty;
  // The key is held by another upload: a new choice makes a new key.
  if (error.status === 409 || error.status === 403) {
    return strings.errors.generic;
  }
  return null;
}

function problemMessage(problem: PhotoProblem): string {
  if (problem.kind === "dark") return s.tooDark;
  if (problem.kind === "blurry") return s.blurry;
  return s.cutOff(problem.side);
}

/**
 * EXPERIENCE.md "Check & send" as the supplier page has it (Story 1.9): the device
 * check, Take again after a failure and Send it anyway from the 2nd; then Send, with a
 * progress bar, the page guarded while it sends. A failed send keeps the file; Send
 * again reuses `uploadKey` and the same device check, so it never makes a second
 * invoice (AD-6). A delivery the server no longer knows goes back to the list.
 */
function CheckAndSend({
  delivery,
  file,
  uploadKey,
  source,
  previousFailures,
  onSent,
  onChooseAgain,
  onDeliveryGone,
  onRetake,
}: {
  delivery: DeliveryRow;
  file: File;
  uploadKey: string;
  source: CaptureSource;
  previousFailures: number;
  onSent: (po: string, supplier: string) => void;
  onChooseAgain: () => void;
  onDeliveryGone: () => void;
  onRetake: (file: File) => void;
}) {
  const heading = usePageHeading(pageTitle(s.checkHeading));
  const [checkable] = useState(() => canCheck(file));
  const [phase, setPhase] = useState<Phase>(() =>
    checkable ? { kind: "checking" } : { kind: "ready" },
  );
  const [skipped, setSkipped] = useState(!checkable);
  const [overridden, setOverridden] = useState(false);
  const sending = phase.kind === "sending";
  const controller = useRef<AbortController | null>(null);
  // Set synchronously, so a second tap before the re-render sends nothing.
  const inFlight = useRef(false);
  const retakeInput = useRef<HTMLInputElement>(null);
  const pdf = isPdf(file);

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
        setPhase({ kind: "refused", message: s.tooManyPages });
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

  useEffect(() => () => controller.current?.abort(), []);

  async function send(deviceCheck: DeviceCheck) {
    if (inFlight.current) return;
    inFlight.current = true;
    const current = new AbortController();
    controller.current = current;
    setPhase({ kind: "sending", progress: 0 });
    try {
      const result = await uploadGoodsIn(delivery.deliveryId, file, uploadKey, {
        signal: current.signal,
        deviceCheck,
        onProgress: (progress) => {
          if (!current.signal.aborted) setPhase({ kind: "sending", progress });
        },
      });
      if (current.signal.aborted) return;
      onSent(
        poLabel(result.poNumber),
        result.supplierName ?? s.unknownSupplier,
      );
    } catch (error: unknown) {
      if (current.signal.aborted) return;
      if (error instanceof ApiError && error.code === "DELIVERY_NOT_FOUND") {
        onDeliveryGone();
        return;
      }
      // The shell shows these; the photo stays for Send again.
      const message =
        error instanceof ApiError && !shells(error)
          ? refusedMessage(error)
          : null;
      setPhase(
        message === null ? { kind: "failed" } : { kind: "refused", message },
      );
    } finally {
      inFlight.current = false;
    }
  }

  function retaken(event: ChangeEvent<HTMLInputElement>) {
    const retake = event.target.files?.[0];
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
  const offerRetake =
    phase.kind === "photo-problem" || (phase.kind === "failed" && overridden);
  const status = sending
    ? s.sending
    : checking
      ? pdf
        ? s.checkingPdf
        : s.checking
      : "";

  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {s.checkHeading}
      </h1>
      <p className="break-words">
        {poLabel(delivery.poNumber)}, {supplierOf(delivery)}
      </p>
      <p className="break-words">
        {pdf ? s.pdf : s.photo}:{" "}
        <span className="font-medium">{file.name}</span>{" "}
        <span className="numeric text-muted-foreground">
          ({fileSize(file.size)})
        </span>
      </p>
      <div className="flex flex-col gap-2">
        {/* Holds only this text, so "Checking…" and "Sending…" are each announced
            once; progress updates stay out of the live region. */}
        <p role="status">{status}</p>
        {sending && (
          <progress
            className="h-2 w-full accent-primary"
            aria-label={s.progressLabel}
            max={1}
            value={phase.progress}
          />
        )}
      </div>
      <p role="alert">
        {phase.kind === "failed" && s.failed}
        {(phase.kind === "refused" || phase.kind === "photo-problem") &&
          phase.message}
      </p>
      <div className="flex flex-col gap-3">
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
            {s.send}
          </Button>
        )}
        {offerRetake && (
          <>
            <Button
              key={canSend ? "secondary" : "primary"}
              type="button"
              variant={canSend ? "outline" : "default"}
              className={CAPTURE}
              data-capture
              onClick={() => retakeInput.current?.click()}
            >
              {s.takeAgain}
            </Button>
            {offerSendAnyway && (
              <Button
                type="button"
                variant="outline"
                className={CAPTURE}
                data-capture
                onClick={() => {
                  setOverridden(true);
                  void send("overridden");
                }}
              >
                {s.sendAnyway}
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
            key={phase.kind === "refused" ? "primary" : "secondary"}
            type="button"
            variant={phase.kind === "refused" ? "default" : "outline"}
            className={CAPTURE}
            data-capture
            onClick={onChooseAgain}
          >
            {s.chooseAgain}
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Flow 4's climax: "Received for PO 45102, Sole Supply Co." in the success colour,
 * announced (`role="status"`, filled just after it mounts so it is announced), with
 * focus on it, then Scan another.
 */
function Received({
  po,
  supplier,
  onScanAnother,
}: {
  po: string;
  supplier: string;
  onScanAnother: () => void;
}) {
  const message = useRef<HTMLParagraphElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    document.title = pageTitle(strings.surfaces.goods_in_scan);
    const timer = window.setTimeout(() => setShown(true), 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (shown) message.current?.focus();
  }, [shown]);

  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 className="sr-only">{strings.surfaces.goods_in_scan}</h1>
      <div role="status">
        {shown && (
          <p
            ref={message}
            tabIndex={-1}
            className="text-xl font-semibold text-success"
          >
            {s.received(po, supplier)}
          </p>
        )}
      </div>
      <Button
        type="button"
        className={CAPTURE}
        data-capture
        onClick={onScanAnother}
      >
        {s.scanAnother}
      </Button>
    </div>
  );
}
