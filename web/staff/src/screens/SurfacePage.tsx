import { pageTitle, strings } from "@/strings";
import type { Surface } from "@/surfaces";

import { usePageHeading } from "./usePageHeading";

/**
 * A surface's page. Each screen story replaces its placeholder body; until then the
 * page has its title and its heading. The "Not allowed" alert after a refused route
 * is the shell's live region (App.tsx).
 */
export function SurfacePage({ surface }: { surface: Surface }) {
  const title = strings.surfaces[surface.id];
  const heading = usePageHeading(pageTitle(title));
  return (
    <div className="flex flex-col gap-4">
      <h1 ref={heading} tabIndex={-1} className="text-xl font-semibold">
        {title}
      </h1>
      <p className="text-muted-foreground">{strings.placeholder}</p>
    </div>
  );
}
