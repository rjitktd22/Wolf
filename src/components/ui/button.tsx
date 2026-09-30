import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 font-medium select-none whitespace-nowrap rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:pointer-events-none disabled:opacity-40 transition-[background-color,color,opacity,transform] duration-150 ease-out active:not-disabled:scale-[0.97]",
  {
    variants: {
      variant: {
        primary: "bg-accent text-accent-fg hover:bg-fg",
        ghost: "bg-transparent text-muted hover:text-fg hover:bg-surface-2",
        outline: "bg-transparent text-fg shadow-[var(--shadow-border)] hover:bg-surface-2",
        buy: "bg-buy/15 text-buy hover:bg-buy/25",
        sell: "bg-sell/15 text-sell hover:bg-sell/25",
      },
      size: {
        sm: "h-10 min-h-10 px-3 text-sm",
        md: "h-11 min-h-11 px-4 text-sm",
        icon: "size-11",
      },
    },
    defaultVariants: { variant: "ghost", size: "sm" },
  },
);

export const Button = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>
>(({ className, variant, size, ...props }, ref) => (
  <button ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />
));
Button.displayName = "Button";
