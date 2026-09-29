// The supplier page's screens for the accessibility check (e2e/a11y.spec.ts, shared
// with web/staff). Screen stories add theirs here.
import type { Page } from "@playwright/test";

import type { ApiAnswer, Screen } from "./checks.ts";

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";

const LINK_OK: Record<string, ApiAnswer> = {
  "/api/link": { status: 200, body: { supplier_name: "Lim Leather Trading" } },
};

async function atHome(page: Page): Promise<void> {
  await page
    .getByRole("heading", { name: "Uploading for Lim Leather Trading" })
    .waitFor();
}

/** Choose a (synthetic) file through the real Choose file input. */
async function choose(
  page: Page,
  name = "invoice-4521.jpg",
  mimeType = "image/jpeg",
): Promise<void> {
  await atHome(page);
  await page.getByTestId("choose-file-input").setInputFiles({
    name,
    mimeType,
    buffer: Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]),
  });
}

async function chooseAndSend(page: Page): Promise<void> {
  await choose(page);
  await page.getByRole("button", { name: "Send" }).click();
}

/** A real PNG of a very dark photo, made in the browser (fails the device check). */
async function darkPhoto(page: Page): Promise<Buffer> {
  const bytes = await page.evaluate(async () => {
    const width = 400;
    const height = 300;
    const pixels = new Uint8ClampedArray(width * height * 4);
    for (let i = 0; i < pixels.length; i += 4) {
      pixels[i] = pixels[i + 1] = pixels[i + 2] = 10;
      pixels[i + 3] = 255;
    }
    const canvas = new OffscreenCanvas(width, height);
    canvas.getContext("2d")!.putImageData(new ImageData(pixels, width), 0, 0);
    const blob = await canvas.convertToBlob({ type: "image/png" });
    return Array.from(new Uint8Array(await blob.arrayBuffer()));
  });
  return Buffer.from(bytes);
}

async function chooseDarkPhoto(page: Page): Promise<void> {
  await atHome(page);
  await page.getByTestId("choose-file-input").setInputFiles({
    name: "dark.png",
    mimeType: "image/png",
    buffer: await darkPhoto(page),
  });
  await page.getByRole("alert").getByText("The photo is too dark.").waitFor();
}

function upload(answer: ApiAnswer): Record<string, ApiAnswer> {
  return { ...LINK_OK, "/api/upload": answer };
}

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
    story: "1.8",
    name: "check and send",
    path: `/u#${TOKEN}`,
    api: LINK_OK,
    steps: (page) => choose(page),
    ready: "invoice-4521.jpg",
  },
  {
    story: "1.9",
    name: "second failed check (send it anyway)",
    path: `/u#${TOKEN}`,
    api: LINK_OK,
    steps: async (page) => {
      await chooseDarkPhoto(page);
      await page.getByTestId("take-again-input").setInputFiles({
        name: "dark-again.png",
        mimeType: "image/png",
        buffer: await darkPhoto(page),
      });
    },
    ready: "Send it anyway",
  },
  {
    story: "1.8",
    name: "received",
    path: `/u#${TOKEN}`,
    api: upload({
      status: 200,
      body: {
        invoice_id: "0199a1b2-0000-7000-8000-000000000005",
        reference: "R-7Q4KXM2D",
      },
    }),
    steps: chooseAndSend,
    ready: "Reference R-7Q4KXM2D",
  },
];
