import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function media(): MediaQueryList | null {
  return typeof window.matchMedia === "function"
    ? window.matchMedia(QUERY)
    : null;
}

function subscribe(onChange: () => void): () => void {
  const list = media();
  list?.addEventListener("change", onChange);
  return () => list?.removeEventListener("change", onChange);
}

/** Whether the user asked for reduced motion (EXPERIENCE.md: no zoom animation). */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, () => media()?.matches ?? false);
}
