import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex h-10 items-center justify-center gap-2 rounded-md px-4 text-sm font-medium transition disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-slate-950 text-white shadow-sm shadow-black/10 hover:bg-slate-800",
        secondary: "bg-blue-600 text-white shadow-sm shadow-blue-600/20 hover:bg-blue-500",
        outline: "border border-black/10 bg-white text-slate-700 hover:border-black/15 hover:bg-slate-50",
        ghost: "text-slate-600 hover:bg-black/[0.04] hover:text-slate-950",
      },
      size: {
        default: "h-10 px-4",
        icon: "h-9 w-9 px-0",
        sm: "h-8 px-3 text-xs",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
    },
  },
);

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>;

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
