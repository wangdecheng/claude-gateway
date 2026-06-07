"use client";

import { useState } from "react";
import { Copy, Ticket } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiClientError } from "@/lib/api/client";
import {
  useCreateAdminRedemptionCode,
  type AdminRedemptionCreateResult,
} from "@/lib/api/admin/redemption";
import { formatDate, formatPrice } from "@/lib/utils/format";

export default function AdminRedemptionPage() {
  const createMutation = useCreateAdminRedemptionCode();
  const [amountYuan, setAmountYuan] = useState("");
  const [expiresInDays, setExpiresInDays] = useState("5");
  const [result, setResult] = useState<AdminRedemptionCreateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setCopied(false);

    const amount = Math.round(Number(amountYuan) * 100);
    if (!Number.isFinite(amount) || amount <= 0) {
      setError("请输入大于 0 的金额");
      return;
    }

    const validDays = Number(expiresInDays);
    if (!Number.isInteger(validDays) || validDays <= 0) {
      setError("有效天数必须为正整数");
      return;
    }

    try {
      const data = await createMutation.mutateAsync({
        amount,
        expiresInDays: validDays,
      });
      setResult(data);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.message);
      } else {
        setError("生成失败，请重试");
      }
    }
  };

  const handleCopy = async () => {
    if (!result) return;
    await navigator.clipboard.writeText(result.code);
    setCopied(true);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-neutral-text-primary">
          兑换码管理
        </h1>
        <p className="mt-1 text-sm text-neutral-text-secondary">
          生成一次性余额兑换码，完整兑换码只在生成后显示一次
        </p>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-6">
        <form onSubmit={handleSubmit} className="grid gap-5 md:grid-cols-[1fr_180px_auto]">
          <div className="space-y-2">
            <Label htmlFor="amount">金额</Label>
            <Input
              id="amount"
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              value={amountYuan}
              onChange={(event) => setAmountYuan(event.target.value)}
              placeholder="例如 10.00"
              disabled={createMutation.isPending}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="expiresInDays">有效天数</Label>
            <Input
              id="expiresInDays"
              type="number"
              min="1"
              step="1"
              value={expiresInDays}
              onChange={(event) => setExpiresInDays(event.target.value)}
              disabled={createMutation.isPending}
            />
          </div>

          <div className="flex items-end">
            <Button type="submit" disabled={createMutation.isPending}>
              <Ticket className="h-4 w-4" />
              {createMutation.isPending ? "生成中..." : "生成兑换码"}
            </Button>
          </div>
        </form>

        {error && (
          <div className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-600" role="alert">
            {error}
          </div>
        )}
      </div>

      {result && (
        <div className="rounded-lg border border-slate-200 bg-white p-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="text-lg font-semibold text-neutral-text-primary">
                生成成功
              </h2>
              <p className="mt-1 text-sm text-neutral-text-secondary">
                请现在复制并交给用户，后台不会再次显示完整兑换码
              </p>
            </div>
            <Button variant="secondary" onClick={handleCopy}>
              <Copy className="h-4 w-4" />
              {copied ? "已复制" : "复制兑换码"}
            </Button>
          </div>

          <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-4">
            <div className="break-all font-mono text-lg font-semibold tracking-wide text-neutral-text-primary">
              {result.code}
            </div>
          </div>

          <dl className="mt-5 grid gap-4 text-sm md:grid-cols-3">
            <div>
              <dt className="text-neutral-text-secondary">金额</dt>
              <dd className="mt-1 font-medium text-neutral-text-primary">
                {formatPrice(result.amount)}
              </dd>
            </div>
            <div>
              <dt className="text-neutral-text-secondary">状态</dt>
              <dd className="mt-1 font-medium text-neutral-text-primary">
                {result.status === "issued" ? "未使用" : result.status}
              </dd>
            </div>
            <div>
              <dt className="text-neutral-text-secondary">过期时间</dt>
              <dd className="mt-1 font-medium text-neutral-text-primary">
                {formatDate(result.expiresAt)}
              </dd>
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
