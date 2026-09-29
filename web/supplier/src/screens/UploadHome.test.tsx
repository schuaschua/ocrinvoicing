import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { UploadHome } from "@/screens/UploadHome";
import { strings } from "@/strings";

function input(testId: "take-photo-input" | "choose-file-input") {
  return screen.getByTestId(testId) as HTMLInputElement;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("1.8 choosing or taking the invoice", () => {
  it("opens the camera or picker, hints when no camera is listed, and refuses what it can't send", async () => {
    // A browser that lists no camera (permission denied, or an in-app browser).
    vi.stubGlobal("navigator", {
      ...navigator,
      mediaDevices: {
        enumerateDevices: async () => [{ kind: "audioinput" }],
      },
    });
    const onFile = vi.fn();
    render(<UploadHome supplierName="<b>Evil</b> Co" onFile={onFile} />);
    await act(async () => {});
    // A name is text, never markup.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Uploading for <b>Evil</b> Co",
    );

    const hint =
      "Camera not available here. Tap Choose file to pick a photo, or open this link in your phone's browser.";
    const takePhoto = screen.getByRole("button", { name: "Take photo" });
    expect(takePhoto).toHaveAccessibleDescription(hint);
    expect(takePhoto).toHaveClass("min-h-capture", "w-full");
    expect(input("take-photo-input")).toHaveAttribute("capture", "environment");
    const camera = vi.spyOn(input("take-photo-input"), "click");
    fireEvent.click(takePhoto);
    expect(camera).toHaveBeenCalledTimes(1);

    const picker = vi.spyOn(input("choose-file-input"), "click");
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    expect(picker).toHaveBeenCalledTimes(1);

    fireEvent.change(input("choose-file-input"), {
      target: {
        files: [
          new File([new Uint8Array([1])], "a.gif", { type: "image/gif" }),
        ],
      },
    });
    expect(onFile).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(
      strings.fileRefused.wrongType,
    );
    fireEvent.click(screen.getByRole("button", { name: "Choose file" }));
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();

    const photo = new File([new Uint8Array([0xff, 0xd8, 0xff])], "inv.jpg", {
      type: "image/jpeg",
    });
    fireEvent.change(input("take-photo-input"), { target: { files: [photo] } });
    expect(onFile).toHaveBeenCalledWith(photo, "camera");
    // Cleared, so the same file can be chosen again.
    expect(input("take-photo-input").value).toBe("");
  });
});
