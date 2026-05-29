import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Conditional + de-duplicating class-name composer used by every shadcn-
 * style primitive. `clsx` handles arrays / objects / falsy values, then
 * `tailwind-merge` resolves conflicting Tailwind utilities (so the
 * caller's `text-red-500` overrides the component's default `text-foreground`).
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
