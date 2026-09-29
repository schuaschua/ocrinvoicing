import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { setShortcutsEnabled, useShortcutsEnabled } from "@/shell/shortcuts";
import { strings } from "@/strings";

/**
 * Story 2.11: the switch that turns the keyboard shortcuts on for this browser. A
 * button with the switch role, so it meets the 48px tap target like the others.
 */
export function ShortcutsToggle({ className }: { className?: string }) {
  const on = useShortcutsEnabled();
  return (
    <Button
      type="button"
      variant="ghost"
      role="switch"
      aria-checked={on}
      className={cn("shrink-0 gap-2", className)}
      onClick={() => setShortcutsEnabled(!on)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "relative inline-block h-5 w-9 shrink-0 rounded-full border border-ring",
          on ? "bg-primary" : "bg-background",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 left-0.5 size-3.5 rounded-full",
            on ? "translate-x-4 bg-primary-foreground" : "bg-ring",
          )}
        />
      </span>
      {strings.shortcuts.toggle}
    </Button>
  );
}
