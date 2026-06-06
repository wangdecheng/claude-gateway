"use client";

import { useState } from "react";
import { useRedeem } from "@/lib/api/redemption";
import { ApiClientError } from "@/lib/api/client";

export function RedemptionInput() {
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  const redeem = useRedeem();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessMessage("");

    const trimmed = code.trim();
    if (!trimmed) {
      setError("请输入兑换码");
      return;
    }

    try {
      const result = await redeem.mutateAsync({ code: trimmed });
      setSuccessMessage(result.message);
      setCode("");
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("兑换失败，请稍后重试");
      }
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setCode(e.target.value.toUpperCase());
    if (error) setError("");
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3">
      <div className="flex gap-3">
        <input
          type="text"
          value={code}
          onChange={handleChange}
          placeholder="REDM-XXXX-XXXX-XXXX"
          className="flex-1 h-10 px-3 rounded-md border border-neutral-border
                     font-mono text-sm uppercase tracking-wider
                     focus:outline-none focus:ring-2 focus:ring-primary-light focus:border-transparent
                     placeholder:text-neutral-text-muted"
          disabled={redeem.isPending}
          autoComplete="off"
        />
        <button
          type="submit"
          disabled={redeem.isPending}
          className="h-10 px-6 rounded-md font-medium text-white
                     bg-[#1e40af] hover:bg-blue-800
                     disabled:opacity-50 disabled:cursor-not-allowed
                     transition-colors"
        >
          {redeem.isPending ? "兑换中..." : "兑换"}
        </button>
      </div>

      {error && (
        <p className="text-sm text-[#dc2626]" role="alert">
          {error}
        </p>
      )}

      {successMessage && (
        <p className="text-sm text-[#16a34a]" role="status">
          {successMessage}
        </p>
      )}
    </form>
  );
}
