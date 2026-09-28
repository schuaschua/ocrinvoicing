import type { MouseEvent } from "react";

import { cn } from "@/lib/utils";
import { navigate } from "@/router";
import { strings } from "@/strings";
import type { Surface } from "@/surfaces";

/** True when `active` is `item` or a page reached from it (e.g. an admin item). */
function isCurrent(item: Surface, active: Surface | null): boolean {
  return (
    active !== null &&
    (active.id === item.id || active.path.startsWith(`${item.path}/`))
  );
}

/**
 * The role-filtered sidebar navigation (UX-DR8): only the surfaces the user may use,
 * the others hidden, not disabled. Real links, so they work by keyboard, open in a new
 * tab and read correctly to a screen reader.
 */
export function Nav({
  items,
  active,
  onNavigate,
}: {
  items: readonly Surface[];
  active: Surface | null;
  onNavigate?: () => void;
}) {
  function follow(event: MouseEvent<HTMLAnchorElement>, path: string) {
    // A modified click keeps the browser's own behaviour (new tab, new window).
    if (
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    event.preventDefault();
    navigate(path);
    onNavigate?.();
  }

  return (
    <nav aria-label={strings.nav.label}>
      <ul className="flex flex-col gap-1">
        {items.map((item) => {
          const current = isCurrent(item, active);
          return (
            <li key={item.id}>
              <a
                href={item.path}
                aria-current={current ? "page" : undefined}
                onClick={(event) => follow(event, item.path)}
                className={cn(
                  "flex min-h-tap-min items-center rounded-md px-3 text-sm font-medium hover:bg-accent hover:text-accent-foreground",
                  current &&
                    "border-l-4 border-primary bg-secondary font-semibold text-secondary-foreground",
                )}
              >
                {strings.surfaces[item.id]}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
