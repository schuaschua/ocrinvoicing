// A small client-side router on the History API: the staff app has a handful of
// flat routes, so no router library (and no new dependency in both apps' lock files).

import { useSyncExternalStore } from "react";

const NAVIGATE = "babaloo:navigate";

// The one-shot "Not allowed" flag: set by the redirect from a refused route, for the
// path it redirected to, and cleared by the next navigation, Back or Forward. It lives
// in memory, not in history.state, so a reload or a return by Back never shows it again.
let notAllowedPath: string | null = null;

window.addEventListener("popstate", () => {
  notAllowedPath = null;
});

function subscribe(onChange: () => void): () => void {
  window.addEventListener("popstate", onChange);
  window.addEventListener(NAVIGATE, onChange);
  return () => {
    window.removeEventListener("popstate", onChange);
    window.removeEventListener(NAVIGATE, onChange);
  };
}

function currentPath(): string {
  return window.location.pathname;
}

function currentNotAllowed(): boolean {
  return notAllowedPath !== null && notAllowedPath === window.location.pathname;
}

/** The current path; re-renders on navigation and on Back/Forward. */
export function usePath(): string {
  return useSyncExternalStore(subscribe, currentPath);
}

/** Whether the app has just redirected here from a route outside the user's roles. */
export function useNotAllowed(): boolean {
  return useSyncExternalStore(subscribe, currentNotAllowed);
}

/**
 * Go to `path` in the app. `replace` swaps the current history entry (a redirect), and
 * `notAllowed` shows the one-shot "Not allowed" alert on the page it lands on.
 */
export function navigate(
  path: string,
  { replace = false, notAllowed = false } = {},
): void {
  if (!replace && path === window.location.pathname && !notAllowed) return;
  notAllowedPath = notAllowed ? path : null;
  if (replace) {
    window.history.replaceState(null, "", path);
  } else {
    window.history.pushState(null, "", path);
  }
  window.dispatchEvent(new Event(NAVIGATE));
}
