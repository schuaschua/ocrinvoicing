import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CheckAndSend } from "@/screens/CheckAndSend";
import { strings } from "@/strings";
import { FakeXhr } from "@/test/fakeXhr";

const UPLOAD_ID = "3fa85f64-5717-4562-b3fc-2c963f66afa6";
const OK = {
  invoice_id: "0199a1b2-0000-7000-8000-000000000001",
  reference: "R-7Q4KXM2D",
};

function photo(): File {
  return new File([new Uint8Array(1500)], "invoice-4521.jpg", {
    type: "image/jpeg",
  });
}

function renderCheck(file = photo()) {
  const props = {
    file,
    uploadKey: UPLOAD_ID,
    source: "camera" as const,
    previousFailures: 0,
    onSent: vi.fn(),
    onLinkNotWorking: vi.fn(),
    onChooseAgain: vi.fn(),
    onRetake: vi.fn(),
  };
  const view = render(<CheckAndSend {...props} />);
  return { ...props, ...view };
}

function send() {
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

beforeEach(() => {
  FakeXhr.reset();
  vi.stubGlobal("XMLHttpRequest", FakeXhr);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("1.8 Check & send", () => {
  it("shows what was chosen, then sends it once, with progress, guarding the page", async () => {
    const { onSent } = renderCheck();
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Check & send");
    expect(heading).toHaveFocus();
    expect(document.title).toBe("Check & send – Babaloo");
    expect(screen.getByText(/Photo:/)).toHaveTextContent(
      "Photo: invoice-4521.jpg (1 KB)",
    );

    // Two taps before the page updates send once.
    const button = screen.getByRole("button", { name: "Send" });
    act(() => {
      button.click();
      button.click();
    });
    expect(FakeXhr.requests).toHaveLength(1);
    // Only the words are live; the bar is outside the region.
    expect(screen.getByRole("status")).toHaveTextContent(/^Sending…$/);
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Choose another file" }),
    ).toBeNull();
    const bar = screen.getByRole("progressbar", { name: "Upload progress" });
    expect(screen.getByRole("status")).not.toContainElement(bar);
    act(() => FakeXhr.last().progress(50, 100));
    expect(bar).toHaveAttribute("value", "0.5");

    const leave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(true);

    await act(async () => FakeXhr.last().respond(200, OK));
    expect(onSent).toHaveBeenCalledWith("R-7Q4KXM2D");
  });

  it("after a failure keeps the file and the key, and words a refusal itself", async () => {
    const file = photo();
    const { onChooseAgain, onSent, unmount } = renderCheck(file);
    send();
    await act(async () => FakeXhr.last().respond(500, {}));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't send. Check your connection and tap Send again.",
    );
    // No longer guarding the page.
    const leave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(false);

    send();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
    const [first, second] = FakeXhr.requests;
    expect(second!.body).toBe(file);
    expect(second!.headers["Idempotency-Key"]).toBe(UPLOAD_ID);
    expect(first!.headers["Idempotency-Key"]).toBe(UPLOAD_ID);
    await act(async () =>
      second!.respond(413, {
        code: "X",
        message: "Server words, never shown.",
      }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      strings.fileRefused.tooLarge,
    );
    expect(screen.queryByText("Server words, never shown.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    expect(onChooseAgain).toHaveBeenCalledTimes(1);
    unmount();

    // Leaving the screen mid-send stops the request and reports nothing.
    const again = renderCheck();
    send();
    const xhr = FakeXhr.last();
    again.unmount();
    expect(xhr.aborted).toBe(true);
    await act(async () => xhr.respond(200, OK));
    expect(onSent).not.toHaveBeenCalled();
    expect(again.onSent).not.toHaveBeenCalled();
  });
});
