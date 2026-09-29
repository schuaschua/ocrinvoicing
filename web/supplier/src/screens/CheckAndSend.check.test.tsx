import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CheckResult } from "@/deviceCheck";
import { CheckAndSend } from "@/screens/CheckAndSend";
import { FakeXhr } from "@/test/fakeXhr";

// The check itself is tested in deviceCheck.test.ts; here it answers when told to.
const check = vi.hoisted(() => ({
  canCheck: vi.fn(() => true),
  checkFile: vi.fn(),
}));
vi.mock("@/deviceCheck", () => check);

const UPLOAD_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const OK = {
  invoice_id: "0199a1b2-0000-7000-8000-000000000001",
  reference: "R-7Q4KXM2D",
};

let answer: (result: CheckResult) => Promise<void>;

beforeEach(() => {
  FakeXhr.reset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
  check.canCheck.mockReturnValue(true);
  check.checkFile.mockImplementation(
    () =>
      new Promise<CheckResult>((resolve) => {
        answer = async (result) => {
          await act(async () => resolve(result));
        };
      }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function photo(name = "invoice-4521.jpg"): File {
  return new File([new Uint8Array(1500)], name, { type: "image/jpeg" });
}

function renderCheck(
  options: {
    file?: File;
    previousFailures?: number;
    source?: "camera" | "file";
  } = {},
) {
  const props = {
    file: options.file ?? photo(),
    uploadKey: UPLOAD_ID,
    source: options.source ?? ("camera" as const),
    previousFailures: options.previousFailures ?? 0,
    onSent: vi.fn(),
    onLinkNotWorking: vi.fn(),
    onChooseAgain: vi.fn(),
    onRetake: vi.fn(),
  };
  const view = render(<CheckAndSend {...props} />);
  return { ...props, ...view };
}

const DARK: CheckResult = { kind: "photo-problem", problem: { kind: "dark" } };

const buttons = () => screen.getAllByRole("button").map((b) => b.textContent);

describe("1.9 on-device photo check", () => {
  it("names a failed check, offers Take again, then Send it anyway from the 2nd failure", async () => {
    const first = renderCheck({ source: "camera" });
    expect(check.checkFile).toHaveBeenCalledWith(first.file);
    expect(screen.getByRole("status")).toHaveTextContent(/^Checking photo…$/);
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    await answer(DARK);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The photo is too dark.",
    );
    expect(buttons()).toEqual(["Take again", "Choose another file"]);

    // Take again reopens the camera the photo came from.
    const input = screen.getByTestId<HTMLInputElement>("take-again-input");
    expect(input).toHaveAttribute("capture", "environment");
    const opened = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button", { name: "Take again" }));
    expect(opened).toHaveBeenCalledTimes(1);
    const retake = photo("retake.jpg");
    fireEvent.change(input, { target: { files: [retake] } });
    expect(first.onRetake).toHaveBeenCalledWith(retake);
    first.unmount();

    // The retake fails too: Send it anyway, the secondary action.
    const second = renderCheck({ previousFailures: 1 });
    await answer({
      kind: "photo-problem",
      problem: { kind: "cut-off", side: "top" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The top edge is cut off.",
    );
    expect(buttons()).toEqual([
      "Take again",
      "Send it anyway",
      "Choose another file",
    ]);
    const anyway = screen.getByRole("button", { name: "Send it anyway" });
    expect(anyway.className).toContain("border");
    fireEvent.click(anyway);
    expect(FakeXhr.last().body).toBe(second.file);
    expect(FakeXhr.last().headers).toMatchObject({
      "X-Device-Check": "overridden",
      "Idempotency-Key": UPLOAD_ID,
    });

    // A failed send is retried still overridden, with Take again beside Send.
    await act(async () => FakeXhr.last().fail());
    expect(buttons()).toEqual(["Send", "Take again", "Choose another file"]);
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("overridden");
    await act(async () => FakeXhr.last().respond(200, OK));
    expect(second.onSent).toHaveBeenCalledWith("R-7Q4KXM2D");
  });

  it("sends what it couldn't check marked skipped, and refuses a PDF over 2 pages", async () => {
    // A browser that can't check goes straight to Send.
    check.canCheck.mockReturnValue(false);
    const plain = renderCheck();
    expect(check.checkFile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("skipped");
    plain.unmount();

    // A check that couldn't finish: no failure, and skipped on every send.
    check.canCheck.mockReturnValue(true);
    const unfinished = renderCheck();
    await answer({ kind: "skipped" });
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    expect(screen.queryByRole("button", { name: "Take again" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => FakeXhr.last().fail());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("skipped");
    unfinished.unmount();

    FakeXhr.reset();
    const pdf = renderCheck({
      file: new File(["%PDF-"], "inv.pdf", { type: "application/pdf" }),
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^Checking PDF…$/);
    expect(screen.getByText(/PDF:/)).toHaveTextContent("PDF: inv.pdf");
    await answer({ kind: "too-many-pages" });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This PDF has more than 2 pages.",
    );
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    expect(pdf.onChooseAgain).toHaveBeenCalledTimes(1);
    expect(FakeXhr.requests).toEqual([]);
  });
});
