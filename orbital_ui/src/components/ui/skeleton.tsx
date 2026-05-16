import * as React from "react";

import { cn } from "@/lib/utils";

function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>): React.ReactElement {
  return (
    <div
      className={cn(
        "min-h-[1rem] animate-pulse rounded-md bg-slate-800/80",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
