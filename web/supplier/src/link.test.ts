import { describe, expect, it, vi } from "vitest";

import { readUploadToken, reloadOnNewLink } from "@/link";

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";

describe("1.7 fragment token reader", () => {
  it("reads only a 256-bit base64url token from the fragment, and reloads for a new link", () => {
    expect(readUploadToken(`#${TOKEN}`)).toBe(TOKEN);
    for (const hash of [
      "",
      `#${TOKEN.slice(1)}`,
      `#${TOKEN}=`,
      `#${TOKEN.slice(1)}+`,
      `#token=${TOKEN}`,
    ]) {
      expect(readUploadToken(hash)).toBeNull();
    }

    const target = Object.assign(new EventTarget(), {
      location: { reload: vi.fn() },
    });
    reloadOnNewLink(target);
    target.dispatchEvent(new Event("hashchange"));
    expect(target.location.reload).toHaveBeenCalledTimes(1);
  });
});
