// The supplier link's token (AD-6), from the URL fragment (`/u#<token>`). The fragment
// stays in the address bar on purpose, so a reload or a bookmark still works; the
// browser never sends it to the server, and the page never stores it anywhere else.
// The page sends it to the API only in the `X-Upload-Token` header.

// 256 bits in base64url without padding. A convenience check only: the server decides
// (coding-style.md rule 16), and anything else can't be a link.
const TOKEN = /^[A-Za-z0-9_-]{43}$/;

/** The token in a `location.hash` value, or null when there is none. */
export function readUploadToken(hash: string): string | null {
  const token = hash.startsWith("#") ? hash.slice(1) : hash;
  return TOKEN.test(token) ? token : null;
}

/** What `reloadOnNewLink` needs from `window`. */
export interface LinkWindow {
  addEventListener(type: "hashchange", listener: () => void): void;
  location: { reload(): void };
}

/**
 * The page reads the token once, at start-up. A new link opened in the same tab only
 * changes the fragment, which doesn't reload the page, so reload it here.
 */
export function reloadOnNewLink(target: LinkWindow): void {
  target.addEventListener("hashchange", () => target.location.reload());
}
