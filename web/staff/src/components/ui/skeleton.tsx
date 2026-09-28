import type * as React from "react";

import { cn } from "@/lib/utils";

// shadcn/ui Skeleton. The pulse runs only when the user allows motion.
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "rounded-md bg-accent motion-safe:animate-pulse",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
