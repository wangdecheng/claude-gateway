"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useCreateOrder } from "@/lib/api/payment";
import { apiClient, ApiClientError } from "@/lib/api/client";
import { formatPrice } from "@/lib/utils/format";

const PAYMENT_METHODS = [
  { value: "alipay" as const, label: "支付宝" },
  { value: "wechat" as const, label: "微信支付" },
];

const QUICK_AMOUNTS = [
  { label: "¥10", value: 1000 },
  { label: "¥50", value: 5000 },
  { label: "¥100", value: 10000 },
];

const MIN_AMOUNT = 100;   // ¥1.00
const MAX_AMOUNT = 500000; // ¥5,000.00

interface RechargeFormProps {
  onSuccess?: (amount: number) => void;
}

/** Safely convert a yuan string to cents (integer), avoiding IEEE 754 drift. */
function yuanToCents(yuan: string): number {
  // Multiply by 100 as string arithmetic to avoid floating-point drift
  const trimmed = yuan.trim();
  const dot = trimmed.indexOf(".");
  if (dot === -1) return parseInt(trimmed, 10) * 100;
  const intPart = trimmed.substring(0, dot);
  let fracPart = trimmed.substring(dot + 1);
  // Pad or truncate to exactly 2 decimal places
  if (fracPart.length === 0) return parseInt(intPart, 10) * 100;
  if (fracPart.length === 1) fracPart = fracPart + "0";
  else fracPart = fracPart.substring(0, 2);
  // Remove leading zeros from intPart for parseInt
  const cents = parseInt(intPart, 10) * 100 + parseInt(fracPart, 10);
  return isNaN(cents) ? 0 : cents;
}

export function RechargeForm({ onSuccess }: RechargeFormProps) {
  const queryClient = useQueryClient();
  const [customAmount, setCustomAmount] = useState("");
  const [selectedQuick, setSelectedQuick] = useState<number | null>(5000);
  const [method, setMethod] = useState<"alipay" | "wechat">("alipay");
  const [error, setError] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);
  const [orderResult, setOrderResult] = useState<{
    orderId: number;
    payUrl: string;
    amount: number;
  } | null>(null);

  const createOrder = useCreateOrder();

  const useCustom = customAmount.trim() !== "";
  const amount = useCustom ? yuanToCents(customAmount) : (selectedQuick ?? 0);

  // Validation
  const amountError = (() => {
    if (!useCustom) return "";
    const n = parseFloat(customAmount);
    if (isNaN(n) || n <= 0) return "请输入有效金额";
    if (n < 1) return `充值金额不能低于 ¥1.00`;
    if (n > 5000) return `充值金额不能超过 ¥5,000.00`;
    return "";
  })();

  const canSubmit = amount >= MIN_AMOUNT && amount <= MAX_AMOUNT && !amountError;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!canSubmit) return;

    try {
      const result = await createOrder.mutateAsync({
        amount,
        method,
      });
      setOrderResult({
        orderId: result.orderId,
        payUrl: result.payUrl,
        amount: result.amount,
      });
      setShowConfirm(true);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("创建订单失败，请稍后重试");
      }
    }
  };

  const handleConfirmPayment = async () => {
    if (!orderResult) return;

    try {
      // V1: Simulated payment — call the callback endpoint
      const url = new URL(orderResult.payUrl, window.location.origin);
      await apiClient(url.pathname + url.search);

      // Success — reset form and refresh data
      setShowConfirm(false);
      setOrderResult(null);
      setCustomAmount("");
      setSelectedQuick(5000);
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      queryClient.invalidateQueries({ queryKey: ["payment", "history"] });
      onSuccess?.(orderResult.amount);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("支付失败，请稍后重试");
      }
      setShowConfirm(false);
    }
  };

  const handleCancelPayment = () => {
    setShowConfirm(false);
    setOrderResult(null);
  };

  return (
    <>
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Quick Amount Buttons */}
        <div>
          <label className="block text-sm font-medium text-neutral-text-primary mb-3">
            快捷金额
          </label>
          <div className="flex gap-3">
            {QUICK_AMOUNTS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                disabled={createOrder.isPending}
                onClick={() => {
                  setSelectedQuick(opt.value);
                  setCustomAmount("");
                  setError("");
                }}
                className={`flex-1 h-12 rounded-md font-mono text-lg font-medium border transition-colors
                  ${!useCustom && selectedQuick === opt.value
                    ? "border-[#1e40af] bg-blue-50 text-[#1e40af]"
                    : "border-neutral-border hover:border-neutral-text-muted text-neutral-text-primary"
                  }
                  disabled:opacity-50 disabled:cursor-not-allowed
                `}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Custom Amount */}
        <div>
          <label
            htmlFor="custom-amount"
            className="block text-sm font-medium text-neutral-text-primary mb-2"
          >
            自定义金额
          </label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-neutral-text-secondary font-mono">
              ¥
            </span>
            <input
              id="custom-amount"
              type="number"
              min="1"
              max="5000"
              step="0.01"
              value={customAmount}
              onChange={(e) => {
                setCustomAmount(e.target.value);
                if (e.target.value) setSelectedQuick(null);
                if (error) setError("");
              }}
              onFocus={() => {
                setSelectedQuick(null);
              }}
              placeholder="输入金额"
              disabled={createOrder.isPending}
              className="w-full h-10 pl-8 pr-3 rounded-md border border-neutral-border
                         font-mono text-sm
                         focus:outline-none focus:ring-2 focus:ring-primary-light focus:border-transparent
                         placeholder:text-neutral-text-muted
                         disabled:opacity-50 disabled:cursor-not-allowed"
            />
          </div>
          {amountError && (
            <p className="text-sm text-[#dc2626] mt-1" role="alert">
              {amountError}
            </p>
          )}
        </div>

        {/* Payment Method */}
        <div>
          <label className="block text-sm font-medium text-neutral-text-primary mb-3">
            支付方式
          </label>
          <div className="flex gap-4">
            {PAYMENT_METHODS.map((pm) => (
              <label
                key={pm.value}
                className={`flex items-center gap-2 px-4 py-3 rounded-md border cursor-pointer transition-colors
                  ${method === pm.value
                    ? "border-[#1e40af] bg-blue-50"
                    : "border-neutral-border hover:border-neutral-text-muted"
                  }
                  ${createOrder.isPending ? "opacity-50 cursor-not-allowed" : ""}
                `}
              >
                <input
                  type="radio"
                  name="method"
                  value={pm.value}
                  checked={method === pm.value}
                  onChange={() => setMethod(pm.value)}
                  disabled={createOrder.isPending}
                  className="sr-only"
                />
                <span className="text-sm font-medium text-neutral-text-primary">
                  {pm.label}
                </span>
              </label>
            ))}
          </div>
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={!canSubmit || createOrder.isPending}
          className="w-full h-12 rounded-md font-medium text-white
                     bg-[#1e40af] hover:bg-blue-800
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors text-base"
        >
          {createOrder.isPending
            ? "创建订单中..."
            : `确认支付 ${formatPrice(amount)}`}
        </button>

        {error && (
          <p className="text-sm text-[#dc2626]" role="alert">
            {error}
          </p>
        )}
      </form>

      {/* Confirmation Modal (V1: Simulated Payment) */}
      {showConfirm && orderResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/40"
            onClick={handleCancelPayment}
          />
          <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-sm mx-4">
            <h3 className="text-lg font-semibold mb-4">确认支付</h3>
            <div className="space-y-3 mb-6">
              <div className="flex justify-between text-sm">
                <span className="text-neutral-text-secondary">金额</span>
                <span className="font-mono font-medium">
                  {formatPrice(orderResult.amount)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-neutral-text-secondary">支付方式</span>
                <span className="font-medium">
                  {PAYMENT_METHODS.find((m) => m.value === method)?.label || method}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-neutral-text-secondary">订单号</span>
                <span className="font-mono text-xs">{orderResult.orderId}</span>
              </div>
              <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded-md">
                <p className="text-xs text-amber-700">
                  🧪 V1 模拟支付模式 — 点击确认后将直接完成支付
                </p>
              </div>
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleCancelPayment}
                className="flex-1 h-10 rounded-md border border-neutral-border
                           font-medium text-sm text-neutral-text-primary
                           hover:bg-neutral-bg transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleConfirmPayment}
                className="flex-1 h-10 rounded-md font-medium text-sm text-white
                           bg-[#1e40af] hover:bg-blue-800
                           transition-colors"
              >
                确认支付（模拟）
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
