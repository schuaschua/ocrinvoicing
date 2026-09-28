import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UploadHome } from "@/screens/UploadHome";
import { strings } from "@/strings";

function renderHome(onFile = vi.fn()) {
  render(<UploadHome supplierName="Lim Leather Trading" onFile={onFile} />);
  return onFile;
}

function input(testId: "take-photo-input" | "choose-file-input") {
  return screen.getByTestId(testId) as HTMLInputElement;
}

function choose(element: HTMLInputElement, file: File) {
  fireEvent.change(element, { target: { files: [file] } });
}

function stubCamera(kinds: MediaDeviceKind[] | "unknown") {
  vi.stubGlobal("navigator", {
    ...navigator,
    mediaDevices:
      kinds === "unknown"
        ? undefined
        : {
            enumerateDevices: async () =>
              kinds.map((kind) => ({ kind }) as MediaDeviceInfo),
          },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("1.7 Upload home", () => {
  it("says who the upload is for, with the name in bold", () => {
    renderHome();
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent("Uploading for Lim Leather Trading");
    expect(heading.querySelector("strong")).toHaveTextContent(
      "Lim Leather Trading",
    );
    expect(heading).toHaveFocus();
    expect(document.title).toBe("Upload – Babaloo");
  });

  it("offers Take photo and Choose file as full-width capture buttons", () => {
    renderHome();
    for (const name of ["Take photo", "Choose file"]) {
      const button = screen.getByRole("button", { name });
      expect(button).toHaveClass("min-h-capture", "w-full");
      expect(button).toHaveAttribute("data-capture");
    }
  });

  it("shows a name as text, never as markup", () => {
    render(<UploadHome supplierName="<b>Evil</b> Co" onFile={vi.fn()} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Uploading for <b>Evil</b> Co",
    );
  });
});

describe("1.8 choosing or taking the invoice", () => {
  it("Choose file opens a picker for JPEG, PNG or PDF", () => {
    renderHome();
    const picker = input("choose-file-input");
    expect(picker.type).toBe("file");
    expect(picker.accept).toBe(
      "image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf",
    );
    expect(picker).not.toHaveAttribute("capture");
    const click = vi.spyOn(picker, "click");
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("Take photo opens the camera input", async () => {
    stubCamera(["videoinput"]);
    renderHome();
    await act(async () => {});
    const camera = input("take-photo-input");
    expect(camera.accept).toBe("image/jpeg,image/png");
    expect(camera).toHaveAttribute("capture", "environment");
    const click = vi.spyOn(camera, "click");
    fireEvent.click(screen.getByRole("button", { name: "Take photo" }));
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("Take photo opens the camera input when the browser can't tell", async () => {
    stubCamera("unknown");
    renderHome();
    await act(async () => {});
    const click = vi.spyOn(input("take-photo-input"), "click");
    fireEvent.click(screen.getByRole("button", { name: "Take photo" }));
    expect(click).toHaveBeenCalledTimes(1);
  });

  it("hints at Choose file when no camera is listed, but still opens Take photo", async () => {
    stubCamera(["audioinput"]);
    renderHome();
    await act(async () => {});
    const hint =
      "Camera not available here. Tap Choose file to pick a photo, or open this link in your phone's browser.";
    const takePhoto = screen.getByRole("button", { name: "Take photo" });
    expect(screen.getByText(hint)).toBeVisible();
    expect(takePhoto).toHaveAccessibleDescription(hint);
    expect(takePhoto).toBeEnabled();
    const click = vi.spyOn(input("take-photo-input"), "click");
    fireEvent.click(takePhoto);
    expect(click).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("shows no camera hint when a camera is listed", async () => {
    stubCamera(["videoinput"]);
    renderHome();
    await act(async () => {});
    expect(screen.queryByText(/Camera not available here/)).toBeNull();
  });

  it.each([
    ["take-photo-input", "camera"],
    ["choose-file-input", "file"],
  ] as const)(
    "passes a sendable file from %s on, with where it came from",
    (testId, source) => {
      const onFile = renderHome();
      const file = new File([new Uint8Array([0xff, 0xd8, 0xff])], "inv.jpg", {
        type: "image/jpeg",
      });
      choose(input(testId), file);
      expect(onFile).toHaveBeenCalledWith(file, source);
      // Cleared, so the same file can be chosen again.
      expect(input(testId).value).toBe("");
    },
  );

  it("clears a refusal when Choose file is tapped again", () => {
    renderHome();
    choose(
      input("choose-file-input"),
      new File([new Uint8Array([1])], "a.gif", { type: "image/gif" }),
    );
    expect(screen.getByRole("alert")).not.toBeEmptyDOMElement();
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it.each([
    ["a GIF", new File([new Uint8Array([1])], "a.gif", { type: "image/gif" })],
    ["an empty file", new File([], "a.jpg", { type: "image/jpeg" })],
  ])("refuses %s with the reason, and sends nothing", (_, file) => {
    const onFile = renderHome();
    choose(input("choose-file-input"), file);
    expect(onFile).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).not.toBeEmptyDOMElement();
  });

  it("refuses a file over 4 MB", () => {
    const onFile = renderHome();
    const big = new File([new Uint8Array([1])], "big.pdf", {
      type: "application/pdf",
    });
    Object.defineProperty(big, "size", { value: 4 * 1024 * 1024 + 1 });
    choose(input("choose-file-input"), big);
    expect(onFile).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      strings.fileRefused.tooLarge,
    );
  });

  it("ignores a picker closed without a choice", () => {
    const onFile = renderHome();
    fireEvent.change(input("choose-file-input"), { target: { files: [] } });
    expect(onFile).not.toHaveBeenCalled();
  });
});
