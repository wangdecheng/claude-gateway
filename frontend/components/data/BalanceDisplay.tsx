import { cn } from "@/lib/utils/cn";
import { formatPrice } from "@/lib/utils/format";

interface BalanceDisplayProps {
  balance: number; // in cents
  className?: string;
}

export function BalanceDisplay({ balance, className }: BalanceDisplayProps) {
  const isLow = balance > 0 && balance < 500; // < ¥5
  const isZero = balance <= 0;

  return (
    <span
      className={cn(
        "font-mono text-[2rem] font-bold leading-tight",
        isZero && "text-[#dc2626]",
        isLow && "text-[#ea580c]",
        !isLow && !isZero && "text-neutral-text-primary",
        className
      )}
    >
      {formatPrice(balance)}
    </span>
  );
}
