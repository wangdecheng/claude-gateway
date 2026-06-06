import { cn } from "@/lib/utils/cn";
import { forwardRef } from "react";

interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  error?: boolean;
}

const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={cn(
          "flex min-h-[80px] w-full rounded-md border bg-neutral-surface px-3 py-2 text-sm transition-colors placeholder:text-neutral-text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-subtle focus-visible:border-primary-light disabled:cursor-not-allowed disabled:opacity-50",
          error
            ? "border-[#dc2626] focus-visible:ring-0 focus-visible:border-[#dc2626]"
            : "border-neutral-border",
          className
        )}
        {...props}
      />
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
