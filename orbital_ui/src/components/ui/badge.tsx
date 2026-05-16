import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border border-transparent px-2 py-0.5 text-xs font-medium font-mono",
  {
    variants: {
      variant: {
        default: "bg-slate-700 text-slate-100",
        action: "bg-red-950 text-red-300 border-red-800",
        watch: "bg-amber-950 text-amber-200 border-amber-800",
        noise: "bg-slate-800 text-slate-400",
        success: "bg-emerald-950 text-emerald-300",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps): React.ReactElement {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
