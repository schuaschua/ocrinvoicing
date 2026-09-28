import { Button } from "@/components/ui/button";
import { strings } from "@/strings";

import { usePageHeading } from "./usePageHeading";

// DESIGN.md capture button: full width, at least 56px, icon and label.
const CAPTURE = "h-auto min-h-capture w-full whitespace-normal text-base";

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
 * actions in the lower half, within thumb reach. Stories 1.8 and 1.9 wire the buttons.
 */
export function UploadHome({ supplierName }: { supplierName: string }) {
  const heading = usePageHeading(strings.uploadHome.pageTitle);
  return (
    <div className="flex flex-1 flex-col gap-6">
      <h1 ref={heading} tabIndex={-1} className="text-xl">
        {strings.uploadHome.uploadingFor} <strong>{supplierName}</strong>
      </h1>
      <div className="mt-auto flex flex-col gap-3">
        <Button type="button" className={CAPTURE}>
          <CameraIcon />
          {strings.uploadHome.takePhoto}
        </Button>
        <Button type="button" variant="outline" className={CAPTURE}>
          <FileIcon />
          {strings.uploadHome.chooseFile}
        </Button>
      </div>
    </div>
  );
}
