import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CheckResult } from "@/deviceCheck";
import { CheckAndSend } from "@/screens/CheckAndSend";
import { strings } from "@/strings";
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

describe("1.9 on-device photo check", () => {
  it("says Checking photo… while it runs, with no Send yet", async () => {
    const { file } = renderCheck();
    expect(check.checkFile).toHaveBeenCalledWith(file);
    expect(screen.getByRole("status")).toHaveTextContent(/^Checking photo…$/);
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    await answer({ kind: "passed" });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("a passing photo is sent marked passed", async () => {
    const { onSent, file } = renderCheck();
    await answer({ kind: "passed" });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const xhr = FakeXhr.last();
    expect(xhr.body).toBe(file);
    expect(xhr.headers["X-Device-Check"]).toBe("passed");
    await act(async () => xhr.respond(200, OK));
    expect(onSent).toHaveBeenCalledWith("R-7Q4KXM2D");
  });

  it.each([
    [{ kind: "dark" }, "The photo is too dark."],
    [{ kind: "blurry" }, "The photo is blurry."],
    [{ kind: "cut-off", side: "bottom" }, "The bottom edge is cut off."],
    [{ kind: "cut-off", side: "left" }, "The left edge is cut off."],
  ] as const)(
    "a first failure names the problem (%o) and offers Take again only",
    async (problem, words) => {
      renderCheck();
      await answer({ kind: "photo-problem", problem });
      expect(screen.getByRole("alert")).toHaveTextContent(words);
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      expect(
        screen.getByRole("button", { name: "Take again" }),
      ).toHaveAttribute("data-capture");
      expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Send it anyway" }),
      ).toBeNull();
    },
  );

  it("Take again reopens the camera for a photo taken with it", async () => {
    const { onRetake } = renderCheck({ source: "camera" });
    await answer(DARK);
    const input = screen.getByTestId<HTMLInputElement>("take-again-input");
    expect(input).toHaveAttribute("capture", "environment");
    expect(input).toHaveAttribute("accept", "image/jpeg,image/png");
    const opened = vi.spyOn(input, "click");
    fireEvent.click(screen.getByRole("button", { name: "Take again" }));
    expect(opened).toHaveBeenCalledTimes(1);

    const retake = photo("retake.jpg");
    fireEvent.change(input, { target: { files: [retake] } });
    expect(onRetake).toHaveBeenCalledWith(retake);
    expect(input.value).toBe("");
  });

  it("Take again reopens the picker for a chosen file", async () => {
    renderCheck({ source: "file" });
    await answer(DARK);
    const input = screen.getByTestId("take-again-input");
    expect(input).not.toHaveAttribute("capture");
    expect(input.getAttribute("accept")).toContain("application/pdf");
  });

  it("a retake the page can't send is refused with the reason", async () => {
    const { onRetake } = renderCheck();
    await answer(DARK);
    fireEvent.change(screen.getByTestId("take-again-input"), {
      target: { files: [new File(["GIF8"], "x.gif", { type: "image/gif" })] },
    });
    expect(onRetake).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      strings.fileRefused.wrongType,
    );
    // The refusal replaces the failure: Choose another file is the way on.
    expect(screen.queryByTestId("take-again-input")).toBeNull();
  });

  it("a cancelled Take again leaves the failure as it was", async () => {
    const { onRetake } = renderCheck();
    await answer(DARK);
    fireEvent.change(screen.getByTestId("take-again-input"), {
      target: { files: [] },
    });
    expect(onRetake).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("too dark");
  });

  it("the second failure adds Send it anyway, which sends the photo marked overridden", async () => {
    const { onSent, file } = renderCheck({ previousFailures: 1 });
    await answer({
      kind: "photo-problem",
      problem: { kind: "cut-off", side: "top" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The top edge is cut off.",
    );
    const buttons = screen.getAllByRole("button").map((b) => b.textContent);
    expect(buttons).toEqual([
      "Take again",
      "Send it anyway",
      "Choose another file",
    ]);
    const anyway = screen.getByRole("button", { name: "Send it anyway" });
    // Secondary: the outline style, never the primary.
    expect(anyway.className).toContain("border");
    fireEvent.click(anyway);
    const xhr = FakeXhr.last();
    expect(xhr.body).toBe(file);
    expect(xhr.headers["X-Device-Check"]).toBe("overridden");
    expect(xhr.headers["Idempotency-Key"]).toBe(UPLOAD_ID);
    await act(async () => xhr.respond(200, OK));
    expect(onSent).toHaveBeenCalledWith("R-7Q4KXM2D");
  });

  it("a send after Send it anyway that fails is retried still marked overridden", async () => {
    renderCheck({ previousFailures: 1 });
    await answer(DARK);
    fireEvent.click(screen.getByRole("button", { name: "Send it anyway" }));
    await act(async () => FakeXhr.last().fail());
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't send.");
    // Take again stays on offer, as the secondary action beside Send.
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Send",
      "Take again",
      "Choose another file",
    ]);
    expect(
      screen.getByRole("button", { name: "Take again" }).className,
    ).toContain("border");
    expect(screen.getByTestId("take-again-input")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("overridden");
  });

  it("a failed send of a photo that passed offers no Take again", async () => {
    renderCheck();
    await answer({ kind: "passed" });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await act(async () => FakeXhr.last().fail());
    expect(screen.queryByRole("button", { name: "Take again" })).toBeNull();
  });

  it("a photo that passes after earlier failures is sent marked passed", async () => {
    renderCheck({ previousFailures: 2 });
    await answer({ kind: "passed" });
    expect(screen.queryByRole("button", { name: "Send it anyway" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("passed");
  });

  it("a PDF over 2 pages is refused on the device, with no photo wording", async () => {
    const { onChooseAgain } = renderCheck({
      file: new File(["%PDF-"], "inv.pdf", { type: "application/pdf" }),
    });
    expect(screen.getByRole("status")).toHaveTextContent(/^Checking PDF…$/);
    await answer({ kind: "too-many-pages" });
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This PDF has more than 2 pages.",
    );
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    expect(onChooseAgain).toHaveBeenCalledTimes(1);
    expect(FakeXhr.requests).toEqual([]);
  });

  it("a PDF of 1 or 2 pages is sent marked passed", async () => {
    renderCheck({
      file: new File(["%PDF-"], "inv.pdf", { type: "application/pdf" }),
    });
    await answer({ kind: "passed" });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.last().headers["X-Device-Check"]).toBe("passed");
  });

  it("a browser that can't check goes straight to Send", () => {
    check.canCheck.mockReturnValue(false);
    renderCheck();
    expect(check.checkFile).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("a check that ends after the screen is gone changes nothing", async () => {
    const errors = vi.spyOn(console, "error");
    const { unmount } = renderCheck();
    unmount();
    await answer(DARK);
    expect(errors).not.toHaveBeenCalled();
  });
});
