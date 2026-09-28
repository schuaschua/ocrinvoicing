import { useEffect, useRef } from "react";

/**
 * Each screen sets its own page title and, when it appears, moves focus to its h1
 * (EXPERIENCE.md "Accessibility Floor": routes). Put the ref on the h1 with tabIndex -1.
 */
export function usePageHeading(title: string) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = title;
    heading.current?.focus();
  }, [title]);
  return heading;
}
