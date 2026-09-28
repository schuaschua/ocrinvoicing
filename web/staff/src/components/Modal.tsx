import { useEffect, useRef, type ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * A modal on the native `<dialog>`: the browser traps focus, makes the page behind it
 * inert, and closes it on `Esc` (EXPERIENCE.md: `Esc` closes the topmost dialog). Used
 * for the session-ended dialog and, styled as a side panel, the narrow-screen sidebar
 * Sheet. Dialogs stack one level deep at most: the caller opens one at a time.
 */
export function Modal({
  open,
  onClose,
  labelledBy,
  className,
  children,
}: {
  open: boolean;
  /** Called when the user closes it (`Esc`); the caller sets `open` to false. */
  onClose: () => void;
  /** The id of the dialog's heading, its accessible name. */
  labelledBy: string;
  className?: string;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) {
      // jsdom has no showModal; the attribute alone still shows it there.
      if (typeof element.showModal === "function") element.showModal();
      else element.setAttribute("open", "");
    } else if (!open && element.open) {
      if (typeof element.close === "function") element.close();
      else element.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      ref={dialog}
      aria-labelledby={labelledBy}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      // Closed by the browser without a cancel event (e.g. a form method="dialog"):
      // tell the caller, so its `open` state follows. Closing it ourselves because
      // `open` went false calls nothing.
      onClose={() => {
        if (open) onClose();
      }}
      className={cn(
        "bg-background text-foreground backdrop:bg-foreground/50",
        className,
      )}
    >
      {open ? children : null}
    </dialog>
  );
}
