import { Slot } from "radix-ui";
import * as React from "react";

import { cn } from "@/lib/utils";

import { Spinner } from "./spinner";

const variants = {
  primary:
    "bg-primary text-on-primary hover:bg-primary-hover border border-primary hover:border-primary-hover shadow-[inset_0_1px_0_rgb(255_255_255/0.08)]",
  amber: "bg-amber text-on-amber hover:bg-amber-hover border border-amber hover:border-amber-hover",
  outline: "border border-ink/80 text-ink hover:bg-ink hover:text-bg dark:border-line-strong dark:hover:border-ink",
  subtle: "border border-line bg-elevated text-ink hover:border-line-strong hover:bg-sunken",
  ghost: "text-ink-2 hover:text-ink hover:bg-sunken border border-transparent",
  danger: "border border-err/60 text-err hover:bg-err hover:text-white hover:border-err",
  link: "text-ink underline underline-offset-4 decoration-line-strong hover:decoration-ink border-0 px-0 h-auto",
} as const;

const sizes = {
  sm: "h-8 px-3 text-[13px] gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
  lg: "h-12 px-6 text-[15px] gap-2.5",
  icon: "h-9 w-9 p-0",
  "icon-sm": "h-8 w-8 p-0",
} as const;

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: keyof typeof variants;
  size?: keyof typeof sizes;
  asChild?: boolean;
  loading?: boolean;
  mono?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "primary", size = "md", asChild, loading, mono, disabled, children, ...props },
  ref,
) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      ref={ref}
      className={cn(
        "relative inline-flex select-none items-center justify-center whitespace-nowrap rounded-[3px] font-medium transition-[background-color,border-color,color,transform,box-shadow] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-50",
        mono && "font-mono text-[12.5px] tracking-[0.02em]",
        variants[variant],
        sizes[size],
        className,
      )}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          {loading && (
            <span className="absolute inset-0 grid place-items-center">
              <Spinner className="h-4 w-4" />
            </span>
          )}
          <span className={cn("inline-flex items-center gap-[inherit]", loading && "invisible")}>{children}</span>
        </>
      )}
    </Comp>
  );
});
