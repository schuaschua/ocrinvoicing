import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { strings } from "@/strings";

import { CAPTURE } from "./capture";

/**
 * EXPERIENCE.md "Received": "Received. Reference R-7Q4KXM2D." in the success colour,
 * announced (`role="status"`), with focus on the reference, then Upload another. The
 * live region mounts empty and is filled just after, since a region that appears
 * with its text already in it is often not announced.
 */
export function Received({
  reference,
  onUploadAnother,
}: {
  reference: string;
  onUploadAnother: () => void;
}) {
  const referenceRef = useRef<HTMLElement>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    document.title = strings.received.pageTitle;
    const timer = window.setTimeout(() => setShown(true), 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    if (shown) referenceRef.current?.focus();
  }, [shown]);

  return (
    <div className="flex flex-1 flex-col gap-6">
      <div role="status" className="flex flex-col gap-2">
        {shown && (
          <>
            <h1 className="text-xl font-semibold text-success">
              {strings.received.heading}
            </h1>
            <p className="text-lg">
              {strings.received.reference}{" "}
              <strong ref={referenceRef} tabIndex={-1} className="numeric">
                {reference}
              </strong>
            </p>
          </>
        )}
      </div>
      <Button
        type="button"
        className={`mt-auto ${CAPTURE}`}
        data-capture
        onClick={onUploadAnother}
      >
        {strings.received.uploadAnother}
      </Button>
    </div>
  );
}
