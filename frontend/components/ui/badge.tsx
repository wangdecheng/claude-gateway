import { cn } from "@/lib/utils/cn";

export type BadgeVariant = "success" | "warning" | "error" | "muted";

const variantStyles: Record<BadgeVariant, string> = {
  success: "bg-[#dcfce7] text-[#16a34a]",
  warning: "bg-[#fff7ed] text-[#ea580c]",
  error: "bg-[#fef2f2] text-[#dc2626]",
  muted: "bg-neutral-bg text-neutral-text-muted",
};

interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

export function Badge({ variant = "muted", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-1.5 py-0.5 text-xs font-medium",
        variantStyles[variant],
        className
      )}
      {...props}
    />
  );
}
