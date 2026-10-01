import { type ChangeEvent, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { strings } from "@/strings";
import {
  CHOOSE_FILE_ACCEPT,
  TAKE_PHOTO_ACCEPT,
  cameraAvailable,
  refusal,
} from "@/upload";

import { CAPTURE, type CaptureSource } from "./capture";
import { usePageHeading } from "./usePageHeading";

function CameraIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-5"
    >
      <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z" />
      <circle cx="12" cy="13" r="3" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-5"
    >
      <path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7z" />
      <path d="M14 2v4a2 2 0 0 0 2 2h4" />
    </svg>
  );
}

/**
 * EXPERIENCE.md "Upload home" (UX-DR4): who the upload is for, then the capture
 * actions in the lower half, within thumb reach. Each opens a native file input: Take
 * photo the camera (with a hint to use Choose file when the browser lists no camera),
 * Choose file a JPEG, PNG or PDF. A chosen file the page can already
 * tell is unsendable is refused here, with the reason; any other goes to `onFile`,
 * with the input it came from. `reminders` (Story 4.3) are the supplier's overdue PO
 * numbers, shown in a read-only banner when there are any.
 */
export function UploadHome({
  supplierName,
  reminders = [],
  onFile,
}: {
  supplierName: string;
  reminders?: readonly string[];
  onFile: (file: File, source: CaptureSource) => void;
}) {
  const heading = usePageHeading(strings.uploadHome.pageTitle);
  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [camera, setCamera] = useState<boolean | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Asked up front, so a tap on Take photo opens the camera at once: a file input
  // opened after an await may lose the tap's user activation.
  useEffect(() => {
    let current = true;
    void cameraAvailable().then((available) => {
      if (current) setCamera(available);
    });
    return () => {
      current = false;
    };
  }, []);

  // Never blocked by the camera hint: the browser may still open a camera or picker.
  function takePhoto() {
    setNotice(null);
    cameraInput.current?.click();
  }

  function chooseFile() {
    setNotice(null);
    fileInput.current?.click();
  }

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
      <h1 ref={heading} tabIndex={-1} className="text-xl">
        {strings.uploadHome.uploadingFor} <strong>{supplierName}</strong>
      </h1>
      {/* Present from the start, so the reminders are announced when they arrive;
          the banner's look only while it has text. */}
      <p
        role="status"
        className={
          reminders.length > 0 ? "rounded-md bg-muted px-3 py-2" : undefined
        }
      >
        {reminders.length > 0 ? strings.uploadHome.reminders(reminders) : null}
      </p>
      {/* Present from the start, so a refusal is announced when it appears. */}
      <p role="alert">{notice}</p>
      <div className="mt-auto flex flex-col gap-3">
        <Button
          type="button"
          className={CAPTURE}
          data-capture
          onClick={takePhoto}
          aria-describedby={camera === false ? "camera-hint" : undefined}
        >
          <CameraIcon />
          {strings.uploadHome.takePhoto}
        </Button>
        {camera === false && (
          <p id="camera-hint" className="text-muted-foreground">
            {strings.uploadHome.cameraUnavailable}
          </p>
        )}
        <Button
          type="button"
          variant="outline"
          className={CAPTURE}
          data-capture
          onClick={chooseFile}
        >
          <FileIcon />
          {strings.uploadHome.chooseFile}
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
