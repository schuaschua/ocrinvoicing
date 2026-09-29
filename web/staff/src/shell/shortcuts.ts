// Story 2.11: opt-in single-key shortcuts for admins who clear the queue all day. Off
// by default, and kept per browser in localStorage, not on a server profile (AD-14).
// A key never fires while the user types or while a dialog is open, so keyboard and
// screen-reader users who don't opt in are unaffected.

import { useEffect, useRef, useSyncExternalStore } from "react";

/** The browser setting: "on", or absent for off. */
export const SHORTCUTS_SETTING = "ocr.shortcuts";

// Set when the storage refused a write: the choice still holds for this session.
let sessionChoice: boolean | null = null;
const listeners = new Set<() => void>();

function stored(): boolean {
  if (sessionChoice !== null) return sessionChoice;
  try {
    return window.localStorage.getItem(SHORTCUTS_SETTING) === "on";
  } catch {
    // No storage (blocked, private mode): off.
    return false;
  }
}

function emit(): void {
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  // Another tab changed it.
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** Whether the shortcuts are on in this browser; re-renders when it changes. */
export function useShortcutsEnabled(): boolean {
  return useSyncExternalStore(subscribe, stored);
}

/** Turn the shortcuts on or off, at once and for later visits where storage allows. */
export function setShortcutsEnabled(on: boolean): void {
  try {
    if (on) window.localStorage.setItem(SHORTCUTS_SETTING, "on");
    else window.localStorage.removeItem(SHORTCUTS_SETTING);
    sessionChoice = null;
  } catch {
    sessionChoice = on;
  }
  emit();
}

const TYPING =
  "input, textarea, select, [contenteditable]:not([contenteditable='false'])";
// Enter on these is the element's own (a link or button): the shortcut stays out.
const ACTIVATES = "a[href], button, [role='button'], summary";

/** Whether a key press may run a shortcut: no modifier or repeat, no typing, no dialog. */
function mayRun(event: KeyboardEvent): boolean {
  if (
    event.defaultPrevented ||
    event.repeat ||
    event.isComposing ||
    event.ctrlKey ||
    event.altKey ||
    event.metaKey
  ) {
    return false;
  }
  // A dialog handles its own keys: the native <dialog> closes on Esc (Modal).
  if (document.querySelector("dialog[open]") !== null) return false;
  const target = event.target;
  if (target instanceof Element) {
    if (target.closest(TYPING) !== null) return false;
    if (event.key === "Enter" && target.closest(ACTIVATES) !== null) {
      return false;
    }
  }
  return true;
}

/** Actions by `KeyboardEvent.key`; a missing or undefined key does nothing. */
export type KeyMap = Readonly<Record<string, (() => void) | undefined>>;

/**
 * Runs `keys[event.key]` on a key press while the shortcuts are on. Pass the same
 * handlers the buttons use, and leave a key out when its button isn't shown, so a
 * shortcut never does more than the page offers.
 */
export function useShortcuts(keys: KeyMap): void {
  const latest = useRef(keys);
  useEffect(() => {
    latest.current = keys;
  });
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!stored() || !mayRun(event)) return;
      // Caps Lock or Shift gives "J": letters match lower case; "?", Enter and
      // Escape stay as they are.
      const key = /^[A-Za-z]$/.test(event.key)
        ? event.key.toLowerCase()
        : event.key;
      const action = latest.current[key];
      if (action === undefined) return;
      event.preventDefault();
      action();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);
}
