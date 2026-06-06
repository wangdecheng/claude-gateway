import { cn } from "@/lib/utils/cn";
import { forwardRef } from "react";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  variant?: "default" | "mono";
  error?: boolean;
}

const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, variant = "default", error, ...props }, ref) => {
    return (
      <input
        ref={ref}
        className={cn(
          "flex h-10 w-full rounded-md border bg-neutral-surface px-3 text-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-neutral-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-subtle focus-visible:border-primary-light disabled:cursor-not-allowed disabled:opacity-50",
          error
            ? "border-[#dc2626] focus-visible:ring-0 focus-visible:border-[#dc2626]"
            : "border-neutral-border",
          variant === "mono" && "font-mono",
          className
        )}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
