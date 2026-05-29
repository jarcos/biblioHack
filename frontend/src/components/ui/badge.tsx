import { type VariantProps, cva } from "class-variance-authority";
import type { HTMLAttributes, ReactElement } from "react";

import { cn } from "@/lib/utils";

/**
 * Badge — small status pill. We carry one variant per
 * `AvailabilityStatus` so a catalog UI can write:
 *
 *   <Badge variant="available">Available</Badge>
 *   <Badge variant="loaned">Loaned · returns 12 Jun</Badge>
 *
 * Status variants use background-tint + same-hue foreground so they
 * read calmly in long lists. Neutral variants (default / outline)
 * are for non-status uses (counts, tags).
 */
const badgeVariants = cva(
  "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        outline: "border-border text-foreground",
        available: "border-transparent bg-status-available/15 text-status-available",
        loaned: "border-transparent bg-status-loaned/15 text-status-loaned",
        reserved: "border-transparent bg-status-reserved/15 text-status-reserved",
        unavailable: "border-transparent bg-status-unavailable/15 text-status-unavailable",
        unknown: "border-transparent bg-status-unknown/15 text-status-unknown",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps): ReactElement {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };
