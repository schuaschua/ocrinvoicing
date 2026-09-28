import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tailwind-merge only knows Tailwind's default scales: without the DESIGN.md spacing
// tokens (src/index.css) it kept both `min-h-tap-min` and `min-h-capture`, and the
// stylesheet's order, not the caller, decided which one won.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { spacing: ["tap-min", "supplier-gutter", "capture", "header"] },
  },
});

/** shadcn/ui's class helper: conditional classes, later Tailwind classes win. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
