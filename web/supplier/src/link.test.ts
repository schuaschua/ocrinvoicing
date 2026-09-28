import { describe, expect, it, vi } from "vitest";

import { readUploadToken, reloadOnNewLink } from "@/link";

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";

describe("1.7 fragment token reader", () => {
  it("reads a 256-bit base64url token from the fragment", () => {
    expect(TOKEN).toHaveLength(43);
    expect(readUploadToken(`#${TOKEN}`)).toBe(TOKEN);
  });

  it.each([
    ["no fragment", ""],
    ["an empty fragment", "#"],
    ["a short token", `#${TOKEN.slice(1)}`],
    ["a long token", `#${TOKEN}A`],
    ["a padded token", `#${TOKEN}=`],
    ["standard base64", `#${TOKEN.slice(1)}+`],
    ["a query-like fragment", `#token=${TOKEN}`],
  ])("finds no token in %s", (_, hash) => {
    expect(readUploadToken(hash)).toBeNull();
  });

  it("reloads the page when a new link changes only the fragment", () => {
    const target = Object.assign(new EventTarget(), {
      location: { reload: vi.fn() },
    });
    reloadOnNewLink(target);
    expect(target.location.reload).not.toHaveBeenCalled();
    target.dispatchEvent(new Event("hashchange"));
    expect(target.location.reload).toHaveBeenCalledTimes(1);
  });
});
