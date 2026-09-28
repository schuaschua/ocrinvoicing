// The supplier page's screens for the accessibility check (e2e/a11y.spec.ts, shared
// with web/staff). Screen stories add theirs here.
import type { Screen } from "./checks.ts";

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";

export const SCREENS: Screen[] = [
  {
    story: "1.7",
    name: "upload home",
    path: `/u#${TOKEN}`,
    api: {
      "/api/link": {
        status: 200,
        body: { supplier_name: "Lim Leather Trading" },
      },
    },
    ready: "Uploading for Lim Leather Trading",
  },
  {
    story: "1.7",
    name: "link not working (no token)",
    path: "/u",
    ready: "This link isn't working.",
  },
  {
    story: "1.7",
    name: "link not working (revoked or unknown)",
    path: `/u#${TOKEN}`,
    api: {
      "/api/link": {
        status: 401,
        body: {
          code: "LINK_NOT_VALID",
          message:
            "This link isn't working. Please contact your buyer at Babaloo.",
          correlation_id: "0199a1b2-0000-7000-8000-000000000001",
        },
      },
    },
    ready: "This link isn't working.",
  },
  {
    story: "1.7",
    name: "waking up",
    path: `/u#${TOKEN}`,
    api: { "/api/link": "hang" },
    ready: "Waking up, one moment…",
  },
  {
    story: "1.7",
    name: "link check failed",
    path: `/u#${TOKEN}`,
    api: {
      "/api/link": {
        status: 503,
        body: {
          code: "SERVICE_UNAVAILABLE",
          message: "The service is busy. Try again in a moment.",
          correlation_id: "0199a1b2-0000-7000-8000-000000000002",
        },
      },
    },
    ready: "Something went wrong. Try again later.",
  },
];
