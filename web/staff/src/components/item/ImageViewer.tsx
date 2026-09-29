import { useState } from "react";

import { itemImageUrl } from "@/api/item";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useShortcuts } from "@/shell/shortcuts";
import { strings } from "@/strings";

import type { FlagBox } from "./boxes";
import { useReducedMotion } from "./useReducedMotion";

/** A view of the image: scale from 1 (whole), and the stage's offset as a fraction of
 * the viewport (0 to 1 - scale), so the invoice always fills it. */
export interface View {
  scale: number;
  x: number;
  y: number;
}

export const WHOLE: View = { scale: 1, x: 0, y: 0 };
const MAX_SCALE = 6;
const ZOOM_STEP = 1.5;
/** A pan button moves a quarter of the viewport. */
const PAN_STEP = 0.25;
/** A box fills at most this share of the viewport when zoomed to. */
const BOX_SHARE = 0.6;
// DESIGN.md field-flag-box: a 2px stroke, 4px when selected, and a 1px halo, on
// screen whatever the zoom.
const STROKE_PX = 2;
const SELECTED_STROKE_PX = 4;
const HALO_PX = 1;

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

function fit(scale: number, x: number, y: number): View {
  const s = clamp(scale, 1, MAX_SCALE);
  return { scale: s, x: clamp(x, 1 - s, 0), y: clamp(y, 1 - s, 0) };
}

/** Zoomed so `box` sits in the middle, filling at most 60 % of the viewport. */
export function zoomTo(box: FlagBox): View {
  const scale = clamp(
    Math.min(
      BOX_SHARE / Math.max(box.width, 1e-3),
      BOX_SHARE / Math.max(box.height, 1e-3),
    ),
    1,
    MAX_SCALE,
  );
  const cx = box.left + box.width / 2;
  const cy = box.top + box.height / 2;
  return fit(scale, 0.5 - scale * cx, 0.5 - scale * cy);
}

function zoomBy(view: View, factor: number): View {
  // Around the middle of the viewport.
  const cx = (0.5 - view.x) / view.scale;
  const cy = (0.5 - view.y) / view.scale;
  const scale = clamp(view.scale * factor, 1, MAX_SCALE);
  return fit(scale, 0.5 - scale * cx, 0.5 - scale * cy);
}

function pan(view: View, dx: number, dy: number): View {
  return fit(view.scale, view.x + dx * PAN_STEP, view.y + dy * PAN_STEP);
}

interface ImageViewerProps {
  invoiceId: string;
  contentType: string;
  imageAvailable: boolean;
  boxes: FlagBox[];
  selected: string | null;
  /** Changes on every selection, so choosing the same field again zooms back to it. */
  selectionKey: number;
  onStep: (fieldId: string, position: number) => void;
  onSelectBox: (fieldId: string) => void;
}

/**
 * The invoice image (EXPERIENCE.md Image viewer, UX-DR10): it opens zoomed to the
 * selected flag box (the first one at first); Previous and Next step between flags,
 * Show whole invoice zooms out, and zoom and pan have buttons, so nothing needs a
 * drag (WCAG 2.5.7). The boxes are hidden from assistive technology: every box has
 * its field in the list. No zoom animation under reduced motion. A PDF is opened by
 * link, with no boxes.
 */
export function ImageViewer({
  invoiceId,
  contentType,
  imageAvailable,
  boxes,
  selected,
  selectionKey,
  onStep,
  onSelectBox,
}: ImageViewerProps) {
  const reducedMotion = useReducedMotion();
  const [failed, setFailed] = useState(false);
  // The admin's own zoom and pan, kept until the next selection.
  const [manual, setManual] = useState<{ key: number; view: View } | null>(
    null,
  );
  const url = itemImageUrl(invoiceId);
  const target = boxes.find((box) => box.fieldId === selected) ?? null;
  const index = target === null ? -1 : boxes.indexOf(target);

  function step(delta: number) {
    if (boxes.length === 0) return;
    const next =
      index === -1
        ? delta > 0
          ? 0
          : boxes.length - 1
        : (index + delta + boxes.length) % boxes.length;
    const box = boxes[next];
    if (box !== undefined) onStep(box.fieldId, next + 1);
  }

  // Story 2.11: Previous and Next flag's handler, only while those buttons work.
  const stepping =
    imageAvailable && contentType !== "application/pdf" && boxes.length > 0;
  useShortcuts({
    n: stepping ? () => step(1) : undefined,
    p: stepping ? () => step(-1) : undefined,
  });

  if (!imageAvailable) {
    return (
      <div className="flex min-h-40 items-center justify-center rounded-md bg-muted p-4">
        <p>{strings.item.viewer.deleted}</p>
      </div>
    );
  }
  if (contentType === "application/pdf") {
    return (
      <div className="flex flex-col items-start gap-2 rounded-md bg-muted p-4">
        <Button asChild variant="outline">
          <a href={url} target="_blank" rel="noopener">
            {strings.item.viewer.openPdf}
          </a>
        </Button>
        <p className="text-sm">{strings.item.viewer.pdfNote}</p>
      </div>
    );
  }

  const view =
    manual !== null && manual.key === selectionKey
      ? manual.view
      : target !== null
        ? zoomTo(target)
        : WHOLE;

  function change(next: View) {
    setManual({ key: selectionKey, view: next });
  }

  const v = strings.item.viewer;
  return (
    <section aria-label={v.label} className="flex flex-col gap-2">
      {boxes.length === 0 ? <p className="text-sm">{v.noBoxes}</p> : null}
      <div
        role="group"
        aria-label={v.controls}
        className="flex flex-wrap items-center gap-2"
      >
        <Button
          type="button"
          variant="outline"
          disabled={boxes.length === 0}
          onClick={() => step(-1)}
        >
          {v.previous}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={boxes.length === 0}
          onClick={() => step(1)}
        >
          {v.next}
        </Button>
        <p className="numeric text-sm">
          {boxes.length === 0
            ? v.noFlags
            : index === -1
              ? v.noSelection(boxes.length)
              : v.position(index + 1, boxes.length)}
        </p>
        <Button type="button" variant="outline" onClick={() => change(WHOLE)}>
          {v.whole}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => change(zoomBy(view, ZOOM_STEP))}
        >
          {v.zoomIn}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => change(zoomBy(view, 1 / ZOOM_STEP))}
        >
          {v.zoomOut}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => change(pan(view, 1, 0))}
        >
          {v.panLeft}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => change(pan(view, -1, 0))}
        >
          {v.panRight}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => change(pan(view, 0, 1))}
        >
          {v.panUp}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => change(pan(view, 0, -1))}
        >
          {v.panDown}
        </Button>
      </div>
      <div
        className="relative overflow-hidden rounded-md bg-muted"
        data-testid="viewer"
      >
        <div
          data-testid="viewer-stage"
          className={cn(
            "relative origin-top-left",
            reducedMotion ? null : "transition-transform duration-200",
          )}
          style={{
            transform: `translate(${view.x * 100}%, ${view.y * 100}%) scale(${view.scale})`,
          }}
        >
          {failed ? (
            <div className="flex min-h-40 items-center justify-center p-4">
              <p>{v.failed}</p>
            </div>
          ) : (
            <img
              src={url}
              alt={v.imageAlt}
              draggable={false}
              className="block w-full select-none"
              onError={() => setFailed(true)}
            />
          )}
          {failed
            ? null
            : boxes.map((box) => {
                const isSelected = box.fieldId === selected;
                return (
                  <div
                    key={box.fieldId}
                    aria-hidden="true"
                    data-testid="flag-box"
                    data-selected={isSelected}
                    className="absolute cursor-pointer border-flag bg-flag-fill outline-flag-halo"
                    style={{
                      left: `${box.left * 100}%`,
                      top: `${box.top * 100}%`,
                      width: `${box.width * 100}%`,
                      height: `${box.height * 100}%`,
                      borderStyle: "solid",
                      borderWidth: `${(isSelected ? SELECTED_STROKE_PX : STROKE_PX) / view.scale}px`,
                      outlineStyle: "solid",
                      outlineWidth: `${HALO_PX / view.scale}px`,
                    }}
                    onClick={() => onSelectBox(box.fieldId)}
                  >
                    {/* The number is drawn by CSS, not text: the viewport clips the zoomed
                        image on purpose, and the field list carries the number. */}
                    <span
                      data-number={box.number}
                      className="numeric absolute bottom-full left-0 origin-bottom-left bg-flag px-1 text-xs text-flag-halo after:content-[attr(data-number)]"
                      style={{ transform: `scale(${1 / view.scale})` }}
                    />
                  </div>
                );
              })}
        </div>
      </div>
    </section>
  );
}
