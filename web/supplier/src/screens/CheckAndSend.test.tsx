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
  it("shows what was chosen, with Send", () => {
    renderCheck();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Check & send",
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveFocus();
    expect(document.title).toBe("Check & send – Babaloo");
    expect(screen.getByText(/Photo:/)).toHaveTextContent(
      "Photo: invoice-4521.jpg (1 KB)",
    );
    expect(screen.getByRole("button", { name: "Send" })).toHaveAttribute(
      "data-capture",
    );
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it.each([
    ["its type", "application/pdf"],
    ["its name when it has no type", ""],
  ])("labels a PDF as a PDF by %s", (_, type) => {
    renderCheck(new File(["%PDF-"], "inv.pdf", { type }));
    expect(screen.getByText(/PDF:/)).toHaveTextContent("PDF: inv.pdf");
  });

  it("sends once when Send is tapped twice before the page updates", () => {
    renderCheck();
    const button = screen.getByRole("button", { name: "Send" });
    act(() => {
      button.click();
      button.click();
    });
    expect(FakeXhr.requests).toHaveLength(1);
  });

  it("while sending: announces it, shows progress, disables Send and guards leaving", async () => {
    const { onSent } = renderCheck();
    send();
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

    // Leaving asks first.
    const leave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(true);

    // A second tap sends nothing more.
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(FakeXhr.requests).toHaveLength(1);

    await act(async () => FakeXhr.last().respond(200, OK));
    expect(onSent).toHaveBeenCalledWith("R-7Q4KXM2D");
  });

  it("stops guarding the page once the send has ended", async () => {
    renderCheck();
    send();
    await act(async () => FakeXhr.last().fail());
    const leave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(false);
  });

  it.each([
    ["a network failure", (xhr: FakeXhr) => xhr.fail()],
    ["a timeout", (xhr: FakeXhr) => xhr.timeOut()],
    [
      "a storage outage",
      (xhr: FakeXhr) =>
        xhr.respond(503, { code: "SERVICE_UNAVAILABLE", message: "Busy." }),
    ],
    ["a server error", (xhr: FakeXhr) => xhr.respond(500, {})],
  ])(
    "after %s: keeps the file, says Couldn't send, and Send again reuses the key",
    async (_, happen) => {
      const file = photo();
      const { onSent } = renderCheck(file);
      send();
      await act(async () => happen(FakeXhr.last()));
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Couldn't send. Check your connection and tap Send again.",
      );
      expect(screen.getByRole("status")).toBeEmptyDOMElement();
      const again = screen.getByRole("button", { name: "Send" });
      expect(again).toBeEnabled();

      fireEvent.click(again);
      expect(screen.getByRole("alert")).toBeEmptyDOMElement();
      const [first, second] = FakeXhr.requests;
      expect(second!.body).toBe(file);
      expect(second!.headers["Idempotency-Key"]).toBe(UPLOAD_ID);
      expect(first!.headers["Idempotency-Key"]).toBe(UPLOAD_ID);
      await act(async () => second!.respond(200, OK));
      expect(onSent).toHaveBeenCalledWith("R-7Q4KXM2D");
    },
  );

  it.each([
    [413, strings.fileRefused.tooLarge],
    [415, strings.fileRefused.wrongType],
    [400, strings.fileRefused.empty],
    [409, strings.errors.generic],
  ])(
    "after a %s refusal: our own words, and Choose another file instead of Send",
    async (status, message) => {
      const { onChooseAgain } = renderCheck();
      send();
      await act(async () =>
        FakeXhr.last().respond(status, {
          code: "X",
          message: "Server words, never shown.",
        }),
      );
      expect(screen.getByRole("alert")).toHaveTextContent(message);
      expect(screen.queryByText("Server words, never shown.")).toBeNull();
      expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
      fireEvent.click(
        screen.getByRole("button", { name: "Choose another file" }),
      );
      expect(onChooseAgain).toHaveBeenCalledTimes(1);
    },
  );

  it("a link that stopped working goes to Link not working", async () => {
    const { onLinkNotWorking } = renderCheck();
    send();
    await act(async () =>
      FakeXhr.last().respond(401, { code: "LINK_NOT_VALID", message: "x" }),
    );
    expect(onLinkNotWorking).toHaveBeenCalledTimes(1);
  });

  it("Choose another file goes back before sending", () => {
    const { onChooseAgain } = renderCheck();
    fireEvent.click(
      screen.getByRole("button", { name: "Choose another file" }),
    );
    expect(onChooseAgain).toHaveBeenCalledTimes(1);
    expect(FakeXhr.requests).toEqual([]);
  });

  it("leaving the screen mid-send stops the request and reports nothing", async () => {
    const { onSent, unmount } = renderCheck();
    send();
    const xhr = FakeXhr.last();
    unmount();
    expect(xhr.aborted).toBe(true);
    await act(async () => xhr.respond(200, OK));
    expect(onSent).not.toHaveBeenCalled();
  });
});
