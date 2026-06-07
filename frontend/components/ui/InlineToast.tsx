"use client";

import { useEffect } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils/cn";

export type InlineToastVariant = "success" | "error";

interface InlineToastProps {
  open: boolean;
  message: string;
  variant?: InlineToastVariant;
  duration?: number;
  onClose: () => void;
}

/**
 * Page-scoped floating notice. Renders a card in the top-right corner
 * and auto-dismisses after `duration` ms (default 2000).
 *
 * Intentionally lightweight — no portal, no provider, no Radix.
 * For app-wide toasts later, swap this out for a real Toaster.
 */
export function InlineToast({
  open,
  message,
  variant = "success",
  duration = 2000,
  onClose,
}: InlineToastProps) {
  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(onClose, duration);
    return () => clearTimeout(timer);
  }, [open, duration, onClose]);

  if (!open) return null;

  const Icon = variant === "success" ? CheckCircle2 : AlertCircle;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "fixed top-4 right-4 z-50 flex items-center gap-2 rounded-md border bg-white px-4 py-3 shadow-lg",
        "animate-in fade-in slide-in-from-top-2",
        variant === "success" ? "border-[#16a34a] text-[#15803d]" : "border-[#dc2626] text-[#b91c1c]"
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      <span className="text-sm font-medium">{message}</span>
    </div>
  );
}
