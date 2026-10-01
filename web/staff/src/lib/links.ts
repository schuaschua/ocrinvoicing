import type { MouseEvent } from "react";

/** A plain left click; a modified one keeps the browser's own behaviour (new tab). */
export function plainClick(event: MouseEvent): boolean {
  return !(
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  );
}
