import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setUploadToken } from "@/api";
import { App } from "@/App";
import type { CheckResult } from "@/deviceCheck";
import { FakeXhr } from "@/test/fakeXhr";

// Every photo fails the device check unless its name says "good".
const check = vi.hoisted(() => ({
  canCheck: vi.fn(() => true),
  checkFile: vi.fn(),
}));
vi.mock("@/deviceCheck", () => check);

// Synthetic: base64url of 32 bytes of 0x5a, canonical like a real link token.
const TOKEN = "WlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlpaWlo";
const OK = {
  invoice_id: "0199a1b2-0000-7000-8000-000000000001",
  reference: "R-7Q4KXM2D",
};

let modified = 1_790_000_000_000;
function jpeg(name: string): File {
  modified += 1;
  return new File([new Uint8Array([0xff, 0xd8, 0xff])], name, {
    type: "image/jpeg",
    lastModified: modified,
  });
}

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ supplier_name: "Lim Leather Trading" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
    ),
  );
  FakeXhr.reset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  check.checkFile.mockImplementation(
    async (file: File): Promise<CheckResult> =>
      file.name.includes("good")
        ? { kind: "passed" }
        : { kind: "photo-problem", problem: { kind: "blurry" } },
  );
});

afterEach(() => {
  setUploadToken(null);
  vi.unstubAllGlobals();
});

async function home() {
  await screen.findByRole("heading", {
    name: "Uploading for Lim Leather Trading",
  });
}

async function takePhoto(name: string) {
  fireEvent.change(screen.getByTestId("take-photo-input"), {
    target: { files: [jpeg(name)] },
  });
  await act(async () => {});
}

async function takeAgain(name: string) {
  fireEvent.change(screen.getByTestId("take-again-input"), {
    target: { files: [jpeg(name)] },
  });
  await act(async () => {});
}

const anyway = () => screen.queryByRole("button", { name: "Send it anyway" });

describe("1.9 failed checks across one upload", () => {
  it("offers Send it anyway after the 2nd failure, then shows Received", async () => {
    render(<App token={TOKEN} />);
    await home();
    await takePhoto("first.jpg");
    expect(screen.getByRole("alert")).toHaveTextContent("The photo is blurry.");
    expect(anyway()).toBeNull();

    await takeAgain("second.jpg");
    // A fresh screen for the retake, with the problem named again.
    expect(screen.getByRole("heading", { name: "Check & send" })).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent("The photo is blurry.");
    fireEvent.click(anyway()!);
    const xhr = FakeXhr.last();
    expect(xhr.headers["X-Device-Check"]).toBe("overridden");
    expect((xhr.body as File).name).toBe("second.jpg");
    await act(async () => xhr.respond(200, OK));
    expect(await screen.findByText("R-7Q4KXM2D")).toBeInTheDocument();
  });

  it("sends a passing retake marked passed, and starts counting again for each new upload", async () => {
    render(<App token={TOKEN} />);
    await home();
    await takePhoto("first.jpg");
    await takeAgain("good.jpg");
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("passed");
    expect((FakeXhr.last().body as File).name).toBe("good.jpg");
    await act(async () => FakeXhr.last().respond(200, OK));

    // After Upload another: a first failure again, so no Send it anyway.
    fireEvent.click(
      await screen.findByRole("button", { name: "Upload another" }),
    );
    await home();
    await takePhoto("next.jpg");
    expect(screen.getByRole("alert")).toHaveTextContent("blurry");
    expect(anyway()).toBeNull();

    // After Choose another file too.
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    await home();
    await takePhoto("other.jpg");
    expect(anyway()).toBeNull();
  });
});
